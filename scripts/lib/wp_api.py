"""
WordPress REST API 共通モジュール

ページ・投稿の取得・更新を提供する。
wp_safe_deploy.py / wp_replace_cta.py / lp_stats_sync.py から抽出。

Usage:
    from lib.config import load_config, get_wp_auth, get_wp_api_url
    from lib.wp_api import wp_get_page, wp_update_post, wp_get_all_posts

    cfg = load_config()
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)

    page = wp_get_page(base_url, auth, page_id=212)
    posts = wp_get_all_posts(base_url, auth)
    wp_update_post(base_url, auth, post_id=123, content="<p>新しい内容</p>")

注意:
    - WordPress への書き込みは wp_safe_deploy.py 経由で行うのがルール。
      このモジュールは低レベルAPI。wp_safe_deploy.py の内部や、
      読み取り専用の処理で使う。
    - CSSで inherit!important 禁止（CLAUDE.md ルール）。
"""

import json
import time
import urllib.request
import urllib.error

from lib.retry import urlopen_with_retry


def _wp_request(url, auth, data=None, method=None, timeout=30):
    """WordPress REST API への共通リクエスト処理。

    Args:
        url: API エンドポイント URL
        auth: get_wp_auth() の戻り値（Base64文字列）
        data: POST/PUT する辞書（省略時は GET）
        method: HTTP メソッド（省略時は data の有無で自動判定）
        timeout: タイムアウト秒数

    Returns:
        dict: API レスポンス

    Raises:
        urllib.error.HTTPError: API エラー
    """
    headers = {"Authorization": f"Basic {auth}"}

    if data is not None:
        encoded = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            url, data=encoded, headers=headers,
            method=method or "POST",
        )
    else:
        req = urllib.request.Request(url, headers=headers, method=method or "GET")

    with urlopen_with_retry(req, timeout=timeout) as r:
        return json.loads(r.read())


def wp_get_page(base_url, auth, page_id, context="edit"):
    """WordPress ページを取得する。

    Args:
        base_url: WP REST API ベースURL（例: "https://tokaiair.com/wp-json/wp/v2"）
        auth: get_wp_auth() の戻り値
        page_id: ページID
        context: "edit"（生HTML）or "view"（レンダリング済み）

    Returns:
        dict: ページデータ。取得失敗時は None。
    """
    url = f"{base_url}/pages/{page_id}?context={context}"
    try:
        return _wp_request(url, auth)
    except urllib.error.HTTPError as e:
        print(f"  WP GET page error: {e.code} {e.read().decode()[:200]}")
        return None


def wp_get_post(base_url, auth, post_id, context="edit"):
    """WordPress 投稿を取得する。

    Args:
        base_url: WP REST API ベースURL
        auth: get_wp_auth() の戻り値
        post_id: 投稿ID
        context: "edit" or "view"

    Returns:
        dict: 投稿データ。取得失敗時は None。
    """
    url = f"{base_url}/posts/{post_id}?context={context}"
    try:
        return _wp_request(url, auth)
    except urllib.error.HTTPError as e:
        print(f"  WP GET post error: {e.code} {e.read().decode()[:200]}")
        return None


def wp_update_post(base_url, auth, post_id, content, extra_fields=None):
    """WordPress 投稿を更新する。

    Args:
        base_url: WP REST API ベースURL
        auth: get_wp_auth() の戻り値
        post_id: 投稿ID
        content: 更新する HTML コンテンツ
        extra_fields: 追加で更新するフィールド辞書（title, excerpt 等）

    Returns:
        dict: 更新後の投稿データ

    Raises:
        urllib.error.HTTPError: 更新失敗時
    """
    data = {"content": content}
    if extra_fields:
        data.update(extra_fields)

    url = f"{base_url}/posts/{post_id}"
    return _wp_request(url, auth, data=data, method="POST")


def wp_update_page(base_url, auth, page_id, content, extra_fields=None):
    """WordPress ページを更新する。

    Args:
        base_url: WP REST API ベースURL
        auth: get_wp_auth() の戻り値
        page_id: ページID
        content: 更新する HTML コンテンツ
        extra_fields: 追加で更新するフィールド辞書

    Returns:
        dict: 更新後のページデータ

    Raises:
        urllib.error.HTTPError: 更新失敗時
    """
    data = {"content": content}
    if extra_fields:
        data.update(extra_fields)

    url = f"{base_url}/pages/{page_id}"
    return _wp_request(url, auth, data=data, method="POST")


def wp_get_all_posts(base_url, auth, per_page=100, status="publish",
                     post_type="posts", extra_params=None):
    """WordPress の全投稿をページネーションで取得する。

    Args:
        base_url: WP REST API ベースURL
        auth: get_wp_auth() の戻り値
        per_page: 1ページあたりの件数（最大100）
        status: 投稿ステータス（"publish", "draft" 等）
        post_type: "posts" or "pages"
        extra_params: 追加クエリパラメータ辞書

    Returns:
        list[dict]: 全投稿のリスト
    """
    all_items = []
    page = 1

    while True:
        url = f"{base_url}/{post_type}?per_page={per_page}&page={page}&status={status}"
        if extra_params:
            for k, v in extra_params.items():
                url += f"&{k}={v}"

        try:
            items = _wp_request(url, auth)
            if not items:
                break
            all_items.extend(items)
            if len(items) < per_page:
                break
            page += 1
            time.sleep(0.5)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                # ページ範囲外
                break
            raise

    return all_items


def wp_get_all_pages(base_url, auth, per_page=100, status="publish"):
    """WordPress の全ページを取得する（wp_get_all_posts のエイリアス）。

    Args:
        base_url: WP REST API ベースURL
        auth: get_wp_auth() の戻り値
        per_page: 1ページあたりの件数
        status: ページステータス

    Returns:
        list[dict]: 全ページのリスト
    """
    return wp_get_all_posts(base_url, auth, per_page=per_page,
                            status=status, post_type="pages")
