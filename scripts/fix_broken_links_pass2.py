#!/usr/bin/env python3
"""
Pass 2: www正規化後、残っているリンク切れを修正
特にリンク切れパスの直接置換（href属性内）
"""

import json
import requests
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime

with open("/mnt/c/Users/USER/Documents/_data/automation_config.json") as f:
    config = json.load(f)

WP = config["wordpress"]
BASE_URL = WP["base_url"]
AUTH = (WP["user"], WP["app_password"])
HEADERS = {"User-Agent": "TAS-Automation/1.0", "Content-Type": "application/json"}

# Full replacement map: broken href (exact match) → correct href
# After www normalization, all internal URLs use tokaiair.com (no www)
REPLACEMENTS = {
    # 旧サービスページ → 新サービスページ
    'href="/uav-survey/"': 'href="/services/uav-survey/"',
    'href="/3d-measurement/"': 'href="/services/3d-measurement/"',
    'href="/infrared-inspection/"': 'href="/services/infrared-inspection/"',
    'href="/drone-survey-cost-nagoya/"': 'href="/info/drone-survey-cost-nagoya/"',
    'href="https://tokaiair.com/service/infrared-inspection/"': 'href="https://tokaiair.com/services/infrared-inspection/"',
    'href="https://tokaiair.com/cases/#list"': 'href="https://tokaiair.com/case-library/cases/"',

    # /news/xxx → 正しいパスへ
    'href="/news/choose-dump-truck/"': 'href="/column/earthwork-cost/choose-dump-truck/"',
    'href="/news/m3-ton-conversion-soil-density/"': 'href="/column/earthwork-cost/m3-ton-conversion-soil-density/"',

    # /tools/ → 新パス
    'href="/tools/earthwork-cost/"': 'href="/tools/earthwork/calculator/"',
    'href="/tools/recycle-sim/"': 'href="/tools/earthwork/calculator/"',

    # /cases/ → case-library
    'href="/cases/"': 'href="/case-library/cases/"',

    # /privacy → privacy-policy
    'href="/privacy"': 'href="/privacy-policy/"',

    # /feed/ → /news/
    'href="/feed/"': 'href="/news/"',

    # /column/xxx/ (カテゴリなし旧URL) → 正しいカテゴリ付きURL
    'href="/column/earthwork-cost/"': 'href="/column/earthwork-cost/earthwork-cost/"',
    'href="/column/3d-volume-measurement-guide/"': 'href="/column/earthwork-cost/pointcloud-to-volume/"',
    'href="/column/drone-survey-qa-before-quotation/"': 'href="/column/earthwork-cost/drone-survey-estimate-qa-checklist/"',
    'href="/column/construction-dx/"': 'href="/column/construction-drone-use-cases/"',
    'href="/column/factory-scan-roi/"': 'href="/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="/column/floor-flatness-warehouse/"': 'href="/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="/column/i-construction-ict-steps-cost-solution/"': 'href="/column/earthwork-cost/i-construction-ict-steps-cost-solution/"',
    'href="/column/pointcloud-bim/"': 'href="/column/point-cloud-data-usage/"',
    'href="/column/uav-survey/"': 'href="/column/drone-survey-accuracy/"',
    'href="/column/tag/earthwork/"': 'href="/column/"',
    'href="/column/tag/quality-control/"': 'href="/column/"',

    # 絶対URL版 (after www normalization → tokaiair.com)
    'href="https://tokaiair.com/column/earthwork-cost-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-flatness-3d-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/slab-unevenness-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/earth-volume-cost-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-unevenness-3d-measurement-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/piping-isometric-pointcloud-bim-route/"': 'href="https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="https://tokaiair.com/column/earthwork-volume-cost-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-unevenness-3d-measurement/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/3d-measurement-case-studies/"': 'href="https://tokaiair.com/case-library/cases/"',
    'href="https://tokaiair.com/column/earthwork-cost-reduction-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/construction-dx-case-studies/"': 'href="https://tokaiair.com/case-library/cases/"',
    'href="https://tokaiair.com/column/volume-cost-management-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/volume-cost-management/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/piping-renewal-pointcloud-isometric-bim-speedup/"': 'href="https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="https://tokaiair.com/column/plant-piping-renewal-stop-time-reduction/"': 'href="https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="https://tokaiair.com/column/sfm-pointcloud-software-selection-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/sfm-pointcloud-software-selection-guide/"',
    'href="https://tokaiair.com/column/factory-scan-introduction-for-equipment-manager/"': 'href="https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="https://tokaiair.com/column/slab-flatness-drone-3d"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/soil-volume-cost-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-leveling-3d-measurement-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/piping-isometric-pointcloud-renewal-speed/"': 'href="https://tokaiair.com/column/pointcloud-bim/factory-3dscan-guide/"',
    'href="https://tokaiair.com/column/doryo-cost-complete-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-3d-measure-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/doyou-cost-guide/"': 'href="https://tokaiair.com/column/earthwork-cost/earthwork-cost/"',
    'href="https://tokaiair.com/column/slab-leveling-3d-scan-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/slab-level-3d-measurement-guide/"': 'href="https://tokaiair.com/column/pointcloud-bim/slab-flatness-warehouse-3d/"',
    'href="https://tokaiair.com/column/dron-earthwork-measurement/"': 'href="https://tokaiair.com/column/drone-earthwork-volume/"',

    # /blog/ → /column/
    'href="https://tokaiair.com/blog/"': 'href="https://tokaiair.com/column/"',

    # /calc-volume-cost/ → /tools/earthwork/calculator/
    'href="https://tokaiair.com/calc-volume-cost/"': 'href="https://tokaiair.com/tools/earthwork/calculator/"',

    # /pricing/ → /case-library/pricing/
    'href="https://tokaiair.com/pricing/"': 'href="https://tokaiair.com/case-library/pricing/"',

    # /service/drone-survey/ → /services/uav-survey/
    'href="https://tokaiair.com/service/drone-survey/"': 'href="https://tokaiair.com/services/uav-survey/"',

    # /news/soil-volume... → /info/...
    'href="https://tokaiair.com/news/soil-volume-calculator-27-media-coverage/"': 'href="https://tokaiair.com/info/soil-volume-calculator-27-media-coverage/"',

    # absolute versions of service pages
    'href="https://tokaiair.com/uav-survey/"': 'href="https://tokaiair.com/services/uav-survey/"',
    'href="https://tokaiair.com/3d-measurement/"': 'href="https://tokaiair.com/services/3d-measurement/"',
    'href="https://tokaiair.com/infrared-inspection/"': 'href="https://tokaiair.com/services/infrared-inspection/"',
}


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


def fix_content(html):
    changes = []
    for old, new in REPLACEMENTS.items():
        if old in html:
            count = html.count(old)
            html = html.replace(old, new)
            changes.append(f"  {old} → {new} ({count}箇所)")
    return html, changes


def update_post(post_id, post_type, content):
    endpoint = "posts" if post_type == "post" else "pages"
    url = f"{BASE_URL}/{endpoint}/{post_id}"
    resp = requests.post(url, json={"content": content}, auth=AUTH, headers=HEADERS)
    return resp.status_code, resp.text


print(f"=== Pass 2: リンク切れ修正（パス置換） ===")
print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

posts = get_all_content("posts")
pages = get_all_content("pages")
all_content = []
for p in posts:
    all_content.append({"id": p["id"], "type": "post", "title": p["title"]["rendered"], "content": p["content"]["rendered"]})
for p in pages:
    all_content.append({"id": p["id"], "type": "page", "title": p["title"]["rendered"], "content": p["content"]["rendered"]})

print(f"合計: {len(all_content)}件\n")

total_fixed = 0
fix_log = []

for item in all_content:
    fixed_content, changes = fix_content(item["content"])

    if changes:
        print(f"[{item['type']}] ID:{item['id']} - {item['title']}")
        for c in changes:
            print(c)

        status, resp_text = update_post(item["id"], item["type"], fixed_content)
        if status == 200:
            print(f"  -> 更新成功\n")
            total_fixed += 1
            fix_log.append({"id": item["id"], "type": item["type"], "title": item["title"], "changes": changes, "status": "success"})
        else:
            print(f"  -> 更新失敗: HTTP {status}")
            print(f"    {resp_text[:200]}\n")
            fix_log.append({"id": item["id"], "type": item["type"], "title": item["title"], "changes": changes, "status": f"failed: HTTP {status}"})

        time.sleep(0.5)

print(f"\n=== 完了 ===")
print(f"修正した記事/ページ: {total_fixed}件")
print(f"終了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

with open("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/broken_links_fix_log_pass2.json", "w", encoding="utf-8") as f:
    json.dump(fix_log, f, ensure_ascii=False, indent=2)
print("\nログを broken_links_fix_log_pass2.json に保存しました。")
