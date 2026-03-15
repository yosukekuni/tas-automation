#!/usr/bin/env python3
"""
IndexNow Submit Script for tokaiair.com
Bing/Yandex にURL更新を即時通知する。

Usage:
    # 単一URL送信
    python indexnow_submit.py https://www.tokaiair.com/some-page/

    # 複数URL送信
    python indexnow_submit.py https://www.tokaiair.com/page1/ https://www.tokaiair.com/page2/

    # WordPress最近更新記事を自動取得して送信
    python indexnow_submit.py --wordpress --days 1

    # WordPress最近更新記事を取得（dry-run: 送信せず確認のみ）
    python indexnow_submit.py --wordpress --days 7 --dry-run
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ── ログ設定 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("indexnow")

# ── 定数 ──
CONFIG_PATH = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
HOST = "www.tokaiair.com"


def load_config():
    """automation_config.json を読み込む"""
    if not CONFIG_PATH.exists():
        log.error(f"設定ファイルが見つかりません: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    # IndexNow APIキー確認
    indexnow_cfg = config.get("indexnow", {})
    api_key = indexnow_cfg.get("api_key", "")
    if not api_key:
        log.error(
            "automation_config.json に indexnow.api_key が設定されていません。\n"
            '  → "indexnow": {"api_key": "YOUR_KEY"} を追加してください。\n'
            "  → キーは https://www.bing.com/indexnow で取得できます。"
        )
        sys.exit(1)

    return config


def submit_single(api_key: str, url: str) -> bool:
    """単一URLをIndexNowに送信"""
    params = {
        "url": url,
        "key": api_key,
    }
    try:
        resp = requests.get(INDEXNOW_ENDPOINT, params=params, timeout=30)
        if resp.status_code in (200, 202):
            log.info(f"OK ({resp.status_code}): {url}")
            return True
        else:
            log.warning(f"FAIL ({resp.status_code}): {url} - {resp.text[:200]}")
            return False
    except requests.RequestException as e:
        log.error(f"ERROR: {url} - {e}")
        return False


def submit_batch(api_key: str, urls: list[str]) -> bool:
    """複数URLをIndexNowに一括送信（POST）"""
    if not urls:
        log.info("送信するURLがありません。")
        return True

    # 単一URLの場合はGETで送信
    if len(urls) == 1:
        return submit_single(api_key, urls[0])

    payload = {
        "host": HOST,
        "key": api_key,
        "keyLocation": f"https://{HOST}/{api_key}.txt",
        "urlList": urls,
    }

    try:
        resp = requests.post(
            INDEXNOW_ENDPOINT,
            json=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=30,
        )
        if resp.status_code in (200, 202):
            log.info(f"一括送信OK ({resp.status_code}): {len(urls)}件")
            for u in urls:
                log.info(f"  - {u}")
            return True
        else:
            log.warning(
                f"一括送信FAIL ({resp.status_code}): {resp.text[:300]}"
            )
            return False
    except requests.RequestException as e:
        log.error(f"一括送信ERROR: {e}")
        return False


def fetch_recent_wp_urls(config: dict, days: int = 1) -> list[str]:
    """WordPress REST APIから最近更新された記事URLを取得"""
    wp_cfg = config.get("wordpress", {})
    base_url = wp_cfg.get("base_url", "")
    user = wp_cfg.get("user", "")
    app_password = wp_cfg.get("app_password", "")

    if not base_url:
        log.error("wordpress.base_url が設定されていません。")
        return []

    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%S")

    urls = []
    page = 1
    per_page = 100

    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "orderby": "modified",
            "order": "desc",
            "modified_after": since_iso,
            "status": "publish",
        }

        auth = None
        if user and app_password:
            auth = (user, app_password.replace(" ", ""))

        try:
            # 投稿を取得
            resp = requests.get(
                f"{base_url}/posts",
                params=params,
                auth=auth,
                timeout=30,
            )
            if resp.status_code != 200:
                log.warning(f"WordPress API応答エラー ({resp.status_code}): {resp.text[:200]}")
                break

            posts = resp.json()
            if not posts:
                break

            for post in posts:
                link = post.get("link", "")
                modified = post.get("modified_gmt", "")
                title = post.get("title", {}).get("rendered", "")
                if link:
                    urls.append(link)
                    log.info(f"  検出: {title[:50]} (更新: {modified}) → {link}")

            # 次ページがあるか
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1

        except requests.RequestException as e:
            log.error(f"WordPress API取得エラー: {e}")
            break

    # 固定ページも取得
    page = 1
    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "orderby": "modified",
            "order": "desc",
            "modified_after": since_iso,
            "status": "publish",
        }

        auth = None
        if user and app_password:
            auth = (user, app_password.replace(" ", ""))

        try:
            resp = requests.get(
                f"{base_url}/pages",
                params=params,
                auth=auth,
                timeout=30,
            )
            if resp.status_code != 200:
                break

            pages_data = resp.json()
            if not pages_data:
                break

            for pg in pages_data:
                link = pg.get("link", "")
                modified = pg.get("modified_gmt", "")
                title = pg.get("title", {}).get("rendered", "")
                if link:
                    urls.append(link)
                    log.info(f"  検出(固定): {title[:50]} (更新: {modified}) → {link}")

            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1

        except requests.RequestException as e:
            log.error(f"WordPress API取得エラー (固定ページ): {e}")
            break

    log.info(f"WordPress から {len(urls)} 件のURLを検出（過去{days}日間）")
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="IndexNow: tokaiair.com のURL更新をBing/Yandexに即時通知"
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="送信するURL（複数指定可）",
    )
    parser.add_argument(
        "--wordpress", "-w",
        action="store_true",
        help="WordPress REST APIから最近更新された記事を自動取得",
    )
    parser.add_argument(
        "--days", "-d",
        type=int,
        default=1,
        help="WordPressモード: 過去何日分を取得するか（デフォルト: 1）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="送信せずにURLリストのみ表示",
    )

    args = parser.parse_args()

    # URL指定もWordPressモードもない場合
    if not args.urls and not args.wordpress:
        parser.print_help()
        sys.exit(1)

    # 設定読み込み
    config = load_config()
    api_key = config["indexnow"]["api_key"]

    # URL収集
    urls = list(args.urls) if args.urls else []

    if args.wordpress:
        log.info(f"WordPress から過去{args.days}日間の更新記事を取得中...")
        wp_urls = fetch_recent_wp_urls(config, days=args.days)
        urls.extend(wp_urls)

    # 重複除去（順序維持）
    seen = set()
    unique_urls = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)
    urls = unique_urls

    if not urls:
        log.info("送信対象のURLがありません。")
        return

    log.info(f"送信対象: {len(urls)} 件")

    if args.dry_run:
        log.info("=== Dry-run モード（送信しません）===")
        for u in urls:
            log.info(f"  {u}")
        return

    # 送信
    success = submit_batch(api_key, urls)
    if success:
        log.info("IndexNow通知が完了しました。")
    else:
        log.warning("一部または全てのURL送信に失敗しました。")
        sys.exit(1)


if __name__ == "__main__":
    main()
