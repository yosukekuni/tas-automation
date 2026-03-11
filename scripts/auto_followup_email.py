#!/usr/bin/env python3
"""
Hot/Warm案件 フォローメール自動生成
CRMのヒアリング内容・備考・録音ログをもとにClaude APIでメール文面を生成

Usage:
  python3 auto_followup_email.py              # ドライラン（生成のみ・送信しない）
  python3 auto_followup_email.py --send       # Lark Mail APIで送信（権限必要）
  python3 auto_followup_email.py --list       # 対象案件一覧のみ表示
  python3 auto_followup_email.py --deal ID    # 特定の商談IDだけ処理

cron（VPS上）:
  毎朝9時に実行 → 担当営業にドラフト通知 or 自動送信
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

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
OUTPUT_DIR = SCRIPT_DIR / "followup_drafts"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]

# CRM table IDs
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# Sales rep info
REP_SIGNATURES = {
    "新美 光": {
        "display": "新美 光",
        "email": "niimi@tokaiair.com",
        "phone": "",
    },
    "ユーザー550372": {
        "display": "政木 勇治",
        "email": "masaki@tokaiair.com",
        "phone": "",
    },
}

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


def find_followup_targets(deals):
    """Hot/Warm案件で次アクションがメールフォローのものを抽出"""
    targets = []
    now = datetime.now()

    for rec in deals:
        f = rec.get("fields", {})
        record_id = rec.get("record_id", "")

        # 温度感チェック
        temp = str(f.get("温度感スコア", "") or "")
        if temp not in ("Hot", "Warm"):
            continue

        # 次アクションチェック（両フィールドを確認）
        next_action = str(f.get("次アクション", "") or "")
        next_action_other_raw = f.get("次アクション：その他", "")
        if isinstance(next_action_other_raw, list) and next_action_other_raw:
            next_action_other = next_action_other_raw[0].get("text", "") if isinstance(next_action_other_raw[0], dict) else str(next_action_other_raw[0])
        else:
            next_action_other = str(next_action_other_raw or "")
        combined_action = f"{next_action} {next_action_other}".strip()
        if not any(kw in combined_action for kw in ["メール", "フォロー", "連絡", "提案", "見積"]):
            continue

        # ステージが不在・失注は除外
        stage = str(f.get("商談ステージ", "") or "")
        if stage in ("不在", "失注", ""):
            continue

        # 担当営業
        rep_field = f.get("担当営業", [])
        rep_name = ""
        if isinstance(rep_field, list):
            for p in rep_field:
                if isinstance(p, dict):
                    rep_name = p.get("name", "")
                elif isinstance(p, str):
                    rep_name = p

        # 次アクション日（期限チェック）
        next_date = f.get("次アクション日")
        overdue = False
        if isinstance(next_date, (int, float)):
            next_dt = datetime.fromtimestamp(next_date / 1000)
            overdue = next_dt < now

        # ヒアリング内容・備考を収集（list of text objects対応）
        hearing_raw = f.get("ヒアリング内容（まとめ）", "")
        if isinstance(hearing_raw, list) and hearing_raw and isinstance(hearing_raw[0], dict):
            hearing = hearing_raw[0].get("text", "")
        else:
            hearing = str(hearing_raw or "")

        notes_raw = f.get("備考", "")
        if isinstance(notes_raw, list) and notes_raw and isinstance(notes_raw[0], dict):
            notes = notes_raw[0].get("text", "")
        else:
            notes = str(notes_raw or "")

        # 商談内での気づき・備考も取得
        insight_raw = f.get("商談内での気づき・備考", "")
        if isinstance(insight_raw, list) and insight_raw and isinstance(insight_raw[0], dict):
            insight = insight_raw[0].get("text", "")
        elif isinstance(insight_raw, str):
            insight = insight_raw
        else:
            insight = str(insight_raw or "")
        if insight and insight not in notes:
            notes = f"{notes}\n{insight}".strip() if notes else insight

        deal_name_raw = f.get("商談名", "")
        if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
            deal_name = deal_name_raw[0].get("text", "") or "(名前なし)"
        else:
            deal_name = str(deal_name_raw or "(名前なし)")

        category = str(f.get("客先カテゴリ", "") or "")
        # 客先カテゴリ：その他 も確認
        if not category:
            cat_other_raw = f.get("客先カテゴリ：その他", "")
            if isinstance(cat_other_raw, list) and cat_other_raw and isinstance(cat_other_raw[0], dict):
                category = cat_other_raw[0].get("text", "")
            else:
                category = str(cat_other_raw or "")

        product_raw = f.get("商材種別", f.get("商材", ""))
        if isinstance(product_raw, list):
            product = ", ".join(str(p) for p in product_raw)
        else:
            product = str(product_raw or "")

        # 音声ファイル情報
        audio_files = []
        for key in f:
            val = f[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict) and item.get("name", "").endswith((".m4a", ".mp3", ".wav")):
                        audio_files.append(item.get("name", ""))

        # 取引先リンク
        account_links = f.get("取引先", [])
        account_id = ""
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    account_id = link.get("record_id", "")
                elif isinstance(link, str):
                    account_id = link

        targets.append({
            "record_id": record_id,
            "deal_name": deal_name,
            "stage": stage,
            "temp": temp,
            "rep_name": rep_name,
            "next_action": combined_action,
            "overdue": overdue,
            "hearing": hearing,
            "notes": notes,
            "category": category,
            "product": product,
            "audio_files": audio_files,
            "account_id": account_id,
            "fields": f,
        })

    return targets


def _extract_link_text(field_value):
    """リンクフィールドからテキスト値を抽出（list of objects対応）"""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        texts = []
        for item in field_value:
            if isinstance(item, dict):
                texts.append(item.get("text_value", "") or item.get("text", "") or "")
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts)
    return ""


def find_contact_for_account(contacts, account_name):
    """取引先名から連絡先を検索（会社名フィールド＋取引先リンクフィールド両方チェック）"""
    if not account_name:
        return None
    for rec in contacts:
        f = rec.get("fields", {})
        # 会社名フィールドで一致チェック
        company = str(f.get("会社名", "") or "")
        if account_name in company:
            return {
                "name": str(f.get("氏名", "") or ""),
                "title": str(f.get("役職", "") or ""),
                "email": str(f.get("メールアドレス", "") or ""),
                "phone": str(f.get("電話番号", "") or ""),
                "company": company,
            }
        # 取引先リンクフィールドで一致チェック
        account_link = f.get("取引先", "")
        account_link_text = _extract_link_text(account_link)
        if account_link_text and account_name in account_link_text:
            return {
                "name": str(f.get("氏名", "") or ""),
                "title": str(f.get("役職", "") or ""),
                "email": str(f.get("メールアドレス", "") or ""),
                "phone": str(f.get("電話番号", "") or ""),
                "company": account_link_text or company,
            }
    return None


def find_account_name(accounts, account_id):
    """取引先IDから会社名を取得"""
    for rec in accounts:
        if rec.get("record_id") == account_id:
            return str(rec.get("fields", {}).get("会社名", "") or "")
    return ""


def generate_email_with_claude(target, contact):
    """Claude APIでフォローメール生成"""
    rep_info = REP_SIGNATURES.get(target["rep_name"], {
        "display": target["rep_name"],
        "email": "",
        "phone": "",
    })

    # コンテキスト組み立て
    context_parts = []
    context_parts.append(f"商談先: {contact.get('company', target['deal_name'])} {contact.get('name', '')} {contact.get('title', '')} 様")
    context_parts.append(f"温度感: {target['temp']}")
    context_parts.append(f"商談ステージ: {target['stage']}")
    if target["category"]:
        context_parts.append(f"業種: {target['category']}")
    if target["product"]:
        context_parts.append(f"関心商材: {target['product']}")
    if target["hearing"]:
        context_parts.append(f"ヒアリング内容:\n{target['hearing']}")
    if target["notes"]:
        context_parts.append(f"備考:\n{target['notes']}")
    if target["audio_files"]:
        context_parts.append(f"録音ファイル: {', '.join(target['audio_files'])}（音声内容は上記ヒアリング内容に反映済み）")

    context = "\n".join(context_parts)

    prompt = f"""あなたは東海エアサービス株式会社の営業担当 {rep_info['display']} として、
商談後のフォローメールを作成してください。

【会社情報】
{COMPANY_INFO['name']}
サービス: {', '.join(COMPANY_INFO['services'])}
HP: {COMPANY_INFO['url']}

【商談コンテキスト】
{context}

【メール作成ルール】
1. 件名と本文を出力（件名は「件名：」で始める）
2. ヒアリング内容に基づいて具体的な提案や情報提供を含める
3. 相手の業種・関心に合わせた内容にする
4. 押し売りしない。相手のペースを尊重しつつ次のステップを提示
5. 簡潔に（300文字以内の本文）
6. 敬語は丁寧すぎず、ビジネスライクに
7. 署名は「{rep_info['display']}」で統一

【出力形式】
件名：〇〇〇
---
（本文）
---
署名:
{COMPANY_INFO['name']}
{rep_info['display']}
"""

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
        return f"[ERROR] Claude API failed: {e}"


def send_via_lark_mail(token, from_email, to_email, subject, body):
    """Lark Mail APIでメール送信（権限: mail:message:send 必要）"""
    # RFC 2822 形式のメール本文
    import base64
    raw_msg = f"From: {from_email}\r\nTo: {to_email}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}"
    encoded = base64.b64encode(raw_msg.encode()).decode()

    data = json.dumps({
        "to": [{"mail_address": to_email}],
        "subject": subject,
        "body": {"content": body},
    }).encode()

    # Note: actual Lark Mail API endpoint may differ
    req = urllib.request.Request(
        f"https://open.larksuite.com/open-apis/mail/v1/users/me/messages",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            return result.get("code") == 0
    except Exception as e:
        print(f"  Lark Mail send error: {e}")
        return False


def notify_rep_via_webhook(text):
    """Lark Webhookで担当営業に通知"""
    webhook = CONFIG.get("notifications", {}).get("lark_webhook_url", "")
    if not webhook:
        return False
    data = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
    req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        return True
    except:
        return False


def main():
    args = sys.argv[1:]
    send_mode = "--send" in args
    list_only = "--list" in args
    specific_deal = None
    if "--deal" in args:
        idx = args.index("--deal")
        if idx + 1 < len(args):
            specific_deal = args[idx + 1]

    print(f"[{datetime.now().strftime('%H:%M:%S')}] フォローメール自動生成")
    print(f"  モード: {'送信' if send_mode else '一覧のみ' if list_only else 'ドラフト生成'}")
    print()

    token = lark_get_token()

    # CRMデータ取得
    print("  CRMデータ取得中...")
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f"  商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")

    # フォロー対象抽出
    targets = find_followup_targets(deals)

    if specific_deal:
        targets = [t for t in targets if t["record_id"] == specific_deal]

    if not targets:
        print("\n  フォロー対象なし（Hot/Warm + メールフォロー該当なし）")
        return

    print(f"\n  フォロー対象: {len(targets)}件")
    print("  " + "─" * 50)

    for t in targets:
        rep_display = REP_SIGNATURES.get(t["rep_name"], {}).get("display", t["rep_name"])
        overdue_mark = " ⚠️期限超過" if t["overdue"] else ""
        print(f"  [{t['temp']}] {t['deal_name']} — {rep_display} — {t['next_action']}{overdue_mark}")

    if list_only:
        return

    # ドラフト出力先
    OUTPUT_DIR.mkdir(exist_ok=True)
    generated = []

    for t in targets:
        print(f"\n{'='*60}")
        print(f"  生成中: {t['deal_name']}")

        # 取引先名取得
        account_name = ""
        if t["account_id"]:
            account_name = find_account_name(accounts, t["account_id"])

        # 連絡先検索
        contact = None
        search_name = account_name or t["deal_name"]
        contact = find_contact_for_account(contacts, search_name)

        if not contact:
            # deal_nameから会社名を推測して再検索
            for rec in contacts:
                cf = rec.get("fields", {})
                company = str(cf.get("会社名", "") or "")
                if company and company in t["deal_name"]:
                    contact = {
                        "name": str(cf.get("氏名", "") or ""),
                        "title": str(cf.get("役職", "") or ""),
                        "email": str(cf.get("メールアドレス", "") or ""),
                        "phone": str(cf.get("電話番号", "") or ""),
                        "company": company,
                    }
                    break

        if not contact:
            contact = {
                "name": "",
                "title": "ご担当者",
                "email": "",
                "phone": "",
                "company": search_name or t["deal_name"],
            }

        # Claude APIでメール生成
        email_text = generate_email_with_claude(t, contact)
        print(f"\n{email_text}")

        # ファイル保存
        timestamp = datetime.now().strftime("%Y%m%d")
        if t["deal_name"] in ("(名前なし)", "") or not t["deal_name"].strip():
            # record_idベースでユニークなファイル名を生成
            safe_account = account_name.replace("/", "_").replace(" ", "_")[:20] if account_name else ""
            rid = t["record_id"][:8]
            if safe_account:
                draft_file = OUTPUT_DIR / f"{timestamp}_{safe_account}_{rid}.txt"
            else:
                draft_file = OUTPUT_DIR / f"{timestamp}_{rid}.txt"
        else:
            safe_name = t["deal_name"].replace("/", "_").replace(" ", "_")[:30]
            draft_file = OUTPUT_DIR / f"{timestamp}_{safe_name}.txt"
        with open(draft_file, "w", encoding="utf-8") as df:
            df.write(f"商談ID: {t['record_id']}\n")
            df.write(f"宛先: {contact.get('email', '不明')}\n")
            df.write(f"担当: {REP_SIGNATURES.get(t['rep_name'], {}).get('display', t['rep_name'])}\n")
            df.write(f"温度感: {t['temp']}\n")
            df.write(f"生成日: {datetime.now().isoformat()}\n")
            df.write(f"\n{'='*50}\n\n")
            df.write(email_text)

        generated.append({
            "deal": t["deal_name"],
            "contact_email": contact.get("email", ""),
            "file": str(draft_file),
            "email_text": email_text,
        })

        # 送信モード
        if send_mode and contact.get("email"):
            # 件名抽出
            subject = ""
            for line in email_text.split("\n"):
                if line.startswith("件名：") or line.startswith("件名:"):
                    subject = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                    break

            if subject:
                print(f"\n  → 送信先: {contact['email']}")
                sent = send_via_lark_mail(token, "", contact["email"], subject, email_text)
                if sent:
                    print("  → 送信完了 ✅")
                else:
                    print("  → 送信失敗（Lark Mail権限を確認してください）")

        time.sleep(1)  # API rate limit

    # サマリー通知
    summary = f"📧 フォローメール自動生成完了\n\n"
    summary += f"対象: {len(generated)}件\n"
    for g in generated:
        summary += f"  - {g['deal']} → {g['contact_email'] or '(メール不明)'}\n"
    summary += f"\nドラフト保存先: {OUTPUT_DIR}/"

    print(f"\n{'='*60}")
    print(summary)

    # Webhook通知
    notify_rep_via_webhook(summary)

    # ログ保存
    log_file = SCRIPT_DIR / "followup_email.log"
    with open(log_file, "a", encoding="utf-8") as lf:
        lf.write(f"\n[{datetime.now().isoformat()}] Generated {len(generated)} emails\n")
        for g in generated:
            lf.write(f"  {g['deal']} → {g['contact_email']}\n")


if __name__ == "__main__":
    main()
