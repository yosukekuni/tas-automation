#!/usr/bin/env python3
"""
tokaiair.com リンク切れ修正スクリプト
検出したリンク切れを修正マッピングに基づいて置換する
"""

import json
import requests
import re
import time
from datetime import datetime

# Config
with open("/mnt/c/Users/USER/Documents/_data/automation_config.json") as f:
    config = json.load(f)

WP = config["wordpress"]
BASE_URL = WP["base_url"]
AUTH = (WP["user"], WP["app_password"])
HEADERS = {"User-Agent": "TAS-Automation/1.0", "Content-Type": "application/json"}

# =====================================================
# LINK REPLACEMENT MAPPING
# Old URL → New URL (based on current site structure)
# =====================================================
LINK_MAP = {
    # === /column/XXX/ → 正しいカテゴリ付きパスへ ===
    # 旧: /column/earthwork-cost/ → 新: カテゴリ直下
    "/column/earthwork-cost/": "/column/earthwork-cost/earthwork-cost/",
    "/column/3d-volume-measurement-guide/": "/column/earthwork-cost/pointcloud-to-volume/",
    "/column/drone-survey-qa-before-quotation/": "/column/earthwork-cost/drone-survey-estimate-qa-checklist/",
    "/column/construction-dx/": "/column/construction-drone-use-cases/",
    "/column/factory-scan-roi/": "/column/pointcloud-bim/factory-3dscan-guide/",
    "/column/floor-flatness-warehouse/": "/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "/column/i-construction-ict-steps-cost-solution/": "/column/earthwork-cost/i-construction-ict-steps-cost-solution/",
    "/column/pointcloud-bim/": "/column/point-cloud-data-usage/",
    "/column/uav-survey/": "/column/drone-survey-accuracy/",
    "/column/tag/earthwork/": "/column/",
    "/column/tag/quality-control/": "/column/",

    # === /news/XXX/ → 正しいパスへ ===
    "/news/choose-dump-truck/": "/column/earthwork-cost/choose-dump-truck/",
    "/news/m3-ton-conversion-soil-density/": "/column/earthwork-cost/m3-ton-conversion-soil-density/",

    # === /tools/XXX/ → 新構造へ ===
    "/tools/earthwork-cost/": "/tools/earthwork/calculator/",
    "/tools/recycle-sim/": "/tools/earthwork/calculator/",

    # === サービスページの旧URL → 新URL ===
    "/uav-survey/": "/services/uav-survey/",
    "/3d-measurement/": "/services/3d-measurement/",
    "/infrared-inspection/": "/services/infrared-inspection/",
    "/drone-survey-cost-nagoya/": "/info/drone-survey-cost-nagoya/",

    # === /cases/ → case-library ===
    "/cases/": "/case-library/cases/",

    # === /privacy → privacy-policy ===
    "/privacy": "/privacy-policy/",

    # === /feed/ → news ===
    "/feed/": "/news/",

    # === 絶対URL版（www.tokaiair.com） ===
    "https://www.tokaiair.com/3d-measurement/": "https://tokaiair.com/services/3d-measurement/",
    "https://www.tokaiair.com/uav-survey/": "https://tokaiair.com/services/uav-survey/",
    "https://www.tokaiair.com/infrared-inspection/": "https://tokaiair.com/services/infrared-inspection/",
    "https://www.tokaiair.com/blog/": "https://tokaiair.com/column/",
    "https://www.tokaiair.com/calc-volume-cost/": "https://tokaiair.com/tools/earthwork/calculator/",
    "https://www.tokaiair.com/pricing/": "https://tokaiair.com/case-library/pricing/",
    "https://www.tokaiair.com/cases/#list": "https://tokaiair.com/case-library/cases/",
    "https://www.tokaiair.com/service/drone-survey/": "https://tokaiair.com/services/uav-survey/",
    "https://www.tokaiair.com/news/soil-volume-calculator-27-media-coverage/": "https://tokaiair.com/info/soil-volume-calculator-27-media-coverage/",

    # === 絶対URL tokaiair.com (without www) ===
    "https://tokaiair.com/service/infrared-inspection/": "https://tokaiair.com/services/infrared-inspection/",

    # === /column/XXX が存在しない記事へのリンク → 最も近い現存ページ ===
    "https://www.tokaiair.com/column/earthwork-cost-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-flatness-3d-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/slab-unevenness-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/earth-volume-cost-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-unevenness-3d-measurement-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/piping-isometric-pointcloud-bim-route/": "https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/",
    "https://www.tokaiair.com/column/earthwork-volume-cost-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-unevenness-3d-measurement/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/3d-measurement-case-studies/": "https://tokaiair.com/case-library/cases/",
    "https://www.tokaiair.com/column/earthwork-cost-reduction-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/construction-dx-case-studies/": "https://tokaiair.com/case-library/cases/",
    "https://www.tokaiair.com/column/volume-cost-management-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/volume-cost-management/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/piping-renewal-pointcloud-isometric-bim-speedup/": "https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/",
    "https://www.tokaiair.com/column/plant-piping-renewal-stop-time-reduction/": "https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/",
    "https://www.tokaiair.com/column/sfm-pointcloud-software-selection-guide/": "https://tokaiair.com/column/earthwork-cost/sfm-pointcloud-software-selection-guide/",
    "https://www.tokaiair.com/column/factory-scan-introduction-for-equipment-manager/": "https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/",
    "https://www.tokaiair.com/column/slab-flatness-drone-3d": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/soil-volume-cost-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-leveling-3d-measurement-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/piping-isometric-pointcloud-renewal-speed/": "https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/",
    "https://www.tokaiair.com/column/doryo-cost-complete-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-3d-measure-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/doyou-cost-guide/": "https://tokaiair.com/column/earthwork-cost/earthwork-cost/",
    "https://www.tokaiair.com/column/slab-leveling-3d-scan-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/slab-level-3d-measurement-guide/": "https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/",
    "https://www.tokaiair.com/column/dron-earthwork-measurement/": "https://tokaiair.com/column/drone-earthwork-volume/",

    # === sandbox: リンク（ChatGPT由来のゴミリンク） → 削除対象 ===
    # これは特殊処理: aタグごと削除してテキストだけ残す

    # === 画像リンク切れ ===
    # tokaiair.com/wp-content/uploads/2025/09/入力画面_page-0001.jpg → 削除
}

# リンクを含むaタグごと削除するパターン（リンクテキストは残す）
REMOVE_LINK_PATTERNS = [
    r'sandbox:/mnt/data/',
    r'tokaiair\.com/wp-content/uploads/2025/09/入力画面_page-0001\.jpg',
]


def get_all_content(endpoint):
    items = []
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            params={"per_page": 100, "page": page, "status": "publish"},
            auth=AUTH,
            headers={"User-Agent": "TAS-Automation/1.0"},
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


def fix_content(html, page_title):
    """Apply all link fixes to HTML content"""
    original = html
    changes = []

    # 1. Apply direct URL replacements
    for old_url, new_url in LINK_MAP.items():
        # Match in href attributes
        old_escaped = re.escape(old_url)
        # Match href="old_url" with possible quotes
        pattern = f'href="{old_escaped}"'
        replacement = f'href="{new_url}"'
        if pattern in html:
            count = html.count(pattern)
            html = html.replace(pattern, replacement)
            changes.append(f"  {old_url} → {new_url} ({count}箇所)")

        # Also match single quotes
        pattern_sq = f"href='{old_escaped}'"
        replacement_sq = f"href='{new_url}'"
        if pattern_sq in html:
            count = html.count(pattern_sq)
            html = html.replace(pattern_sq, replacement_sq)
            changes.append(f"  {old_url} → {new_url} ({count}箇所, single quote)")

    # 2. Remove broken links (keep text)
    for pattern in REMOVE_LINK_PATTERNS:
        regex = re.compile(r'<a\s[^>]*href="[^"]*' + pattern + r'[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
        matches = regex.findall(html)
        if matches:
            html = regex.sub(r'\1', html)
            changes.append(f"  リンク削除(テキスト残す): {pattern} ({len(matches)}箇所)")

    # 3. Normalize www.tokaiair.com → tokaiair.com for remaining links
    www_pattern = 'href="https://www.tokaiair.com/'
    no_www = 'href="https://tokaiair.com/'
    if www_pattern in html:
        count = html.count(www_pattern)
        html = html.replace(www_pattern, no_www)
        changes.append(f"  www.tokaiair.com → tokaiair.com 正規化 ({count}箇所)")

    return html, changes


def update_post(post_id, post_type, content):
    """Update post/page via WP REST API using POST method"""
    endpoint = "posts" if post_type == "post" else "pages"
    url = f"{BASE_URL}/{endpoint}/{post_id}"

    resp = requests.post(
        url,
        json={"content": content},
        auth=AUTH,
        headers=HEADERS,
    )
    return resp.status_code, resp.text


# Main execution
print(f"=== tokaiair.com リンク切れ修正 ===")
print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

# Get all content
print("全コンテンツ取得中...")
posts = get_all_content("posts")
pages = get_all_content("pages")
all_content = []
for p in posts:
    all_content.append({
        "id": p["id"],
        "type": "post",
        "title": p["title"]["rendered"],
        "content": p["content"]["rendered"],
    })
for p in pages:
    all_content.append({
        "id": p["id"],
        "type": "page",
        "title": p["title"]["rendered"],
        "content": p["content"]["rendered"],
    })

print(f"合計: {len(all_content)}件\n")

# Process each content item
total_fixed = 0
fix_log = []

for item in all_content:
    fixed_content, changes = fix_content(item["content"], item["title"])

    if changes:
        print(f"[{item['type']}] ID:{item['id']} - {item['title']}")
        for c in changes:
            print(c)

        # Update via API
        status, resp_text = update_post(item["id"], item["type"], fixed_content)
        if status == 200:
            print(f"  ✓ 更新成功\n")
            total_fixed += 1
            fix_log.append({
                "id": item["id"],
                "type": item["type"],
                "title": item["title"],
                "changes": changes,
                "status": "success",
            })
        else:
            print(f"  ✗ 更新失敗: HTTP {status}\n")
            # Show first 200 chars of error
            print(f"    {resp_text[:200]}\n")
            fix_log.append({
                "id": item["id"],
                "type": item["type"],
                "title": item["title"],
                "changes": changes,
                "status": f"failed: HTTP {status}",
            })

        time.sleep(0.5)  # Rate limiting

print(f"\n=== 完了 ===")
print(f"修正した記事/ページ: {total_fixed}件")
print(f"終了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# Save fix log
with open("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/broken_links_fix_log.json", "w", encoding="utf-8") as f:
    json.dump(fix_log, f, ensure_ascii=False, indent=2)

print("\n修正ログを broken_links_fix_log.json に保存しました。")
