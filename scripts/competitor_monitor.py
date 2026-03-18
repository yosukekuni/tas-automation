#!/usr/bin/env python3
"""
競合監視スクリプト（施策7: 競合監視の自動化）

月次で競合サイトの以下をチェックし、Lark Webhook通知:
  - ページ数の増減（sitemap解析）
  - 新規コンテンツの検出
  - 構造化データの変化
  - 主要キーワードの検索順位変動（Search Console経由）

Usage:
    python3 competitor_monitor.py --check        # 全競合サイトをチェック
    python3 competitor_monitor.py --report       # 前回比レポート生成
    python3 competitor_monitor.py --dry-run      # チェックのみ（通知なし）
    python3 competitor_monitor.py --add URL      # 競合サイトを追加

cron (GitHub Actions):
    毎月1日 8:00 JST
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config
from lib.lark_api import lark_get_token, send_lark_webhook

STATE_FILE = SCRIPT_DIR / "data" / "competitor_monitor_state.json"
LOG_FILE = SCRIPT_DIR / "competitor_monitor.log"

# 監視対象の競合サイト
COMPETITORS = {
    # ドローン測量系（tokaiair.com の競合）
    "tokaiair": {
        "own": True,
        "url": "https://www.tokaiair.com",
        "sitemap": "https://www.tokaiair.com/sitemap_index.xml",
        "keywords": ["ドローン測量", "ドローン測量 費用", "ドローン測量 名古屋",
                      "土量計算", "ドローン 3D測量", "ドローン測量 愛知"],
    },
    "skymatix": {
        "url": "https://skymatix.co.jp",
        "sitemap": "https://skymatix.co.jp/sitemap.xml",
        "keywords": [],
    },
    "terra_drone": {
        "url": "https://www.terra-drone.net",
        "sitemap": "https://www.terra-drone.net/sitemap.xml",
        "keywords": [],
    },
    "drone_ipros": {
        "url": "https://www.ipros.jp",
        "sitemap": None,
        "note": "ポータルサイト比較用",
        "keywords": [],
    },
}

# AI事業承継系（tomoshi.jp の競合）
COMPETITORS_TOMOSHI = {
    "tomoshi": {
        "own": True,
        "url": "https://tomoshi.jp",
        "sitemap": "https://tomoshi.jp/sitemap.xml",
        "keywords": ["事業承継 AI", "属人化 リスク", "事業承継 DX"],
    },
}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except IOError:
        pass


def fetch_sitemap_urls(sitemap_url, timeout=30):
    """sitemapからURLリストを取得（sitemap indexにも対応）"""
    if not sitemap_url:
        return []

    urls = []
    try:
        req = urllib.request.Request(
            sitemap_url,
            headers={"User-Agent": "TokaiAir-CompetitorMonitor/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read().decode("utf-8", errors="replace")

        root = ET.fromstring(content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        # sitemap indexの場合
        sitemaps = root.findall(".//sm:sitemap/sm:loc", ns)
        if sitemaps:
            for sm in sitemaps:
                child_urls = fetch_sitemap_urls(sm.text, timeout)
                urls.extend(child_urls)
                time.sleep(1)  # 礼儀正しいクロール
        else:
            # 通常のsitemap
            for url_elem in root.findall(".//sm:url/sm:loc", ns):
                urls.append(url_elem.text)

    except Exception as e:
        log(f"  Sitemap取得エラー ({sitemap_url}): {e}")

    return urls


def check_structured_data(url, timeout=15):
    """ページのJSON-LD構造化データを確認"""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "TokaiAir-CompetitorMonitor/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="replace")

        # JSON-LDの数をカウント
        import re
        json_ld_blocks = re.findall(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html, re.DOTALL | re.IGNORECASE
        )

        schemas = []
        for block in json_ld_blocks:
            try:
                data = json.loads(block)
                if isinstance(data, list):
                    for item in data:
                        schemas.append(item.get("@type", "Unknown"))
                else:
                    schemas.append(data.get("@type", "Unknown"))
            except json.JSONDecodeError:
                pass

        return schemas

    except Exception as e:
        log(f"  構造化データ取得エラー ({url}): {e}")
        return []


def load_state():
    """前回の状態を読み込み"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"snapshots": {}, "last_check": None}


def save_state(state):
    """状態を保存"""
    STATE_FILE.parent.mkdir(exist_ok=True)
    state["last_check"] = datetime.now().isoformat()
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def check_competitor(name, info, previous_snapshot=None):
    """1つの競合サイトをチェック"""
    log(f"  チェック中: {name} ({info['url']})")

    snapshot = {
        "url": info["url"],
        "checked_at": datetime.now().isoformat(),
        "page_count": 0,
        "urls": [],
        "structured_data_types": [],
    }

    # Sitemapからページ数取得
    if info.get("sitemap"):
        urls = fetch_sitemap_urls(info["sitemap"])
        snapshot["page_count"] = len(urls)
        snapshot["urls"] = urls[:500]  # 保存サイズ制限
        log(f"    ページ数: {len(urls)}")
    else:
        log(f"    Sitemap未設定（ページ数不明）")

    # トップページの構造化データ
    schemas = check_structured_data(info["url"])
    snapshot["structured_data_types"] = schemas
    log(f"    構造化データ: {schemas}")

    # 前回との差分
    changes = []
    if previous_snapshot:
        prev_count = previous_snapshot.get("page_count", 0)
        curr_count = snapshot["page_count"]
        if curr_count != prev_count and prev_count > 0:
            diff = curr_count - prev_count
            sign = "+" if diff > 0 else ""
            changes.append(f"ページ数: {prev_count} -> {curr_count} ({sign}{diff})")

        # 新規URL検出
        prev_urls = set(previous_snapshot.get("urls", []))
        curr_urls = set(snapshot.get("urls", []))
        new_urls = curr_urls - prev_urls
        removed_urls = prev_urls - curr_urls

        if new_urls:
            changes.append(f"新規ページ: {len(new_urls)}件")
            for u in list(new_urls)[:5]:
                changes.append(f"  + {u}")

        if removed_urls:
            changes.append(f"削除ページ: {len(removed_urls)}件")

        # 構造化データの変化
        prev_schemas = set(previous_snapshot.get("structured_data_types", []))
        curr_schemas = set(snapshot.get("structured_data_types", []))
        if curr_schemas != prev_schemas:
            changes.append(f"構造化データ変化: {prev_schemas} -> {curr_schemas}")

    snapshot["changes"] = changes
    return snapshot


def generate_report(state):
    """レポートテキストを生成"""
    lines = [
        "=== 競合監視レポート ===",
        f"チェック日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    snapshots = state.get("snapshots", {})
    has_changes = False

    for name, snap in sorted(snapshots.items()):
        lines.append(f"## {name} ({snap.get('url', '')})")
        lines.append(f"   ページ数: {snap.get('page_count', '?')}")
        lines.append(f"   構造化データ: {', '.join(snap.get('structured_data_types', [])) or 'なし'}")

        changes = snap.get("changes", [])
        if changes:
            has_changes = True
            lines.append("   [変化あり]")
            for c in changes:
                lines.append(f"   {c}")
        else:
            lines.append("   変化なし")
        lines.append("")

    if not has_changes:
        lines.append("--- 今月は目立った変化なし ---")

    return "\n".join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="競合監視")
    parser.add_argument("--check", action="store_true", help="全競合チェック")
    parser.add_argument("--report", action="store_true", help="レポート生成")
    parser.add_argument("--dry-run", action="store_true", help="通知なし")
    parser.add_argument("--add", type=str, help="競合URL追加")
    args = parser.parse_args()

    if not any([args.check, args.report, args.add]):
        parser.print_help()
        sys.exit(1)

    cfg = load_config()
    state = load_state()

    if args.check:
        log("=== 競合監視チェック開始 ===")
        all_competitors = {**COMPETITORS, **COMPETITORS_TOMOSHI}

        for name, info in all_competitors.items():
            prev = state.get("snapshots", {}).get(name)
            snapshot = check_competitor(name, info, prev)
            state.setdefault("snapshots", {})[name] = snapshot
            time.sleep(2)  # 礼儀正しいクロール間隔

        save_state(state)
        log("=== チェック完了 ===")

        # レポート生成
        report = generate_report(state)
        print("\n" + report)

        # Lark通知（dry-runでなければ）
        if not args.dry_run:
            try:
                send_lark_webhook(cfg, report[:2000])
                log("Lark通知送信完了")
            except Exception as e:
                log(f"Lark通知失敗: {e}")

    if args.report:
        report = generate_report(state)
        print(report)

    if args.add:
        log(f"競合追加: {args.add}")
        print("注意: 恒久的な追加はスクリプト内のCOMPETITORS辞書を編集してください。")
        snapshot = check_competitor(
            args.add.replace("https://", "").replace("/", "_"),
            {"url": args.add, "sitemap": f"{args.add}/sitemap.xml", "keywords": []},
            None,
        )
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
