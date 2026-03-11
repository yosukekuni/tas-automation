#!/usr/bin/env python3
"""
リード・ナーチャリング／リサイクルシステム
Cold/Stale/失注/過去顧客を再活性化するための自動メール生成

Usage:
  python3 lead_nurturing.py --analyze   # セグメント分析（統計のみ）
  python3 lead_nurturing.py --list      # ナーチャリング対象一覧
  python3 lead_nurturing.py --generate  # メール文面を生成（ドラフト保存）
  python3 lead_nurturing.py --segment past_customer   # 特定セグメントのみ
  python3 lead_nurturing.py --limit 5   # 生成件数を制限
  python3 lead_nurturing.py --dry       # Claude API呼び出しスキップ

cron:
  毎週月曜 10:00 に --generate で実行 → Lark Botで通知
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

# ─── Configuration ──────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
NURTURE_STATE_FILE = SCRIPT_DIR / "nurture_state.json"
OUTPUT_DIR = SCRIPT_DIR / "nurture_drafts"
LOG_FILE = SCRIPT_DIR / "lead_nurturing.log"

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
TABLE_ORDERS = "tbldLj2iMJYocct6"  # 受注台帳

# Owner open_id for Lark Bot DM
OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# Nurturing cooldown (days)
NURTURE_COOLDOWN_DAYS = 30

# Segment definitions
SEGMENTS = {
    "past_customer": {
        "label": "過去顧客（受注済み）",
        "desc": "受注後6〜12ヶ月経過 → 定期点検・新サービス提案",
        "cooldown_days": 60,
    },
    "stale_hot_warm": {
        "label": "放置Hot/Warm",
        "desc": "Hot/Warmだったが30日以上活動なし → 再活性化",
        "cooldown_days": 30,
    },
    "cold_with_hearing": {
        "label": "Cold（ヒアリング済み）",
        "desc": "ヒアリングしたが見積未提出 → 見積フォロー",
        "cooldown_days": 30,
    },
    "lost_deals": {
        "label": "失注案件",
        "desc": "失注後3〜6ヶ月経過 → 新プラン提案で再アプローチ",
        "cooldown_days": 90,
    },
    "seasonal": {
        "label": "季節トリガー",
        "desc": "建設業者向け春秋の測量需要期 → タイミング提案",
        "cooldown_days": 45,
    },
}

# Sales rep info (shared with auto_followup_email.py)
REP_SIGNATURES = {
    "新美 光": {"display": "新美 光", "email": "niimi@tokaiair.com"},
    "ユーザー550372": {"display": "政木 勇治", "email": "masaki@tokaiair.com"},
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

# Construction-related categories for seasonal targeting
CONSTRUCTION_CATEGORIES = [
    "建設", "土木", "ゼネコン", "測量", "設計", "コンサル",
    "建築", "ハウス", "不動産", "開発", "工事", "造成",
]

# Seasonal months (spring: 3-5, fall: 9-11)
SEASONAL_MONTHS = {
    "spring": [2, 3, 4],     # Propose in Feb-Apr for spring work
    "fall":   [8, 9, 10],    # Propose in Aug-Oct for fall work
}


# ─── Lark API helpers ──────────────────────────────────────

def lark_get_token():
    """Get Lark tenant access token."""
    data = json.dumps({
        "app_id": LARK_APP_ID,
        "app_secret": LARK_APP_SECRET,
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        resp = json.loads(r.read())
    if resp.get("code") != 0:
        raise RuntimeError(f"Lark token error: {resp}")
    return resp["tenant_access_token"]


def get_all_records(token, table_id):
    """Fetch all records from a Lark Bitable table (handles pagination)."""
    records = []
    page_token = None
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def send_lark_bot_dm(token, open_id, message_text):
    """Send a text message to a user via Lark Bot DM."""
    data = json.dumps({
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": message_text}),
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        return resp.get("code") == 0
    except Exception as e:
        log(f"Lark Bot DM error: {e}")
        return False


# ─── Nurture state tracking ────────────────────────────────

def load_nurture_state():
    """Load nurturing state from JSON file."""
    if NURTURE_STATE_FILE.exists():
        try:
            with open(NURTURE_STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_nurture_state(state):
    """Save nurturing state to JSON file."""
    with open(NURTURE_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def is_in_cooldown(state, record_id, segment):
    """Check if a deal is still within the nurturing cooldown period."""
    entry = state.get(record_id)
    if not entry:
        return False
    last_date_str = entry.get("last_nurture_date", "")
    if not last_date_str:
        return False
    try:
        last_date = datetime.fromisoformat(last_date_str)
    except ValueError:
        return False
    cooldown = SEGMENTS.get(segment, {}).get("cooldown_days", NURTURE_COOLDOWN_DAYS)
    return (datetime.now() - last_date).days < cooldown


def record_nurture(state, record_id, segment, deal_name):
    """Record a nurture event for a deal."""
    entry = state.get(record_id, {})
    count = entry.get("nurture_count", 0) + 1
    state[record_id] = {
        "deal_name": deal_name,
        "segment": segment,
        "last_nurture_date": datetime.now().isoformat(),
        "nurture_count": count,
        "history": entry.get("history", []) + [{
            "date": datetime.now().isoformat(),
            "segment": segment,
        }],
    }
    return state


# ─── Logging ───────────────────────────────────────────────

def log(msg):
    """Append a log entry."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except IOError:
        pass


# ─── Field extraction helpers ──────────────────────────────

def _field_str(fields, key, default=""):
    """Extract string value from a Lark field (handles lists, dicts, etc.)."""
    val = fields.get(key, default)
    if val is None:
        return default
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(item.get("text", "") or item.get("name", "") or str(item))
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else default
    return str(val)


def _field_timestamp(fields, key):
    """Extract datetime from a Lark timestamp field (milliseconds)."""
    val = fields.get(key)
    if isinstance(val, (int, float)) and val > 0:
        return datetime.fromtimestamp(val / 1000)
    return None


def _field_person_name(fields, key):
    """Extract person name from a Lark person field."""
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


def _extract_link_text(field_value):
    """Extract text from a Lark link field."""
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        parts = []
        for item in field_value:
            if isinstance(item, dict):
                parts.append(
                    item.get("text_value", "")
                    or item.get("text", "")
                    or item.get("record_id", "")
                )
            elif isinstance(item, str):
                parts.append(item)
        return " ".join(parts)
    return ""


# ─── Segmentation engine ──────────────────────────────────

def build_past_customer_set(orders, now=None):
    """
    Build a set of past customer names from 受注台帳, with order dates.
    Returns dict: { normalized_company_name: { last_order_date, order_count, ... } }
    """
    if now is None:
        now = datetime.now()

    customers = {}
    for rec in orders:
        f = rec.get("fields", {})
        company = _field_str(f, "取引先").strip()
        if not company:
            continue

        order_date = _field_timestamp(f, "受注日")
        amount = f.get("受注金額") or f.get("請求金額")
        case_name = _field_str(f, "案件名")

        # Normalize: strip whitespace, common suffixes
        norm = company.replace("　", " ").strip()

        existing = customers.get(norm, {
            "company": company,
            "last_order_date": None,
            "order_count": 0,
            "total_amount": 0,
            "last_case": "",
        })
        existing["order_count"] += 1
        if isinstance(amount, (int, float)) and amount > 0:
            existing["total_amount"] += amount
        if case_name:
            existing["last_case"] = case_name
        if order_date and (not existing["last_order_date"] or order_date > existing["last_order_date"]):
            existing["last_order_date"] = order_date

        customers[norm] = existing

    return customers


def _match_company(name, past_customers):
    """Fuzzy match a company name against past customers dict. Returns match or None."""
    if not name:
        return None
    norm = name.replace("　", " ").strip()
    # Exact match
    if norm in past_customers:
        return past_customers[norm]
    # Partial match (either direction)
    for key, val in past_customers.items():
        if key in norm or norm in key:
            return val
    return None


def segment_deals(deals, accounts_map, orders, now=None):
    """
    Analyze deals and assign nurturing segments.
    Uses 受注台帳 for past customer identification and real CRM field values.
    Returns dict: { segment_name: [deal_info, ...] }
    """
    if now is None:
        now = datetime.now()

    current_month = now.month
    is_seasonal_period = any(
        current_month in months
        for months in SEASONAL_MONTHS.values()
    )

    # Build past customer set from 受注台帳
    past_customers = build_past_customer_set(orders, now)

    # Track which deals have already been assigned to avoid duplicates
    assigned = set()
    results = defaultdict(list)

    for rec in deals:
        f = rec.get("fields", {})
        record_id = rec.get("record_id", "")

        deal_name = _field_str(f, "商談名", "(名前なし)")
        stage = _field_str(f, "商談ステージ")
        temp = _field_str(f, "温度感スコア")
        hearing = _field_str(f, "ヒアリング内容（まとめ）")
        notes = _field_str(f, "商談内での気づき・備考")
        category = _field_str(f, "客先カテゴリ")
        product = _field_str(f, "商材種別")
        next_action = _field_str(f, "次アクション")
        rep_name = _field_person_name(f, "担当営業")
        no_prospect_reason = _field_str(f, "営業見込みなしの理由")

        # Timestamps -- use record-level timestamps when field timestamps absent
        created_dt = _field_timestamp(f, "商談日")
        updated_dt = None
        # Lark records have auto timestamps at record level
        rec_created = rec.get("created_time")
        rec_updated = rec.get("last_modified_time")
        if isinstance(rec_created, (int, float)) and rec_created > 0:
            created_dt = created_dt or datetime.fromtimestamp(rec_created / 1000)
        if isinstance(rec_updated, (int, float)) and rec_updated > 0:
            updated_dt = datetime.fromtimestamp(rec_updated / 1000)

        next_action_dt = _field_timestamp(f, "次アクション日")

        # Account link
        account_links = f.get("取引先", [])
        account_id = ""
        account_name = ""
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    aid = link.get("record_id", "")
                    if aid:
                        account_id = aid
                        account_name = accounts_map.get(aid, "")
                elif isinstance(link, str):
                    account_id = link
                    account_name = accounts_map.get(link, "")
        elif isinstance(account_links, str):
            account_name = account_links
        if not account_name:
            account_name = _extract_link_text(account_links)

        # Skip deals with no company info at all
        if not account_name and deal_name == "(名前なし)":
            continue

        # Skip 不在 (absent -- never reached)
        if stage == "不在" or temp == "不在のため不明":
            continue

        # Days since last activity
        last_activity = updated_dt or created_dt
        days_since_activity = (now - last_activity).days if last_activity else 999

        # Build deal info dict
        deal_info = {
            "record_id": record_id,
            "deal_name": deal_name,
            "stage": stage,
            "temp": temp,
            "hearing": hearing,
            "notes": notes,
            "category": category,
            "product": product,
            "next_action": next_action,
            "rep_name": rep_name,
            "account_id": account_id,
            "account_name": account_name,
            "days_since_activity": days_since_activity,
            "created_dt": created_dt,
            "updated_dt": updated_dt,
            "no_prospect_reason": no_prospect_reason,
            "fields": f,
        }

        # ── Segment 1: Past customers (from 受注台帳, 6+ months since last order) ──
        search_name = account_name or deal_name
        past_match = _match_company(search_name, past_customers)
        if past_match and past_match.get("last_order_date"):
            months_since = (now - past_match["last_order_date"]).days / 30
            if months_since >= 6:
                deal_info["months_since_close"] = round(months_since, 1)
                deal_info["past_order_count"] = past_match["order_count"]
                deal_info["past_total_amount"] = past_match["total_amount"]
                deal_info["last_case"] = past_match.get("last_case", "")
                if record_id not in assigned:
                    assigned.add(record_id)
                    results["past_customer"].append(deal_info)
                continue

        # ── Segment 2: Stale Hot/Warm (30+ days no activity) ──
        if temp in ("Hot", "Warm") and days_since_activity >= 30:
            if record_id not in assigned:
                assigned.add(record_id)
                results["stale_hot_warm"].append(deal_info)
            continue

        # ── Segment 3: Cold with hearing (had hearing, no quote sent) ──
        has_hearing = bool(hearing and len(hearing.strip()) > 10)
        at_hearing_stage = stage in ("ヒアリング", "") and temp in ("Cold", "Warm", "")
        not_quoted = stage not in ("見積検討",)
        if has_hearing and at_hearing_stage and not_quoted:
            if record_id not in assigned:
                assigned.add(record_id)
                results["cold_with_hearing"].append(deal_info)
            continue

        # ── Segment 4: Lost deals (営業見込みなしの理由 filled, 3+ months ago) ──
        if no_prospect_reason and days_since_activity >= 90:
            deal_info["months_since_loss"] = round(days_since_activity / 30, 1)
            deal_info["loss_reason"] = no_prospect_reason
            if record_id not in assigned:
                assigned.add(record_id)
                results["lost_deals"].append(deal_info)
            continue

        # ── Segment 5: Seasonal triggers (construction companies in season) ──
        if is_seasonal_period and record_id not in assigned:
            is_construction = any(
                kw in (category or "") or kw in (deal_name or "") or kw in (account_name or "")
                for kw in CONSTRUCTION_CATEGORIES
            )
            if is_construction:
                season_name = "春" if current_month in SEASONAL_MONTHS.get("spring", []) else "秋"
                deal_info["season"] = season_name
                assigned.add(record_id)
                results["seasonal"].append(deal_info)

    # Deduplicate past_customer by company name (keep first per company)
    if results.get("past_customer"):
        seen_companies = set()
        deduped = []
        for d in results["past_customer"]:
            company = d.get("account_name") or d["deal_name"]
            if company not in seen_companies:
                seen_companies.add(company)
                deduped.append(d)
        results["past_customer"] = deduped

    return results


# ─── Email generation via Claude API ──────────────────────

EMAIL_TEMPLATES = {
    "past_customer": """あなたは東海エアサービス株式会社の営業担当 {rep_name} です。
過去に受注いただいたお客様へ、定期点検や新サービスの案内メールを書いてください。

【お客様情報】
会社名: {company}
担当者: {contact_name} {contact_title} 様
前回受注からの経過: 約{months_since_close}ヶ月
前回の商材: {product}
業種: {category}

【ヒアリング履歴】
{hearing}

【メール方針】
- 「ご無沙汰しております」から始める
- 前回のお仕事への感謝を述べる
- 定期点検の重要性を自然に提案（前回の商材に関連づけて）
- 新サービス（太陽光パネル点検、赤外線調査等）も軽く紹介
- 押し売りせず「お気軽にご相談ください」のトーン
- 簡潔に（250文字以内の本文）""",

    "stale_hot_warm": """あなたは東海エアサービス株式会社の営業担当 {rep_name} です。
以前お話しさせていただいたお客様に、その後の状況確認メールを書いてください。

【お客様情報】
会社名: {company}
担当者: {contact_name} {contact_title} 様
前回の温度感: {temp}
商談ステージ: {stage}
最終活動から: {days_since_activity}日
関心商材: {product}

【ヒアリング履歴】
{hearing}

【備考】
{notes}

【メール方針】
- 「その後いかがでしょうか」のトーン
- 前回のヒアリング内容に触れて具体性を出す
- 概算見積の提示や、無料相談の提案
- 相手の忙しさに配慮し、プレッシャーをかけない
- 簡潔に（250文字以内の本文）""",

    "cold_with_hearing": """あなたは東海エアサービス株式会社の営業担当 {rep_name} です。
以前ヒアリングさせていただいたが見積に至らなかったお客様に、改めての提案メールを書いてください。

【お客様情報】
会社名: {company}
担当者: {contact_name} {contact_title} 様
業種: {category}
関心商材: {product}

【ヒアリング内容】
{hearing}

【メール方針】
- 「以前お話を伺った際のことを覚えております」的な入り
- ヒアリング内容を踏まえた具体的な見積提案
- 「改めてお見積りをお出しできます」
- 新しい実績や技術アップデートがあれば言及
- 簡潔に（250文字以内の本文）""",

    "lost_deals": """あなたは東海エアサービス株式会社の営業担当 {rep_name} です。
以前ご検討いただいたが失注となったお客様に、改めてのご提案メールを書いてください。

【お客様情報】
会社名: {company}
担当者: {contact_name} {contact_title} 様
失注からの経過: 約{months_since_loss}ヶ月
関心商材: {product}
業種: {category}

【当時のヒアリング内容】
{hearing}

【メール方針】
- 「以前はご検討いただきありがとうございました」から始める
- 以前の失注理由には直接触れない（相手に恥をかかせない）
- 新しいプラン・価格帯・実績をアピール
- 「状況が変わっていればまたお力になれます」のスタンス
- 簡潔に（250文字以内の本文）""",

    "seasonal": """あなたは東海エアサービス株式会社の営業担当 {rep_name} です。
建設業のお客様に、{season}の測量シーズンに向けた提案メールを書いてください。

【お客様情報】
会社名: {company}
担当者: {contact_name} {contact_title} 様
業種: {category}
関心商材: {product}

【ヒアリング履歴】
{hearing}

【メール方針】
- 「{season}の現場が始まる前にご準備を」的なタイミング訴求
- ドローン測量の工期短縮メリットを具体的に
- i-Construction対応・3次元点群のコスト削減効果
- 早期予約のメリット（繁忙期は混雑）
- 簡潔に（250文字以内の本文）""",
}


def generate_nurture_email(segment, deal_info, contact):
    """Generate a nurturing email using Claude API."""
    template = EMAIL_TEMPLATES.get(segment, "")
    if not template:
        return "[ERROR] Unknown segment"

    rep_name_raw = deal_info.get("rep_name", "")
    rep_info = REP_SIGNATURES.get(rep_name_raw, {"display": rep_name_raw or "営業担当"})
    rep_display = rep_info.get("display", rep_name_raw or "営業担当")

    # Build template variables
    vars_dict = {
        "rep_name": rep_display,
        "company": contact.get("company", deal_info.get("account_name", deal_info["deal_name"])),
        "contact_name": contact.get("name", ""),
        "contact_title": contact.get("title", "ご担当者"),
        "temp": deal_info.get("temp", ""),
        "stage": deal_info.get("stage", ""),
        "days_since_activity": deal_info.get("days_since_activity", ""),
        "product": deal_info.get("product", "ドローン測量"),
        "category": deal_info.get("category", ""),
        "hearing": deal_info.get("hearing", "(記録なし)") or "(記録なし)",
        "notes": deal_info.get("notes", "") or "",
        "months_since_close": deal_info.get("months_since_close", ""),
        "months_since_loss": deal_info.get("months_since_loss", ""),
        "season": deal_info.get("season", ""),
    }

    # Safe format (ignore missing keys)
    try:
        prompt_body = template.format(**vars_dict)
    except KeyError as e:
        prompt_body = template  # fallback

    full_prompt = f"""{prompt_body}

【会社情報】
{COMPANY_INFO['name']}
サービス: {', '.join(COMPANY_INFO['services'])}
HP: {COMPANY_INFO['url']}

【出力形式】
件名：〇〇〇
---
（本文）
---
署名:
{COMPANY_INFO['name']}
{rep_display}
"""

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": full_prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            result = json.loads(r.read())
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text
    except Exception as e:
        return f"[ERROR] Claude API failed: {e}"


# ─── Contact resolution ───────────────────────────────────

def build_accounts_map(accounts):
    """Build record_id -> company_name mapping."""
    m = {}
    for rec in accounts:
        rid = rec.get("record_id", "")
        name = _field_str(rec.get("fields", {}), "会社名")
        if rid and name:
            m[rid] = name
    return m


def find_contact(contacts, account_name, deal_name=""):
    """Find a contact record matching the account name."""
    if not account_name and not deal_name:
        return None

    search_terms = [t for t in [account_name, deal_name] if t]

    for rec in contacts:
        f = rec.get("fields", {})
        company = _field_str(f, "会社名")
        account_link_text = _extract_link_text(f.get("取引先", ""))

        for term in search_terms:
            if (company and term in company) or (account_link_text and term in account_link_text):
                return {
                    "name": _field_str(f, "氏名"),
                    "title": _field_str(f, "役職"),
                    "email": _field_str(f, "メールアドレス"),
                    "phone": _field_str(f, "電話番号"),
                    "company": company or account_link_text,
                }
            # Reverse check: company name appears in search term
            if company and company in term:
                return {
                    "name": _field_str(f, "氏名"),
                    "title": _field_str(f, "役職"),
                    "email": _field_str(f, "メールアドレス"),
                    "phone": _field_str(f, "電話番号"),
                    "company": company,
                }

    return None


def make_fallback_contact(deal_info):
    """Create a fallback contact when no CRM contact found."""
    return {
        "name": "",
        "title": "ご担当者",
        "email": "",
        "phone": "",
        "company": deal_info.get("account_name") or deal_info.get("deal_name", ""),
    }


# ─── CLI commands ──────────────────────────────────────────

def cmd_analyze(segmented, state):
    """Show segmentation statistics."""
    total = sum(len(v) for v in segmented.values())
    print()
    print("=" * 65)
    print("  リード・ナーチャリング セグメント分析")
    print("=" * 65)
    print()

    for seg_key, seg_meta in SEGMENTS.items():
        deals_in_seg = segmented.get(seg_key, [])
        actionable = [
            d for d in deals_in_seg
            if not is_in_cooldown(state, d["record_id"], seg_key)
        ]
        in_cooldown = len(deals_in_seg) - len(actionable)

        print(f"  [{seg_meta['label']}]")
        print(f"    {seg_meta['desc']}")
        print(f"    対象: {len(deals_in_seg)}件  (実行可能: {actionable_count(actionable)}件 / クールダウン中: {in_cooldown}件)")
        print(f"    クールダウン: {seg_meta['cooldown_days']}日")

        # Top 3 preview
        if actionable:
            print(f"    --- 上位3件 ---")
            for d in actionable[:3]:
                rep = REP_SIGNATURES.get(d["rep_name"], {}).get("display", d["rep_name"] or "未割当")
                company = d.get("account_name") or d["deal_name"]
                extra = ""
                if seg_key == "past_customer":
                    extra = f"  (受注後{d.get('months_since_close', '?')}ヶ月)"
                elif seg_key == "stale_hot_warm":
                    extra = f"  ({d['days_since_activity']}日間放置)"
                elif seg_key == "lost_deals":
                    extra = f"  (失注後{d.get('months_since_loss', '?')}ヶ月)"
                print(f"      {company} [{rep}]{extra}")
        print()

    print(f"  合計ナーチャリング対象: {total}件")

    # Nurture state stats
    total_nurtured = len(state)
    total_sends = sum(e.get("nurture_count", 0) for e in state.values())
    print(f"  過去のナーチャリング実績: {total_nurtured}件 / 合計{total_sends}通")
    print()


def actionable_count(items):
    return len(items)


def cmd_list(segmented, state):
    """List all nurture targets."""
    print()
    print("=" * 75)
    print("  ナーチャリング対象一覧")
    print("=" * 75)

    for seg_key, seg_meta in SEGMENTS.items():
        deals_in_seg = segmented.get(seg_key, [])
        if not deals_in_seg:
            continue

        print(f"\n  [{seg_meta['label']}] ({len(deals_in_seg)}件)")
        print(f"  {'─' * 70}")

        for d in deals_in_seg:
            rep = REP_SIGNATURES.get(d["rep_name"], {}).get("display", d["rep_name"] or "未割当")
            company = d.get("account_name") or d["deal_name"]
            cooldown = is_in_cooldown(state, d["record_id"], seg_key)
            cd_mark = " [CD]" if cooldown else ""

            extra_parts = []
            if d.get("product"):
                extra_parts.append(d["product"])
            if d.get("category"):
                extra_parts.append(d["category"])
            extra = f" ({', '.join(extra_parts)})" if extra_parts else ""

            has_hearing_mark = " [H]" if d.get("hearing", "").strip() else ""

            print(f"    {company} | {rep} | {d['stage']} | {d['days_since_activity']}日前{extra}{has_hearing_mark}{cd_mark}")

    total = sum(len(v) for v in segmented.values())
    print(f"\n  合計: {total}件  ([H]=ヒアリング有 [CD]=クールダウン中)")
    print()


def cmd_generate(segmented, contacts, state, token, segment_filter=None, limit=None, dry=False):
    """Generate nurturing emails."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    generated = []
    skipped_cooldown = 0
    skipped_no_contact = 0
    errors = 0
    count = 0

    segments_to_process = [segment_filter] if segment_filter else list(SEGMENTS.keys())

    for seg_key in segments_to_process:
        deals_in_seg = segmented.get(seg_key, [])
        seg_label = SEGMENTS.get(seg_key, {}).get("label", seg_key)

        for d in deals_in_seg:
            if limit and count >= limit:
                break

            # Cooldown check
            if is_in_cooldown(state, d["record_id"], seg_key):
                skipped_cooldown += 1
                continue

            # Find contact
            contact = find_contact(
                contacts,
                d.get("account_name", ""),
                d.get("deal_name", ""),
            )
            if not contact:
                contact = make_fallback_contact(d)

            company = contact.get("company") or d.get("account_name") or d["deal_name"]

            print(f"\n{'─' * 60}")
            print(f"  [{seg_label}] {company}")
            print(f"  担当: {REP_SIGNATURES.get(d['rep_name'], {}).get('display', d['rep_name'] or '未割当')}")
            print(f"  連絡先: {contact.get('name', '不明')} ({contact.get('email', 'メール不明')})")

            if dry:
                print("  [DRY RUN] メール生成スキップ")
                email_text = "(ドライラン - 生成スキップ)"
            else:
                print("  メール生成中...")
                email_text = generate_nurture_email(seg_key, d, contact)

                if email_text.startswith("[ERROR]"):
                    print(f"  {email_text}")
                    errors += 1
                    continue

                print(f"\n{email_text}")

            # Save draft
            timestamp = datetime.now().strftime("%Y%m%d")
            safe_company = (company or "unknown").replace("/", "_").replace(" ", "_").replace("\\", "_")[:25]
            draft_file = OUTPUT_DIR / f"{timestamp}_{seg_key}_{safe_company}_{d['record_id'][:8]}.txt"

            with open(draft_file, "w", encoding="utf-8") as df:
                df.write(f"セグメント: {seg_label}\n")
                df.write(f"商談ID: {d['record_id']}\n")
                df.write(f"会社名: {company}\n")
                df.write(f"宛先: {contact.get('email', '不明')}\n")
                df.write(f"担当: {REP_SIGNATURES.get(d['rep_name'], {}).get('display', d['rep_name'])}\n")
                df.write(f"生成日: {datetime.now().isoformat()}\n")
                df.write(f"\n{'=' * 50}\n\n")
                df.write(email_text)

            # Update nurture state
            state = record_nurture(state, d["record_id"], seg_key, d["deal_name"])

            generated.append({
                "segment": seg_key,
                "segment_label": seg_label,
                "company": company,
                "contact_email": contact.get("email", ""),
                "contact_name": contact.get("name", ""),
                "rep": REP_SIGNATURES.get(d["rep_name"], {}).get("display", d["rep_name"]),
                "file": str(draft_file),
            })

            count += 1
            time.sleep(1.5)  # API rate limit

        if limit and count >= limit:
            break

    # Save updated state
    save_nurture_state(state)

    # Summary
    print(f"\n{'=' * 65}")
    print("  ナーチャリングメール生成 完了")
    print(f"{'=' * 65}")
    print(f"  生成: {len(generated)}件")
    print(f"  クールダウンスキップ: {skipped_cooldown}件")
    print(f"  エラー: {errors}件")
    print(f"  ドラフト保存先: {OUTPUT_DIR}/")
    print()

    for g in generated:
        print(f"  [{g['segment_label']}] {g['company']} -> {g['contact_email'] or '(メール不明)'}")

    # Lark Bot notification
    if generated and not dry:
        summary_lines = [
            "--- リード・ナーチャリング実行レポート ---",
            f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"生成: {len(generated)}件 / スキップ: {skipped_cooldown}件",
            "",
        ]
        seg_counts = defaultdict(int)
        for g in generated:
            seg_counts[g["segment_label"]] += 1
        for label, cnt in seg_counts.items():
            summary_lines.append(f"  {label}: {cnt}件")
        summary_lines.append("")
        summary_lines.append("対象企業:")
        for g in generated[:10]:
            summary_lines.append(f"  - {g['company']} ({g['segment_label']})")
        if len(generated) > 10:
            summary_lines.append(f"  ...他{len(generated) - 10}件")
        summary_lines.append(f"\nドラフト保存先: nurture_drafts/")

        summary_text = "\n".join(summary_lines)

        try:
            sent = send_lark_bot_dm(token, OWNER_OPEN_ID, summary_text)
            if sent:
                print("\n  Lark Bot通知: 送信完了")
            else:
                print("\n  Lark Bot通知: 送信失敗（権限を確認してください）")
        except Exception as e:
            print(f"\n  Lark Bot通知エラー: {e}")

    # Log
    log(f"Generated {len(generated)} nurture emails. Skipped {skipped_cooldown} (cooldown). Errors: {errors}")

    return generated


# ─── Main ──────────────────────────────────────────────────

def main():
    args = sys.argv[1:]

    mode_analyze = "--analyze" in args
    mode_list = "--list" in args
    mode_generate = "--generate" in args
    dry_run = "--dry" in args

    # Optional segment filter
    segment_filter = None
    if "--segment" in args:
        idx = args.index("--segment")
        if idx + 1 < len(args):
            segment_filter = args[idx + 1]
            if segment_filter not in SEGMENTS:
                print(f"ERROR: Unknown segment '{segment_filter}'")
                print(f"Valid segments: {', '.join(SEGMENTS.keys())}")
                sys.exit(1)

    # Optional limit
    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            try:
                limit = int(args[idx + 1])
            except ValueError:
                print("ERROR: --limit requires an integer")
                sys.exit(1)

    if not any([mode_analyze, mode_list, mode_generate]):
        print(__doc__)
        sys.exit(0)

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] リード・ナーチャリングシステム 起動")
    if segment_filter:
        print(f"  セグメントフィルタ: {SEGMENTS[segment_filter]['label']}")
    if limit:
        print(f"  生成上限: {limit}件")
    if dry_run:
        print("  [DRY RUN モード]")
    print()

    # Get Lark token
    print("  Larkトークン取得中...")
    token = lark_get_token()
    print("  OK")

    # Fetch CRM data
    print("  CRMデータ取得中...")
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    orders = get_all_records(token, TABLE_ORDERS)
    print(f"  商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件 / 受注: {len(orders)}件")

    # Build accounts map
    accounts_map = build_accounts_map(accounts)

    # Segment deals
    print("  セグメント分析中...")
    segmented = segment_deals(deals, accounts_map, orders)

    # Load nurture state
    state = load_nurture_state()

    # Execute command
    if mode_analyze:
        cmd_analyze(segmented, state)

    elif mode_list:
        cmd_list(segmented, state)

    elif mode_generate:
        cmd_generate(
            segmented, contacts, state, token,
            segment_filter=segment_filter,
            limit=limit,
            dry=dry_run,
        )


if __name__ == "__main__":
    main()
