#!/usr/bin/env python3
"""
地域別LP 41ページ + 関連ページのリンク切れ一括修正

テンプレート内のリンクURLと実際のWordPressページslugが不一致だった問題を修正。
既にデプロイ済みの全ページのHTMLコンテンツ内のhref属性を正しいURLに置換する。

修正対象:
  /earthwork-calculator/     → /tools/earthwork/calculator/
  /cost-comparison/          → /drone-survey-cost-comparison/
  /uav-survey/               → /services/uav-survey/
  /3d-measurement/           → /services/3d-measurement/
  /case-library/             → /case-library/cases/  (事例一覧リンクのみ)
  /statistics/               → /drone-survey-statistics/
  /market-report/            → /drone-survey-market-report/

WAF対策: wp_safe_deploy.py の WAF context manager を使用
キャッシュ: 修正完了後に LiteSpeed キャッシュパージ
IndexNow: 修正ページのURLを一括送信

Usage:
    python3 fix_area_lp_links.py --dry-run    # 変更内容確認のみ
    python3 fix_area_lp_links.py              # 実行
"""

import json
import sys
import re
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from lib.config import load_config, get_wp_auth, get_wp_api_url

# ── リンク置換マッピング ──
# href属性内で置換するパターン (old → new)
# 注意: 順序が重要（より具体的なパターンを先に）
LINK_REPLACEMENTS = [
    # 費用比較シミュレーター
    ('href="/cost-comparison/"', 'href="/drone-survey-cost-comparison/"'),
    ("href='/cost-comparison/'", "href='/drone-survey-cost-comparison/'"),
    # 実績データ統計
    ('href="/statistics/"', 'href="/drone-survey-statistics/"'),
    ("href='/statistics/'", "href='/drone-survey-statistics/'"),
    # 市場レポート
    ('href="/market-report/"', 'href="/drone-survey-market-report/"'),
    ("href='/market-report/'", "href='/drone-survey-market-report/'"),
    # 土量計算ツール
    ('href="/earthwork-calculator/"', 'href="/tools/earthwork/calculator/"'),
    ("href='/earthwork-calculator/'", "href='/tools/earthwork/calculator/'"),
    # ドローン測量サービス（/services/ プレフィックスなし → あり）
    # 注意: /services/uav-survey/ は正しいのでスキップするため、否定先読みで限定
    ('href="/uav-survey/"', 'href="/services/uav-survey/"'),
    ("href='/uav-survey/'", "href='/services/uav-survey/'"),
    # 3次元計測
    ('href="/3d-measurement/"', 'href="/services/3d-measurement/"'),
    ("href='/3d-measurement/'", "href='/services/3d-measurement/'"),
    # 事例一覧（/case-library/ 単体でリンクされている場合 → /case-library/cases/）
    # ただし /case-library/cases/ や /case-library/pricing/ 等は変更しない
]

# /case-library/ のみで終わるリンクを /case-library/cases/ に変換（子パスは除外）
CASE_LIBRARY_PATTERN = re.compile(r'href="(/case-library/)"')
CASE_LIBRARY_REPLACEMENT = 'href="/case-library/cases/"'

# 絶対URL版も対応
ABSOLUTE_LINK_REPLACEMENTS = [
    ('href="https://tokaiair.com/cost-comparison/"', 'href="https://tokaiair.com/drone-survey-cost-comparison/"'),
    ('href="https://tokaiair.com/statistics/"', 'href="https://tokaiair.com/drone-survey-statistics/"'),
    ('href="https://tokaiair.com/earthwork-calculator/"', 'href="https://tokaiair.com/tools/earthwork/calculator/"'),
    ('href="https://tokaiair.com/uav-survey/"', 'href="https://tokaiair.com/services/uav-survey/"'),
    ('href="https://tokaiair.com/3d-measurement/"', 'href="https://tokaiair.com/services/3d-measurement/"'),
    ('href="https://www.tokaiair.com/cost-comparison/"', 'href="https://tokaiair.com/drone-survey-cost-comparison/"'),
    ('href="https://www.tokaiair.com/statistics/"', 'href="https://tokaiair.com/drone-survey-statistics/"'),
    ('href="https://www.tokaiair.com/earthwork-calculator/"', 'href="https://tokaiair.com/tools/earthwork/calculator/"'),
    ('href="https://www.tokaiair.com/uav-survey/"', 'href="https://tokaiair.com/services/uav-survey/"'),
    ('href="https://www.tokaiair.com/3d-measurement/"', 'href="https://tokaiair.com/services/3d-measurement/"'),
]


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def get_all_pages(cfg):
    """WordPress REST APIで全固定ページ(publish)を取得"""
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)
    pages = []
    page_num = 1

    while True:
        url = f"{base_url}/pages?per_page=100&page={page_num}&status=publish"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "TAS-Automation/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data:
                    break
                pages.extend(data)
                total_pages = int(r.headers.get("X-WP-TotalPages", 1))
                if page_num >= total_pages:
                    break
                page_num += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise

    return pages


def get_all_posts(cfg):
    """WordPress REST APIで全投稿(publish)を取得"""
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)
    posts = []
    page_num = 1

    while True:
        url = f"{base_url}/posts?per_page=100&page={page_num}&status=publish"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "TAS-Automation/1.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data:
                    break
                posts.extend(data)
                total_pages = int(r.headers.get("X-WP-TotalPages", 1))
                if page_num >= total_pages:
                    break
                page_num += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise

    return posts


def fix_links(html):
    """HTMLコンテンツ内のリンクを修正。(修正後HTML, 変更リスト) を返す"""
    original = html
    changes = []

    # 相対URLの置換
    for old, new in LINK_REPLACEMENTS:
        if old in html:
            count = html.count(old)
            html = html.replace(old, new)
            changes.append(f"  {old} -> {new} ({count}件)")

    # /case-library/ 単体リンクのみ変換
    matches = CASE_LIBRARY_PATTERN.findall(html)
    if matches:
        html = CASE_LIBRARY_PATTERN.sub(CASE_LIBRARY_REPLACEMENT, html)
        changes.append(f'  /case-library/ -> /case-library/cases/ ({len(matches)}件)')

    # 絶対URLの置換
    for old, new in ABSOLUTE_LINK_REPLACEMENTS:
        if old in html:
            count = html.count(old)
            html = html.replace(old, new)
            changes.append(f"  {old} -> {new} ({count}件)")

    return html, changes


def update_content(cfg, content_id, content_type, new_content):
    """WordPress REST APIでコンテンツを更新"""
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)
    endpoint = "posts" if content_type == "post" else "pages"

    data = json.dumps({"content": new_content}).encode()
    req = urllib.request.Request(
        f"{base_url}/{endpoint}/{content_id}",
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def submit_indexnow(cfg, urls):
    """IndexNowで修正ページURLを送信"""
    api_key = cfg.get("indexnow", {}).get("api_key", "")
    if not api_key:
        log("IndexNow APIキー未設定", "WARN")
        return

    payload = {
        "host": "www.tokaiair.com",
        "key": api_key,
        "keyLocation": f"https://www.tokaiair.com/{api_key}.txt",
        "urlList": urls
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            log(f"IndexNow送信完了: {r.getcode()}, {len(urls)}件")
    except urllib.error.HTTPError as e:
        if e.code == 202:
            log(f"IndexNow送信完了: 202 Accepted, {len(urls)}件")
        else:
            log(f"IndexNow送信エラー: {e.code}", "WARN")
    except Exception as e:
        log(f"IndexNow送信失敗: {e}", "WARN")


def purge_cache(cfg):
    """LiteSpeedキャッシュパージ"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR / "lib"))
        from litespeed_cache import purge_all
        auth = get_wp_auth(cfg)
        wp_base = get_wp_api_url(cfg).replace("/wp/v2", "")
        result = purge_all(wp_base, auth)
        if result["success"]:
            log("LiteSpeedキャッシュパージ完了")
        else:
            log(f"キャッシュパージ警告: {result['message']}", "WARN")
    except Exception as e:
        log(f"キャッシュパージスキップ: {e}", "WARN")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="地域LP + 関連ページのリンク切れ一括修正")
    parser.add_argument("--dry-run", action="store_true", help="変更内容確認のみ（更新しない）")
    parser.add_argument("--no-indexnow", action="store_true", help="IndexNow送信しない")
    args = parser.parse_args()

    cfg = load_config()
    dry_run = args.dry_run

    log("=" * 60)
    log("地域別LP + 関連ページ リンク切れ一括修正")
    log(f"モード: {'DRY-RUN' if dry_run else 'LIVE FIX'}")
    log("=" * 60)

    # 全コンテンツ取得
    log("WordPress全ページ取得中...")
    wp_pages = get_all_pages(cfg)
    log(f"  固定ページ: {len(wp_pages)}件")

    log("WordPress全投稿取得中...")
    wp_posts = get_all_posts(cfg)
    log(f"  投稿: {len(wp_posts)}件")

    all_content = []
    for p in wp_pages:
        all_content.append({
            "id": p["id"],
            "type": "page",
            "title": p["title"]["rendered"],
            "content": p["content"]["rendered"],
            "link": p.get("link", ""),
        })
    for p in wp_posts:
        all_content.append({
            "id": p["id"],
            "type": "post",
            "title": p["title"]["rendered"],
            "content": p["content"]["rendered"],
            "link": p.get("link", ""),
        })

    log(f"合計: {len(all_content)}件のコンテンツを検査")
    log("")

    # WAF OFF → 修正 → WAF ON
    waf_ctx = None
    if not dry_run:
        try:
            from wp_safe_deploy import _get_waf_context
            waf_ctx = _get_waf_context(cfg)
        except Exception:
            from contextlib import nullcontext
            waf_ctx = nullcontext(False)
    else:
        from contextlib import nullcontext
        waf_ctx = nullcontext(False)

    fixed_count = 0
    fixed_urls = []
    fix_log = []

    with waf_ctx:
        for item in all_content:
            fixed_html, changes = fix_links(item["content"])

            if not changes:
                continue

            log(f"[{item['type']}] ID:{item['id']} - {item['title']}")
            for c in changes:
                log(f"  {c}")

            if dry_run:
                log("  [DRY-RUN] 更新スキップ")
                fix_log.append({
                    "id": item["id"],
                    "type": item["type"],
                    "title": item["title"],
                    "changes": changes,
                    "status": "dry-run",
                })
            else:
                try:
                    update_content(cfg, item["id"], item["type"], fixed_html)
                    log(f"  更新完了")
                    fix_log.append({
                        "id": item["id"],
                        "type": item["type"],
                        "title": item["title"],
                        "changes": changes,
                        "status": "success",
                    })
                    if item["link"]:
                        fixed_urls.append(item["link"])
                    fixed_count += 1
                    time.sleep(0.3)
                except Exception as e:
                    log(f"  更新失敗: {e}", "ERROR")
                    fix_log.append({
                        "id": item["id"],
                        "type": item["type"],
                        "title": item["title"],
                        "changes": changes,
                        "status": f"failed: {e}",
                    })

            log("")

    # キャッシュパージ
    if not dry_run and fixed_count > 0:
        purge_cache(cfg)

    # IndexNow送信
    if not dry_run and not args.no_indexnow and fixed_urls:
        submit_indexnow(cfg, fixed_urls)

    # ログ保存
    log_path = SCRIPT_DIR / "area_lp_link_fix_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(fix_log, f, ensure_ascii=False, indent=2)

    # サマリー
    log("=" * 60)
    log("修正完了サマリー")
    log("=" * 60)
    log(f"  検査対象: {len(all_content)}件")
    log(f"  修正対象: {len(fix_log)}件")
    log(f"  更新成功: {fixed_count}件")
    log(f"  IndexNow送信: {len(fixed_urls)}件")
    log(f"  ログ: {log_path}")


if __name__ == "__main__":
    main()
