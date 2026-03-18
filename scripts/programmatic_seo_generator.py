#!/usr/bin/env python3
"""
プログラマティックSEO — 地域別ランディングページ自動生成

愛知県・三重県・岐阜県・静岡県の主要市区町村ごとに
「{市区町村名} ドローン測量 | 東海エアサービス」のLPを自動生成する。

各ページに含まれるもの:
  - その地域の測量需要（建設・インフラ）
  - 対応実績（CRM受注台帳から匿名化統計を自動引用）
  - アクセス情報（名古屋からの距離・所要時間）
  - 料金目安
  - FAQ構造化データ + LocalBusiness構造化データ

Usage:
  python3 programmatic_seo_generator.py --dry-run          # 10ページ分HTML生成（確認用）
  python3 programmatic_seo_generator.py --dry-run --all    # 全ページHTML生成（確認用）
  python3 programmatic_seo_generator.py --deploy           # WordPress下書きとして作成
  python3 programmatic_seo_generator.py --deploy --publish # WordPress公開

出力:
  - content/seo_moat_dry_run/*.html  (dry-run時)
  - WordPress固定ページ /area/{slug}/ (deploy時)
"""

import json
import sys
import os
import re
import time
import base64
import urllib.request
import urllib.error
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content"
DRY_RUN_DIR = CONTENT_DIR / "seo_moat_dry_run"

sys.path.insert(0, str(SCRIPT_DIR))
from lib.config import load_config, get_wp_auth, get_wp_api_url
from lib.lark_api import lark_get_token, lark_list_records

# ── 定数 ──
PHONE = "050-7117-7141"
BRAND_COLOR = "#1647FB"
BRAND_DARK = "#0d2f99"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"
COMPANY_NAME = "東海エアサービス株式会社"
BASE_ADDRESS = "愛知県名古屋市"

# ── 市区町村データ ──
# 主要市区町村（建設・インフラ需要が高い都市を優先選定）
MUNICIPALITIES = {
    "愛知県": {
        "region_slug": "aichi",
        "cities": [
            {"name": "名古屋市", "slug": "nagoya", "desc": "中部地方最大の都市。再開発事業やリニア中央新幹線関連工事など大規模建設プロジェクトが進行中。", "demand": "都市再開発、リニア関連工事、道路インフラ整備", "distance": "拠点所在地"},
            {"name": "豊田市", "slug": "toyota", "desc": "自動車産業の中心地。工場敷地の測量や周辺インフラ整備の需要が高い。", "demand": "工場用地測量、道路・橋梁点検、造成工事", "distance": "名古屋から約40分"},
            {"name": "岡崎市", "slug": "okazaki", "desc": "三河地域の中核都市。住宅開発や河川整備事業が活発。", "demand": "宅地造成、河川測量、公共工事", "distance": "名古屋から約50分"},
            {"name": "一宮市", "slug": "ichinomiya", "desc": "尾張西部の中心都市。都市計画道路や区画整理事業が進行。", "demand": "区画整理、道路建設、上下水道整備", "distance": "名古屋から約20分"},
            {"name": "豊橋市", "slug": "toyohashi", "desc": "東三河の中核都市。港湾施設や農業基盤整備の測量需要がある。", "demand": "港湾施設、農地測量、工業団地造成", "distance": "名古屋から約80分"},
            {"name": "春日井市", "slug": "kasugai", "desc": "名古屋市北東のベッドタウン。宅地開発や道路整備が活発。", "demand": "宅地造成、道路・上下水道整備、砕石場管理", "distance": "名古屋から約25分"},
            {"name": "安城市", "slug": "anjo", "desc": "日本のデンマークと呼ばれる農業都市。農業基盤整備と工業団地の需要。", "demand": "農地整備、工場用地測量、区画整理", "distance": "名古屋から約40分"},
            {"name": "豊川市", "slug": "toyokawa", "desc": "東三河の工業都市。工場跡地の再開発や河川整備が進行。", "demand": "工業団地、河川堤防測量、太陽光発電用地", "distance": "名古屋から約70分"},
            {"name": "西尾市", "slug": "nishio", "desc": "矢作川下流域の都市。河川・海岸線の測量需要が高い。", "demand": "河川測量、海岸保全、農地整備", "distance": "名古屋から約55分"},
            {"name": "小牧市", "slug": "komaki", "desc": "名古屋北部の物流拠点。倉庫・物流施設建設に伴う測量需要。", "demand": "物流施設建設、道路整備、工業用地", "distance": "名古屋から約25分"},
            {"name": "半田市", "slug": "handa", "desc": "知多半島の中核都市。臨海工業地帯や都市基盤整備の需要。", "demand": "臨海施設、道路・橋梁、住宅開発", "distance": "名古屋から約35分"},
            {"name": "刈谷市", "slug": "kariya", "desc": "自動車部品産業の集積地。工場拡張や周辺インフラ整備。", "demand": "工場用地、道路建設、区画整理", "distance": "名古屋から約35分"},
            {"name": "瀬戸市", "slug": "seto", "desc": "陶磁器の街。丘陵地の造成工事や万博跡地の再開発。", "demand": "造成工事、丘陵地測量、再開発事業", "distance": "名古屋から約30分"},
            {"name": "東海市", "slug": "tokai", "desc": "名古屋南部の臨海工業都市。製鉄所や港湾関連施設の測量。", "demand": "臨海工業施設、港湾測量、道路整備", "distance": "名古屋から約25分"},
            {"name": "大府市", "slug": "obu", "desc": "名古屋南部の住宅都市。健康の森周辺の開発が進行。", "demand": "住宅開発、道路建設、公共施設", "distance": "名古屋から約25分"},
        ]
    },
    "岐阜県": {
        "region_slug": "gifu",
        "cities": [
            {"name": "岐阜市", "slug": "gifu-city", "desc": "岐阜県の県庁所在地。長良川周辺の河川整備や都市再開発が活発。", "demand": "河川整備、都市再開発、道路建設", "distance": "名古屋から約30分"},
            {"name": "大垣市", "slug": "ogaki", "desc": "西濃地域の中心都市。水の都として河川インフラの整備需要が高い。", "demand": "河川堤防、治水施設、工業団地", "distance": "名古屋から約40分"},
            {"name": "各務原市", "slug": "kakamigahara", "desc": "航空宇宙産業の集積地。大規模工場敷地や河川敷の測量需要。", "demand": "航空関連施設、河川敷測量、住宅開発", "distance": "名古屋から約40分"},
            {"name": "多治見市", "slug": "tajimi", "desc": "東濃地域の商業都市。丘陵地の宅地造成や道路整備。", "demand": "宅地造成、道路建設、商業施設", "distance": "名古屋から約45分"},
            {"name": "関市", "slug": "seki", "desc": "刃物の街。中濃地域の工業・商業施設建設に伴う測量需要。", "demand": "工業施設、道路整備、山間部測量", "distance": "名古屋から約50分"},
            {"name": "中津川市", "slug": "nakatsugawa", "desc": "リニア中央新幹線の岐阜県駅が建設予定。関連インフラ整備が本格化。", "demand": "リニア関連工事、道路建設、トンネル測量", "distance": "名古屋から約70分"},
            {"name": "可児市", "slug": "kani", "desc": "名古屋のベッドタウン。住宅団地の再整備や道路建設が進行。", "demand": "住宅団地、道路整備、河川管理", "distance": "名古屋から約50分"},
            {"name": "高山市", "slug": "takayama", "desc": "日本一面積の広い市。山岳部のインフラ整備や観光施設建設の需要。", "demand": "山岳道路、観光施設、林道整備", "distance": "名古屋から約150分"},
        ]
    },
    "三重県": {
        "region_slug": "mie",
        "cities": [
            {"name": "津市", "slug": "tsu", "desc": "三重県の県庁所在地。港湾施設や河川整備、大学関連施設の建設需要。", "demand": "港湾施設、河川整備、公共工事", "distance": "名古屋から約60分"},
            {"name": "四日市市", "slug": "yokkaichi", "desc": "石油化学コンビナートを擁する工業都市。大規模プラントやインフラの測量需要。", "demand": "コンビナート施設、道路建設、港湾整備", "distance": "名古屋から約40分"},
            {"name": "鈴鹿市", "slug": "suzuka", "desc": "鈴鹿サーキットで知られる工業都市。自動車関連工場や住宅開発の需要。", "demand": "工場用地、住宅開発、道路整備", "distance": "名古屋から約50分"},
            {"name": "松阪市", "slug": "matsusaka", "desc": "三重県中部の商業都市。農業基盤整備と工業団地の測量需要。", "demand": "農地整備、工業団地、道路建設", "distance": "名古屋から約80分"},
            {"name": "桑名市", "slug": "kuwana", "desc": "名古屋に隣接する商業都市。大規模商業施設や住宅開発が進行。", "demand": "商業施設、住宅開発、河川堤防", "distance": "名古屋から約30分"},
            {"name": "伊勢市", "slug": "ise", "desc": "伊勢神宮の門前都市。観光インフラ整備や沿岸部の防災施設建設。", "demand": "観光インフラ、海岸保全、公共施設", "distance": "名古屋から約90分"},
            {"name": "伊賀市", "slug": "iga", "desc": "忍者の里。山間部のインフラ整備や農地の基盤整備。", "demand": "山間部道路、農地整備、太陽光発電用地", "distance": "名古屋から約70分"},
            {"name": "名張市", "slug": "nabari", "desc": "大阪のベッドタウン。住宅団地の再整備や道路建設の需要。", "demand": "住宅団地再整備、道路建設、河川管理", "distance": "名古屋から約90分"},
            {"name": "亀山市", "slug": "kameyama", "desc": "東名阪自動車道の要衝。物流施設建設や工業団地整備の需要。", "demand": "物流施設、工業団地、道路建設", "distance": "名古屋から約55分"},
            {"name": "いなべ市", "slug": "inabe", "desc": "北勢地域の自然豊かな都市。セメント産業や砕石場の測量需要。", "demand": "砕石場測量、道路建設、農地整備", "distance": "名古屋から約50分"},
        ]
    },
    "静岡県": {
        "region_slug": "shizuoka",
        "cities": [
            {"name": "静岡市", "slug": "shizuoka-city", "desc": "静岡県の県庁所在地。清水港周辺の再開発や駿河湾沿岸の防災施設。", "demand": "港湾再開発、防災施設、道路建設", "distance": "名古屋から約120分"},
            {"name": "浜松市", "slug": "hamamatsu", "desc": "静岡県最大の都市。楽器・自動車産業の拠点で工場施設の測量需要が高い。", "demand": "工場用地、道路建設、河川整備", "distance": "名古屋から約80分"},
            {"name": "沼津市", "slug": "numazu", "desc": "駿河湾に面した都市。港湾施設や防災インフラの測量需要。", "demand": "港湾施設、防災インフラ、商業施設", "distance": "名古屋から約150分"},
            {"name": "富士市", "slug": "fuji", "desc": "製紙産業の中心地。工場施設や富士山麓の開発に伴う測量需要。", "demand": "工場施設、河川管理、道路建設", "distance": "名古屋から約140分"},
            {"name": "磐田市", "slug": "iwata", "desc": "自動車・楽器産業の集積地。工場拡張や農地の基盤整備。", "demand": "工場用地、農地整備、河川堤防", "distance": "名古屋から約90分"},
            {"name": "掛川市", "slug": "kakegawa", "desc": "東名高速と新幹線が交差する交通の要衝。物流施設建設の需要。", "demand": "物流施設、茶畑測量、道路建設", "distance": "名古屋から約100分"},
            {"name": "藤枝市", "slug": "fujieda", "desc": "静岡県中部の住宅都市。宅地造成や道路整備の測量需要。", "demand": "宅地造成、道路整備、農地転用", "distance": "名古屋から約110分"},
            {"name": "湖西市", "slug": "kosai", "desc": "浜名湖西岸の都市。浜名湖周辺の開発や自動車関連工場の測量。", "demand": "工場用地、湖岸整備、住宅開発", "distance": "名古屋から約70分"},
        ]
    },
}


# ── CRM統計取得 ──

def _extract_text(value):
    """Larkフィールド値からテキスト抽出"""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item.get("text", item.get("name", str(item)))
            return str(item)
        return ""
    if isinstance(value, dict):
        return value.get("text", value.get("name", str(value)))
    return str(value) if value else ""


def fetch_crm_stats(cfg):
    """受注台帳から匿名化統計データを取得"""
    print("[CRM] 受注台帳から実績データ取得中...")
    token = lark_get_token(cfg)
    records = lark_list_records(token, ORDER_TABLE_ID, cfg=cfg)
    print(f"  取得レコード数: {len(records)}")

    non_case = re.compile(r"支払通知書|支払明細|営業代行|送付$")

    stats = {
        "total_cases": 0,
        "total_companies": set(),
        "by_service": defaultdict(int),
        "by_industry": defaultdict(int),
        "by_prefecture": defaultdict(int),
    }

    for rec in records:
        fields = rec.get("fields", {})
        case_name = _extract_text(fields.get("案件名", ""))
        company = _extract_text(fields.get("取引先", ""))

        if non_case.search(case_name):
            continue
        if not case_name.strip():
            continue

        stats["total_cases"] += 1
        if company:
            stats["total_companies"].add(company)

        # 業種分類
        text = company + " " + case_name
        industry = "その他"
        for ind, keywords in {
            "ゼネコン": ["建設", "組", "工業", "工務", "土木", "鳶", "基礎", "舗装"],
            "建設コンサルタント": ["コンサルタント", "コンサル", "設計", "技研"],
            "測量会社": ["測量", "工測"],
            "不動産": ["不動産", "デベロッパー", "地所"],
            "官公庁": ["市役所", "県庁", "事務所", "高校", "学校", "国交省"],
        }.items():
            if any(kw in text for kw in keywords):
                industry = ind
                break
        stats["by_industry"][industry] += 1

        # サービス種別
        service = "その他"
        for svc, keywords in {
            "ドローン測量": ["測量", "土量", "点群"],
            "現場空撮": ["空撮", "撮影"],
            "眺望撮影": ["眺望"],
            "点検": ["点検", "赤外線"],
        }.items():
            if any(kw in case_name for kw in keywords):
                service = svc
                break
        stats["by_service"][service] += 1

    stats["total_companies"] = len(stats["total_companies"])
    print(f"  統計: {stats['total_cases']}件 / {stats['total_companies']}社")
    return stats


# ── HTMLテンプレート生成 ──

def build_structured_data(city_name, prefecture, slug):
    """FAQPage + LocalBusiness + BreadcrumbList 構造化データ"""
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "LocalBusiness",
                "@id": "https://tokaiair.com/#organization",
                "name": COMPANY_NAME,
                "url": "https://tokaiair.com/",
                "telephone": PHONE,
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "名古屋市",
                    "addressRegion": "愛知県",
                    "addressCountry": "JP"
                },
                "areaServed": {
                    "@type": "City",
                    "name": city_name,
                    "containedInPlace": {"@type": "State", "name": prefecture}
                },
                "priceRange": "$$"
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1,
                     "name": "ホーム", "item": "https://tokaiair.com/"},
                    {"@type": "ListItem", "position": 2,
                     "name": "対応エリア", "item": "https://tokaiair.com/area/"},
                    {"@type": "ListItem", "position": 3,
                     "name": f"{city_name}のドローン測量",
                     "item": f"https://tokaiair.com/area/{slug}/"}
                ]
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": f"{city_name}でドローン測量を依頼するにはどうすればよいですか？",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"東海エアサービスでは{city_name}エリアのドローン測量に対応しております。お電話（{PHONE}）またはお問い合わせフォームからご連絡ください。最短当日でお見積りをお出しします。"
                        }
                    },
                    {
                        "@type": "Question",
                        "name": f"{city_name}のドローン測量の費用はいくらですか？",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "現場の面積・地形・精度要件により異なりますが、一般的なドローン測量は数万円から対応可能です。従来の測量方法と比較して30〜70%のコスト削減が見込めます。"
                        }
                    },
                    {
                        "@type": "Question",
                        "name": f"{city_name}への出張費はかかりますか？",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": f"{city_name}は東海エアサービスの対応エリア内です。名古屋の拠点から直接お伺いいたします。出張費については現場の所在地により異なりますので、お見積り時にご確認ください。"
                        }
                    },
                    {
                        "@type": "Question",
                        "name": "ドローン測量のデータ納品形式は？",
                        "acceptedAnswer": {
                            "@type": "Answer",
                            "text": "点群データ（LAS/LAZ）、オルソ画像（GeoTIFF）、3Dモデル（OBJ）、CADデータ（DXF/DWG）など主要フォーマットに対応。お使いの施工管理ソフトやCADに合わせた形式で納品いたします。"
                        }
                    }
                ]
            },
            {
                "@type": "Service",
                "name": f"{city_name}のドローン測量サービス",
                "description": f"{city_name}エリアでのドローン測量・3次元データ取得サービス。高精度な点群データ・オルソ画像を短工期で納品。",
                "provider": {
                    "@type": "LocalBusiness",
                    "name": COMPANY_NAME,
                    "telephone": PHONE
                },
                "areaServed": {
                    "@type": "City",
                    "name": city_name
                }
            }
        ]
    }
    return json.dumps(graph, ensure_ascii=False, indent=2)


def generate_page_html(city, prefecture, stats):
    """地域別LPのHTMLを生成"""
    city_name = city["name"]
    slug = city["slug"]
    desc = city["desc"]
    demand = city["demand"]
    distance = city["distance"]

    total_cases = stats["total_cases"]
    total_companies = stats["total_companies"]

    structured_data = build_structured_data(city_name, prefecture, slug)

    html = f"""<!-- {city_name} ドローン測量 | 東海エアサービス — 自動生成ページ -->
<script type="application/ld+json">
{structured_data}
</script>

<div class="page-hero" style="background:linear-gradient(135deg, {BRAND_COLOR} 0%, {BRAND_DARK} 100%); color:#fff; padding:60px 20px; text-align:center;">
  <p style="font-size:.9rem; margin:0 0 8px; opacity:.85;">{prefecture} &gt; {city_name}</p>
  <h1 style="font-size:2rem; margin:0 0 16px; font-weight:800;">{city_name}のドローン測量</h1>
  <p style="font-size:1.1rem; margin:0; max-width:700px; margin-inline:auto; line-height:1.7;">
    {desc}<br>
    東海エアサービスは{city_name}エリアのドローン測量に対応しています。
  </p>
</div>

<!-- 実績バナー -->
<section style="background:#f8f9fa; padding:32px 20px; text-align:center;">
  <div style="display:flex; justify-content:center; gap:40px; flex-wrap:wrap; max-width:700px; margin:0 auto;">
    <div>
      <span style="font-size:2.5rem; font-weight:800; color:{BRAND_COLOR};">{total_cases}+</span>
      <p style="margin:4px 0 0; font-size:.9rem; color:#555;">案件実績</p>
    </div>
    <div>
      <span style="font-size:2.5rem; font-weight:800; color:{BRAND_COLOR};">{total_companies}+</span>
      <p style="margin:4px 0 0; font-size:.9rem; color:#555;">取引先企業</p>
    </div>
    <div>
      <span style="font-size:2.5rem; font-weight:800; color:{BRAND_COLOR};">4</span>
      <p style="margin:4px 0 0; font-size:.9rem; color:#555;">対応県</p>
    </div>
  </div>
</section>

<!-- {city_name}の測量需要 -->
<section style="padding:48px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.5rem; font-weight:700; margin:0 0 24px; color:#1a1a1a;">
    {city_name}における測量需要
  </h2>
  <p style="line-height:1.8; color:#333; margin:0 0 16px;">
    {desc}
  </p>
  <p style="line-height:1.8; color:#333; margin:0 0 24px;">
    {city_name}では特に<strong>{demand}</strong>などの分野でドローン測量の需要が高まっています。
    従来の測量方法と比較して、ドローン測量は<strong>工期を50〜80%短縮</strong>し、
    <strong>コストを30〜70%削減</strong>できるため、多くの建設・インフラ事業者様にご採用いただいています。
  </p>

  <div style="background:#f0f4ff; border-radius:12px; padding:24px; margin:0 0 32px;">
    <h3 style="font-size:1.1rem; color:{BRAND_COLOR}; margin:0 0 12px;">
      {city_name}で活用されるドローン測量サービス
    </h3>
    <ul style="margin:0; padding:0 0 0 20px; line-height:2;">
      <li><strong>3次元測量（点群データ取得）</strong> — 造成現場・建設用地の高精度3Dデータ</li>
      <li><strong>土量計算</strong> — 切土・盛土の正確な体積算出</li>
      <li><strong>オルソ画像作成</strong> — 広域現場の正射投影画像</li>
      <li><strong>進捗管理空撮</strong> — 工事の定期記録撮影</li>
      <li><strong>インフラ点検</strong> — 橋梁・建物の赤外線サーモグラフィ点検</li>
    </ul>
  </div>
</section>

<!-- ドローン測量のメリット -->
<section style="background:#f8f9fa; padding:48px 20px;">
  <div style="max-width:900px; margin:0 auto;">
    <h2 style="font-size:1.5rem; font-weight:700; margin:0 0 24px; color:#1a1a1a;">
      {city_name}でドローン測量を選ぶメリット
    </h2>
    <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(250px, 1fr)); gap:20px;">
      <div style="background:#fff; border-radius:12px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,.06);">
        <h3 style="font-size:1.05rem; color:{BRAND_COLOR}; margin:0 0 8px;">工期短縮</h3>
        <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
          従来1週間かかる測量を最短1日で完了。{city_name}の現場に迅速に対応します。
        </p>
      </div>
      <div style="background:#fff; border-radius:12px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,.06);">
        <h3 style="font-size:1.05rem; color:{BRAND_COLOR}; margin:0 0 8px;">コスト削減</h3>
        <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
          人員と日数を大幅に削減。測量コストを30〜70%カットできます。
        </p>
      </div>
      <div style="background:#fff; border-radius:12px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,.06);">
        <h3 style="font-size:1.05rem; color:{BRAND_COLOR}; margin:0 0 8px;">高精度データ</h3>
        <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
          RTK-GNSS基準点を使用した高精度3次元データ。±5cm以内の精度を実現。
        </p>
      </div>
      <div style="background:#fff; border-radius:12px; padding:24px; box-shadow:0 2px 8px rgba(0,0,0,.06);">
        <h3 style="font-size:1.05rem; color:{BRAND_COLOR}; margin:0 0 8px;">安全性</h3>
        <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
          危険な斜面や高所に人が入る必要がありません。作業員の安全を確保します。
        </p>
      </div>
    </div>
  </div>
</section>

<!-- アクセス・対応情報 -->
<section style="padding:48px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.5rem; font-weight:700; margin:0 0 24px; color:#1a1a1a;">
    {city_name}へのアクセス・対応情報
  </h2>
  <table style="width:100%; border-collapse:collapse; margin:0 0 24px;">
    <tr style="border-bottom:1px solid #e0e0e0;">
      <td style="padding:12px 16px; font-weight:600; width:160px; color:#333;">対応エリア</td>
      <td style="padding:12px 16px; color:#555;">{prefecture} {city_name} 全域</td>
    </tr>
    <tr style="border-bottom:1px solid #e0e0e0;">
      <td style="padding:12px 16px; font-weight:600; color:#333;">拠点からの距離</td>
      <td style="padding:12px 16px; color:#555;">{distance}</td>
    </tr>
    <tr style="border-bottom:1px solid #e0e0e0;">
      <td style="padding:12px 16px; font-weight:600; color:#333;">対応サービス</td>
      <td style="padding:12px 16px; color:#555;">ドローン測量、3次元計測、空撮、赤外線点検</td>
    </tr>
    <tr style="border-bottom:1px solid #e0e0e0;">
      <td style="padding:12px 16px; font-weight:600; color:#333;">見積り</td>
      <td style="padding:12px 16px; color:#555;">最短当日対応</td>
    </tr>
    <tr style="border-bottom:1px solid #e0e0e0;">
      <td style="padding:12px 16px; font-weight:600; color:#333;">料金目安</td>
      <td style="padding:12px 16px; color:#555;">数万円〜（面積・精度により変動）</td>
    </tr>
  </table>
</section>

<!-- FAQ -->
<section style="background:#f8f9fa; padding:48px 20px;">
  <div style="max-width:900px; margin:0 auto;">
    <h2 style="font-size:1.5rem; font-weight:700; margin:0 0 24px; color:#1a1a1a;">
      {city_name}のドローン測量 — よくあるご質問
    </h2>

    <div style="margin:0 0 16px; background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <h3 style="font-size:1rem; margin:0 0 8px; color:#1a1a1a;">Q. {city_name}でドローン測量を依頼するにはどうすればよいですか？</h3>
      <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
        A. お電話（{PHONE}）またはお問い合わせフォームからご連絡ください。
        現場の所在地・面積・ご希望の納品物をお伝えいただければ、最短当日でお見積りをお出しします。
      </p>
    </div>

    <div style="margin:0 0 16px; background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <h3 style="font-size:1rem; margin:0 0 8px; color:#1a1a1a;">Q. {city_name}のドローン測量の費用はいくらですか？</h3>
      <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
        A. 現場の面積・地形・精度要件により異なりますが、一般的なドローン測量は数万円から対応可能です。
        従来の測量方法と比較して30〜70%のコスト削減が見込めます。詳しくはお見積りをご依頼ください。
      </p>
    </div>

    <div style="margin:0 0 16px; background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <h3 style="font-size:1rem; margin:0 0 8px; color:#1a1a1a;">Q. {city_name}への出張費はかかりますか？</h3>
      <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
        A. {city_name}は東海エアサービスの対応エリア内です。
        出張費については現場の所在地により異なりますので、お見積り時にご確認ください。
      </p>
    </div>

    <div style="margin:0 0 16px; background:#fff; border-radius:8px; padding:20px; box-shadow:0 1px 4px rgba(0,0,0,.05);">
      <h3 style="font-size:1rem; margin:0 0 8px; color:#1a1a1a;">Q. ドローン測量のデータ納品形式は？</h3>
      <p style="margin:0; font-size:.95rem; color:#555; line-height:1.6;">
        A. 点群データ（LAS/LAZ）、オルソ画像（GeoTIFF）、3Dモデル（OBJ）、CADデータ（DXF/DWG）など
        主要フォーマットに対応しています。お使いの施工管理ソフトやCADに合わせた形式で納品いたします。
      </p>
    </div>
  </div>
</section>

<!-- CTA -->
<section style="padding:48px 20px; text-align:center; background:linear-gradient(135deg, {BRAND_COLOR} 0%, {BRAND_DARK} 100%); color:#fff;">
  <h2 style="font-size:1.5rem; font-weight:700; margin:0 0 12px;">
    {city_name}のドローン測量はお任せください
  </h2>
  <p style="font-size:1rem; margin:0 0 24px; opacity:.9; max-width:600px; margin-inline:auto; line-height:1.7;">
    {total_cases}件以上の実績を持つ東海エアサービスが、{city_name}の現場に最適な測量プランをご提案します。
    まずはお気軽にご相談ください。
  </p>
  <div style="display:flex; gap:16px; justify-content:center; flex-wrap:wrap;">
    <a href="/contact/" style="display:inline-block; padding:16px 36px; background:#fff; color:{BRAND_COLOR}; text-decoration:none; border-radius:8px; font-weight:700; font-size:1rem;">
      無料見積りを依頼する
    </a>
    <a href="tel:{PHONE.replace('-', '')}" style="display:inline-block; padding:16px 36px; border:2px solid #fff; color:#fff; text-decoration:none; border-radius:8px; font-weight:700; font-size:1rem;">
      {PHONE}
    </a>
  </div>
  <p style="margin:16px 0 0; font-size:.85rem; opacity:.7;">
    <a href="/tools/earthwork/calculator/" style="color:#fff; text-decoration:underline;">土量計算ツールを試す</a>
    &nbsp;|&nbsp;
    <a href="/drone-survey-cost-comparison/" style="color:#fff; text-decoration:underline;">費用比較シミュレーター</a>
  </p>
</section>

<!-- 関連ページリンク -->
<section style="padding:32px 20px; max-width:900px; margin:0 auto;">
  <h2 style="font-size:1.2rem; font-weight:700; margin:0 0 16px; color:#1a1a1a;">関連ページ</h2>
  <ul style="margin:0; padding:0 0 0 20px; line-height:2;">
    <li><a href="/services/uav-survey/" style="color:{BRAND_COLOR};">ドローン測量サービス詳細</a></li>
    <li><a href="/services/3d-measurement/" style="color:{BRAND_COLOR};">3次元計測サービス</a></li>
    <li><a href="/case-library/cases/" style="color:{BRAND_COLOR};">実績事例一覧</a></li>
    <li><a href="/drone-survey-cost-comparison/" style="color:{BRAND_COLOR};">費用比較シミュレーター</a></li>
    <li><a href="/faq/" style="color:{BRAND_COLOR};">よくあるご質問</a></li>
    <li><a href="/drone-survey-statistics/" style="color:{BRAND_COLOR};">実績データ統計</a></li>
  </ul>
</section>
"""
    return html


# ── WordPress操作 ──

def create_or_update_wp_page(cfg, slug, title, content, parent_id=0, status="draft"):
    """WordPress固定ページを作成（or既存があれば更新）"""
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)

    # 既存ページを検索
    search_url = f"{base_url}/pages?slug={slug}&status=any"
    req = urllib.request.Request(search_url, headers={
        "Authorization": f"Basic {auth}"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            existing = json.loads(r.read())
    except Exception:
        existing = []

    data = {
        "title": title,
        "content": content,
        "status": status,
        "slug": slug,
    }
    if parent_id:
        data["parent"] = parent_id

    encoded = json.dumps(data).encode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }

    if existing:
        page_id = existing[0]["id"]
        url = f"{base_url}/pages/{page_id}"
        print(f"  既存ページ更新: ID={page_id} slug={slug}")
    else:
        url = f"{base_url}/pages"
        print(f"  新規ページ作成: slug={slug}")

    req = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.loads(r.read())
    return result


# ── メイン ──

def main():
    parser = argparse.ArgumentParser(description="プログラマティックSEO 地域別LP生成")
    parser.add_argument("--dry-run", action="store_true", help="HTML生成のみ（WP更新なし）")
    parser.add_argument("--all", action="store_true", help="全ページ生成（dry-runのデフォルトは10ページ）")
    parser.add_argument("--deploy", action="store_true", help="WordPressに下書き作成")
    parser.add_argument("--publish", action="store_true", help="公開状態で作成")
    parser.add_argument("--prefecture", type=str, help="特定県のみ生成（例: 愛知県）")
    parser.add_argument("--city", type=str, help="特定市のみ生成（例: nagoya）")
    args = parser.parse_args()

    if not args.dry_run and not args.deploy:
        print("Usage: --dry-run（HTML確認）or --deploy（WordPress作成）を指定してください")
        sys.exit(1)

    # CRM統計取得
    try:
        cfg = load_config()
        stats = fetch_crm_stats(cfg)
    except Exception as e:
        print(f"[WARN] CRM取得失敗（デフォルト値使用）: {e}")
        stats = {
            "total_cases": 180,
            "total_companies": 50,
            "by_service": {},
            "by_industry": {},
        }

    # ページ生成
    DRY_RUN_DIR.mkdir(exist_ok=True)
    generated = 0
    max_pages = 999 if args.all or args.deploy else 10

    for prefecture, region_data in MUNICIPALITIES.items():
        if args.prefecture and prefecture != args.prefecture:
            continue

        for city in region_data["cities"]:
            if args.city and city["slug"] != args.city:
                continue

            if generated >= max_pages:
                break

            slug = city["slug"]
            title = f'{city["name"]}のドローン測量 | {COMPANY_NAME}'
            html = generate_page_html(city, prefecture, stats)

            if args.dry_run:
                output_path = DRY_RUN_DIR / f"area_{slug}.html"
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"<!-- Title: {title} -->\n")
                    f.write(f"<!-- Slug: area/{slug} -->\n")
                    f.write(f"<!-- Prefecture: {prefecture} -->\n\n")
                    f.write(html)
                print(f"[{generated + 1}] 生成: {output_path.name} ({city['name']})")

            elif args.deploy:
                status = "publish" if args.publish else "draft"
                try:
                    result = create_or_update_wp_page(
                        cfg, slug=slug, title=title,
                        content=html, status=status
                    )
                    print(f"  URL: {result.get('link', 'N/A')}")
                    time.sleep(1)  # API rate limit
                except Exception as e:
                    print(f"  [ERROR] {city['name']}: {e}")

            generated += 1

        if generated >= max_pages:
            break

    print(f"\n完了: {generated}ページ生成")
    if args.dry_run:
        print(f"確認先: {DRY_RUN_DIR}")


if __name__ == "__main__":
    main()
