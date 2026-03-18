"""
LiteSpeed Cache パージモジュール

WordPress の LiteSpeed Cache プラグインのキャッシュパージを実行する。
tas/v1/purge-cache カスタムエンドポイント（Snippet #XX）経由で呼び出す。

Usage:
    from lib.litespeed_cache import purge_all, purge_url

    cfg = load_config()
    auth = get_wp_auth(cfg)
    base_url = get_wp_base_url(cfg)  # "https://tokaiair.com/wp-json"

    purge_all(base_url, auth)                    # 全キャッシュパージ
    purge_url(base_url, auth, "/drone-survey/")  # 特定URLパージ

仕組み:
    WordPress Code Snippets に登録した tas/v1/purge-cache エンドポイントが
    do_action('litespeed_purge_all') または litespeed_purge_url() を呼ぶ。
    LiteSpeed Cache プラグインが無効でもエラーにはならない（空振り）。

注意:
    - パージ失敗でもデプロイは中断しない（呼び出し元で警告のみ）
    - WAF ON 状態でも GET リクエストなのでブロックされない想定
    - POST fallback も用意（WAF設定次第）
"""

import json
import urllib.request
import urllib.error


def purge_all(base_url, auth, timeout=15):
    """全キャッシュをパージする。

    Args:
        base_url: WordPress REST API ベースURL（/wp/v2 なし）
            例: "https://tokaiair.com/wp-json"
        auth: Basic認証文字列（Base64エンコード済み）
        timeout: タイムアウト秒数

    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    url = f"{base_url}/tas/v1/purge-cache"
    return _do_purge(url, auth, {"action": "purge_all"}, timeout)


def purge_url(base_url, auth, target_url, timeout=15):
    """特定URLのキャッシュをパージする。

    Args:
        base_url: WordPress REST API ベースURL（/wp/v2 なし）
        auth: Basic認証文字列（Base64エンコード済み）
        target_url: パージ対象URL（相対パスまたは絶対URL）
        timeout: タイムアウト秒数

    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    url = f"{base_url}/tas/v1/purge-cache"
    return _do_purge(url, auth, {"action": "purge_url", "url": target_url}, timeout)


def _do_purge(url, auth, payload, timeout):
    """パージリクエストを実行する内部関数。

    Args:
        url: エンドポイントURL
        auth: Basic認証文字列
        payload: リクエストボディ
        timeout: タイムアウト秒数

    Returns:
        dict: {"success": True/False, "message": "..."}
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
            success = resp.get("success", False)
            message = resp.get("message", "不明")
            if success:
                print(f"  [Cache] パージ成功: {message}")
            else:
                print(f"  [Cache] パージ応答（非成功）: {message}")
            return {"success": success, "message": message}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        msg = f"HTTP {e.code}: {body}"
        print(f"  [Cache] パージ失敗: {msg}")
        return {"success": False, "message": msg}
    except Exception as e:
        msg = str(e)
        print(f"  [Cache] パージ失敗: {msg}")
        return {"success": False, "message": msg}
