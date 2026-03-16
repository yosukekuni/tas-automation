#!/usr/bin/env python3
"""
CRM商談ステージ自動分類スクリプト
ステージ未設定の商談を分類ルールに基づいて自動分類する

モード:
  --dry-run   分類結果のレポートのみ出力（デフォルト・データ変更なし）
  --execute   実際にLark Baseを更新する（要ユーザー確認）

分類ルール:
  1. 失注判定: 最終更新180日以上経過 AND 温度感Cold → 「営業見込みなし」
  2. 初回接触: 商談日が1件のみ AND 結果が空 → 「初回接触」
  3. ヒアリング済み: ヒアリング内容に記載あり → 「ヒアリング」
  4. その他: 手動レビュー必要 → タグ付けのみ
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from collections import Counter

# ── Config ──
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"

BACKUP_DIR = Path("/mnt/c/Users/USER/Documents/_data/tas-automation/backups")
REPORT_PATH = Path("/mnt/c/Users/USER/Documents/_data/content/crm_stage_classification.md")

NOW = datetime.now()
TIMESTAMP = NOW.strftime("%Y%m%d_%H%M%S")


# ── Lark API ──
def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def fetch_all_records(token):
    """全商談レコード取得（ページネーション対応）"""
    all_records = []
    page_token = None
    page = 0
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{DEAL_TABLE_ID}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())

        if result.get("code") != 0:
            print(f"API Error: {result}", file=sys.stderr)
            break

        data = result.get("data", {})
        items = data.get("items", [])
        all_records.extend(items)
        page += 1
        print(f"  Page {page}: {len(items)} records (total: {len(all_records)})", file=sys.stderr)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        time.sleep(0.3)

    return all_records


def update_record(token, record_id, fields):
    """Lark Baseレコードを更新"""
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{DEAL_TABLE_ID}/records/{record_id}"
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    if result.get("code") != 0:
        print(f"  Update Error for {record_id}: {result}", file=sys.stderr)
        return False
    return True


def safe_get(fields, key, default=""):
    val = fields.get(key)
    if val is None:
        return default
    if isinstance(val, list):
        if len(val) == 0:
            return default
        if isinstance(val[0], dict):
            return val[0].get("text", val[0].get("name", str(val[0])))
        return str(val[0])
    if isinstance(val, dict):
        return val.get("text", val.get("name", str(val)))
    return str(val)


def ts_to_date(ms_val):
    if not ms_val:
        return None
    try:
        ts = int(ms_val) / 1000
        return datetime.fromtimestamp(ts)
    except:
        return None


def parse_date_field(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return ts_to_date(val)
    if isinstance(val, str):
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(val, fmt)
            except:
                pass
        return ts_to_date(val)
    return None


def classify_deal(deal, fields):
    """
    分類ルールに基づいて商談のステージを判定する

    Returns: (stage, rule_name, reason)
        stage: 設定するステージ名 (Noneの場合は手動レビュー)
        rule_name: 適用されたルール名
        reason: 分類理由
    """
    temperature = safe_get(fields, "温度感スコア").lower()
    hearing = safe_get(fields, "ヒアリング内容（まとめ）")
    result_field = safe_get(fields, "結果")
    deal_date_str = safe_get(fields, "商談日")
    next_action = safe_get(fields, "次アクション")
    deal_name = safe_get(fields, "商談名")
    absent_action = safe_get(fields, "不在時の対応")

    # 最終更新日を取得
    updated = ts_to_date(deal.get("last_modified_time"))
    created = ts_to_date(deal.get("created_time"))
    deal_date = parse_date_field(deal_date_str)

    # 最も新しい日付を「最終活動日」とする
    last_activity = updated or deal_date or created
    days_since_activity = (NOW - last_activity).days if last_activity else None

    # ── ルール1: 失注判定 ──
    # 180日以上経過 AND 温度感がCold系
    is_cold = any(c in temperature for c in ["cold", "コールド", "c", "低"])
    if days_since_activity and days_since_activity >= 180 and is_cold:
        return (
            "営業見込みなし",
            "Rule1_失注判定",
            f"最終活動{days_since_activity}日前 + 温度感Cold"
        )

    # ── ルール1b: 超長期放置（365日以上） ──
    # 温度感に関係なく、1年以上放置は失注
    if days_since_activity and days_since_activity >= 365:
        return (
            "営業見込みなし",
            "Rule1b_超長期放置",
            f"最終活動{days_since_activity}日前（1年以上放置）"
        )

    # ── ルール2: 不在対応 ──
    # 不在時の対応が記録されている場合
    if absent_action and len(str(absent_action)) > 2:
        return (
            "不在",
            "Rule2_不在",
            f"不在時の対応記録あり: {str(absent_action)[:50]}"
        )

    # ── ルール3: ヒアリング済み ──
    # ヒアリング内容に実質的な記載あり
    if hearing and len(str(hearing).strip()) > 5:
        return (
            "ヒアリング",
            "Rule3_ヒアリング済",
            f"ヒアリング内容記載あり（{len(str(hearing))}文字）"
        )

    # ── ルール4: 初回接触 ──
    # ヒアリング内容なし AND 結果なし → 初回接触レベル
    if (not hearing or len(str(hearing).strip()) <= 5) and (not result_field or result_field == ""):
        return (
            "リード獲得",
            "Rule4_初回接触",
            "ヒアリング内容なし・結果なし → リード獲得段階"
        )

    # ── ルール5: その他（手動レビュー必要） ──
    return (
        None,
        "Rule5_手動レビュー",
        "自動分類ルールに該当せず"
    )


def save_snapshot(records, suffix=""):
    """変更前スナップショットをJSON保存"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{TIMESTAMP}_deal_stage_snapshot{suffix}.json"
    filepath = BACKUP_DIR / filename

    # raw_fieldsを保存可能な形式に変換
    snapshot = []
    for r in records:
        snapshot.append({
            "record_id": r.get("record_id"),
            "fields": r.get("fields", {}),
            "created_time": r.get("created_time"),
            "last_modified_time": r.get("last_modified_time"),
        })

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2, default=str)

    print(f"  Snapshot saved: {filepath} ({len(snapshot)} records)", file=sys.stderr)
    return filepath


def generate_report(classifications, total_deals, unstaged_count):
    """dry-runレポートを生成"""
    lines = []
    lines.append("# CRM商談ステージ自動分類レポート（dry-run）")
    lines.append("")
    lines.append(f"生成日: {NOW.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"対象: 商談テーブル（{DEAL_TABLE_ID}）")
    lines.append(f"総商談数: **{total_deals}件**")
    lines.append(f"ステージ未設定: **{unstaged_count}件**")
    lines.append("")

    # ── 分類サマリー ──
    rule_counter = Counter()
    stage_counter = Counter()
    for c in classifications:
        rule_counter[c["rule"]] += 1
        stage_counter[c["new_stage"] or "(手動レビュー)"] += 1

    lines.append("## 分類結果サマリー")
    lines.append("")
    lines.append("### ステージ別")
    lines.append("| 分類先ステージ | 件数 | 割合 |")
    lines.append("|---------------|------|------|")
    for stage, cnt in stage_counter.most_common():
        lines.append(f"| {stage} | {cnt} | {cnt/unstaged_count*100:.1f}% |")
    lines.append("")

    lines.append("### ルール別")
    lines.append("| ルール | 件数 | 割合 |")
    lines.append("|--------|------|------|")
    for rule, cnt in rule_counter.most_common():
        lines.append(f"| {rule} | {cnt} | {cnt/unstaged_count*100:.1f}% |")
    lines.append("")

    # ── 担当者別 ──
    rep_counter = {}
    for c in classifications:
        rep = c["rep"] or "(未設定)"
        if rep not in rep_counter:
            rep_counter[rep] = Counter()
        rep_counter[rep][c["new_stage"] or "(手動レビュー)"] += 1

    lines.append("### 担当者別")
    for rep in sorted(rep_counter.keys()):
        rep_total = sum(rep_counter[rep].values())
        lines.append(f"")
        lines.append(f"**{rep}** ({rep_total}件)")
        lines.append("| 分類先 | 件数 |")
        lines.append("|--------|------|")
        for stage, cnt in rep_counter[rep].most_common():
            lines.append(f"| {stage} | {cnt} |")
    lines.append("")

    # ── 自動分類対象の詳細（ステージ別） ──
    auto_classified = [c for c in classifications if c["new_stage"] is not None]
    manual_review = [c for c in classifications if c["new_stage"] is None]

    lines.append(f"## 自動分類対象: {len(auto_classified)}件")
    lines.append("")

    # ステージごとにグループ化して表示
    by_stage = {}
    for c in auto_classified:
        s = c["new_stage"]
        if s not in by_stage:
            by_stage[s] = []
        by_stage[s].append(c)

    for stage in ["営業見込みなし", "不在", "ヒアリング", "リード獲得"]:
        items = by_stage.get(stage, [])
        if not items:
            continue
        lines.append(f"### {stage}（{len(items)}件）")
        lines.append("")
        lines.append("| # | 商談名 | 担当 | ルール | 理由 |")
        lines.append("|---|--------|------|--------|------|")
        for i, c in enumerate(items, 1):
            name = c["name"][:35]
            lines.append(f"| {i} | {name} | {c['rep'] or '-'} | {c['rule']} | {c['reason'][:60]} |")
        lines.append("")

    # ── 手動レビュー対象 ──
    if manual_review:
        lines.append(f"## 手動レビュー対象: {len(manual_review)}件")
        lines.append("")
        lines.append("| # | 商談名 | 担当 | 理由 |")
        lines.append("|---|--------|------|------|")
        for i, c in enumerate(manual_review, 1):
            name = c["name"][:35]
            lines.append(f"| {i} | {name} | {c['rep'] or '-'} | {c['reason']} |")
        lines.append("")

    # ── 実行コマンド ──
    lines.append("## 本番実行方法")
    lines.append("")
    lines.append("```bash")
    lines.append("# ユーザー確認後に実行")
    lines.append("python3 /mnt/c/Users/USER/Documents/_data/tas-automation/scripts/crm_stage_classifier.py --execute")
    lines.append("```")
    lines.append("")
    lines.append(f"バックアップ: `backups/{TIMESTAMP}_deal_stage_snapshot.json`")
    lines.append("")
    lines.append("---")
    lines.append("*dry-run: データ変更は行っていません。`--execute` で本番実行します。*")

    return "\n".join(lines)


def main():
    mode = "--dry-run"
    if len(sys.argv) > 1:
        mode = sys.argv[1]

    is_execute = mode == "--execute"

    print(f"=== CRM商談ステージ自動分類 ===", file=sys.stderr)
    print(f"モード: {'本番実行' if is_execute else 'dry-run（レポートのみ）'}", file=sys.stderr)
    print(f"", file=sys.stderr)

    # 1. トークン取得
    print("1. Larkトークン取得...", file=sys.stderr)
    token = get_token()

    # 2. 全商談レコード取得
    print("2. 全商談レコード取得...", file=sys.stderr)
    records = fetch_all_records(token)
    total = len(records)
    print(f"   取得完了: {total}件", file=sys.stderr)

    # 3. ステージ未設定を抽出
    unstaged = []
    for r in records:
        fields = r.get("fields", {})
        stage = safe_get(fields, "商談ステージ")
        if not stage or stage == "(未設定)" or stage.strip() == "":
            unstaged.append(r)

    print(f"3. ステージ未設定: {len(unstaged)}件 / {total}件", file=sys.stderr)

    # 4. スナップショット保存（変更前バックアップ）
    print("4. スナップショット保存...", file=sys.stderr)
    snapshot_path = save_snapshot(unstaged)

    # 5. 分類実行
    print("5. 分類ルール適用...", file=sys.stderr)
    classifications = []
    for r in unstaged:
        fields = r.get("fields", {})
        new_stage, rule, reason = classify_deal(r, fields)

        classifications.append({
            "record_id": r.get("record_id"),
            "name": safe_get(fields, "商談名"),
            "rep": safe_get(fields, "担当営業"),
            "temperature": safe_get(fields, "温度感スコア"),
            "new_stage": new_stage,
            "rule": rule,
            "reason": reason,
        })

    # 分類結果のサマリー
    auto_count = sum(1 for c in classifications if c["new_stage"] is not None)
    manual_count = sum(1 for c in classifications if c["new_stage"] is None)
    print(f"   自動分類: {auto_count}件 / 手動レビュー: {manual_count}件", file=sys.stderr)

    # 6. レポート生成
    print("6. レポート生成...", file=sys.stderr)
    report = generate_report(classifications, total, len(unstaged))

    # レポート保存
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"   レポート保存: {REPORT_PATH}", file=sys.stderr)

    # 分類結果JSONも保存（本番実行時に使用）
    classification_json_path = BACKUP_DIR / f"{TIMESTAMP}_deal_stage_classifications.json"
    with open(classification_json_path, "w", encoding="utf-8") as f:
        json.dump(classifications, f, ensure_ascii=False, indent=2)
    print(f"   分類結果JSON: {classification_json_path}", file=sys.stderr)

    # 7. 本番実行（--execute の場合のみ）
    if is_execute:
        print("", file=sys.stderr)
        print("7. 本番実行: Lark Base更新...", file=sys.stderr)

        success = 0
        fail = 0
        for c in classifications:
            if c["new_stage"] is None:
                continue  # 手動レビュー対象はスキップ

            ok = update_record(token, c["record_id"], {
                "商談ステージ": c["new_stage"]
            })
            if ok:
                success += 1
            else:
                fail += 1
            time.sleep(0.2)  # Rate limit

        print(f"   更新完了: 成功{success}件 / 失敗{fail}件", file=sys.stderr)
    else:
        print("", file=sys.stderr)
        print("=== dry-run完了。本番実行は --execute オプションで。 ===", file=sys.stderr)

    # 標準出力にレポート
    print(report)


if __name__ == "__main__":
    main()
