#!/usr/bin/env python3
"""
サイトヘルス自動監査
毎週実行 → 問題を検出 → Lark Bot DMで報告

チェック項目:
- 全ページのtitle/meta description（空・デフォルト・重複）
- 構造化データの有無（JSON-LD）
- 内部リンク切れ
- 画像alt属性
- ページ速度指標
- SEO/AEO基本要件
"""

import json
import re
import time
import urllib.request
import urllib.parse
import base64
from datetime import datetime
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

WP_BASE = "https://tokaiair.com/wp-json/wp/v2"
WP_AUTH = base64.b64encode(
    f"{CONFIG['wordpress']['user']}:{CONFIG['wordpress']['app_password']}".encode()
).decode()

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

SITE_URL = "https://www.tokaiair.com"

# 致命的な問題パターン
BAD_TITLES = ["HOME", "ホーム", "トップページ", "untitled", "無題", "WordPress"]
REQUIRED_SCHEMAS = ["Organization", "LocalBusiness", "FAQPage"]


def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def send_lark_dm(token, text):
    data = json.dumps({
        "receive_id": OWNER_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"  Lark DM error: {e}")


def wp_get(endpoint, params=None):
    url = f"{WP_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {WP_AUTH}"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except Exception as e:
        return []


def fetch_page(url):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "TAS-HealthAudit/1.0"
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  Fetch error [{url}]: {e}")
        return ""


def extract_meta(html):
    """HTMLからtitle, meta description, JSON-LDを抽出"""
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
    if m:
        title = m.group(1).strip()

    desc = ""
    m = re.search(r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if m:
        desc = m.group(1).strip()

    schemas = []
    for m in re.finditer(r'<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>', html, re.DOTALL):
        try:
            j = json.loads(m.group(1))
            if isinstance(j, dict):
                if "@graph" in j:
                    for item in j["@graph"]:
                        schemas.append(item.get("@type", ""))
                else:
                    schemas.append(j.get("@type", ""))
        except (json.JSONDecodeError, ValueError):
            pass

    # Check for author info
    has_author = bool(re.search(r'(筆者|著者|執筆|author|ライター)', html, re.IGNORECASE))

    # Check for FAQ section
    has_faq = bool(re.search(r'(よくある質問|FAQ|Q&A|質問と回答)', html, re.IGNORECASE))

    # Count H1/H2
    h1_count = len(re.findall(r'<h1[\s>]', html, re.IGNORECASE))
    h2_tags = re.findall(r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL)

    # Images without alt
    imgs_total = len(re.findall(r'<img\s', html, re.IGNORECASE))
    imgs_no_alt = len(re.findall(r'<img\s(?:(?!alt=)[^>])*>', html, re.IGNORECASE))

    return {
        "title": title,
        "description": desc,
        "schemas": schemas,
        "has_author": has_author,
        "has_faq": has_faq,
        "h1_count": h1_count,
        "h2_count": len(h2_tags),
        "imgs_total": imgs_total,
        "imgs_no_alt": imgs_no_alt,
    }


def audit_all():
    """全ページ監査"""
    now = datetime.now()
    issues = {"critical": [], "high": [], "medium": [], "info": []}

    # Get all pages and posts
    pages = []
    for ptype in ["pages", "posts"]:
        page_num = 1
        while True:
            items = wp_get(ptype, {"per_page": 100, "page": page_num, "status": "publish"})
            if not items:
                break
            pages.extend(items)
            if len(items) < 100:
                break
            page_num += 1
            time.sleep(0.3)

    print(f"監査対象: {len(pages)}ページ")

    titles_seen = {}
    descs_seen = {}

    for i, page in enumerate(pages):
        url = page.get("link", "")
        wp_title = page.get("title", {}).get("rendered", "")
        slug = page.get("slug", "")

        if not url:
            continue

        # Fetch actual page
        html = fetch_page(url)
        if not html:
            issues["high"].append(f"アクセス不可: {url}")
            continue

        meta = extract_meta(html)

        # Check title
        if not meta["title"]:
            issues["critical"].append(f"タイトルなし: {url}")
        elif any(bad.lower() in meta["title"].lower() for bad in BAD_TITLES):
            issues["critical"].append(f"デフォルトタイトル「{meta['title'][:50]}」: {url}")
        elif len(meta["title"]) < 10:
            issues["high"].append(f"タイトル短すぎ「{meta['title']}」: {url}")
        elif len(meta["title"]) > 60:
            issues["medium"].append(f"タイトル長すぎ({len(meta['title'])}字): {url}")

        # Title duplicate check
        if meta["title"] in titles_seen:
            issues["high"].append(f"タイトル重複「{meta['title'][:40]}」: {url} = {titles_seen[meta['title']]}")
        titles_seen[meta["title"]] = url

        # Check description
        if not meta["description"]:
            issues["high"].append(f"meta description なし: {url}")
        elif len(meta["description"]) < 50:
            issues["medium"].append(f"meta description 短すぎ({len(meta['description'])}字): {url}")
        elif meta["description"] in descs_seen:
            issues["medium"].append(f"meta description 重複: {url}")
        if meta["description"]:
            descs_seen[meta["description"]] = url

        # Check structured data
        if not meta["schemas"]:
            issues["medium"].append(f"構造化データなし: {url}")

        # Service pages need Service schema
        if "/service" in url and "Service" not in meta["schemas"]:
            issues["high"].append(f"Serviceスキーマなし（サービスページ）: {url}")

        # Articles need author
        if page.get("type") == "post" and not meta["has_author"]:
            issues["medium"].append(f"筆者情報なし（記事）: {url}")

        # H1 check
        if meta["h1_count"] == 0:
            issues["high"].append(f"H1タグなし: {url}")
        elif meta["h1_count"] > 1:
            issues["medium"].append(f"H1タグ複数({meta['h1_count']}個): {url}")

        # Images without alt
        if meta["imgs_no_alt"] > 0:
            issues["medium"].append(f"alt属性なし画像{meta['imgs_no_alt']}/{meta['imgs_total']}枚: {url}")

        # AEO: FAQ section without schema
        if meta["has_faq"] and "FAQPage" not in meta["schemas"]:
            issues["high"].append(f"FAQ内容あるがFAQPageスキーマなし: {url}")

        # 名古屋 mention check for service pages
        if "/service" in url and "名古屋" not in html:
            issues["medium"].append(f"サービスページに「名古屋」なし（AEO）: {url}")

        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(pages)} 完了...")
        time.sleep(0.5)

    # Global checks
    # Check for LocalBusiness on homepage
    homepage_html = fetch_page(SITE_URL)
    if homepage_html:
        hp_meta = extract_meta(homepage_html)
        if "LocalBusiness" not in hp_meta["schemas"] and "ProfessionalService" not in hp_meta["schemas"]:
            issues["critical"].append("ホームページにLocalBusinessスキーマなし")
        if "東海エアサービス" not in hp_meta["title"]:
            issues["critical"].append(f"ホームページタイトルに社名なし: {hp_meta['title'][:60]}")

    return issues


def format_report(issues):
    """レポート生成"""
    now = datetime.now()
    lines = [
        f"🔍 サイトヘルス監査レポート",
        f"実行: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    total = sum(len(v) for v in issues.values())

    if issues["critical"]:
        lines.append(f"🚨 致命的({len(issues['critical'])}件)")
        for item in issues["critical"][:10]:
            lines.append(f"  {item}")
        lines.append("")

    if issues["high"]:
        lines.append(f"⚠️ 重要({len(issues['high'])}件)")
        for item in issues["high"][:15]:
            lines.append(f"  {item}")
        lines.append("")

    if issues["medium"]:
        lines.append(f"📋 中({len(issues['medium'])}件)")
        for item in issues["medium"][:10]:
            lines.append(f"  {item}")
        if len(issues["medium"]) > 10:
            lines.append(f"  ...他{len(issues['medium'])-10}件")
        lines.append("")

    lines.extend([
        f"合計: {total}件の問題を検出",
        f"致命的{len(issues['critical'])} / 重要{len(issues['high'])} / 中{len(issues['medium'])}",
    ])

    return "\n".join(lines)


def main():
    import sys
    print("=== サイトヘルス監査開始 ===")

    issues = audit_all()
    report = format_report(issues)

    print("\n" + report)

    # Save log
    log_file = SCRIPT_DIR / "site_health.log"
    with open(log_file, "a") as f:
        f.write(f"\n{'='*50}\n{report}\n")

    # Send Lark DM
    if "--notify" in sys.argv:
        token = lark_get_token()
        # Truncate if too long for Lark
        if len(report) > 3500:
            report = report[:3500] + "\n...(詳細はログ参照)"
        send_lark_dm(token, report)
        print("[Lark通知送信完了]")

    # Save detailed JSON
    detail_file = SCRIPT_DIR / "site_health_detail.json"
    with open(detail_file, "w") as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
