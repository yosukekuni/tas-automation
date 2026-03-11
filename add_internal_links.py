#!/usr/bin/env python3
"""
土量コスト記事にドローン測量CTAブロックを自動追加するスクリプト
"""

import requests
import json
import time
import sys
from requests.auth import HTTPBasicAuth

# Config
CONFIG_PATH = "/mnt/c/Users/USER/Documents/_data/automation_config.json"
with open(CONFIG_PATH) as f:
    config = json.load(f)

WP_BASE = config["wordpress"]["base_url"]
WP_USER = config["wordpress"]["user"]
WP_PASS = config["wordpress"]["app_password"]
AUTH = HTTPBasicAuth(WP_USER, WP_PASS)

CTA_BLOCK = """<div style="margin:2.5rem 0;padding:1.5rem;border:2px solid var(--brand,#1a3a5c);border-radius:12px;background:var(--surface,#f8f9fa)">
<p style="font-size:1.1rem;font-weight:700;margin:0 0 .5rem">ドローン測量で土量計算を効率化しませんか？</p>
<p style="margin:0 0 1rem;color:var(--muted,#555)">東海エアサービスなら、従来3日かかる土量計算を半日で完了。精度±3cm、年間100件超の実績。</p>
<a href="/services/uav-survey/" style="display:inline-block;padding:.75rem 1.5rem;background:var(--brand,#1a3a5c);color:#fff;text-decoration:none;border-radius:8px;font-weight:600">ドローン測量サービスを見る →</a>
<a href="/contact/" style="display:inline-block;margin-left:1rem;padding:.75rem 1.5rem;border:1px solid var(--brand,#1a3a5c);color:var(--brand,#1a3a5c);text-decoration:none;border-radius:8px;font-weight:600">無料見積もり</a>
</div>"""

CTA_CHECK_STRING = "ドローン測量で土量計算を効率化"

# 土量関連キーワード
DORYO_KEYWORDS = ["土量", "m3", "t換算", "ほぐし", "締固め", "土砂量", "残土", "盛土", "切土",
                   "土工", "掘削", "埋戻", "地山", "変化率"]

def fetch_all_posts():
    """全投稿を取得"""
    all_posts = []
    page = 1
    while True:
        print(f"Fetching page {page}...")
        resp = requests.get(
            f"{WP_BASE}/posts",
            params={"per_page": 100, "page": page, "status": "publish"},
            auth=AUTH
        )
        if resp.status_code != 200:
            print(f"  Status {resp.status_code}, stopping pagination.")
            break
        posts = resp.json()
        if not posts:
            break
        all_posts.extend(posts)
        print(f"  Got {len(posts)} posts (total: {len(all_posts)})")
        # Check if there are more pages
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break
        page += 1
    return all_posts

def is_doryo_post(post):
    """土量関連の記事かどうか判定"""
    title = post.get("title", {}).get("rendered", "").lower()
    slug = post.get("slug", "").lower()
    # content rendered for keyword check
    content = post.get("content", {}).get("rendered", "").lower()

    for kw in DORYO_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title or kw_lower in slug:
            return True
    return False

def has_cta_already(post):
    """既にCTAが含まれているかチェック"""
    content = post.get("content", {}).get("rendered", "")
    return CTA_CHECK_STRING in content

def update_post(post_id, new_content):
    """記事を更新（POSTのみ）"""
    resp = requests.post(
        f"{WP_BASE}/posts/{post_id}",
        json={"content": new_content},
        auth=AUTH
    )
    return resp.status_code, resp.text

def main():
    print("=" * 60)
    print("土量コスト記事 → ドローン測量CTA追加スクリプト")
    print("=" * 60)

    # Step 1: 全投稿取得
    posts = fetch_all_posts()
    print(f"\n全投稿数: {len(posts)}")

    # Step 2: 土量記事をフィルタ
    doryo_posts = [p for p in posts if is_doryo_post(p)]
    print(f"土量関連記事: {len(doryo_posts)}")

    # リスト表示
    print("\n--- 土量関連記事一覧 ---")
    for p in doryo_posts:
        title = p["title"]["rendered"]
        has_cta = "✓CTA済" if has_cta_already(p) else "→追加対象"
        print(f"  [{p['id']}] {title}  {has_cta}")

    # Step 3: CTA未追加の記事をフィルタ
    target_posts = [p for p in doryo_posts if not has_cta_already(p)]
    already_done = len(doryo_posts) - len(target_posts)
    print(f"\nCTA追加済み: {already_done}件")
    print(f"CTA追加対象: {len(target_posts)}件")

    if not target_posts:
        print("\n全記事にCTAが追加済みです。処理終了。")
        return

    # Step 4: 各記事にCTAを追加
    # content.raw を取得するために個別にfetch (context=edit)
    success = 0
    failed = 0
    skipped = 0

    for i, post in enumerate(target_posts):
        post_id = post["id"]
        title = post["title"]["rendered"]
        print(f"\n[{i+1}/{len(target_posts)}] Processing: {title} (ID:{post_id})")

        # Get raw content
        resp = requests.get(
            f"{WP_BASE}/posts/{post_id}",
            params={"context": "edit"},
            auth=AUTH
        )
        if resp.status_code != 200:
            print(f"  ✗ Failed to fetch raw content: {resp.status_code}")
            failed += 1
            time.sleep(1)
            continue

        post_data = resp.json()
        raw_content = post_data.get("content", {}).get("raw", "")

        if not raw_content:
            print(f"  ✗ Empty raw content, skipping")
            skipped += 1
            time.sleep(1)
            continue

        # Double check CTA not already in raw
        if CTA_CHECK_STRING in raw_content:
            print(f"  → Already has CTA in raw content, skipping")
            skipped += 1
            time.sleep(1)
            continue

        # Append CTA
        new_content = raw_content.rstrip() + "\n\n" + CTA_BLOCK

        # Update
        status, resp_text = update_post(post_id, new_content)
        if status == 200:
            print(f"  ✓ Updated successfully")
            success += 1
        else:
            print(f"  ✗ Update failed: {status}")
            # Show first 200 chars of error
            print(f"    {resp_text[:200]}")
            failed += 1

        time.sleep(1)

    # Summary
    print("\n" + "=" * 60)
    print("処理結果サマリ")
    print("=" * 60)
    print(f"土量関連記事:     {len(doryo_posts)}件")
    print(f"CTA追加済み(既存): {already_done}件")
    print(f"今回CTA追加成功:   {success}件")
    print(f"スキップ:          {skipped}件")
    print(f"失敗:              {failed}件")
    print("=" * 60)

if __name__ == "__main__":
    main()
