#!/usr/bin/env python3
"""
bid_scanner.py - 官公庁入札案件スキャナー（ドローン測量関連）

対象サイト:
  1. 国交省 中部地方整備局 e-bisc.go.jp（業務・工事）— 過去6営業日分
  2. 中部地方整備局 cbr.mlit.go.jp 公告一覧（静的HTML）
  3. 愛知県 あいち電子調達共同システム（TODO: 動的JSPポータル）
  4. 名古屋市 電子調達システム（TODO: 動的フォーム）

Usage:
  python bid_scanner.py          # スキャン＆Lark通知
  python bid_scanner.py --test   # ドライラン（通知なし）
  python bid_scanner.py --days 3 # 過去3日分（デフォルト7日）
  python bid_scanner.py --all    # 既読含め全件表示
"""

import urllib.request
import urllib.parse
import json
import ssl
import sys
import re
import os
import logging
from datetime import datetime, timedelta
from html.parser import HTMLParser

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
KEYWORDS = [
    "測量", "ドローン", "UAV", "3次元", "三次元", "点群",
    "レーザー", "写真測量", "i-Construction", "i-construction",
    "不陸", "地形測量", "航空", "空中写真", "LiDAR", "lidar",
    "MMS", "地上レーザ", "ICT", "無人航空機",
    # 2026-03-16 追加: 赤外線調査・構造物点検・i-Con関連
    "赤外線", "外壁調査", "建物調査",
    "橋梁点検", "護岸点検", "無人化", "空撮",
]

# 業種カテゴリに以下が含まれる場合はキーワード不問で自動マッチ
CATEGORY_AUTO_MATCH = ["測量"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load credentials from automation_config.json (not hardcoded)
_config_path = os.path.join(SCRIPT_DIR, "automation_config.json")
if os.path.exists(_config_path):
    with open(_config_path) as _f:
        _cfg = json.load(_f)
    LARK_APP_ID = _cfg["lark"]["app_id"]
    LARK_APP_SECRET = _cfg["lark"]["app_secret"]
else:
    LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
    LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")

OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"
LOG_FILE = os.path.join(SCRIPT_DIR, "bid_scanner.log")
STATE_FILE = os.path.join(SCRIPT_DIR, "bid_scanner_state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# SSL context — some gov sites have certificate issues
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def fetch_url(url, encoding="utf-8", timeout=30, method="GET", post_data=None):
    """Fetch URL content as string. Returns None on error."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
        }
        if post_data is not None:
            if isinstance(post_data, dict):
                post_data = urllib.parse.urlencode(post_data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            req = urllib.request.Request(url, data=post_data, headers=headers)
        else:
            req = urllib.request.Request(url, headers=headers)

        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
            raw = resp.read()
            for enc in [encoding, "shift_jis", "euc-jp", "cp932", "utf-8"]:
                try:
                    return raw.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        log.error(f"Fetch failed [{url}]: {e}")
        return None


# ---------------------------------------------------------------------------
# HTML Parser for e-bisc.go.jp bid listing tables
# ---------------------------------------------------------------------------
class EBiscTableParser(HTMLParser):
    """
    Parse the ITIRAN table from e-bisc.go.jp.

    Columns (業務 cbr_g):
      0: No. | 1: 担当部・事務所 | 2: 業務名(link) | 3: 入札契約方式 | 4: 業務区分 | 5: 文書更新日時

    Columns (工事 cbr_k):
      0: No. | 1: 担当部・事務所 | 2: 工事名(link) | 3: 入札契約方式 | 4: 工事種別 | 5: 文書更新日時
    """

    def __init__(self):
        super().__init__()
        self.bids = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._in_th = False
        self._current_row = []
        self._current_cell = ""
        self._current_link = None

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")

        if tag == "table" and "ITIRAN" in cls:
            self._in_table = True
            return

        if not self._in_table:
            return

        if tag == "tr":
            self._in_row = True
            self._current_row = []

        elif tag == "th":
            self._in_th = True

        elif tag == "td":
            self._in_cell = True
            self._current_cell = ""
            self._current_link = None

        elif tag == "a" and self._in_cell:
            href = attrs_dict.get("href", "")
            if href and ("KokaiBunsho" in href or "e-bisc" in href):
                # Unescape &amp; → &
                self._current_link = href.replace("&amp;", "&")

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell += data.strip()

    def handle_entityref(self, name):
        if self._in_cell:
            self._current_cell += " "

    def handle_endtag(self, tag):
        if tag == "table" and self._in_table:
            self._in_table = False
            return

        if not self._in_table:
            return

        if tag == "th":
            self._in_th = False

        elif tag == "td" and self._in_cell:
            self._in_cell = False
            self._current_row.append({
                "text": self._current_cell.strip(),
                "link": self._current_link,
            })

        elif tag == "tr" and self._in_row:
            self._in_row = False
            row = self._current_row
            # Skip header rows (th) and short rows
            if len(row) < 4:
                return

            # Extract link from any cell
            link = None
            for cell in row:
                if cell.get("link"):
                    link = cell["link"]
                    break

            bid = {
                "no": row[0]["text"] if len(row) > 0 else "",
                "agency": row[1]["text"] if len(row) > 1 else "",
                "title": row[2]["text"] if len(row) > 2 else "",
                "url": link,
                "bid_method": row[3]["text"] if len(row) > 3 else "",
                "category": row[4]["text"] if len(row) > 4 else "",
                "updated": row[5]["text"] if len(row) > 5 else "",
            }
            if bid["title"]:  # Skip empty rows
                self.bids.append(bid)


# ---------------------------------------------------------------------------
# Business day calculation
# ---------------------------------------------------------------------------
def get_past_business_days(days=7):
    """Get list of past business days as YYYYMMDD strings."""
    dates = []
    d = datetime.now()
    while len(dates) < days:
        d -= timedelta(days=1)
        # Skip weekends (5=Sat, 6=Sun)
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
    return dates


# ---------------------------------------------------------------------------
# Source 1: 中部地方整備局 e-bisc.go.jp (primary source)
# ---------------------------------------------------------------------------
EBISC_SOURCES = [
    # (base_url, search_url, label)
    (
        "https://e2ppiw01.e-bisc.go.jp/new/anken/cbr_g",
        "https://e2ppiw01.e-bisc.go.jp/new/anken/cbr_g/search",
        "中部地整・業務",
    ),
    (
        "https://e2ppiw01.e-bisc.go.jp/new/anken/cbr_k",
        "https://e2ppiw01.e-bisc.go.jp/new/anken/cbr_k/search",
        "中部地整・工事",
    ),
]


def scan_ebisc(days=7):
    """
    Scan e-bisc.go.jp for Chubu Regional Bureau bid announcements.
    Fetches today's page + past N business days via POST.
    """
    results = []
    past_dates = get_past_business_days(days)

    for base_url, search_url, label in EBISC_SOURCES:
        log.info(f"Scanning: {label}")

        # 1. Fetch today's page (GET)
        html = fetch_url(base_url, encoding="shift_jis")
        pages = []
        if html:
            pages.append(("today", html))

        # 2. Fetch past dates (POST)
        for date_str in past_dates:
            html = fetch_url(
                search_url,
                encoding="shift_jis",
                post_data={"targetDate": date_str},
            )
            if html:
                pages.append((date_str, html))

        # Parse all pages
        total = 0
        for date_label, page_html in pages:
            parser = EBiscTableParser()
            try:
                parser.feed(page_html)
            except Exception as e:
                log.error(f"  Parse error ({label}/{date_label}): {e}")
                continue

            total += len(parser.bids)

            for bid in parser.bids:
                title = bid.get("title", "")
                category = bid.get("category", "")
                bid_method = bid.get("bid_method", "")
                search_text = f"{title} {category} {bid_method}"

                if matches_keywords(search_text, category=category):
                    results.append({
                        "案件名": title,
                        "発注者": bid.get("agency", "") or label,
                        "公告日": bid.get("updated", ""),
                        "締切日": "",
                        "業種": category,
                        "入札方式": bid_method,
                        "概要URL": bid.get("url", base_url),
                        "ソース": label,
                    })

        log.info(f"  {label}: {total} total bids, {len([r for r in results if r['ソース'] == label])} matched keywords")

    return results


# ---------------------------------------------------------------------------
# Source 2: 中部地方整備局 cbr.mlit.go.jp 公告一覧（静的HTML）
# ---------------------------------------------------------------------------
def scan_cbr_static():
    """Scan static bid announcement pages on cbr.mlit.go.jp."""
    results = []
    urls = [
        ("https://www.cbr.mlit.go.jp/contract/kouji/koukoku.htm", "中部地整・工事公告"),
    ]

    for url, source_label in urls:
        log.info(f"Scanning: {source_label}")
        html = fetch_url(url, encoding="shift_jis")
        if not html:
            log.warning(f"  Could not fetch {source_label}")
            continue

        link_pattern = re.compile(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )

        for match in link_pattern.finditer(html):
            href = match.group(1)
            text = re.sub(r"<[^>]+>", "", match.group(2)).strip()

            if not text or len(text) < 5:
                continue

            if matches_keywords(text):
                if href.startswith("/"):
                    href = "https://www.cbr.mlit.go.jp" + href
                elif not href.startswith("http"):
                    href = url.rsplit("/", 1)[0] + "/" + href

                results.append({
                    "案件名": text,
                    "発注者": source_label,
                    "公告日": "",
                    "締切日": "",
                    "業種": "",
                    "入札方式": "",
                    "概要URL": href,
                    "ソース": source_label,
                })

        log.info(f"  {source_label}: {len([r for r in results if r['ソース'] == source_label])} matched")

    return results


# ---------------------------------------------------------------------------
# Source 3: 愛知県 あいち電子調達共同システム
# ---------------------------------------------------------------------------
def scan_aichi():
    """
    愛知県 電子調達共同システム (CALS/EC)
    Portal: https://www.chotatsu.e-aichi.jp/portal/index.jsp

    TODO: This site uses Java servlets with session-based navigation.
    Implementation requires:
      1. GET the portal page to establish a session cookie
      2. Navigate to 入札情報サービス
      3. Submit search form with keyword/category filters
      4. Parse result table
    Alternatively, use Selenium/Playwright for full browser automation.
    """
    log.info("愛知県: Skipped (JSP session-based portal)")
    log.info("  Manual: https://www.chotatsu.e-aichi.jp/portal/index.jsp")
    return []


# ---------------------------------------------------------------------------
# Source 4: 名古屋市 電子調達システム
# ---------------------------------------------------------------------------
def scan_nagoya():
    """
    名古屋市 電子調達システム
    PPI: https://www.chotatsu.city.nagoya.jp/ejpkg/EjPPIj

    TODO: Nagoya's system uses auto-form-submit on page load.
    Implementation requires:
      1. GET the PPI page → auto-redirect via JS form.submit()
      2. Navigate to 入札情報 → 案件検索
      3. Submit search with category=測量 or keyword filters
      4. Parse result pages
    Alternatively, use Selenium/Playwright for full browser automation.
    """
    log.info("名古屋市: Skipped (dynamic JS form system)")
    log.info("  Manual: https://www.chotatsu.city.nagoya.jp/ejpkg/EjPPIj")
    return []


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------
def matches_keywords(text, category=""):
    """Check if text contains any of the target keywords (case-insensitive).
    Also auto-matches if category contains any CATEGORY_AUTO_MATCH terms.
    """
    # Auto-match by category (e.g. 業種 = "測量" → always match)
    if category:
        cat_lower = category.lower()
        for cat_kw in CATEGORY_AUTO_MATCH:
            if cat_kw.lower() in cat_lower:
                return True

    text_lower = text.lower()
    for kw in KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Lark Bot notification
# ---------------------------------------------------------------------------
def get_lark_tenant_token():
    """Get Lark tenant access token."""
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({
        "app_id": LARK_APP_ID,
        "app_secret": LARK_APP_SECRET,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json; charset=utf-8",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                return data.get("tenant_access_token")
            log.error(f"Lark token error: {data}")
            return None
    except Exception as e:
        log.error(f"Lark token request failed: {e}")
        return None


def send_lark_message(token, text):
    """Send a Lark Bot DM to the owner."""
    url = "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id"
    payload = json.dumps({
        "receive_id": OWNER_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                log.info("Lark message sent successfully")
                return True
            log.error(f"Lark send error: {data}")
            return False
    except Exception as e:
        log.error(f"Lark send failed: {e}")
        return False


def format_lark_message(bids):
    """Format bid results for Lark DM notification."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "入札案件スキャン結果",
        f"実行: {now}",
        f"該当案件: {len(bids)}件",
        "--------------------",
        "",
    ]

    for i, bid in enumerate(bids, 1):
        lines.append(f"[{i}] {bid['案件名']}")
        if bid.get("発注者"):
            lines.append(f"  発注者: {bid['発注者']}")
        if bid.get("公告日"):
            lines.append(f"  公告日: {bid['公告日']}")
        if bid.get("締切日"):
            lines.append(f"  締切: {bid['締切日']}")
        if bid.get("業種"):
            lines.append(f"  業種: {bid['業種']}")
        if bid.get("入札方式"):
            lines.append(f"  方式: {bid['入札方式']}")
        if bid.get("概要URL"):
            lines.append(f"  URL: {bid['概要URL']}")
        lines.append("")

    lines.append("--------------------")
    lines.append("KW: " + ", ".join(KEYWORDS[:8]))
    lines.append("")
    lines.append("[未対応 - 手動確認]")
    lines.append("愛知県: https://www.chotatsu.e-aichi.jp/portal/index.jsp")
    lines.append("名古屋市: https://www.chotatsu.city.nagoya.jp/ejpkg/EjPPIj")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Deduplication & state management
# ---------------------------------------------------------------------------
def deduplicate(bids):
    """Remove duplicate bids by title."""
    seen = set()
    unique = []
    for bid in bids:
        key = bid["案件名"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(bid)
    return unique


def load_seen_bids():
    """Load previously seen bid keys (auto-prune >30 days)."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            cutoff = (datetime.now() - timedelta(days=30)).isoformat()
            return {k: v for k, v in data.items() if v > cutoff}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_seen_bids(seen):
    """Persist seen bid keys."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def filter_new_bids(bids, seen):
    """Return only bids not previously seen. Marks them as seen."""
    new_bids = []
    now = datetime.now().isoformat()
    for bid in bids:
        key = bid["案件名"][:50]
        if key not in seen:
            new_bids.append(bid)
            seen[key] = now
    return new_bids


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(description="官公庁入札スキャナー（ドローン測量）")
    ap.add_argument("--test", action="store_true", help="ドライラン（通知なし）")
    ap.add_argument("--days", type=int, default=7, help="過去N営業日分をスキャン（デフォルト7）")
    ap.add_argument("--all", action="store_true", help="既読案件も含めて全件表示")
    args = ap.parse_args()

    log.info("=" * 60)
    log.info("入札スキャナー開始" + (" [TEST MODE]" if args.test else ""))
    log.info(f"対象: 過去{args.days}営業日")
    log.info("=" * 60)

    all_bids = []

    # --- Source 1: e-bisc.go.jp (primary, most reliable) ---
    try:
        bids = scan_ebisc(days=args.days)
        all_bids.extend(bids)
    except Exception as e:
        log.error(f"e-bisc scan error: {e}")

    # --- Source 2: cbr.mlit.go.jp static pages ---
    try:
        bids = scan_cbr_static()
        all_bids.extend(bids)
    except Exception as e:
        log.error(f"cbr static scan error: {e}")

    # --- Source 3: Aichi (TODO) ---
    try:
        scan_aichi()
    except Exception as e:
        log.error(f"Aichi scan error: {e}")

    # --- Source 4: Nagoya (TODO) ---
    try:
        scan_nagoya()
    except Exception as e:
        log.error(f"Nagoya scan error: {e}")

    # Deduplicate
    all_bids = deduplicate(all_bids)
    log.info(f"Total unique keyword-matched bids: {len(all_bids)}")

    # Filter new only (unless --all)
    if not args.all:
        seen = load_seen_bids()
        new_bids = filter_new_bids(all_bids, seen)
        if not args.test:
            save_seen_bids(seen)
        log.info(f"New (unseen) bids: {len(new_bids)}")
    else:
        new_bids = all_bids

    # Print results to console
    if new_bids:
        print(f"\n{'=' * 60}")
        print(f"  該当案件: {len(new_bids)}件")
        print(f"{'=' * 60}")
        for i, bid in enumerate(new_bids, 1):
            print(f"\n  [{i}] {bid['案件名']}")
            print(f"      発注者: {bid.get('発注者', '-')}")
            if bid.get("公告日"):
                print(f"      公告日: {bid['公告日']}")
            if bid.get("業種"):
                print(f"      業種: {bid['業種']}")
            if bid.get("入札方式"):
                print(f"      方式: {bid['入札方式']}")
            if bid.get("概要URL"):
                print(f"      URL: {bid['概要URL']}")
        print()
    else:
        print("\n  該当する新規案件はありません。\n")

    # Lark notification
    if new_bids and not args.test:
        log.info("Sending Lark notification...")
        token = get_lark_tenant_token()
        if token:
            msg = format_lark_message(new_bids)
            # Lark has 4096 char limit per message — split if needed
            if len(msg) > 3800:
                chunks = []
                current = ""
                for line in msg.split("\n"):
                    if len(current) + len(line) + 1 > 3800:
                        chunks.append(current)
                        current = line
                    else:
                        current += "\n" + line if current else line
                if current:
                    chunks.append(current)
                for chunk in chunks:
                    send_lark_message(token, chunk)
            else:
                send_lark_message(token, msg)
        else:
            log.error("Could not get Lark token")
    elif args.test and new_bids:
        log.info("[TEST] Notification skipped")
        print("--- Lark message preview ---")
        print(format_lark_message(new_bids))
        print("--- end preview ---")

    log.info("スキャン完了")
    return len(new_bids)


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
