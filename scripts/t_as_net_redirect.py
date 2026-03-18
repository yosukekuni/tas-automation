#!/usr/bin/env python3
"""
t-as.net → tokaiair.com 301リダイレクト設定スクリプト

t-as.netのWordPress管理画面にアクセスし、以下を設定:
1. .htaccess に301リダイレクトルール追加
2. robots.txt をクロール制限に更新

前提: t-as.net の WordPress App Password が automation_config.json に設定済み

Usage:
    python3 t_as_net_redirect.py --check     # 現状確認のみ
    python3 t_as_net_redirect.py --deploy     # 実際にデプロイ
"""

import json
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent

# .htaccess content for 301 redirect
HTACCESS_REDIRECT = """# t-as.net -> tokaiair.com 301 Redirect
# Deployed: {timestamp}
# Purpose: Retire t-as.net, consolidate SEO to tokaiair.com

RewriteEngine On
RewriteCond %{HTTP_HOST} ^(www\\.)?t-as\\.net$ [NC]
RewriteRule ^(.*)$ https://tokaiair.com/$1 [R=301,L]
"""

# robots.txt to block crawling (backup measure)
ROBOTS_TXT = """# t-as.net - Retired site
# All traffic redirected to tokaiair.com via 301
# This robots.txt serves as a backup crawl block

User-agent: *
Disallow: /

# No sitemap - site retired
"""

# URL mapping for key pages that have different slugs
URL_MAP = {
    # t-as.net slug -> tokaiair.com slug (for pages with different paths)
    "soil-volume": "tools/earthwork",
    "soil-volume-nagoya": "tools/earthwork",
    "soil-volume-gifu": "tools/earthwork",
    "soil-volume-mie": "tools/earthwork",
    "soil-volume-shizuoka": "tools/earthwork",
    "fee_soil-volume": "tools/earthwork",
    "fee": "contact",
    "workflow": "contact",
    "infrared-survey": "",  # No equivalent, redirect to home
    "corresponding-area": "",  # Redirect to home
    "privacy": "privacy-policy",
    "customers-voice": "",
    "actual-introduction": "case-library",
}


def load_config():
    p = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
    if p.exists():
        with open(p) as f:
            return json.load(f)
    raise FileNotFoundError("automation_config.json not found")


def check_current_state():
    """現状確認: t-as.netの.htaccessとrobots.txtを取得"""
    print("=== t-as.net 現状確認 ===\n")

    # Check robots.txt
    try:
        req = urllib.request.Request("https://t-as.net/robots.txt")
        with urllib.request.urlopen(req, timeout=10) as resp:
            robots = resp.read().decode()
            print("[robots.txt]")
            print(robots)
    except Exception as e:
        print(f"[robots.txt] Error: {e}")

    # Check if redirect is already in place
    try:
        req = urllib.request.Request("https://t-as.net/test-redirect-check")
        req.add_header("User-Agent", "Mozilla/5.0")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
        resp = opener.open(req, timeout=10)
        final_url = resp.geturl()
        print(f"\n[Redirect Test] https://t-as.net/test-redirect-check -> {final_url}")
        if "tokaiair.com" in final_url:
            print("  -> 301 redirect is ACTIVE")
        else:
            print("  -> No redirect detected")
    except urllib.error.HTTPError as e:
        if e.code == 301 or e.code == 302:
            location = e.headers.get("Location", "")
            print(f"\n[Redirect Test] {e.code} -> {location}")
        else:
            print(f"\n[Redirect Test] HTTP {e.code}")
    except Exception as e:
        print(f"\n[Redirect Test] Error: {e}")

    # Check total content count
    for endpoint in ["posts", "pages"]:
        try:
            req = urllib.request.Request(
                f"https://t-as.net/wp-json/wp/v2/{endpoint}?per_page=1"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                total = resp.headers.get("X-WP-Total", "?")
                print(f"\n[Content] {endpoint}: {total} items")
        except Exception as e:
            print(f"\n[Content] {endpoint}: Error - {e}")


def generate_htaccess_with_map():
    """URL個別マッピング付き.htaccessを生成"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# t-as.net -> tokaiair.com 301 Redirect",
        f"# Deployed: {timestamp}",
        f"# Purpose: Retire t-as.net, consolidate SEO to tokaiair.com",
        "",
        "RewriteEngine On",
        "",
        "# Specific URL mappings for pages with different slugs",
    ]

    for old_slug, new_slug in URL_MAP.items():
        target = f"https://tokaiair.com/{new_slug}" if new_slug else "https://tokaiair.com/"
        lines.append(f"RewriteRule ^{old_slug}/?$ {target} [R=301,L]")

    lines.extend([
        "",
        "# Catch-all: redirect everything else to same path on tokaiair.com",
        "RewriteCond %{HTTP_HOST} ^(www\\.)?t-as\\.net$ [NC]",
        "RewriteRule ^(.*)$ https://tokaiair.com/$1 [R=301,L]",
    ])

    return "\n".join(lines) + "\n"


def save_snapshot():
    """現在のt-as.netの状態をスナップショット保存"""
    snapshot_dir = SCRIPT_DIR / "snapshots"
    snapshot_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snapshot = {
        "timestamp": timestamp,
        "action": "t-as.net_redirect_setup",
        "robots_txt_before": None,
        "redirect_test_before": None,
    }

    try:
        req = urllib.request.Request("https://t-as.net/robots.txt")
        with urllib.request.urlopen(req, timeout=10) as resp:
            snapshot["robots_txt_before"] = resp.read().decode()
    except Exception as e:
        snapshot["robots_txt_before"] = f"Error: {e}"

    filepath = snapshot_dir / f"t_as_net_redirect_snapshot_{timestamp}.json"
    with open(filepath, "w") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"Snapshot saved: {filepath}")
    return filepath


def print_manual_instructions():
    """手動設定手順を出力"""
    htaccess_content = generate_htaccess_with_map()

    print("\n" + "=" * 70)
    print("t-as.net 301リダイレクト 手動設定手順")
    print("=" * 70)

    print("""
方法A: ロリポップ管理画面から設定
─────────────────────────────────
1. ロリポップ管理画面にログイン
2. サーバーの管理・設定 → ロリポップ!FTP
3. t-as.net のドキュメントルートに移動
4. .htaccess を開いて以下の内容を先頭に追加:
""")
    print("--- .htaccess (先頭に追加) ---")
    print(htaccess_content)

    print("""
5. robots.txt を以下の内容に置き換え:
""")
    print("--- robots.txt ---")
    print(ROBOTS_TXT)

    print("""
方法B: WordPressプラグインで設定
─────────────────────────────────
1. t-as.net の WordPress管理画面にログイン
2. プラグイン「Redirection」をインストール・有効化
3. 正規表現リダイレクトで .* -> https://tokaiair.com/$1 を設定

方法C: FTP接続で設定
─────────────────────────────────
1. ロリポップFTP情報を確認（サーバーの管理・設定 → アカウント情報）
2. FTPクライアントで接続
3. .htaccess と robots.txt を配置
""")

    print("""
追加作業:
─────────────────────────────────
1. Google Search Console で t-as.net のサイトマップを削除
   - https://search.google.com/search-console にアクセス
   - t-as.net プロパティを選択
   - サイトマップ → 送信済みサイトマップ → 削除
   - sitemap.xml と sitemap.rss を削除

2. リダイレクト動作確認
   - curl -I https://t-as.net/ で 301 が返ることを確認
   - curl -I https://t-as.net/soil-volume で tokaiair.com/earthwork にリダイレクトされることを確認

3. 1-2週間後: Google Search Console で t-as.net のインデックス状況を確認
   - ページが徐々にインデックスから削除されていればOK
""")


def write_deliverables():
    """デプロイ用ファイルを書き出し"""
    output_dir = SCRIPT_DIR / "data" / "t_as_net_redirect"
    output_dir.mkdir(parents=True, exist_ok=True)

    # .htaccess
    htaccess_content = generate_htaccess_with_map()
    htaccess_path = output_dir / "htaccess_redirect.txt"
    with open(htaccess_path, "w") as f:
        f.write(htaccess_content)
    print(f"Written: {htaccess_path}")

    # robots.txt
    robots_path = output_dir / "robots.txt"
    with open(robots_path, "w") as f:
        f.write(ROBOTS_TXT)
    print(f"Written: {robots_path}")

    # URL mapping reference
    map_path = output_dir / "url_mapping.json"
    with open(map_path, "w") as f:
        json.dump(URL_MAP, f, ensure_ascii=False, indent=2)
    print(f"Written: {map_path}")

    return output_dir


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 t_as_net_redirect.py [--check|--deploy|--manual]")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "--check":
        check_current_state()
    elif mode == "--manual":
        save_snapshot()
        output_dir = write_deliverables()
        print_manual_instructions()
        print(f"\nDeliverable files saved to: {output_dir}")
    elif mode == "--deploy":
        print("ERROR: Direct deploy requires t-as.net WordPress credentials in automation_config.json")
        print("Add 'wordpress_tas' section with 'base_url', 'user', 'app_password'")
        print("\nUse --manual for manual setup instructions instead.")
        sys.exit(1)
    else:
        print(f"Unknown mode: {mode}")
        sys.exit(1)
