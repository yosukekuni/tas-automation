#!/usr/bin/env python3
"""
Claude Code 技術キャッチアップ 週次トレンドスキャン

スキャン対象:
  - https://www.anthropic.com/changelog (HTML)
  - https://docs.anthropic.com/ (変更検知)
  - https://zenn.dev/topics/claudecode (RSS)
  - https://github.com/anthropics/claude-code/releases (HTML)

処理フロー:
  1. 各ソースから最新記事/リリースを取得
  2. 前回スキャン結果（JSONファイル）と差分を検出
  3. 新規コンテンツをClaude APIで日本語サマリー生成（3行以内）
  4. Lark Webhookで週次サマリー通知

GitHub Actions: .github/workflows/claude_tech_catchup.yml
  スケジュール: 毎週月曜 08:00 JST (23:00 UTC日曜)
"""

import sys
import json
import re
import hashlib
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from xml.etree import ElementTree

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config

STATE_FILE = SCRIPT_DIR / "claude_tech_catchup_state.json"

SOURCES = {
    "anthropic_news": {
        "url": "https://www.anthropic.com/news",
        "type": "html",
        "label": "Anthropic News",
    },
    "zenn_claudecode": {
        "url": "https://zenn.dev/topics/claudecode/feed?all=1",
        "type": "rss",
        "label": "Zenn / Claude Code",
    },
    "github_releases": {
        "url": "https://github.com/anthropics/claude-code/releases",
        "type": "html",
        "label": "GitHub Releases (claude-code)",
    },
    "anthropic_docs": {
        "url": "https://docs.anthropic.com/",
        "type": "html_hash",
        "label": "Anthropic Docs",
    },
}

MAX_ITEMS_PER_SOURCE = 5
CLAUDE_MODEL = "claude-3-5-haiku-20241022"


# ── State Management ──

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── HTTP Fetch ──

def fetch_url(url, timeout=20):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; TAS-Bot/1.0; "
            "+https://tokaiair.com/) claudetech-catchup"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja,en;q=0.9",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Fetch failed {url}: {e}")
        return None


# ── Parsers ──

def parse_anthropic_news(html):
    """Anthropic newsページからエントリを抽出（スラグベース）"""
    items = []
    if not html:
        return items

    # Extract news article slugs from href="/news/<slug>"
    slug_pattern = re.compile(r'href="/news/([a-z0-9-]{5,100})"', re.IGNORECASE)
    slugs_raw = slug_pattern.findall(html)

    # Deduplicate while preserving order
    seen = set()
    slugs = []
    for s in slugs_raw:
        if s not in seen:
            seen.add(s)
            slugs.append(s)

    # Extract dates (ISO or written format)
    date_pattern = re.compile(
        r'(\d{4}-\d{2}-\d{2}|'
        r'(?:January|February|March|April|May|June|July|August|September|'
        r'October|November|December)\s+\d{1,2},\s+\d{4})',
        re.IGNORECASE
    )
    dates = date_pattern.findall(html)

    for i, slug in enumerate(slugs[:MAX_ITEMS_PER_SOURCE]):
        # Convert slug to readable title
        title = slug.replace("-", " ").title()
        date = dates[i] if i < len(dates) else ""
        item_id = hashlib.md5(slug.encode()).hexdigest()[:12]
        items.append({
            "id": item_id,
            "title": title,
            "date": date,
            "url": f"https://www.anthropic.com/news/{slug}",
            "source": "anthropic_news",
        })

    return items[:MAX_ITEMS_PER_SOURCE]


def parse_rss(xml_text, source_key):
    """RSS/Atomフィードからエントリを抽出"""
    items = []
    if not xml_text:
        return items

    try:
        # Strip ALL namespace declarations and prefixes for simpler parsing
        xml_clean = re.sub(r' xmlns(?::\w+)?="[^"]*"', '', xml_text)
        # Remove namespace prefixes from tags (e.g. dc:creator -> creator)
        xml_clean = re.sub(r'<(/?)(\w+):(\w+)', r'<\1\3', xml_clean)
        root = ElementTree.fromstring(xml_clean)

        # RSS 2.0
        entries = root.findall('.//item')
        # Atom fallback
        if not entries:
            entries = root.findall('.//entry')

        for entry in entries[:MAX_ITEMS_PER_SOURCE]:
            title_el = entry.find('title')
            link_el = entry.find('link')
            date_el = (entry.find('pubDate') if entry.find('pubDate') is not None
                       else entry.find('published') if entry.find('published') is not None
                       else entry.find('updated'))

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            if not link:
                link = link_el.get('href', '') if link_el is not None else ""
            date = date_el.text.strip() if date_el is not None and date_el.text else ""

            if not title:
                continue

            item_id = hashlib.md5((title + link).encode()).hexdigest()[:12]
            items.append({
                "id": item_id,
                "title": title,
                "date": date,
                "url": link,
                "source": source_key,
            })
    except Exception as e:
        print(f"  [WARN] RSS parse error ({source_key}): {e}")

    return items


def parse_github_releases(html, source_key):
    """GitHubリリースページからリリースエントリを抽出"""
    items = []
    if not html:
        return items

    # GitHub releases: <h2 class="..."><a href="/...releases/tag/...">vX.Y.Z</a></h2>
    pattern = re.compile(
        r'href="(/anthropics/claude-code/releases/tag/([^"]+))"[^>]*>([^<]+)</a>',
        re.IGNORECASE
    )
    date_pattern = re.compile(
        r'datetime="(\d{4}-\d{2}-\d{2})',
        re.IGNORECASE
    )

    matches = pattern.findall(html)
    dates = date_pattern.findall(html)

    seen = set()
    for i, (path, tag, label) in enumerate(matches[:MAX_ITEMS_PER_SOURCE]):
        tag = tag.strip()
        label = label.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        date = dates[i] if i < len(dates) else ""
        item_id = hashlib.md5(tag.encode()).hexdigest()[:12]
        items.append({
            "id": item_id,
            "title": f"Release {tag}: {label}" if label != tag else f"Release {tag}",
            "date": date,
            "url": f"https://github.com{path}",
            "source": source_key,
        })

    return items[:MAX_ITEMS_PER_SOURCE]


def parse_html_hash(html, source_key, url):
    """ページのハッシュで変更を検知（docs等）"""
    if not html:
        return []
    content_hash = hashlib.md5(html[:50000].encode()).hexdigest()[:16]
    return [{
        "id": content_hash,
        "title": f"ページ変更検知: {url}",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "url": url,
        "source": source_key,
    }]


# ── Diff Detection ──

def find_new_items(items, prev_ids):
    """前回状態にないアイテムを返す"""
    return [item for item in items if item["id"] not in prev_ids]


# ── Claude Summary ──

def generate_summary(new_items_by_source, api_key):
    """新規アイテムをClaude APIで日本語サマリー化（3行以内）"""
    if not new_items_by_source or not api_key:
        return None

    # Build prompt
    items_text = []
    for source_label, items in new_items_by_source.items():
        items_text.append(f"\n【{source_label}】")
        for item in items:
            items_text.append(f"  - {item['title']} ({item['date']}) {item['url']}")

    prompt = (
        "以下は Claude Code / Anthropic に関する今週の新着情報です。\n"
        "開発者・システム管理者の視点で、実務上重要なポイントを3行以内で日本語サマリーしてください。\n"
        "不要な情報（日付重複・タイトル繰り返し）は省いてください。\n\n"
        + "\n".join(items_text)
        + "\n\n出力形式: 箇条書き3点以内。各行は「・」から始める。"
    )

    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        return resp["content"][0]["text"].strip()
    except Exception as e:
        print(f"  [WARN] Claude API error: {e}")
        return None


# ── Lark Notification ──

def send_lark_notification(webhook_url, new_items_by_source, summary, scan_time):
    """Lark Webhookでサマリーを通知"""
    if not webhook_url:
        print("  [WARN] Lark webhook URL not configured")
        return False

    total = sum(len(v) for v in new_items_by_source.values())

    if total == 0:
        body_text = f"Claude Code 技術キャッチアップ（{scan_time}）\n\n今週の新着情報はありませんでした。"
    else:
        lines = [
            f"Claude Code 技術キャッチアップ（{scan_time}）",
            f"新着: {total}件",
            "",
        ]
        if summary:
            lines.append("【AIサマリー】")
            lines.append(summary)
            lines.append("")

        lines.append("【新着一覧】")
        for source_label, items in new_items_by_source.items():
            if items:
                lines.append(f"\n{source_label}:")
                for item in items[:3]:
                    lines.append(f"  • {item['title']}")
                    if item.get("url"):
                        lines.append(f"    {item['url']}")

        body_text = "\n".join(lines)

    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": body_text},
    }).encode()

    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
        if resp.get("code") == 0 or resp.get("StatusCode") == 0:
            print("  Lark通知送信完了")
            return True
        else:
            print(f"  [WARN] Lark通知失敗: {resp}")
            return False
    except Exception as e:
        print(f"  [WARN] Lark通知エラー: {e}")
        return False


# ── Main ──

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Claude Code技術キャッチアップ 週次スキャン")
    parser.add_argument("--dry-run", action="store_true", help="通知しない（テスト用）")
    parser.add_argument("--force", action="store_true", help="差分なくても通知する")
    args = parser.parse_args()

    print("=" * 60)
    print("Claude Code 技術キャッチアップ 週次スキャン")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    cfg = load_config()
    api_key = cfg.get("anthropic", {}).get("api_key", "")
    webhook_url = cfg.get("notifications", {}).get("lark_webhook_url", "")

    # ── 前回状態の読み込み ──
    state = load_state()
    scan_time = datetime.now().strftime("%Y/%m/%d")

    all_new_items = {}
    new_state = {}

    # ── 各ソースをスキャン ──
    print("\n[1/4] ソースをスキャン中...")

    for source_key, source_cfg in SOURCES.items():
        url = source_cfg["url"]
        label = source_cfg["label"]
        source_type = source_cfg["type"]
        print(f"\n  [{label}] {url}")

        html = fetch_url(url)

        if source_type == "html":
            if source_key == "anthropic_news":
                items = parse_anthropic_news(html)
            elif source_key == "github_releases":
                items = parse_github_releases(html, source_key)
            else:
                items = []
        elif source_type == "rss":
            items = parse_rss(html, source_key)
        elif source_type == "html_hash":
            items = parse_html_hash(html, source_key, url)
        else:
            items = []

        print(f"    取得: {len(items)}件")

        # 差分検出
        prev_ids = set(state.get(source_key, {}).get("seen_ids", []))
        new_items = find_new_items(items, prev_ids)
        if args.force:
            new_items = items

        print(f"    新着: {len(new_items)}件")

        if new_items:
            all_new_items[label] = new_items

        # 状態更新（最新IDを記録）
        all_ids = list({item["id"] for item in items})
        # Keep up to 50 IDs per source to avoid unbounded growth
        prev_ids_list = list(prev_ids)
        merged_ids = list(set(prev_ids_list + all_ids))[-50:]
        new_state[source_key] = {
            "seen_ids": merged_ids,
            "last_scan": scan_time,
        }

    total_new = sum(len(v) for v in all_new_items.values())
    print(f"\n  合計新着: {total_new}件")

    # ── AIサマリー生成 ──
    summary = None
    if total_new > 0 and api_key:
        print("\n[2/4] AIサマリー生成中...")
        summary = generate_summary(all_new_items, api_key)
        if summary:
            print(f"  サマリー生成完了:\n{summary}")
        else:
            print("  サマリー生成失敗（APIエラー）")
    else:
        print("\n[2/4] 新着なし or APIキー未設定 - サマリースキップ")

    # ── Lark通知 ──
    print("\n[3/4] Lark通知...")
    if args.dry_run:
        print("  [DRY-RUN] 通知スキップ")
        print(f"\n  --- DRY-RUN 通知内容プレビュー ---")
        print(f"  新着: {total_new}件")
        if summary:
            print(f"  サマリー: {summary}")
        for src_label, items in all_new_items.items():
            print(f"  {src_label}:")
            for item in items:
                print(f"    - {item['title']}")
    else:
        if total_new > 0 or args.force:
            send_lark_notification(webhook_url, all_new_items, summary, scan_time)
        else:
            print("  新着なし - 通知スキップ")

    # ── 状態保存 ──
    print("\n[4/4] 状態を保存中...")
    if not args.dry_run:
        save_state(new_state)
        print(f"  状態保存完了: {STATE_FILE}")
    else:
        print(f"  [DRY-RUN] 状態保存スキップ")

    print(f"\n完了: 新着{total_new}件")
    print("=" * 60)


if __name__ == "__main__":
    main()
