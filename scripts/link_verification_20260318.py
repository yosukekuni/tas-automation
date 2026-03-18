#!/usr/bin/env python3
"""
tokaiair.com 全ページ内部リンク検証 + 新規デプロイページ検証
2026-03-18

Phase 1: WP REST APIで全公開コンテンツ取得
Phase 2: 全内部リンク抽出 → HTTP GETで200確認
Phase 3: 新規デプロイページの詳細検証（title/meta/JSON-LD）
Phase 4: 結果をMarkdownレポートに保存
"""

import json
import re
import sys
import time
import requests
from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser
from datetime import datetime

# Config
with open("/mnt/c/Users/USER/Documents/_data/automation_config.json") as f:
    config = json.load(f)

WP = config["wordpress"]
BASE_URL = WP["base_url"]
AUTH = (WP["user"], WP["app_password"])
HEADERS = {"User-Agent": "TAS-LinkVerifier/1.0"}
SITE_DOMAIN = "tokaiair.com"

# Pages to verify in detail
DEPLOY_PAGES = [
    "/drone-survey-cost-comparison/",
    "/drone-survey-statistics/",
    "/drone-survey-market-report/",
    "/nagoya/",
    "/toyota/",
    "/gifu-city/",
    "/tsu/",
    "/shizuoka-city/",
    "/case-library/cases/",
]


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href" and value:
                    self.links.append(value)


class MetaExtractor(HTMLParser):
    """Extract title, meta description, JSON-LD from full HTML"""
    def __init__(self):
        super().__init__()
        self.title = ""
        self.meta_description = ""
        self.json_ld_blocks = []
        self._in_title = False
        self._in_script_jsonld = False
        self._script_content = ""

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and attrs_dict.get("name", "").lower() == "description":
            self.meta_description = attrs_dict.get("content", "")
        elif tag == "script" and attrs_dict.get("type") == "application/ld+json":
            self._in_script_jsonld = True
            self._script_content = ""

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_script_jsonld:
            self._script_content += data

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_script_jsonld:
            self._in_script_jsonld = False
            if self._script_content.strip():
                self.json_ld_blocks.append(self._script_content.strip())


def get_all_content(endpoint):
    """Paginate through WP REST API endpoint"""
    items = []
    page = 1
    while True:
        try:
            resp = requests.get(
                f"{BASE_URL}/{endpoint}",
                params={"per_page": 100, "page": page, "status": "publish"},
                auth=AUTH,
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            if not data:
                break
            items.extend(data)
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1
        except Exception as e:
            print(f"  ERROR fetching {endpoint} page {page}: {e}")
            break
    return items


def extract_links(html_content):
    parser = LinkExtractor()
    parser.feed(html_content or "")
    return parser.links


def is_internal(href):
    if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
        return False
    parsed = urlparse(href)
    if not parsed.scheme and not parsed.netloc:
        return True
    if SITE_DOMAIN in (parsed.netloc or ""):
        return True
    return False


def normalize_url(href):
    """Normalize to full URL"""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return f"https://{SITE_DOMAIN}{href}"
    parsed = urlparse(href)
    if not parsed.scheme:
        return f"https://{SITE_DOMAIN}/{href}"
    return href


def check_url(url, timeout=15):
    """HTTP GET and return (status_code, redirect_url_or_None)"""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        final_url = resp.url if resp.url != url else None
        return resp.status_code, final_url, len(resp.content)
    except requests.exceptions.Timeout:
        return "TIMEOUT", None, 0
    except requests.exceptions.ConnectionError as e:
        return "CONN_ERROR", None, 0
    except Exception as e:
        return f"ERROR:{str(e)[:50]}", None, 0


def check_page_detail(url):
    """Fetch full HTML and extract title, meta desc, JSON-LD"""
    try:
        resp = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        if resp.status_code != 200:
            return {
                "status": resp.status_code,
                "title": None,
                "meta_description": None,
                "json_ld_valid": False,
                "json_ld_count": 0,
                "content_length": len(resp.content),
            }

        html = resp.text
        parser = MetaExtractor()
        parser.feed(html)

        # Validate JSON-LD
        json_ld_valid = True
        json_ld_parsed = []
        for block in parser.json_ld_blocks:
            try:
                parsed = json.loads(block)
                json_ld_parsed.append(parsed)
            except json.JSONDecodeError:
                json_ld_valid = False

        # Extract internal links from this page
        link_parser = LinkExtractor()
        link_parser.feed(html)
        internal_links = [normalize_url(h) for h in link_parser.links if is_internal(h)]

        return {
            "status": resp.status_code,
            "title": parser.title.strip() if parser.title else None,
            "meta_description": parser.meta_description or None,
            "json_ld_valid": json_ld_valid,
            "json_ld_count": len(parser.json_ld_blocks),
            "json_ld_types": [p.get("@type", "unknown") if isinstance(p, dict) else "array" for p in json_ld_parsed],
            "content_length": len(resp.content),
            "internal_links": internal_links,
        }
    except Exception as e:
        return {
            "status": f"ERROR:{str(e)[:80]}",
            "title": None,
            "meta_description": None,
            "json_ld_valid": False,
            "json_ld_count": 0,
            "content_length": 0,
        }


# ============================================================
# MAIN EXECUTION
# ============================================================

print("=" * 60)
print("tokaiair.com 全ページリンク検証 + デプロイ検証")
print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# Phase 1: Get all content from WP REST API
print("\n[Phase 1] WordPress REST APIから全コンテンツ取得...")
posts = get_all_content("posts")
pages = get_all_content("pages")
print(f"  投稿: {len(posts)}件, 固定ページ: {len(pages)}件")

all_content = []
all_known_urls = set()

for p in posts + pages:
    url = p["link"]
    all_content.append({
        "id": p["id"],
        "type": "post" if p in posts else "page",
        "title": p["title"]["rendered"],
        "url": url,
        "slug": p["slug"],
        "content_html": p["content"]["rendered"],
    })
    all_known_urls.add(url.rstrip("/"))

print(f"  既知URL数: {len(all_known_urls)}")

# Phase 2: Extract all internal links and check with HTTP GET
print("\n[Phase 2] 全内部リンク抽出 & HTTP検証...")

# Collect all unique internal links with their source pages
link_sources = {}  # url -> [source_page_titles]
for c in all_content:
    links = extract_links(c["content_html"])
    for href in links:
        if is_internal(href):
            full_url = normalize_url(href)
            if full_url not in link_sources:
                link_sources[full_url] = []
            link_sources[full_url].append(c["title"])

unique_internal_urls = sorted(link_sources.keys())
print(f"  ユニーク内部リンク数: {len(unique_internal_urls)}")

# HTTP check each unique internal link
broken_links = []
redirect_links = []
ok_count = 0
checked = 0

for url in unique_internal_urls:
    checked += 1
    if checked % 20 == 0:
        print(f"  ... {checked}/{len(unique_internal_urls)} チェック済み (OK: {ok_count}, BROKEN: {len(broken_links)})")

    status, redirect_url, content_len = check_url(url)

    if isinstance(status, int) and status == 200:
        ok_count += 1
    elif isinstance(status, int) and 300 <= status < 400:
        redirect_links.append({
            "url": url,
            "status": status,
            "redirect_to": redirect_url,
            "sources": link_sources[url][:3],
        })
    elif isinstance(status, int) and status == 404:
        broken_links.append({
            "url": url,
            "status": status,
            "sources": link_sources[url][:3],
        })
        print(f"  [404] {url}")
        print(f"        リンク元: {link_sources[url][0]}")
    elif isinstance(status, int) and status >= 400:
        broken_links.append({
            "url": url,
            "status": status,
            "sources": link_sources[url][:3],
        })
        print(f"  [{status}] {url}")
    else:
        broken_links.append({
            "url": url,
            "status": str(status),
            "sources": link_sources[url][:3],
        })
        print(f"  [{status}] {url}")

    time.sleep(0.15)  # Rate limiting

print(f"\n  結果: OK={ok_count}, BROKEN={len(broken_links)}, REDIRECT={len(redirect_links)}")

# Phase 3: Detailed check of deploy pages
print("\n[Phase 3] 新規デプロイページ詳細検証...")
deploy_results = {}

for path in DEPLOY_PAGES:
    url = f"https://{SITE_DOMAIN}{path}"
    print(f"\n  検証中: {url}")
    detail = check_page_detail(url)
    deploy_results[path] = detail

    status_icon = "OK" if detail["status"] == 200 else "NG"
    title_icon = "OK" if detail["title"] else "NG"
    meta_icon = "OK" if detail["meta_description"] else "NG"
    jsonld_icon = "OK" if detail["json_ld_valid"] and detail["json_ld_count"] > 0 else "NG"

    print(f"    HTTP: [{status_icon}] {detail['status']}")
    print(f"    Title: [{title_icon}] {(detail['title'] or 'MISSING')[:60]}")
    print(f"    Meta Desc: [{meta_icon}] {(detail['meta_description'] or 'MISSING')[:60]}")
    print(f"    JSON-LD: [{jsonld_icon}] {detail['json_ld_count']}件 valid={detail['json_ld_valid']}")

    # Check internal links within deploy pages
    if detail.get("internal_links"):
        page_broken = []
        for ilink in set(detail["internal_links"]):
            s, _, _ = check_url(ilink)
            if isinstance(s, int) and s != 200:
                page_broken.append({"url": ilink, "status": s})
            elif not isinstance(s, int):
                page_broken.append({"url": ilink, "status": str(s)})
            time.sleep(0.1)
        deploy_results[path]["broken_internal"] = page_broken
        if page_broken:
            print(f"    内部リンク切れ: {len(page_broken)}件")
            for bl in page_broken:
                print(f"      [{bl['status']}] {bl['url']}")
        else:
            print(f"    内部リンク: 全{len(set(detail['internal_links']))}件 OK")

    time.sleep(0.2)

# Phase 4: Generate Markdown report
print("\n\n[Phase 4] レポート生成...")

report = f"""# tokaiair.com リンク検証レポート
**実行日時**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## サマリー
| 項目 | 件数 |
|------|------|
| 投稿数 | {len(posts)} |
| 固定ページ数 | {len(pages)} |
| ユニーク内部リンク数 | {len(unique_internal_urls)} |
| 正常 (200) | {ok_count} |
| リンク切れ | {len(broken_links)} |
| リダイレクト | {len(redirect_links)} |

## 1. リンク切れ一覧
"""

if broken_links:
    report += "\n| URL | ステータス | リンク元ページ |\n|-----|-----------|----------------|\n"
    for bl in broken_links:
        sources = ", ".join(bl["sources"][:2])
        report += f"| `{bl['url']}` | {bl['status']} | {sources} |\n"
else:
    report += "\nリンク切れはありません。\n"

report += "\n## 2. リダイレクト一覧\n"
if redirect_links:
    report += "\n| 元URL | ステータス | リダイレクト先 |\n|-------|-----------|----------------|\n"
    for rl in redirect_links:
        report += f"| `{rl['url']}` | {rl['status']} | `{rl.get('redirect_to', 'N/A')}` |\n"
else:
    report += "\nリダイレクトはありません。\n"

report += "\n## 3. 新規デプロイページ詳細検証\n"

for path, detail in deploy_results.items():
    status_mark = "PASS" if detail["status"] == 200 else "FAIL"
    title_mark = "PASS" if detail["title"] else "FAIL"
    meta_mark = "PASS" if detail["meta_description"] else "FAIL"
    jsonld_mark = "PASS" if detail["json_ld_valid"] and detail["json_ld_count"] > 0 else "FAIL"
    broken_count = len(detail.get("broken_internal", []))
    link_mark = "PASS" if broken_count == 0 else "FAIL"

    overall = "PASS" if all([
        detail["status"] == 200,
        detail["title"],
        detail["meta_description"],
        detail["json_ld_valid"] and detail["json_ld_count"] > 0,
        broken_count == 0,
    ]) else "FAIL"

    report += f"""
### `{path}` [{overall}]
| チェック項目 | 結果 | 詳細 |
|-------------|------|------|
| HTTP Status | {status_mark} | {detail['status']} |
| Title | {title_mark} | {(detail['title'] or 'MISSING')[:80]} |
| Meta Description | {meta_mark} | {(detail['meta_description'] or 'MISSING')[:80]} |
| JSON-LD | {jsonld_mark} | {detail['json_ld_count']}件, valid={detail['json_ld_valid']}, types={detail.get('json_ld_types', [])} |
| 内部リンク | {link_mark} | 切れ: {broken_count}件 |
"""
    if broken_count > 0:
        for bl in detail["broken_internal"]:
            report += f"- BROKEN: `{bl['url']}` ({bl['status']})\n"

report += f"""
## 4. 判定

### 全体結果
- 内部リンク切れ: **{len(broken_links)}件**
- デプロイページ不合格: **{sum(1 for d in deploy_results.values() if d['status'] != 200 or not d['title'] or not d['meta_description'])}件**

### 対応要否
"""

if broken_links or any(d["status"] != 200 for d in deploy_results.values()):
    report += "**要対応** - 上記の問題を修正してください。\n"
else:
    report += "**対応不要** - 全リンク正常、全デプロイページ正常です。\n"

# Save report
report_path = "/mnt/c/Users/USER/Documents/_data/tas-automation/content/link_check_20260318.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)
print(f"\nレポート保存: {report_path}")

# Save JSON for programmatic use
json_path = "/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/link_verification_20260318.json"
json_data = {
    "timestamp": datetime.now().isoformat(),
    "summary": {
        "posts": len(posts),
        "pages": len(pages),
        "unique_internal_links": len(unique_internal_urls),
        "ok": ok_count,
        "broken": len(broken_links),
        "redirects": len(redirect_links),
    },
    "broken_links": broken_links,
    "redirect_links": redirect_links,
    "deploy_page_results": {k: {kk: vv for kk, vv in v.items() if kk != "internal_links"} for k, v in deploy_results.items()},
}
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(json_data, f, ensure_ascii=False, indent=2)
print(f"JSON保存: {json_path}")

print("\n" + "=" * 60)
print("検証完了")
print("=" * 60)
