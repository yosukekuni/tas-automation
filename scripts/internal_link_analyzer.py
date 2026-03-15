#!/usr/bin/env python3
"""
内部リンク分析・最適化スクリプト

tokaiair.comの全公開記事の内部リンク構造を分析し、
関連記事間のリンクを自動挿入してSEOを強化する。

Usage:
    python3 internal_link_analyzer.py --analyze      # 分析のみ
    python3 internal_link_analyzer.py --dry-run      # プレビュー（変更なし）
    python3 internal_link_analyzer.py --apply        # 実行
"""

import json
import re
import sys
import base64
import urllib.request
import urllib.error
import argparse
from pathlib import Path
from collections import defaultdict

# Config
CONFIG_PATH = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")

def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)

def get_wp_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode((user + ":" + pwd).encode()).decode()

def get_all_posts(cfg):
    auth = get_wp_auth(cfg)
    base = cfg["wordpress"]["base_url"]
    all_posts = []
    page = 1
    while True:
        url = (base + "/posts?per_page=50&page=" + str(page)
               + "&status=publish&_fields=id,slug,title,link,categories,content")
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        try:
            resp = urllib.request.urlopen(req)
            posts = json.loads(resp.read())
            if not posts:
                break
            all_posts.extend(posts)
            page += 1
        except urllib.error.HTTPError as e:
            if e.code == 400:
                break
            raise
    return all_posts


def count_internal_links(content):
    """記事本文内の内部リンク数を数える"""
    pattern = r'href=["\'](?:https?://(?:www\.)?tokaiair\.com)?(/[^"\']*)["\']'
    links = re.findall(pattern, content)
    # WP管理画面系を除外
    return [l for l in links if not l.startswith("/wp-")]


def extract_keywords(title, content):
    """記事からキーワードを抽出"""
    # タイトルからキーワード
    title_clean = re.sub(r'<[^>]+>', '', title).strip()
    # H2見出しからもキーワード抽出
    h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', content, re.DOTALL)
    h2_texts = [re.sub(r'<[^>]+>', '', h).strip() for h in h2s]

    keywords = set()
    # ドローン測量関連キーワード
    kw_map = {
        "土量計算": ["土量", "土工量", "切盛", "残土"],
        "3次元": ["3D", "三次元", "点群", "3次元計測"],
        "ドローン測量": ["ドローン", "UAV", "空撮"],
        "i-Construction": ["i-Con", "ICT施工", "ICT活用"],
        "公共測量": ["公共", "測量作業規程", "精度管理"],
        "費用": ["コスト", "価格", "料金", "費用", "相場"],
        "赤外線": ["外壁調査", "赤外線調査", "外壁点検"],
        "測量会社": ["選び方", "業者", "依頼"],
        "安全": ["安全管理", "飛行申請", "航空法"],
        "資格": ["技能証明", "免許", "ライセンス"],
        "精度": ["精度", "誤差", "GNSS", "RTK"],
        "BIM/CIM": ["BIM", "CIM", "3Dモデル"],
        "写真測量": ["SfM", "写真測量", "オルソ画像"],
        "レーザー": ["LiDAR", "レーザー測量", "グリーンレーザー"],
        "法面": ["法面", "のり面", "斜面"],
        "橋梁": ["橋梁", "橋", "インフラ点検"],
        "建設コンサルタント": ["建設コンサルタント", "建コン"],
        "ゼネコン": ["ゼネコン", "建設会社", "施工会社"],
    }

    text = title_clean + " " + " ".join(h2_texts)
    for category, kws in kw_map.items():
        for kw in kws:
            if kw in text:
                keywords.add(category)
                break

    return keywords, title_clean, h2_texts


def find_related_posts(posts_data):
    """キーワードの重複度で関連記事を特定"""
    relations = defaultdict(list)

    for i, post_a in enumerate(posts_data):
        for j, post_b in enumerate(posts_data):
            if i == j:
                continue
            # キーワードの重複
            common = post_a["keywords"] & post_b["keywords"]
            if len(common) >= 1:
                relations[post_a["id"]].append({
                    "id": post_b["id"],
                    "slug": post_b["slug"],
                    "title": post_b["title"],
                    "link": post_b["link"],
                    "common_keywords": common,
                    "score": len(common),
                })

    # スコア順にソート
    for pid in relations:
        relations[pid].sort(key=lambda x: x["score"], reverse=True)

    return relations


def generate_related_links_html(related, max_links=3):
    """関連記事リンクのHTML生成"""
    if not related:
        return ""

    top = related[:max_links]
    links_html = []
    for r in top:
        links_html.append(
            '<li><a href="' + r["link"] + '">' + r["title"] + '</a></li>'
        )

    html = (
        '\n<!-- 関連記事（自動挿入） -->\n'
        '<div class="related-articles" style="background:#f5f5f5;border-radius:8px;'
        'padding:20px 24px;margin:32px 0;">\n'
        '<h3 style="font-size:1.1em;margin:0 0 12px;color:#1a2a3a;">'
        'あわせて読みたい</h3>\n'
        '<ul style="margin:0;padding-left:1.2em;">\n'
        + "\n".join(links_html) + "\n"
        '</ul>\n'
        '</div>\n'
        '<!-- /関連記事 -->\n'
    )
    return html


RELATED_MARKER = "<!-- 関連記事（自動挿入） -->"
RELATED_MARKER_END = "<!-- /関連記事 -->"


def has_related_section(content):
    """既に関連記事セクションがあるか"""
    return RELATED_MARKER in content


def insert_related_links(content, related_html):
    """記事末尾（最後の</div>の前or記事末尾）に関連記事を挿入"""
    if has_related_section(content):
        # 既存の関連記事セクションを置換
        pattern = RELATED_MARKER + ".*?" + RELATED_MARKER_END
        content = re.sub(pattern, related_html.strip(), content, flags=re.DOTALL)
        return content

    # CTAセクション（お問い合わせ）の前に挿入
    cta_patterns = [
        r'(<div[^>]*class="[^"]*cta[^"]*"[^>]*>)',
        r'(<div[^>]*class="[^"]*contact[^"]*"[^>]*>)',
        r'(<h[23][^>]*>.*?(?:お問い合わせ|ご相談|無料相談).*?</h[23]>)',
    ]
    for pat in cta_patterns:
        match = re.search(pat, content, re.IGNORECASE | re.DOTALL)
        if match:
            return content[:match.start()] + related_html + content[match.start():]

    # 見つからなければ末尾に追加
    return content + related_html


def update_post_content(cfg, post_id, new_content):
    """WordPress REST APIで記事を更新"""
    auth = get_wp_auth(cfg)
    base = cfg["wordpress"]["base_url"]
    url = base + "/posts/" + str(post_id)

    data = json.dumps({"content": new_content}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={
                                     "Authorization": "Basic " + auth,
                                     "Content-Type": "application/json",
                                     "User-Agent": "TAS-Automation/1.0",
                                 })
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def main():
    parser = argparse.ArgumentParser(description="内部リンク分析・最適化")
    parser.add_argument("--analyze", action="store_true", help="分析のみ")
    parser.add_argument("--dry-run", action="store_true", help="プレビュー")
    parser.add_argument("--apply", action="store_true", help="実行")
    parser.add_argument("--max-links", type=int, default=3, help="関連記事最大数")
    args = parser.parse_args()

    if not any([args.analyze, args.dry_run, args.apply]):
        args.analyze = True

    cfg = load_config()
    print("記事を取得中...")
    posts = get_all_posts(cfg)
    print(f"取得: {len(posts)}件\n")

    # 各記事のデータを準備
    posts_data = []
    for p in posts:
        content = p.get("content", {}).get("rendered", "")
        title = p["title"]["rendered"]
        keywords, title_clean, h2s = extract_keywords(title, content)
        internal_links = count_internal_links(content)
        has_related = has_related_section(content)

        posts_data.append({
            "id": p["id"],
            "slug": p["slug"],
            "title": title_clean,
            "link": p["link"],
            "categories": p.get("categories", []),
            "keywords": keywords,
            "internal_link_count": len(internal_links),
            "has_related": has_related,
            "content": content,
            "h2s": h2s,
        })

    # 関連記事マッピング
    relations = find_related_posts(posts_data)

    # === ANALYZE ===
    print("=" * 70)
    print("内部リンク分析レポート")
    print("=" * 70)

    # 内部リンク数の分布
    link_counts = [p["internal_link_count"] for p in posts_data]
    no_links = sum(1 for c in link_counts if c == 0)
    few_links = sum(1 for c in link_counts if 0 < c <= 2)
    ok_links = sum(1 for c in link_counts if c > 2)

    print(f"\n内部リンク数の分布:")
    print(f"  0本（孤立記事）: {no_links}件")
    print(f"  1-2本: {few_links}件")
    print(f"  3本以上: {ok_links}件")

    # 関連記事なしの記事
    no_related = [p for p in posts_data if not p["has_related"]]
    print(f"\n関連記事セクションなし: {len(no_related)}/{len(posts_data)}件")

    # 内部リンクが少ない記事トップ20
    sorted_posts = sorted(posts_data, key=lambda x: x["internal_link_count"])
    print(f"\n内部リンクが少ない記事（トップ20）:")
    for p in sorted_posts[:20]:
        related = relations.get(p["id"], [])
        rel_count = len(related)
        marker = " [関連記事あり]" if p["has_related"] else ""
        print(f"  {p['id']:5d} | links={p['internal_link_count']:2d} | rel={rel_count:2d} | {p['title'][:45]}{marker}")

    if args.analyze:
        print(f"\n分析完了。--dry-run でプレビュー、--apply で実行してください。")
        return

    # === DRY-RUN / APPLY ===
    updates = []
    for p in posts_data:
        if p["has_related"]:
            continue  # 既に関連記事セクションがある

        related = relations.get(p["id"], [])
        if not related:
            continue

        related_html = generate_related_links_html(related, max_links=args.max_links)
        if not related_html:
            continue

        new_content = insert_related_links(p["content"], related_html)
        if new_content == p["content"]:
            continue

        updates.append({
            "id": p["id"],
            "slug": p["slug"],
            "title": p["title"],
            "related": [r["title"][:30] for r in related[:args.max_links]],
            "new_content": new_content,
        })

    print(f"\n更新対象: {len(updates)}件")
    for u in updates:
        print(f"  {u['id']:5d} | {u['title'][:40]}")
        for r in u["related"]:
            print(f"         -> {r}")

    if args.dry_run:
        print(f"\n--dry-run: 変更は適用されていません。--apply で実行してください。")
        return

    if args.apply:
        print(f"\n適用中...")
        success = 0
        fail = 0
        for u in updates:
            try:
                update_post_content(cfg, u["id"], u["new_content"])
                print(f"  OK: {u['id']} {u['title'][:40]}")
                success += 1
            except Exception as e:
                print(f"  NG: {u['id']} {u['title'][:40]} - {str(e)[:60]}")
                fail += 1

        print(f"\n完了: 成功={success}, 失敗={fail}")


if __name__ == "__main__":
    main()
