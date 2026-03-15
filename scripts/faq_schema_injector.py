#!/usr/bin/env python3
"""
FAQ Schema (JSON-LD) 自動挿入スクリプト

tokaiair.comの既存記事からFAQ的な見出し+回答を抽出し、
FAQPage Schemaを記事末尾に挿入してリッチリザルト獲得を目指す。

Usage:
    python3 faq_schema_injector.py --list          # FAQ抽出可能な記事一覧
    python3 faq_schema_injector.py --dry-run       # プレビューのみ（全記事）
    python3 faq_schema_injector.py --test-one      # 1記事だけテスト実行
    python3 faq_schema_injector.py                 # 全記事に適用
"""

import json
import sys
import re
import html
import base64
import time
import urllib.request
import urllib.error
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# ── 定数 ──
MAX_FAQ_PER_POST = 5
MAX_ANSWER_CHARS = 200
FAQ_SCHEMA_MARKER = '"@type":"FAQPage"'
FAQ_SCHEMA_MARKER_ALT = '"@type": "FAQPage"'

# 質問形式の見出しパターン（日本語）
# 優先度高: 明確な質問形式
QUESTION_PATTERNS = [
    r'^Q[\.\s．].*',           # "Q. ..." で始まる見出し（最優先）
    r'.*[？\?]$',              # 末尾が？で終わるもの
    r'.*とは$',                # "〜とは"（？なしでも質問的）
]

# 非質問形式の除外パターン（マッチしたらスキップ）
EXCLUDE_PATTERNS = [
    r'^(メリット|デメリット)\d',    # "メリット1：..." 列挙系
    r'^チェックポイント[①-⑩\d]',  # "チェックポイント①：..."
    r'^(比較表|早見表|一覧)',       # テーブル見出し
    r'^確認(方法|すべき)',          # 手順見出し
    r'^\d+[\.\)）]',              # "1. ..." 番号付き見出し
]

# 社外秘キーワード（これらを含むFAQはスキップ）
CONFIDENTIAL_KEYWORDS = [
    '顧客依存率', '営業成績', 'ランウェイ', '売上',
    '受注率', '失注', '粗利', '利益率',
]


# ── Config ──
def load_config():
    import os
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        SCRIPT_DIR / "automation_config.json",
    ]:
        if p.exists():
            with open(p) as f:
                raw = f.read()
            # 環境変数を展開
            for key in ['WP_USER', 'WP_APP_PASSWORD', 'LARK_APP_ID', 'LARK_APP_SECRET',
                         'CRM_BASE_TOKEN', 'ANTHROPIC_API_KEY', 'LARK_WEBHOOK_URL',
                         'GA4_PROPERTY_ID', 'WEB_ANALYTICS_BASE_TOKEN']:
                env_val = os.environ.get(key, '')
                raw = raw.replace(f'${{{key}}}', env_val)
            return json.loads(raw)
    raise FileNotFoundError("automation_config.json not found")


def get_wp_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode(f"{user}:{pwd}".encode()).decode()


# ── WP API ──
def wp_get(url, auth):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wp_get_all_posts(base_url, auth, per_page=100):
    """全投稿記事を取得（ページネーション対応）"""
    all_posts = []
    page = 1
    while True:
        url = f"{base_url}/posts?per_page={per_page}&page={page}&status=publish"
        try:
            posts = wp_get(url, auth)
            if not posts:
                break
            all_posts.extend(posts)
            if len(posts) < per_page:
                break
            page += 1
            time.sleep(0.5)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
    return all_posts


def wp_update_post(base_url, auth, post_id, content):
    """投稿記事のコンテンツを更新"""
    data = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{base_url}/posts/{post_id}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


# ── HTML解析 ──
def strip_html_tags(text):
    """HTMLタグを除去してプレーンテキストにする"""
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = text.strip()
    return text


def extract_faqs_from_content(content_html):
    """
    記事本文からFAQ的な見出し+回答ペアを抽出。
    H2/H3見出しが質問形式 → 直後の段落群を回答として取得。
    """
    # CTAブロックを除去（回答にCTAテキストが混入するのを防ぐ）
    content_html = re.sub(
        r'<div[^>]*style="[^"]*background:\s*#f0f7ff[^"]*"[^>]*>.*?</div>',
        '', content_html, flags=re.DOTALL | re.IGNORECASE
    )

    # 見出しと段落をパースする
    # パターン: <h2>...<h3>... と <p>...</p> を順番に抽出
    elements = re.findall(
        r'(<h[23][^>]*>.*?</h[23]>|<p[^>]*>.*?</p>|<ul[^>]*>.*?</ul>|<ol[^>]*>.*?</ol>)',
        content_html,
        re.DOTALL | re.IGNORECASE
    )

    faqs = []
    current_question = None
    answer_parts = []

    for elem in elements:
        # 見出しかどうか判定
        heading_match = re.match(r'<h[23][^>]*>(.*?)</h[23]>', elem, re.DOTALL | re.IGNORECASE)
        if heading_match:
            # 前の質問があれば保存
            if current_question and answer_parts:
                answer_text = _clean_answer(' '.join(answer_parts))
                if len(answer_text) > MAX_ANSWER_CHARS:
                    answer_text = answer_text[:MAX_ANSWER_CHARS - 1] + '…'
                if not _contains_confidential(current_question + answer_text):
                    faqs.append({
                        'question': _clean_question(current_question),
                        'answer': answer_text,
                    })

            heading_text = strip_html_tags(heading_match.group(1))
            current_question = None
            answer_parts = []

            # 質問形式かチェック
            if _is_question_heading(heading_text):
                current_question = heading_text
        else:
            # 段落/リスト → 回答の一部として蓄積
            if current_question:
                plain = strip_html_tags(elem)
                if plain:
                    answer_parts.append(plain)

    # 最後の質問を保存
    if current_question and answer_parts:
        answer_text = _clean_answer(' '.join(answer_parts))
        if len(answer_text) > MAX_ANSWER_CHARS:
            answer_text = answer_text[:MAX_ANSWER_CHARS - 1] + '…'
        if not _contains_confidential(current_question + answer_text):
            faqs.append({
                'question': _clean_question(current_question),
                'answer': answer_text,
            })

    # 最大5つに制限
    return faqs[:MAX_FAQ_PER_POST]


def _is_question_heading(text):
    """見出しが質問形式かどうか判定"""
    # 除外パターンに該当する場合はスキップ
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, text):
            return False
    # 質問パターンにマッチするか
    for pattern in QUESTION_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _contains_confidential(text):
    """社外秘キーワードを含むかチェック"""
    for kw in CONFIDENTIAL_KEYWORDS:
        if kw in text:
            return True
    return False


def _clean_question(text):
    """質問文からQ.プレフィックスを除去"""
    return re.sub(r'^Q[\.\s．]\s*', '', text)


def _clean_answer(text):
    """回答文からA.プレフィックスを除去"""
    return re.sub(r'^A[\.\s．]\s*', '', text)


def has_existing_faq_schema(content_html):
    """既にFAQPage Schemaが挿入済みかチェック"""
    normalized = content_html.replace(' ', '')
    return FAQ_SCHEMA_MARKER.replace(' ', '') in normalized


# ── Schema生成 ──
def generate_faq_schema_jsonld(faqs):
    """FAQPage Schema JSON-LDを生成"""
    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": []
    }
    for faq in faqs:
        schema["mainEntity"].append({
            "@type": "Question",
            "name": faq["question"],
            "acceptedAnswer": {
                "@type": "Answer",
                "text": faq["answer"]
            }
        })
    # JSON-LDスクリプトタグとして整形
    json_str = json.dumps(schema, ensure_ascii=False, indent=2)
    return f'\n<script type="application/ld+json">\n{json_str}\n</script>'


# ── メイン処理 ──
def main():
    parser = argparse.ArgumentParser(description='FAQ Schema (JSON-LD) 自動挿入')
    parser.add_argument('--list', action='store_true', help='FAQ抽出可能な記事一覧を表示')
    parser.add_argument('--dry-run', action='store_true', help='プレビューのみ（更新しない）')
    parser.add_argument('--test-one', action='store_true', help='1記事だけテスト実行')
    args = parser.parse_args()

    cfg = load_config()
    base_url = cfg["wordpress"]["base_url"]
    auth = get_wp_auth(cfg)

    print("📡 WordPress記事を取得中...")
    posts = wp_get_all_posts(base_url, auth)
    print(f"   取得: {len(posts)}件")

    results = []

    for post in posts:
        post_id = post["id"]
        title = post["title"]["rendered"]
        content = post["content"]["rendered"]
        link = post.get("link", "")

        # 既にFAQ Schemaがある場合はスキップ
        if has_existing_faq_schema(content):
            continue

        # FAQ抽出
        faqs = extract_faqs_from_content(content)
        if not faqs:
            continue

        results.append({
            'id': post_id,
            'title': strip_html_tags(title),
            'link': link,
            'faqs': faqs,
            'content': content,
        })

    if not results:
        print("FAQ抽出可能な記事が見つかりませんでした。")
        return

    # --list モード
    if args.list:
        print(f"\n📋 FAQ抽出可能な記事: {len(results)}件\n")
        for r in results:
            print(f"  [{r['id']}] {r['title']} ({len(r['faqs'])}問)")
            for i, faq in enumerate(r['faqs'], 1):
                print(f"       Q{i}: {faq['question']}")
        return

    # --test-one: 最初の1件だけ
    if args.test_one:
        results = results[:1]

    # --dry-run / 実行
    updated = 0
    skipped = 0

    for r in results:
        schema_html = generate_faq_schema_jsonld(r['faqs'])

        print(f"\n{'='*60}")
        print(f"📄 [{r['id']}] {r['title']}")
        print(f"   URL: {r['link']}")
        print(f"   FAQ数: {len(r['faqs'])}")
        for i, faq in enumerate(r['faqs'], 1):
            print(f"   Q{i}: {faq['question']}")
            print(f"   A{i}: {faq['answer'][:80]}...")

        if args.dry_run:
            print(f"\n   [DRY-RUN] 生成されるJSON-LD:")
            print(schema_html)
            continue

        # 記事末尾にJSON-LDを追加
        new_content = r['content'] + schema_html

        try:
            wp_update_post(base_url, auth, r['id'], new_content)
            print(f"   ✅ Schema挿入完了")
            updated += 1
            time.sleep(1)  # API負荷軽減
        except Exception as e:
            print(f"   ❌ エラー: {e}")
            skipped += 1

    print(f"\n{'='*60}")
    if args.dry_run:
        print(f"📊 DRY-RUN完了: {len(results)}件プレビュー")
    else:
        print(f"📊 完了: {updated}件更新 / {skipped}件スキップ")


if __name__ == "__main__":
    main()
