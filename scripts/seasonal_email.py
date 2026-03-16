#!/usr/bin/env python3
"""
季節メール自動送信（4月新年度・10月下期）

過去受注実績のある顧客（セグメントA/C群）へ測量計画確認メールを送信。
デフォルトはドラフト生成のみ（--sendで WordPress wp_mail 経由送信）。

Usage:
  python3 seasonal_email.py                    # ドラフト生成のみ（デフォルト）
  python3 seasonal_email.py --send             # WordPress経由で送信
  python3 seasonal_email.py --list             # 対象顧客一覧のみ表示
  python3 seasonal_email.py --season april     # 季節を明示指定（april / october）
  python3 seasonal_email.py --dry-run          # ドラフト生成（--sendなしと同じ）

cron (GitHub Actions):
  workflow_dispatch（手動トリガー）で4月/10月に実行
"""

import csv
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
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "tas-automation" / "scripts" / "automation_config.json"

OUTPUT_DIR = SCRIPT_DIR / "seasonal_drafts"
LOG_FILE = SCRIPT_DIR / "seasonal_email.log"
SEGMENTATION_CSV = SCRIPT_DIR.parent / "data" / "crm_segmentation.csv"


# ── 設定読み込み（環境変数 > config file） ──
def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    return {
        "lark_app_id": os.environ.get("LARK_APP_ID", cfg.get("lark", {}).get("app_id", "")),
        "lark_app_secret": os.environ.get("LARK_APP_SECRET", cfg.get("lark", {}).get("app_secret", "")),
        "crm_base_token": os.environ.get("CRM_BASE_TOKEN", cfg.get("lark", {}).get("crm_base_token", "")),
        "wp_base_url": cfg.get("wordpress", {}).get("base_url", "https://tokaiair.com/wp-json/wp/v2").replace("/wp/v2", ""),
        "wp_user": os.environ.get("WP_USER", cfg.get("wordpress", {}).get("user", "")),
        "wp_app_password": os.environ.get("WP_APP_PASSWORD", cfg.get("wordpress", {}).get("app_password", "")),
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", cfg.get("anthropic", {}).get("api_key", "")),
        "lark_webhook_url": os.environ.get("LARK_WEBHOOK_URL", cfg.get("notifications", {}).get("lark_webhook_url", "")),
    }


CONFIG = load_config()

# CRM Table IDs
TABLE_ORDERS = "tbldLj2iMJYocct6"    # 受注台帳
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"  # 取引先
TABLE_CONTACTS = "tblN53hFIQoo4W8j"  # 連絡先
TABLE_EMAIL_LOG = "tblfBahatPZMJEM5"  # メールログ
TABLE_DEALS = "tbl1rM86nAw9l3bP"     # 商談

# セーフガード
MAX_TARGETS = 30          # 1回の実行で最大30件
DUPLICATE_WINDOW_DAYS = 60  # 同一取引先への送信間隔（日）

# 営業担当マッピング
SALES_REPS = {
    "新美 光": {
        "display": "新美 光",
        "email": "h.niimi@tokaiair.com",
    },
    "新美光": {
        "display": "新美 光",
        "email": "h.niimi@tokaiair.com",
    },
    "ユーザー550372": {
        "display": "政木 勇治",
        "email": "y-masaki@riseasone.jp",
    },
}

DEFAULT_REP = {
    "display": "國本 洋輔",
    "email": "info@tokaiair.com",
}

COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "phone": "052-720-5885",
    "email": "info@tokaiair.com",
    "services": [
        "ドローン測量（公共測量対応・i-Construction）",
        "3次元点群計測・図面化",
        "建物赤外線調査（外壁タイル浮き等）",
        "眺望撮影・空撮",
        "太陽光パネル点検",
    ],
}

SIGNATURE_HTML = """<div style="margin-top:24px;padding-top:16px;border-top:1px solid #ccc;font-size:12px;color:#666;">
<p style="margin:0;">東海エアサービス株式会社<br>
TEL: 052-720-5885<br>
<a href="https://www.tokaiair.com/" style="color:#0066cc;">https://www.tokaiair.com/</a></p>
</div>"""

# 季節別プロンプト
SEASONAL_PROMPTS = {
    "april": {
        "label": "新年度（4月）",
        "context": "4月に入り新年度の予算・計画が動き出す時期。新年度のご挨拶を兼ねて測量計画の有無を確認。",
        "subject_base": "新年度の測量計画についてご挨拶",
    },
    "october": {
        "label": "下期（10月）",
        "context": "10月に入り下期のスタート。年度内に実施予定の測量案件について、冬場前のスケジュール確保を促す。",
        "subject_base": "下期の測量ご計画について",
    },
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Lark API ──
def lark_get_token():
    data = json.dumps({
        "app_id": CONFIG["lark_app_id"],
        "app_secret": CONFIG["lark_app_secret"],
    }).encode()
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
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CONFIG['crm_base_token']}/tables/{table_id}/records?page_size=500"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    if not body:
                        log(f"  [WARN] Empty response (attempt {attempt+1}/3)")
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
                log(f"  [WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if result is None:
            log(f"  [ERROR] Failed to fetch records after 3 attempts for table {table_id}")
            break
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def create_record(token, table_id, fields):
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CONFIG['crm_base_token']}/tables/{table_id}/records"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            return result.get("data", {}).get("record", {}).get("record_id")
    except urllib.error.HTTPError as e:
        log(f"  Lark create record error: {e.code} {e.read().decode()}")
        return None


# ── セグメントCSV読み込み ──
def load_segmentation():
    """crm_segmentation.csv からセグメントA/C群の会社名を取得"""
    segments = {}  # {会社名: セグメント}
    if not SEGMENTATION_CSV.exists():
        log(f"  [WARN] セグメントCSVが見つかりません: {SEGMENTATION_CSV}")
        return segments
    try:
        with open(SEGMENTATION_CSV, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                seg = row.get("セグメント", "").strip()
                company = row.get("会社名（正式）", "").strip()
                company_short = row.get("会社名（略称）", "").strip()
                if seg in ("A", "C"):
                    if company:
                        segments[company] = seg
                    if company_short and company_short != company:
                        segments[company_short] = seg
        log(f"  セグメントCSV: A/C群 {len(segments)}社")
    except Exception as e:
        log(f"  [ERROR] セグメントCSV読み込みエラー: {e}")
    return segments


# ── 対象顧客の抽出 ──
def extract_seasonal_targets(orders, accounts, contacts, email_logs, deals, segments):
    """
    抽出条件:
    - 受注台帳にレコードが存在する取引先
    - 取引先のセグメント = A群 or C群（CSVベース）
    - 連絡先にメールアドレスが登録されている
    - 直近60日以内にメール送信していない
    - 商談ステージが「失注」「不在」でない
    """
    # 1. 受注台帳から取引先IDを収集
    order_account_ids = set()
    order_history = {}  # account_id -> [案件名, ...]
    for rec in orders:
        f = rec.get("fields", {})
        account_links = f.get("取引先", [])
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    rid = link.get("record_id", "")
                    if rid:
                        order_account_ids.add(rid)
                        case_name = str(f.get("案件名", "") or "")
                        if case_name:
                            order_history.setdefault(rid, []).append(case_name)

    log(f"  受注実績あり取引先: {len(order_account_ids)}社")

    # 2. 取引先IDから会社名を取得、セグメントA/Cフィルタ
    account_map = {}  # record_id -> {name, segment, rep}
    for rec in accounts:
        rid = rec.get("record_id", "")
        f = rec.get("fields", {})
        name = str(f.get("会社名", "") or "")
        if not name or rid not in order_account_ids:
            continue

        # セグメント判定（CSVを参照）
        seg = None
        for key in segments:
            if key in name or name in key:
                seg = segments[key]
                break
        if not seg:
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

        account_map[rid] = {
            "name": name,
            "segment": seg,
            "rep_name": rep_name,
            "orders": order_history.get(rid, []),
        }

    log(f"  セグメントA/C群かつ受注実績あり: {len(account_map)}社")

    # 3. 商談ステージで失注・不在を除外
    excluded_accounts = set()
    for rec in deals:
        f = rec.get("fields", {})
        stage = str(f.get("商談ステージ", "") or "")
        if stage in ("失注", "不在"):
            account_links = f.get("取引先", [])
            if isinstance(account_links, list):
                for link in account_links:
                    if isinstance(link, dict):
                        rid = link.get("record_id", "")
                        if rid:
                            excluded_accounts.add(rid)

    for rid in excluded_accounts:
        if rid in account_map:
            log(f"    除外（失注/不在）: {account_map[rid]['name']}")
            del account_map[rid]

    # 4. 連絡先からメールアドレスを紐づけ
    targets = []
    for rid, acct in account_map.items():
        contact = find_contact_for_account(contacts, acct["name"])
        if not contact or not contact.get("email") or "@" not in contact.get("email", ""):
            log(f"    スキップ（メールなし）: {acct['name']}")
            continue
        targets.append({
            "account_id": rid,
            "account_name": acct["name"],
            "segment": acct["segment"],
            "rep_name": acct["rep_name"],
            "orders": acct["orders"],
            "contact_name": contact["name"],
            "contact_title": contact["title"],
            "contact_email": contact["email"],
            "contact_company": contact["company"],
        })

    # 5. メールログで60日重複排除
    now = datetime.now()
    cutoff = now - timedelta(days=DUPLICATE_WINDOW_DAYS)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    recent_emails = set()
    for rec in email_logs:
        f = rec.get("fields", {})
        sent_date = f.get("送信日時")
        if isinstance(sent_date, (int, float)) and sent_date >= cutoff_ms:
            addr = str(f.get("宛先メール", "") or "").lower()
            if addr:
                recent_emails.add(addr)

    before_dedup = len(targets)
    targets = [
        t for t in targets
        if t["contact_email"].lower() not in recent_emails
    ]
    log(f"  60日重複排除: {before_dedup} -> {len(targets)}件")

    # 6. 最大件数制限
    if len(targets) > MAX_TARGETS:
        log(f"  最大{MAX_TARGETS}件に制限（{len(targets)}件中）")
        targets = targets[:MAX_TARGETS]

    return targets


def extract_warm_deal_targets(deals, accounts, contacts, email_logs, existing_targets):
    """
    Warm以上の商談から季節メール対象を抽出。
    既存の受注実績ベース対象と重複しないもののみ追加。
    """
    now = datetime.now()
    cutoff = now - timedelta(days=DUPLICATE_WINDOW_DAYS)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    # 既存対象のメールアドレスを収集（重複排除用）
    existing_emails = {t["contact_email"].lower() for t in existing_targets if t.get("contact_email")}
    existing_account_ids = {t["account_id"] for t in existing_targets if t.get("account_id")}

    # メールログから60日以内の送信先を収集
    recent_emails = set()
    for rec in email_logs:
        f = rec.get("fields", {})
        sent_date = f.get("送信日時")
        if isinstance(sent_date, (int, float)) and sent_date >= cutoff_ms:
            addr = str(f.get("宛先メール", "") or "").lower()
            if addr:
                recent_emails.add(addr)

    # 取引先IDから会社名を引くためのマップ
    account_name_map = {}
    for rec in accounts:
        rid = rec.get("record_id", "")
        name = str(rec.get("fields", {}).get("会社名", "") or "")
        if rid and name:
            account_name_map[rid] = name

    warm_targets = []
    seen_accounts = set()

    for rec in deals:
        f = rec.get("fields", {})

        # Warm以上のみ
        temp = str(f.get("温度感スコア", "") or "")
        if temp not in ("Hot", "Warm"):
            continue

        # 失注・不在は除外
        stage = str(f.get("商談ステージ", "") or "")
        if stage in ("失注", "不在", ""):
            continue

        # 取引先ID取得
        account_links = f.get("取引先", [])
        account_id = ""
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    account_id = link.get("record_id", "")
                elif isinstance(link, str):
                    account_id = link

        # 既にターゲットに含まれている取引先はスキップ
        if account_id and account_id in existing_account_ids:
            continue
        if account_id and account_id in seen_accounts:
            continue

        account_name = account_name_map.get(account_id, "")
        if not account_name:
            # 商談名や新規取引先名からフォールバック
            account_name = str(f.get("商談名", "") or f.get("新規取引先名", "") or "")
        if not account_name:
            continue

        # 連絡先検索
        contact = find_contact_for_account(contacts, account_name)
        if not contact or not contact.get("email") or "@" not in contact.get("email", ""):
            continue

        # 60日重複排除
        if contact["email"].lower() in recent_emails:
            continue
        if contact["email"].lower() in existing_emails:
            continue

        # 担当営業
        rep_name = ""
        rep_field = f.get("担当営業", [])
        if isinstance(rep_field, list):
            for p in rep_field:
                if isinstance(p, dict):
                    rep_name = p.get("name", "")
                elif isinstance(p, str):
                    rep_name = p

        # 商材情報
        product_raw = f.get("商材種別", f.get("商材", ""))
        if isinstance(product_raw, list):
            product = ", ".join(str(p) for p in product_raw)
        else:
            product = str(product_raw or "")

        if account_id:
            seen_accounts.add(account_id)
        existing_emails.add(contact["email"].lower())

        warm_targets.append({
            "account_id": account_id,
            "account_name": account_name,
            "segment": f"Warm({temp})",
            "rep_name": rep_name,
            "orders": [product] if product else ["ドローン測量（商談中）"],
            "contact_name": contact["name"],
            "contact_title": contact["title"],
            "contact_email": contact["email"],
            "contact_company": contact["company"],
        })

    # 最大件数制限（既存分と合わせて）
    remaining = MAX_TARGETS - len(existing_targets)
    if remaining <= 0:
        return []
    return warm_targets[:remaining]


def find_contact_for_account(contacts, account_name):
    """取引先名から連絡先を検索"""
    if not account_name:
        return None
    for rec in contacts:
        f = rec.get("fields", {})
        company = str(f.get("会社名", "") or "")
        email = str(f.get("メールアドレス", "") or "")
        if not email or "@" not in email:
            continue
        if account_name in company or company in account_name:
            return {
                "name": str(f.get("氏名", "") or ""),
                "title": str(f.get("役職", "") or ""),
                "email": email,
                "company": company,
            }
        # 取引先リンクフィールドも確認
        account_link = f.get("取引先", "")
        link_text = _extract_link_text(account_link)
        if link_text and (account_name in link_text or link_text in account_name):
            return {
                "name": str(f.get("氏名", "") or ""),
                "title": str(f.get("役職", "") or ""),
                "email": email,
                "company": link_text or company,
            }
    return None


def _extract_link_text(field_value):
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


# ── Claude APIでメール生成 ──
def generate_seasonal_email(target, season):
    """Claude APIで顧客ごとにパーソナライズしたメール文面を生成"""
    season_info = SEASONAL_PROMPTS[season]
    rep_info = SALES_REPS.get(target["rep_name"], DEFAULT_REP)

    order_desc = ""
    if target["orders"]:
        order_list = target["orders"][:3]  # 最大3件
        order_desc = "、".join(order_list)
    else:
        order_desc = "ドローン測量"

    prompt = f"""あなたは東海エアサービス株式会社の営業担当 {rep_info['display']} として、
季節の挨拶を兼ねた測量計画確認メールを作成してください。

【季節】{season_info['label']}（{season_info['context']}）
【会社情報】東海エアサービス株式会社 — ドローン測量（公共測量対応・i-Construction）
【過去取引】{order_desc}
【顧客情報】{target['account_name']} / {target['contact_name']} {target['contact_title']}様

【ルール】
1. 件名と本文を出力（件名は「件名：」で始める）
2. 過去の取引内容に触れつつ、新規案件の相談を促す
3. 押し売りしない。「ご計画があれば」程度のトーン
4. 300文字以内の本文。敬語は丁寧すぎず
5. HTML形式で出力（<p>タグで段落区切り）
6. 署名ブロックは含めない（システムが自動付与）
7. 件名は「{season_info['subject_base']}」をベースに会社名を入れない形で

【出力形式】
件名：〇〇〇
---
<p>（本文HTML）</p>
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
            "x-api-key": CONFIG["anthropic_api_key"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text
    except Exception as e:
        log(f"  [ERROR] Claude API failed: {e}")
        return None


def parse_email_response(response_text):
    """Claude APIレスポンスから件名とHTML本文を抽出"""
    subject = ""
    body_lines = []
    in_body = False

    for line in response_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("件名：") or stripped.startswith("件名:"):
            subject = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
            continue
        if stripped == "---":
            in_body = not in_body
            continue
        if in_body or (not subject and stripped.startswith("<p>")):
            body_lines.append(line)
            in_body = True

    # 件名のフォールバック
    if not subject:
        subject = SEASONAL_PROMPTS.get("april", {}).get("subject_base", "測量計画のご案内") + " - 東海エアサービス"

    body_html = "\n".join(body_lines).strip()
    # <p>タグがない場合は段落で囲む
    if body_html and not body_html.startswith("<"):
        paragraphs = body_html.split("\n\n")
        body_html = "\n".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

    return subject, body_html


# ── review_agent連携 ──
def run_email_review(subject, body, to_email, from_email="info@tokaiair.com"):
    """送信前にreview_agent.pyのemailプロファイルでチェック。CRITICAL=送信中止"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from review_agent import review
        content = f"To: {to_email}\nFrom: {from_email}\nSubject: {subject}\n\n{body}"
        result = review("email", content, output_json=True)
        return result
    except Exception as e:
        log(f"  レビューエージェント実行エラー（処理は続行）: {e}")
        return {"verdict": "OK", "issues": [], "summary": f"レビュースキップ: {e}"}


# ── WordPress wp_mail送信 ──
def send_email_via_wordpress(to_email, subject, html_body,
                              from_name="東海エアサービス", from_email="info@tokaiair.com"):
    wp_auth = base64.b64encode(
        f"{CONFIG['wp_user']}:{CONFIG['wp_app_password']}".encode()
    ).decode()
    endpoint = CONFIG["wp_base_url"] + "/tas/v1/send-email"

    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Kaku Gothic ProN',sans-serif;font-size:14px;line-height:1.7;color:#333;">
{html_body}
{SIGNATURE_HTML}
</body>
</html>"""

    data = json.dumps({
        "to": to_email,
        "subject": subject,
        "body": full_html,
        "from_name": from_name,
        "from_email": from_email,
        "headers": ["Content-Type: text/html; charset=UTF-8"],
    }).encode()

    req = urllib.request.Request(
        endpoint, data=data,
        headers={
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            success = result.get("success", False)
            if success:
                log(f"    送信完了: {to_email}")
            else:
                log(f"    送信失敗: {result}")
            return success
    except Exception as e:
        log(f"    送信エラー: {e}")
        return False


# ── メールログ記録 ──
def log_email_to_lark(token, to_email, to_name, subject, status, season):
    fields = {
        "シーケンス": f"seasonal_{season}",
        "ステップ": f"seasonal_{season}_{datetime.now().strftime('%Y%m')}",
        "宛先メール": to_email,
        "宛先名": to_name,
        "件名": subject,
        "ステータス": status,
        "送信日時": int(datetime.now().timestamp() * 1000),
    }
    try:
        record_id = create_record(token, TABLE_EMAIL_LOG, fields)
        if record_id:
            log(f"    メールログ記録: {record_id}")
        return record_id
    except Exception as e:
        log(f"    メールログ記録エラー: {e}")
        return None


# ── Lark Webhook通知 ──
def notify_webhook(text):
    webhook = CONFIG.get("lark_webhook_url", "")
    if not webhook:
        return False
    data = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
    req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        return True
    except Exception:
        return False


# ── 季節の自動判定 ──
def detect_season():
    month = datetime.now().month
    if 3 <= month <= 5:
        return "april"
    elif 9 <= month <= 11:
        return "october"
    else:
        # デフォルトは直近の季節
        return "april" if month <= 6 else "october"


# ── メイン処理 ──
def main():
    args = sys.argv[1:]
    send_mode = "--send" in args
    list_only = "--list" in args
    dry_run = "--dry-run" in args

    # 季節指定
    season = None
    if "--season" in args:
        idx = args.index("--season")
        if idx + 1 < len(args):
            season = args[idx + 1].lower()
    if not season:
        season = detect_season()

    if season not in SEASONAL_PROMPTS:
        log(f"[ERROR] 不正な季節指定: {season}（april / october のみ）")
        sys.exit(1)

    season_info = SEASONAL_PROMPTS[season]

    log(f"季節メール自動送信: {season_info['label']}")
    log(f"  モード: {'送信' if send_mode else '一覧のみ' if list_only else 'ドラフト生成'}")
    log("")

    # Lark認証
    token = lark_get_token()

    # CRMデータ取得
    log("  CRMデータ取得中...")
    orders = get_all_records(token, TABLE_ORDERS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    deals = get_all_records(token, TABLE_DEALS)
    email_logs = []
    try:
        email_logs = get_all_records(token, TABLE_EMAIL_LOG)
    except Exception as e:
        log(f"  メールログ取得スキップ: {e}")

    log(f"  受注台帳: {len(orders)}件 / 取引先: {len(accounts)}件 / "
        f"連絡先: {len(contacts)}件 / 商談: {len(deals)}件 / "
        f"メールログ: {len(email_logs)}件")

    # セグメントCSV読み込み
    segments = load_segmentation()
    if not segments:
        log("  [WARN] セグメントデータなし。受注台帳の全取引先を対象にします")
        # フォールバック: 受注台帳に存在する取引先を全てA群として扱う
        for rec in accounts:
            name = str(rec.get("fields", {}).get("会社名", "") or "")
            if name:
                segments[name] = "A"

    # 対象顧客抽出（受注実績 + Warm以上の商談）
    targets = extract_seasonal_targets(orders, accounts, contacts, email_logs, deals, segments)
    warm_targets = extract_warm_deal_targets(deals, accounts, contacts, email_logs, targets)
    if warm_targets:
        log(f"  Warm以上商談からの追加対象: {len(warm_targets)}件")
        targets.extend(warm_targets)

    if not targets:
        log("\n  対象顧客なし")
        notify_webhook(f"季節メール({season_info['label']}): 対象顧客なし")
        return

    log(f"\n  対象顧客: {len(targets)}件")
    log("  " + "-" * 60)
    for t in targets:
        rep = SALES_REPS.get(t["rep_name"], DEFAULT_REP)
        log(f"  [{t['segment']}] {t['account_name']} / {t['contact_name']}様 "
            f"/ {t['contact_email']} / 担当: {rep['display']}")

    if list_only:
        return

    # ドラフト生成
    OUTPUT_DIR.mkdir(exist_ok=True)
    generated = []
    skipped = []

    for i, t in enumerate(targets):
        log(f"\n{'='*60}")
        log(f"  [{i+1}/{len(targets)}] {t['account_name']} / {t['contact_name']}様")

        # Claude APIでメール生成
        response = generate_seasonal_email(t, season)
        if not response:
            log("  [ERROR] メール生成失敗、スキップ")
            skipped.append(t["account_name"])
            continue

        subject, html_body = parse_email_response(response)
        log(f"  件名: {subject}")

        # review_agentチェック
        review_result = run_email_review(subject, html_body, t["contact_email"])
        verdict = review_result.get("verdict", "OK")
        if verdict == "CRITICAL":
            issues = review_result.get("issues", [])
            log(f"  [BLOCKED] レビューNG: {review_result.get('summary', '')}")
            for issue in issues:
                log(f"    - {issue}")
            skipped.append(f"{t['account_name']}(レビューNG)")
            continue
        else:
            log(f"  レビューOK: {review_result.get('summary', 'パス')}")

        # ドラフトファイル保存
        timestamp = datetime.now().strftime("%Y%m%d")
        safe_name = t["account_name"].replace("/", "_").replace(" ", "_").replace("　", "_")[:30]
        draft_file = OUTPUT_DIR / f"{timestamp}_{season}_{safe_name}.html"

        full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Kaku Gothic ProN',sans-serif;font-size:14px;line-height:1.7;color:#333;">
<!-- To: {t['contact_email']} -->
<!-- From: {COMPANY_INFO['email']} -->
<!-- Subject: {subject} -->
<!-- Account: {t['account_name']} -->
<!-- Contact: {t['contact_name']} -->
<!-- Segment: {t['segment']} -->
{html_body}
{SIGNATURE_HTML}
</body>
</html>"""

        with open(draft_file, "w", encoding="utf-8") as f:
            f.write(full_html)
        log(f"  ドラフト保存: {draft_file.name}")

        draft_info = {
            "account_name": t["account_name"],
            "contact_name": t["contact_name"],
            "contact_email": t["contact_email"],
            "subject": subject,
            "html_body": html_body,
            "file": str(draft_file),
            "rep": SALES_REPS.get(t["rep_name"], DEFAULT_REP),
        }

        # 送信モード
        if send_mode:
            success = send_email_via_wordpress(
                to_email=t["contact_email"],
                subject=subject,
                html_body=html_body,
                from_name=COMPANY_INFO["name"],
                from_email=COMPANY_INFO["email"],
            )
            if success:
                log_email_to_lark(
                    token, t["contact_email"], t["contact_name"],
                    subject, "sent", season
                )
                draft_info["status"] = "sent"
            else:
                draft_info["status"] = "send_failed"
        else:
            draft_info["status"] = "draft"

        generated.append(draft_info)
        time.sleep(1)  # API rate limit

    # サマリー
    log(f"\n{'='*60}")
    summary_lines = [
        f"季節メール({season_info['label']}) 処理完了",
        f"  生成: {len(generated)}件 / スキップ: {len(skipped)}件",
    ]
    if send_mode:
        sent = sum(1 for g in generated if g.get("status") == "sent")
        failed = sum(1 for g in generated if g.get("status") == "send_failed")
        summary_lines.append(f"  送信済: {sent}件 / 送信失敗: {failed}件")

    for g in generated:
        status_mark = {"sent": "送信済", "send_failed": "失敗", "draft": "下書き"}.get(g["status"], "?")
        summary_lines.append(f"  [{status_mark}] {g['account_name']} -> {g['contact_email']}")

    if skipped:
        summary_lines.append(f"  スキップ: {', '.join(skipped)}")

    if not send_mode:
        summary_lines.append(f"\n  ドラフト保存先: {OUTPUT_DIR}/")
        summary_lines.append("  送信するには --send フラグを付けて再実行してください")

    summary = "\n".join(summary_lines)
    log(summary)

    # Webhook通知
    notify_webhook(summary)


if __name__ == "__main__":
    main()
