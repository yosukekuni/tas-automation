#!/usr/bin/env python3
"""
AI検索最適化（AEO）構造化データ強化スクリプト

全主要ページに以下の構造化データを追加・更新する:
  - Speakable: AI音声読み上げ対象セクション指定
  - FAQPage: FAQリッチリザルト
  - HowTo: ドローン測量の流れ
  - Service: サービス詳細
  - LocalBusiness: 事業者情報

また、AI検索頻出クエリに対応するコンテンツスニペットを生成する。

Usage:
  python3 aeo_structured_data.py --list        # 対象ページ一覧
  python3 aeo_structured_data.py --dry-run     # 生成されるJSONを確認
  python3 aeo_structured_data.py --deploy      # WordPressに適用
  python3 aeo_structured_data.py --generate-content  # AEOコンテンツ生成

出力:
  - content/aeo_schemas/ ディレクトリにJSON-LDファイル
  - content/aeo_content_snippets.html  AI検索対応コンテンツ
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content"
SCHEMA_DIR = CONTENT_DIR / "aeo_schemas"

sys.path.insert(0, str(SCRIPT_DIR))

# ── 定数 ──
PHONE = "050-7117-7141"
BRAND_COLOR = "#1647FB"
COMPANY_NAME = "東海エアサービス株式会社"
SITE_URL = "https://tokaiair.com"

# ── ページ定義 ──
PAGES = {
    "top": {
        "page_id": None,  # トップページ（別管理）
        "url": f"{SITE_URL}/",
        "title": "東海エアサービス | ドローン測量・3次元データサービス",
    },
    "uav-survey": {
        "page_id": 4831,
        "url": f"{SITE_URL}/uav-survey/",
        "title": "ドローン測量サービス",
    },
    "3d-measurement": {
        "page_id": 4843,
        "url": f"{SITE_URL}/3d-measurement/",
        "title": "3次元計測サービス",
    },
    "infrared-inspection": {
        "page_id": 4834,
        "url": f"{SITE_URL}/infrared-inspection/",
        "title": "赤外線点検サービス",
    },
    "services": {
        "page_id": 4837,
        "url": f"{SITE_URL}/services/",
        "title": "サービス一覧",
    },
    "faq": {
        "page_id": 4850,
        "url": f"{SITE_URL}/faq/",
        "title": "よくあるご質問",
    },
    "case-library": {
        "page_id": 5098,
        "url": f"{SITE_URL}/case-library/",
        "title": "実績事例一覧",
    },
    "company": {
        "page_id": 16,
        "url": f"{SITE_URL}/company/",
        "title": "会社概要",
    },
}


# ── 構造化データビルダー ──

def build_organization_schema():
    """Organization構造化データ（全ページ共通）"""
    return {
        "@type": "Organization",
        "@id": f"{SITE_URL}/#organization",
        "name": COMPANY_NAME,
        "url": SITE_URL,
        "telephone": PHONE,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "名古屋市",
            "addressRegion": "愛知県",
            "postalCode": "460-0003",
            "addressCountry": "JP"
        },
        "areaServed": [
            {"@type": "State", "name": "愛知県"},
            {"@type": "State", "name": "岐阜県"},
            {"@type": "State", "name": "三重県"},
            {"@type": "State", "name": "静岡県"}
        ],
        "knowsAbout": [
            "ドローン測量",
            "UAV測量",
            "3次元計測",
            "点群データ",
            "オルソ画像",
            "赤外線点検",
            "土量計算",
            "i-Construction"
        ]
    }


def build_speakable_schema(url, css_selectors=None):
    """Speakable構造化データ（AI音声読み上げ対象）"""
    return {
        "@type": "WebPage",
        "@id": url,
        "speakable": {
            "@type": "SpeakableSpecification",
            "cssSelector": css_selectors or [
                ".page-hero h1",
                ".page-hero p",
                ".service-intro",
                ".faq-answer"
            ]
        }
    }


def build_howto_drone_survey():
    """HowTo構造化データ: ドローン測量の流れ"""
    return {
        "@type": "HowTo",
        "name": "ドローン測量の依頼から納品までの流れ",
        "description": "東海エアサービスにドローン測量を依頼する際の一般的な流れをご説明します。",
        "totalTime": "P7D",
        "estimatedCost": {
            "@type": "MonetaryAmount",
            "currency": "JPY",
            "value": "50000"
        },
        "step": [
            {
                "@type": "HowToStep",
                "position": 1,
                "name": "お問い合わせ・ご相談",
                "text": "お電話（050-7117-7141）またはお問い合わせフォームから、測量対象の現場情報（所在地・面積・地形）と希望する納品物をお伝えください。",
                "url": f"{SITE_URL}/contact/"
            },
            {
                "@type": "HowToStep",
                "position": 2,
                "name": "お見積り",
                "text": "現場情報をもとに、最短当日でお見積りをお出しします。面積・精度要件・納品物により費用が異なります。"
            },
            {
                "@type": "HowToStep",
                "position": 3,
                "name": "現場調査・飛行計画",
                "text": "必要に応じて現場の事前調査を行い、飛行ルート・基準点（GCP/RTK）の設置計画を策定します。航空法に基づく飛行許可も弊社で対応します。"
            },
            {
                "@type": "HowToStep",
                "position": 4,
                "name": "ドローン撮影",
                "text": "高精度RTK-GNSS対応ドローンで空撮を実施。一般的な現場であれば数時間で撮影が完了します。"
            },
            {
                "@type": "HowToStep",
                "position": 5,
                "name": "データ解析・処理",
                "text": "撮影データをSfM（Structure from Motion）ソフトウェアで処理し、点群データ・オルソ画像・3Dモデルを生成します。"
            },
            {
                "@type": "HowToStep",
                "position": 6,
                "name": "品質検査・納品",
                "text": "精度検証を行った上で、ご希望のフォーマット（LAS/LAZ/GeoTIFF/DXF/DWG等）で納品します。データの読み方のサポートも行います。"
            }
        ]
    }


def build_service_schemas():
    """各サービスのService構造化データ"""
    services = [
        {
            "name": "ドローン測量（UAV測量）",
            "description": "高精度RTK-GNSS対応ドローンを使用した3次元測量。点群データ・オルソ画像・3Dモデルを短工期で納品。造成現場・建設用地・道路・河川など幅広い現場に対応。",
            "url": f"{SITE_URL}/uav-survey/",
            "category": "測量サービス",
        },
        {
            "name": "3次元計測",
            "description": "レーザースキャナーとドローンを組み合わせた高密度3次元計測。建物・構造物・地形の精密な3Dデータを取得。BIM/CIM連携にも対応。",
            "url": f"{SITE_URL}/3d-measurement/",
            "category": "計測サービス",
        },
        {
            "name": "赤外線建物点検",
            "description": "赤外線サーモグラフィカメラ搭載ドローンによる非破壊検査。外壁タイル浮き・雨漏り・断熱不良を効率的に発見。足場不要で安全かつ低コスト。",
            "url": f"{SITE_URL}/infrared-inspection/",
            "category": "点検サービス",
        },
        {
            "name": "土量計算",
            "description": "ドローン測量で取得した点群データから正確な切土・盛土量を算出。従来の断面法と比較して高精度な体積計算が可能。",
            "url": f"{SITE_URL}/earthwork-calculator/",
            "category": "測量サービス",
        },
        {
            "name": "現場空撮（進捗管理）",
            "description": "建設現場の定期空撮による進捗管理。工事の記録・報告書作成・施主説明に活用。オルソ画像で面積や位置関係を正確に把握。",
            "url": f"{SITE_URL}/services/",
            "category": "撮影サービス",
        },
    ]

    schemas = []
    for svc in services:
        schemas.append({
            "@type": "Service",
            "name": svc["name"],
            "description": svc["description"],
            "url": svc["url"],
            "category": svc["category"],
            "provider": {
                "@type": "LocalBusiness",
                "@id": f"{SITE_URL}/#organization",
                "name": COMPANY_NAME,
                "telephone": PHONE
            },
            "areaServed": [
                {"@type": "State", "name": "愛知県"},
                {"@type": "State", "name": "岐阜県"},
                {"@type": "State", "name": "三重県"},
                {"@type": "State", "name": "静岡県"}
            ],
            "hasOfferCatalog": {
                "@type": "OfferCatalog",
                "name": f"{svc['name']}の料金",
                "itemListElement": [{
                    "@type": "Offer",
                    "priceCurrency": "JPY",
                    "priceSpecification": {
                        "@type": "PriceSpecification",
                        "priceCurrency": "JPY",
                        "minPrice": "30000"
                    }
                }]
            }
        })
    return schemas


def build_faq_for_aeo():
    """AI検索頻出クエリに対応するFAQ構造化データ"""
    faqs = [
        # 「ドローン測量 どこに頼む」対応
        ("ドローン測量はどこに頼めばいいですか？",
         "ドローン測量は、国土交通省の飛行許可を持ち、測量の専門知識を有する事業者に依頼することをおすすめします。東海エアサービスは愛知・岐阜・三重・静岡の東海4県で181件以上の実績があり、建設会社・コンサルタント・測量会社など幅広い業種のお客様にご利用いただいています。"),

        # 「名古屋 ドローン測量 おすすめ」対応
        ("名古屋でおすすめのドローン測量会社はどこですか？",
         "名古屋を拠点とするドローン測量会社をお探しなら、東海エアサービスがおすすめです。名古屋市内に拠点を構え、高精度RTK-GNSS対応ドローンを使用。52社以上の取引実績があり、最短当日でお見積りが可能です。"),

        # 「ドローン測量 費用 相場」対応
        ("ドローン測量の費用相場はいくらですか？",
         "ドローン測量の費用は、測量面積・地形・精度要件により異なりますが、一般的に数万円〜数十万円です。小規模宅地（〜1,000m2）で5〜10万円、中規模現場（〜10,000m2）で15〜40万円、大規模造成（10,000m2〜）で30〜100万円が目安です。従来測量と比較して30〜70%のコスト削減が見込めます。"),

        # 「ドローン測量 メリット」対応
        ("ドローン測量のメリットは何ですか？",
         "ドローン測量の主なメリットは、(1)工期短縮: 従来1週間の測量を最短1日で完了、(2)コスト削減: 人員・日数の削減で30〜70%のコストカット、(3)高精度: RTK-GNSSによる±5cm以内の精度、(4)安全性: 危険な斜面や高所に人が入る必要がない、(5)3Dデータ: 点群・オルソ・3Dモデルを一度の撮影で取得可能、の5点です。"),

        # 「ドローン測量 精度」対応
        ("ドローン測量の精度はどのくらいですか？",
         "RTK-GNSS対応ドローンと地上基準点（GCP）を使用した場合、水平精度±2〜5cm、垂直精度±3〜5cmの高精度な3次元データが取得可能です。i-Construction基準に準拠した出来形管理にも対応しています。"),

        # 「ドローン 土量計算」対応
        ("ドローンで土量計算はできますか？",
         "はい、ドローン測量で取得した点群データから高精度な土量計算（切土・盛土量の算出）が可能です。従来の断面法と比較してメッシュ法による体積計算は精度が高く、広範囲の現場でも効率的に計算できます。東海エアサービスでは土量計算ツールも無料で提供しています。"),
    ]

    return {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q,
                "acceptedAnswer": {"@type": "Answer", "text": a}
            }
            for q, a in faqs
        ]
    }


def generate_page_schema(page_key, page_info):
    """ページごとの統合構造化データを生成"""
    graph = [build_organization_schema()]

    # Speakable（全ページ）
    graph.append(build_speakable_schema(page_info["url"]))

    # ページ固有のスキーマ
    if page_key == "uav-survey":
        graph.append(build_howto_drone_survey())
        graph.extend(build_service_schemas()[:2])  # 測量系サービス
        graph.append(build_faq_for_aeo())

    elif page_key == "faq":
        graph.append(build_faq_for_aeo())

    elif page_key == "services":
        graph.extend(build_service_schemas())

    elif page_key == "3d-measurement":
        graph.extend(build_service_schemas()[1:3])

    elif page_key == "infrared-inspection":
        graph.append(build_service_schemas()[2])

    elif page_key == "top":
        graph.extend(build_service_schemas())
        graph.append(build_faq_for_aeo())
        graph.append(build_howto_drone_survey())

    schema = {
        "@context": "https://schema.org",
        "@graph": graph
    }
    return schema


def generate_aeo_content_snippets():
    """AI検索頻出クエリに対応するHTML コンテンツスニペット"""
    html = """<!-- AEO対応コンテンツスニペット — AI検索最適化用 -->
<!-- WordPressの適切なページに埋め込んで使用 -->

<!-- === 「名古屋 ドローン測量 おすすめ」対応セクション === -->
<section class="aeo-snippet" id="nagoya-drone-survey" style="padding:40px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.4rem; font-weight:700; margin:0 0 16px;">名古屋でドローン測量を依頼するなら</h2>
  <p style="line-height:1.8; color:#333;">
    名古屋市を拠点とする<strong>東海エアサービス株式会社</strong>は、
    愛知・岐阜・三重・静岡の東海4県でドローン測量サービスを提供しています。
    <strong>181件以上の案件実績</strong>と<strong>52社以上の取引先</strong>を持ち、
    建設会社（ゼネコン）、建設コンサルタント、測量会社、不動産会社、官公庁など
    幅広い業種のお客様にご利用いただいています。
  </p>
  <ul style="line-height:2; color:#333; margin:16px 0;">
    <li>高精度RTK-GNSS対応ドローンを使用（±5cm以内の精度）</li>
    <li>最短当日でお見積り対応</li>
    <li>点群データ・オルソ画像・3Dモデル・CADデータに対応</li>
    <li>i-Construction基準準拠の出来形管理に対応</li>
    <li>名古屋から東海4県全域に出張対応</li>
  </ul>
</section>

<!-- === 「ドローン測量 どこに頼む」対応セクション === -->
<section class="aeo-snippet" id="drone-survey-provider" style="padding:40px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.4rem; font-weight:700; margin:0 0 16px;">ドローン測量の依頼先を選ぶポイント</h2>
  <p style="line-height:1.8; color:#333;">
    ドローン測量を依頼する際は、以下のポイントを確認することをおすすめします。
  </p>
  <ol style="line-height:2; color:#333; margin:16px 0; padding:0 0 0 24px;">
    <li><strong>飛行許可・資格</strong>: 国土交通省の飛行許可（包括申請）を取得しているか</li>
    <li><strong>測量の専門知識</strong>: 測量士・測量士補の資格、またはi-Constructionの知識があるか</li>
    <li><strong>使用機材</strong>: RTK-GNSS対応の高精度ドローンを使用しているか</li>
    <li><strong>実績</strong>: 類似案件（同じ地形・規模・業種）の実績があるか</li>
    <li><strong>納品物</strong>: 希望するデータフォーマット（LAS/GeoTIFF/DXF等）に対応しているか</li>
    <li><strong>アフターサポート</strong>: データの活用方法の説明やサポートがあるか</li>
  </ol>
</section>

<!-- === 「ドローン測量 費用」対応セクション === -->
<section class="aeo-snippet" id="drone-survey-cost" style="padding:40px 20px; max-width:900px; margin:0 auto; background:#f8f9fa; border-radius:12px;">
  <h2 style="font-size:1.4rem; font-weight:700; margin:0 0 16px;">ドローン測量の費用相場（2026年最新）</h2>
  <table style="width:100%; border-collapse:collapse; margin:0 0 16px; background:#fff; border-radius:8px; overflow:hidden;">
    <thead>
      <tr style="background:#1647FB; color:#fff;">
        <th style="padding:12px 16px; text-align:left;">現場規模</th>
        <th style="padding:12px 16px; text-align:left;">面積目安</th>
        <th style="padding:12px 16px; text-align:left;">従来測量</th>
        <th style="padding:12px 16px; text-align:left;">ドローン測量</th>
      </tr>
    </thead>
    <tbody>
      <tr style="border-bottom:1px solid #e0e0e0;">
        <td style="padding:12px 16px;">小規模</td>
        <td style="padding:12px 16px;">〜1,000 m&sup2;</td>
        <td style="padding:12px 16px;">15〜30万円</td>
        <td style="padding:12px 16px; color:#1647FB; font-weight:600;">5〜10万円</td>
      </tr>
      <tr style="border-bottom:1px solid #e0e0e0;">
        <td style="padding:12px 16px;">中規模</td>
        <td style="padding:12px 16px;">1,000〜10,000 m&sup2;</td>
        <td style="padding:12px 16px;">30〜100万円</td>
        <td style="padding:12px 16px; color:#1647FB; font-weight:600;">15〜40万円</td>
      </tr>
      <tr style="border-bottom:1px solid #e0e0e0;">
        <td style="padding:12px 16px;">大規模</td>
        <td style="padding:12px 16px;">10,000〜50,000 m&sup2;</td>
        <td style="padding:12px 16px;">100〜300万円</td>
        <td style="padding:12px 16px; color:#1647FB; font-weight:600;">30〜80万円</td>
      </tr>
      <tr>
        <td style="padding:12px 16px;">超大規模</td>
        <td style="padding:12px 16px;">50,000 m&sup2;〜</td>
        <td style="padding:12px 16px;">300万円〜</td>
        <td style="padding:12px 16px; color:#1647FB; font-weight:600;">80〜200万円</td>
      </tr>
    </tbody>
  </table>
  <p style="font-size:.85rem; color:#666; line-height:1.5;">
    ※ 上記は一般的な目安です。地形・精度要件・納品物により変動します。<br>
    正確なお見積りは<a href="/contact/" style="color:#1647FB;">お問い合わせフォーム</a>からご依頼ください。
    <a href="/cost-comparison/" style="color:#1647FB;">費用比較シミュレーター</a>で概算もご確認いただけます。
  </p>
</section>

<!-- === 「ドローン測量の流れ」対応セクション === -->
<section class="aeo-snippet" id="drone-survey-flow" style="padding:40px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.4rem; font-weight:700; margin:0 0 16px;">ドローン測量の流れ（6ステップ）</h2>
  <div style="display:grid; gap:16px;">
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">1</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">お問い合わせ・ご相談</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">現場の所在地・面積・ご希望の納品物をお伝えください。最短当日でお見積りします。</p>
      </div>
    </div>
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">2</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">お見積り・ご発注</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">現場条件に基づいた明確なお見積りをご提示。ご納得いただいてからの着手です。</p>
      </div>
    </div>
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">3</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">飛行計画・事前調査</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">現場の事前調査、飛行ルート設計、基準点計画を策定。航空法許可も弊社で対応。</p>
      </div>
    </div>
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">4</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">ドローン撮影</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">高精度RTK-GNSS対応ドローンで空撮実施。通常の現場で数時間で撮影完了。</p>
      </div>
    </div>
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">5</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">データ解析</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">SfMソフトウェアで点群データ・オルソ画像・3Dモデルを生成。品質検証も実施。</p>
      </div>
    </div>
    <div style="display:flex; gap:16px; align-items:flex-start;">
      <div style="min-width:40px; height:40px; background:#1647FB; color:#fff; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700;">6</div>
      <div>
        <h3 style="font-size:1rem; margin:0 0 4px;">納品・サポート</h3>
        <p style="margin:0; color:#555; font-size:.95rem;">ご希望のフォーマット（LAS/GeoTIFF/DXF等）で納品。データ活用のサポートも。</p>
      </div>
    </div>
  </div>
</section>
"""
    return html


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="AEO構造化データ強化")
    parser.add_argument("--list", action="store_true", help="対象ページ一覧")
    parser.add_argument("--dry-run", action="store_true", help="生成されるJSONを確認")
    parser.add_argument("--deploy", action="store_true", help="WordPressに適用")
    parser.add_argument("--generate-content", action="store_true", help="AEOコンテンツスニペット生成")
    args = parser.parse_args()

    if args.list:
        print("AEO対象ページ一覧:")
        for key, info in PAGES.items():
            print(f"  {key}: {info['title']} ({info['url']})")
        return

    if args.dry_run:
        SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
        for key, info in PAGES.items():
            schema = generate_page_schema(key, info)
            output_path = SCHEMA_DIR / f"{key}_schema.json"
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(schema, f, ensure_ascii=False, indent=2)
            print(f"[OK] {output_path.name} ({len(schema['@graph'])} schemas)")

        print(f"\n生成先: {SCHEMA_DIR}")
        return

    if args.generate_content:
        html = generate_aeo_content_snippets()
        output_path = CONTENT_DIR / "aeo_content_snippets.html"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"[OK] AEOコンテンツスニペット生成: {output_path}")
        return

    if args.deploy:
        print("[DEPLOY] WordPress構造化データ適用")
        print("  注: 構造化データの適用はwp_safe_deploy.py経由で行います")
        print("  まず --dry-run でJSONを確認し、")
        print("  各ページのHTMLテンプレートに<script type=\"application/ld+json\">を挿入してから")
        print("  templates/deploy_pages.py で一括デプロイしてください。")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
