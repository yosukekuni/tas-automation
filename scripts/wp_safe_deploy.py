#!/usr/bin/env python3
"""
WordPress安全デプロイラッパー

全てのWordPress書き込み操作は、このモジュール経由で行う。
review_agent.pyによる事前チェックを強制し、CRITICALなら中止+CEO通知。
ロリポップWAF自動制御: デプロイ前にWAF OFF → デプロイ後にWAF ON（try/finallyで保証）。
LiteSpeedキャッシュ自動パージ: デプロイ成功時に tas/v1/purge-cache 経由で全キャッシュパージ。
パージ失敗でもデプロイは中断しない（警告のみ）。

Usage (他スクリプトから):
    from wp_safe_deploy import safe_update_page, safe_update_option, safe_update_snippet

Usage (CLI):
    python3 wp_safe_deploy.py page 212 /tmp/content.html
    python3 wp_safe_deploy.py option force_light_mode /tmp/css.txt
    python3 wp_safe_deploy.py snippet 70 /tmp/code.php
"""

import json
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

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


def get_wp_base(cfg):
    return cfg["wordpress"]["base_url"].replace("/wp/v2", "")


# ── LiteSpeed Cache Purge ──
def _purge_cache(cfg, context="deploy"):
    """デプロイ後のLiteSpeedキャッシュパージ（失敗しても警告のみ）。

    Args:
        cfg: automation_config辞書
        context: ログ表示用のコンテキスト名
    """
    try:
        sys.path.insert(0, str(SCRIPT_DIR / "lib"))
        from litespeed_cache import purge_all
        wp_auth = get_wp_auth(cfg)
        wp_base = get_wp_base(cfg)
        print(f"  [Cache] LiteSpeed キャッシュパージ実行中... ({context})")
        result = purge_all(wp_base, wp_auth)
        if result["success"]:
            print(f"  [Cache] パージ完了")
        else:
            print(f"  [Cache] パージ警告: {result['message']}（デプロイは成功済み）")
    except Exception as e:
        print(f"  [Cache] パージスキップ: {e}（デプロイは成功済み）")


# ── WAF Control ──
def _has_waf_config(cfg):
    """ロリポップWAF設定が存在するか確認"""
    lolipop = cfg.get("lolipop", {})
    return bool(lolipop.get("domain")) and bool(lolipop.get("password"))


def _get_waf_context(cfg):
    """WAFコンテキストマネージャを返す。設定がなければダミーを返す。"""
    if _has_waf_config(cfg):
        try:
            sys.path.insert(0, str(SCRIPT_DIR / "lib"))
            from lolipop_waf import waf_context
            return waf_context(cfg)
        except ImportError as e:
            print(f"  [WAF] モジュール読み込み失敗: {e} - WAF手動操作にフォールバック")
    from contextlib import nullcontext
    return nullcontext(False)


# ── Review Agent ──
def run_review(content, profile="css"):
    """review_agent.pyを呼び出し。CRITICALがあればNG。"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from review_agent import review
        result = review(profile, content, output_json=True)
        return result
    except Exception as e:
        # レビューが実行できない場合は警告付きでOKにしない → NGにする
        return {
            "verdict": "NG",
            "issues": [{"severity": "CRITICAL", "check_number": 0,
                        "description": f"レビューエージェント実行失敗: {e}",
                        "fix_suggestion": "review_agent.pyの設定を確認"}],
            "summary": f"レビュー実行エラー: {e}"
        }


def notify_ceo(cfg, message):
    """CEO Lark DM通知"""
    try:
        from deal_thankyou_email import lark_get_token, send_lark_dm, CEO_OPEN_ID
        token = lark_get_token()
        send_lark_dm(token, CEO_OPEN_ID, message)
    except Exception:
        print(f"  CEO通知失敗（メッセージ: {message[:100]}）")


# ── Profile Auto-Detection ──
def detect_profile(content, operation_type=""):
    """コンテンツと操作種別からレビュープロファイルを自動判定"""
    if operation_type in ("page", "post", "article"):
        return "article"
    if operation_type in ("snippet", "css", "option"):
        return "css"
    if operation_type == "email":
        return "email"
    # Content-based detection
    if "<style" in content or "background" in content or "color:" in content:
        return "css"
    if "件名" in content or "Subject:" in content or "様" in content[:200]:
        return "email"
    if "<h1" in content or "<h2" in content or "<article" in content:
        return "article"
    return "css"  # default


# ── Safe Deploy Functions ──
def safe_update_page(page_id, content, profile=None, dry_run=False):
    """ページ更新（review_agent強制）"""
    if profile is None:
        profile = detect_profile(content, "page")

    print(f"[SafeDeploy] ページ {page_id} 更新 (profile: {profile})")

    # Review
    result = run_review(content, profile)
    print(f"  レビュー結果: {result['verdict']} - {result['summary']}")

    if result["verdict"] == "NG":
        issues = "\n".join(f"  - [{i['severity']}] {i['description']}"
                           for i in result.get("issues", []))
        print(f"  ブロック:\n{issues}")
        cfg = load_config()
        notify_ceo(cfg, f"デプロイブロック（ページ{page_id}更新）\n"
                        f"レビューNG: {result['summary']}\n{issues}")
        return False

    if dry_run:
        print(f"  [DRY-RUN] 更新スキップ")
        return True

    # Execute (WAF OFF → deploy → WAF ON)
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = cfg["wordpress"]["base_url"]

    data = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{wp_base}/pages/{page_id}",
        data=data,
        headers={"Authorization": f"Basic {wp_auth}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    with _get_waf_context(cfg):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
                print(f"  更新完了: page {resp.get('id')}")
                _purge_cache(cfg, f"page {page_id}")
                return True
        except urllib.error.HTTPError as e:
            print(f"  更新失敗: {e.code} {e.read().decode()[:200]}")
            return False


def safe_update_option(key, value, profile=None, dry_run=False):
    """WP option更新 via tas/v1/store（review_agent強制）"""
    if profile is None:
        profile = detect_profile(value, "option")

    print(f"[SafeDeploy] Option tas_{key} 更新 (profile: {profile})")

    # Review
    result = run_review(value, profile)
    print(f"  レビュー結果: {result['verdict']} - {result['summary']}")

    if result["verdict"] == "NG":
        issues = "\n".join(f"  - [{i['severity']}] {i['description']}"
                           for i in result.get("issues", []))
        print(f"  ブロック:\n{issues}")
        cfg = load_config()
        notify_ceo(cfg, f"デプロイブロック（Option: tas_{key}）\n"
                        f"レビューNG: {result['summary']}\n{issues}")
        return False

    if dry_run:
        print(f"  [DRY-RUN] 更新スキップ")
        return True

    # Execute (WAF OFF → deploy → WAF ON)
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = get_wp_base(cfg)

    hex_val = value.encode().hex()
    data = json.dumps({"key": key, "val": hex_val}).encode()
    req = urllib.request.Request(
        f"{wp_base}/tas/v1/store",
        data=data,
        headers={"Authorization": f"Basic {wp_auth}",
                 "Content-Type": "application/json"}
    )
    with _get_waf_context(cfg):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                print(f"  更新完了: {resp}")
                _purge_cache(cfg, f"option tas_{key}")
                return True
        except urllib.error.HTTPError as e:
            print(f"  更新失敗: {e.code} {e.read().decode()[:200]}")
            return False


def safe_update_snippet(snippet_id, code, profile="css", dry_run=False):
    """Snippet更新（review_agent強制）"""
    print(f"[SafeDeploy] Snippet {snippet_id} 更新 (profile: {profile})")

    # Review
    result = run_review(code, profile)
    print(f"  レビュー結果: {result['verdict']} - {result['summary']}")

    if result["verdict"] == "NG":
        issues = "\n".join(f"  - [{i['severity']}] {i['description']}"
                           for i in result.get("issues", []))
        print(f"  ブロック:\n{issues}")
        cfg = load_config()
        notify_ceo(cfg, f"デプロイブロック（Snippet {snippet_id}）\n"
                        f"レビューNG: {result['summary']}\n{issues}")
        return False

    if dry_run:
        print(f"  [DRY-RUN] 更新スキップ")
        return True

    # Execute (WAF OFF → deploy → WAF ON)
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = get_wp_base(cfg)

    data = json.dumps({"code": code}).encode()
    req = urllib.request.Request(
        f"{wp_base}/code-snippets/v1/snippets/{snippet_id}",
        data=data,
        headers={"Authorization": f"Basic {wp_auth}",
                 "Content-Type": "application/json"},
        method="PUT"
    )
    with _get_waf_context(cfg):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                print(f"  更新完了: Snippet {resp.get('id', snippet_id)}")
                _purge_cache(cfg, f"snippet {snippet_id}")
                return True
        except urllib.error.HTTPError as e:
            print(f"  更新失敗: {e.code} {e.read().decode()[:200]}")
            return False


def safe_update_global_styles(styles_css, dry_run=False):
    """Global Styles CSS更新（review_agent強制）"""
    print(f"[SafeDeploy] Global Styles CSS 更新")

    result = run_review(styles_css, "css")
    print(f"  レビュー結果: {result['verdict']} - {result['summary']}")

    if result["verdict"] == "NG":
        issues = "\n".join(f"  - [{i['severity']}] {i['description']}"
                           for i in result.get("issues", []))
        print(f"  ブロック:\n{issues}")
        cfg = load_config()
        notify_ceo(cfg, f"デプロイブロック（Global Styles）\n"
                        f"レビューNG: {result['summary']}\n{issues}")
        return False

    if dry_run:
        print(f"  [DRY-RUN] 更新スキップ")
        return True

    # Execute (WAF OFF → deploy → WAF ON)
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = cfg["wordpress"]["base_url"]

    data = json.dumps({"styles": {"css": styles_css}}).encode()
    req = urllib.request.Request(
        f"{wp_base}/global-styles/3503",
        data=data,
        headers={"Authorization": f"Basic {wp_auth}",
                 "Content-Type": "application/json"},
        method="POST"
    )
    with _get_waf_context(cfg):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                resp = json.loads(r.read())
                print(f"  更新完了")
                _purge_cache(cfg, "global-styles")
                return True
        except urllib.error.HTTPError as e:
            print(f"  更新失敗: {e.code} {e.read().decode()[:200]}")
            return False


# ── CLI ──
def main():
    if len(sys.argv) < 3:
        print("Usage: python3 wp_safe_deploy.py <type> <id/key> [file] [--dry-run]")
        print("  type: page, option, snippet, global-styles")
        sys.exit(1)

    op_type = sys.argv[1]
    target = sys.argv[2]
    dry_run = "--dry-run" in sys.argv

    # Read content
    file_arg = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "-"
    if file_arg == "-":
        content = sys.stdin.read()
    else:
        content = Path(file_arg).read_text(encoding="utf-8")

    if not content.strip():
        print("Error: empty content")
        sys.exit(1)

    if op_type == "page":
        ok = safe_update_page(int(target), content, dry_run=dry_run)
    elif op_type == "option":
        ok = safe_update_option(target, content, dry_run=dry_run)
    elif op_type == "snippet":
        ok = safe_update_snippet(int(target), content, dry_run=dry_run)
    elif op_type == "global-styles":
        ok = safe_update_global_styles(content, dry_run=dry_run)
    else:
        print(f"Unknown type: {op_type}")
        sys.exit(1)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
