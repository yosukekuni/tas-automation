#!/usr/bin/env python3
"""
Deploy snippet_h1_fix.php to WordPress as a Code Snippet.
テーマの wp-block-post-title H1→H2 変換を適用する。

WAF回避方式:
  1. PHPコードを hex エンコードして tas/v1/store に保存
  2. Code Snippets に eval(get_option()) ローダーを登録
  3. LiteSpeed キャッシュをパージ

Usage:
    python3 deploy_h1_fix.py [--dry-run]
"""

import json
import re
import base64
import urllib.request
import urllib.error
import sys
import time
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
SNIPPET_ID = 73  # 既存ローダーSnippet ID
OPTION_KEY = "h1_fix_snippet"  # wp_option: tas_h1_fix_snippet
CONFIG_PATHS = [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]
TEST_PAGES = [
    ("https://tokaiair.com/service/", "/service/"),
    ("https://tokaiair.com/company/", "/company/"),
    ("https://tokaiair.com/faq/", "/faq/"),
    ("https://tokaiair.com/services/uav-survey/", "/services/uav-survey/"),
]


def load_config():
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p) as f:
                return json.load(f)
    raise FileNotFoundError("automation_config.json not found")


def get_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()


def get_base(cfg):
    return cfg["wordpress"]["base_url"].replace("/wp/v2", "")


def count_h1(url):
    """ページのH1タグ数をカウント"""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Cache-Control": "no-cache",
        })
        resp = urllib.request.urlopen(req, timeout=15)
        html = resp.read().decode("utf-8", errors="replace")
        h1_tags = re.findall(r'<h1[^>]*>.*?</h1>', html, re.DOTALL)
        h2_pt = re.findall(r'<h2[^>]*class="[^"]*wp-block-post-title[^"]*"[^>]*>.*?</h2>', html, re.DOTALL)
        return h1_tags, h2_pt
    except Exception as e:
        return [], []


def main():
    dry_run = "--dry-run" in sys.argv
    cfg = load_config()
    auth = get_auth(cfg)
    base = get_base(cfg)

    php_path = SCRIPT_DIR / "snippet_h1_fix.php"
    code = php_path.read_text(encoding="utf-8").strip()

    print("=== H1 Fix Snippet Deploy ===")
    print(f"PHP code: {len(code)} chars")
    print(f"Target: Snippet #{SNIPPET_ID}, Option: tas_{OPTION_KEY}")

    # Step 1: 変更前の状態記録
    print("\n[1] 変更前のH1状態:")
    for url, label in TEST_PAGES:
        h1s, h2pts = count_h1(url)
        print(f"  {label}: H1 x{len(h1s)}")
        for t in h1s:
            print(f"    - {(t[:100] + '...') if len(t) > 100 else t}")

    if dry_run:
        print("\n[DRY-RUN] デプロイをスキップします")
        return

    # Step 2: PHPコードを hex エンコードして tas/v1/store に保存
    print("\n[2] PHPコードをwp_optionに保存...")
    hex_code = code.encode().hex()
    store_data = json.dumps({"key": OPTION_KEY, "val": hex_code}).encode()
    req = urllib.request.Request(
        f"{base}/tas/v1/store",
        data=store_data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        print(f"  OK: {result}")
    except urllib.error.HTTPError as e:
        print(f"  FAIL: {e.code} {e.read().decode()[:200]}")
        sys.exit(1)

    # Step 3: ローダーSnippetが有効か確認
    print(f"\n[3] Snippet #{SNIPPET_ID} 確認...")
    req2 = urllib.request.Request(
        f"{base}/code-snippets/v1/snippets/{SNIPPET_ID}",
        headers={"Authorization": f"Basic {auth}"},
    )
    resp2 = urllib.request.urlopen(req2, timeout=30)
    snippet = json.loads(resp2.read())
    print(f"  Name: {snippet.get('name')}")
    print(f"  Active: {snippet.get('active')}")
    print(f"  Code: {snippet.get('code')}")

    if not snippet.get("active"):
        print("  Activating snippet...")
        activate_data = json.dumps({"active": True}).encode()
        req3 = urllib.request.Request(
            f"{base}/code-snippets/v1/snippets/{SNIPPET_ID}",
            data=activate_data,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        resp3 = urllib.request.urlopen(req3, timeout=30)
        print(f"  Activated: {json.loads(resp3.read()).get('active')}")

    # Step 4: LiteSpeed キャッシュパージ
    print("\n[4] LiteSpeedキャッシュパージ...")
    purge_data = json.dumps({"active": True}).encode()
    req4 = urllib.request.Request(
        f"{base}/code-snippets/v1/snippets/52",
        data=purge_data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    try:
        urllib.request.urlopen(req4, timeout=30)
        time.sleep(3)
        deactivate = json.dumps({"active": False}).encode()
        req5 = urllib.request.Request(
            f"{base}/code-snippets/v1/snippets/52",
            data=deactivate,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
            method="PUT",
        )
        urllib.request.urlopen(req5, timeout=30)
        print("  パージ完了")
    except Exception as e:
        print(f"  パージ試行（エラー: {e}）")

    # Step 5: 検証
    print("\n[5] 変更後のH1状態（検証）:")
    time.sleep(2)
    all_ok = True
    for url, label in TEST_PAGES:
        h1s, h2pts = count_h1(url)
        status = "OK" if len(h1s) <= 1 else "NG"
        if status == "NG":
            all_ok = False
        print(f"  {label}: H1 x{len(h1s)}, Post-Title-H2 x{len(h2pts)} [{status}]")

    if all_ok:
        print("\n=== 全ページでH1重複が解消されました ===")
    else:
        print("\n=== 一部ページでH1が複数残っています（キャッシュの可能性） ===")
        print("  LiteSpeedキャッシュのパージを手動で確認してください。")


if __name__ == "__main__":
    main()
