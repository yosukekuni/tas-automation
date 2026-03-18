#!/usr/bin/env python3
"""
CRM全体監査スクリプト
- 全テーブルのレコード数・フィールド充填率
- 商談パイプライン詳細分析
- データ品質スコアリング
- 改善提案の根拠データ収集

読み取り専用。データ変更なし。
"""

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── Config (from automation_config.json, not hardcoded) ──
_SCRIPT_DIR = Path(__file__).parent
_CONFIG_FILE = _SCRIPT_DIR / "automation_config.json"
if _CONFIG_FILE.exists():
    with open(_CONFIG_FILE) as _f:
        _cfg = json.load(_f)
    APP_ID = _cfg["lark"]["app_id"]
    APP_SECRET = _cfg["lark"]["app_secret"]
    BASE_TOKEN = _cfg["lark"]["crm_base_token"]
else:
    import os as _os
    APP_ID = _os.environ.get("LARK_APP_ID", "")
    APP_SECRET = _os.environ.get("LARK_APP_SECRET", "")
    BASE_TOKEN = _os.environ.get("CRM_BASE_TOKEN", "")

TABLES = {
    "取引先": "tblTfGScQIdLTYxA",
    "連絡先": "tblN53hFIQoo4W8j",
    "商談": "tbl1rM86nAw9l3bP",
    "受注台帳": "tbldLj2iMJYocct6",
    "メールログ": "tblfBahatPZMJEM5",
    "支払明細": "tbl0FeQMip23oab3",
    "面談管理": "tblyKFlnIYI6Md09",
}

OUTPUT_PATH = Path("/mnt/c/Users/USER/Documents/_data/content/crm_audit_report.md")


def get_token():
    data = json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    return resp["tenant_access_token"]


def list_fields(token, table_id):
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/fields?page_size=100"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    return resp.get("data", {}).get("items", [])


def list_records(token, table_id, page_size=500):
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
        items = resp.get("data", {}).get("items") or []
        records.extend(items)
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp["data"].get("page_token")
    return records


def field_fill_rate(records, field_name):
    """フィールドの充填率を計算"""
    if not records:
        return 0, 0
    filled = 0
    for r in records:
        val = r.get("fields", {}).get(field_name)
        if val is not None and val != "" and val != [] and val != {}:
            filled += 1
    return filled, len(records)


def extract_text(val):
    """Larkフィールド値からテキストを抽出"""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        # リンクフィールドやマルチセレクト
        texts = []
        for item in val:
            if isinstance(item, dict):
                t = item.get("text") or item.get("name") or str(item)
                if t:
                    texts.append(str(t))
            elif item is not None:
                texts.append(str(item))
        return ", ".join(texts) if texts else None
    if isinstance(val, dict):
        return val.get("text", val.get("name", str(val)))
    return str(val)


def ms_to_date(ms_val):
    """ミリ秒タイムスタンプを日付に変換"""
    if ms_val is None:
        return None
    try:
        if isinstance(ms_val, (int, float)):
            return datetime.fromtimestamp(ms_val / 1000)
        return None
    except:
        return None


def main():
    print("=== CRM全体監査 開始 ===")
    print(f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    token = get_token()
    print(f"認証OK")

    report = []
    report.append("# CRM精密監査レポート")
    report.append(f"\n**監査日**: {datetime.now().strftime('%Y年%m月%d日')}")
    report.append("**対象**: 東海エアサービス CRM（Lark Base）")
    report.append("**種別**: 読み取り専用・全テーブルデータ品質監査")
    report.append("\n---\n")

    # ========================================
    # Part 1: 全テーブル概要
    # ========================================
    report.append("## 1. テーブル概要\n")
    report.append("| テーブル | レコード数 | フィールド数 |")
    report.append("|---------|-----------|------------|")

    all_data = {}
    all_fields = {}

    for tname, tid in TABLES.items():
        print(f"\n--- {tname} ({tid}) ---")
        try:
            fields = list_fields(token, tid)
            records = list_records(token, tid)
            all_data[tname] = records
            all_fields[tname] = fields
            print(f"  レコード: {len(records)}, フィールド: {len(fields)}")
            report.append(f"| {tname} | {len(records)} | {len(fields)} |")
        except Exception as e:
            print(f"  ERROR: {e}")
            all_data[tname] = []
            all_fields[tname] = []
            report.append(f"| {tname} | ERROR | ERROR |")

    report.append("")

    # ========================================
    # Part 2: フィールド充填率（全テーブル）
    # ========================================
    report.append("## 2. フィールド充填率\n")

    for tname, fields in all_fields.items():
        records = all_data.get(tname, [])
        if not records:
            continue

        report.append(f"### {tname}（{len(records)}件）\n")
        report.append("| フィールド | 型 | 充填数 | 充填率 | 評価 |")
        report.append("|-----------|-----|--------|--------|------|")

        for f in fields:
            fname = f.get("field_name", "?")
            ftype = f.get("type", "?")
            type_names = {1: "テキスト", 2: "数値", 3: "単一選択", 4: "複数選択",
                         5: "日付", 7: "チェック", 11: "人", 13: "電話", 15: "URL",
                         17: "添付", 18: "リンク", 19: "ルックアップ", 20: "数式",
                         21: "自動番号", 22: "作成日時", 23: "更新日時", 1001: "作成者", 1002: "更新者"}
            type_label = type_names.get(ftype, f"type{ftype}")

            filled, total = field_fill_rate(records, fname)
            rate = (filled / total * 100) if total > 0 else 0

            if rate >= 90:
                grade = "良好"
            elif rate >= 50:
                grade = "要改善"
            elif rate > 0:
                grade = "深刻"
            else:
                grade = "未使用"

            report.append(f"| {fname} | {type_label} | {filled}/{total} | {rate:.1f}% | {grade} |")

        report.append("")

    # ========================================
    # Part 3: 商談パイプライン詳細分析
    # ========================================
    deals = all_data.get("商談", [])
    report.append("## 3. 商談パイプライン詳細分析\n")
    report.append(f"**総商談数**: {len(deals)}件\n")

    # 3a. ステージ分布
    stage_counter = Counter()
    temp_counter = Counter()  # 温度感
    owner_counter = Counter()
    next_action_counter = Counter()

    hot_warm_no_action_date = []
    stagnant_deals = []
    no_stage = []

    now = datetime.now()

    for d in deals:
        f = d.get("fields", {})

        stage = extract_text(f.get("商談ステージ"))
        stage_counter[stage or "(未設定)"] += 1

        temp = extract_text(f.get("温度感スコア"))
        temp_counter[temp or "(未設定)"] += 1

        owner = extract_text(f.get("担当営業"))
        owner_counter[owner or "(未設定)"] += 1

        next_action = extract_text(f.get("次アクション"))
        next_action_counter[next_action or "(未設定)"] += 1

        # Hot/Warmで次アクション日未設定
        next_action_date = f.get("次アクション日")
        if temp and temp in ("Hot", "Warm") and not next_action_date:
            company = extract_text(f.get("取引先")) or extract_text(f.get("新規取引先名")) or "(不明)"
            hot_warm_no_action_date.append({
                "company": company,
                "temp": temp,
                "stage": stage or "(未設定)",
                "owner": owner or "(未設定)"
            })

        # ステージ未設定
        if not stage:
            company = extract_text(f.get("取引先")) or extract_text(f.get("新規取引先名")) or "(不明)"
            no_stage.append({
                "company": company,
                "owner": owner or "(未設定)",
                "temp": temp or "(未設定)"
            })

        # 停滞（商談日から30日以上）
        updated = f.get("商談日") or f.get("次アクション日")
        if updated:
            updated_dt = ms_to_date(updated)
            if updated_dt and (now - updated_dt).days > 30:
                company = extract_text(f.get("取引先")) or extract_text(f.get("新規取引先名")) or "(不明)"
                stagnant_deals.append({
                    "company": company,
                    "days": (now - updated_dt).days,
                    "stage": stage or "(未設定)",
                    "owner": owner or "(未設定)"
                })

    report.append("### 3a. ステージ分布\n")
    report.append("| ステージ | 件数 | 割合 |")
    report.append("|---------|------|------|")
    for stage, count in stage_counter.most_common():
        pct = count / len(deals) * 100 if deals else 0
        report.append(f"| {stage} | {count} | {pct:.1f}% |")

    report.append("\n### 3b. 温度感分布\n")
    report.append("| 温度感 | 件数 | 割合 |")
    report.append("|--------|------|------|")
    for temp, count in temp_counter.most_common():
        pct = count / len(deals) * 100 if deals else 0
        report.append(f"| {temp} | {count} | {pct:.1f}% |")

    report.append("\n### 3c. 担当者別分布\n")
    report.append("| 担当 | 件数 | 割合 |")
    report.append("|------|------|------|")
    for owner, count in owner_counter.most_common():
        pct = count / len(deals) * 100 if deals else 0
        report.append(f"| {owner} | {count} | {pct:.1f}% |")

    report.append(f"\n### 3d. 次アクション選択肢分布（全{len(next_action_counter)}種）\n")
    report.append("| 次アクション | 件数 |")
    report.append("|-------------|------|")
    for action, count in next_action_counter.most_common(30):
        report.append(f"| {action} | {count} |")
    if len(next_action_counter) > 30:
        report.append(f"| ...他{len(next_action_counter) - 30}種 | - |")

    # 3e. Hot/Warmで次アクション日未設定
    report.append(f"\n### 3e. Hot/Warm案件で次アクション日未設定（{len(hot_warm_no_action_date)}件）\n")
    if hot_warm_no_action_date:
        report.append("| 取引先 | 温度感 | ステージ | 担当 |")
        report.append("|--------|--------|---------|------|")
        for item in hot_warm_no_action_date[:50]:
            report.append(f"| {item['company'][:20]} | {item['temp']} | {item['stage']} | {item['owner']} |")
        if len(hot_warm_no_action_date) > 50:
            report.append(f"| ...他{len(hot_warm_no_action_date) - 50}件 | | | |")

    # 3f. 停滞商談
    stagnant_deals.sort(key=lambda x: -x["days"])
    report.append(f"\n### 3f. 停滞商談（30日以上更新なし: {len(stagnant_deals)}件）\n")
    report.append(f"**90日以上**: {sum(1 for d in stagnant_deals if d['days'] >= 90)}件")
    report.append(f"**180日以上**: {sum(1 for d in stagnant_deals if d['days'] >= 180)}件")
    report.append(f"**365日以上**: {sum(1 for d in stagnant_deals if d['days'] >= 365)}件\n")

    # 停滞の日数分布
    stag_buckets = {"30-60日": 0, "61-90日": 0, "91-180日": 0, "181-365日": 0, "365日超": 0}
    for d in stagnant_deals:
        days = d["days"]
        if days <= 60:
            stag_buckets["30-60日"] += 1
        elif days <= 90:
            stag_buckets["61-90日"] += 1
        elif days <= 180:
            stag_buckets["91-180日"] += 1
        elif days <= 365:
            stag_buckets["181-365日"] += 1
        else:
            stag_buckets["365日超"] += 1

    report.append("| 停滞期間 | 件数 |")
    report.append("|---------|------|")
    for bucket, count in stag_buckets.items():
        report.append(f"| {bucket} | {count} |")

    # ========================================
    # Part 4: 担当者別クロス分析
    # ========================================
    report.append("\n## 4. 担当者別クロス分析\n")

    owner_stages = defaultdict(lambda: Counter())
    owner_temps = defaultdict(lambda: Counter())
    owner_stagnant = defaultdict(int)

    for d in deals:
        f = d.get("fields", {})
        owner = extract_text(f.get("担当営業")) or "(未設定)"
        stage = extract_text(f.get("商談ステージ")) or "(未設定)"
        temp = extract_text(f.get("温度感スコア")) or "(未設定)"
        owner_stages[owner][stage] += 1
        owner_temps[owner][temp] += 1

        updated = f.get("商談日") or f.get("次アクション日")
        if updated:
            updated_dt = ms_to_date(updated)
            if updated_dt and (now - updated_dt).days > 90:
                owner_stagnant[owner] += 1

    for owner in sorted(owner_stages.keys()):
        total = sum(owner_stages[owner].values())
        report.append(f"### {owner}（{total}件）\n")

        report.append("**ステージ別**:")
        for stage, count in owner_stages[owner].most_common():
            report.append(f"- {stage}: {count}件")

        report.append(f"\n**温度感別**:")
        for temp, count in owner_temps[owner].most_common():
            report.append(f"- {temp}: {count}件")

        report.append(f"\n**90日以上停滞**: {owner_stagnant.get(owner, 0)}件\n")

    # ========================================
    # Part 5: 取引先・連絡先分析
    # ========================================
    accounts = all_data.get("取引先", [])
    contacts = all_data.get("連絡先", [])

    report.append("## 5. 取引先・連絡先分析\n")
    report.append(f"**取引先数**: {len(accounts)}件")
    report.append(f"**連絡先数**: {len(contacts)}件\n")

    # 連絡先のメール・電話充填率
    contact_email_filled = 0
    contact_phone_filled = 0
    for c in contacts:
        f = c.get("fields", {})
        if f.get("メールアドレス"):
            contact_email_filled += 1
        # 電話のフィールド名候補
        for phone_key in ["電話番号", "電話", "携帯", "TEL"]:
            if f.get(phone_key):
                contact_phone_filled += 1
                break

    if contacts:
        report.append(f"- メールアドレス充填率: {contact_email_filled}/{len(contacts)} ({contact_email_filled/len(contacts)*100:.1f}%)")
        report.append(f"- 電話番号充填率: {contact_phone_filled}/{len(contacts)} ({contact_phone_filled/len(contacts)*100:.1f}%)")

    # ========================================
    # Part 6: 受注台帳分析
    # ========================================
    orders = all_data.get("受注台帳", [])
    report.append(f"\n## 6. 受注台帳分析\n")
    report.append(f"**受注件数**: {len(orders)}件\n")

    if orders:
        # 金額分布（フィールド名を探す）
        amount_field = None
        for f in all_fields.get("受注台帳", []):
            fname = f.get("field_name", "")
            if "金額" in fname or "売上" in fname or "受注" in fname:
                if f.get("type") in (2, 20):  # 数値 or 数式
                    amount_field = fname
                    break

        if amount_field:
            amounts = []
            for o in orders:
                val = o.get("fields", {}).get(amount_field)
                if isinstance(val, (int, float)) and val > 0:
                    amounts.append(val)

            if amounts:
                report.append(f"**金額フィールド**: {amount_field}")
                report.append(f"- 合計: {sum(amounts):,.0f}円")
                report.append(f"- 平均: {sum(amounts)/len(amounts):,.0f}円")
                report.append(f"- 最大: {max(amounts):,.0f}円")
                report.append(f"- 最小: {min(amounts):,.0f}円")
                report.append(f"- 件数（金額あり）: {len(amounts)}件")

    # ========================================
    # Part 7: メールログ分析
    # ========================================
    emails = all_data.get("メールログ", [])
    report.append(f"\n## 7. メールログ分析\n")
    report.append(f"**総送信数**: {len(emails)}件\n")

    if emails:
        # 送信日の分布
        email_months = Counter()
        for e in emails:
            f = e.get("fields", {})
            for date_key in ["送信日", "日付", "作成日時"]:
                dt_val = f.get(date_key)
                if dt_val:
                    dt = ms_to_date(dt_val)
                    if dt:
                        email_months[dt.strftime("%Y-%m")] += 1
                    break

        if email_months:
            report.append("**月別送信数**:")
            report.append("| 月 | 件数 |")
            report.append("|----|------|")
            for month in sorted(email_months.keys()):
                report.append(f"| {month} | {email_months[month]} |")

    # ========================================
    # Part 8: 面談管理分析
    # ========================================
    meetings = all_data.get("面談管理", [])
    report.append(f"\n## 8. 面談管理分析\n")
    report.append(f"**面談記録数**: {len(meetings)}件\n")

    # ========================================
    # Part 9: 次アクション選択肢の全リスト
    # ========================================
    report.append("## 9. 次アクション選択肢の全リスト\n")
    report.append("現在の選択肢を整理し、統合案を提示する根拠データ。\n")

    # フィールド定義から選択肢を取得
    deal_fields = all_fields.get("商談", [])
    for f in deal_fields:
        if f.get("field_name") == "次アクション":
            options = (f.get("property") or {}).get("options", [])
            report.append(f"**定義済み選択肢数**: {len(options)}\n")
            if options:
                report.append("| # | 選択肢名 |")
                report.append("|---|---------|")
                for i, opt in enumerate(options, 1):
                    report.append(f"| {i} | {opt.get('name', '?')} |")
            break

    # ========================================
    # Part 10: 商談ステージの選択肢
    # ========================================
    report.append("\n## 10. 商談ステージの選択肢\n")
    for f in deal_fields:
        if f.get("field_name") == "商談ステージ":
            options = (f.get("property") or {}).get("options", [])
            report.append(f"**定義済みステージ数**: {len(options)}\n")
            if options:
                report.append("| # | ステージ名 |")
                report.append("|---|-----------|")
                for i, opt in enumerate(options, 1):
                    report.append(f"| {i} | {opt.get('name', '?')} |")
            break

    # ========================================
    # Part 11: 温度感の選択肢
    # ========================================
    report.append("\n## 11. 温度感の選択肢\n")
    for f in deal_fields:
        if f.get("field_name") == "温度感スコア":
            options = (f.get("property") or {}).get("options", [])
            report.append(f"**定義済み選択肢数**: {len(options)}\n")
            if options:
                for opt in options:
                    report.append(f"- {opt.get('name', '?')}")
            break

    # ========================================
    # Part 12: 全フィールド定義一覧（商談テーブル）
    # ========================================
    report.append("\n## 12. 商談テーブル フィールド定義一覧\n")
    report.append("| # | フィールド名 | 型 | 選択肢数/備考 |")
    report.append("|---|------------|-----|-------------|")
    type_names = {1: "テキスト", 2: "数値", 3: "単一選択", 4: "複数選択",
                 5: "日付", 7: "チェック", 11: "人", 13: "電話", 15: "URL",
                 17: "添付", 18: "リンク", 19: "ルックアップ", 20: "数式",
                 21: "自動番号", 22: "作成日時", 23: "更新日時", 1001: "作成者", 1002: "更新者"}

    for i, f in enumerate(deal_fields, 1):
        fname = f.get("field_name", "?")
        ftype = f.get("type", "?")
        type_label = type_names.get(ftype, f"type{ftype}")
        options = (f.get("property") or {}).get("options", [])
        note = f"{len(options)}選択肢" if options else ""
        report.append(f"| {i} | {fname} | {type_label} | {note} |")

    # ========================================
    # Part 13: データ品質スコア
    # ========================================
    report.append("\n## 13. データ品質スコア\n")

    scores = {}

    # 商談ステージ充填率
    stage_filled = sum(1 for d in deals if extract_text(d.get("fields", {}).get("商談ステージ")))
    scores["商談ステージ充填率"] = stage_filled / len(deals) * 100 if deals else 0

    # 次アクション充填率
    action_filled = sum(1 for d in deals if extract_text(d.get("fields", {}).get("次アクション")))
    scores["次アクション充填率"] = action_filled / len(deals) * 100 if deals else 0

    # 温度感充填率
    temp_filled = sum(1 for d in deals if extract_text(d.get("fields", {}).get("温度感スコア")))
    scores["温度感充填率"] = temp_filled / len(deals) * 100 if deals else 0

    # 連絡先メール充填率
    scores["連絡先メール充填率"] = contact_email_filled / len(contacts) * 100 if contacts else 0

    # 停滞率（90日以上）
    stagnant_90 = sum(1 for d in stagnant_deals if d["days"] >= 90)
    scores["非停滞率（90日基準）"] = (1 - stagnant_90 / len(deals)) * 100 if deals else 0

    total_score = sum(scores.values()) / len(scores) if scores else 0

    report.append(f"**総合スコア: {total_score:.1f} / 100**\n")
    report.append("| 指標 | スコア | 評価 |")
    report.append("|------|--------|------|")
    for metric, score in scores.items():
        if score >= 80:
            grade = "良好"
        elif score >= 50:
            grade = "要改善"
        else:
            grade = "深刻"
        report.append(f"| {metric} | {score:.1f} | {grade} |")

    # ========================================
    # Part 14: 改善提案
    # ========================================
    report.append("\n---\n")
    report.append("## 14. 改善提案\n")

    report.append("### 優先度1: 即時対応（1週間以内）\n")
    report.append("#### 1-1. ステージ未設定商談の一括クリーンアップ")
    report.append(f"- **対象**: {stage_counter.get('(未設定)', 0)}件のステージ未設定商談")
    report.append("- **方法**: 温度感・最終更新日を基準に自動分類スクリプトを作成")
    report.append("  - 180日以上更新なし → 「失注/見込みなし」")
    report.append("  - Cold + 90日以上 → 「休眠」")
    report.append("  - Hot/Warm → 担当者に個別確認")
    report.append("- **効果**: パイプラインの実態が見える化される\n")

    report.append("#### 1-2. Hot/Warm案件の次アクション日設定")
    report.append(f"- **対象**: {len(hot_warm_no_action_date)}件")
    report.append("- **方法**: 担当者にリストを送付し、1件ずつ次アクション日を設定")
    report.append("- **効果**: フォローアップ漏れの防止\n")

    report.append("### 優先度2: 短期改善（1ヶ月以内）\n")
    report.append("#### 2-1. 次アクション選択肢の統合")
    na_count = len(next_action_counter)
    report.append(f"- **現状**: {na_count}種類の選択肢（多すぎて運用不可能）")
    report.append("- **提案**: 10種類以下に統合")
    report.append("  - 電話フォロー / メール送付 / 見積作成 / 訪問・面談 / 資料送付")
    report.append("  - 提案書作成 / 契約手続き / 納品調整 / 顧客対応待ち / クローズ確認")
    report.append("- **効果**: 入力の標準化、レポート分析の精度向上\n")

    report.append("#### 2-2. 商談ステージの再定義")
    report.append("- **提案ステージ**: リード → ヒアリング → 見積提出 → 交渉中 → 受注 → 失注 → 休眠")
    report.append("- **各ステージに必須フィールドを設定**:")
    report.append("  - ヒアリング: 課題・ニーズ入力必須")
    report.append("  - 見積提出: 見積金額必須")
    report.append("  - 受注/失注: 結果理由必須\n")

    report.append("#### 2-3. 受注時自動フロー設計")
    report.append("- ステージ「受注」に変更時:")
    report.append("  1. 受注台帳にレコード自動作成")
    report.append("  2. お礼メール下書き生成")
    report.append("  3. 請求書作成トリガー")
    report.append("  4. Lark通知（CEO・チーム）\n")

    report.append("#### 2-4. 失注→リサイクルフロー設計")
    report.append("- ステージ「失注」に変更時:")
    report.append("  1. 失注理由の入力を必須化")
    report.append("  2. 90日後に自動で「休眠→再アプローチ」リストへ")
    report.append("  3. 温度感をColdに自動変更")
    report.append("  4. リサイクル候補リストを月次で営業に送付\n")

    report.append("### 優先度3: 中期改善（3ヶ月以内）\n")
    report.append("#### 3-1. 連絡先データ補完")
    report.append(f"- メール未設定: {len(contacts) - contact_email_filled}件")
    report.append("- 名刺OCR・メール署名からの自動抽出を活用")
    report.append("- 重複チェック・名寄せの実施\n")

    report.append("#### 3-2. KPIダッシュボード構築")
    report.append("- 週次自動レポートに以下を追加:")
    report.append("  - ステージ進捗率（新規→ヒアリング変換率等）")
    report.append("  - アクション実行率（期限内の次アクション完了率）")
    report.append("  - 停滞商談の増減トレンド")
    report.append("  - 担当者別パフォーマンス\n")

    report.append("#### 3-3. 営業プロセス標準化")
    report.append("- 初回接触から受注までの標準フローを文書化")
    report.append("- 各ステージでの必須アクション・期限を明確化")
    report.append("- CRMモニター（lark_crm_monitor.py）にプロセス逸脱検知を追加\n")

    report.append("---\n")
    report.append(f"*監査完了: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")

    # ファイル出力
    output = "\n".join(report)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(f"\n=== レポート出力完了: {OUTPUT_PATH} ===")
    print(f"総行数: {len(report)}")

    # サマリーをコンソールにも出力
    print(f"\n--- サマリー ---")
    print(f"総合スコア: {total_score:.1f}/100")
    for metric, score in scores.items():
        print(f"  {metric}: {score:.1f}")
    print(f"商談数: {len(deals)}, ステージ未設定: {stage_counter.get('(未設定)', 0)}")
    print(f"停滞(90日超): {stagnant_90}, Hot/Warm次アクション日未設定: {len(hot_warm_no_action_date)}")


if __name__ == "__main__":
    main()
