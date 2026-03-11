#!/usr/bin/env python3
"""
AIバリューアップ事業部 メールナーチャリング自動化

LP問い合わせ → 5段階メールシーケンスを自動送信

Day 0:  サンクスメール（即時）
Day 3:  事例共有（自社12自動化の実績）
Day 7:  課題提起（簡易診断チェックリスト）
Day 14: 比較（SIer/SaaS vs 本プログラム）
Day 21: 限定オファー（パイロット特別条件）

Usage:
  python3 ai_valueup_nurture.py --scan      # 新規リードをスキャン→Day0送信
  python3 ai_valueup_nurture.py --send      # シーケンスメール送信
  python3 ai_valueup_nurture.py --list      # リード一覧
  python3 ai_valueup_nurture.py --dry       # ドライラン（送信しない）
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

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "ai_valueup_nurture_state.json"
TABLE_IDS_FILE = SCRIPT_DIR / "ai_valueup_table_ids.json"
LOG_FILE = SCRIPT_DIR / "ai_valueup_nurture.log"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]
WP_BASE_URL = CONFIG["wordpress"]["base_url"].replace("/wp/v2", "")
WP_USER = CONFIG["wordpress"]["user"]
WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]

CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"
CEO_EMAIL = "yosuke.toyoda@gmail.com"

BASE_URL = "https://open.larksuite.com/open-apis"

# Sequence timing (days from first contact)
SEQUENCE = [
    {"stage": "day0",  "days": 0,  "subject_hint": "お問い合わせありがとうございます"},
    {"stage": "day3",  "days": 3,  "subject_hint": "AI自動化で変わった会社の実例"},
    {"stage": "day7",  "days": 7,  "subject_hint": "御社の業務、何%が自動化できるか？"},
    {"stage": "day14", "days": 14, "subject_hint": "SIer vs SaaS vs AI自動化：コスト比較"},
    {"stage": "day21", "days": 21, "subject_hint": "パイロット案件 特別条件のご案内"},
]

# ─── Lark API ────────────────────────────────────────

def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def api_get(token, path):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_post(token, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  API Error {e.code}: {err[:200]}")
        return {"code": e.code, "msg": err}


def get_lead_table_id():
    """Get AI_VU_リード table ID"""
    if TABLE_IDS_FILE.exists():
        with open(TABLE_IDS_FILE) as f:
            ids = json.load(f)
        return ids.get("AI_VU_リード")
    return None


def get_all_leads(token, table_id):
    """Fetch all leads from AI_VU_リード table"""
    records = []
    page_token = None
    while True:
        url = f"/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        res = api_get(token, url)
        data = res.get("data", {})
        records.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        time.sleep(0.3)
    return records


# ─── State Management ────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─── Email Generation (Claude API) ────────────────────

def generate_email(stage, lead_info):
    """Generate nurture email using Claude API"""

    prompts = {
        "day0": f"""あなたは東海エアサービス株式会社の代表・國本洋輔として、AI業務自動化サービスへの問い合わせに対するサンクスメールを書いてください。

問い合わせ者情報:
- 会社名: {lead_info.get('company', '不明')}
- 担当者名: {lead_info.get('name', '不明')}
- 関心業種: {lead_info.get('industry', '不明')}

要件:
- 丁寧だが堅すぎない文体
- 問い合わせへの感謝
- 簡潔に当社のAI業務自動化サービスを紹介（1-2行）
- 面談の候補日を提案（「来週のご都合はいかがでしょうか」程度）
- 署名は不要（別途付与）
- 件名と本文を出力。件名は「件名:」、本文は「本文:」で始めてください""",

        "day3": f"""あなたは東海エアサービス株式会社の代表・國本洋輔として、3日前に問い合わせがあった方へのフォローメールを書いてください。テーマは「AI自動化の実例」です。

相手:
- 会社名: {lead_info.get('company', '不明')}
- 担当者名: {lead_info.get('name', '不明')}

内容に含めること:
- 自社（ドローン測量会社・社員数名）で12の自動化を構築した実績
- 具体例を3つ程度（CRM監視15分→即通知、レポート作成2時間→0、見積30分→即時 等）
- 全てサーバー代ゼロ、月額約5,000円で運営
- コードは1行も書いていない事実
- 押し売りにならないトーン
- 件名と本文を出力。件名は「件名:」、本文は「本文:」で始めてください""",

        "day7": f"""あなたは東海エアサービス株式会社の代表・國本洋輔として、1週間前に問い合わせがあった方に「業務自動化の可能性を考える」メールを書いてください。

相手:
- 会社名: {lead_info.get('company', '不明')}
- 担当者名: {lead_info.get('name', '不明')}
- 関心業種: {lead_info.get('industry', '不明')}

内容:
- 「属人的な業務」と「自動化可能な業務」の違いを簡潔に説明
- 相手の業種に合わせた自動化可能業務を3-4個列挙
- 「30分のオンライン面談で、どの業務が自動化可能か無料で診断します」というオファー
- 件名と本文を出力。件名は「件名:」、本文は「本文:」で始めてください""",

        "day14": f"""あなたは東海エアサービス株式会社の代表・國本洋輔として、2週間前に問い合わせがあった方に「コスト比較」メールを書いてください。

相手:
- 会社名: {lead_info.get('company', '不明')}
- 担当者名: {lead_info.get('name', '不明')}

内容:
- SIer/システム開発（初期500-1000万、保守月10万〜、6ヶ月〜1年）
- SaaS複数導入（導入支援50万〜、月5-15万、3ヶ月〜）
- 当社AI自動化（個別見積、1-3ヶ月で完了）
- なぜ今このコスト構造が可能になったか（2025年以降のAI技術革新）
- 「具体的なお見積りをご希望でしたらお気軽にどうぞ」
- 件名と本文を出力。件名は「件名:」、本文は「本文:」で始めてください""",

        "day21": f"""あなたは東海エアサービス株式会社の代表・國本洋輔として、3週間前に問い合わせがあった方に最終フォローメールを書いてください。

相手:
- 会社名: {lead_info.get('company', '不明')}
- 担当者名: {lead_info.get('name', '不明')}

内容:
- パイロット案件として特別条件で実施可能であること
- 「まずは1つの業務から試してみませんか」という軽いトーン
- 期限を区切る（「今月中のお申込みで」等）
- しつこくならない程度に、最後のプッシュ
- 「ご不要でしたらお手数ですがその旨ご返信ください」
- 件名と本文を出力。件名は「件名:」、本文は「本文:」で始めてください""",
    }

    prompt = prompts.get(stage)
    if not prompt:
        return None, None

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        text = result["content"][0]["text"]

        # Parse subject and body
        subject = ""
        body = ""
        if "件名:" in text:
            parts = text.split("本文:", 1)
            subject = parts[0].replace("件名:", "").strip()
            body = parts[1].strip() if len(parts) > 1 else ""
        else:
            body = text
            subject = SEQUENCE[[s["stage"] for s in SEQUENCE].index(stage)]["subject_hint"]

        return subject, body
    except Exception as e:
        print(f"  Claude API error: {e}")
        return None, None


# ─── Email Sending (WordPress wp_mail) ────────────────

def send_email(to_email, subject, body, to_name=""):
    """Send email via WordPress REST API"""
    signature = "\n\n---\n國本洋輔\n東海エアサービス株式会社\nTEL: 050-7117-7141\nhttps://www.tokaiair.com/services/ai-valueup/"

    full_body = body + signature

    wp_auth = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    data = json.dumps({
        "to": to_email,
        "subject": subject,
        "body": full_body,
        "from_name": "國本洋輔 / 東海エアサービス",
        "from_email": CEO_EMAIL,
    }).encode()

    req = urllib.request.Request(
        f"{WP_BASE_URL}/tas/v1/send-email",
        data=data,
        headers={
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        if result.get("success"):
            print(f"  ✓ メール送信成功: {to_email}")
            return True
        else:
            print(f"  ✗ メール送信失敗: {result}")
            return False
    except Exception as e:
        print(f"  ✗ メール送信エラー: {e}")
        return False


# ─── Lark Bot Notification ────────────────────────────

def send_lark_dm(token, text):
    """Send DM to CEO via Lark Bot"""
    data = json.dumps({
        "receive_id": CEO_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception:
        pass


# ─── Main Logic ──────────────────────────────────────

def scan_new_leads(token, table_id, state, dry_run=False):
    """Scan for new leads and send Day 0 email"""
    leads = get_all_leads(token, table_id)
    new_count = 0

    for lead in leads:
        rid = lead["record_id"]
        fields = lead.get("fields", {})

        if rid in state:
            continue  # Already in sequence

        company = str(fields.get("会社名", "") or "")
        name = str(fields.get("担当者名", "") or "")
        email = str(fields.get("メール", "") or "")
        industry = str(fields.get("関心業種", "") or "")
        status = str(fields.get("ステータス", "") or "")

        if not email:
            print(f"  Skip {company}: メールなし")
            continue

        if status == "失注":
            continue

        print(f"\n  新規リード: {company} / {name} / {email}")

        lead_info = {"company": company, "name": name, "industry": industry}

        if dry_run:
            print(f"  [DRY] Day 0 メール生成スキップ")
        else:
            subject, body = generate_email("day0", lead_info)
            if subject and body:
                sent = send_email(email, subject, body, to_name=name)
                if sent:
                    state[rid] = {
                        "company": company,
                        "name": name,
                        "email": email,
                        "industry": industry,
                        "first_contact": datetime.now().isoformat(),
                        "sent_stages": ["day0"],
                        "day0_sent_at": datetime.now().isoformat(),
                    }
                    new_count += 1

    return new_count


def send_sequence_emails(token, table_id, state, dry_run=False):
    """Send scheduled sequence emails"""
    sent_count = 0
    now = datetime.now()

    for rid, info in list(state.items()):
        first_contact = datetime.fromisoformat(info["first_contact"])
        sent_stages = info.get("sent_stages", [])
        days_elapsed = (now - first_contact).days

        for seq in SEQUENCE:
            stage = seq["stage"]
            target_days = seq["days"]

            if stage in sent_stages:
                continue

            if days_elapsed < target_days:
                continue

            # Time to send this stage
            company = info.get("company", "不明")
            email = info.get("email", "")
            name = info.get("name", "")

            if not email:
                continue

            print(f"\n  {company}: {stage} (Day {target_days}) 送信")
            lead_info = {
                "company": company,
                "name": name,
                "industry": info.get("industry", ""),
            }

            if dry_run:
                print(f"  [DRY] スキップ")
                continue

            subject, body = generate_email(stage, lead_info)
            if subject and body:
                sent = send_email(email, subject, body, to_name=name)
                if sent:
                    info["sent_stages"].append(stage)
                    info[f"{stage}_sent_at"] = now.isoformat()
                    sent_count += 1
                    time.sleep(1)  # Rate limit

    return sent_count


def list_leads(state):
    """Display all leads and their sequence status"""
    if not state:
        print("  リードなし")
        return

    for rid, info in state.items():
        company = info.get("company", "不明")
        email = info.get("email", "")
        stages = info.get("sent_stages", [])
        first = info.get("first_contact", "")[:10]
        progress = " → ".join(stages) if stages else "未送信"
        print(f"  {company:20s} {email:30s} {first} [{progress}]")


def main():
    scan = "--scan" in sys.argv
    send = "--send" in sys.argv
    list_mode = "--list" in sys.argv
    dry_run = "--dry" in sys.argv

    if not any([scan, send, list_mode]):
        # Default: scan + send
        scan = True
        send = True

    print("=" * 60)
    print("AIバリューアップ ナーチャリング")
    print("=" * 60)

    state = load_state()

    if list_mode:
        list_leads(state)
        return

    # Get Lark token and table ID
    token = get_token()
    table_id = get_lead_table_id()

    if not table_id:
        print("  ✗ AI_VU_リード テーブルIDが見つかりません")
        print("  先に ai_valueup_crm_setup.py を実行してください")
        sys.exit(1)

    total_new = 0
    total_sent = 0

    if scan:
        print("\n── 新規リードスキャン ──")
        total_new = scan_new_leads(token, table_id, state, dry_run=dry_run)
        print(f"\n  新規: {total_new}件")

    if send:
        print("\n── シーケンスメール送信 ──")
        total_sent = send_sequence_emails(token, table_id, state, dry_run=dry_run)
        print(f"\n  送信: {total_sent}件")

    save_state(state)

    # Notify CEO if anything happened
    if (total_new > 0 or total_sent > 0) and not dry_run:
        msg = f"🤖 AI ValueUp ナーチャリング\n新規: {total_new}件\nシーケンス送信: {total_sent}件"
        send_lark_dm(token, msg)

    print(f"\n完了。")


if __name__ == "__main__":
    main()
