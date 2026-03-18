#!/usr/bin/env python3
"""
土量計算カテゴリ記事にドローン測量関連の内部リンクを自動追加するスクリプト

対象: カテゴリID:14 (earthwork-cost) の全記事
挿入: ドローン測量コーナーストーン記事への関連リンクブロック
位置: CTAブロックの直前、またはCTAがなければ記事末尾

Usage:
    python3 earthwork_internal_links.py --dry-run   # プレビュー（変更なし）
    python3 earthwork_internal_links.py --apply      # 本番実行
"""

import json
import re
import sys
import time
import base64
import urllib.request
import urllib.error
import argparse
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

CONFIG_PATH = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
CATEGORY_ID = 14
SLEEP_SEC = 0.5

# リンク先コーナーストーン記事ID（自己参照防止用）
CORNERSTONE_IDS = [5185, 5927, 5944]

# 関連リンクブロックに含める記事（ID: 表示タイトル）
# リンクURLはAPIから動的に取得する
LINK_POSTS = {
    5185: "ドローン測量 vs 地上測量を徹底比較｜精度・コスト・工期から選ぶ最終判断ガイド",
    5927: "ドローン測量の費用相場｜名古屋・東海エリアの実勢価格",
}

# 重複チェック用キーワード（slug部分文字列）
DUPLICATE_CHECK_SLUGS = [
    "drone-vs-ground-survey-ultimate-guide",
    "drone-survey-cost-nagoya",
    "drone-survey-vs-traditional-survey",
    "drone-vs-traditional-survey",
]

# CTAブロック検出パターン
CTA_PATTERN = re.compile(r'ドローン測量の費用、気になりませんか')


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def wp_request(url, cfg, method="GET", data=None):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    auth = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def get_category_posts(cfg):
    """カテゴリID:14の全記事を取得（context=edit で生のHTMLを取得）"""
    base = cfg["wordpress"]["base_url"]
    all_posts = []
    page = 1
    while True:
        url = (f"{base}/posts?per_page=50&page={page}"
               f"&categories={CATEGORY_ID}&status=publish&context=edit"
               f"&_fields=id,slug,title,content,link")
        try:
            posts = wp_request(url, cfg)
            if not posts:
                break
            all_posts.extend(posts)
            page += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:  # No more pages
                break
            raise
    return all_posts


def fetch_cornerstone_links(cfg):
    """リンク先記事の実際のURLをAPIから取得し、関連リンクブロックHTMLを構築"""
    base = cfg["wordpress"]["base_url"]
    print("=== リンク先記事の確認 ===")
    link_items = []
    for post_id, display_title in LINK_POSTS.items():
        url = f"{base}/posts/{post_id}?_fields=id,slug,link,title"
        post = wp_request(url, cfg)
        link = post["link"]
        # 相対パスに変換
        relative = "/" + link.split("//", 1)[1].split("/", 1)[1]
        print(f"  ID:{post_id} -> {relative} ({display_title[:30]}...)")
        link_items.append(f'    <li><a href="{relative}">{display_title}</a></li>')

    block = (
        '<div style="background:var(--bg-2,#f8fafc);border-left:4px solid var(--brand,#1647FB);'
        'padding:20px 24px;margin:24px 0;border-radius:0 8px 8px 0">\n'
        '  <p style="font-weight:700;margin:0 0 8px;color:var(--brand,#1647FB)">関連記事</p>\n'
        '  <ul style="margin:0;padding-left:20px">\n'
        + "\n".join(link_items) + "\n"
        '  </ul>\n'
        '</div>'
    )
    print()
    return block


def has_drone_survey_links(content):
    """既にドローン測量記事へのリンクがあるかチェック"""
    for slug in DUPLICATE_CHECK_SLUGS:
        if slug in content:
            return True
    return False


def is_cornerstone_post(post):
    """記事自身がコーナーストーン記事かどうか"""
    return post["id"] in CORNERSTONE_IDS


def insert_related_block(content, related_block):
    """関連リンクブロックを適切な位置に挿入"""
    cta_match = CTA_PATTERN.search(content)
    if cta_match:
        pos = cta_match.start()
        before = content[:pos]
        # CTAを包むdivの開始タグを探す
        last_div = before.rfind('<div')
        if last_div >= 0:
            insert_pos = last_div
        else:
            insert_pos = pos
        new_content = content[:insert_pos] + related_block + "\n" + content[insert_pos:]
        return new_content, "CTA直前に挿入"
    else:
        new_content = content.rstrip() + "\n" + related_block
        return new_content, "記事末尾に追加"


def main():
    parser = argparse.ArgumentParser(description="土量計算記事にドローン測量内部リンクを追加")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="プレビューのみ（変更なし）")
    group.add_argument("--apply", action="store_true", help="本番実行")
    args = parser.parse_args()

    cfg = load_config()
    base = cfg["wordpress"]["base_url"]

    # Step 1: リンク先記事のURL取得・ブロックHTML構築
    related_block = fetch_cornerstone_links(cfg)

    # Step 2: カテゴリ記事取得
    print(f"=== カテゴリID:{CATEGORY_ID}の記事を取得中... ===")
    posts = get_category_posts(cfg)
    print(f"  取得記事数: {len(posts)}")
    print()

    # Step 3: 各記事を処理
    stats = {"total": len(posts), "updated": 0, "skipped_has_links": 0,
             "skipped_self": 0, "errors": 0}

    for i, post in enumerate(posts, 1):
        post_id = post["id"]
        title = post["title"]["raw"] if isinstance(post["title"], dict) else post["title"]
        slug = post["slug"]
        content = post["content"]["raw"] if isinstance(post["content"], dict) else post["content"]

        print(f"[{i}/{len(posts)}] ID:{post_id} {title}")

        # 自己参照チェック
        if is_cornerstone_post(post):
            print(f"  -> SKIP: リンク先記事自身（自己参照防止）")
            stats["skipped_self"] += 1
            time.sleep(SLEEP_SEC)
            continue

        # 重複チェック
        if has_drone_survey_links(content):
            print(f"  -> SKIP: 既にドローン測量リンクあり")
            stats["skipped_has_links"] += 1
            time.sleep(SLEEP_SEC)
            continue

        # リンクブロック挿入
        new_content, position = insert_related_block(content, related_block)
        print(f"  -> {position}")

        if args.apply:
            try:
                url = f"{base}/posts/{post_id}"
                wp_request(url, cfg, method="POST", data={"content": new_content})
                print(f"  -> UPDATED")
                stats["updated"] += 1
            except Exception as e:
                print(f"  -> ERROR: {e}")
                stats["errors"] += 1
        else:
            print(f"  -> DRY-RUN: 変更をスキップ")
            stats["updated"] += 1  # dry-runでは対象数としてカウント

        time.sleep(SLEEP_SEC)

    # サマリー
    print()
    print("=== 処理結果サマリー ===")
    print(f"  全記事数:           {stats['total']}")
    print(f"  更新{'予定' if args.dry_run else '完了'}:           {stats['updated']}")
    print(f"  スキップ(既存リンク): {stats['skipped_has_links']}")
    print(f"  スキップ(自己参照):   {stats['skipped_self']}")
    if stats["errors"]:
        print(f"  エラー:             {stats['errors']}")
    mode = "DRY-RUN" if args.dry_run else "APPLY"
    print(f"  モード:             {mode}")


if __name__ == "__main__":
    main()
