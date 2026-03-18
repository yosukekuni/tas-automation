#!/usr/bin/env python3
"""
SEO 1位奪取施策 デプロイスクリプト

WordPress Yoast SEOのtitle/meta descriptionを更新し、
サービスページにLocalBusiness + Service構造化データを追加する。

wp_safe_deploy.py経由でコンテンツ変更を実行。
"""

import json
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent

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


def update_yoast_meta(page_id, seo_title, seo_desc, is_post=False):
    """Yoast SEO title/descriptionをWordPress REST API経由で更新"""
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = cfg["wordpress"]["base_url"]

    endpoint = "posts" if is_post else "pages"

    payload = {
        "yoast_meta": {
            "yoast_wpseo_title": seo_title,
            "yoast_wpseo_metadesc": seo_desc
        },
        "meta": {
            "_yoast_wpseo_title": seo_title,
            "_yoast_wpseo_metadesc": seo_desc
        }
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{wp_base}/{endpoint}/{page_id}",
        data=data,
        headers={
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            new_yoast = resp.get("yoast_head_json", {})
            new_title = new_yoast.get("title", "")
            new_desc = new_yoast.get("description", "")
            print(f"  [OK] {endpoint}/{page_id}")
            print(f"    New Title: {new_title}")
            print(f"    New Desc:  {new_desc[:80]}...")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"  [FAIL] {endpoint}/{page_id}: {e.code} {body}")
        return False


def get_page_content(page_id, is_post=False):
    """ページの現在のコンテンツを取得"""
    cfg = load_config()
    wp_auth = get_wp_auth(cfg)
    wp_base = cfg["wordpress"]["base_url"]

    endpoint = "posts" if is_post else "pages"
    req = urllib.request.Request(
        f"{wp_base}/{endpoint}/{page_id}?_fields=content",
        headers={"Authorization": f"Basic {wp_auth}"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
        return data.get("content", {}).get("rendered", "")


def inject_schema_jsonld(page_id, schema_data):
    """ページコンテンツの末尾にJSON-LDスクリプトを追加（既存のものを置換）"""
    content = get_page_content(page_id)

    # 既存のカスタムschemaタグを除去
    import re
    content = re.sub(
        r'<!-- TAS-SEO-SCHEMA-START -->.*?<!-- TAS-SEO-SCHEMA-END -->',
        '',
        content,
        flags=re.DOTALL
    )

    schema_json = json.dumps(schema_data, ensure_ascii=False, indent=2)
    schema_block = f'\n<!-- TAS-SEO-SCHEMA-START -->\n<script type="application/ld+json">\n{schema_json}\n</script>\n<!-- TAS-SEO-SCHEMA-END -->'

    new_content = content.strip() + schema_block

    # wp_safe_deploy経由で更新
    sys.path.insert(0, str(SCRIPT_DIR))
    from wp_safe_deploy import safe_update_page
    return safe_update_page(page_id, new_content, profile="article")


def submit_indexnow(urls):
    """IndexNow APIで更新URLを送信"""
    cfg = load_config()
    api_key = cfg.get("indexnow", {}).get("api_key", "")
    if not api_key:
        print("  [SKIP] IndexNow API key not configured")
        return

    payload = {
        "host": "tokaiair.com",
        "key": api_key,
        "keyLocation": f"https://tokaiair.com/{api_key}.txt",
        "urlList": urls
    }

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"  [OK] IndexNow submitted {len(urls)} URLs (status: {r.status})")
    except urllib.error.HTTPError as e:
        print(f"  [INFO] IndexNow response: {e.code} (202/200 = OK)")


def main():
    print("=" * 60)
    print("SEO 1位奪取施策 デプロイ")
    print("=" * 60)

    dry_run = "--dry-run" in sys.argv
    skip_schema = "--skip-schema" in sys.argv

    if dry_run:
        print("[DRY-RUN MODE]")

    # ── 1. サービスページ（/services/uav-survey/）Title/Desc最適化 ──
    print("\n[1/5] サービスページ title/desc 最適化 (Page 4831)")
    if not dry_run:
        update_yoast_meta(
            4831,
            seo_title="名古屋のドローン測量｜±3cm高精度・最短翌日｜東海エアサービス",
            seo_desc="名古屋・愛知県のドローン測量なら東海エアサービス。RTK/PPK対応±3cm精度、最短翌日納品。土量算出・出来形管理・i-Construction対応。測量業者登録・国交省許可取得。料金15万円〜。無料見積り受付中。"
        )
    else:
        print("  [DRY-RUN] Title: 名古屋のドローン測量｜±3cm高精度・最短翌日｜東海エアサービス")

    # ── 2. 費用ページ Title最適化 ──
    print("\n[2/5] 費用ページ title 最適化 (Post 5927)")
    if not dry_run:
        update_yoast_meta(
            5927,
            seo_title="ドローン測量の費用相場【2026年版】名古屋・東海エリア実勢価格と料金表",
            seo_desc="ドローン測量の費用相場を2026年最新の名古屋・東海エリア実勢価格で解説。面積別料金表・写真測量vsレーザー比較・見積りのポイント。15万円〜。東海エアサービス。",
            is_post=True
        )
    else:
        print("  [DRY-RUN] Title: ドローン測量の費用相場【2026年版】...")

    # ── 3. 土量計算ページ Title最適化 ──
    print("\n[3/5] 土量コスト計算機 title 最適化 (Page 4721)")
    if not dry_run:
        update_yoast_meta(
            4721,
            seo_title="ドローン土量計算・残土コスト無料シミュレーション｜東海エアサービス",
            seo_desc="ドローン測量の土量計算を無料でシミュレーション。体積入力でダンプ台数・運搬費・処分費を30秒で自動算出。建設現場のコスト管理に。東海エアサービス（名古屋）。"
        )
    else:
        print("  [DRY-RUN] Title: ドローン土量計算・残土コスト無料シミュレーション...")

    # ── 4. 土量計算記事 Title最適化 ──
    print("\n[4/5] 土量計算記事 title 最適化 (Post 5956)")
    if not dry_run:
        update_yoast_meta(
            5956,
            seo_title="ドローン土量計算の方法｜従来手法との精度・コスト・工期を比較｜東海エアサービス",
            seo_desc="ドローン測量による土量計算の効率化を解説。従来手法との精度・コスト・工期を徹底比較。造成工事・残土管理・災害復旧の活用事例付き。名古屋の東海エアサービス。",
            is_post=True
        )
    else:
        print("  [DRY-RUN] Title: ドローン土量計算の方法｜従来手法...")

    # ── 5. サービスページにLocalBusiness + Service Schema追加 ──
    print("\n[5/5] サービスページに構造化データ追加 (Page 4831)")
    if not dry_run and not skip_schema:
        schema = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "LocalBusiness",
                    "@id": "https://tokaiair.com/#localbusiness",
                    "name": "東海エアサービス株式会社",
                    "description": "名古屋・愛知県のドローン測量・3D計測・赤外線調査の専門会社。RTK/PPK対応±3cm精度。測量業者登録済み。",
                    "url": "https://tokaiair.com/",
                    "telephone": "+81-50-7117-7141",
                    "email": "info@tokaiair.com",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "植園町1-9-3",
                        "addressLocality": "名古屋市名東区",
                        "addressRegion": "愛知県",
                        "postalCode": "465-0077",
                        "addressCountry": "JP"
                    },
                    "geo": {
                        "@type": "GeoCoordinates",
                        "latitude": 35.1715,
                        "longitude": 137.0042
                    },
                    "areaServed": [
                        {"@type": "State", "name": "愛知県"},
                        {"@type": "State", "name": "岐阜県"},
                        {"@type": "State", "name": "三重県"},
                        {"@type": "State", "name": "静岡県"}
                    ],
                    "priceRange": "¥150,000〜",
                    "openingHours": "Mo-Fr 09:00-18:00"
                },
                {
                    "@type": "Service",
                    "@id": "https://tokaiair.com/services/uav-survey/#service",
                    "name": "ドローン測量",
                    "description": "RTK/PPK対応のドローン測量サービス。±3cm精度で土量算出・出来形管理・GCP最適化に対応。最短翌日納品。",
                    "provider": {"@id": "https://tokaiair.com/#localbusiness"},
                    "serviceType": "ドローン測量",
                    "areaServed": [
                        {"@type": "State", "name": "愛知県"},
                        {"@type": "State", "name": "岐阜県"},
                        {"@type": "State", "name": "三重県"},
                        {"@type": "State", "name": "静岡県"},
                        {"@type": "Country", "name": "日本"}
                    ],
                    "offers": {
                        "@type": "Offer",
                        "priceSpecification": {
                            "@type": "PriceSpecification",
                            "price": "150000",
                            "priceCurrency": "JPY",
                            "description": "基本料金15万円〜（面積・条件により変動）"
                        }
                    },
                    "hasOfferCatalog": {
                        "@type": "OfferCatalog",
                        "name": "ドローン測量サービス",
                        "itemListElement": [
                            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "土量算出（起工測量・出来形管理）"}},
                            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "3次元地表面モデル（DSM/DTM）作成"}},
                            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "オルソ画像作成"}},
                            {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "i-Construction対応データ納品"}}
                        ]
                    }
                },
                {
                    "@type": "FAQPage",
                    "mainEntity": [
                        {
                            "@type": "Question",
                            "name": "ドローン測量の精度はどのくらいですか？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "RTK/PPK測位で地表面モデル±3cmの精度を標準としています。GCP（地上基準点）を設置し、チェックポイントで検証した誤差値をレポートでお渡しします。"
                            }
                        },
                        {
                            "@type": "Question",
                            "name": "ドローン測量の料金はいくらですか？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "基本料金は15万円〜です。面積・地形条件・必要な成果品により変動します。1,000m2以下で15〜25万円、1ha以上で50〜80万円が目安です。無料でお見積りいたします。"
                            }
                        },
                        {
                            "@type": "Question",
                            "name": "納品までどのくらいかかりますか？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "撮影から最短翌日〜5営業日で納品します。面積や成果品の種類により前後します。お急ぎの場合はご相談ください。"
                            }
                        },
                        {
                            "@type": "Question",
                            "name": "対応エリアはどこまでですか？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "愛知県・岐阜県・三重県・静岡県は交通費無料で対応。全国出張も可能です。遠方の場合は別途交通費をいただきます。"
                            }
                        },
                        {
                            "@type": "Question",
                            "name": "土量計算だけ依頼できますか？",
                            "acceptedAnswer": {
                                "@type": "Answer",
                                "text": "はい、土量算出のみのご依頼も承ります。既存の測量データからの解析や、定期的な土量変化の計測にも対応しています。"
                            }
                        }
                    ]
                }
            ]
        }
        inject_schema_jsonld(4831, schema)
    elif skip_schema:
        print("  [SKIP] Schema injection skipped")
    else:
        print("  [DRY-RUN] Schema injection skipped")

    # ── IndexNow送信 ──
    print("\n[IndexNow] URL送信")
    updated_urls = [
        "https://tokaiair.com/services/uav-survey/",
        "https://tokaiair.com/info/drone-survey-cost-nagoya/",
        "https://tokaiair.com/tools/earthwork/",
        "https://tokaiair.com/articles/drone-earthwork-volume/"
    ]
    if not dry_run:
        submit_indexnow(updated_urls)
    else:
        print(f"  [DRY-RUN] Would submit {len(updated_urls)} URLs")

    print("\n" + "=" * 60)
    print("デプロイ完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
