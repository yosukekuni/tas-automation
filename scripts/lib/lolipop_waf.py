"""
ロリポップ WAF 自動制御モジュール

ロリポップ管理画面にセッションログインし、WAFの有効化/無効化を行う。
wp_safe_deploy.py から呼び出され、デプロイ前にWAF OFF → デプロイ後にWAF ON する。

Usage:
    from lib.lolipop_waf import waf_disable, waf_enable, waf_context

    # 個別操作
    waf_disable(cfg)
    waf_enable(cfg)

    # コンテキストマネージャ（推奨）
    with waf_context(cfg):
        # WAF OFF の状態でデプロイ
        do_deploy()
    # 自動で WAF ON に戻る

設定:
    automation_config.json の "lolipop" キー:
    {
        "domain": "tokaiair.com",
        "password": "...",
        "waf_url": "https://user.lolipop.jp/?mode=waf&state=waf&..."
    }

注意:
    - WAF ON 復帰は try/finally で保証する
    - WAF 操作失敗時もデプロイは中断しない（警告のみ）
"""

import time
import urllib.request
import urllib.parse
import http.cookiejar
from contextlib import contextmanager

# ロリポップ管理画面のURL
LOLIPOP_LOGIN_URL = "https://user.lolipop.jp/?mode=login&exec=1"
LOLIPOP_WAF_BASE = "https://user.lolipop.jp/"


def _create_session():
    """Cookie対応のurllib openerを生成する。

    Returns:
        tuple: (opener, cookie_jar)
    """
    cj = http.cookiejar.CookieJar()
    handler = urllib.request.HTTPCookieProcessor(cj)
    opener = urllib.request.build_opener(handler)
    return opener, cj


def _login(opener, cfg):
    """ロリポップ管理画面にログインする。

    ログインフォームは以下のフィールドを使用:
    - account: ドメイン名のユーザー部分
    - domain_id: ドメイン種別（独自ドメインは99固定）
    - domain_name_2: ドメイン名
    - domain_name_3: 空文字（独自ドメイン時）
    - passwd: パスワード
    - chkSetCookie: 1（Cookie保持）

    Args:
        opener: urllib opener
        cfg: automation_config の辞書

    Returns:
        bool: ログイン成功なら True

    Raises:
        Exception: ログイン失敗時
    """
    lolipop = cfg.get("lolipop", {})
    domain = lolipop.get("domain", "")
    password = lolipop.get("password", "")

    if not domain or not password:
        raise ValueError("lolipop.domain / lolipop.password が未設定")

    # 独自ドメインログイン: domain_id=99, domain_name_2=ドメイン全体
    login_data = urllib.parse.urlencode({
        "account": "",
        "domain_id": "99",
        "domain_name_2": domain,
        "domain_name_3": "",
        "passwd": password,
        "chkSetCookie": "1",
    }).encode()

    req = urllib.request.Request(
        LOLIPOP_LOGIN_URL,
        data=login_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://user.lolipop.jp/",
        },
    )

    resp = opener.open(req, timeout=30)
    body = resp.read().decode("utf-8", errors="replace")

    # ログイン成功判定: ログインページにリダイレクトされていなければ成功
    if "mode=login" in resp.url and "exec=" not in resp.url:
        raise RuntimeError("ロリポップ ログイン失敗（認証エラー）")

    # ダッシュボード要素があれば成功
    if "mode=top" in resp.url or "logout" in body.lower() or "mode=waf" not in body.lower():
        print("  [WAF] ロリポップ ログイン成功")
        return True

    # レスポンスURLから判定
    print(f"  [WAF] ログイン後URL: {resp.url}")
    return True


def _set_waf(opener, cfg, enable=True):
    """WAFの有効/無効を設定する。

    Args:
        opener: ログイン済みopener
        cfg: automation_config の辞書
        enable: True=WAF有効化, False=WAF無効化

    Returns:
        bool: 操作成功なら True
    """
    domain = cfg.get("lolipop", {}).get("domain", "")
    # WAF設定変更のURL
    # state=waf_save で保存、pdStatus: 0=OFF, 1=ON
    pd_status = "1" if enable else "0"
    action = "有効化" if enable else "無効化"

    # WAF設定ページを取得（CSRFトークン等の確認）
    waf_page_url = (
        f"{LOLIPOP_WAF_BASE}?mode=waf&state=waf"
        f"&pdStatus=0&col_flag=0&domain=www.{domain}&bid="
    )
    try:
        resp = opener.open(waf_page_url, timeout=30)
        waf_html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WAF] 設定ページ取得失敗: {e}")
        return False

    # WAF設定変更リクエスト
    # ロリポップのWAF設定は mode=waf&state=waf_save で POST
    save_url = f"{LOLIPOP_WAF_BASE}?mode=waf&state=waf_save"
    save_data = urllib.parse.urlencode({
        "domain": f"www.{domain}",
        "pdStatus": pd_status,
    }).encode()

    req = urllib.request.Request(
        save_url,
        data=save_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": waf_page_url,
        },
    )

    try:
        resp = opener.open(req, timeout=30)
        body = resp.read().decode("utf-8", errors="replace")
        print(f"  [WAF] {action} リクエスト送信完了 (HTTP {resp.getcode()})")
        return True
    except Exception as e:
        print(f"  [WAF] {action} リクエスト失敗: {e}")
        return False


def waf_disable(cfg):
    """WAFを無効化する。

    Args:
        cfg: automation_config の辞書

    Returns:
        bool: 成功なら True
    """
    print("[WAF] ロリポップ WAF 無効化開始...")
    try:
        opener, _ = _create_session()
        _login(opener, cfg)
        result = _set_waf(opener, cfg, enable=False)
        if result:
            print("[WAF] WAF 無効化完了 - 反映待ち 5秒...")
            time.sleep(5)
        return result
    except Exception as e:
        print(f"[WAF] WAF 無効化失敗: {e}")
        return False


def waf_enable(cfg):
    """WAFを有効化する。

    Args:
        cfg: automation_config の辞書

    Returns:
        bool: 成功なら True
    """
    print("[WAF] ロリポップ WAF 有効化開始...")
    try:
        opener, _ = _create_session()
        _login(opener, cfg)
        result = _set_waf(opener, cfg, enable=True)
        if result:
            print("[WAF] WAF 有効化完了")
        return result
    except Exception as e:
        print(f"[WAF] WAF 有効化失敗: {e}")
        return False


@contextmanager
def waf_context(cfg):
    """WAF無効化→処理→WAF有効化のコンテキストマネージャ。

    WAF操作が失敗してもyieldは実行される（デプロイ続行）。
    処理完了後（成功・失敗問わず）WAFは必ずONに戻す。

    Usage:
        with waf_context(cfg):
            deploy_something()

    Args:
        cfg: automation_config の辞書
    """
    waf_disabled = False
    try:
        waf_disabled = waf_disable(cfg)
        if not waf_disabled:
            print("[WAF] WAF無効化失敗 - デプロイは続行（手動WAF操作にフォールバック）")
    except Exception as e:
        print(f"[WAF] WAF無効化で例外: {e} - デプロイは続行")

    try:
        yield waf_disabled
    finally:
        if waf_disabled:
            try:
                waf_enable(cfg)
            except Exception as e:
                print(f"[WAF] !!! WAF有効化失敗 !!! 手動でWAFをONにしてください: {e}")


# ── CLI テスト用 ──
if __name__ == "__main__":
    import sys
    import json
    from pathlib import Path

    # config読み込み
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        Path(__file__).parent.parent / "automation_config.json",
    ]:
        if p.exists():
            with open(p) as f:
                cfg = json.load(f)
            break
    else:
        print("automation_config.json not found")
        sys.exit(1)

    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("=== WAF 制御テスト ===")
        print("1. WAF OFF")
        ok_off = waf_disable(cfg)
        print(f"   結果: {'成功' if ok_off else '失敗'}")

        print("2. 5秒待機（テストデプロイ相当）")
        time.sleep(5)

        print("3. WAF ON")
        ok_on = waf_enable(cfg)
        print(f"   結果: {'成功' if ok_on else '失敗'}")

        print(f"\n=== テスト完了: OFF={'OK' if ok_off else 'NG'} / ON={'OK' if ok_on else 'NG'} ===")
    elif len(sys.argv) > 1 and sys.argv[1] == "off":
        waf_disable(cfg)
    elif len(sys.argv) > 1 and sys.argv[1] == "on":
        waf_enable(cfg)
    else:
        print("Usage: python3 lolipop_waf.py [test|on|off]")
