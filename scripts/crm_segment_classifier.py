#!/usr/bin/env python3
"""
CRM取引先ランク自動分類スクリプト
取引先531社をA/B/C/Dランクに自動分類する

ランク定義:
  A: 受注実績あり + 直近6ヶ月以内に商談（リピート候補）
  B: 商談実績あり + Hot/Warm温度感（見込み高）
  C: 商談実績あり + Cold or 温度感未設定（要育成）
  D: 取引先登録のみで商談なし（休眠）

Usage:
  python3 crm_segment_classifier.py --dry-run    # 分析のみ（書き込みなし）
  python3 crm_segment_classifier.py              # 分類実行 + 取引先テーブル更新
  python3 crm_segment_classifier.py --verbose     # 詳細ログ付き

出力:
  - ランク別集計
  - 各ランクの代表的な取引先リスト
  - 取引先テーブルの「ランク」フィールドを更新（dry-run以外）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# ── 設定 ──
SCRIPT_DIR = Path(__file__).parent
# ローカル実行: _data直下の本物config / GitHub Actions: scripts/内のテンプレ(env展開済み)
_LOCAL_CONFIG = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
_SCRIPT_CONFIG = SCRIPT_DIR / "automation_config.json"
CONFIG_FILE = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _SCRIPT_CONFIG

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = os.environ.get("LARK_APP_ID") or CONFIG["lark"]["app_id"]
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET") or CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = os.environ.get("CRM_BASE_TOKEN") or CONFIG["lark"]["crm_base_token"]

# テーブルID
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"   # 取引先 (530件)
TABLE_DEALS = "tbl1rM86nAw9l3bP"       # 商談 (545件)
TABLE_ORDERS = "tbldLj2iMJYocct6"      # 受注台帳 (181件)

# ランク分類の基準日（直近6ヶ月）
SIX_MONTHS_AGO = datetime.now() - timedelta(days=180)
SIX_MONTHS_TS = int(SIX_MONTHS_AGO.timestamp() * 1000)  # Larkはミリ秒

# 更新先フィールド名（取引先テーブルの「ランク」フィールド）
RANK_FIELD_NAME = "ランク"

# ── Lark API共通 ──
def lark_get_token():
    """テナントアクセストークンを取得"""
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
        if "tenant_access_token" not in resp:
            print(f"[ERROR] トークン取得失敗: {resp}")
            sys.exit(1)
        return resp["tenant_access_token"]


def get_all_records(token, table_id, fields=None):
    """テーブルの全レコードをページネーション付きで取得"""
    records = []
    page_token = None
    while True:
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500")
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    if not body:
                        print(f"[WARN] Empty response (attempt {attempt+1}/3), retrying...")
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
                print(f"[WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if result is None:
            print(f"[ERROR] Failed to fetch records after 3 attempts for table {table_id}")
            break
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def get_table_fields(token, table_id):
    """テーブルのフィールド一覧を取得"""
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/fields?page_size=100")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        return result.get("data", {}).get("items", [])


def create_single_select_field(token, table_id, field_name, options):
    """シングルセレクトフィールドを作成"""
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/fields")
    payload = {
        "field_name": field_name,
        "type": 3,  # Single Select
        "property": {
            "options": [{"name": opt} for opt in options]
        }
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        if result.get("code") != 0:
            print(f"[ERROR] フィールド作成失敗: {result}")
            return None
        return result.get("data", {}).get("field", {})


def update_record(token, table_id, record_id, fields):
    """レコードを更新"""
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}")
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT"
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        return result.get("code") == 0


def batch_update_records(token, table_id, records_to_update):
    """レコードを一括更新（最大500件/回）"""
    success_count = 0
    fail_count = 0
    for i in range(0, len(records_to_update), 500):
        batch = records_to_update[i:i+500]
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records/batch_update")
        payload = {
            "records": [
                {"record_id": rec_id, "fields": fields}
                for rec_id, fields in batch
            ]
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as r:
                result = json.loads(r.read())
                if result.get("code") == 0:
                    success_count += len(batch)
                else:
                    print(f"[WARN] バッチ更新エラー: {result.get('msg')}")
                    fail_count += len(batch)
        except urllib.error.HTTPError as e:
            print(f"[ERROR] バッチ更新HTTP エラー: {e.code} {e.read().decode()}")
            fail_count += len(batch)
        time.sleep(0.5)
    return success_count, fail_count


# ── データ取得 ──
def fetch_all_data(token):
    """取引先・商談・受注台帳の全データを取得"""
    print("📥 データ取得中...")

    print("  取引先テーブル...", end="", flush=True)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f" {len(accounts)}件")

    print("  商談テーブル...", end="", flush=True)
    deals = get_all_records(token, TABLE_DEALS)
    print(f" {len(deals)}件")

    print("  受注台帳...", end="", flush=True)
    orders = get_all_records(token, TABLE_ORDERS)
    print(f" {len(orders)}件")

    return accounts, deals, orders


# ── 商談から取引先record_idへのマッピング構築 ──
def build_deal_map(deals):
    """
    商談を取引先record_id別にまとめる
    返り値: { account_record_id: [deal_info, ...] }
    deal_info = {
        "deal_id": str,
        "deal_date_ts": int or None,
        "temperature": str or None (Hot/Warm/Cold),
        "stage": str or None,
        "has_order": bool (受注日があるか)
    }
    """
    deal_map = defaultdict(list)
    unlinked_deals = []  # 取引先未リンクの商談
    unlinked_info = {}   # deal_id -> deal_info（テキストマッチ用）

    for deal in deals:
        fields = deal.get("fields", {})
        deal_id = deal.get("record_id", "")

        # 取引先リンク取得
        account_link = fields.get("取引先", {})
        account_record_ids = []
        if isinstance(account_link, dict):
            rids = account_link.get("record_ids")
            if rids:
                account_record_ids = rids
        elif isinstance(account_link, list):
            for item in account_link:
                if isinstance(item, dict):
                    rids = item.get("record_ids")
                    if rids:
                        account_record_ids.extend(rids)

        # 商談日（ミリ秒タイムスタンプ）
        deal_date_ts = fields.get("商談日")
        if isinstance(deal_date_ts, str):
            try:
                deal_date_ts = int(deal_date_ts)
            except ValueError:
                deal_date_ts = None

        # 温度感スコア
        temperature = fields.get("温度感スコア")

        # 商談ステージ
        stage = fields.get("商談ステージ")

        # 受注日の有無
        order_date = fields.get("受注日")
        has_order = order_date is not None

        deal_info = {
            "deal_id": deal_id,
            "deal_date_ts": deal_date_ts,
            "temperature": temperature,
            "stage": stage,
            "has_order": has_order,
        }

        if account_record_ids:
            for aid in account_record_ids:
                deal_map[aid].append(deal_info)
        else:
            unlinked_deals.append((deal_id, fields.get("新規取引先名", "不明")))
            unlinked_info[deal_id] = deal_info

    return deal_map, unlinked_deals, unlinked_info


def build_order_map(orders):
    """
    受注台帳を取引先名（テキスト）で集約
    返り値: { 取引先名(正規化): [order_info, ...] }
    order_info = { "order_date_ts": int or None, "amount": float or None }
    """
    order_map = defaultdict(list)
    for order in orders:
        fields = order.get("fields", {})
        company = fields.get("取引先", "")
        if not company or not company.strip():
            continue

        # 正規化: 空白除去、株式会社等の表記揺れ対応
        normalized = normalize_company_name(company)
        if not normalized or len(normalized) < 2:
            # 1文字以下の名前は無視（ノイズ除去）
            continue

        order_date_ts = fields.get("受注日")
        amount = fields.get("受注金額") or fields.get("請求金額")

        order_map[normalized].append({
            "order_date_ts": order_date_ts,
            "amount": amount,
            "raw_name": company,
        })

    return order_map


def normalize_company_name(name):
    """会社名を正規化して比較可能にする"""
    if not name:
        return ""
    # 空白除去
    name = name.replace(" ", "").replace("　", "").strip()
    # 株式会社等の表記除去
    for prefix in ["株式会社", "(株)", "（株）", "有限会社", "(有)", "（有）"]:
        name = name.replace(prefix, "")
    return name.strip()


# ── 分類ロジック ──
def classify_accounts(accounts, deal_map, order_map, unlinked_deals, unlinked_info, verbose=False):
    """
    各取引先をA/B/C/Dランクに分類

    A: 受注実績あり + 直近6ヶ月以内に商談（リピート候補）
    B: 商談実績あり + Hot/Warm温度感（見込み高）
    C: 商談実績あり + Cold or 温度感未設定（要育成）
    D: 取引先登録のみで商談なし（休眠）
    """
    results = {}  # record_id -> {"rank": str, "reason": str, "name": str}
    rank_counts = defaultdict(int)
    rank_details = defaultdict(list)
    unlinked_deals_list = unlinked_deals
    unlinked_deals_info = unlinked_info

    for account in accounts:
        fields = account.get("fields", {})
        record_id = account.get("record_id", "")
        company_name = fields.get("会社名（正式）") or fields.get("会社名（略称）") or "不明"
        company_short = fields.get("会社名（略称）", "") or ""
        normalized_name = normalize_company_name(company_name)
        normalized_short = normalize_company_name(company_short)

        # 会社名が不明・空のレコードはテキストマッチスキップ
        skip_text_match = not normalized_name or len(normalized_name) < 2 or company_name == "不明"

        # ── 商談データ確認 ──
        # 1) Larkリンクから商談取得
        linked_deals = deal_map.get(record_id, [])

        # 2) テキストマッチでリンクなし商談も拾う（会社名が有効な場合のみ）
        if skip_text_match:
            pass  # テキストマッチスキップ
        else:
          for deal_id, unlinked_name in unlinked_deals_list:
            norm_unlinked = normalize_company_name(unlinked_name)
            if norm_unlinked and len(norm_unlinked) >= 3 and (
                norm_unlinked == normalized_name or
                norm_unlinked == normalized_short or
                (len(norm_unlinked) >= 4 and (norm_unlinked in normalized_name or normalized_name in norm_unlinked)) or
                (normalized_short and len(normalized_short) >= 4 and
                 (norm_unlinked in normalized_short or normalized_short in norm_unlinked))
            ):
                # unlinked_deals_mapからdeal_infoを取得
                if deal_id in unlinked_deals_info:
                    linked_deals.append(unlinked_deals_info[deal_id])

        # 3) 受注台帳から会社名マッチで取得（厳密マッチ）
        matched_orders = []
        if not skip_text_match:
            for norm_key, order_list in order_map.items():
                if not norm_key or len(norm_key) < 3:
                    continue
                # 厳密マッチ: 正規化名が完全一致 or 十分長い部分文字列マッチ
                if (
                    norm_key == normalized_name or
                    norm_key == normalized_short or
                    (len(norm_key) >= 4 and (norm_key in normalized_name or normalized_name in norm_key)) or
                    (normalized_short and len(normalized_short) >= 4 and
                     (norm_key in normalized_short or normalized_short in norm_key))
                ):
                    matched_orders.extend(order_list)

        # ── 受注実績の判定 ──
        has_order_from_deals = any(d["has_order"] for d in linked_deals)
        has_order_from_ledger = len(matched_orders) > 0

        # 取引ステータスも参考にする
        deal_status = fields.get("取引ステータス", "")
        is_active_customer = deal_status in ("取引中", "リピート")

        has_order = has_order_from_deals or has_order_from_ledger or is_active_customer

        # ── 直近6ヶ月以内の商談 ──
        recent_deals = [
            d for d in linked_deals
            if d["deal_date_ts"] and d["deal_date_ts"] >= SIX_MONTHS_TS
        ]
        has_recent_deal = len(recent_deals) > 0

        # ── 温度感の判定 ──
        # 取引先テーブルの総合温度感
        overall_temp = fields.get("温度感（総合）", "")
        # 最新の商談温度感
        deal_temps = [d["temperature"] for d in linked_deals if d["temperature"]]
        latest_temp = deal_temps[-1] if deal_temps else None

        # Hot/Warmの判定（取引先or最新商談のどちらかがHot/Warm）
        is_hot_warm = (
            overall_temp in ("Hot", "Warm") or
            latest_temp in ("Hot", "Warm")
        )

        # ── ランク判定 ──
        has_any_deals = len(linked_deals) > 0

        if has_order and has_recent_deal:
            rank = "A"
            reason = "受注実績あり＋直近6ヶ月以内に商談"
        elif has_order and not has_recent_deal:
            # 受注はあるが最近の商談がない → Bランク（優良だがフォロー必要）
            rank = "B"
            reason = "受注実績あり（直近商談なし→フォロー推奨）"
        elif has_any_deals and is_hot_warm:
            rank = "B"
            # 温度感の出典を明示
            if overall_temp in ("Hot", "Warm"):
                reason = f"商談あり＋取引先温度感: {overall_temp}"
            else:
                reason = f"商談あり＋最新商談温度感: {latest_temp}"
        elif has_any_deals:
            rank = "C"
            temp_label = overall_temp or latest_temp or "未設定"
            reason = f"商談あり＋温度感: {temp_label}（要育成）"
        else:
            rank = "D"
            reason = "商談なし（休眠）"

        results[record_id] = {
            "rank": rank,
            "reason": reason,
            "name": company_name,
            "deals_count": len(linked_deals),
            "orders_count": len(matched_orders),
            "current_priority": fields.get("優先度", "未設定"),
        }

        rank_counts[rank] += 1
        rank_details[rank].append({
            "name": company_name,
            "reason": reason,
            "deals": len(linked_deals),
            "orders": len(matched_orders),
        })

        if verbose:
            print(f"  {company_name}: {rank} ({reason})")

    return results, rank_counts, rank_details


# ── メイン処理 ──
def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 60)
    print("  CRM取引先ランク自動分類")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  モード: {'ドライラン（分析のみ）' if dry_run else '本番更新'}")
    print(f"  基準: 直近6ヶ月 = {SIX_MONTHS_AGO.strftime('%Y-%m-%d')}以降")
    print("=" * 60)

    # トークン取得
    token = lark_get_token()

    # データ取得
    accounts, deals, orders = fetch_all_data(token)

    # マッピング構築
    print("\n🔗 データ紐付け中...")
    deal_map, unlinked_deals, unlinked_info = build_deal_map(deals)
    order_map = build_order_map(orders)

    print(f"  商談→取引先リンク済み: {sum(len(v) for v in deal_map.values())}件")
    print(f"  商談→取引先リンクなし: {len(unlinked_deals)}件")
    print(f"  受注台帳 取引先名パターン: {len(order_map)}件")

    # 分類実行
    print("\n📊 ランク分類中...")
    results, rank_counts, rank_details = classify_accounts(
        accounts, deal_map, order_map, unlinked_deals, unlinked_info, verbose=verbose
    )

    # ── 結果表示 ──
    print("\n" + "=" * 60)
    print("  分類結果サマリ")
    print("=" * 60)

    total = sum(rank_counts.values())
    for rank in ["A", "B", "C", "D"]:
        count = rank_counts.get(rank, 0)
        pct = (count / total * 100) if total > 0 else 0
        labels = {
            "A": "リピート候補（受注+直近商談）",
            "B": "見込み高（受注or Hot/Warm）",
            "C": "要育成（商談あり Cold/未設定）",
            "D": "休眠（商談なし）",
        }
        bar = "█" * int(pct / 2)
        print(f"\n  ランク{rank}: {count:>4}社 ({pct:5.1f}%)  {bar}")
        print(f"  　└ {labels[rank]}")

    print(f"\n  合計: {total}社")

    # 各ランク上位表示
    for rank in ["A", "B", "C", "D"]:
        details = rank_details.get(rank, [])
        if not details:
            continue
        print(f"\n── ランク{rank} 代表例（最大10社）──")
        # 商談数・受注数が多い順にソート
        details.sort(key=lambda x: (x["orders"], x["deals"]), reverse=True)
        for i, d in enumerate(details[:10]):
            extra = []
            if d["deals"]:
                extra.append(f"商談{d['deals']}件")
            if d["orders"]:
                extra.append(f"受注{d['orders']}件")
            extra_str = f" [{', '.join(extra)}]" if extra else ""
            print(f"  {i+1:>2}. {d['name']}{extra_str}")
            print(f"      → {d['reason']}")

    # 取引先リンクなし商談の報告
    if unlinked_deals:
        print(f"\n⚠️  取引先未リンク商談: {len(unlinked_deals)}件")
        if verbose:
            for did, name in unlinked_deals[:20]:
                print(f"  - {did}: {name}")

    # ── 書き込み（本番のみ）──
    if dry_run:
        print("\n" + "=" * 60)
        print("  ドライラン完了。書き込みは行いません。")
        print("  本番実行: python3 crm_segment_classifier.py")
        print("=" * 60)
        return

    # フィールド存在確認 → なければ作成
    print(f"\n✏️  取引先テーブルに「{RANK_FIELD_NAME}」フィールドを確認中...")
    existing_fields = get_table_fields(token, TABLE_ACCOUNTS)
    rank_field = None
    for f in existing_fields:
        if f["field_name"] == RANK_FIELD_NAME:
            rank_field = f
            break

    if not rank_field:
        print(f"  「{RANK_FIELD_NAME}」フィールドが見つかりません。作成します...")
        rank_field = create_single_select_field(
            token, TABLE_ACCOUNTS, RANK_FIELD_NAME, ["A", "B", "C", "D"]
        )
        if not rank_field:
            print("[ERROR] フィールド作成に失敗しました。手動で作成してください。")
            sys.exit(1)
        print(f"  ✅ 「{RANK_FIELD_NAME}」フィールドを作成しました")
    else:
        print(f"  ✅ 「{RANK_FIELD_NAME}」フィールドが存在します")

    # バッチ更新
    print(f"\n📝 {len(results)}社のランクを更新中...")
    records_to_update = [
        (record_id, {RANK_FIELD_NAME: info["rank"]})
        for record_id, info in results.items()
    ]

    success, fail = batch_update_records(token, TABLE_ACCOUNTS, records_to_update)
    print(f"  ✅ 成功: {success}件 / ❌ 失敗: {fail}件")

    print("\n" + "=" * 60)
    print("  分類・更新完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
