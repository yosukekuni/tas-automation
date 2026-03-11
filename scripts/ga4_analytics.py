#!/usr/bin/env python3
"""
GA4 & Search Console Analytics Script
東海エアサービス株式会社 (https://www.tokaiair.com)

Fetches GA4 analytics and Search Console data, generates analysis CSVs
for Lark import, and prints a summary dashboard.
"""

import csv
import json
import os
import sys
import time
import base64
import hashlib
import struct
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────
GA4_PROPERTY_ID = "499408061"
SITE_URL = "https://www.tokaiair.com/"
SITE_URL_SC_DOMAIN = "sc-domain:tokaiair.com"
SERVICE_ACCOUNT_EMAIL = "service-account@drive-organizer-489313.iam.gserviceaccount.com"
DATA_DIR = Path(r"/mnt/c/Users/USER/Documents/_data")
OUTPUT_DIR = DATA_DIR / "lark_import"
SCOPES = "https://www.googleapis.com/auth/analytics.readonly https://www.googleapis.com/auth/webmasters.readonly"

TODAY = datetime.now()
DATE_90_AGO = (TODAY - timedelta(days=90)).strftime("%Y-%m-%d")
DATE_TODAY = TODAY.strftime("%Y-%m-%d")

# ── Find Service Account Key ─────────────────────────────────────────────
def find_service_account_key():
    """Search for service account JSON key file."""
    search_dirs = [
        DATA_DIR,
        DATA_DIR.parent,
        Path.home(),
        Path.home() / ".config" / "gcloud",
        Path(r"/mnt/c/Users/USER"),
        Path(r"/mnt/c/Users/USER/Documents"),
        Path(r"/mnt/c/Users/USER/Downloads"),
        Path(r"/mnt/c/Users/USER/Desktop"),
    ]

    # Priority 1: files matching drive-organizer or 489313
    for d in search_dirs:
        if not d.exists():
            continue
        try:
            for f in d.iterdir():
                if f.suffix == ".json" and ("drive-organizer" in f.name or "489313" in f.name):
                    print(f"  Found key file (name match): {f}")
                    return f
        except PermissionError:
            continue

    # Priority 2: any JSON with private_key
    for d in search_dirs:
        if not d.exists():
            continue
        try:
            for f in d.iterdir():
                if f.suffix == ".json":
                    try:
                        data = json.loads(f.read_text(encoding="utf-8"))
                        if "private_key" in data and "client_email" in data:
                            print(f"  Found key file (content match): {f}")
                            return f
                    except Exception:
                        continue
        except PermissionError:
            continue

    return None


# ── Authentication ────────────────────────────────────────────────────────
def get_access_token(key_path):
    """Get OAuth2 access token using service account key."""
    # Try google-auth library first
    try:
        from google.oauth2 import service_account as sa_mod
        from google.auth.transport.requests import Request as AuthRequest
        credentials = sa_mod.Credentials.from_service_account_file(
            str(key_path),
            scopes=SCOPES.split()
        )
        credentials.refresh(AuthRequest())
        print("  Authenticated via google-auth library")
        return credentials.token
    except ImportError:
        pass
    except Exception as e:
        print(f"  google-auth failed: {e}, trying manual JWT...")

    # Manual JWT signing
    key_data = json.loads(Path(key_path).read_text(encoding="utf-8"))
    private_key_pem = key_data["private_key"]
    client_email = key_data.get("client_email", SERVICE_ACCOUNT_EMAIL)

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": client_email,
        "scope": SCOPES,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now,
        "exp": now + 3600,
    }

    def b64url(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    # Try cryptography library
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None
        )
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt_token = f"{header_b64}.{payload_b64}.{b64url(signature)}"
        print("  Signed JWT via cryptography library")
    except ImportError:
        # Fallback: use openssl subprocess
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
            kf.write(private_key_pem)
            kf_path = kf.name
        try:
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", kf_path],
                input=signing_input, capture_output=True
            )
            if proc.returncode != 0:
                raise RuntimeError(f"openssl failed: {proc.stderr.decode()}")
            signature = proc.stdout
            jwt_token = f"{header_b64}.{payload_b64}.{b64url(signature)}"
            print("  Signed JWT via openssl")
        finally:
            os.unlink(kf_path)

    # Exchange JWT for access token
    token_data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant_type:jwt-bearer",
        "assertion": jwt_token,
    }).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())

    print("  Access token obtained")
    return result["access_token"]


# ── API Helpers ───────────────────────────────────────────────────────────
def api_post(url, body, token):
    """POST JSON to API with bearer token."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"  API Error {e.code} for {url}: {error_body[:300]}")
        return None


def api_get(url, token):
    """GET from API with bearer token."""
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"  API Error {e.code} for {url}: {error_body[:300]}")
        return None


# ── GA4 Data API Calls ───────────────────────────────────────────────────
GA4_API = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY_ID}:runReport"


def ga4_page_views(token):
    """2a: Page views by page path (last 90 days)."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [
            {"name": "screenPageViews"},
            {"name": "totalUsers"},
            {"name": "averageSessionDuration"},
            {"name": "bounceRate"},
        ],
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": 500,
    }
    return api_post(GA4_API, body, token)


def ga4_traffic_sources(token):
    """2b: Traffic sources with sessions and conversions."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [
            {"name": "sessionSource"},
            {"name": "sessionMedium"},
        ],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "conversions"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 100,
    }
    return api_post(GA4_API, body, token)


def ga4_landing_pages(token):
    """2c: Top landing pages with bounce rate and avg session duration."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "landingPagePlusQueryString"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "bounceRate"},
            {"name": "averageSessionDuration"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 100,
    }
    return api_post(GA4_API, body, token)


def ga4_device_category(token):
    """2d: Device category breakdown."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "deviceCategory"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
        ],
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    return api_post(GA4_API, body, token)


def ga4_geo_breakdown(token):
    """2e: Geographic breakdown (city level, Japan)."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "city"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
        ],
        "dimensionFilter": {
            "filter": {
                "fieldName": "country",
                "stringFilter": {"value": "Japan"},
            }
        },
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
        "limit": 50,
    }
    return api_post(GA4_API, body, token)


def ga4_weekly_trend(token):
    """2f: Weekly trend of sessions/users/pageviews."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "isoYearIsoWeek"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
            {"name": "newUsers"},
        ],
        "orderBys": [{"dimension": {"dimensionName": "isoYearIsoWeek"}, "desc": False}],
    }
    return api_post(GA4_API, body, token)


def ga4_new_vs_returning(token):
    """2g: New vs returning users."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "newVsReturning"}],
        "metrics": [
            {"name": "sessions"},
            {"name": "totalUsers"},
        ],
    }
    return api_post(GA4_API, body, token)


def ga4_conversion_events(token):
    """2h: Conversion events."""
    body = {
        "dateRanges": [{"startDate": DATE_90_AGO, "endDate": DATE_TODAY}],
        "dimensions": [{"name": "eventName"}],
        "metrics": [
            {"name": "eventCount"},
            {"name": "totalUsers"},
        ],
        "dimensionFilter": {
            "orGroup": {
                "expressions": [
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "submit"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "form"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "click"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "contact"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "tel"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "phone"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "conversion"}}},
                    {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "CONTAINS", "value": "generate_lead"}}},
                ]
            }
        },
        "orderBys": [{"metric": {"metricName": "eventCount"}, "desc": True}],
        "limit": 50,
    }
    return api_post(GA4_API, body, token)


# ── Search Console API Calls ─────────────────────────────────────────────
def gsc_api_url(site):
    """Build Search Console API URL."""
    encoded = urllib.parse.quote(site, safe="")
    return f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/searchAnalytics/query"


def gsc_query(token, site_url, body):
    """Try both URL-prefix and sc-domain site URLs."""
    result = api_post(gsc_api_url(site_url), body, token)
    if result is not None:
        return result
    # Try sc-domain format
    print(f"  Retrying with {SITE_URL_SC_DOMAIN}...")
    return api_post(gsc_api_url(SITE_URL_SC_DOMAIN), body, token)


def gsc_top_queries(token):
    """3a: Top queries."""
    body = {
        "startDate": DATE_90_AGO,
        "endDate": DATE_TODAY,
        "dimensions": ["query"],
        "rowLimit": 500,
    }
    return gsc_query(token, SITE_URL, body)


def gsc_top_pages(token):
    """3b: Top pages by clicks."""
    body = {
        "startDate": DATE_90_AGO,
        "endDate": DATE_TODAY,
        "dimensions": ["page"],
        "rowLimit": 500,
    }
    return gsc_query(token, SITE_URL, body)


def gsc_query_page_combos(token):
    """3c: Query-page combinations for column/glossary."""
    body = {
        "startDate": DATE_90_AGO,
        "endDate": DATE_TODAY,
        "dimensions": ["query", "page"],
        "dimensionFilterGroups": [{
            "filters": [{
                "dimension": "page",
                "operator": "contains",
                "expression": "/column/"
            }]
        }],
        "rowLimit": 500,
    }
    col_result = gsc_query(token, SITE_URL, body)

    body["dimensionFilterGroups"][0]["filters"][0]["expression"] = "/glossary/"
    glos_result = gsc_query(token, SITE_URL, body)

    rows = []
    if col_result and "rows" in col_result:
        rows.extend(col_result["rows"])
    if glos_result and "rows" in glos_result:
        rows.extend(glos_result["rows"])
    return {"rows": rows} if rows else None


def gsc_device_breakdown(token):
    """3d: Device breakdown."""
    body = {
        "startDate": DATE_90_AGO,
        "endDate": DATE_TODAY,
        "dimensions": ["device"],
        "rowLimit": 10,
    }
    return gsc_query(token, SITE_URL, body)


# ── CSV Writers ───────────────────────────────────────────────────────────
def write_csv(filename, headers, rows):
    """Write CSV with UTF-8-sig BOM for Lark compatibility."""
    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    print(f"  Wrote {filepath.name} ({len(rows)} rows)")
    return filepath


def parse_ga4_rows(result):
    """Parse GA4 runReport response into list of dicts."""
    if not result or "rows" not in result:
        return []
    dim_headers = [h["name"] for h in result.get("dimensionHeaders", [])]
    met_headers = [h["name"] for h in result.get("metricHeaders", [])]
    rows = []
    for row in result["rows"]:
        d = {}
        for i, dv in enumerate(row.get("dimensionValues", [])):
            d[dim_headers[i]] = dv["value"]
        for i, mv in enumerate(row.get("metricValues", [])):
            d[met_headers[i]] = mv["value"]
        rows.append(d)
    return rows


def parse_gsc_rows(result):
    """Parse Search Console response rows."""
    if not result or "rows" not in result:
        return []
    return result["rows"]


# ── Main Logic ────────────────────────────────────────────────────────────
def classify_page(path):
    """Classify page as column, glossary, or other."""
    if "/column/" in path or "/column" == path:
        return "column"
    elif "/glossary/" in path or "/glossary" == path:
        return "glossary"
    return "other"


def guess_title(path):
    """Guess page title from path."""
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        return "トップページ"
    last = parts[-1]
    # Remove file extensions
    last = last.replace(".html", "").replace(".php", "").replace(".htm", "")
    # Replace hyphens/underscores with spaces
    last = last.replace("-", " ").replace("_", " ")
    return last if last else "/".join(parts)


def fmt_pct(val):
    """Format as percentage string."""
    try:
        return f"{float(val)*100:.1f}%" if float(val) <= 1 else f"{float(val):.1f}%"
    except (ValueError, TypeError):
        return val


def fmt_num(val):
    """Format number string."""
    try:
        v = float(val)
        return f"{v:.0f}" if v == int(v) else f"{v:.2f}"
    except (ValueError, TypeError):
        return val


def fmt_duration(seconds_str):
    """Format duration in seconds to mm:ss."""
    try:
        s = float(seconds_str)
        m = int(s) // 60
        sec = int(s) % 60
        return f"{m}:{sec:02d}"
    except (ValueError, TypeError):
        return seconds_str


def generate_seo_suggestions(ga4_pages, gsc_queries, gsc_pages):
    """Generate SEO improvement suggestions."""
    suggestions = []

    # High impressions, low CTR → title/description improvement
    for row in gsc_pages:
        keys = row.get("keys", [])
        page = keys[0] if keys else ""
        clicks = row.get("clicks", 0)
        impressions = row.get("impressions", 0)
        ctr = row.get("ctr", 0)
        position = row.get("position", 0)

        if impressions > 50 and ctr < 0.02:
            suggestions.append({
                "page": page,
                "position": f"{position:.1f}",
                "impressions": impressions,
                "clicks": clicks,
                "ctr": f"{ctr*100:.1f}%",
                "suggestion": "CTRが低い（<2%）: タイトル・ディスクリプション改善推奨",
            })
        elif impressions > 20 and ctr < 0.05 and position <= 10:
            suggestions.append({
                "page": page,
                "position": f"{position:.1f}",
                "impressions": impressions,
                "clicks": clicks,
                "ctr": f"{ctr*100:.1f}%",
                "suggestion": "上位表示だがCTRが低い: メタ情報の最適化を推奨",
            })

    # Position 5-20 → opportunity to push higher
    for row in gsc_pages:
        keys = row.get("keys", [])
        page = keys[0] if keys else ""
        position = row.get("position", 0)
        impressions = row.get("impressions", 0)
        clicks = row.get("clicks", 0)
        ctr = row.get("ctr", 0)

        if 5 <= position <= 20 and impressions > 30:
            suggestions.append({
                "page": page,
                "position": f"{position:.1f}",
                "impressions": impressions,
                "clicks": clicks,
                "ctr": f"{ctr*100:.1f}%",
                "suggestion": f"順位{position:.0f}位: コンテンツ強化でTOP3入り可能",
            })

    # Column pages with low GA4 views → content refresh
    for pg in ga4_pages:
        path = pg.get("pagePath", "")
        pvs = int(float(pg.get("screenPageViews", "0")))
        if "/column/" in path and pvs < 10:
            suggestions.append({
                "page": path,
                "position": "-",
                "impressions": "-",
                "clicks": "-",
                "ctr": "-",
                "suggestion": f"コラムページ PV={pvs}: コンテンツリフレッシュ推奨",
            })

    # Top queries without matching column/glossary content
    query_set = set()
    for row in gsc_queries:
        keys = row.get("keys", [])
        query = keys[0] if keys else ""
        impressions = row.get("impressions", 0)
        clicks = row.get("clicks", 0)
        if impressions > 50 and clicks < 3:
            drone_keywords = ["ドローン", "drone", "測量", "点検", "空撮", "3d", "i-con", "ortho"]
            if any(kw in query.lower() for kw in drone_keywords):
                if query not in query_set:
                    query_set.add(query)
                    suggestions.append({
                        "page": f"[新規] query: {query}",
                        "position": "-",
                        "impressions": impressions,
                        "clicks": clicks,
                        "ctr": "-",
                        "suggestion": "検索需要あり: 新規コンテンツ作成機会",
                    })

    # Deduplicate by page
    seen = set()
    unique = []
    for s in suggestions:
        key = s["page"] + s["suggestion"][:20]
        if key not in seen:
            seen.add(key)
            unique.append(s)

    return unique[:100]


def print_dashboard(ga4_data, gsc_data):
    """Print summary dashboard to stdout."""
    print("\n" + "=" * 72)
    print("  GA4 & GSC アナリティクス ダッシュボード")
    print(f"  東海エアサービス株式会社 | {DATE_90_AGO} ~ {DATE_TODAY}")
    print("=" * 72)

    # Weekly trend summary
    weekly = ga4_data.get("weekly", [])
    if weekly:
        total_sessions = sum(int(float(w.get("sessions", 0))) for w in weekly)
        total_users = sum(int(float(w.get("totalUsers", 0))) for w in weekly)
        total_pvs = sum(int(float(w.get("screenPageViews", 0))) for w in weekly)
        total_new = sum(int(float(w.get("newUsers", 0))) for w in weekly)
        print(f"\n  [90日間サマリー]")
        print(f"    セッション: {total_sessions:,}")
        print(f"    ユーザー数: {total_users:,}")
        print(f"    ページビュー: {total_pvs:,}")
        print(f"    新規ユーザー: {total_new:,}")
        if total_users > 0:
            print(f"    新規率: {total_new/total_users*100:.1f}%")

    # Device breakdown
    devices = ga4_data.get("devices", [])
    if devices:
        total_dev = sum(int(float(d.get("sessions", 0))) for d in devices)
        print(f"\n  [デバイス別]")
        for d in devices:
            name = d.get("deviceCategory", "?")
            sess = int(float(d.get("sessions", 0)))
            pct = sess / total_dev * 100 if total_dev else 0
            print(f"    {name}: {sess:,} ({pct:.1f}%)")

    # Top 10 pages
    pages = ga4_data.get("pages", [])
    if pages:
        print(f"\n  [トップ10ページ (PV)]")
        for p in pages[:10]:
            path = p.get("pagePath", "?")
            pvs = fmt_num(p.get("screenPageViews", "0"))
            print(f"    {pvs:>6}  {path}")

    # Top traffic sources
    sources = ga4_data.get("sources", [])
    if sources:
        print(f"\n  [トップ5流入経路]")
        for s in sources[:5]:
            src = s.get("sessionSource", "?")
            med = s.get("sessionMedium", "?")
            sess = fmt_num(s.get("sessions", "0"))
            print(f"    {sess:>6}  {src} / {med}")

    # Top geo
    geo = ga4_data.get("geo", [])
    if geo:
        print(f"\n  [トップ5地域]")
        for g in geo[:5]:
            city = g.get("city", "?")
            sess = fmt_num(g.get("sessions", "0"))
            print(f"    {sess:>6}  {city}")

    # GSC top queries
    queries = gsc_data.get("queries", [])
    if queries:
        print(f"\n  [トップ10検索クエリ]")
        print(f"    {'クエリ':<30} {'クリック':>6} {'表示':>8} {'CTR':>7} {'順位':>6}")
        for q in queries[:10]:
            keys = q.get("keys", [])
            query = keys[0] if keys else "?"
            clicks = q.get("clicks", 0)
            imps = q.get("impressions", 0)
            ctr = q.get("ctr", 0)
            pos = q.get("position", 0)
            print(f"    {query:<30} {clicks:>6} {imps:>8} {ctr*100:>6.1f}% {pos:>5.1f}")

    # Column/Glossary focus
    col_pages = [p for p in pages if "/column/" in p.get("pagePath", "")]
    glos_pages = [p for p in pages if "/glossary/" in p.get("pagePath", "")]
    col_pvs = sum(int(float(p.get("screenPageViews", 0))) for p in col_pages)
    glos_pvs = sum(int(float(p.get("screenPageViews", 0))) for p in glos_pages)
    all_pvs = sum(int(float(p.get("screenPageViews", 0))) for p in pages)
    print(f"\n  [コンテンツセクション別PV]")
    print(f"    コラム (/column/): {col_pvs:,} PV ({len(col_pages)} pages)")
    print(f"    用語集 (/glossary/): {glos_pvs:,} PV ({len(glos_pages)} pages)")
    if all_pvs > 0:
        other_pvs = all_pvs - col_pvs - glos_pvs
        print(f"    その他: {other_pvs:,} PV")

    print("\n" + "=" * 72)
    print("  CSV出力先: " + str(OUTPUT_DIR))
    print("=" * 72 + "\n")


def main():
    print("\n[1/6] サービスアカウントキーを検索中...")
    key_path = find_service_account_key()
    if not key_path:
        print("  ERROR: サービスアカウントキーが見つかりません。")
        print("  以下のいずれかに配置してください:")
        print(f"    {DATA_DIR}/<name>.json")
        print("  ファイルには private_key と client_email が必要です。")
        sys.exit(1)

    print("\n[2/6] 認証中...")
    try:
        token = get_access_token(key_path)
    except Exception as e:
        print(f"  ERROR: 認証失敗 - {e}")
        sys.exit(1)

    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── GA4 API Calls ─────────────────────────────────────────────────
    print("\n[3/6] GA4 Data API からデータ取得中...")
    ga4_data = {}

    print("  ページ別PV...")
    result = ga4_page_views(token)
    ga4_data["pages"] = parse_ga4_rows(result)

    print("  流入経路...")
    result = ga4_traffic_sources(token)
    ga4_data["sources"] = parse_ga4_rows(result)

    print("  ランディングページ...")
    result = ga4_landing_pages(token)
    ga4_data["landing"] = parse_ga4_rows(result)

    print("  デバイス別...")
    result = ga4_device_category(token)
    ga4_data["devices"] = parse_ga4_rows(result)

    print("  地域別...")
    result = ga4_geo_breakdown(token)
    ga4_data["geo"] = parse_ga4_rows(result)

    print("  週次トレンド...")
    result = ga4_weekly_trend(token)
    ga4_data["weekly"] = parse_ga4_rows(result)

    print("  新規vs再訪...")
    result = ga4_new_vs_returning(token)
    ga4_data["new_returning"] = parse_ga4_rows(result)

    print("  コンバージョンイベント...")
    result = ga4_conversion_events(token)
    ga4_data["conversions"] = parse_ga4_rows(result)

    # ── Search Console API Calls ──────────────────────────────────────
    print("\n[4/6] Search Console API からデータ取得中...")
    gsc_data = {}

    print("  検索クエリ...")
    result = gsc_top_queries(token)
    gsc_data["queries"] = parse_gsc_rows(result)

    print("  ページ別...")
    result = gsc_top_pages(token)
    gsc_data["pages"] = parse_gsc_rows(result)

    print("  コラム/用語集 クエリ-ページ...")
    result = gsc_query_page_combos(token)
    gsc_data["combos"] = parse_gsc_rows(result)

    print("  デバイス別...")
    result = gsc_device_breakdown(token)
    gsc_data["devices"] = parse_gsc_rows(result)

    # ── Generate CSVs ─────────────────────────────────────────────────
    print("\n[5/6] CSV生成中...")

    # 11a: ページ別PV
    rows = []
    for p in ga4_data["pages"]:
        rows.append([
            p.get("pagePath", ""),
            fmt_num(p.get("screenPageViews", "0")),
            fmt_num(p.get("totalUsers", "0")),
            fmt_duration(p.get("averageSessionDuration", "0")),
            fmt_pct(p.get("bounceRate", "0")),
        ])
    write_csv("11a_GA4_ページ別PV.csv",
              ["ページパス", "PV", "ユーザー", "平均滞在時間", "直帰率"], rows)

    # 11b: 流入経路
    rows = []
    for s in ga4_data["sources"]:
        rows.append([
            s.get("sessionSource", ""),
            s.get("sessionMedium", ""),
            fmt_num(s.get("sessions", "0")),
            fmt_num(s.get("totalUsers", "0")),
            fmt_num(s.get("conversions", "0")),
        ])
    write_csv("11b_GA4_流入経路.csv",
              ["ソース", "メディア", "セッション", "ユーザー", "コンバージョン"], rows)

    # 11c: 週次トレンド
    rows = []
    for w in ga4_data["weekly"]:
        week_str = w.get("isoYearIsoWeek", "")
        rows.append([
            week_str,
            fmt_num(w.get("sessions", "0")),
            fmt_num(w.get("totalUsers", "0")),
            fmt_num(w.get("screenPageViews", "0")),
            fmt_num(w.get("newUsers", "0")),
        ])
    write_csv("11c_GA4_週次トレンド.csv",
              ["週", "セッション", "ユーザー", "PV", "新規ユーザー"], rows)

    # 11d: デバイス別
    total_dev = sum(int(float(d.get("sessions", 0))) for d in ga4_data["devices"])
    rows = []
    for d in ga4_data["devices"]:
        sess = int(float(d.get("sessions", 0)))
        pct = f"{sess/total_dev*100:.1f}%" if total_dev else "0%"
        rows.append([
            d.get("deviceCategory", ""),
            fmt_num(d.get("sessions", "0")),
            pct,
        ])
    write_csv("11d_GA4_デバイス別.csv",
              ["デバイス", "セッション", "割合"], rows)

    # 11e: 地域別
    rows = []
    for g in ga4_data["geo"]:
        rows.append([
            g.get("city", ""),
            fmt_num(g.get("sessions", "0")),
            fmt_num(g.get("totalUsers", "0")),
        ])
    write_csv("11e_GA4_地域別.csv",
              ["都市", "セッション", "ユーザー"], rows)

    # 11f: GSC検索クエリ
    rows = []
    for q in gsc_data["queries"]:
        keys = q.get("keys", [])
        rows.append([
            keys[0] if keys else "",
            q.get("clicks", 0),
            q.get("impressions", 0),
            f"{q.get('ctr', 0)*100:.1f}%",
            f"{q.get('position', 0):.1f}",
        ])
    write_csv("11f_GSC_検索クエリ.csv",
              ["クエリ", "クリック", "表示回数", "CTR", "平均順位"], rows)

    # 11g: GSCページ別
    rows = []
    for p in gsc_data["pages"]:
        keys = p.get("keys", [])
        rows.append([
            keys[0] if keys else "",
            p.get("clicks", 0),
            p.get("impressions", 0),
            f"{p.get('ctr', 0)*100:.1f}%",
            f"{p.get('position', 0):.1f}",
        ])
    write_csv("11g_GSC_ページ別.csv",
              ["ページ", "クリック", "表示回数", "CTR", "平均順位"], rows)

    # 11h: コンテンツ分析 (merge GA4 page data with GSC data)
    # Build lookup from GSC pages
    gsc_page_lookup = {}
    for p in gsc_data["pages"]:
        keys = p.get("keys", [])
        if keys:
            page_url = keys[0]
            # Extract path from full URL
            parsed = urllib.parse.urlparse(page_url)
            path = parsed.path or page_url
            gsc_page_lookup[path] = p

    # Build lookup for top query per page from combos
    top_query_lookup = {}
    for c in gsc_data.get("combos", []):
        keys = c.get("keys", [])
        if len(keys) >= 2:
            query, page_url = keys[0], keys[1]
            parsed = urllib.parse.urlparse(page_url)
            path = parsed.path or page_url
            if path not in top_query_lookup:
                top_query_lookup[path] = query

    # Also build from full GSC query data for pages without combo data
    # (we'd need query+page dimension data; use what we have)

    rows = []
    for p in ga4_data["pages"]:
        path = p.get("pagePath", "")
        pvs = fmt_num(p.get("screenPageViews", "0"))
        page_type = classify_page(path)
        gsc_info = gsc_page_lookup.get(path, {})
        search_clicks = gsc_info.get("clicks", 0)
        top_query = top_query_lookup.get(path, "")
        rows.append([
            path,
            guess_title(path),
            page_type,
            pvs,
            search_clicks,
            top_query,
        ])
    write_csv("11h_コンテンツ分析.csv",
              ["パス", "推定タイトル", "タイプ", "PV", "検索クリック", "トップクエリ"], rows)

    # 11i: SEO改善提案
    print("  SEO改善提案を生成中...")
    suggestions = generate_seo_suggestions(
        ga4_data["pages"], gsc_data["queries"], gsc_data["pages"]
    )
    rows = []
    for s in suggestions:
        rows.append([
            s["page"],
            s["position"],
            s["impressions"],
            s["clicks"],
            s["ctr"],
            s["suggestion"],
        ])
    write_csv("11i_SEO改善提案.csv",
              ["ページ", "現在順位", "表示回数", "クリック", "CTR", "提案"], rows)

    # ── Dashboard ─────────────────────────────────────────────────────
    print("\n[6/6] ダッシュボード表示...")
    print_dashboard(ga4_data, gsc_data)

    print("完了!")


if __name__ == "__main__":
    main()
