#!/usr/bin/env python3
"""
週次営業レポート（担当別カスタマイズ版）
Hot商談のフォローメール案 + Warm商談の架電トーク例 + 未接触取引先TOP3

Usage:
  python3 weekly_sales_report.py              # ドライラン（生成のみ、メール送信なし）
  python3 weekly_sales_report.py --send       # メール送信
  python3 weekly_sales_report.py --rep 政木   # 特定担当のみ
  python3 weekly_sales_report.py --send --rep 新美  # 新美分のみ送信

cron: 毎週木曜 08:00 JST → GitHub Actions
"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

# Config: prefer real credentials
for _p in [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]:
    if _p.exists():
        with open(_p) as f:
            _cfg = json.load(f)
        if not str(_cfg.get("lark", {}).get("app_id", "")).startswith("${"):
            CONFIG = _cfg
            break
else:
    raise FileNotFoundError("automation_config.json not found")

if "CONFIG" not in dir():
    CONFIG = _cfg

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]

# CRM table IDs
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# Sales rep config
SALES_REPS = {
    "新美 光": {
        "display": "新美",
        "full_name": "新美 光",
        "email": "h.niimi@tokaiair.com",
        "cc_ceo": True,  # CEOにもコピー送信
    },
    "ユーザー550372": {
        "display": "政木",
        "full_name": "政木 勇治",
        "email": "y-masaki@riseasone.jp",
        "cc_ceo": False,  # CEOはLark Mailで直接確認可能
    },
}

CEO_EMAIL = "yosuke.toyoda@gmail.com"

COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "services": [
        "ドローン測量（公共測量対応・i-Construction）",
        "3次元点群計測・図面化",
        "建物赤外線調査（外壁タイル浮き等）",
        "眺望撮影・空撮",
        "太陽光パネル点検",
    ],
}


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            d = result.get("data", {})
            records.extend(d.get("items", []))
            if not d.get("has_more"):
                break
            page_token = d.get("page_token")
            time.sleep(0.3)
    return records


# ── Field extraction helpers ──
def extract_text(field_value):
    """Lark Bitable各種フィールド値からテキストを抽出"""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        for item in field_value:
            if isinstance(item, dict):
                return item.get("text", "") or item.get("text_value", "") or ""
            if isinstance(item, str):
                return item
    return str(field_value or "")


def extract_rep_name(field_value):
    """担当営業フィールドから名前を取得"""
    if isinstance(field_value, list):
        for p in field_value:
            if isinstance(p, dict):
                return p.get("name", "")
            if isinstance(p, str):
                return p
    return str(field_value or "")


def resolve_company_name(fields):
    """取引先リンク → 商談名 → 新規取引先名の優先順で会社名を取得"""
    # 取引先リンク
    company_link = fields.get("取引先", [])
    if isinstance(company_link, list) and company_link:
        for item in company_link:
            if isinstance(item, dict):
                name = item.get("text", "") or ""
                if name:
                    return name
                arr = item.get("text_arr", [])
                if arr:
                    return arr[0]
    # 商談名
    deal_name = extract_text(fields.get("商談名", ""))
    if deal_name:
        return deal_name
    # 新規取引先名
    return extract_text(fields.get("新規取引先名", "")) or "(不明)"


# ── CRMデータ分析 ──
def classify_deals_by_rep(deals):
    """商談を担当別・温度感別に分類"""
    rep_deals = defaultdict(lambda: {"hot": [], "warm": [], "cold": []})

    for rec in deals:
        f = rec.get("fields", {})
        rep_name = extract_rep_name(f.get("担当営業", []))
        if rep_name not in SALES_REPS:
            continue

        stage = extract_text(f.get("商談ステージ", ""))
        if stage in ("不在", "失注", "受注", ""):
            continue

        temp = extract_text(f.get("温度感スコア", ""))
        company = resolve_company_name(f)

        hearing = extract_text(f.get("ヒアリング内容（まとめ）", ""))
        notes = extract_text(f.get("備考", ""))
        insight = extract_text(f.get("商談内での気づき・備考", ""))
        if insight and insight not in notes:
            notes = f"{notes}\n{insight}".strip() if notes else insight

        next_action = extract_text(f.get("次アクション", ""))
        next_action_other = extract_text(f.get("次アクション：その他", ""))
        combined_action = f"{next_action} {next_action_other}".strip()

        next_date = f.get("次アクション日")
        next_date_str = ""
        overdue = False
        if isinstance(next_date, (int, float)):
            next_dt = datetime.fromtimestamp(next_date / 1000)
            next_date_str = next_dt.strftime("%m/%d")
            overdue = next_dt < datetime.now()

        category = extract_text(f.get("客先カテゴリ", "")) or extract_text(f.get("客先カテゴリ：その他", ""))
        product = f.get("商材種別", f.get("商材", ""))
        if isinstance(product, list):
            product = ", ".join(str(p) for p in product)
        else:
            product = str(product or "")

        amount = f.get("見積・予算金額")
        amount_str = ""
        if amount:
            try:
                amount_str = f"¥{float(amount):,.0f}"
            except:
                pass

        deal_info = {
            "record_id": rec.get("record_id", ""),
            "company": company,
            "stage": stage,
            "temp": temp,
            "category": category,
            "product": product,
            "hearing": hearing,
            "notes": notes,
            "next_action": combined_action,
            "next_date": next_date_str,
            "overdue": overdue,
            "amount": amount_str,
        }

        if temp == "Hot":
            rep_deals[rep_name]["hot"].append(deal_info)
        elif temp == "Warm":
            rep_deals[rep_name]["warm"].append(deal_info)
        else:
            rep_deals[rep_name]["cold"].append(deal_info)

    return rep_deals


def find_untouched_accounts(deals, accounts):
    """全取引先のうち、商談が一度もない or 全て不在のものを優先度A候補として抽出"""
    # 既にアクティブ商談がある取引先名セット
    active_companies = set()
    for rec in deals:
        f = rec.get("fields", {})
        stage = extract_text(f.get("商談ステージ", ""))
        if stage not in ("不在", "失注", ""):
            company = resolve_company_name(f)
            active_companies.add(company)

    # 取引先マスタから未接触を抽出
    untouched = []
    for rec in accounts:
        f = rec.get("fields", {})
        company_name = extract_text(f.get("会社名", ""))
        if not company_name or company_name in active_companies:
            continue

        priority = extract_text(f.get("優先度", ""))
        category = extract_text(f.get("業種", "")) or extract_text(f.get("客先カテゴリ", ""))
        area = extract_text(f.get("エリア", "")) or extract_text(f.get("都道府県", ""))

        untouched.append({
            "company": company_name,
            "priority": priority,
            "category": category,
            "area": area,
        })

    # 優先度A → それ以外の順でソート
    untouched.sort(key=lambda x: (0 if x["priority"] == "A" else 1 if x["priority"] == "B" else 2))
    return untouched[:5]  # TOP5


def find_contact_for_company(contacts, company_name):
    """取引先名から連絡先を検索"""
    if not company_name:
        return None
    for rec in contacts:
        f = rec.get("fields", {})
        company = extract_text(f.get("会社名", ""))
        if company and company_name in company:
            return {
                "name": extract_text(f.get("氏名", "")),
                "title": extract_text(f.get("役職", "")),
                "email": extract_text(f.get("メールアドレス", "")),
                "phone": extract_text(f.get("電話番号", "")),
            }
        # 取引先リンクフィールドも確認
        account_link = extract_text(f.get("取引先", ""))
        if account_link and company_name in account_link:
            return {
                "name": extract_text(f.get("氏名", "")),
                "title": extract_text(f.get("役職", "")),
                "email": extract_text(f.get("メールアドレス", "")),
                "phone": extract_text(f.get("電話番号", "")),
            }
    return None


# ── Claude API ──
def generate_followup_email(deal, contact, rep_name):
    """Hot商談向けフォローメール案をClaude APIで生成"""
    rep_info = SALES_REPS.get(rep_name, {})
    contact_str = ""
    if contact:
        contact_str = f"{contact.get('name', '')} {contact.get('title', '')}様"

    prompt = f"""東海エアサービス株式会社の営業 {rep_info.get('full_name', rep_name)} として、
以下のHot商談に対するフォローメールの件名と本文を作成してください。

【商談情報】
- 会社名: {deal['company']} {contact_str}
- 商談ステージ: {deal['stage']}
- 関心商材: {deal['product']}
- 業種: {deal['category']}
- ヒアリング内容: {deal['hearing'] or '(なし)'}
- 備考: {deal['notes'] or '(なし)'}
- 次アクション: {deal['next_action']}
- 見積金額: {deal['amount'] or '(未定)'}

【ルール】
1. 件名は「件名：」で始める
2. 本文は300文字以内で簡潔に
3. ヒアリング内容に具体的に触れて信頼感を出す
4. 押し売りしない。次のステップを自然に提示
5. 敬語は丁寧すぎず、ビジネスライクに

【出力形式】
件名：〇〇〇
本文：
（メール本文）"""

    return _call_claude(prompt)


def generate_call_script(deal, contact, rep_name):
    """Warm商談向け架電トーク例をClaude APIで生成"""
    rep_info = SALES_REPS.get(rep_name, {})
    contact_str = ""
    if contact:
        contact_str = f"{contact.get('name', '')} {contact.get('title', '')}様"

    prompt = f"""東海エアサービス株式会社の営業 {rep_info.get('full_name', rep_name)} として、
以下のWarm商談に対する架電トーク例を作成してください。

【商談情報】
- 会社名: {deal['company']} {contact_str}
- 商談ステージ: {deal['stage']}
- 関心商材: {deal['product']}
- 業種: {deal['category']}
- ヒアリング内容: {deal['hearing'] or '(なし)'}
- 備考: {deal['notes'] or '(なし)'}
- 次アクション: {deal['next_action']}

【ルール】
1. 冒頭の名乗り → 用件 → ヒアリング内容への言及 → 提案 → クロージング の流れ
2. 200文字以内で簡潔に
3. 相手が忙しい前提で端的に用件を伝える
4. 「〜の件で」と具体的に切り出す

【出力形式】
（トーク例をそのまま出力）"""

    return _call_claude(prompt)


def generate_cold_call_script(account, rep_name):
    """未接触取引先向けコールドコール台本をClaude APIで生成"""
    rep_info = SALES_REPS.get(rep_name, {})

    prompt = f"""東海エアサービス株式会社の営業 {rep_info.get('full_name', rep_name)} として、
まだ接触したことがない取引先への初回架電トーク例を作成してください。

【取引先情報】
- 会社名: {account['company']}
- 業種: {account.get('category', '(不明)')}
- エリア: {account.get('area', '(不明)')}

【東海エアサービスのサービス】
- ドローン測量（公共測量対応・i-Construction）
- 3次元点群計測・図面化
- 建物赤外線調査（外壁タイル浮き等）

【ルール】
1. 150文字以内で端的に
2. 「お忙しいところ恐れ入ります」で始める
3. 相手の業種に合わせたサービスを1つだけ提案
4. 「資料だけでもお送りしてよろしいでしょうか」でクロージング

【出力形式】
（トーク例をそのまま出力）"""

    return _call_claude(prompt)


def _call_claude(prompt):
    """Claude API呼び出し"""
    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text
    except Exception as e:
        return f"[生成エラー: {e}]"


# ── メール送信 ──
def send_email_via_wordpress(to_email, subject, body):
    """WordPress wp_mail API経由でメール送信"""
    try:
        wp_config = CONFIG.get("wordpress", {})
        wp_base = wp_config.get("base_url", "").replace("/wp/v2", "")
        wp_user = wp_config.get("user", "")
        wp_pass = wp_config.get("app_password", "")
        if not all([wp_base, wp_user, wp_pass]):
            print(f"  WordPress config missing, email skipped: {to_email}")
            return False

        wp_auth = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
        endpoint = wp_base + "/tas/v1/send-email"
        data = json.dumps({
            "to": to_email,
            "subject": subject,
            "body": body,
            "from_name": "東海エアサービス",
            "from_email": "info@tokaiair.com",
        }).encode()
        req = urllib.request.Request(
            endpoint, data=data,
            headers={"Authorization": f"Basic {wp_auth}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("success", False)
    except Exception as e:
        print(f"  Email send error ({to_email}): {e}")
        return False


# ── レポート生成 ──
def build_report(rep_name, rep_deals, untouched_accounts, contacts):
    """担当別カスタマイズ週次レポートを生成"""
    rep_info = SALES_REPS[rep_name]
    now = datetime.now()
    lines = []

    lines.append(f"{'═'*50}")
    lines.append(f"  週次営業レポート（{rep_info['display']}担当分）")
    lines.append(f"  {now.strftime('%Y年%m月%d日')} 生成")
    lines.append(f"{'═'*50}")
    lines.append("")

    hot_deals = rep_deals.get("hot", [])
    warm_deals = rep_deals.get("warm", [])

    # AI生成の上限（API呼び出し数を制御）
    MAX_HOT_AI = 5    # Hot商談: 全件表示、AI生成は上位5件
    MAX_WARM_AI = 5   # Warm商談: 全件表示、AI生成は上位5件
    MAX_COLD_AI = 3   # 未接触: TOP3

    # ── Hot商談 ──
    lines.append(f"🔥 Hot商談: {len(hot_deals)}件")
    lines.append(f"{'─'*50}")

    if not hot_deals:
        lines.append("  現在Hot商談はありません。")
        lines.append("")
    else:
        for i, deal in enumerate(hot_deals, 1):
            contact = find_contact_for_company(contacts, deal["company"])
            overdue_mark = " ⚠期限超過" if deal["overdue"] else ""

            lines.append(f"\n  [{i}] {deal['company']}")
            lines.append(f"      ステージ: {deal['stage']} | 商材: {deal['product']}")
            if deal["amount"]:
                lines.append(f"      見積金額: {deal['amount']}")
            lines.append(f"      次アクション: {deal['next_action']} ({deal['next_date']}{overdue_mark})")

            # AI生成フォローメール（上位N件のみ）
            if i <= MAX_HOT_AI:
                lines.append(f"\n      【フォローメール案】(Claude生成)")
                email_draft = generate_followup_email(deal, contact, rep_name)
                for line in email_draft.split("\n"):
                    lines.append(f"      {line}")
                time.sleep(1)  # API rate limit
            lines.append("")

    # ── Warm商談 ──
    lines.append(f"\n🌤 Warm商談: {len(warm_deals)}件")
    lines.append(f"{'─'*50}")

    if not warm_deals:
        lines.append("  現在Warm商談はありません。")
        lines.append("")
    else:
        for i, deal in enumerate(warm_deals, 1):
            contact = find_contact_for_company(contacts, deal["company"])
            overdue_mark = " ⚠期限超過" if deal["overdue"] else ""

            lines.append(f"\n  [{i}] {deal['company']}")
            lines.append(f"      ステージ: {deal['stage']} | 商材: {deal['product']}")
            lines.append(f"      次アクション: {deal['next_action']} ({deal['next_date']}{overdue_mark})")

            # AI生成架電トーク例（上位N件のみ）
            if i <= MAX_WARM_AI:
                lines.append(f"\n      【架電トーク例】(Claude生成)")
                call_script = generate_call_script(deal, contact, rep_name)
                for line in call_script.split("\n"):
                    lines.append(f"      {line}")
                time.sleep(1)
            lines.append("")

    # ── 未接触取引先 TOP3 ──
    if untouched_accounts:
        lines.append(f"\n📋 優先度A・未接触取引先 TOP3")
        lines.append(f"{'─'*50}")

        for i, acc in enumerate(untouched_accounts[:MAX_COLD_AI], 1):
            lines.append(f"\n  [{i}] {acc['company']}")
            if acc["category"]:
                lines.append(f"      業種: {acc['category']}")
            if acc["area"]:
                lines.append(f"      エリア: {acc['area']}")

            # AI生成コールドコール台本
            lines.append(f"\n      【初回架電トーク例】(Claude生成)")
            cold_script = generate_cold_call_script(acc, rep_name)
            for line in cold_script.split("\n"):
                lines.append(f"      {line}")
            lines.append("")
            time.sleep(1)

    # ── フッター ──
    lines.append(f"\n{'═'*50}")
    lines.append(f"  東海エアサービス株式会社 営業支援AI")
    lines.append(f"  ※ メール案・トーク例はAI自動生成です。")
    lines.append(f"    適宜修正のうえご活用ください。")
    lines.append(f"{'═'*50}")

    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    send_mode = "--send" in args
    target_rep = None
    if "--rep" in args:
        idx = args.index("--rep")
        if idx + 1 < len(args):
            target_rep = args[idx + 1]

    now = datetime.now()
    print(f"[{now.strftime('%H:%M:%S')}] 週次営業レポート生成")
    print(f"  モード: {'送信' if send_mode else 'ドライラン'}")
    if target_rep:
        print(f"  対象: {target_rep}")
    print()

    # CRMデータ取得
    print("  CRMデータ取得中...")
    token = lark_get_token()
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f"  商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")

    # 商談を担当別に分類
    rep_deals = classify_deals_by_rep(deals)

    # 未接触取引先
    untouched = find_untouched_accounts(deals, accounts)
    print(f"  未接触取引先候補: {len(untouched)}件")

    # 担当別レポート生成・送信
    for rep_name, rep_info in SALES_REPS.items():
        display = rep_info["display"]

        # フィルタリング
        if target_rep and target_rep not in (display, rep_name, rep_info["full_name"]):
            continue

        print(f"\n{'='*60}")
        print(f"  {display} レポート生成中...")

        hot_count = len(rep_deals[rep_name].get("hot", []))
        warm_count = len(rep_deals[rep_name].get("warm", []))
        print(f"  Hot: {hot_count}件 / Warm: {warm_count}件")

        if hot_count == 0 and warm_count == 0 and not untouched:
            print(f"  → 対象商談なし、スキップ")
            continue

        # レポート生成（Claude API呼び出し含む）
        report = build_report(rep_name, rep_deals[rep_name], untouched, contacts)
        print(f"\n{report}")

        # ファイル保存
        date_str = now.strftime("%Y%m%d")
        report_file = SCRIPT_DIR / f"weekly_reports/{date_str}_{display}.txt"
        report_file.parent.mkdir(exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\n  保存: {report_file}")

        # メール送信
        if send_mode:
            subject = f"【週次レポート】{display}担当分 — {now.strftime('%m/%d')}"

            # 担当者に送信
            sent = send_email_via_wordpress(rep_info["email"], subject, report)
            if sent:
                print(f"  → {display}({rep_info['email']}) 送信完了 ✅")
            else:
                print(f"  → {display}({rep_info['email']}) 送信失敗 ❌")

            # CEOにもコピー送信（新美分など）
            if rep_info.get("cc_ceo"):
                sent_ceo = send_email_via_wordpress(CEO_EMAIL, f"[CC] {subject}", report)
                if sent_ceo:
                    print(f"  → CEO({CEO_EMAIL}) CC送信完了 ✅")
                else:
                    print(f"  → CEO({CEO_EMAIL}) CC送信失敗 ❌")

    # ログ保存
    log_file = SCRIPT_DIR / "weekly_sales_report.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{now.isoformat()}] Report generated (send={send_mode})\n")

    print(f"\n[完了] {now.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
