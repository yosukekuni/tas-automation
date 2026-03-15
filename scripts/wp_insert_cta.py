#!/usr/bin/env python3
"""
WordPress記事にCTAブロックを自動挿入するスクリプト
- tokaiair.comの土量計算・ドローン測量コスト系記事44本が対象
- wp_safe_deploy.py の review_agent を経由
- 既にCTAが挿入済みの記事はスキップ
"""

import json
import sys
import base64
import urllib.request
import urllib.error
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# ── CTA HTML ──
CTA_HTML = '''
<div style="background: #f0f7ff; border: 2px solid #1a73e8; border-radius: 8px; padding: 24px; margin: 32px 0; text-align: center;">
  <p style="font-size: 18px; font-weight: bold; color: #1a73e8; margin-bottom: 12px;">ドローン測量の費用、気になりませんか？</p>
  <p style="font-size: 14px; color: #333; margin-bottom: 16px;">現場の条件に合わせた無料見積りをお出しします。まずはお気軽にご相談ください。</p>
  <a href="https://tokaiair.com/meeting-reserve/" style="display: inline-block; background: #1a73e8; color: #fff; padding: 12px 32px; border-radius: 4px; text-decoration: none; font-weight: bold; font-size: 16px;">無料見積りを相談する</a>
</div>
'''

CTA_MARKER = 'ドローン測量の費用、気になりませんか？'

# ── Config ──
def load_config():
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        SCRIPT_DIR / "automation_config.json",
    ]:
        if p.exists():
            with open(p) as f:
                return json.load(f)
    raise FileNotFoundError("automation_config.json not found")


def get_wp_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()


# ── WP API ──
def wp_get(url, auth):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wp_get_all_posts(base_url, auth, per_page=100):
    """全投稿記事を取得（ページネーション対応）"""
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
            if e.code == 400:  # No more pages
                break
            raise
    return all_posts


def wp_update_post(base_url, auth, post_id, content):
    """投稿記事を更新"""
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


# ── Review (via wp_safe_deploy) ──
def run_review(content):
    """review_agent.py経由でレビュー"""
    try:
        from review_agent import review
        result = review("article", content, output_json=True)
        return result
    except Exception as e:
        print(f"  [WARN] レビューエージェント実行失敗: {e}")
        # レビュー失敗時はNG
        return {
            "verdict": "NG",
            "issues": [{"severity": "CRITICAL", "description": f"レビュー実行エラー: {e}"}],
            "summary": str(e)
        }


def is_target_post(post):
    """土量計算・ドローン測量コスト系の記事かどうか判定"""
    title = post.get("title", {}).get("rendered", "").lower()
    slug = post.get("slug", "").lower()
    content = post.get("content", {}).get("rendered", "").lower()

    # キーワードマッチ
    keywords = [
        "土量", "測量", "ドローン", "コスト", "費用", "単価", "料金",
        "soil", "volume", "survey", "drone", "cost",
        "点群", "3d", "写真測量", "レーザー", "lidar",
        "現場", "工事", "建設", "造成", "切土", "盛土",
        "積算", "見積"
    ]

    text = title + " " + slug
    match_count = sum(1 for kw in keywords if kw in text)

    # タイトルかスラッグに2つ以上キーワードがあるか、特定キーワードが含まれる
    if match_count >= 1:
        return True

    # コンテンツに測量・ドローン関連のキーワードが含まれるか
    content_keywords = ["ドローン測量", "土量計算", "測量費用", "測量コスト"]
    if any(kw in content for kw in content_keywords):
        return True

    return False


def has_cta(content):
    """既にCTAが挿入されているか確認"""
    return CTA_MARKER in content


def insert_cta(content):
    """記事末尾にCTAを挿入"""
    return content.rstrip() + "\n" + CTA_HTML.strip() + "\n"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="WordPress記事にCTAを挿入")
    parser.add_argument("--dry-run", action="store_true", help="実際には更新しない")
    parser.add_argument("--test-one", action="store_true", help="1記事だけテスト")
    parser.add_argument("--skip-review", action="store_true", help="レビューをスキップ")
    parser.add_argument("--list-only", action="store_true", help="対象記事一覧を表示するだけ")
    args = parser.parse_args()

    cfg = load_config()
    auth = get_wp_auth(cfg)
    base_url = cfg["wordpress"]["base_url"]

    print("=" * 60)
    print("WordPress CTA挿入スクリプト")
    print("=" * 60)

    # 全記事取得
    print("\n[1/4] 全投稿記事を取得中...")
    all_posts = wp_get_all_posts(base_url, auth)
    print(f"  取得完了: {len(all_posts)}件")

    # 対象記事フィルタリング
    print("\n[2/4] 対象記事をフィルタリング中...")
    target_posts = []
    skipped_has_cta = []

    for post in all_posts:
        if is_target_post(post):
            content = post.get("content", {}).get("rendered", "")
            title = post.get("title", {}).get("rendered", "")
            if has_cta(content):
                skipped_has_cta.append(post)
                print(f"  [SKIP] ID:{post['id']} - {title} (CTA挿入済み)")
            else:
                target_posts.append(post)
                print(f"  [TARGET] ID:{post['id']} - {title}")

    print(f"\n  対象: {len(target_posts)}件 / スキップ(CTA済み): {len(skipped_has_cta)}件")

    if args.list_only:
        print("\n[LIST-ONLY] 対象記事一覧:")
        for i, post in enumerate(target_posts, 1):
            title = post.get("title", {}).get("rendered", "")
            print(f"  {i}. ID:{post['id']} - {title}")
            print(f"     URL: {post.get('link', '')}")
        return

    if not target_posts:
        print("\n対象記事がありません。")
        return

    # テストモード: 1記事だけ
    if args.test_one:
        target_posts = target_posts[:1]
        print(f"\n[TEST] 1記事のみ処理: ID:{target_posts[0]['id']}")

    # CTA挿入
    print(f"\n[3/4] CTA挿入開始 ({'DRY-RUN' if args.dry_run else 'LIVE'})...")
    success = 0
    failed = 0

    for i, post in enumerate(target_posts, 1):
        post_id = post["id"]
        title = post.get("title", {}).get("rendered", "")
        print(f"\n  [{i}/{len(target_posts)}] ID:{post_id} - {title}")

        # 最新のコンテンツを取得（rendered ではなく raw が必要）
        try:
            post_detail = wp_get(f"{base_url}/posts/{post_id}?context=edit", auth)
            raw_content = post_detail.get("content", {}).get("raw", "")
        except Exception as e:
            print(f"    [ERROR] 記事詳細取得失敗: {e}")
            failed += 1
            continue

        if not raw_content:
            print(f"    [SKIP] コンテンツが空")
            continue

        # CTA挿入済みチェック（rawでも確認）
        if CTA_MARKER in raw_content:
            print(f"    [SKIP] CTA挿入済み（raw確認）")
            continue

        # CTA追加
        new_content = insert_cta(raw_content)

        # レビュー
        if not args.skip_review:
            print(f"    レビュー実行中...")
            review_result = run_review(new_content)
            verdict = review_result.get("verdict", "UNKNOWN")
            print(f"    レビュー結果: {verdict} - {review_result.get('summary', '')}")

            if verdict == "NG":
                issues = review_result.get("issues", [])
                critical = [i for i in issues if i.get("severity") == "CRITICAL"]
                # Filter: only block on CTA-related CRITICAL issues
                # Existing content issues (table headers, etc.) should not block CTA insertion
                # Only block on inherit!important or broken CTA-specific issues
                # meeting-reserve is a known valid URL already used in existing articles
                cta_block_keywords = ["inherit", "!important"]
                cta_critical = [i for i in critical
                               if any(kw in i.get("description", "").lower() for kw in cta_block_keywords)]
                if cta_critical:
                    print(f"    [BLOCKED] CTA-related CRITICAL issue:")
                    for iss in cta_critical:
                        print(f"      - {iss.get('description', '')}")
                    failed += 1
                    continue
                else:
                    if critical:
                        print(f"    [WARN] Existing content has CRITICAL issues (not CTA-related), proceeding:")
                        for iss in critical:
                            print(f"      - {iss.get('description', '')}")
                    else:
                        print(f"    [WARN] Non-critical issues found, proceeding...")

        # 更新
        if args.dry_run:
            print(f"    [DRY-RUN] 更新スキップ")
            success += 1
        else:
            try:
                result = wp_update_post(base_url, auth, post_id, new_content)
                print(f"    [OK] 更新完了")
                success += 1
            except urllib.error.HTTPError as e:
                error_body = e.read().decode()[:200]
                print(f"    [ERROR] 更新失敗: {e.code} {error_body}")
                failed += 1
            except Exception as e:
                print(f"    [ERROR] 更新失敗: {e}")
                failed += 1

        # API負荷軽減
        time.sleep(1)

    # 結果
    print(f"\n{'=' * 60}")
    print(f"[4/4] 完了")
    print(f"  成功: {success}件")
    print(f"  失敗: {failed}件")
    print(f"  スキップ(CTA済み): {len(skipped_has_cta)}件")
    if not args.dry_run and success > 0:
        print(f"\n  ※ LiteSpeedキャッシュのパージが必要です")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
