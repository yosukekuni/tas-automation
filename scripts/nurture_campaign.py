#!/usr/bin/env python3
"""
セグメント別ナーチャリングメール自動生成・送信

連絡先319件を温度感スコアベースで3セグメントに分類し、
セグメント別にパーソナライズしたメールを生成・送信する。

セグメント:
  Seg1: Hot/Warm（~37件）→ 月1回。訪問済みなので「ご無沙汰」系。実績+季節提案
  Seg2: Cold/未設定/不在（~280件）→ 四半期1回。事例紹介+土量計算機
  Seg3: 土量計算機リード（~18件）→ 既存email_nurturing_sequencesに委任

Usage:
  python3 nurture_campaign.py --dry-run          # 対象リスト+メールプレビュー（送信なし）
  python3 nurture_campaign.py --dry-run --seg1   # Seg1のみプレビュー
  python3 nurture_campaign.py --dry-run --seg2   # Seg2のみプレビュー
  python3 nurture_campaign.py --send             # WordPress wp_mail経由で送信
  python3 nurture_campaign.py --send --seg1      # Seg1のみ送信
  python3 nurture_campaign.py --list             # セグメント一覧のみ表示
  python3 nurture_campaign.py --limit 3          # 生成件数を制限（テスト用）

cron (GitHub Actions):
  Seg1: 毎月第1月曜 9:00
  Seg2: 1月/4月/7月/10月の第1月曜 9:00
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

# ── 設定 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
_LOCAL_CONFIG = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
_SCRIPT_CONFIG = SCRIPT_DIR / "automation_config.json"
CONFIG_FILE = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _SCRIPT_CONFIG

OUTPUT_DIR = SCRIPT_DIR / "nurture_campaign_drafts"
STATE_FILE = SCRIPT_DIR / "nurture_campaign_state.json"
LOG_FILE = SCRIPT_DIR / "nurture_campaign.log"


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
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ORDERS = "tbldLj2iMJYocct6"
TABLE_EMAIL_LOG = "tblfBahatPZMJEM5"

# セーフガード
MAX_SENDS_PER_RUN = 50
COOLDOWN_SEG1_DAYS = 25   # Seg1: 月1回 → 25日クールダウン
COOLDOWN_SEG2_DAYS = 80   # Seg2: 四半期1回 → 80日クールダウン
DUPLICATE_WINDOW_DAYS = 14  # 同一宛先への全体重複チェック（14日）

# 会社情報
COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "phone": "052-720-5885",
    "email": "info@tokaiair.com",
    "calc_url": "https://www.tokaiair.com/soil-volume-calculator/",
    "contact_url": "https://www.tokaiair.com/contact/",
}

SIGNATURE_HTML = """<div style="margin-top:24px;padding-top:16px;border-top:1px solid #ccc;font-size:12px;color:#666;">
<p style="margin:0;">東海エアサービス株式会社<br>
TEL: 052-720-5885<br>
<a href="https://www.tokaiair.com/" style="color:#0066cc;">https://www.tokaiair.com/</a></p>
</div>"""

# 季節コンテキスト
def get_seasonal_context():
    """現在月に合わせた季節の案件提案テキストを返す"""
    month = datetime.now().month
    if month in (1, 2, 3):
        return "年度末の測量需要に向けて。3月までの予算消化案件や、来年度に向けた概算見積のご準備はいかがでしょうか。"
    elif month in (4, 5, 6):
        return "新年度がスタートし、測量計画が動き出す時期です。梅雨前の好天期に現場を進めるのが効率的です。"
    elif month in (7, 8, 9):
        return "夏場の現場は暑さ対策が重要ですが、ドローン測量なら作業員の負担を大幅に軽減できます。下期の計画もお早めに。"
    else:  # 10, 11, 12
        return "年内の残案件消化と来年度の予算取りの時期です。冬場の測量はドローンが効率的です。"


# ── ログ ──────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Lark API ──────────────────────────────────────────────
def lark_get_token():
    data = json.dumps({
        "app_id": CONFIG["lark_app_id"],
        "app_secret": CONFIG["lark_app_secret"],
    }).encode()
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
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("data", {}).get("record", {}).get("record_id")
    except urllib.error.HTTPError as e:
        log(f"  Lark create record error: {e.code} {e.read().decode()}")
        return None


# ── フィールド抽出ヘルパー ────────────────────────────────
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


def _extract_link_text(field_value):
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        texts = []
        for item in field_value:
            if isinstance(item, dict):
                texts.append(item.get("text_value", "") or item.get("text", "") or item.get("record_id", ""))
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts)
    return ""


def _extract_link_record_ids(field_value):
    """リンクフィールドからrecord_idのリストを取得"""
    ids = []
    if isinstance(field_value, list):
        for item in field_value:
            if isinstance(item, dict):
                rid = item.get("record_id", "")
                if rid:
                    ids.append(rid)
            elif isinstance(item, str):
                ids.append(item)
    elif isinstance(field_value, str):
        ids.append(field_value)
    return ids


# ── 状態管理 ──────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_in_cooldown(state, contact_id, segment):
    entry = state.get(contact_id)
    if not entry:
        return False
    last_str = entry.get("last_sent_date", "")
    if not last_str:
        return False
    try:
        last_date = datetime.fromisoformat(last_str)
    except ValueError:
        return False
    cooldown = COOLDOWN_SEG1_DAYS if segment == "seg1" else COOLDOWN_SEG2_DAYS
    return (datetime.now() - last_date).days < cooldown


def record_send(state, contact_id, segment, company, email):
    entry = state.get(contact_id, {})
    count = entry.get("send_count", 0) + 1
    state[contact_id] = {
        "company": company,
        "email": email,
        "segment": segment,
        "last_sent_date": datetime.now().isoformat(),
        "send_count": count,
        "history": entry.get("history", []) + [{
            "date": datetime.now().isoformat(),
            "segment": segment,
        }],
    }
    return state


# ── セグメント分類 ────────────────────────────────────────
def segment_contacts(contacts, deals, accounts_map):
    """
    連絡先を3セグメントに分類。
    温度感スコアは連絡先テーブルにある。商談テーブルのヒアリング内容も参照。
    """
    # 商談データを取引先record_id別にまとめる
    deal_by_account = defaultdict(list)
    for d in deals:
        f = d.get("fields", {})
        account_links = f.get("取引先", [])
        rids = _extract_link_record_ids(account_links)
        deal_info = {
            "deal_name": _field_str(f, "商談名"),
            "stage": _field_str(f, "商談ステージ"),
            "hearing": _field_str(f, "ヒアリング内容（まとめ）"),
            "product": _field_str(f, "商材種別"),
            "notes": _field_str(f, "商談内での気づき・備考"),
        }
        for rid in rids:
            deal_by_account[rid].append(deal_info)

    seg1 = []  # Hot/Warm
    seg2 = []  # Cold/未設定/不在
    seg3 = []  # 土量計算機リード

    for rec in contacts:
        f = rec.get("fields", {})
        record_id = rec.get("record_id", "")

        name = _field_str(f, "氏名")
        company = _field_str(f, "会社名")
        email = _field_str(f, "メールアドレス")
        title = _field_str(f, "役職")
        phone = _field_str(f, "電話番号")
        temp = _field_str(f, "温度感スコア")
        channel = _field_str(f, "接触チャネル")
        source = _field_str(f, "流入元")
        category = _field_str(f, "客先カテゴリ")

        # 取引先リンク
        account_link = f.get("取引先", [])
        account_rids = _extract_link_record_ids(account_link)
        account_name = ""
        for rid in account_rids:
            if rid in accounts_map:
                account_name = accounts_map[rid]
                break
        if not account_name:
            account_name = _extract_link_text(account_link)

        # 会社名の決定（連絡先の会社名 > 取引先リンク名）
        display_company = company or account_name or "(不明)"

        # メールアドレスなし→スキップ
        if not email or "@" not in email:
            continue

        # 関連商談情報を取得
        related_deals = []
        for rid in account_rids:
            related_deals.extend(deal_by_account.get(rid, []))

        # ヒアリング内容・商材をまとめる
        hearings = [d["hearing"] for d in related_deals if d.get("hearing")]
        products = [d["product"] for d in related_deals if d.get("product")]
        stages = [d["stage"] for d in related_deals if d.get("stage")]
        notes = [d["notes"] for d in related_deals if d.get("notes")]

        contact_info = {
            "record_id": record_id,
            "name": name,
            "company": display_company,
            "email": email,
            "title": title,
            "phone": phone,
            "temp": temp,
            "channel": channel,
            "source": source,
            "category": category,
            "account_rids": account_rids,
            "hearings": hearings[:3],  # 最大3件
            "products": list(set(products))[:3],
            "stages": stages,
            "notes": notes[:2],
        }

        # セグメント判定
        # Seg3: 土量計算機リード（流入元 or 接触チャネルに「計算機」「calculator」含む）
        source_lower = (source + channel).lower()
        if "計算機" in source_lower or "calculator" in source_lower or "土量" in source_lower:
            seg3.append(contact_info)
            continue

        # Seg1: Hot/Warm
        if temp in ("Hot", "Warm"):
            seg1.append(contact_info)
            continue

        # Seg2: Cold/未設定/不在のため不明/その他
        seg2.append(contact_info)

    return seg1, seg2, seg3


# ── Claude APIでメール生成 ────────────────────────────────
SEG1_PROMPT = """あなたは東海エアサービス株式会社の國本洋輔です。
過去に訪問して名刺交換済みの「温度感が高い」お客様に対し、
定期的な関係維持のためのメールを作成してください。

【お客様情報】
会社名: {company}
担当者: {name} {title}様
業種: {category}
関心商材: {products}

【過去のヒアリング内容】
{hearings}

【季節コンテキスト】
{seasonal}

【メール方針】
1. 「ご無沙汰しております」系の書き出し
2. 直近の実績事例を1つ具体的に紹介（例: 「先日、〇〇市内の造成現場で3次元測量を実施し、作業期間を従来の1/3に短縮できました」等の架空だが現実的な事例）
3. 季節に合った案件提案（年度末予算消化、新年度計画等）
4. CTAは「お気軽にお電話ください」「ご計画がございましたらご相談ください」程度
5. 300文字以内。押し売りしない
6. 社外秘情報（顧客名、売上、社内事情）は絶対に含めない
7. 「AI」「Claude」等の技術名は使わない
8. HTML形式（<p>タグで段落）
9. 署名は含めない（システムが自動付与）

【出力形式】
件名：〇〇〇
---
<p>（本文HTML）</p>
"""

SEG2_PROMPT = """あなたは東海エアサービス株式会社の國本洋輔です。
過去に訪問したが反応が薄かった（Cold/未設定）お客様に対し、
事例紹介をメインにした軽いナーチャリングメールを作成してください。

【お客様情報】
会社名: {company}
担当者: {name} {title}様
業種: {category}

【メール方針】
1. 「以前お伺いした際にはありがとうございました」系の書き出し
2. 事例紹介: ドローン測量の工期短縮・コスト削減の具体例を1つ（架空だが現実的）
3. 土量計算機の案内: 「ちなみに、現場の土量をWeb上で簡易算出できる無料ツールをご用意しました」
4. 土量計算機URL: {calc_url}
5. 問い合わせ先: お電話({phone}) or お問い合わせフォーム({contact_url})
6. 250文字以内。あっさりしたトーン
7. 社外秘情報（顧客名、売上、社内事情）は絶対に含めない
8. 「AI」「Claude」等の技術名は使わない
9. HTML形式（<p>タグで段落）
10. 署名は含めない（システムが自動付与）

【出力形式】
件名：〇〇〇
---
<p>（本文HTML）</p>
"""


def generate_email_content(segment, contact_info):
    """Claude APIでメール文面を生成"""
    seasonal = get_seasonal_context()

    if segment == "seg1":
        prompt = SEG1_PROMPT.format(
            company=contact_info["company"],
            name=contact_info["name"] or "ご担当者",
            title=contact_info.get("title", ""),
            category=contact_info.get("category", "建設業"),
            products=", ".join(contact_info.get("products", [])) or "ドローン測量",
            hearings="\n".join(contact_info.get("hearings", [])) or "(記録なし)",
            seasonal=seasonal,
        )
    else:  # seg2
        prompt = SEG2_PROMPT.format(
            company=contact_info["company"],
            name=contact_info["name"] or "ご担当者",
            title=contact_info.get("title", ""),
            category=contact_info.get("category", ""),
            calc_url=COMPANY_INFO["calc_url"],
            phone=COMPANY_INFO["phone"],
            contact_url=COMPANY_INFO["contact_url"],
        )

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}],
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

    if not subject:
        subject = "東海エアサービスよりご案内"

    body_html = "\n".join(body_lines).strip()
    if body_html and not body_html.startswith("<"):
        paragraphs = body_html.split("\n\n")
        body_html = "\n".join(f"<p>{p.strip()}</p>" for p in paragraphs if p.strip())

    return subject, body_html


# ── review_agent連携 ──────────────────────────────────────
def run_email_review(subject, body, to_email, from_email="info@tokaiair.com"):
    """送信前にreview_agent.pyのemailプロファイルでチェック"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from review_agent import review
        content = f"To: {to_email}\nFrom: {from_email}\nSubject: {subject}\n\n{body}"
        result = review("email", content, output_json=True)
        return result
    except Exception as e:
        log(f"  レビューエージェント実行エラー（処理は続行）: {e}")
        return {"verdict": "OK", "issues": [], "summary": f"レビュースキップ: {e}"}


# ── WordPress wp_mail送信 ─────────────────────────────────
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


# ── メールログ記録 ────────────────────────────────────────
def log_email_to_lark(token, to_email, to_name, subject, status, segment):
    fields = {
        "シーケンス": f"nurture_campaign_{segment}",
        "ステップ": f"nurture_{segment}_{datetime.now().strftime('%Y%m')}",
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


# ── 重複チェック（メールログ） ─────────────────────────────
def get_recent_email_addresses(token):
    """直近14日以内にメール送信したアドレスのセットを返す"""
    try:
        email_logs = get_all_records(token, TABLE_EMAIL_LOG)
    except Exception:
        return set()

    now = datetime.now()
    cutoff_ms = int((now - timedelta(days=DUPLICATE_WINDOW_DAYS)).timestamp() * 1000)
    recent = set()
    for rec in email_logs:
        f = rec.get("fields", {})
        sent_date = f.get("送信日時")
        if isinstance(sent_date, (int, float)) and sent_date >= cutoff_ms:
            addr = str(f.get("宛先メール", "") or "").lower().strip()
            if addr:
                recent.add(addr)
    return recent


# ── 取引先マップ構築 ──────────────────────────────────────
def build_accounts_map(accounts):
    m = {}
    for rec in accounts:
        rid = rec.get("record_id", "")
        f = rec.get("fields", {})
        name = _field_str(f, "会社名") or _field_str(f, "会社名（正式）") or _field_str(f, "会社名（略称）")
        if rid and name:
            m[rid] = name
    return m


# ── メイン処理 ────────────────────────────────────────────
def main():
    args = sys.argv[1:]

    dry_run = "--dry-run" in args
    send_mode = "--send" in args
    list_only = "--list" in args
    seg1_only = "--seg1" in args
    seg2_only = "--seg2" in args

    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            try:
                limit = int(args[idx + 1])
            except ValueError:
                print("ERROR: --limit requires an integer")
                sys.exit(1)

    if not any([dry_run, send_mode, list_only]):
        print(__doc__)
        sys.exit(0)

    log("=" * 65)
    log("  セグメント別ナーチャリングキャンペーン")
    log(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    mode_str = "送信" if send_mode else "プレビュー（dry-run）" if dry_run else "一覧のみ"
    log(f"  モード: {mode_str}")
    if seg1_only:
        log("  セグメント: Seg1（Hot/Warm）のみ")
    elif seg2_only:
        log("  セグメント: Seg2（Cold/未設定）のみ")
    if limit:
        log(f"  生成上限: {limit}件")
    log("=" * 65)

    # Lark認証
    log("\n  Larkトークン取得中...")
    token = lark_get_token()
    log("  OK")

    # CRMデータ取得
    log("  CRMデータ取得中...")
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    deals = get_all_records(token, TABLE_DEALS)
    log(f"  連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件 / 商談: {len(deals)}件")

    # 取引先マップ
    accounts_map = build_accounts_map(accounts)

    # セグメント分類
    log("  セグメント分類中...")
    seg1, seg2, seg3 = segment_contacts(contacts, deals, accounts_map)
    log(f"  Seg1 (Hot/Warm): {len(seg1)}件")
    log(f"  Seg2 (Cold/未設定): {len(seg2)}件")
    log(f"  Seg3 (土量計算機リード): {len(seg3)}件 → email_nurturing_sequences.pyに委任")

    # 状態読み込み
    state = load_state()

    # メールログから重複チェック
    log("  メール送信履歴チェック中...")
    recent_emails = get_recent_email_addresses(token)
    log(f"  直近{DUPLICATE_WINDOW_DAYS}日間の送信済み: {len(recent_emails)}件")

    # 一覧表示
    if list_only:
        _print_list("Seg1 (Hot/Warm) - 月1回メール", seg1, state, "seg1")
        _print_list("Seg2 (Cold/未設定) - 四半期1回メール", seg2, state, "seg2")
        _print_list("Seg3 (土量計算機リード) - 既存フロー", seg3, state, "seg3")
        return

    # 処理対象セグメント
    targets = []
    if not seg2_only:
        for c in seg1:
            if not is_in_cooldown(state, c["record_id"], "seg1"):
                if c["email"].lower() not in recent_emails:
                    targets.append(("seg1", c))
    if not seg1_only:
        for c in seg2:
            if not is_in_cooldown(state, c["record_id"], "seg2"):
                if c["email"].lower() not in recent_emails:
                    targets.append(("seg2", c))

    if limit:
        targets = targets[:limit]

    if not targets:
        log("\n  対象なし（全件クールダウン中 or 最近送信済み）")
        return

    log(f"\n  処理対象: {len(targets)}件")
    seg1_count = sum(1 for s, _ in targets if s == "seg1")
    seg2_count = sum(1 for s, _ in targets if s == "seg2")
    log(f"    Seg1: {seg1_count}件 / Seg2: {seg2_count}件")

    # ドラフト生成ループ
    OUTPUT_DIR.mkdir(exist_ok=True)
    generated = []
    skipped = []
    errors = 0

    for i, (segment, contact) in enumerate(targets):
        if len(generated) >= MAX_SENDS_PER_RUN:
            log(f"\n  最大送信数({MAX_SENDS_PER_RUN})に到達。残りは次回実行に")
            break

        seg_label = "Seg1(Hot/Warm)" if segment == "seg1" else "Seg2(Cold/未設定)"
        log(f"\n{'─' * 60}")
        log(f"  [{i+1}/{len(targets)}] [{seg_label}] {contact['company']}")
        log(f"  宛先: {contact['name']} {contact.get('title', '')}様 <{contact['email']}>")

        if dry_run:
            # dry-runでもClaude APIを呼んでプレビュー表示
            log("  メール生成中...")
            response = generate_email_content(segment, contact)
            if not response:
                log("  [ERROR] メール生成失敗")
                errors += 1
                continue

            subject, html_body = parse_email_response(response)
            log(f"  件名: {subject}")

            # review_agentチェック
            review_result = run_email_review(subject, html_body, contact["email"])
            verdict = review_result.get("verdict", "OK")
            if verdict == "CRITICAL":
                log(f"  [BLOCKED] レビューNG: {review_result.get('summary', '')}")
                skipped.append(f"{contact['company']}(レビューNG)")
                continue
            log(f"  レビュー: {verdict} - {review_result.get('summary', 'OK')}")

            # プレビュー表示
            log(f"\n  --- メールプレビュー ---")
            log(f"  To: {contact['email']}")
            log(f"  From: info@tokaiair.com")
            log(f"  Subject: {subject}")
            # HTML本文のプレビュー（タグ除去して表示）
            import re
            plain = re.sub(r'<[^>]+>', '', html_body).strip()
            for line in plain.split("\n"):
                if line.strip():
                    log(f"  | {line.strip()}")
            log(f"  --- プレビュー終了 ---")

            # ドラフト保存
            timestamp = datetime.now().strftime("%Y%m%d")
            safe_name = contact["company"].replace("/", "_").replace(" ", "_").replace("　", "_")[:30]
            draft_file = OUTPUT_DIR / f"{timestamp}_{segment}_{safe_name}.html"
            _save_draft(draft_file, subject, html_body, contact, segment)
            log(f"  ドラフト保存: {draft_file.name}")

            generated.append({
                "segment": segment,
                "company": contact["company"],
                "email": contact["email"],
                "name": contact["name"],
                "subject": subject,
                "status": "draft",
            })

            time.sleep(1.5)  # API rate limit

        elif send_mode:
            # 本番送信
            log("  メール生成中...")
            response = generate_email_content(segment, contact)
            if not response:
                log("  [ERROR] メール生成失敗")
                errors += 1
                continue

            subject, html_body = parse_email_response(response)
            log(f"  件名: {subject}")

            # review_agentチェック（CLAUDE.mdルール: 送信前チェック必須）
            review_result = run_email_review(subject, html_body, contact["email"])
            verdict = review_result.get("verdict", "OK")
            if verdict == "CRITICAL":
                log(f"  [BLOCKED] レビューNG: {review_result.get('summary', '')}")
                skipped.append(f"{contact['company']}(レビューNG)")
                continue
            log(f"  レビュー: {verdict} - {review_result.get('summary', 'OK')}")

            # ドラフト保存（送信前にも保存）
            timestamp = datetime.now().strftime("%Y%m%d")
            safe_name = contact["company"].replace("/", "_").replace(" ", "_").replace("　", "_")[:30]
            draft_file = OUTPUT_DIR / f"{timestamp}_{segment}_{safe_name}.html"
            _save_draft(draft_file, subject, html_body, contact, segment)

            # WordPress経由送信
            success = send_email_via_wordpress(
                to_email=contact["email"],
                subject=subject,
                html_body=html_body,
            )

            if success:
                # メールログ記録
                log_email_to_lark(
                    token, contact["email"], contact["name"],
                    subject, "sent", segment
                )
                # 状態更新
                state = record_send(
                    state, contact["record_id"], segment,
                    contact["company"], contact["email"]
                )
                save_state(state)
                status = "sent"
            else:
                status = "send_failed"

            generated.append({
                "segment": segment,
                "company": contact["company"],
                "email": contact["email"],
                "name": contact["name"],
                "subject": subject,
                "status": status,
            })

            time.sleep(2)  # 送信間隔

    # サマリー
    log(f"\n{'=' * 65}")
    log("  ナーチャリングキャンペーン 処理完了")
    log(f"{'=' * 65}")
    log(f"  生成/送信: {len(generated)}件")
    log(f"  スキップ: {len(skipped)}件")
    log(f"  エラー: {errors}件")

    if generated:
        seg1_gen = [g for g in generated if g["segment"] == "seg1"]
        seg2_gen = [g for g in generated if g["segment"] == "seg2"]
        if seg1_gen:
            log(f"\n  --- Seg1 (Hot/Warm) ---")
            for g in seg1_gen:
                status = {"sent": "送信済", "send_failed": "失敗", "draft": "下書き"}.get(g["status"], "?")
                log(f"    [{status}] {g['company']} -> {g['email']}")
        if seg2_gen:
            log(f"\n  --- Seg2 (Cold/未設定) ---")
            for g in seg2_gen:
                status = {"sent": "送信済", "send_failed": "失敗", "draft": "下書き"}.get(g["status"], "?")
                log(f"    [{status}] {g['company']} -> {g['email']}")

    if dry_run:
        log(f"\n  ドラフト保存先: {OUTPUT_DIR}/")
        log("  送信するには --send フラグで再実行してください")

    log("")


def _print_list(label, contacts, state, segment):
    """セグメントの連絡先一覧を表示"""
    log(f"\n  [{label}] ({len(contacts)}件)")
    log(f"  {'─' * 60}")
    for c in contacts:
        cd = is_in_cooldown(state, c["record_id"], segment)
        cd_mark = " [CD]" if cd else ""
        temp_mark = f" [{c['temp']}]" if c.get("temp") else ""
        log(f"    {c['company']} | {c['name']} | {c['email']}{temp_mark}{cd_mark}")


def _save_draft(draft_file, subject, html_body, contact, segment):
    """ドラフトHTMLファイルを保存"""
    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{subject}</title></head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Kaku Gothic ProN',sans-serif;font-size:14px;line-height:1.7;color:#333;">
<!-- To: {contact['email']} -->
<!-- From: info@tokaiair.com -->
<!-- Subject: {subject} -->
<!-- Company: {contact['company']} -->
<!-- Contact: {contact['name']} -->
<!-- Segment: {segment} -->
<!-- Generated: {datetime.now().isoformat()} -->
{html_body}
{SIGNATURE_HTML}
</body>
</html>"""

    with open(draft_file, "w", encoding="utf-8") as f:
        f.write(full_html)


if __name__ == "__main__":
    main()
