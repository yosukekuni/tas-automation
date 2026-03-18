#!/usr/bin/env python3
"""
Yoast SEO meta description一括設定スクリプト

全記事・主要固定ページのmeta descriptionを確認し、
未設定のものにタイトル+冒頭文から自動生成したdescriptionを設定する。

使用API: tas/v1/pagemeta (Snippet #55) + wp/v2/posts, wp/v2/pages
"""

import json
import base64
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from datetime import datetime
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()


# ── Config ──
def load_config():
    p = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
    with open(p) as f:
        return json.load(f)


CFG = load_config()
WP_BASE = CFG["wordpress"]["base_url"]
WP_AUTH = base64.b64encode(
    f"{CFG['wordpress']['user']}:{CFG['wordpress']['app_password']}".encode()
).decode()
TAS_BASE = WP_BASE.replace("/wp/v2", "")

# SEOキーワード（自然に含める）
KEYWORDS = ["ドローン測量", "土量計算", "名古屋", "東海エアサービス"]
MAX_DESC_LENGTH = 160


# ── HTML Strip ──
class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.result = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.result.append(data)

    def get_text(self):
        return "".join(self.result)


def strip_html(html_str):
    """HTMLタグを除去してプレーンテキストを返す"""
    if not html_str:
        return ""
    s = HTMLStripper()
    s.feed(html_str)
    text = s.get_text()
    # 連続空白・改行を整理
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ── API Helpers ──
def wp_get(endpoint, params=None):
    """WP REST API GET"""
    url = f"{WP_BASE}/{endpoint}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url += f"?{qs}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {WP_AUTH}")
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())


def wp_get_all(endpoint, fields="id,title,content,yoast_head_json,slug,link"):
    """WP REST APIで全件取得（ページネーション対応）"""
    all_items = []
    page = 1
    while True:
        url = f"{WP_BASE}/{endpoint}?per_page=100&page={page}&_fields={fields}"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Basic {WP_AUTH}")
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            items = json.loads(resp.read())
            if not items:
                break
            all_items.extend(items)
            total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
            if page >= total_pages:
                break
            page += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
    return all_items


def set_meta_description(post_id, description):
    """tas/v1/pagemeta APIでmeta descriptionを設定"""
    payload = json.dumps({
        "key": "_yoast_wpseo_metadesc",
        "val": description
    }).encode()
    req = urllib.request.Request(
        f"{TAS_BASE}/tas/v1/pagemeta/{post_id}",
        data=payload,
        method="POST"
    )
    req.add_header("Authorization", f"Basic {WP_AUTH}")
    req.add_header("Content-Type", "application/json")

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        return data.get("ok", False)
    except urllib.error.HTTPError as e:
        print(f"  ERROR setting meta for post {post_id}: {e.code}")
        return False


def get_existing_meta_desc(post_id):
    """tas/v1/pagemeta APIで既存のmeta descriptionを取得"""
    req = urllib.request.Request(f"{TAS_BASE}/tas/v1/pagemeta/{post_id}")
    req.add_header("Authorization", f"Basic {WP_AUTH}")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        all_keys = data.get("all_keys", [])
        if "_yoast_wpseo_metadesc" in all_keys:
            # Need to get actual value - read from yoast_head_json instead
            return True  # Key exists
        return False
    except:
        return False


# ── Description Generation ──
def generate_description(title, content_html, slug="", post_type="post"):
    """タイトル+冒頭文からmeta descriptionを生成"""
    title_text = strip_html(title) if "<" in title else title
    content_text = strip_html(content_html)

    # Remove title from content start if duplicated
    if content_text.startswith(title_text):
        content_text = content_text[len(title_text):].strip()

    # 冒頭テキストを取得（句読点で切る）
    excerpt = content_text[:300]

    # 固定ページ用の特別処理
    if post_type == "page":
        return generate_page_description(title_text, excerpt, slug)

    # 記事用: タイトルベースの説明文を構成
    desc = generate_article_description(title_text, excerpt)

    return desc[:MAX_DESC_LENGTH]


def generate_article_description(title, excerpt):
    """記事用のmeta description生成"""
    # タイトルに含まれるキーワードを確認
    has_drone = "ドローン" in title
    has_survey = "測量" in title
    has_earthwork = "土量" in title

    # 基本パターン: タイトルの要約 + 冒頭文の要約
    # まずタイトルをベースにする
    base = title

    # 冒頭文から補足情報を取得
    if excerpt:
        # 最初の句点または読点で区切る
        first_sentence = ""
        for sep in ["。", "！", "？"]:
            idx = excerpt.find(sep)
            if idx > 0 and idx < 120:
                first_sentence = excerpt[:idx + 1]
                break
        if not first_sentence and len(excerpt) > 20:
            first_sentence = excerpt[:80]

        if first_sentence:
            # タイトルと重複しない情報を追加
            combined = f"{base}。{first_sentence}"
            if len(combined) <= MAX_DESC_LENGTH:
                desc = combined
            else:
                desc = combined[:MAX_DESC_LENGTH - 1]
        else:
            desc = base
    else:
        desc = base

    # キーワード補完（自然に）
    if "東海エアサービス" not in desc and len(desc) < 130:
        desc = desc.rstrip("。") + "。東海エアサービスが解説。"

    if "名古屋" not in desc and "東海" not in desc and len(desc) < 145:
        desc = desc.rstrip("。") + "（名古屋）"

    return desc[:MAX_DESC_LENGTH]


def generate_page_description(title, excerpt, slug):
    """固定ページ用のmeta description"""
    descriptions = {
        "": "東海エアサービス株式会社｜名古屋を拠点にドローン測量・土量計算サービスを提供。高精度な3次元データで建設現場のDXを支援します。",
        "services": "ドローン測量・3D点群データ・土量計算など、東海エアサービスのサービス一覧。名古屋を拠点に東海エリアの建設現場をサポート。",
        "contact": "東海エアサービスへのお問い合わせ。ドローン測量・土量計算のお見積り・ご相談はお気軽にどうぞ。名古屋から東海エリア全域対応。",
        "faq": "ドローン測量に関するよくある質問（FAQ）。費用・精度・納期・天候条件など、お客様の疑問にお答えします。東海エアサービス。",
        "column": "ドローン測量・土量計算に関するコラム・技術情報。現場で役立つ知識を東海エアサービスの専門スタッフがわかりやすく解説。",
        "company": "東海エアサービス株式会社の会社概要。名古屋市に本社を置くドローン測量の専門企業。代表挨拶・沿革・アクセス情報。",
        "privacy-policy": "東海エアサービス株式会社のプライバシーポリシー。個人情報の取り扱いについて。",
    }

    # スラグからマッチ
    for key, desc in descriptions.items():
        if slug == key or slug.rstrip("/") == key:
            return desc

    # デフォルト: タイトルベース
    if excerpt:
        desc = f"{title}。{excerpt[:100]}"
    else:
        desc = f"{title} - 東海エアサービス株式会社"

    return desc[:MAX_DESC_LENGTH]


# ── Main ──
def main():
    print("=" * 60)
    print("Yoast SEO Meta Description 一括設定")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # バックアップ用データ
    backup = {"timestamp": datetime.now().isoformat(), "updates": []}

    # ── 1. 全投稿を取得 ──
    print("\n[1/4] 全投稿を取得中...")
    posts = wp_get_all("posts", "id,title,content,yoast_head_json,slug,link")
    print(f"  投稿数: {len(posts)}")

    # ── 2. 全固定ページを取得 ──
    print("\n[2/4] 固定ページを取得中...")
    pages = wp_get_all("pages", "id,title,content,yoast_head_json,slug,link")
    print(f"  固定ページ数: {len(pages)}")

    # ── 3. meta description状況を確認 ──
    print("\n[3/4] meta description設定状況を確認中...")

    needs_update = []
    already_set = []
    all_items = []

    for item in posts:
        item["_type"] = "post"
        all_items.append(item)
    for item in pages:
        item["_type"] = "page"
        all_items.append(item)

    for item in all_items:
        yoast = item.get("yoast_head_json") or {}
        existing_desc = yoast.get("description", "")
        og_desc = yoast.get("og_description", "")

        # descriptionがある = Yoastで設定されているか自動生成されている
        # og_descriptionがある場合は既にdescription設定済みの可能性
        # ただしYoastは未設定でもタイトルをdescriptionに使うことがある
        # 正確な判定: _yoast_wpseo_metadesc が空かどうか

        title = item.get("title", {}).get("rendered", "")
        slug = item.get("slug", "")
        content = item.get("content", {}).get("rendered", "")
        post_type = item["_type"]
        post_id = item["id"]

        # og_descriptionが空 or タイトルとほぼ同じ = 未設定の可能性が高い
        if not og_desc or og_desc == title or og_desc.startswith(title[:30]):
            # 正確にmeta fieldを確認
            needs_update.append({
                "id": post_id,
                "title": title,
                "slug": slug,
                "content": content,
                "type": post_type,
                "current_desc": og_desc,
            })
        else:
            already_set.append({
                "id": post_id,
                "title": title,
                "desc": og_desc[:80],
                "type": post_type,
            })

    print(f"\n  設定済み: {len(already_set)}件")
    print(f"  未設定（候補）: {len(needs_update)}件")

    # 設定済み一覧表示
    if already_set:
        print("\n  --- 設定済み一覧 ---")
        for item in already_set[:10]:
            print(f"  [{item['type']}] ID:{item['id']} {item['title'][:40]}")
            print(f"    desc: {item['desc'][:60]}...")
        if len(already_set) > 10:
            print(f"  ... 他{len(already_set) - 10}件")

    # ── 4. 未設定の記事にdescriptionを生成・設定 ──
    print(f"\n[4/4] meta description生成・設定中... ({len(needs_update)}件)")

    updated = 0
    skipped = 0
    errors = 0

    for i, item in enumerate(needs_update):
        post_id = item["id"]
        title = item["title"]
        content = item["content"]
        slug = item["slug"]
        post_type = item["type"]

        # 生成
        desc = generate_description(title, content, slug, post_type)

        if not desc or len(desc) < 20:
            print(f"  SKIP [{post_type}] ID:{post_id} {title[:40]} - 生成できず")
            skipped += 1
            continue

        # バックアップ保存
        backup["updates"].append({
            "id": post_id,
            "type": post_type,
            "title": title,
            "slug": slug,
            "old_desc": item.get("current_desc", ""),
            "new_desc": desc,
        })

        # 設定
        ok = set_meta_description(post_id, desc)
        if ok:
            updated += 1
            print(f"  OK [{post_type}] ID:{post_id} {title[:40]}")
            print(f"     -> {desc[:80]}...")
        else:
            errors += 1
            print(f"  ERR [{post_type}] ID:{post_id} {title[:40]}")

        # Rate limiting
        if (i + 1) % 10 == 0:
            time.sleep(0.5)

    # ── バックアップ保存 ──
    backup_path = Path("/mnt/c/Users/USER/Documents/_data/tas-automation/backups")
    backup_path.mkdir(exist_ok=True)
    backup_file = backup_path / f"yoast_metadesc_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False, indent=2)

    # ── サマリ ──
    print("\n" + "=" * 60)
    print("完了サマリ")
    print("=" * 60)
    print(f"  全投稿+ページ: {len(all_items)}件")
    print(f"  既に設定済み:   {len(already_set)}件")
    print(f"  今回更新:       {updated}件")
    print(f"  スキップ:       {skipped}件")
    print(f"  エラー:         {errors}件")
    print(f"  バックアップ:   {backup_file}")
    print("=" * 60)

    return updated, errors


if __name__ == "__main__":
    updated, errors = main()
