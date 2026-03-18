#!/usr/bin/env python3
"""
Hot/Warm商談フォローリスト抽出
次アクション日が未設定のHot/Warm案件を担当者別に抽出し、MDファイルに保存
READ-ONLY: データ取得・分析のみ
"""

import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── Config ──
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"

OUTPUT_FILE = Path("/mnt/c/Users/USER/Documents/_data/content/hot_warm_followup_list.md")

# Lark user ID → 担当営業名マッピング（人物フィールドがIDで返る場合の対応）
USER_ID_MAP = {
    "550372": "政木 勇治",
    "ユーザー550372": "政木 勇治",
}


def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def fetch_all_records(token):
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


def get_company_name(fields):
    """取引先リンクフィールドから取引先名を取得"""
    company_link = fields.get("取引先", [])
    if company_link and isinstance(company_link, list) and len(company_link) > 0:
        if isinstance(company_link[0], dict):
            name = company_link[0].get("text", "")
            if not name:
                text_arr = company_link[0].get("text_arr", [])
                if text_arr:
                    name = text_arr[0]
            if name:
                return name
    # fallback to 新規取引先名
    return safe_get(fields, "新規取引先名", "(取引先名なし)")


def ts_to_date_str(ms_val):
    if not ms_val:
        return ""
    try:
        ts = int(ms_val) / 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except:
        return ""


def parse_date_display(val):
    """日付フィールドを表示用文字列に変換"""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        return ts_to_date_str(val)
    if isinstance(val, str):
        # Try as timestamp string first
        try:
            ts = int(val)
            if ts > 1000000000:  # looks like a timestamp
                return ts_to_date_str(ts)
        except:
            pass
        return val[:10]  # YYYY-MM-DD
    return ""


def main():
    print("=== Hot/Warm商談フォローリスト抽出 ===", file=sys.stderr)

    # 1. トークン取得
    token = get_token()
    print(f"Token取得完了", file=sys.stderr)

    # 2. 全レコード取得
    records = fetch_all_records(token)
    print(f"全{len(records)}件取得", file=sys.stderr)

    # 3. Hot/Warm & 次アクション日未設定を抽出
    hot_warm_no_action = []
    for r in records:
        f = r.get("fields", {})
        temp = safe_get(f, "温度感スコア")
        next_action_date = safe_get(f, "次アクション日")
        stage = safe_get(f, "商談ステージ")

        # 温度感がHotまたはWarm
        if temp not in ("Hot", "Warm"):
            continue

        # 受注・失注・営業見込みなしは除外
        if stage in ("受注", "失注", "営業見込みなし"):
            continue

        # 次アクション日が未設定
        if next_action_date and next_action_date.strip():
            continue

        company = get_company_name(f)
        rep_raw = safe_get(f, "担当営業") or "(未設定)"
        rep = USER_ID_MAP.get(rep_raw, rep_raw)
        hearing = safe_get(f, "ヒアリング内容（まとめ）")
        next_action = safe_get(f, "次アクション")
        deal_name = safe_get(f, "商談名")
        deal_date_raw = f.get("商談日")
        deal_date = parse_date_display(deal_date_raw)
        amount = safe_get(f, "見積・予算金額") or safe_get(f, "確定金額") or ""
        category = safe_get(f, "客先カテゴリ")
        updated = ts_to_date_str(r.get("last_modified_time"))

        hot_warm_no_action.append({
            "company": company,
            "deal_name": deal_name,
            "rep": rep,
            "temp": temp,
            "stage": stage or "(未設定)",
            "next_action": next_action,
            "hearing": hearing,
            "deal_date": deal_date,
            "amount": amount,
            "category": category,
            "rep_raw": rep_raw,
            "updated": updated,
            "record_id": r.get("record_id", ""),
        })

    # Debug: show unique rep values
    raw_reps = set(d["rep_raw"] for d in hot_warm_no_action)
    print(f"\n担当営業の生値: {raw_reps}", file=sys.stderr)
    print(f"Hot/Warm & 次アクション日未設定: {len(hot_warm_no_action)}件", file=sys.stderr)

    # 4. 担当者別に分類
    by_rep = defaultdict(list)
    for d in hot_warm_no_action:
        by_rep[d["rep"]].append(d)

    # 温度感順（Hot > Warm）でソート
    temp_order = {"Hot": 0, "Warm": 1}
    for rep in by_rep:
        by_rep[rep].sort(key=lambda x: (temp_order.get(x["temp"], 2), x["updated"] or ""))

    # 5. Markdown生成
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []
    lines.append(f"# Hot/Warm商談 フォローアップリスト")
    lines.append(f"")
    lines.append(f"**抽出日時**: {now}")
    lines.append(f"**抽出条件**: 温度感=Hot/Warm、次アクション日=未設定、ステージ=受注/失注/営業見込みなし以外")
    lines.append(f"**該当件数**: {len(hot_warm_no_action)}件")
    lines.append(f"")

    # サマリーテーブル
    lines.append("## サマリー")
    lines.append("")
    lines.append("| 担当者 | Hot | Warm | 合計 |")
    lines.append("|--------|-----|------|------|")
    for rep in sorted(by_rep.keys()):
        deals = by_rep[rep]
        hot_count = sum(1 for d in deals if d["temp"] == "Hot")
        warm_count = sum(1 for d in deals if d["temp"] == "Warm")
        lines.append(f"| {rep} | {hot_count} | {warm_count} | {len(deals)} |")
    total_hot = sum(1 for d in hot_warm_no_action if d["temp"] == "Hot")
    total_warm = sum(1 for d in hot_warm_no_action if d["temp"] == "Warm")
    lines.append(f"| **合計** | **{total_hot}** | **{total_warm}** | **{len(hot_warm_no_action)}** |")
    lines.append("")

    # 担当者別の詳細（新美→政木→その他の順）
    rep_order = ["新美 光", "政木 勇治"]
    ordered_reps = [r for r in rep_order if r in by_rep] + [r for r in sorted(by_rep.keys()) if r not in rep_order]

    for rep in ordered_reps:
        deals = by_rep[rep]
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## {rep}（{len(deals)}件）")
        lines.append(f"")

        for i, d in enumerate(deals, 1):
            amount_str = ""
            if d["amount"]:
                try:
                    amt = float(d["amount"])
                    amount_str = f" / 金額: {amt:,.0f}円"
                except:
                    amount_str = f" / 金額: {d['amount']}"

            lines.append(f"### {i}. {d['company']}")
            lines.append(f"")
            lines.append(f"- **商談名**: {d['deal_name']}")
            lines.append(f"- **温度感**: {d['temp']} / **ステージ**: {d['stage']}{amount_str}")
            lines.append(f"- **カテゴリ**: {d['category'] or '(未設定)'}")
            lines.append(f"- **商談日**: {d['deal_date'] or '(未記録)'} / **最終更新**: {d['updated'] or '(不明)'}")
            if d["next_action"]:
                lines.append(f"- **次アクション（内容のみ、日付なし）**: {d['next_action']}")
            else:
                lines.append(f"- **次アクション**: 未設定")

            if d["hearing"]:
                # ヒアリング内容は長い場合があるので改行付き
                hearing_lines = d["hearing"].replace("\n", "\n  > ")
                lines.append(f"- **ヒアリング内容**:")
                lines.append(f"  > {hearing_lines}")
            lines.append(f"")

    # 6. 週次レポート組み込み用セクション
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## 週次レポート組み込み用テキスト")
    lines.append(f"")

    for rep in ordered_reps:
        deals = by_rep[rep]
        hot_deals = [d for d in deals if d["temp"] == "Hot"]
        warm_deals = [d for d in deals if d["temp"] == "Warm"]

        lines.append(f"### {rep}向け")
        lines.append(f"")
        lines.append(f"**要フォロー案件（次アクション日未設定）**")
        lines.append(f"")

        if hot_deals:
            lines.append(f"Hot案件（{len(hot_deals)}件）:")
            for d in hot_deals:
                lines.append(f"  - {d['company']}（{d['stage']}）← 次アクション日を設定してください")
        if warm_deals:
            lines.append(f"Warm案件（{len(warm_deals)}件）:")
            for d in warm_deals:
                lines.append(f"  - {d['company']}（{d['stage']}）← 次アクション日を設定してください")
        lines.append(f"")

    md_content = "\n".join(lines)

    # 出力先ディレクトリ確認
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(md_content, encoding="utf-8")
    print(f"\n出力完了: {OUTPUT_FILE}", file=sys.stderr)

    # コンソールにもサマリー出力
    print(f"\n{'='*60}")
    print(f"Hot/Warm商談 フォローアップリスト")
    print(f"{'='*60}")
    print(f"該当件数: {len(hot_warm_no_action)}件")
    for rep in ordered_reps:
        deals = by_rep[rep]
        hot_count = sum(1 for d in deals if d["temp"] == "Hot")
        warm_count = sum(1 for d in deals if d["temp"] == "Warm")
        print(f"  {rep}: Hot={hot_count}, Warm={warm_count}, 計{len(deals)}件")
    print(f"\n詳細: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
