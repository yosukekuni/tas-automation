#!/usr/bin/env python3
"""
セグメント別LP 3ページ作成・デプロイスクリプト

対象:
  - /lp/government/   官公庁向け（parent: 6147）
  - /lp/real-estate/  不動産向け（parent: 6147）
  - /lp/inspection/   点検向け（parent: 6147）

設計書: docs/additional_lp_design.md
既存LP参考: /lp/general-contractor/ (ID:6148), /lp/consultant/ (ID:6149)

実績数値はCRM受注台帳から自動取得（ハードコード禁止）。
wp_safe_deploy.py 経由でデプロイ。

Usage:
  python3 deploy_segment_lps.py                # 3ページ作成（ドラフト）
  python3 deploy_segment_lps.py --publish      # 公開
  python3 deploy_segment_lps.py --dry-run      # HTML確認のみ
  python3 deploy_segment_lps.py --lp government # 特定LPのみ
"""

import json
import sys
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config, get_wp_auth, get_wp_api_url
from lib.lark_api import lark_get_token, lark_list_records

# ── Constants ──
LP_PARENT_ID = 6147  # /lp/ parent page
PHONE = "050-7117-7141"
BRAND_COLOR = "#1647FB"
BRAND_DARK = "#0d2f99"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"  # 受注台帳

# ── Structured Data Builders ──

def build_local_business_schema():
    """LocalBusiness構造化データ"""
    return {
        "@type": "LocalBusiness",
        "@id": "https://tokaiair.com/#organization",
        "name": "東海エアサービス株式会社",
        "url": "https://tokaiair.com/",
        "telephone": PHONE,
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "名古屋市",
            "addressRegion": "愛知県",
            "addressCountry": "JP"
        },
        "areaServed": [
            {"@type": "State", "name": "愛知県"},
            {"@type": "State", "name": "岐阜県"},
            {"@type": "State", "name": "三重県"},
            {"@type": "State", "name": "静岡県"}
        ]
    }


def build_breadcrumb_schema(lp_slug, lp_name):
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1,
             "name": "ホーム", "item": "https://tokaiair.com/"},
            {"@type": "ListItem", "position": 2,
             "name": "LP", "item": "https://tokaiair.com/lp/"},
            {"@type": "ListItem", "position": 3,
             "name": lp_name,
             "item": f"https://tokaiair.com/lp/{lp_slug}/"}
        ]
    }


def build_service_schema(name, description, provider_name="東海エアサービス株式会社",
                         area_served=None):
    schema = {
        "@type": "Service",
        "name": name,
        "description": description,
        "provider": {
            "@type": "LocalBusiness",
            "name": provider_name,
            "telephone": PHONE
        },
        "areaServed": area_served or [
            {"@type": "State", "name": "愛知県"},
            {"@type": "State", "name": "岐阜県"},
            {"@type": "State", "name": "三重県"},
            {"@type": "State", "name": "静岡県"}
        ]
    }
    return schema


def build_faq_schema(faqs):
    """FAQPage構造化データ"""
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


def build_howto_schema(name, steps):
    return {
        "@type": "HowTo",
        "name": name,
        "step": [
            {"@type": "HowToStep", "position": i + 1, "name": s}
            for i, s in enumerate(steps)
        ]
    }


def wrap_structured_data(*schemas):
    """複数スキーマを@graphでラップ"""
    graph = {
        "@context": "https://schema.org",
        "@graph": list(schemas)
    }
    return json.dumps(graph, ensure_ascii=False, indent=2)


# ── CTA HTML Builders ──

def cta_primary(text="費用について問い合わせる", href="/contact/"):
    return (
        f'<a href="{href}" style="display:inline-block;padding:16px 36px;'
        f'background:{BRAND_COLOR};color:#fff;text-decoration:none;'
        f'border-radius:8px;font-weight:700;font-size:1rem;'
        f'transition:background .2s">{text}</a>'
    )


def cta_phone():
    return (
        f'<a href="tel:{PHONE.replace("-", "")}" style="display:inline-block;'
        f'padding:16px 36px;border:2px solid {BRAND_COLOR};color:{BRAND_COLOR};'
        f'text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem">'
        f'{PHONE}</a>'
    )


def cta_secondary(text, href):
    return (
        f'<a href="{href}" style="display:inline-block;padding:12px 28px;'
        f'border:2px solid {BRAND_COLOR};color:{BRAND_COLOR};text-decoration:none;'
        f'border-radius:8px;font-weight:600;font-size:.95rem">{text}</a>'
    )


def cta_tool(text="土量計算ツールを試す", href="/tools/earthwork/calculator/"):
    return (
        f'<a href="{href}" style="display:inline-block;padding:12px 28px;'
        f'background:#f0f4ff;color:{BRAND_COLOR};text-decoration:none;'
        f'border-radius:8px;font-weight:600;font-size:.95rem;'
        f'border:1px solid {BRAND_COLOR}">{text}</a>'
    )


def cta_block(primary_text="費用について問い合わせる", show_tool=True):
    """段階的CTA: ツール/問い合わせ/電話/面談"""
    parts = ['<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap;margin:2rem 0">']
    if show_tool:
        parts.append(cta_tool())
    parts.append(cta_primary(primary_text))
    parts.append(cta_phone())
    parts.append('</div>')
    parts.append(
        '<p style="text-align:center;margin:.5rem 0 0;font-size:.85rem;color:#666">'
        '<a href="/contact/" style="color:#666;text-decoration:underline">面談予約はこちら</a></p>'
    )
    return "\n".join(parts)


# ── Stats from CRM ──

def fetch_crm_stats(cfg):
    """受注台帳からセグメント別統計を取得"""
    print("[CRM] 受注台帳から実績データ取得中...")
    token = lark_get_token(cfg)
    records = lark_list_records(token, ORDER_TABLE_ID, cfg=cfg)
    print(f"  取得レコード数: {len(records)}")

    # 非案件パターン除外
    import re
    non_case = re.compile(r"支払通知書|支払明細|営業代行|送付$")

    stats = defaultdict(lambda: {"count": 0, "companies": set()})

    for rec in records:
        fields = rec.get("fields", {})
        case_name = _extract_text(fields.get("案件名", ""))
        company = _extract_text(fields.get("取引先", ""))

        if non_case.search(case_name):
            continue
        if not case_name.strip():
            continue

        # 業種分類
        industry = _classify_industry(company, case_name)
        service = _classify_service(case_name)

        stats[f"industry_{industry}"]["count"] += 1
        if company:
            stats[f"industry_{industry}"]["companies"].add(company)

        stats[f"service_{service}"]["count"] += 1
        if company:
            stats[f"service_{service}"]["companies"].add(company)

        stats["total"]["count"] += 1
        if company:
            stats["total"]["companies"].add(company)

    # setをcountに変換
    result = {}
    for k, v in stats.items():
        result[k] = {"count": v["count"], "companies": len(v["companies"])}

    print(f"  統計: 総案件{result.get('total', {}).get('count', 0)}件 / "
          f"総取引先{result.get('total', {}).get('companies', 0)}社")
    return result


def _extract_text(value):
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


def _classify_industry(company, case_name):
    rules = {
        "ゼネコン": ["建設", "組", "工業", "工務", "土木", "JV",
                    "鳶", "基礎", "舗装", "造園", "電工", "設備工",
                    "鉄工", "管工", "塗装", "防水", "解体", "重機"],
        "建設コンサルタント": ["コンサルタント", "コンサル", "設計", "技研",
                          "地質", "エンジニア", "計画"],
        "測量会社": ["測量", "工測"],
        "不動産": ["不動産", "デベロッパー", "地所", "リアルティ"],
        "官公庁": ["市役所", "県庁", "事務所", "高校", "学校", "教育委員会",
                  "国交省", "NEXCO"],
    }
    text = company + " " + case_name
    for industry, keywords in rules.items():
        for kw in keywords:
            if kw in text:
                return industry
    return "その他"


def _classify_service(case_name):
    if any(k in case_name for k in ["眺望", "パノラマ"]):
        return "眺望撮影"
    if any(k in case_name for k in ["点検", "赤外線", "サーモ", "外壁"]):
        return "点検"
    if any(k in case_name for k in ["測量", "土量", "三次元", "3D", "点群", "RTK", "計測"]):
        return "ドローン測量"
    if any(k in case_name for k in ["空撮", "撮影", "写真", "動画"]):
        return "現場空撮"
    return "その他"


# ── LP HTML Builders ──

def build_government_lp(stats):
    """官公庁向けLP HTML"""
    total = stats.get("total", {}).get("count", 0)
    gov_count = stats.get("industry_官公庁", {}).get("count", 0)
    consul_count = stats.get("industry_建設コンサルタント", {}).get("count", 0)
    survey_count = stats.get("service_ドローン測量", {}).get("count", 0)

    structured_data = wrap_structured_data(
        build_service_schema(
            "官公庁向けドローン測量・点検",
            "公共測量作業規程準拠のドローン測量。河川・砂防・橋梁点検に対応。i-Construction準拠の点群データ納品。"
        ),
        build_faq_schema([
            ("公共測量作業規程に準拠していますか？",
             "はい。RTK-GNSS測量で水平5mm+1ppm、鉛直10mm+1ppmの精度を確保し、公共測量作業規程準則に準拠した成果品を納品します。"),
            ("飛行許可はどうなりますか？",
             "国交省の包括許可を取得済みです。DID地区・夜間・目視外飛行にも対応可能。現場に応じた個別許可申請も代行します。"),
            ("i-Construction対応のデータ形式で納品できますか？",
             "SXF、LandXML、GeoTIFF、LAS/LAZ、PDF等、i-Construction要求のフォーマットに対応しています。"),
        ]),
        build_howto_schema("官公庁向けドローン測量の流れ", [
            "お問い合わせ・仕様確認",
            "現地踏査・飛行計画作成",
            "飛行許可申請（必要時）",
            "現地計測",
            "データ処理・成果品納品",
            "検査対応・修正",
        ]),
        build_local_business_schema(),
        build_breadcrumb_schema("government", "官公庁向け"),
    )

    html = f'''<!-- 構造化データ -->
<script type="application/ld+json">
{structured_data}
</script>

<!-- ファーストビュー -->
<div style="background:linear-gradient(135deg, #0a1628 0%, {BRAND_COLOR} 100%);color:#fff;padding:4rem 2rem;text-align:center;border-radius:0 0 24px 24px">
<p style="font-size:.85rem;letter-spacing:3px;opacity:.8;margin:0">FOR GOVERNMENT</p>
<h1 style="font-size:2rem;line-height:1.5;margin:1rem 0;font-weight:800">官公庁向けドローン測量・点検<br><span style="font-size:1.1rem;font-weight:400">公共測量対応・NETIS登録技術</span></h1>
<p style="font-size:1.1rem;opacity:.9;margin:0 0 .5rem">公共測量からインフラ点検まで、行政DXをドローンで実現</p>
<p style="font-size:.9rem;opacity:.7">国土交通省i-Construction対応 / 公共測量作業規程準則準拠</p>
<div style="margin-top:2rem">
<p style="font-size:.85rem;opacity:.7;margin:0 0 .5rem">累計受注実績 <strong style="font-size:1.3rem" data-stat-count="{total}">{total}</strong>件 / ドローン測量 <strong data-stat-survey="{survey_count}">{survey_count}</strong>件</p>
</div>
{cta_block("費用について問い合わせる", show_tool=False)}
</div>

<!-- 課題提起 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">こんな課題をお持ちではありませんか？</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>河川・砂防施設の現地測量に人員と日数がかかりすぎる</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">ドローン測量なら1日で数kmの河川縦横断を計測可能</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>i-Construction対応の測量業者が地域に少ない</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">RTK-GNSS測量で規程準則準拠の精度を保証</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>橋梁・トンネル等のインフラ点検で足場設置コストが膨大</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">赤外線カメラ搭載ドローンで非破壊検査</p>
</div>
</div>
</div>

<!-- ソリューション -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:900px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">ドローン活用で行政コストを削減</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">公共測量作業規程準拠</h3>
<p style="margin:0;font-size:.9rem;color:#555">GNSS/RTK測量で水平5mm+1ppm、鉛直10mm+1ppmの精度保証</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">広域3D計測</h3>
<p style="margin:0;font-size:.9rem;color:#555">河川縦横断・砂防施設を1日で数km対応</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">赤外線点検</h3>
<p style="margin:0;font-size:.9rem;color:#555">橋梁・建築物の非破壊点検をドローンで安全に実施</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">多様な納品形式</h3>
<p style="margin:0;font-size:.9rem;color:#555">SXF / LandXML / GeoTIFF / LAS・LAZ / PDF対応</p>
</div>
</div>
</div>

{cta_block("お見積もりを依頼する", show_tool=False)}

<!-- 技術仕様 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">技術仕様・対応規格</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<tr style="background:{BRAND_COLOR};color:#fff"><th style="padding:12px;text-align:left">項目</th><th style="padding:12px;text-align:left">仕様</th></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px;font-weight:600">測量精度</td><td style="padding:12px">水平5mm+1ppm / 鉛直10mm+1ppm（RTK）</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px;font-weight:600">対応規格</td><td style="padding:12px">公共測量作業規程準則 / i-Construction</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px;font-weight:600">納品形式</td><td style="padding:12px">SXF, LandXML, GeoTIFF, LAS/LAZ, PDF</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px;font-weight:600">飛行許可</td><td style="padding:12px">国交省包括許可取得済 / DID・夜間・目視外</td></tr>
<tr><td style="padding:12px;font-weight:600">保険</td><td style="padding:12px">対人対物1億円</td></tr>
</table>
</div>

<!-- 実績 -->
<div style="background:#f8f9fa;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">実績</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">河川測量・砂防施設計測</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">中津川地区4箇所（コンサル経由）</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">公共測量</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">建設コンサルタント経由（450万円規模案件）</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">県立学校施設測量</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">愛知県内2校</p>
</div>
</div>
</div>

<!-- 料金 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">料金目安</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<tr style="background:{BRAND_COLOR};color:#fff"><th style="padding:12px;text-align:left">サービス</th><th style="padding:12px;text-align:right">目安価格</th></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">公共測量（1ha未満）</td><td style="padding:12px;text-align:right;font-weight:700">15万円〜</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px">河川縦横断測量（1km）</td><td style="padding:12px;text-align:right;font-weight:700">30万円〜</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">赤外線点検（橋梁1橋）</td><td style="padding:12px;text-align:right;font-weight:700">20万円〜</td></tr>
<tr style="background:#f8f9fa"><td style="padding:12px">点群処理・成果品作成</td><td style="padding:12px;text-align:right;font-weight:700">10万円〜</td></tr>
</table>
</div>

<!-- ご利用の流れ -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">ご利用の流れ</h2>
<div style="display:grid;gap:1rem">
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">1</span>
<span>お問い合わせ・仕様確認</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">2</span>
<span>現地踏査・飛行計画作成</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">3</span>
<span>飛行許可申請（必要時）</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">4</span>
<span>現地計測</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">5</span>
<span>データ処理・成果品納品</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">6</span>
<span>検査対応・修正</span>
</div>
</div>
</div>

<!-- 関連ページ -->
<div style="max-width:800px;margin:2rem auto;padding:0 1.5rem;font-size:.9rem">
<p style="color:#666">関連ページ: <a href="/services/uav-survey/" style="color:{BRAND_COLOR}">UAV測量サービス</a> | <a href="/services/3d-measurement/" style="color:{BRAND_COLOR}">3次元計測</a> | <a href="/lp/consultant/" style="color:{BRAND_COLOR}">コンサルタント向けLP</a></p>
</div>

<!-- クロージングCTA -->
<div style="background:linear-gradient(135deg, #0a1628 0%, {BRAND_COLOR} 100%);color:#fff;padding:3rem 2rem;text-align:center;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.4rem;margin:0 0 1rem">公共測量・インフラ点検のご相談はこちら</h2>
<p style="opacity:.8;margin:0 0 2rem;font-size:.95rem">対応エリア: 愛知・岐阜・三重・静岡（全国出張対応可）</p>
{cta_block("お問い合わせ", show_tool=False)}
</div>'''
    return html


def build_realestate_lp(stats):
    """不動産向けLP HTML"""
    total = stats.get("total", {}).get("count", 0)
    photo_count = stats.get("service_現場空撮", {}).get("count", 0)
    pano_count = stats.get("service_眺望撮影", {}).get("count", 0)

    structured_data = wrap_structured_data(
        build_service_schema(
            "不動産向けドローン撮影",
            "マンション眺望撮影・360度パノラマ・物件空撮をワンストップ提供。RTK測位で正確な高度から各階眺望を再現。"
        ),
        build_faq_schema([
            ("建設前のマンションの眺望を撮影できますか？",
             "はい。RTK測位で各階の正確な高度からドローン撮影が可能です。建設前でも各フロアの眺望をシミュレーションできます。"),
            ("納品データの形式は？",
             "RAW + 現像済みJPEG + コンタクトシートを標準納品。VR用360度パノラマやWeb埋め込み用データも対応可能です。"),
            ("撮影にかかる日数は？",
             "通常1日で撮影完了、データ処理・納品まで3〜5営業日が目安です。お急ぎの場合はご相談ください。"),
        ]),
        build_howto_schema("不動産向けドローン撮影の流れ", [
            "お問い合わせ・撮影要件ヒアリング",
            "現地ロケハン・飛行計画",
            "撮影実施",
            "画像処理・パノラマ合成",
            "コンタクトシート確認・修正",
            "最終データ納品",
        ]),
        build_local_business_schema(),
        build_breadcrumb_schema("real-estate", "不動産向け"),
    )

    html = f'''<!-- 構造化データ -->
<script type="application/ld+json">
{structured_data}
</script>

<!-- ファーストビュー -->
<div style="background:linear-gradient(135deg, #1a1a2e 0%, {BRAND_COLOR} 100%);color:#fff;padding:4rem 2rem;text-align:center;border-radius:0 0 24px 24px">
<p style="font-size:.85rem;letter-spacing:3px;opacity:.8;margin:0">FOR REAL ESTATE</p>
<h1 style="font-size:2rem;line-height:1.5;margin:1rem 0;font-weight:800">不動産向けドローン撮影<br><span style="font-size:1.1rem;font-weight:400">眺望パノラマ・物件空撮で成約率アップ</span></h1>
<p style="font-size:1.1rem;opacity:.9;margin:0 0 .5rem">買い手の心を動かす眺望を、ドローンで</p>
<p style="font-size:.9rem;opacity:.7">マンション眺望撮影・360度パノラマ・建物空撮をワンストップ提供</p>
<div style="margin-top:2rem">
<p style="font-size:.85rem;opacity:.7;margin:0 0 .5rem">累計受注実績 <strong style="font-size:1.3rem" data-stat-count="{total}">{total}</strong>件 / 空撮 <strong data-stat-photo="{photo_count}">{photo_count}</strong>件</p>
</div>
{cta_block("撮影プランを相談する", show_tool=False)}
</div>

<!-- 課題提起 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">こんな課題をお持ちではありませんか？</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>上層階の眺望を購入検討者に正確に伝えられない</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">RTK測位で各階の正確な高さから眺望を撮影</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>物件の魅力を写真だけでは差別化できない</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">360度パノラマ・4K動画で臨場感のある物件紹介</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>販促用の空撮を依頼したいが、どこに頼めば良いか分からない</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">撮影から画像処理・納品までワンストップで対応</p>
</div>
</div>
</div>

<!-- ソリューション -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:900px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">ドローン撮影で物件の価値を可視化</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">眺望シミュレーション</h3>
<p style="margin:0;font-size:.9rem;color:#555">建設前の各階眺望をドローンで再現撮影。RTK測位で誤差数cm。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">360度パノラマ撮影</h3>
<p style="margin:0;font-size:.9rem;color:#555">VR内覧・Webパノラマ埋め込み対応。没入感のある物件紹介。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">4K空撮映像</h3>
<p style="margin:0;font-size:.9rem;color:#555">物件紹介動画・CM素材に対応。プロ品質の空撮映像。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">敷地測量</h3>
<p style="margin:0;font-size:.9rem;color:#555">造成前後の土量算出・現況図作成。開発計画の基礎データに。</p>
</div>
</div>
</div>

{cta_block("撮影プランを相談する", show_tool=False)}

<!-- 眺望撮影の特長 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">眺望撮影の特長</h2>
<div style="display:grid;gap:1rem">
<div style="background:#f8f9fa;border-radius:8px;padding:1.2rem;display:flex;align-items:start;gap:1rem">
<span style="color:{BRAND_COLOR};font-weight:700;font-size:1.5rem">01</span>
<div><strong>RTK測位で各階の正確な高度から撮影</strong><br><span style="font-size:.9rem;color:#666">誤差数cmの高精度測位</span></div>
</div>
<div style="background:#f8f9fa;border-radius:8px;padding:1.2rem;display:flex;align-items:start;gap:1rem">
<span style="color:{BRAND_COLOR};font-weight:700;font-size:1.5rem">02</span>
<div><strong>東西南北4方向 + パノラマ合成を標準提供</strong><br><span style="font-size:.9rem;color:#666">全方位の眺望を網羅</span></div>
</div>
<div style="background:#f8f9fa;border-radius:8px;padding:1.2rem;display:flex;align-items:start;gap:1rem">
<span style="color:{BRAND_COLOR};font-weight:700;font-size:1.5rem">03</span>
<div><strong>コンタクトシート付き納品</strong><br><span style="font-size:.9rem;color:#666">販促資料にそのまま使用可能</span></div>
</div>
<div style="background:#f8f9fa;border-radius:8px;padding:1.2rem;display:flex;align-items:start;gap:1rem">
<span style="color:{BRAND_COLOR};font-weight:700;font-size:1.5rem">04</span>
<div><strong>RAW + 現像済みJPEGの二重納品</strong><br><span style="font-size:.9rem;color:#666">後工程での調整に対応</span></div>
</div>
</div>
</div>

<!-- 導入事例 -->
<div style="background:#f8f9fa;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">導入事例</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">マンション眺望撮影（名古屋市内）</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">RTK測量併用、4方位パノラマ撮影。建設前の販促資料として活用。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">不動産販促空撮（遠隔地案件）</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">東海圏外からのご依頼にも全国出張対応。</p>
</div>
</div>
</div>

<!-- 料金 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">料金目安</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<tr style="background:{BRAND_COLOR};color:#fff"><th style="padding:12px;text-align:left">サービス</th><th style="padding:12px;text-align:right">目安価格</th></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">眺望撮影（1物件・4方位）</td><td style="padding:12px;text-align:right;font-weight:700">15万円〜</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px">360度パノラマ（5カット）</td><td style="padding:12px;text-align:right;font-weight:700">8万円〜</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">物件空撮（写真+動画）</td><td style="padding:12px;text-align:right;font-weight:700">5万円〜</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px">敷地測量+オルソ画像</td><td style="padding:12px;text-align:right;font-weight:700">10万円〜</td></tr>
<tr><td style="padding:12px">眺望撮影+RTK測量セット</td><td style="padding:12px;text-align:right;font-weight:700">30万円〜</td></tr>
</table>
</div>

<!-- ご利用の流れ -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">ご利用の流れ</h2>
<div style="display:grid;gap:1rem">
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">1</span>
<span>お問い合わせ・撮影要件ヒアリング</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">2</span>
<span>現地ロケハン・飛行計画</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">3</span>
<span>撮影実施</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">4</span>
<span>画像処理・パノラマ合成</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">5</span>
<span>コンタクトシート確認・修正</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">6</span>
<span>最終データ納品</span>
</div>
</div>
</div>

<!-- 関連ページ -->
<div style="max-width:800px;margin:2rem auto;padding:0 1.5rem;font-size:.9rem">
<p style="color:#666">関連ページ: <a href="/services/uav-survey/" style="color:{BRAND_COLOR}">UAV測量サービス</a></p>
</div>

<!-- クロージングCTA -->
<div style="background:linear-gradient(135deg, #1a1a2e 0%, {BRAND_COLOR} 100%);color:#fff;padding:3rem 2rem;text-align:center;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.4rem;margin:0 0 1rem">物件の魅力を最大化する撮影プランをご提案します</h2>
<p style="opacity:.8;margin:0 0 2rem;font-size:.95rem">対応エリア: 愛知・岐阜・三重・静岡（全国出張対応可）</p>
{cta_block("お問い合わせ", show_tool=False)}
</div>'''
    return html


def build_inspection_lp(stats):
    """点検向けLP HTML"""
    total = stats.get("total", {}).get("count", 0)
    inspection_count = stats.get("service_点検", {}).get("count", 0)

    structured_data = wrap_structured_data(
        build_service_schema(
            "ドローン点検サービス",
            "足場不要のドローン点検。赤外線カメラで外壁タイル浮き・太陽光ホットスポットを非破壊検出。12条点検対応。"
        ),
        build_faq_schema([
            ("12条点検にドローン赤外線調査は使えますか？",
             "はい。建築基準法12条・告示282号に基づく外壁調査の代替手法として、赤外線サーモグラフィ調査が認められています。"),
            ("足場と比べてどれくらいコスト削減できますか？",
             "一般的に足場設置費用の50〜70%削減が可能です。高層建築物ほどコストメリットが大きくなります。"),
            ("太陽光パネルのホットスポットも検出できますか？",
             "赤外線カメラで太陽光パネル表面の温度分布を計測し、ホットスポット・クラスター故障・バイパスダイオード異常を検出します。"),
        ]),
        build_howto_schema("ドローン点検の流れ", [
            "お問い合わせ・点検対象ヒアリング",
            "現地踏査・飛行計画作成",
            "点検実施（赤外線+可視光撮影）",
            "画像解析・損傷箇所特定",
            "報告書作成（損傷図・温度分布図）",
            "納品・改修提案",
        ]),
        build_local_business_schema(),
        build_breadcrumb_schema("inspection", "点検向け"),
    )

    html = f'''<!-- 構造化データ -->
<script type="application/ld+json">
{structured_data}
</script>

<!-- ファーストビュー -->
<div style="background:linear-gradient(135deg, #0d1b2a 0%, {BRAND_COLOR} 100%);color:#fff;padding:4rem 2rem;text-align:center;border-radius:0 0 24px 24px">
<p style="font-size:.85rem;letter-spacing:3px;opacity:.8;margin:0">DRONE INSPECTION</p>
<h1 style="font-size:2rem;line-height:1.5;margin:1rem 0;font-weight:800">ドローン点検<br><span style="font-size:1.1rem;font-weight:400">赤外線外壁調査・インフラ点検・太陽光パネル診断</span></h1>
<p style="font-size:1.1rem;opacity:.9;margin:0 0 .5rem">足場不要。ドローンで安全・低コストな点検を</p>
<p style="font-size:.9rem;opacity:.7">赤外線カメラ搭載ドローンで外壁・屋根・設備を非破壊診断</p>
<div style="margin-top:2rem">
<p style="font-size:.85rem;opacity:.7;margin:0 0 .5rem">累計受注実績 <strong style="font-size:1.3rem" data-stat-count="{total}">{total}</strong>件</p>
</div>
{cta_block("点検の見積もりを依頼する", show_tool=False)}
</div>

<!-- 課題提起 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">こんな課題をお持ちではありませんか？</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>外壁の打診調査に足場を組むと数百万円のコストがかかる</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">ドローン赤外線調査で足場費用50〜70%削減</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>太陽光パネルのホットスポットを効率的に見つけたい</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">赤外線カメラで面的にホットスポットを検出</p>
</div>
<div style="background:#f8f9fa;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-size:1rem"><strong>高所・危険箇所の点検で作業員の安全確保が難しい</strong></p>
<p style="margin:.5rem 0 0;font-size:.9rem;color:#666">ドローンなら高所作業なし。安全に点検完了</p>
</div>
</div>
</div>

<!-- ソリューション -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:900px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem;color:#1a1a1a">ドローン点検で安全性とコストを両立</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">赤外線サーモグラフィ</h3>
<p style="margin:0;font-size:.9rem;color:#555">外壁タイルの浮き・剥離を非接触で検出。12条点検対応。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">高解像度撮影</h3>
<p style="margin:0;font-size:.9rem;color:#555">4K/8Kカメラでひび割れ・劣化を詳細記録。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">太陽光パネル診断</h3>
<p style="margin:0;font-size:.9rem;color:#555">ホットスポット・クラスター故障を面的に検出。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem">
<h3 style="font-size:1.1rem;color:{BRAND_COLOR};margin:0 0 .5rem">3Dモデル生成</h3>
<p style="margin:0;font-size:.9rem;color:#555">点群データから劣化箇所を座標付きで記録。</p>
</div>
</div>
</div>

{cta_block("点検の見積もりを依頼する", show_tool=False)}

<!-- 対応点検種別 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">対応点検種別</h2>
<table style="width:100%;border-collapse:collapse;font-size:.9rem">
<tr style="background:{BRAND_COLOR};color:#fff"><th style="padding:10px;text-align:left">点検対象</th><th style="padding:10px;text-align:left">手法</th><th style="padding:10px;text-align:left">対応規格</th></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:10px">外壁タイル（12条点検）</td><td style="padding:10px">赤外線サーモグラフィ</td><td style="padding:10px">建築基準法12条 / 告示282号</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:10px">太陽光パネル</td><td style="padding:10px">赤外線 + 可視光</td><td style="padding:10px">IEC 62446準拠</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:10px">橋梁・高架</td><td style="padding:10px">近接撮影 + 赤外線</td><td style="padding:10px">道路橋定期点検要領</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:10px">屋根・煙突・鉄塔</td><td style="padding:10px">高解像度撮影</td><td style="padding:10px">-</td></tr>
<tr><td style="padding:10px">工場・プラント設備</td><td style="padding:10px">赤外線 + 3Dスキャン</td><td style="padding:10px">-</td></tr>
</table>
</div>

<!-- 導入事例 -->
<div style="background:#f8f9fa;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">導入事例</h2>
<div style="display:grid;gap:1.5rem">
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">高速道路関連施設点検</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">ドローン + 点検ロボット併用による効率的な点検を実施。</p>
</div>
<div style="background:#fff;border-radius:12px;padding:1.5rem;border-left:4px solid {BRAND_COLOR}">
<p style="margin:0;font-weight:700">赤外線外壁調査</p>
<p style="margin:.3rem 0 0;font-size:.9rem;color:#666">足場設置と比較して費用70%削減の実績。</p>
</div>
</div>
</div>

<!-- 料金 -->
<div style="max-width:800px;margin:3rem auto;padding:0 1.5rem">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">料金目安</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<tr style="background:{BRAND_COLOR};color:#fff"><th style="padding:12px;text-align:left">サービス</th><th style="padding:12px;text-align:right">目安価格</th></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">赤外線外壁調査（〜500m2）</td><td style="padding:12px;text-align:right;font-weight:700">15万円〜</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px">赤外線外壁調査（〜2000m2）</td><td style="padding:12px;text-align:right;font-weight:700">30万円〜</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">太陽光パネル点検（〜1MW）</td><td style="padding:12px;text-align:right;font-weight:700">10万円〜</td></tr>
<tr style="background:#f8f9fa;border-bottom:1px solid #e0e0e0"><td style="padding:12px">橋梁近接撮影（1橋）</td><td style="padding:12px;text-align:right;font-weight:700">20万円〜</td></tr>
<tr style="border-bottom:1px solid #e0e0e0"><td style="padding:12px">屋根・高所設備撮影</td><td style="padding:12px;text-align:right;font-weight:700">5万円〜</td></tr>
<tr style="background:#f8f9fa"><td style="padding:12px">報告書作成（損傷図付き）</td><td style="padding:12px;text-align:right;font-weight:700">5万円〜</td></tr>
</table>
</div>

<!-- ご利用の流れ -->
<div style="background:#f0f4ff;padding:3rem 1.5rem;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">ご利用の流れ</h2>
<div style="display:grid;gap:1rem">
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">1</span>
<span>お問い合わせ・点検対象ヒアリング</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">2</span>
<span>現地踏査・飛行計画作成</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">3</span>
<span>点検実施（赤外線+可視光撮影）</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">4</span>
<span>画像解析・損傷箇所特定</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">5</span>
<span>報告書作成（損傷図・温度分布図）</span>
</div>
<div style="display:flex;align-items:center;gap:1rem;background:#fff;border-radius:8px;padding:1rem">
<span style="background:{BRAND_COLOR};color:#fff;border-radius:50%;min-width:36px;height:36px;display:flex;align-items:center;justify-content:center;font-weight:700">6</span>
<span>納品・改修提案</span>
</div>
</div>
</div>

<!-- 関連ページ -->
<div style="max-width:800px;margin:2rem auto;padding:0 1.5rem;font-size:.9rem">
<p style="color:#666">関連ページ: <a href="/services/infrared-inspection/" style="color:{BRAND_COLOR}">赤外線調査サービス</a> | <a href="/services/3d-measurement/" style="color:{BRAND_COLOR}">3次元計測</a></p>
</div>

<!-- クロージングCTA -->
<div style="background:linear-gradient(135deg, #0d1b2a 0%, {BRAND_COLOR} 100%);color:#fff;padding:3rem 2rem;text-align:center;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.4rem;margin:0 0 1rem">足場を組む前に、まずドローン点検をご検討ください</h2>
<p style="opacity:.8;margin:0 0 2rem;font-size:.95rem">対応エリア: 愛知・岐阜・三重・静岡（全国出張対応可）</p>
{cta_block("お問い合わせ", show_tool=False)}
</div>'''
    return html


# ── LP Definitions ──

LP_DEFS = {
    "government": {
        "slug": "government",
        "title": "官公庁向けドローン測量・点検｜公共測量対応 | 東海エアサービス",
        "meta_title": "官公庁向けドローン測量・点検｜公共測量対応 | 東海エアサービス",
        "meta_description": "公共測量作業規程準拠のドローン測量。河川・砂防・橋梁点検に対応。i-Construction準拠の点群データ納品。愛知・東海エリアから全国出張可。",
        "builder": build_government_lp,
    },
    "real-estate": {
        "slug": "real-estate",
        "title": "不動産向けドローン撮影｜眺望パノラマ・物件空撮 | 東海エアサービス",
        "meta_title": "不動産向けドローン撮影｜眺望パノラマ・物件空撮 | 東海エアサービス",
        "meta_description": "マンション眺望撮影・360度パノラマ・物件空撮をワンストップ提供。RTK測位で正確な高度から各階眺望を再現。不動産販促の差別化に。",
        "builder": build_realestate_lp,
    },
    "inspection": {
        "slug": "inspection",
        "title": "ドローン点検｜赤外線外壁調査・太陽光パネル・インフラ点検 | 東海エアサービス",
        "meta_title": "ドローン点検｜赤外線外壁調査・太陽光パネル・インフラ点検 | 東海エアサービス",
        "meta_description": "足場不要のドローン点検。赤外線カメラで外壁タイル浮き・太陽光ホットスポットを非破壊検出。12条点検対応。名古屋・東海エリアから全国出張可。",
        "builder": build_inspection_lp,
    },
}


# ── WordPress API ──

def wp_request(cfg, endpoint, method="GET", data=None, params=None, max_retries=3):
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)
    url = f"{base_url}/{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())

    body = json.dumps(data).encode("utf-8") if data else None

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Basic {auth}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"  HTTP Error {e.code}: {e.read().decode()[:300]}")
            return None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"  接続エラー (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
    print(f"  接続失敗: {max_retries}回リトライ後も失敗")
    return None


def find_existing_page(cfg, slug):
    pages = wp_request(cfg, "pages", params={"slug": slug, "per_page": "5", "status": "any"})
    if pages:
        for p in pages:
            if p.get("slug") == slug:
                return p["id"]
    return None


def create_or_update_page(cfg, lp_key, html, publish=False, dry_run=False):
    """LP作成 or 更新

    WAF対策: 新規作成時はシンプルなコンテンツで作成後、分割更新。
    """
    lp = LP_DEFS[lp_key]
    slug = lp["slug"]
    status = "publish" if publish else "draft"

    print(f"\n{'='*60}")
    print(f"[LP] {lp_key}: /{slug}/")

    if dry_run:
        output_path = SCRIPT_DIR.parent / "backups" / f"lp_{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        output_path.parent.mkdir(exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        print(f"  [DRY-RUN] HTML出力: {output_path}")
        print(f"  HTMLサイズ: {len(html):,} bytes")
        return True

    # wp_safe_deploy経由でデプロイ
    from wp_safe_deploy import safe_update_page

    existing_id = find_existing_page(cfg, slug)

    if existing_id:
        print(f"  既存ページ発見: ID {existing_id} → 更新")
        ok = safe_update_page(existing_id, html, profile="article")
        if ok:
            # meta更新
            wp_request(cfg, f"pages/{existing_id}", method="POST", data={
                "title": lp["title"],
                "status": status,
            })
            # Yoast meta
            _update_yoast_meta(cfg, existing_id, lp)
        return ok
    else:
        # WAF対策: まずシンプルなコンテンツで作成
        print(f"  新規作成(2段階): parent={LP_PARENT_ID}, status=draft")
        placeholder = "<p>ページ準備中</p>"
        page_data = {
            "title": lp["title"],
            "slug": slug,
            "content": placeholder,
            "status": "draft",
            "parent": LP_PARENT_ID,
        }
        result = wp_request(cfg, "pages", method="POST", data=page_data)
        if not result or not result.get("id"):
            print(f"  作成失敗（ステップ1）")
            return False

        page_id = result["id"]
        print(f"  ステップ1完了: ID {page_id} (draft)")
        time.sleep(2)

        # ステップ2: コンテンツ更新 via safe_update_page
        print(f"  ステップ2: コンテンツ更新...")
        ok = safe_update_page(page_id, html, profile="article")
        if not ok:
            print(f"  コンテンツ更新失敗。ページID {page_id} は下書きのまま残ります。")
            return False

        # ステータス変更
        if status == "publish":
            time.sleep(1)
            wp_request(cfg, f"pages/{page_id}", method="POST", data={"status": "publish"})
            print(f"  公開完了")

        _update_yoast_meta(cfg, page_id, lp)
        print(f"  完了: ID {page_id}")
        return True


def _update_yoast_meta(cfg, page_id, lp):
    """Yoast SEOメタ更新"""
    try:
        wp_request(cfg, f"pages/{page_id}", method="POST", data={
            "yoast_head_json": {
                "title": lp["meta_title"],
                "description": lp["meta_description"],
            },
            "meta": {
                "_yoast_wpseo_title": lp["meta_title"],
                "_yoast_wpseo_metadesc": lp["meta_description"],
            }
        })
        print(f"  Yoast meta更新完了")
    except Exception as e:
        print(f"  Yoast meta更新失敗（非致命的）: {e}")


# ── lp_stats_sync.py 連携 ──

def update_lp_stats_sync_config():
    """lp_stats_sync.pyに新LP定義を追加するための情報を出力"""
    print("\n[INFO] lp_stats_sync.py に以下のLP定義を追加してください:")
    for key, lp in LP_DEFS.items():
        print(f'  "{key}": {{"page_id": <ID>, "industry": "<業種>", "slug": "{lp["slug"]}", "label": "{lp["title"][:20]}..."}},')


# ── Main ──

def main():
    dry_run = "--dry-run" in sys.argv
    publish = "--publish" in sys.argv
    target_lp = None

    for i, arg in enumerate(sys.argv):
        if arg == "--lp" and i + 1 < len(sys.argv):
            target_lp = sys.argv[i + 1]

    cfg = load_config()

    # CRM実績データ取得
    stats = fetch_crm_stats(cfg)

    # LP生成 & デプロイ
    results = {}
    for lp_key, lp_def in LP_DEFS.items():
        if target_lp and lp_key != target_lp:
            continue

        html = lp_def["builder"](stats)
        ok = create_or_update_page(cfg, lp_key, html, publish=publish, dry_run=dry_run)
        results[lp_key] = ok

    # サマリー
    print(f"\n{'='*60}")
    print(f"[結果サマリー] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in results.items():
        status_str = "OK" if v else "NG"
        print(f"  {k}: {status_str}")

    if not dry_run:
        update_lp_stats_sync_config()

    return all(results.values())


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
