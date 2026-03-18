#!/usr/bin/env python3
"""
商談報告後 顧客向けサンクスメール自動送信（キュー方式）

2段階で動作:
  1. --queue: 新規商談検出→メール生成→キューに保存（crm_monitorと同タイミング/15分毎）
  2. --send:  キューから送信時刻が来たメールを送信（平日8:30/17:00のcron）

送信タイミングロジック:
  - 15:00前に報告 → 当日17:00に送信
  - 15:00以降に報告 → 翌営業日8:30に送信

Usage:
  python3 deal_thankyou_email.py --queue          # 新規商談→キュー保存
  python3 deal_thankyou_email.py --send           # キューから送信
  python3 deal_thankyou_email.py --dry-run        # キュー内容を表示（送信しない）
  python3 deal_thankyou_email.py --list           # キュー一覧
  python3 deal_thankyou_email.py --deal ID        # 特定商談のみ処理（即キュー追加）
  python3 deal_thankyou_email.py --deal-name "豊建,鶴田石材,徳倉建設"  # 商談名で検索→キュー追加
  python3 deal_thankyou_email.py --find-deals 豊建  # 商談名で検索→record_id表示
"""

import json
import os
import re
import sys
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "thankyou_state.json"
QUEUE_FILE = SCRIPT_DIR / "thankyou_queue.json"
LOG_FILE = SCRIPT_DIR / "thankyou_email.log"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]
WP_BASE_URL = CONFIG["wordpress"]["base_url"].replace("/wp/v2", "")
WP_USER = CONFIG["wordpress"]["user"]
WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]

# CRM Table IDs
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# 営業担当マッピング
SALES_REPS = {
    "新美 光": {
        "display": "新美 光",
        "email": "h.niimi@tokaiair.com",
        "open_id": "ou_189dc637b61a83b886d356becb3ae18e",
        "signature": "新美 光\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
    },
    "新美光": {
        "display": "新美 光",
        "email": "h.niimi@tokaiair.com",
        "open_id": "ou_189dc637b61a83b886d356becb3ae18e",
        "signature": "新美 光\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
    },
    "ユーザー550372": {
        "display": "政木 勇治",
        "email": "y-masaki@riseasone.jp",
        "open_id": None,
        "signature": "政木 勇治\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
    },
}

CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# セーフガード設定
MAX_SENDS_PER_DAY = 5          # 1日の送信上限
DUPLICATE_WINDOW_DAYS = 30     # 同一メールアドレスへの重複防止期間
CANCEL_KEYWORD = "キャンセル"   # Larkで返信するとキャンセル


# ── レビューエージェント連携 ──
def run_email_review(subject, body, to_email, from_email="info@tokaiair.com"):
    """送信前にreview_agent.pyのemailプロファイルでチェック。CRITICAL=送信中止"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from review_agent import review
        content = f"To: {to_email}\nFrom: {from_email}\nSubject: {subject}\n\n{body}"
        result = review("email", content, output_json=True)
        return result
    except Exception as e:
        print(f"  レビューエージェント実行エラー（送信は続行）: {e}")
        return {"verdict": "OK", "issues": [], "summary": f"レビュースキップ: {e}"}

COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "phone": "052-720-5885",
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


def send_lark_dm(token, open_id, text):
    if not open_id:
        return
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        data = json.dumps({
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": chunk})
        }).encode()
        req = urllib.request.Request(
            "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            print(f"  Lark DM error: {e.code} {e.read().decode()}")
        time.sleep(0.3)


def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
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


# ── State & Queue Management ──
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed_ids": [], "last_check": None}


def save_state(state):
    # Keep all IDs to prevent re-processing old deals
    # (Trimming to 300 caused 288 old deals to be re-detected every run)
    # Only trim if truly excessive (>2000)
    if len(state.get("processed_ids", [])) > 2000:
        state["processed_ids"] = state["processed_ids"][-1500:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_queue():
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ── 送信スケジュール計算 ──
def calc_send_time(detected_at=None):
    """
    送信タイミングを計算（JST）
    - 15:00前 → 当日17:00
    - 15:00以降 → 翌営業日8:30
    """
    now = detected_at or datetime.now()
    hour = now.hour

    if hour < 15:
        # 当日17:00
        send_at = now.replace(hour=17, minute=0, second=0, microsecond=0)
    else:
        # 翌営業日8:30
        next_day = now + timedelta(days=1)
        # 土日スキップ
        while next_day.weekday() >= 5:  # 5=土, 6=日
            next_day += timedelta(days=1)
        send_at = next_day.replace(hour=8, minute=30, second=0, microsecond=0)

    return send_at.isoformat()


# ── 連絡先からメールアドレス検索 ──
def _normalize_company(name):
    """会社名を正規化して比較しやすくする（株式会社/有限会社等を除去）"""
    if not name:
        return ""
    # 法人格を除去
    normalized = re.sub(r'(株式会社|有限会社|合同会社|一般社団法人|公益社団法人|（株）|\(株\))', '', name)
    # 空白・全角スペースを除去
    normalized = re.sub(r'[\s\u3000]+', '', normalized)
    return normalized.strip()


def _company_match(name_a, name_b):
    """会社名の柔軟なマッチング（双方向部分一致 + 正規化比較）"""
    if not name_a or not name_b:
        return False
    # そのまま部分一致（どちらかが含まれればOK）
    if name_a in name_b or name_b in name_a:
        return True
    # 正規化して比較
    norm_a = _normalize_company(name_a)
    norm_b = _normalize_company(name_b)
    if not norm_a or not norm_b:
        return False
    if norm_a in norm_b or norm_b in norm_a:
        return True
    return False


def _extract_contact_info(contact_record):
    """連絡先レコードからメール・氏名・会社名・役職を抽出"""
    cf = contact_record.get("fields", {})
    email = str(cf.get("メールアドレス", "") or "")
    if not email or "@" not in email:
        return None
    return {
        "email": email,
        "name": str(cf.get("氏名", "") or ""),
        "company": str(cf.get("会社名", "") or ""),
        "title": str(cf.get("役職", "") or ""),
    }


def find_customer_email(contacts, accounts, deal_fields):
    # 1. 商談に直接リンクされた連絡先
    contact_links = deal_fields.get("連絡先", [])
    if isinstance(contact_links, list):
        for link in contact_links:
            if isinstance(link, dict):
                rid = link.get("record_id", "")
                for c in contacts:
                    if c.get("record_id") == rid:
                        info = _extract_contact_info(c)
                        if info:
                            return info

    # 2. 取引先リンクから会社名を取得→連絡先を会社名で検索
    account_links = deal_fields.get("取引先", [])
    account_name = ""
    if isinstance(account_links, list):
        for link in account_links:
            if isinstance(link, dict):
                rid = link.get("record_id", "")
                for a in accounts:
                    if a.get("record_id") == rid:
                        account_name = str(a.get("fields", {}).get("会社名", "") or "")
                        break

    # 取引先リンクがない場合、新規取引先名フィールドも試す
    if not account_name:
        account_name = str(deal_fields.get("新規取引先名", "") or "")

    if account_name:
        for c in contacts:
            company = str(c.get("fields", {}).get("会社名", "") or "")
            if _company_match(account_name, company):
                info = _extract_contact_info(c)
                if info:
                    return info

    # 3. 商談名から推測（連絡先の会社名が商談名に含まれているか）
    deal_name_raw = deal_fields.get("商談名", "")
    if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
        deal_name = deal_name_raw[0].get("text", "") or ""
    else:
        deal_name = str(deal_name_raw or "")
    if deal_name:
        for c in contacts:
            company = str(c.get("fields", {}).get("会社名", "") or "")
            if company and _company_match(company, deal_name):
                info = _extract_contact_info(c)
                if info:
                    return info

    return None


# ── Claude API でサンクスメール生成 ──
def generate_thankyou_email(deal_fields, contact, rep_info):
    deal_name = str(deal_fields.get("商談名", "") or "")
    hearing = str(deal_fields.get("ヒアリング内容（まとめ）", "") or "")
    notes = str(deal_fields.get("備考", "") or "")
    category = str(deal_fields.get("客先カテゴリ", "") or "")
    product = str(deal_fields.get("商材", "") or "")
    stage = str(deal_fields.get("商談ステージ", "") or "")
    next_action = str(deal_fields.get("次アクション", "") or "")

    customer_name = contact.get("name", "") or "ご担当者"
    customer_company = contact.get("company", "") or deal_name
    customer_title = contact.get("title", "")

    context = f"""【商談情報】
商談先: {customer_company} {customer_name} {customer_title} 様
業種: {category or '未記載'}
関心商材: {product or '未記載'}
商談ステージ: {stage or '初回訪問'}
"""
    if hearing:
        context += f"\n【ヒアリング内容】\n{hearing}\n"
    if notes:
        context += f"\n【備考】\n{notes}\n"
    if next_action:
        context += f"\n【次のアクション】\n{next_action}\n"

    temp = str(deal_fields.get("温度感スコア", "") or "")
    is_cold = temp in ("Cold", "不在のため不明", "")

    tone_instruction = ""
    if is_cold:
        tone_instruction = """10. 温度感が低い（Cold/不在）商談なので、軽めのお礼にする。
    売り込みは一切しない。「本日はお時間いただきありがとうございました」程度。
    次のステップには触れず「何かございましたらお気軽にご連絡ください」で締める。
    本文は200文字以内。"""

    prompt = f"""あなたは{COMPANY_INFO['name']}の営業担当 {rep_info['display']} として、
本日の商談（打ち合わせ）後の顧客向けサンクスメールを作成してください。

{context}

【メール作成ルール】
1. 件名は「件名：」で始める
2. 本日の商談（訪問・打ち合わせ）へのお礼で始める
3. ヒアリング内容があれば、それに基づいた具体的な内容を含める
4. 次のステップがあれば触れる（見積、資料送付、現場確認等）
5. 次のステップがなければ「何かございましたらお気軽にご連絡ください」で締める
6. 押し売りしない。自然なビジネスメール
7. 本文は300文字以内。簡潔に。
8. AIっぽい表現を避ける。普通のビジネスメールの文体で。
9. 「つきましては」「さて」等の堅すぎる接続詞は使わない
{tone_instruction}

【出力形式】
件名：〇〇〇

（本文のみ。宛先の「○○様」から書き出し。署名は不要。）
"""

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
            "Content-Type": "application/json",
        }
    )

    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())
        return result["content"][0]["text"].strip()


def parse_email_text(email_text, rep_info):
    """Claude APIの出力から件名・本文を分離し、署名を追加"""
    subject = ""
    body_lines = []
    in_body = False
    for line in email_text.split("\n"):
        if line.startswith("件名：") or line.startswith("件名:"):
            subject = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if not in_body and not line.strip():
            in_body = True
            continue
        if in_body or line.strip():
            in_body = True
            body_lines.append(line)

    body = "\n".join(body_lines).strip()
    body += f"\n\n──────────────────\n{rep_info['signature']}"

    if not subject:
        subject = f"本日はありがとうございました - {COMPANY_INFO['name']}"

    return subject, body


# ── WordPress wp_mail で送信 ──
def send_email_via_wordpress(to_email, subject, body, from_name="東海エアサービス", from_email="info@tokaiair.com"):
    wp_auth = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    endpoint = WP_BASE_URL + "/tas/v1/send-email"

    data = json.dumps({
        "to": to_email,
        "subject": subject,
        "body": body,
        "from_name": from_name,
        "from_email": from_email,
    }).encode()

    req = urllib.request.Request(
        endpoint, data=data,
        headers={
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("success", False)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"  WordPress email error: {e.code} {body_text}")
        return False
    except Exception as e:
        print(f"  WordPress email error: {e}")
        return False


# ── セーフガード ──
def is_duplicate_email(queue, to_email):
    """同一メールアドレスに過去N日以内に送信済みならTrue"""
    cutoff = (datetime.now() - timedelta(days=DUPLICATE_WINDOW_DAYS)).isoformat()
    for item in queue:
        if item.get("to_email") == to_email and item.get("status") == "sent":
            sent_at = item.get("sent_at", "")
            if sent_at > cutoff:
                return True
    return False


def count_sent_today(queue):
    """今日の送信件数"""
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for q in queue if q.get("status") == "sent"
               and q.get("sent_at", "").startswith(today))


# ── 商談名で検索（--find-deals 用）──
def find_deals_by_name(search_term):
    """商談名・取引先名で検索して record_id を表示"""
    print(f"商談検索: '{search_term}'")
    token = lark_get_token()
    deals = get_all_records(token, TABLE_DEALS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)

    found = 0
    for rec in deals:
        fields = rec.get("fields", {})
        rid = rec.get("record_id", "")

        # 商談名
        deal_name_raw = fields.get("商談名", "")
        if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
            deal_name = deal_name_raw[0].get("text", "") or ""
        else:
            deal_name = str(deal_name_raw or "")

        # 取引先名
        account_name = ""
        account_links = fields.get("取引先", [])
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    for a in accounts:
                        if a.get("record_id") == link.get("record_id", ""):
                            account_name = str(a.get("fields", {}).get("会社名", "") or "")
                            break

        new_account = str(fields.get("新規取引先名", "") or "")

        # 検索
        names = [deal_name, account_name, new_account]
        if any(search_term in n for n in names if n):
            deal_date = fields.get("商談日", 0)
            date_str = ""
            if isinstance(deal_date, (int, float)) and deal_date > 0:
                date_str = datetime.fromtimestamp(deal_date / 1000).strftime('%Y-%m-%d')
            stage = str(fields.get("商談ステージ", "") or "")
            temp = str(fields.get("温度感スコア", "") or "")
            print(f"  {rid} | {deal_name or account_name or new_account} | {date_str} | {stage} | {temp}")
            found += 1

    print(f"\n  {found}件見つかりました")


# ── キューモード: 新規商談→メール生成→キュー保存 ──
def queue_new_deals(specific_deal=None, deal_names=None):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 商談サンクスメール: キュー追加チェック")

    token = lark_get_token()
    state = load_state()
    queue = load_queue()
    processed_ids = set(state.get("processed_ids", []))

    # CRMデータ取得
    print("  データ取得中...")
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f"  商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")

    # deal_names指定時: 商談名・取引先名で検索してrecord_idを特定
    deal_name_ids = set()
    if deal_names:
        for rec in deals:
            fields = rec.get("fields", {})
            rid = rec.get("record_id", "")
            # 商談名
            dn_raw = fields.get("商談名", "")
            if isinstance(dn_raw, list) and dn_raw and isinstance(dn_raw[0], dict):
                dn = dn_raw[0].get("text", "") or ""
            else:
                dn = str(dn_raw or "")
            # 取引先名
            acct_name = ""
            acct_links = fields.get("取引先", [])
            if isinstance(acct_links, list):
                for link in acct_links:
                    if isinstance(link, dict):
                        for a in accounts:
                            if a.get("record_id") == link.get("record_id", ""):
                                acct_name = str(a.get("fields", {}).get("会社名", "") or "")
                                break
            new_acct = str(fields.get("新規取引先名", "") or "")
            # マッチ判定
            for search_name in deal_names:
                if any(search_name in n for n in [dn, acct_name, new_acct] if n):
                    deal_name_ids.add(rid)
                    print(f"  名前検索ヒット: '{search_name}' → {rid} ({dn or acct_name or new_acct})")
        if not deal_name_ids:
            print(f"  指定された商談名に一致する商談が見つかりません: {deal_names}")
            return

    # 新規商談を検出
    new_deals = []
    for rec in deals:
        rid = rec.get("record_id", "")
        if specific_deal:
            if rid == specific_deal:
                new_deals.append(rec)
            continue
        if deal_name_ids:
            if rid in deal_name_ids:
                new_deals.append(rec)
            continue
        if rid not in processed_ids:
            new_deals.append(rec)

    # 初回実行: 全件を処理済みにする（--deal/--deal-name指定時はスキップ）
    if not state.get("last_check") and not specific_deal and not deal_name_ids:
        print(f"\n  初回実行: {len(deals)}件を処理済みとしてマーク")
        state["processed_ids"] = [r.get("record_id", "") for r in deals]
        state["last_check"] = datetime.now().isoformat()
        save_state(state)
        print("  次回以降、新規商談をキューに追加します。")
        return

    if not new_deals:
        print("  新規商談なし")
        state["last_check"] = datetime.now().isoformat()
        save_state(state)
        return

    print(f"\n  新規商談: {len(new_deals)}件 (処理済みID: {len(processed_ids)}件, 全商談: {len(deals)}件)")
    queued = 0
    skip_reasons = {"old_date": 0, "no_date": 0, "cold": 0, "bad_stage": 0, "no_email": 0, "duplicate": 0, "gen_error": 0}

    for rec in new_deals:
        rid = rec.get("record_id", "")
        fields = rec.get("fields", {})

        # 商談名の取得（list of text objects対応 + フォーム投入レコード対応）
        deal_name_raw = fields.get("商談名", "")
        if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
            deal_name = deal_name_raw[0].get("text", "") or ""
        else:
            deal_name = str(deal_name_raw or "")
        # フォームから投入されたレコードは商談名が空。新規取引先名/取引先名で補完
        if not deal_name:
            deal_name = str(fields.get("新規取引先名", "") or "")
        if not deal_name:
            # 取引先リンクからテキスト取得を試みる
            account_links = fields.get("取引先", [])
            if isinstance(account_links, list):
                for link in account_links:
                    if isinstance(link, dict):
                        text_arr = link.get("text_arr", [])
                        if text_arr:
                            deal_name = str(text_arr[0])
                            break
                        text = link.get("text", "")
                        if text:
                            deal_name = str(text)
                            break
        if not deal_name:
            deal_name = "(名前なし)"

        print(f"\n  商談: {deal_name}")

        # 商談日チェック: 直近3日以内のみ対象（--deal/--deal-name指定時はスキップ）
        is_manual = specific_deal or deal_name_ids
        deal_date = fields.get("商談日", 0)
        if isinstance(deal_date, (int, float)) and deal_date > 0:
            deal_dt = datetime.fromtimestamp(deal_date / 1000)
            days_ago = (datetime.now() - deal_dt).days
            if days_ago > 3 and not is_manual:
                print(f"  -> 商談日が{days_ago}日前({deal_dt.strftime('%Y-%m-%d')})。スキップ。")
                skip_reasons["old_date"] += 1
                processed_ids.add(rid)
                continue
            else:
                print(f"  -> 商談日: {deal_dt.strftime('%Y-%m-%d')} ({days_ago}日前) OK")
        else:
            if not is_manual:
                print(f"  -> 商談日なし (type={type(deal_date).__name__}, val={deal_date})。スキップ。")
                skip_reasons["no_date"] += 1
                processed_ids.add(rid)
                continue
            else:
                print(f"  -> 商談日なし（手動指定のためスキップしません）")

        # ステージチェック: 不在・失注・納品完了は除外（不在=名刺なし=メールなし）
        stage = str(fields.get("商談ステージ", "") or "")
        if stage in ("不在", "失注", "納品完了"):
            print(f"  -> ステージ「{stage}」。スキップ。")
            skip_reasons["bad_stage"] += 1
            processed_ids.add(rid)
            continue

        # 担当営業
        rep_field = fields.get("担当営業", [])
        rep_name = ""
        if isinstance(rep_field, list):
            for p in rep_field:
                if isinstance(p, dict):
                    rep_name = p.get("name", "")
                elif isinstance(p, str):
                    rep_name = p
        rep_info = SALES_REPS.get(rep_name, {
            "display": rep_name or "東海エアサービス",
            "email": "",
            "open_id": None,
            "signature": f"{rep_name or '担当者'}\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
        })

        # 顧客メール検索
        contact = find_customer_email(contacts, accounts, fields)
        if not contact or not contact.get("email"):
            print(f"  -> メールアドレスなし。スキップ。")
            skip_reasons["no_email"] += 1
            processed_ids.add(rid)
            continue

        print(f"  -> 宛先: {contact['company']} {contact['name']} <{contact['email']}>")

        # 重複チェック: 同一メールアドレスに過去N日以内に送信済み
        if is_duplicate_email(queue, contact["email"]):
            print(f"  -> 過去{DUPLICATE_WINDOW_DAYS}日以内に送信済み。スキップ。")
            skip_reasons["duplicate"] += 1
            processed_ids.add(rid)
            continue

        # Claude APIでメール生成
        try:
            email_text = generate_thankyou_email(fields, contact, rep_info)
        except Exception as e:
            print(f"  -> メール生成エラー: {e}")
            skip_reasons["gen_error"] += 1
            processed_ids.add(rid)
            continue

        subject, body = parse_email_text(email_text, rep_info)
        send_at = calc_send_time()

        # キューに追加
        queue_item = {
            "record_id": rid,
            "deal_name": deal_name,
            "to_email": contact["email"],
            "to_name": f"{contact['company']} {contact['name']}".strip(),
            "subject": subject,
            "body": body,
            "from_name": rep_info["display"] + " / " + COMPANY_INFO["name"],
            "from_email": rep_info.get("email") or "info@tokaiair.com",
            "rep_name": rep_info["display"],
            "rep_open_id": rep_info.get("open_id"),
            "queued_at": datetime.now().isoformat(),
            "send_at": send_at,
            "status": "pending",
        }
        queue.append(queue_item)
        processed_ids.add(rid)
        queued += 1

        print(f"  → キュー追加。送信予定: {send_at}")

        # CEOにキュー追加通知（本文プレビュー付き）
        preview_body = body[:300] + ("..." if len(body) > 300 else "")
        send_lark_dm(token, CEO_OPEN_ID,
            f"📋 サンクスメールキュー追加\n"
            f"商談: {deal_name}\n"
            f"宛先: {contact['company']} {contact['name']} <{contact['email']}>\n"
            f"件名: {subject}\n"
            f"送信予定: {send_at}\n"
            f"─────────\n"
            f"{preview_body}\n"
            f"─────────\n"
            f"⛔ 止める場合: 「キャンセル {deal_name}」と返信")

        time.sleep(1)

    # 保存
    state["processed_ids"] = list(processed_ids)
    state["last_check"] = datetime.now().isoformat()
    save_state(state)
    save_queue(queue)

    print(f"\n  キュー追加: {queued}件 / 合計キュー: {len([q for q in queue if q['status'] == 'pending'])}件")
    print(f"  処理済みID: {len(processed_ids)}件")
    skip_total = sum(skip_reasons.values())
    if skip_total > 0:
        print(f"  スキップ内訳: 古い商談={skip_reasons['old_date']}, 日付なし={skip_reasons['no_date']}, "
              f"Cold/不在={skip_reasons['cold']}, ステージ除外={skip_reasons['bad_stage']}, "
              f"メールなし={skip_reasons['no_email']}, 重複={skip_reasons['duplicate']}, "
              f"生成エラー={skip_reasons['gen_error']}")


# ── 送信モード: キューから送信時刻が来たものを送信 ──
def send_queued_emails(dry_run=False):
    now = datetime.now()
    print(f"[{now.strftime('%H:%M:%S')}] 商談サンクスメール: キュー送信チェック")

    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]

    if not pending:
        print("  送信待ちなし")
        return

    print(f"  キュー内: {len(pending)}件")

    token = lark_get_token()
    sent = 0

    # 1日の送信上限チェック
    today_sent = count_sent_today(queue)
    if today_sent >= MAX_SENDS_PER_DAY:
        print(f"  ⚠️ 本日の送信上限({MAX_SENDS_PER_DAY}件)に達しています。送信なし。")
        send_lark_dm(token, CEO_OPEN_ID,
            f"⚠️ サンクスメール: 本日の送信上限({MAX_SENDS_PER_DAY}件)到達。"
            f"残り{len(pending)}件は翌営業日に送信。")
        return

    for item in queue:
        if item["status"] != "pending":
            continue

        send_at = datetime.fromisoformat(item["send_at"])
        if now < send_at:
            remaining = send_at - now
            print(f"  [{item['deal_name']}] 送信予定: {item['send_at']} (あと{remaining})")
            continue

        # 送信上限チェック（ループ内）
        if sent + today_sent >= MAX_SENDS_PER_DAY:
            print(f"  ⚠️ 送信上限到達。残りは翌営業日。")
            break

        # 送信直前の重複チェック
        if is_duplicate_email(queue, item["to_email"]):
            print(f"  → {item['to_email']}は過去{DUPLICATE_WINDOW_DAYS}日以内に送信済み。スキップ。")
            item["status"] = "skipped_duplicate"
            continue

        print(f"\n  送信中: {item['deal_name']} → {item['to_email']}")
        print(f"  件名: {item['subject']}")

        if dry_run:
            print(f"  [ドライラン] 送信スキップ")
            continue

        # レビューエージェントによる送信前チェック
        review_result = run_email_review(
            item["subject"], item["body"],
            item["to_email"], item.get("from_email", "info@tokaiair.com"))
        if review_result["verdict"] == "NG":
            critical_issues = [i for i in review_result.get("issues", []) if i["severity"] == "CRITICAL"]
            issue_text = "\n".join(f"  - {i['description']}" for i in critical_issues)
            print(f"  レビューNG: {review_result['summary']}")
            item["status"] = "review_rejected"
            item["review_result"] = review_result["summary"]
            send_lark_dm(token, CEO_OPEN_ID,
                f"メール送信ブロック（レビューNG）\n"
                f"商談: {item['deal_name']}\n"
                f"宛先: {item['to_email']}\n"
                f"理由:\n{issue_text}\n"
                f"手動確認が必要です")
            continue
        else:
            print(f"  レビューOK: {review_result['summary']}")

        success = send_email_via_wordpress(
            to_email=item["to_email"],
            subject=item["subject"],
            body=item["body"],
            from_name=item["from_name"],
            from_email=item.get("from_email", "info@tokaiair.com"),
        )

        if success:
            item["status"] = "sent"
            item["sent_at"] = now.isoformat()
            sent += 1
            print(f"  ✅ 送信完了")

            # 担当営業に通知
            if item.get("rep_open_id"):
                send_lark_dm(token, item["rep_open_id"],
                    f"📧 サンクスメール送信完了\n\n"
                    f"商談: {item['deal_name']}\n"
                    f"宛先: {item['to_name']} 様\n"
                    f"メール: {item['to_email']}\n"
                    f"件名: {item['subject']}")

            # CEO通知
            send_lark_dm(token, CEO_OPEN_ID,
                f"📧 サンクスメール送信: {item['deal_name']} → {item['to_email']}")
        else:
            item["status"] = "failed"
            item["failed_at"] = now.isoformat()
            print(f"  ❌ 送信失敗")

            # 失敗をCEOに通知
            send_lark_dm(token, CEO_OPEN_ID,
                f"⚠️ サンクスメール送信失敗\n"
                f"商談: {item['deal_name']}\n"
                f"宛先: {item['to_email']}\n"
                f"手動対応が必要です")

        # ログ記録
        with open(LOG_FILE, "a", encoding="utf-8") as lf:
            lf.write(f"[{now.isoformat()}] {item['deal_name']} → {item['to_email']} "
                     f"({item['status']})\n")

        time.sleep(1)

    # 古い送信済みをクリーンアップ（7日以上前）
    cutoff = (now - timedelta(days=7)).isoformat()
    queue = [q for q in queue if q["status"] == "pending" or q.get("sent_at", q.get("failed_at", "")) > cutoff]
    save_queue(queue)

    print(f"\n  送信完了: {sent}件")


# ── キュー一覧表示 ──
def show_queue():
    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]
    sent = [q for q in queue if q["status"] == "sent"]
    failed = [q for q in queue if q["status"] == "failed"]

    print(f"サンクスメールキュー状況:")
    print(f"  待機中: {len(pending)}件 / 送信済: {len(sent)}件 / 失敗: {len(failed)}件")

    if pending:
        print(f"\n  【待機中】")
        for q in pending:
            print(f"    {q['deal_name']} → {q['to_email']} (送信: {q['send_at']})")

    if sent:
        print(f"\n  【送信済（直近）】")
        for q in sent[-5:]:
            print(f"    {q['deal_name']} → {q['to_email']} ({q.get('sent_at', '')})")

    if failed:
        print(f"\n  【失敗】")
        for q in failed:
            print(f"    {q['deal_name']} → {q['to_email']} ({q.get('failed_at', '')})")


def main():
    args = sys.argv[1:]

    if "--list" in args:
        show_queue()
        return

    if "--send" in args:
        send_queued_emails(dry_run="--dry-run" in args)
        return

    if "--find-deals" in args:
        # 商談名で検索して record_id を表示（--deal オプション用）
        search_term = ""
        idx = args.index("--find-deals")
        if idx + 1 < len(args):
            search_term = args[idx + 1]
        find_deals_by_name(search_term)
        return

    if "--queue" in args or "--deal" in args or "--deal-name" in args or not args:
        specific_deal = None
        deal_names = []
        if "--deal" in args:
            idx = args.index("--deal")
            if idx + 1 < len(args):
                specific_deal = args[idx + 1]
        if "--deal-name" in args:
            idx = args.index("--deal-name")
            if idx + 1 < len(args):
                deal_names = [n.strip() for n in args[idx + 1].split(",")]
        queue_new_deals(specific_deal, deal_names=deal_names)
        return

    if "--dry-run" in args:
        send_queued_emails(dry_run=True)
        return

    # デフォルト: キュー追加チェック
    queue_new_deals()


if __name__ == "__main__":
    main()
