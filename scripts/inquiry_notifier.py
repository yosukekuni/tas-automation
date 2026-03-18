#!/usr/bin/env python3
"""
問い合わせメール即時通知 (営業メール除外フィルター付き)

TAS (info@tokaiair.com) / TOMOSHI (info@tomoshi.jp) への問い合わせを検知し、
営業メールを除外した上でCEOにLark Bot DMで即時通知する。

動作モード:
  - ローカル: Spark Desktop SQLiteから新着検出 (デフォルト)
  - CI/IMAP: IMAP経由で新着チェック (--imap フラグ or INQUIRY_MODE=imap)

Usage:
  python3 inquiry_notifier.py              # ローカル実行 (SparkDB)
  python3 inquiry_notifier.py --imap       # IMAP経由 (GitHub Actions用)
  python3 inquiry_notifier.py --dry-run    # 通知送信なし
  python3 inquiry_notifier.py --init       # 初期化 (既存メールをスキップ)
"""

import argparse
import email
import email.policy
import imaplib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── 定数 ──
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "inquiry_notifier_state.json"

SPARK_DB = Path(r"/mnt/c/Users/USER/AppData/Local/Spark Desktop/core-data/databases/messages.sqlite")
ACCOUNT_PK = 12  # info@tokaiair.com

# Config読み込み
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
    CONFIG = _cfg if "_cfg" in dir() else {}

LARK_APP_ID = CONFIG.get("lark", {}).get("app_id", os.environ.get("LARK_APP_ID", ""))
LARK_APP_SECRET = CONFIG.get("lark", {}).get("app_secret", os.environ.get("LARK_APP_SECRET", ""))
CRM_BASE_TOKEN = CONFIG.get("lark", {}).get("crm_base_token", os.environ.get("CRM_BASE_TOKEN", ""))
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"
BASE_URL = "https://open.larksuite.com/open-apis"

# IMAP設定 (.env or 環境変数)
ENV_PATH = Path("/home/user/tokaiair/.env")
if ENV_PATH.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        # dotenvなしの場合は手動パース
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

IMAP_HOST = os.environ.get("LARK_IMAP_HOST", "imap.larksuite.com")
IMAP_PORT = int(os.environ.get("LARK_IMAP_PORT", "993"))
IMAP_USER = os.environ.get("LARK_IMAP_USER", "info@tokaiair.com")
IMAP_PASS = os.environ.get("LARK_IMAP_PASS", os.environ.get("IMAP_PASS", ""))

# 取引先テーブル (ホワイトリスト用)
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# ── 営業メール除外フィルター ──

# 件名NGワード
SUBJECT_NG_WORDS = [
    "SEO", "Web制作", "ホームページ制作", "人材", "求人", "営業",
    "ご提案", "広告", "集客", "無料", "キャンペーン", "代行",
    "サービスのご案内", "パートナー", "業務提携", "コスト削減",
    "助成金", "補助金", "セミナー", "ウェビナー", "展示会",
    "メルマガ", "ニュースレター", "プレスリリース", "取材",
    "マーケティング", "リスティング", "SNS運用", "動画制作",
    "DX推進", "IT導入", "クラウド", "SaaS", "BPO",
    "アウトソーシング", "コンサルティング", "研修", "セールス",
    "採用", "合同企業説明会", "アンケート", "ギフトカード",
]

# 本文NGフレーズ (営業メール特有の表現)
BODY_NG_PHRASES = [
    "突然のメール失礼", "突然のご連絡失礼", "突然のご連絡を",
    "貴社のサイトを拝見", "貴社のホームページを拝見",
    "貴社サイトを拝見", "御社のサイトを拝見",
    "弊社のサービス", "弊社サービスの", "弊社では",
    "ご興味がございましたら", "ご興味がおありでしたら",
    "お力になれる", "お役に立てる",
    "まずはお気軽に", "無料でご相談",
    "実績多数", "導入実績", "成功事例",
    "配信停止", "配信解除", "メール配信を停止",
    "オプトアウト", "unsubscribe",
    "一斉配信", "一斉送信",
    "はじめまして", "初めまして",
    "ご担当者様",
    "成長戦略", "M&A", "事業承継",
    "資料を送付", "資料をお送り",
    "ご挨拶", "ご紹介させて",
    "Bccでお送り",
]

# 送信元ドメインNGリスト (営業メール常連)
DOMAIN_NG_LIST = [
    # SEO/Web制作系
    "seo-", "web-marketing", "listing-", "ad-agency",
    # メルマガ/ニュース配信
    "mail-magazine", "newsletter", "mailchimp.com", "sendgrid.net",
    "benchmark", "mailgun", "campaign-archive",
    # 人材系
    "recruit", "jinzai", "agent", "career",
    # 営業代行
    "sales-", "eigyo-",
    # 大量配信プラットフォーム
    "hubspot", "marketo", "pardot", "eloqua",
]

# 送信元ドメイン完全一致NGリスト
DOMAIN_NG_EXACT = [
    "sokudan.work", "ipros.jp", "forstartups.com",
    "mapbox.com",  # サービス通知
    "8card.net",  # Eight名刺
    "careecon.jp",  # CAREECON
    "fcip.jp",  # 建設業振興基金
    "nipc.or.jp",  # 名古屋産業振興公社
    "billing.larksuite.com",  # Lark請求通知
    "youtrust.co.jp",  # YOUTRUST
    "onepile.jp",  # JobPacker
    "innovation.co.jp",  # ITトレンド
    "iconico.co.jp",  # イコニコ
    "sbro.co.jp",  # SBIソーシングブラザーズ (M&A営業)
    "nagoya-cci.or.jp",  # 名古屋商工会議所 (メルマガ/案内)
]

# 送信元アドレスNGリスト (noreply等)
SENDER_NG_PATTERNS = [
    "noreply@", "no-reply@", "no_reply@",
    "mailer-daemon@", "postmaster@",
    "notification@", "notifications@",
    "newsletter@", "news@",
    "mailmag@", "magazine@", "mail-magazine@",
    "info@careecon", "info@ipros",
    "expo-mailmag@",
]

# ホワイトリストドメイン (CRMから動的取得 + 固定リスト)
DOMAIN_WHITELIST_FIXED = [
    "riseasone.jp",  # 政木
    # 既存主要取引先 (初期値、CRMから自動追加される)
    "st-koo.co.jp", "wagocons.co.jp",
]

# 自社ドメイン (自社発メールは除外)
SELF_DOMAINS = ["tokaiair.com", "tomoshi.jp"]

# 自動応答・システムメール除外
AUTO_REPLY_PATTERNS = [
    r"^(自動応答|自動返信|Auto.?Reply|Out of Office|Automatic reply)",
    r"^(Delivery Status|Undeliverable|Mail delivery failed)",
    r"\[Warning\]",
]

# 通知不要なシステムメールの件名パターン
SYSTEM_MAIL_PATTERNS = [
    r"^Re:",  # 返信は通知不要 (既知のやり取り)
    r"^Fwd:",  # 転送
    r"^転送:",
    r"振込受付完了",  # 銀行通知
    r"出金のお知らせ",
    r"入金のお知らせ",
    r"支払い完了通知",
    r"Web21",  # 三井住友Web21
    r"メールマガジン",
    r"メルマガ",
    r"ニュースレター",
    r"BMサプリ",
    r"ハーモニー.*\d{4}\.",  # 名商ハーモニー
    r"CCUSメンバーズ",
]

# DRY_RUN フラグ
DRY_RUN = False


# ── Lark API ──

def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["tenant_access_token"]


def lark_send_dm(token, text):
    """CEOにLark Bot DMを送信"""
    if DRY_RUN:
        print(f"  [DRY-RUN] DM送信スキップ")
        print(f"  内容: {text[:200]}...")
        return True

    data = json.dumps({
        "receive_id": CEO_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                print(f"  Lark DM送信成功")
                return True
            else:
                print(f"  Lark DMエラー: {result.get('msg', 'unknown')}")
                return False
    except Exception as e:
        print(f"  Lark DM送信失敗: {e}")
        return False


def get_crm_whitelist_domains(token):
    """CRM取引先テーブルからドメインを取得してホワイトリストに追加"""
    domains = set(DOMAIN_WHITELIST_FIXED)
    try:
        page_token = None
        while True:
            url = f"{BASE_URL}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_ACCOUNTS}/records?page_size=500"
            if page_token:
                url += f"&page_token={page_token}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=15) as r:
                result = json.loads(r.read())
                data = result.get("data", {})
                for item in data.get("items", []):
                    fields = item.get("fields", {})
                    # メールアドレスからドメイン抽出
                    for field_name in ["メールアドレス", "メール", "email", "Email", "ドメイン", "Webサイト", "URL"]:
                        val = fields.get(field_name)
                        if val and isinstance(val, str):
                            # メールアドレスからドメイン
                            if "@" in val:
                                domain = val.split("@")[-1].strip().lower()
                                if domain and "." in domain:
                                    domains.add(domain)
                            # URLからドメイン
                            elif "." in val:
                                domain = val.replace("https://", "").replace("http://", "").split("/")[0].strip().lower()
                                if domain:
                                    domains.add(domain)
                    # リンクフィールド (配列)
                    for field_name in ["メールアドレス", "メール", "Webサイト"]:
                        val = fields.get(field_name)
                        if val and isinstance(val, list):
                            for v in val:
                                if isinstance(v, dict):
                                    v = v.get("text", "") or v.get("link", "")
                                if isinstance(v, str) and "@" in v:
                                    domain = v.split("@")[-1].strip().lower()
                                    if domain and "." in domain:
                                        domains.add(domain)
                if not data.get("has_more"):
                    break
                page_token = data.get("page_token")
                time.sleep(0.3)
        print(f"  CRMホワイトリスト: {len(domains)}ドメイン取得")
    except Exception as e:
        print(f"  CRMホワイトリスト取得エラー (固定リストを使用): {e}")

    return domains


# ── 営業メール判定 ──

def classify_email(subject, body, from_addr, from_domain, whitelist_domains):
    """
    営業メール判定。スコアリングで営業確率を算出。

    Returns:
        (spam_score, spam_label, reasons)
        spam_score: 0-100 (高いほど営業メール)
        spam_label: "低" / "中" / "高"
        reasons: [str] 判定理由リスト
    """
    score = 0
    reasons = []
    subject_lower = (subject or "").lower()
    body_lower = (body or "").lower()
    from_lower = (from_addr or "").lower()
    domain_lower = (from_domain or "").lower()

    # ── 自社メール除外 ──
    if domain_lower in SELF_DOMAINS:
        return 100, "高", ["自社メール除外"]

    # ── unknown@unknown.com (SparkDB未解決送信者=ほぼメルマガ) ──
    if from_lower == "unknown@unknown.com" or domain_lower == "unknown.com":
        # 業務キーワードがある場合のみ通知 (問い合わせフォーム経由の可能性)
        has_business = False
        for kw in ["ドローン", "測量", "撮影", "空撮", "点群", "土量", "見積", "発注", "依頼", "お問い合わせ"]:
            if kw in subject_lower or kw in body_lower:
                has_business = True
                break
        if not has_business:
            return 80, "高", ["Unknown送信者(メルマガ)"]

    # ── 自動応答・システムメール ──
    for pat in AUTO_REPLY_PATTERNS:
        if re.search(pat, subject or "", re.IGNORECASE):
            return 100, "高", ["自動応答/システムメール"]

    # ── システムメール (銀行通知・メルマガ等) ──
    for pat in SYSTEM_MAIL_PATTERNS:
        if re.search(pat, subject or "", re.IGNORECASE):
            return 100, "高", [f"システムメール: {pat}"]

    # ── 送信元アドレスNGパターン ──
    for pat in SENDER_NG_PATTERNS:
        if pat.lower() in from_lower:
            score += 30
            reasons.append(f"送信元NG: {pat}")
            break

    # ── ホワイトリスト判定 (最優先で通知) ──
    if domain_lower in whitelist_domains:
        return 0, "低", ["ホワイトリスト(CRM取引先)"]

    # ── 件名NGワードチェック ──
    for word in SUBJECT_NG_WORDS:
        if word.lower() in subject_lower:
            score += 25
            reasons.append(f"件名NG: {word}")

    # ── 本文NGフレーズチェック ──
    body_hits = 0
    for phrase in BODY_NG_PHRASES:
        if phrase.lower() in body_lower:
            body_hits += 1
            if body_hits <= 3:  # 最初の3つだけ理由に記録
                reasons.append(f"本文NG: {phrase}")
    score += min(body_hits * 15, 45)  # 最大45点

    # ── ドメインNGチェック ──
    # 完全一致 or サブドメイン一致
    domain_ng_hit = False
    for ng_domain in DOMAIN_NG_EXACT:
        if domain_lower == ng_domain or domain_lower.endswith("." + ng_domain):
            score += 60
            reasons.append(f"ドメインNG(完全一致): {ng_domain}")
            domain_ng_hit = True
            break
    if not domain_ng_hit:
        for ng_pattern in DOMAIN_NG_LIST:
            if ng_pattern.lower() in domain_lower:
                score += 40
                reasons.append(f"ドメインNG(部分一致): {ng_pattern}")
                break

    # ── 追加ヒューリスティック ──
    # 配信停止リンク
    if "配信停止" in body_lower or "配信解除" in body_lower or "unsubscribe" in body_lower:
        score += 20
        reasons.append("配信停止リンクあり")

    # HTMLメルマガ特有パターン
    if body_lower.count("━") > 5 or body_lower.count("■") > 5 or body_lower.count("□") > 5:
        score += 15
        reasons.append("メルマガ装飾パターン")

    # noreply/no-reply
    if "noreply" in from_lower or "no-reply" in from_lower or "no_reply" in from_lower:
        score += 20
        reasons.append("noreplyアドレス")

    # 問い合わせフォーム経由の判定 (WordPress Contact Form)
    if "wordpress" in from_lower or "contact form" in subject_lower or "お問い合わせ" in subject_lower:
        score -= 30  # フォーム経由は実顧客の可能性大
        reasons.append("フォーム経由(減点)")

    # 「ドローン」「測量」「撮影」等の業務関連ワード
    business_keywords = ["ドローン", "測量", "撮影", "空撮", "点群", "土量", "3d", "オルソ",
                         "見積", "御見積", "お見積", "発注", "依頼", "相談"]
    for kw in business_keywords:
        if kw in subject_lower or kw in body_lower:
            score -= 20
            reasons.append(f"業務キーワード(減点): {kw}")
            break

    # スコア正規化
    score = max(0, min(100, score))

    # ラベル判定
    if score >= 60:
        label = "高"
    elif score >= 30:
        label = "中"
    else:
        label = "低"

    return score, label, reasons


def should_notify(spam_score, spam_label):
    """通知すべきかどうかを判定"""
    # 営業確率「高」は通知しない
    if spam_label == "高":
        return False
    return True


# ── メール情報抽出 ──

def extract_company_name(from_name, from_addr, body):
    """送信者名・メール・本文から会社名を推定"""
    # From名に会社名が含まれることが多い
    if from_name:
        # 「会社名 担当者名」パターン
        parts = from_name.split()
        if len(parts) >= 2:
            return parts[0]
        # 「株式会社XXX」パターン
        m = re.search(r'(株式会社\S+|\S+株式会社|\S+㈱|㈱\S+)', from_name)
        if m:
            return m.group(1)

    # ドメインから推定
    if from_addr and "@" in from_addr:
        domain = from_addr.split("@")[-1]
        # 一般的なフリーメールは除外
        if domain not in ["gmail.com", "yahoo.co.jp", "hotmail.com", "outlook.com", "icloud.com"]:
            return f"({domain})"

    return "不明"


def detect_source(subject, from_addr, body):
    """TAS問い合わせかTOMOSHI問い合わせかを判定"""
    subject_lower = (subject or "").lower()
    body_lower = (body or "").lower()
    from_lower = (from_addr or "").lower()

    # TOMOSHI判定
    if "tomoshi" in from_lower or "tomoshi" in subject_lower or "tomoshi" in body_lower:
        return "TOMOSHI", "🔶"
    if "ai" in subject_lower and ("診断" in subject_lower or "バリューアップ" in subject_lower):
        return "TOMOSHI", "🔶"
    if "info@tomoshi.jp" in from_lower:
        return "TOMOSHI", "🔶"

    # デフォルトはTAS
    return "TAS", "📩"


def format_notification(source, icon, subject, from_name, from_addr, company,
                        body_preview, spam_score, spam_label, reasons):
    """通知テキストを整形"""
    lines = [
        f"{icon} {source} 問い合わせ",
        f"━━━━━━━━━━━━━━━━━",
        f"送信者: {from_name or '不明'}",
        f"メール: {from_addr}",
        f"会社名: {company}",
        f"件名: {subject}",
        f"",
        f"本文プレビュー:",
        f"{body_preview}",
        f"",
        f"営業メール確率: {spam_label} ({spam_score}点)",
    ]
    if reasons and spam_label != "低":
        lines.append(f"判定理由: {', '.join(reasons[:3])}")

    return "\n".join(lines)


# ── State管理 ──

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "last_check_timestamp": 0,
        "notified_message_ids": [],
        "last_imap_uid": 0,
    }


def save_state(state):
    # notified_message_ids を最新500件に制限
    if len(state.get("notified_message_ids", [])) > 500:
        state["notified_message_ids"] = state["notified_message_ids"][-500:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── SparkDB モード ──

def check_sparkdb(state, whitelist_domains):
    """SparkDBから新着メールをチェック"""
    if not SPARK_DB.exists():
        print("エラー: Spark DBが見つかりません")
        return []

    # DBをtmpにコピー (WALロック回避)
    tmp_dir = tempfile.mkdtemp(prefix="inquiry_")
    for ext in ["", "-shm", "-wal"]:
        src = Path(str(SPARK_DB) + ext)
        if src.exists():
            shutil.copy2(str(src), os.path.join(tmp_dir, src.name))
    db_path = os.path.join(tmp_dir, SPARK_DB.name)

    new_messages = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        last_ts = state.get("last_check_timestamp", 0)
        notified_ids = set(state.get("notified_message_ids", []))

        # 直近の受信メールを取得 (送信済み除外)
        cur.execute("""
            SELECT pk, receivedDate, subject, messageFrom, messageFromMailbox,
                   messageFromDomain, shortBody, messageId, inSent
            FROM messages
            WHERE accountPk = ? AND inSent = 0 AND receivedDate > ?
            ORDER BY receivedDate DESC
            LIMIT 50
        """, (ACCOUNT_PK, last_ts))

        rows = cur.fetchall()
        conn.close()

        for row in rows:
            msg_id = row["messageId"] or str(row["pk"])
            if msg_id in notified_ids:
                continue

            subject = row["subject"] or ""
            from_addr = row["messageFromMailbox"] or ""
            from_domain = row["messageFromDomain"] or ""
            from_name = (row["messageFrom"] or "").replace('"', '').strip()
            # "Name <email>" から Name部分を抽出
            if "<" in from_name:
                from_name = from_name.split("<")[0].strip()
            body = row["shortBody"] or ""

            new_messages.append({
                "msg_id": msg_id,
                "timestamp": row["receivedDate"],
                "subject": subject,
                "from_name": from_name,
                "from_addr": from_addr,
                "from_domain": from_domain,
                "body": body,
            })

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return new_messages


# ── IMAPモード ──

def check_imap(state, whitelist_domains):
    """IMAP経由で新着メールをチェック"""
    if not IMAP_PASS:
        print("エラー: IMAP_PASS が設定されていません")
        return []

    new_messages = []
    notified_ids = set(state.get("notified_message_ids", []))

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select("INBOX", readonly=True)

        # UNSEEN or 直近のメールを検索
        # 過去1日分のメールをチェック (5分間隔なので十分)
        since_date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%d-%b-%Y")
        status, data = imap.search(None, f'(SINCE {since_date})')

        if status != "OK" or not data[0]:
            imap.logout()
            return []

        msg_nums = data[0].split()
        # 最新50件に制限
        msg_nums = msg_nums[-50:]

        for num in msg_nums:
            # UID取得
            status, uid_data = imap.fetch(num, "(UID)")
            uid_str = uid_data[0].decode() if uid_data[0] else ""
            uid_match = re.search(r'UID (\d+)', uid_str)
            uid = uid_match.group(1) if uid_match else num.decode()

            if f"imap_{uid}" in notified_ids:
                continue

            # ヘッダーと本文プレビューを取得
            status, msg_data = imap.fetch(num, "(RFC822.HEADER BODY.PEEK[TEXT]<0.500>)")
            if status != "OK":
                continue

            # ヘッダー解析
            header_data = None
            body_data = b""
            for part in msg_data:
                if isinstance(part, tuple):
                    desc = part[0].decode() if isinstance(part[0], bytes) else str(part[0])
                    if "HEADER" in desc:
                        header_data = part[1]
                    elif "TEXT" in desc or "BODY" in desc:
                        body_data = part[1]

            if not header_data:
                continue

            msg = email.message_from_bytes(header_data, policy=email.policy.default)
            subject = str(msg.get("Subject", ""))
            from_header = str(msg.get("From", ""))

            # From解析
            from_name = from_header
            from_addr = from_header
            m = re.match(r'"?([^"<]*)"?\s*<([^>]+)>', from_header)
            if m:
                from_name = m.group(1).strip()
                from_addr = m.group(2).strip()
            elif "<" in from_header:
                from_addr = from_header.split("<")[-1].rstrip(">").strip()

            from_domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""

            # 本文プレビュー
            body_preview = ""
            if body_data:
                try:
                    body_preview = body_data.decode("utf-8", errors="replace")
                except Exception:
                    body_preview = body_data.decode("iso-2022-jp", errors="replace")
                # HTMLタグ除去
                body_preview = re.sub(r'<[^>]+>', ' ', body_preview)
                body_preview = re.sub(r'\s+', ' ', body_preview).strip()

            new_messages.append({
                "msg_id": f"imap_{uid}",
                "timestamp": time.time(),
                "subject": subject,
                "from_name": from_name,
                "from_addr": from_addr,
                "from_domain": from_domain,
                "body": body_preview[:500],
            })

        imap.logout()

    except Exception as e:
        print(f"IMAPエラー: {e}")

    return new_messages


# ── メイン処理 ──

def main():
    global DRY_RUN

    parser = argparse.ArgumentParser(description="問い合わせメール即時通知")
    parser.add_argument("--imap", action="store_true", help="IMAP経由でチェック (GitHub Actions用)")
    parser.add_argument("--dry-run", action="store_true", help="通知送信なし")
    parser.add_argument("--init", action="store_true", help="初期化 (既存メールをスキップ)")
    args = parser.parse_args()

    DRY_RUN = args.dry_run
    use_imap = args.imap or os.environ.get("INQUIRY_MODE") == "imap"

    print(f"=== 問い合わせ通知チェック ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print(f"  モード: {'IMAP' if use_imap else 'SparkDB'}")
    if DRY_RUN:
        print(f"  [DRY-RUN モード]")

    # State読み込み
    state = load_state()

    # 初期化モード
    if args.init:
        print("初期化モード: 現在のメールをスキップマークします")
        if use_imap:
            # IMAP: 現在の最新UIDを記録
            state["last_imap_uid"] = int(time.time())
        else:
            # SparkDB: 現在のタイムスタンプを記録
            state["last_check_timestamp"] = time.time()
        save_state(state)
        print("初期化完了")
        return

    # Lark トークン取得
    try:
        token = lark_get_token()
    except Exception as e:
        print(f"Larkトークン取得失敗: {e}")
        sys.exit(1)

    # CRMホワイトリスト取得
    whitelist_domains = get_crm_whitelist_domains(token)

    # 新着メールチェック
    if use_imap:
        new_messages = check_imap(state, whitelist_domains)
    else:
        new_messages = check_sparkdb(state, whitelist_domains)

    if not new_messages:
        print("  新着メールなし")
        # タイムスタンプ更新 (SparkDB用)
        if not use_imap:
            state["last_check_timestamp"] = time.time()
            save_state(state)
        return

    print(f"  新着メール: {len(new_messages)}件")

    # 各メールを処理
    notified_count = 0
    skipped_count = 0

    for msg in new_messages:
        subject = msg["subject"]
        from_name = msg["from_name"]
        from_addr = msg["from_addr"]
        from_domain = msg["from_domain"]
        body = msg["body"]

        # 営業メール判定
        spam_score, spam_label, reasons = classify_email(
            subject, body, from_addr, from_domain, whitelist_domains
        )

        print(f"\n  [{spam_label}] {subject[:50]}")
        print(f"    From: {from_addr} (スコア: {spam_score})")
        if reasons:
            print(f"    理由: {', '.join(reasons[:3])}")

        # 通知判定
        if not should_notify(spam_score, spam_label):
            print(f"    -> スキップ (営業メール)")
            skipped_count += 1
            state.setdefault("notified_message_ids", []).append(msg["msg_id"])
            continue

        # 送信元・会社推定
        company = extract_company_name(from_name, from_addr, body)
        source, icon = detect_source(subject, from_addr, body)

        # 本文プレビュー (最初の200文字)
        body_preview = (body or "")[:200]
        if len(body or "") > 200:
            body_preview += "..."

        # 通知テキスト作成
        notification = format_notification(
            source, icon, subject, from_name, from_addr, company,
            body_preview, spam_score, spam_label, reasons
        )

        print(f"    -> 通知送信 ({source})")

        # Lark DM送信
        lark_send_dm(token, notification)
        notified_count += 1

        # State更新
        state.setdefault("notified_message_ids", []).append(msg["msg_id"])
        time.sleep(0.5)  # レートリミット対策

    # タイムスタンプ更新
    if new_messages and not use_imap:
        max_ts = max(m["timestamp"] for m in new_messages)
        state["last_check_timestamp"] = max_ts

    save_state(state)

    print(f"\n=== 完了: 通知{notified_count}件, スキップ{skipped_count}件 ===")


if __name__ == "__main__":
    main()
