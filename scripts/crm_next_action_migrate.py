#!/usr/bin/env python3
"""
CRM 次アクション選択肢統合スクリプト: 87→10

商談テーブルの「次アクション」フィールドを87個の選択肢から10個に統合する。
旧値の情報は備考欄に保存。

Usage:
  python3 crm_next_action_migrate.py              # ドライラン（プレビューのみ）
  python3 crm_next_action_migrate.py --execute     # 本番実行
  python3 crm_next_action_migrate.py --check-only  # 現状確認のみ
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"
LARK_API_BASE = "https://open.larksuite.com/open-apis"

# ──────────────────────────────────────────────
# 統合マッピング
# ──────────────────────────────────────────────
NEW_OPTIONS = [
    "再訪問",
    "再訪問（帯同）",
    "電話フォロー",
    "メールフォロー",
    "提案・見積作成",
    "ウェブミーティング",
    "回答・連絡待ち",
    "未定",
    "アクション不要",
    "その他",
]

# 旧値 → 新値のマッピング（部分一致キーワードベース）
EXACT_MAP = {
    "再訪（営業担当者のみ）": "再訪問",
    "再訪（技術者・上長の帯同が必要）": "再訪問（帯同）",
    "電話フォロー": "電話フォロー",
    "メールフォロー": "メールフォロー",
    "状況確認電話": "電話フォロー",
    "フォロー電話": "電話フォロー",
    "後日電話": "電話フォロー",
    "見積提出": "提案・見積作成",
    "見積提示": "提案・見積作成",
    "提案資料作成": "提案・見積作成",
    "ウェブミーティング": "ウェブミーティング",
    "営業見込みなし": "アクション不要",
    "その他": "その他",
    "未定": "未定",
    "連絡待ち": "回答・連絡待ち",
    "調整中": "未定",
    "掘り起こしメール": "メールフォロー",
    "実績をメール送信": "メールフォロー",
    "なし": "アクション不要",
    "無し": "アクション不要",
    "無": "アクション不要",
    "なしふ": "アクション不要",  # typo
}

# キーワードベースの分類（EXACT_MAPに一致しない場合に使用）
KEYWORD_RULES = [
    # (キーワードリスト, 新値)
    (["再訪", "訪問", "アポ", "挨拶", "飛び込み", "向かう"], "再訪問"),
    (["電話", "テレアポ", "確認", "進捗", "商談", "連絡"], "電話フォロー"),
    (["メール", "送信"], "メールフォロー"),
    (["見積", "提案"], "提案・見積作成"),
    (["待ち", "可能があれば", "検討"], "回答・連絡待ち"),
    (["無し", "なし", "無い", "ない", "見込みなし", "依頼なし", "進捗なし",
      "ドローン測量なし"], "アクション不要"),
    (["機会があれば", "提案できるサービス"], "アクション不要"),
    (["下見", "現場"], "再訪問"),
]


def classify_action(old_value):
    """旧値を新カテゴリに分類"""
    if not old_value or old_value == "(未設定)":
        return None  # 未設定のまま

    # 完全一致
    if old_value in EXACT_MAP:
        return EXACT_MAP[old_value]

    # 複合値（カンマ区切り）
    if ", " in old_value:
        parts = [p.strip() for p in old_value.split(",")]
        classified = [EXACT_MAP.get(p) for p in parts if p in EXACT_MAP]
        if classified:
            return classified[0]  # 最初のマッチを使用

    # キーワードマッチ
    for keywords, new_value in KEYWORD_RULES:
        if any(kw in old_value for kw in keywords):
            return new_value

    # どれにも当てはまらない場合
    return "その他"


# ──────────────────────────────────────────────
# Lark API
# ──────────────────────────────────────────────
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def lark_get_token(config):
    data = json.dumps({
        "app_id": config["lark"]["app_id"],
        "app_secret": config["lark"]["app_secret"],
    }).encode()
    req = urllib.request.Request(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def lark_list_records(token, table_id, page_size=500):
    records = []
    page_token = None
    while True:
        url = (
            f"{LARK_API_BASE}/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                resp = json.loads(r.read())
                items = resp.get("data", {}).get("items", [])
                records.extend(items)
                if not resp.get("data", {}).get("has_more"):
                    break
                page_token = resp["data"].get("page_token")
        except Exception as e:
            print(f"[ERROR] Lark API: {e}")
            break
        time.sleep(0.3)
    return records


def lark_update_record(token, table_id, record_id, fields):
    url = (
        f"{LARK_API_BASE}/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return resp.get("code") == 0
    except Exception as e:
        print(f"  [ERROR] Lark update {record_id}: {e}")
        return False


def lark_get_field_info(token, table_id, field_name):
    """フィールド定義を取得"""
    url = f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/fields?page_size=100"
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
        fields = resp.get("data", {}).get("items", [])
    for field in fields:
        if field.get("field_name") == field_name:
            return field
    return None


def lark_update_field(token, table_id, field_id, new_options):
    """フィールド定義を更新（選択肢を変更）"""
    url = (
        f"{LARK_API_BASE}/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/fields/{field_id}"
    )
    body = {
        "property": {
            "options": [{"name": opt} for opt in new_options]
        }
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return resp.get("code") == 0
    except Exception as e:
        print(f"  [ERROR] Field update: {e}")
        return False


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                texts.append(item.get("text", "") or item.get("name", "") or "")
            elif item is not None:
                texts.append(str(item))
        return ", ".join(texts) if texts else ""
    if isinstance(value, dict):
        return value.get("text", "") or value.get("name", "") or ""
    return str(value) if value else ""


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def main():
    execute = "--execute" in sys.argv
    check_only = "--check-only" in sys.argv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print("  CRM 次アクション選択肢統合: 87 → 10")
    print(f"  モード: {'本番実行' if execute else 'チェックのみ' if check_only else 'ドライラン'}")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    config = load_config()
    token = lark_get_token(config)

    # 1. 全商談レコード取得
    print("\n[1/5] 商談レコード取得...")
    records = lark_list_records(token, DEAL_TABLE_ID)
    print(f"  全レコード: {len(records)}件")

    # 2. 現在の次アクション分布を確認
    print("\n[2/5] 次アクション分布分析...")
    old_counter = Counter()
    migration_plan = []

    for rec in records:
        fields = rec.get("fields", {})
        old_value = extract_text(fields.get("次アクション", ""))
        old_counter[old_value or "(未設定)"] += 1

        new_value = classify_action(old_value)

        if old_value and new_value and old_value != new_value:
            # 個別記述の情報は備考に追記
            should_save_memo = old_value not in EXACT_MAP
            migration_plan.append({
                "record_id": rec["record_id"],
                "old_value": old_value,
                "new_value": new_value,
                "save_to_memo": should_save_memo,
                "deal_name": extract_text(fields.get("商談名", ""))[:50],
                "existing_memo": extract_text(fields.get("備考", ""))[:100],
            })

    print(f"  旧選択肢の種類: {len(old_counter)}種")
    print(f"  変更対象レコード: {len(migration_plan)}件")
    print(f"  変更不要（未設定 or 新値と同一）: {len(records) - len(migration_plan)}件")

    # 3. 統合結果プレビュー
    print("\n[3/5] 統合結果プレビュー...")
    new_counter = Counter()
    for rec in records:
        fields = rec.get("fields", {})
        old_value = extract_text(fields.get("次アクション", ""))
        new_value = classify_action(old_value)
        new_counter[new_value or "(未設定)"] += 1

    print(f"\n  {'新カテゴリ':20s} | {'件数':>5s} | {'割合':>6s}")
    print(f"  {'-' * 20}-+-{'-' * 5}-+-{'-' * 6}")
    for cat in ["(未設定)"] + NEW_OPTIONS:
        count = new_counter.get(cat, 0)
        pct = count / len(records) * 100 if records else 0
        print(f"  {cat:20s} | {count:5d} | {pct:5.1f}%")

    # 変換詳細（上位30件）
    print(f"\n  --- 変換詳細（変更対象 {len(migration_plan)}件中、上位30件） ---")
    for i, m in enumerate(migration_plan[:30], 1):
        memo_tag = " [+備考]" if m["save_to_memo"] else ""
        print(f"  {i:3d}. {m['old_value'][:30]:30s} → {m['new_value']:15s}{memo_tag}")
    if len(migration_plan) > 30:
        print(f"  ... 他 {len(migration_plan) - 30}件")

    if check_only:
        print("\n[CHECK-ONLY] 分析完了。")
        return

    # 4. バックアップ
    print("\n[4/5] バックアップ...")
    backup_data = {
        "timestamp": timestamp,
        "total_records": len(records),
        "old_distribution": dict(old_counter.most_common()),
        "migration_plan": migration_plan,
        "new_options": NEW_OPTIONS,
    }
    backup_path = BACKUP_DIR / f"{timestamp}_next_action_migration_plan.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    print(f"  保存: {backup_path}")

    # 全レコードのスナップショットも保存
    snapshot_path = BACKUP_DIR / f"{timestamp}_deals_snapshot_pre_migration.json"
    snapshot = []
    for rec in records:
        snapshot.append({
            "record_id": rec["record_id"],
            "fields": {k: extract_text(v) for k, v in rec.get("fields", {}).items()
                       if k in ("商談名", "次アクション", "備考", "取引先", "商談ステージ")},
        })
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  保存: {snapshot_path}")

    if not execute:
        print("\n[DRY-RUN] レコード更新をスキップ。")
        print("  本番実行するには: python3 crm_next_action_migrate.py --execute")
        return

    # 5. レコード一括更新
    print("\n[5/5] レコード一括更新...")
    success = 0
    fail = 0

    for i, m in enumerate(migration_plan, 1):
        update_fields = {"次アクション": m["new_value"]}

        # 個別記述は備考に追記
        if m["save_to_memo"]:
            existing = m["existing_memo"].strip()
            memo_addition = f"[旧次アクション] {m['old_value']}"
            if existing:
                update_fields["備考"] = f"{existing}\n{memo_addition}"
            else:
                update_fields["備考"] = memo_addition

        ok = lark_update_record(token, DEAL_TABLE_ID, m["record_id"], update_fields)
        if ok:
            success += 1
            if i <= 5 or i % 50 == 0:
                print(f"  {i:3d}/{len(migration_plan)} OK: {m['old_value'][:25]} → {m['new_value']}")
        else:
            fail += 1
            print(f"  {i:3d}/{len(migration_plan)} NG: {m['record_id']} - {m['old_value'][:25]}")

        time.sleep(0.3)  # Rate limit

    print(f"\n  レコード更新完了: {success}件成功 / {fail}件失敗")

    # フィールド定義の更新
    print("\n  フィールド定義の更新...")
    field_info = lark_get_field_info(token, DEAL_TABLE_ID, "次アクション")
    if field_info:
        field_id = field_info.get("field_id")
        ok = lark_update_field(token, DEAL_TABLE_ID, field_id, NEW_OPTIONS)
        if ok:
            print(f"  フィールド定義更新OK: 選択肢 {len(NEW_OPTIONS)}個")
        else:
            print("  フィールド定義更新NG（手動対応が必要）")
    else:
        print("  フィールド情報が取得できませんでした")

    # ログ保存
    log_path = BACKUP_DIR / f"{timestamp}_next_action_migration_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "mode": "execute",
            "total_records": len(records),
            "migration_count": len(migration_plan),
            "success": success,
            "fail": fail,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 70}")
    print(f"  完了: {success}件成功 / {fail}件失敗")
    print(f"  ログ: {log_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
