#!/usr/bin/env python3
"""
WordPress記事のCTAブロック一括差し替えスクリプト
- meeting-reserve を含む既存CTAブロックを検出
- リンク先・ボタンテキスト・説明テキストを置換
- 既存CTA が見つからない記事はスキップ
"""

import json
import re
import base64
import urllib.request
import urllib.error
import time
from pathlib import Path

# ── Config ──
CONFIG_PATHS = [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    Path(__file__).parent / "automation_config.json",
]

# ── 新CTA HTML ──
NEW_CTA_HTML = '''<div style="background: #f0f7ff; border: 2px solid #1a73e8; border-radius: 8px; padding: 24px; margin: 32px 0; text-align: center;">
  <p style="font-size: 18px; font-weight: bold; color: #1a73e8; margin-bottom: 12px;">ドローン測量の費用、気になりませんか？</p>
  <p style="font-size: 14px; color: #333; margin-bottom: 16px;">現場の条件に合わせた概算費用をお伝えします。お気軽にお問い合わせください。</p>
  <a href="https://tokaiair.com/contact/" style="display: inline-block; background: #1a73e8; color: #fff; padding: 12px 32px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 16px;">費用について問い合わせる</a>
</div>'''


def load_config():
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p) as f:
                return json.load(f)
    raise FileNotFoundError("automation_config.json not found")


def get_wp_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()


def wp_get(url, auth):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wp_get_all_posts(base_url, auth, per_page=100):
    all_posts = []
    page = 1
    while True:
        url = f"{base_url}/posts?per_page={per_page}&page={page}&status=publish"
        try:
            posts = wp_get(url, auth)
            if not posts:
                break
            all_posts.extend(posts)
            if len(posts) < per_page:
                break
            page += 1
            time.sleep(0.5)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
    return all_posts


def wp_update_post(base_url, auth, post_id, content):
    data = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{base_url}/posts/{post_id}",
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def find_and_replace_cta(content):
    """
    meeting-reserve を含む CTA div ブロックを検出し、新CTAに置換。
    返り値: (new_content, replaced) — replaced=True なら置換実行済み
    """
    # meeting-reserve を含む div ブロック全体をマッチ
    # パターン: <div ...>...(meeting-reserve を含む)...</div>
    # 最外側の div を非貪欲にマッチさせる
    pattern = r'<div[^>]*>[\s\S]*?meeting-reserve[\s\S]*?</div>'

    match = re.search(pattern, content)
    if not match:
        return content, False

    old_block = match.group(0)
    new_content = content.replace(old_block, NEW_CTA_HTML)

    # 置換が実際に行われたか確認
    if new_content == content:
        return content, False

    return new_content, True


def main():
    cfg = load_config()
    auth = get_wp_auth(cfg)
    base_url = cfg["wordpress"]["base_url"]

    print("=" * 60)
    print("WordPress CTA差し替えスクリプト")
    print("  meeting-reserve → contact")
    print("  無料見積りを相談する → 費用について問い合わせる")
    print("=" * 60)

    # 全記事取得
    print("\n[1/3] 全投稿記事を取得中...")
    all_posts = wp_get_all_posts(base_url, auth)
    print(f"  取得完了: {len(all_posts)}件")

    # 各記事をチェック＆置換
    print("\n[2/3] CTA差し替え実行中...")
    success = 0
    failed = 0
    skipped = 0
    already_new = 0
    results = []

    for i, post in enumerate(all_posts):
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", "")
        rendered = post.get("content", {}).get("rendered", "")

        # まず rendered でざっくり meeting-reserve 有無チェック
        if "meeting-reserve" not in rendered:
            # 新CTAが既にある場合
            if "tokaiair.com/contact/" in rendered and "費用について問い合わせる" in rendered:
                already_new += 1
            else:
                skipped += 1
            continue

        # raw コンテンツを取得
        try:
            post_detail = wp_get(f"{base_url}/posts/{post_id}?context=edit", auth)
            raw_content = post_detail.get("content", {}).get("raw", "")
        except Exception as e:
            print(f"  [ERROR] ID:{post_id} {title} - 詳細取得失敗: {e}")
            failed += 1
            results.append({"id": post_id, "title": title, "status": "ERROR", "detail": str(e)})
            continue

        if "meeting-reserve" not in raw_content:
            skipped += 1
            continue

        # CTA置換
        new_content, replaced = find_and_replace_cta(raw_content)

        if not replaced:
            print(f"  [SKIP] ID:{post_id} {title} - CTAブロック検出失敗（パターン不一致）")
            skipped += 1
            results.append({"id": post_id, "title": title, "status": "SKIP", "detail": "パターン不一致"})
            continue

        # 二重チェック: inherit!important が含まれていないか
        if "inherit" in new_content and "!important" in new_content:
            print(f"  [BLOCKED] ID:{post_id} {title} - inherit!important 検出")
            failed += 1
            results.append({"id": post_id, "title": title, "status": "BLOCKED"})
            continue

        # 更新
        try:
            wp_update_post(base_url, auth, post_id, new_content)
            print(f"  [OK] ID:{post_id} {title}")
            success += 1
            results.append({"id": post_id, "title": title, "status": "OK"})
        except urllib.error.HTTPError as e:
            error_body = e.read().decode()[:200]
            print(f"  [ERROR] ID:{post_id} {title} - {e.code}: {error_body}")
            failed += 1
            results.append({"id": post_id, "title": title, "status": "ERROR", "detail": f"{e.code}"})
        except Exception as e:
            print(f"  [ERROR] ID:{post_id} {title} - {e}")
            failed += 1
            results.append({"id": post_id, "title": title, "status": "ERROR", "detail": str(e)})

        time.sleep(1)

    # 結果サマリー
    print(f"\n{'=' * 60}")
    print(f"[3/3] 完了")
    print(f"  成功: {success}件")
    print(f"  失敗: {failed}件")
    print(f"  スキップ(CTA無し): {skipped}件")
    print(f"  既に新CTA: {already_new}件")
    print(f"  合計: {len(all_posts)}件")

    if success > 0:
        print(f"\n  ※ LiteSpeedキャッシュのパージが必要です")

    # 詳細結果
    if results:
        print(f"\n--- 処理詳細 ---")
        for r in results:
            print(f"  ID:{r['id']} [{r['status']}] {r['title']}")

    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
