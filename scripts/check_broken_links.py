#!/usr/bin/env python3
"""
tokaiair.com 全ページのリンク切れ検出スクリプト
1. WordPress REST APIで全投稿・全固定ページを取得
2. HTMLからaタグのhref属性を全抽出
3. 内部リンク・外部リンクをチェック
4. 結果をJSONに出力
"""

import json
import re
import requests
from urllib.parse import urlparse, urljoin
from html.parser import HTMLParser
import time

# Config
with open("/mnt/c/Users/USER/Documents/_data/automation_config.json") as f:
    config = json.load(f)

WP = config["wordpress"]
BASE_URL = WP["base_url"]
AUTH = (WP["user"], WP["app_password"])
HEADERS = {"User-Agent": "TAS-Automation/1.0"}

SITE_DOMAIN = "tokaiair.com"


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for attr, value in attrs:
                if attr == "href" and value:
                    self.links.append(value)


def get_all_content(endpoint):
    """Paginate through WP REST API endpoint"""
    items = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            params={"per_page": 100, "page": page, "status": "publish"},
            auth=AUTH,
            headers=HEADERS,
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
    return items


def extract_links(html_content):
    parser = LinkExtractor()
    parser.feed(html_content or "")
    return parser.links


def classify_link(href):
    """Classify as internal, external, or skip"""
    if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
        return "skip", href
    parsed = urlparse(href)
    if not parsed.scheme and not parsed.netloc:
        return "internal", href
    if SITE_DOMAIN in (parsed.netloc or ""):
        return "internal", href
    return "external", href


def check_internal_link(href, all_slugs, all_urls):
    """Check if internal link exists"""
    parsed = urlparse(href)
    path = parsed.path.rstrip("/").lstrip("/")

    if not path:
        return True  # homepage

    # Check against known URLs
    for url in all_urls:
        url_path = urlparse(url).path.rstrip("/").lstrip("/")
        if url_path == path:
            return True

    return False


def check_external_link(href, timeout=10):
    """Check if external link is alive"""
    try:
        resp = requests.head(href, timeout=timeout, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code < 400:
            return True, resp.status_code
        # Try GET as fallback (some sites block HEAD)
        resp = requests.get(href, timeout=timeout, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        return resp.status_code < 400, resp.status_code
    except Exception as e:
        return False, str(e)


print("=== tokaiair.com リンク切れ検出 ===\n")

# 1. Get all content
print("1. 全投稿・全固定ページを取得中...")
posts = get_all_content("posts")
pages = get_all_content("pages")
print(f"   投稿: {len(posts)}件, 固定ページ: {len(pages)}件")

all_content = []
for p in posts:
    all_content.append({
        "id": p["id"],
        "type": "post",
        "title": p["title"]["rendered"],
        "url": p["link"],
        "slug": p["slug"],
        "content": p["content"]["rendered"],
    })
for p in pages:
    all_content.append({
        "id": p["id"],
        "type": "page",
        "title": p["title"]["rendered"],
        "url": p["link"],
        "slug": p["slug"],
        "content": p["content"]["rendered"],
    })

# Build set of all known URLs
all_urls = set()
all_slugs = set()
for c in all_content:
    all_urls.add(c["url"])
    all_slugs.add(c["slug"])

print(f"   既知URL数: {len(all_urls)}")

# 2. Extract and classify links
print("\n2. リンク抽出中...")
all_links = []  # (content_item, href, link_type)
for c in all_content:
    links = extract_links(c["content"])
    for href in links:
        link_type, clean_href = classify_link(href)
        if link_type != "skip":
            all_links.append((c, clean_href, link_type))

internal_links = [(c, h) for c, h, t in all_links if t == "internal"]
external_links = [(c, h) for c, h, t in all_links if t == "external"]

# Deduplicate external links for checking
unique_external = set(h for _, h in external_links)
unique_internal = set(h for _, h in internal_links)

print(f"   内部リンク: {len(internal_links)}件 (ユニーク: {len(unique_internal)})")
print(f"   外部リンク: {len(external_links)}件 (ユニーク: {len(unique_external)})")

# 3. Check internal links
print("\n3. 内部リンクチェック中...")
broken_internal = {}
for href in sorted(unique_internal):
    if not check_internal_link(href, all_slugs, all_urls):
        broken_internal[href] = True
        print(f"   [BROKEN] {href}")

# 4. Check external links
print("\n4. 外部リンクチェック中...")
broken_external = {}
checked = 0
for href in sorted(unique_external):
    checked += 1
    if checked % 10 == 0:
        print(f"   ... {checked}/{len(unique_external)} チェック済み")
    alive, status = check_external_link(href)
    if not alive:
        broken_external[href] = status
        print(f"   [BROKEN] {href} → {status}")
    time.sleep(0.3)  # rate limiting

# 5. Build report
print("\n\n=== レポート ===\n")
broken_report = []
for c, href, link_type in all_links:
    if link_type == "internal" and href in broken_internal:
        broken_report.append({
            "page_id": c["id"],
            "page_type": c["type"],
            "page_title": c["title"],
            "page_url": c["url"],
            "broken_link": href,
            "link_type": "internal",
            "status": "not_found",
        })
    elif link_type == "external" and href in broken_external:
        broken_report.append({
            "page_id": c["id"],
            "page_type": c["type"],
            "page_title": c["title"],
            "page_url": c["url"],
            "broken_link": href,
            "link_type": "external",
            "status": str(broken_external[href]),
        })

# Also check for Zoho links
zoho_links = []
for c, href, link_type in all_links:
    if "zoho" in href.lower():
        zoho_links.append({
            "page_id": c["id"],
            "page_type": c["type"],
            "page_title": c["title"],
            "page_url": c["url"],
            "zoho_link": href,
        })

print(f"リンク切れ合計: {len(broken_report)}件")
print(f"Zohoリンク: {len(zoho_links)}件\n")

for b in broken_report:
    print(f"  [{b['link_type']}] {b['broken_link']}")
    print(f"    ページ: {b['page_title']} (ID:{b['page_id']})")
    print()

if zoho_links:
    print("Zohoリンク（Lark Schedulerに置換対象）:")
    for z in zoho_links:
        print(f"  {z['zoho_link']}")
        print(f"    ページ: {z['page_title']} (ID:{z['page_id']})")
        print()

# Save results
results = {
    "broken_links": broken_report,
    "zoho_links": zoho_links,
    "all_known_urls": sorted(list(all_urls)),
    "all_known_slugs": sorted(list(all_slugs)),
}

with open("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/broken_links_report.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n結果を broken_links_report.json に保存しました。")
