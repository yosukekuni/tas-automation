#!/usr/bin/env python3
"""
納品後サンクスメール自動送信

受注台帳（tbldLj2iMJYocct6）から納品完了案件を検出し、
翌営業日にお礼メール + データ取り扱いガイド + リピート割引案内を送信。

Usage:
  python3 delivery_thankyou_email.py --check      # 納品完了案件をチェック→キュー追加
  python3 delivery_thankyou_email.py --send        # キューから送信
  python3 delivery_thankyou_email.py --dry-run     # 送信せずプレビュー
  python3 delivery_thankyou_email.py --list        # キュー一覧
  python3 delivery_thankyou_email.py --order ID    # 特定の受注レコードのみ処理

cron (GitHub Actions):
  毎日9:00 --check → キュー追加
  毎日10:00 --send → 送信実行
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
STATE_FILE = SCRIPT_DIR / "delivery_thankyou_state.json"
QUEUE_FILE = SCRIPT_DIR / "delivery_thankyou_queue.json"
LOG_FILE = SCRIPT_DIR / "delivery_thankyou.log"

# ── Config (file or env vars for GitHub Actions) ──
if CONFIG_FILE.exists():
    with open(CONFIG_FILE) as f:
        CONFIG = json.load(f)
    LARK_APP_ID = CONFIG["lark"]["app_id"]
    LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
    CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
    CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]
    WP_BASE_URL = CONFIG["wordpress"]["base_url"].replace("/wp/v2", "")
    WP_USER = CONFIG["wordpress"]["user"]
    WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]
else:
    LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
    LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
    CRM_BASE_TOKEN = os.environ.get("CRM_BASE_TOKEN", "")
    CLAUDE_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    WP_BASE_URL = "https://tokaiair.com/wp-json"
    WP_USER = os.environ.get("WP_USER", "")
    WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD", "")

# CRM Table IDs
TABLE_ORDERS = "tbldLj2iMJYocct6"      # 受注台帳
TABLE_CONTACTS = "tblN53hFIQoo4W8j"     # 連絡先
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"     # 取引先
TABLE_EMAIL_LOG = "tblfBahatPZMJEM5"    # メールログ

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
        "email": "masaki@tokaiair.com",
        "open_id": None,
        "signature": "政木 勇治\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
    },
}

CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# セーフガード設定
MAX_SENDS_PER_DAY = 5          # 1日の送信上限
DUPLICATE_WINDOW_DAYS = 30     # 同一メールアドレスへの重複防止期間


def is_duplicate_email(queue, to_email):
    """過去N日以内に同一アドレスに送信済みかチェック"""
    cutoff = (datetime.now() - timedelta(days=DUPLICATE_WINDOW_DAYS)).isoformat()
    for item in queue:
        if item.get("to_email") == to_email and item.get("status") == "sent":
            sent_at = item.get("sent_at", "")
            if sent_at > cutoff:
                return True
    return False


def count_sent_today(queue):
    """本日の送信件数をカウント"""
    today = datetime.now().strftime("%Y-%m-%d")
    return sum(1 for q in queue if q.get("status") == "sent"
               and q.get("sent_at", "").startswith(today))


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

# リピート割引
REPEAT_DISCOUNT_PERCENT = 5
SURVEY_URL = "https://www.tokaiair.com/survey/"  # TODO: 実際のアンケートURLに差し替え


# ── Logging ──
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except IOError:
        pass


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    if resp.get("code") != 0:
        raise RuntimeError(f"Lark token error: {resp}")
    return resp["tenant_access_token"]


def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            d = result.get("data", {})
            records.extend(d.get("items", []))
            if not d.get("has_more"):
                break
            page_token = d.get("page_token")
            time.sleep(0.3)
    return records


def create_lark_record(token, table_id, fields):
    """Lark Bitable にレコードを作成"""
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/records"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return resp.get("code") == 0
    except Exception as e:
        log(f"Lark record create error: {e}")
        return False


def send_lark_dm(token, open_id, text):
    if not open_id:
        return
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
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
            log(f"Lark DM error: {e.code}")
        time.sleep(0.3)


# ── State & Queue ──
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"processed_ids": [], "last_check": None}


def save_state(state):
    if len(state.get("processed_ids", [])) > 500:
        state["processed_ids"] = state["processed_ids"][-300:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_queue():
    if QUEUE_FILE.exists():
        try:
            with open(QUEUE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


# ── Field helpers ──
def _field_str(fields, key, default=""):
    val = fields.get(key, default)
    if val is None:
        return default
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or item.get("name", "") or item.get("text_value", "") or str(item))
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else default
    return str(val)


def _field_timestamp(fields, key):
    val = fields.get(key)
    if isinstance(val, (int, float)) and val > 0:
        return datetime.fromtimestamp(val / 1000)
    return None


def _field_person_name(fields, key):
    val = fields.get(key, [])
    if isinstance(val, list):
        for p in val:
            if isinstance(p, dict):
                return p.get("name", "")
            elif isinstance(p, str):
                return p
    if isinstance(val, str):
        return val
    return ""


# ── 翌営業日計算 ──
def next_business_day(from_date=None):
    """翌営業日の10:00を返す"""
    d = from_date or datetime.now()
    next_day = d + timedelta(days=1)
    # 土日スキップ
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day.replace(hour=10, minute=0, second=0, microsecond=0)


# ── 納品完了案件の検出 ──
def find_delivered_orders(orders, processed_ids):
    """
    受注台帳から納品完了案件を検出。
    判定ロジック:
      - 出典フィールドまたはステータスフィールドに「納品」を含む
      - または納品日フィールドが存在する
    """
    targets = []

    for rec in orders:
        rid = rec.get("record_id", "")
        if rid in processed_ids:
            continue

        f = rec.get("fields", {})

        # 案件名
        case_name = _field_str(f, "案件名")
        if not case_name:
            continue

        # 納品完了の判定: 複数のフィールドを確認
        is_delivered = False
        delivery_date = None

        # 1. 納品日フィールドをチェック
        for key in ("納品日", "納品完了日", "完了日"):
            dt = _field_timestamp(f, key)
            if dt:
                is_delivered = True
                delivery_date = dt
                break

        # 2. 出典/ステータスフィールドをチェック
        if not is_delivered:
            for key in ("出典", "ステータス", "進捗"):
                val = _field_str(f, key)
                if "納品" in val or "完了" in val:
                    is_delivered = True
                    break

        if not is_delivered:
            continue

        # 納品日が直近7日以内のもののみ対象（古い案件は除外）
        if delivery_date:
            days_ago = (datetime.now() - delivery_date).days
            if days_ago > 7 or days_ago < 0:
                continue
        else:
            # 納品日不明の場合、レコード更新日を参照
            updated = rec.get("last_modified_time")
            if isinstance(updated, (int, float)) and updated > 0:
                updated_dt = datetime.fromtimestamp(updated / 1000)
                days_ago = (datetime.now() - updated_dt).days
                if days_ago > 7:
                    continue

        # 取引先
        account_name = _field_str(f, "取引先")
        # 受注金額
        amount = f.get("受注金額") or f.get("請求金額")
        amount_str = ""
        if isinstance(amount, (int, float)) and amount > 0:
            amount_str = f"{int(amount):,}円"

        # 担当営業
        rep_name = _field_person_name(f, "担当営業") or _field_person_name(f, "担当")
        # 商材
        product = _field_str(f, "商材") or _field_str(f, "商材種別") or _field_str(f, "案件種別")

        targets.append({
            "record_id": rid,
            "case_name": case_name,
            "account_name": account_name,
            "amount_str": amount_str,
            "rep_name": rep_name,
            "product": product,
            "delivery_date": delivery_date.isoformat() if delivery_date else "",
            "fields": f,
        })

    return targets


# ── 連絡先メールアドレス検索 ──
def find_customer_email(contacts, accounts, account_name, case_name=""):
    """取引先名から連絡先を検索"""
    if not account_name and not case_name:
        return None

    search_terms = [t for t in [account_name, case_name] if t]

    for rec in contacts:
        f = rec.get("fields", {})
        company = _field_str(f, "会社名")
        email = _field_str(f, "メールアドレス")

        if not email or "@" not in email:
            continue

        for term in search_terms:
            if (company and term in company) or (company and company in term):
                return {
                    "email": email,
                    "name": _field_str(f, "氏名"),
                    "company": company,
                    "title": _field_str(f, "役職"),
                }

    return None


# ── Claude API でメール生成 ──
def generate_delivery_email(order_info, contact, rep_info):
    customer_name = contact.get("name", "") or "ご担当者"
    customer_company = contact.get("company", "") or order_info["account_name"]
    customer_title = contact.get("title", "")
    case_name = order_info["case_name"]
    product = order_info["product"] or "ドローン測量"

    prompt = f"""あなたは{COMPANY_INFO['name']}の営業担当 {rep_info['display']} として、
納品完了後の顧客向けサンクスメールを作成してください。

【納品情報】
取引先: {customer_company}
担当者: {customer_name} {customer_title} 様
案件名: {case_name}
商材: {product}
納品金額: {order_info['amount_str'] or '（記載なし）'}

【メール作成ルール】
1. 件名は「件名：」で始める
2. 納品完了のお礼から始める
3. 以下の内容を自然に盛り込む:
   a) 納品データの取り扱い方法のアドバイス（商材に応じて）
      - ドローン測量: 点群データの保存・バックアップ推奨、座標系の確認
      - 赤外線調査: 報告書の読み方、経年比較の重要性
      - 空撮: 高解像度データの活用方法
   b) 次回ご依頼時に{REPEAT_DISCOUNT_PERCENT}%割引のリピーター特典
   c) アンケートのお願い（以下URLへ誘導）
      アンケートURL: {SURVEY_URL}
4. 押し売りしない。感謝と今後のサポート姿勢を伝える
5. 本文は400文字以内。簡潔かつ丁寧に。
6. AIっぽい表現を避ける。普通のビジネスメールの文体で。
7. 「つきましては」「さて」等の堅すぎる接続詞は使わない

【出力形式】
件名：〇〇〇

（本文のみ。宛先の「○○様」から書き出し。署名は不要。）
"""

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
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
        subject = f"納品完了のご報告とお礼 - {COMPANY_INFO['name']}"

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
        log(f"WordPress email error: {e.code} {body_text}")
        return False
    except Exception as e:
        log(f"WordPress email error: {e}")
        return False


# ── メールログ記録（Lark Base） ──
def record_email_log(token, order_info, contact, subject, status="送信済み"):
    """メールログテーブルにレコード追加"""
    fields = {
        "日時": int(datetime.now().timestamp() * 1000),
        "方向": "送信",
        "送信者": order_info.get("rep_name", "東海エアサービス"),
        "受信者": f"{contact.get('company', '')} {contact.get('name', '')}".strip(),
        "件名": subject,
        "本文要約": f"納品完了サンクスメール（{order_info['case_name']}）",
        "メール種別": "納品御礼",
        "ステータス": status,
        "備考": f"自動送信 (delivery_thankyou_email.py) / 案件: {order_info['case_name']}",
    }
    return create_lark_record(token, TABLE_EMAIL_LOG, fields)


# ── チェックモード: 納品完了案件→キュー追加 ──
def check_and_queue(specific_order=None):
    log("納品サンクスメール: チェック開始")

    token = lark_get_token()
    state = load_state()
    queue = load_queue()
    processed_ids = set(state.get("processed_ids", []))

    # CRMデータ取得
    print("  データ取得中...")
    orders = get_all_records(token, TABLE_ORDERS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f"  受注台帳: {len(orders)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")

    # 初回実行: 全件を処理済みにする（既存納品案件にメールを送らない）
    if not state.get("last_check"):
        print(f"\n  初回実行: {len(orders)}件を処理済みとしてマーク")
        state["processed_ids"] = [r.get("record_id", "") for r in orders]
        state["last_check"] = datetime.now().isoformat()
        save_state(state)
        print("  次回以降、新規納品完了案件をキューに追加します。")
        return

    # 特定レコード指定時
    if specific_order:
        processed_ids_for_search = set()  # 指定時は処理済みチェック無視
    else:
        processed_ids_for_search = processed_ids

    # 納品完了案件を検出
    targets = find_delivered_orders(orders, processed_ids_for_search)

    if specific_order:
        targets = [t for t in targets if t["record_id"] == specific_order]

    if not targets:
        print("  納品完了案件なし")
        state["last_check"] = datetime.now().isoformat()
        save_state(state)
        return

    print(f"\n  納品完了案件: {len(targets)}件")
    queued = 0

    for order_info in targets:
        rid = order_info["record_id"]
        print(f"\n  案件: {order_info['case_name']} ({order_info['account_name']})")

        # 顧客メール検索
        contact = find_customer_email(
            contacts, accounts,
            order_info["account_name"],
            order_info["case_name"]
        )
        if not contact or not contact.get("email"):
            print(f"  -> メールアドレスなし。スキップ。")
            processed_ids.add(rid)
            continue

        print(f"  -> 宛先: {contact['company']} {contact['name']} <{contact['email']}>")

        # 重複チェック
        if is_duplicate_email(queue, contact["email"]):
            print(f"  -> 過去{DUPLICATE_WINDOW_DAYS}日以内に送信済み。スキップ。")
            processed_ids.add(rid)
            continue

        # 担当営業情報
        rep_info = SALES_REPS.get(order_info["rep_name"], {
            "display": order_info["rep_name"] or "東海エアサービス",
            "email": "info@tokaiair.com",
            "open_id": None,
            "signature": f"{order_info['rep_name'] or '担当者'}\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/",
        })

        # Claude APIでメール生成
        try:
            email_text = generate_delivery_email(order_info, contact, rep_info)
        except Exception as e:
            log(f"メール生成エラー ({order_info['case_name']}): {e}")
            processed_ids.add(rid)
            continue

        subject, body = parse_email_text(email_text, rep_info)
        send_at = next_business_day().isoformat()

        # キューに追加
        queue_item = {
            "record_id": rid,
            "case_name": order_info["case_name"],
            "account_name": order_info["account_name"],
            "to_email": contact["email"],
            "to_name": f"{contact['company']} {contact['name']}".strip(),
            "subject": subject,
            "body": body,
            "from_name": rep_info["display"] + " / " + COMPANY_INFO["name"],
            "from_email": rep_info.get("email") or "info@tokaiair.com",
            "rep_name": rep_info["display"],
            "rep_open_id": rep_info.get("open_id"),
            "product": order_info["product"],
            "amount_str": order_info["amount_str"],
            "queued_at": datetime.now().isoformat(),
            "send_at": send_at,
            "status": "pending",
        }
        queue.append(queue_item)
        processed_ids.add(rid)
        queued += 1

        print(f"  -> キュー追加。送信予定: {send_at}")
        print(f"  -> 件名: {subject}")

        # CEOにキュー追加通知（本文プレビュー付き）
        preview_body = body[:300] + ("..." if len(body) > 300 else "")
        send_lark_dm(token, CEO_OPEN_ID,
            f"納品サンクスメール キュー追加\n"
            f"案件: {order_info['case_name']}\n"
            f"取引先: {order_info['account_name']}\n"
            f"宛先: {contact['email']}\n"
            f"件名: {subject}\n"
            f"送信予定: {send_at}\n"
            f"─────────\n"
            f"{preview_body}\n"
            f"─────────\n"
            f"止める場合: 「キャンセル {order_info['case_name']}」と返信")

        time.sleep(1)

    # 保存
    state["processed_ids"] = list(processed_ids)
    state["last_check"] = datetime.now().isoformat()
    save_state(state)
    save_queue(queue)

    pending_count = len([q for q in queue if q["status"] == "pending"])
    log(f"キュー追加: {queued}件 / 合計待機: {pending_count}件")


# ── 送信モード ──
def send_queued_emails(dry_run=False):
    now = datetime.now()
    log(f"納品サンクスメール: 送信チェック {'[DRY-RUN]' if dry_run else ''}")

    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]

    if not pending:
        print("  送信待ちなし")
        return

    print(f"  キュー内: {len(pending)}件")

    token = lark_get_token()
    sent_count = 0

    # 1日の送信上限チェック
    today_sent = count_sent_today(queue)
    if today_sent >= MAX_SENDS_PER_DAY:
        print(f"  本日の送信上限({MAX_SENDS_PER_DAY}件)に達しています。送信なし。")
        send_lark_dm(token, CEO_OPEN_ID,
            f"納品サンクスメール: 本日の送信上限({MAX_SENDS_PER_DAY}件)到達。"
            f"残り{len(pending)}件は翌営業日に送信。")
        return

    for item in queue:
        if item["status"] != "pending":
            continue

        send_at = datetime.fromisoformat(item["send_at"])
        if now < send_at:
            remaining = send_at - now
            print(f"  [{item['case_name']}] 送信予定: {item['send_at']} (あと{remaining})")
            continue

        # 送信上限チェック（ループ内）
        if sent_count + today_sent >= MAX_SENDS_PER_DAY:
            print(f"  送信上限到達。残りは翌営業日。")
            break

        # 送信直前の重複チェック
        if is_duplicate_email(queue, item["to_email"]):
            print(f"  -> {item['to_email']}は過去{DUPLICATE_WINDOW_DAYS}日以内に送信済み。スキップ。")
            item["status"] = "skipped_duplicate"
            continue

        print(f"\n  送信中: {item['case_name']} -> {item['to_email']}")
        print(f"  件名: {item['subject']}")

        if dry_run:
            print(f"  [DRY-RUN] 送信スキップ")
            print(f"  --- 本文プレビュー ---")
            print(item["body"][:500])
            print(f"  --- ここまで ---")
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
                f"納品メール送信ブロック（レビューNG）\n"
                f"案件: {item['case_name']}\n"
                f"宛先: {item['to_email']}\n"
                f"理由:\n{issue_text}\n"
                f"手動確認が必要です")
            continue
        else:
            print(f"  レビューOK: {review_result['summary']}")

        # WordPress経由で送信
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
            sent_count += 1
            log(f"送信完了: {item['case_name']} -> {item['to_email']}")

            # メールログに記録
            try:
                record_email_log(token, {
                    "case_name": item["case_name"],
                    "rep_name": item["rep_name"],
                }, {
                    "company": item["account_name"],
                    "name": item["to_name"],
                    "email": item["to_email"],
                }, item["subject"], "送信済み")
            except Exception as e:
                log(f"メールログ記録エラー: {e}")

            # 担当営業に通知
            if item.get("rep_open_id"):
                send_lark_dm(token, item["rep_open_id"],
                    f"納品サンクスメール送信完了\n\n"
                    f"案件: {item['case_name']}\n"
                    f"宛先: {item['to_name']} 様\n"
                    f"メール: {item['to_email']}\n"
                    f"件名: {item['subject']}")

            # CEO通知
            send_lark_dm(token, CEO_OPEN_ID,
                f"納品サンクスメール送信: {item['case_name']} -> {item['to_email']}")
        else:
            item["status"] = "failed"
            item["failed_at"] = now.isoformat()
            log(f"送信失敗: {item['case_name']} -> {item['to_email']}")

            # メールログに記録（失敗）
            try:
                record_email_log(token, {
                    "case_name": item["case_name"],
                    "rep_name": item["rep_name"],
                }, {
                    "company": item["account_name"],
                    "name": item["to_name"],
                    "email": item["to_email"],
                }, item["subject"], "送信失敗")
            except Exception:
                pass

            send_lark_dm(token, CEO_OPEN_ID,
                f"納品サンクスメール送信失敗\n"
                f"案件: {item['case_name']}\n"
                f"宛先: {item['to_email']}\n"
                f"手動対応が必要です")

        time.sleep(1)

    # 古い送信済みをクリーンアップ（14日以上前）
    cutoff = (now - timedelta(days=14)).isoformat()
    queue = [q for q in queue if q["status"] == "pending" or q.get("sent_at", q.get("failed_at", "")) > cutoff]
    save_queue(queue)

    log(f"送信完了: {sent_count}件")


# ── キュー一覧表示 ──
def show_queue():
    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]
    sent = [q for q in queue if q["status"] == "sent"]
    failed = [q for q in queue if q["status"] == "failed"]

    print(f"納品サンクスメール キュー状況:")
    print(f"  待機中: {len(pending)}件 / 送信済: {len(sent)}件 / 失敗: {len(failed)}件")

    if pending:
        print(f"\n  [待機中]")
        for q in pending:
            print(f"    {q['case_name']} ({q['account_name']}) -> {q['to_email']} (送信: {q['send_at']})")

    if sent:
        print(f"\n  [送信済（直近）]")
        for q in sent[-5:]:
            print(f"    {q['case_name']} -> {q['to_email']} ({q.get('sent_at', '')})")

    if failed:
        print(f"\n  [失敗]")
        for q in failed:
            print(f"    {q['case_name']} -> {q['to_email']} ({q.get('failed_at', '')})")


# ── Main ──
def main():
    args = sys.argv[1:]

    if "--list" in args:
        show_queue()
        return

    if "--send" in args:
        send_queued_emails(dry_run="--dry-run" in args)
        return

    if "--dry-run" in args and "--send" not in args and "--check" not in args:
        send_queued_emails(dry_run=True)
        return

    if "--check" in args or "--order" in args or not args:
        specific_order = None
        if "--order" in args:
            idx = args.index("--order")
            if idx + 1 < len(args):
                specific_order = args[idx + 1]
        check_and_queue(specific_order)
        return

    # デフォルト: チェック
    check_and_queue()


if __name__ == "__main__":
    main()
