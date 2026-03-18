#!/usr/bin/env python3
"""
事例ページ統合自動更新スクリプト（v2）
受注台帳（Lark Base）から全受注レコードを取得し、
業種別フィルター付きHTMLを生成 → wp_safe_deploy.py経由でWordPress反映

匿名化ルール:
  - 顧客名（取引先名）: 匿名（業種表記に変換）
  - 現場名: そのまま表示OK（公知の施設名・現場名）
  - 地域: そのまま表示OK
  - 金額: 範囲表記

Usage:
  python3 auto_case_updater.py --dry-run     # HTML生成のみ（WP更新なし）
  python3 auto_case_updater.py               # 生成 + WP更新
  python3 auto_case_updater.py --notify      # 生成 + WP更新 + Lark通知
"""

import json
import re
import sys
import time
import urllib.request
import urllib.parse
import base64
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content"
CONTENT_DIR.mkdir(exist_ok=True)
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

# Lark
LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
ORDER_TABLE_ID = "tbldLj2iMJYocct6"  # 受注台帳
OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# WordPress 実績ページ
CASES_PAGE_ID = 4846

# ── カテゴリ正規化マップ ──

INDUSTRY_MAP = {
    "ゼネコン": "ゼネコン",
    "コンサルタント": "建設コンサルタント",
    "建設コンサルタント": "建設コンサルタント",
    "測量会社": "測量会社",
    "不動産": "不動産",
    "官公庁": "官公庁",
    "メーカー": "その他",
    "その他": "その他",
    "": "その他",
}

SERVICE_MAP = {
    "空撮": "現場空撮",
    "現場空撮": "現場空撮",
    "ドローン測量": "ドローン測量",
    "眺望撮影": "眺望撮影",
    "点検": "点検",
    "その他": "その他",
    "": "その他",
}

# 業種の表示順
INDUSTRY_ORDER = ["ゼネコン", "建設コンサルタント", "測量会社", "不動産", "官公庁", "その他"]
SERVICE_ORDER = ["ドローン測量", "現場空撮", "眺望撮影", "点検", "その他"]

# 業種の表示設定
INDUSTRY_DISPLAY = {
    "ゼネコン": {
        "icon": "fa-building",
        "color": "#1565C0",
        "label": "建設会社",
        "description": "大手ゼネコン・建設会社様の現場空撮実績",
    },
    "建設コンサルタント": {
        "icon": "fa-drafting-compass",
        "color": "#2E7D32",
        "label": "建設コンサルタント",
        "description": "建設コンサルタント様のドローン測量実績",
    },
    "測量会社": {
        "icon": "fa-map-marked-alt",
        "color": "#F57F17",
        "label": "測量会社",
        "description": "測量会社様のドローン測量パートナー実績",
    },
    "不動産": {
        "icon": "fa-home",
        "color": "#6A1B9A",
        "label": "不動産",
        "description": "不動産デベロッパー様の眺望撮影実績",
    },
    "官公庁": {
        "icon": "fa-university",
        "color": "#37474F",
        "label": "官公庁・教育機関",
        "description": "官公庁・学校でのドローン活用実績",
    },
    "その他": {
        "icon": "fa-briefcase",
        "color": "#455A64",
        "label": "その他の業種",
        "description": "多様な業種でのドローン活用実績",
    },
}

# サービスの表示設定
SERVICE_DISPLAY = {
    "ドローン測量": {"icon": "fa-ruler-combined", "label": "ドローン測量"},
    "現場空撮": {"icon": "fa-camera", "label": "現場空撮"},
    "眺望撮影": {"icon": "fa-mountain", "label": "眺望撮影"},
    "点検": {"icon": "fa-search", "label": "施設点検"},
    "その他": {"icon": "fa-drone", "label": "その他"},
}


# ── Lark API ──

def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def send_lark_dm(token, text):
    data = json.dumps({
        "receive_id": OWNER_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"  Lark DM error: {e}")


def lark_list_records(token, table_id, page_size=500):
    """Lark Baseからレコード一覧取得"""
    records = []
    page_token = None
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        )
        if page_token:
            url += f"&page_token={page_token}"

        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                resp = json.loads(r.read())
                items = resp.get("data", {}).get("items", [])
                records.extend(items)
                if not resp.get("data", {}).get("has_more"):
                    break
                page_token = resp["data"].get("page_token")
        except Exception as e:
            print(f"Lark API error: {e}")
            break
        time.sleep(0.3)
    return records


# ── データ抽出・分類 ──

def _extract_field_text(fields, field_name):
    """Lark Baseの各種フィールド型からテキストを取得"""
    val = fields.get(field_name)
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                text = item.get("text", item.get("name", ""))
                if text:
                    return text.strip()
            elif isinstance(item, str):
                return item.strip()
    return ""


def extract_case_info(record):
    """受注台帳レコードから実績情報を抽出"""
    fields = record.get("fields", {})

    name = _extract_field_text(fields, "案件名")
    client = _extract_field_text(fields, "取引先名")
    source = _extract_field_text(fields, "出典")

    # 取引先（リンクフィールド）をフォールバック
    if not client:
        client = _extract_field_text(fields, "取引先")

    # 金額
    amount = fields.get("受注金額", 0) or 0
    if isinstance(amount, str):
        try:
            amount = float(amount)
        except ValueError:
            amount = 0

    # 業種（CRMフィールドまたは取引先名から推定）
    industry_raw = _extract_field_text(fields, "業種")
    if not industry_raw:
        industry_raw = _extract_field_text(fields, "CRM業種")
    industry = classify_industry(industry_raw, client)

    # サービス種別
    service_raw = _extract_field_text(fields, "サービス種別")
    service = SERVICE_MAP.get(service_raw, "その他")

    # 非案件フラグ
    non_case = _extract_field_text(fields, "非案件")
    is_non_case = non_case.strip().upper() in ("Y", "YES", "TRUE", "1")

    return {
        "name": name,
        "client": client,
        "source": source,
        "amount": float(amount),
        "industry": industry,
        "service": service,
        "is_non_case": is_non_case,
        "record_id": record.get("record_id", ""),
    }


def classify_industry(industry_raw, client_name):
    """業種を正規化。フィールド値優先、なければ取引先名から推定"""
    if industry_raw and industry_raw in INDUSTRY_MAP:
        return INDUSTRY_MAP[industry_raw]

    # 取引先名からの推定
    cl = client_name.lower() if client_name else ""
    if any(k in cl for k in ["建設", "組", "工業", "工務", "鹿島", "大成", "清水", "竹中", "大林"]):
        return "ゼネコン"
    if any(k in cl for k in ["コンサルタント", "コンサル"]):
        return "建設コンサルタント"
    if any(k in cl for k in ["測量"]):
        return "測量会社"
    if any(k in cl for k in ["不動産", "リアルティ", "デベロッパー"]):
        return "不動産"
    if any(k in cl for k in ["市", "県", "町", "村", "国土", "官"]):
        return "官公庁"

    return INDUSTRY_MAP.get(industry_raw, "その他")


# ── 匿名化・表示処理 ──

def extract_site_name(case_name, client_name):
    """案件名から現場名を抽出（取引先名_現場名 のパターン）

    ルール: 現場名はそのまま表示OK（ユーザー承認済み）
    郵便番号や住所番地のみの場合は汎用表記にする
    """
    if not case_name:
        return ""

    # アンダースコアで分割
    parts = case_name.split("_")
    if len(parts) >= 2:
        site = parts[-1].strip()
    else:
        # 取引先名が案件名に含まれる場合、それを除去して残りを現場名に
        if client_name and client_name in case_name:
            site = case_name.replace(client_name, "").strip()
            # 先頭の記号・空白を除去
            site = re.sub(r'^[\s_・\-]+', '', site)
        else:
            site = ""

    # 郵便番号のみ（〒XXX-XXXX）→ 空
    if re.match(r'^〒?\d{3}-?\d{4}$', site):
        return ""

    # 住所番地のみ（数字-数字パターン）→ 空
    if re.match(r'^[\d\-]+$', site):
        return ""

    # 英語住所パターン（"1 Chome-..." など）→ 空
    if re.match(r'^\d+\s+Chome', site, re.IGNORECASE):
        return ""

    # 「町名+番地」パターン（例: 河芸町東千里600, 潤田1071）→ 空
    if re.match(r'^.{2,6}(町|丁目).{1,10}\d+', site):
        return ""
    if re.match(r'^[\u4e00-\u9fff]{1,6}\d{2,}', site):
        return ""

    # 番地のみ（例: 小木南２丁目１９−1, 丸岡町舛田２０−1-1）→ 空
    if re.search(r'[０-９\d]{2,}[−\-]', site):
        return ""

    return site


def anonymize_client(client_name, industry):
    """取引先名を業種表記に匿名化

    社外秘ルール: 顧客名は絶対に出さない
    """
    return INDUSTRY_DISPLAY.get(industry, INDUSTRY_DISPLAY["その他"])["label"]


def anonymize_amount(amount):
    """金額を範囲表記に匿名化"""
    a = int(amount)
    if a < 50000:
        return "5万円未満"
    elif a < 100000:
        return "5-10万円"
    elif a < 200000:
        return "10-20万円"
    elif a < 500000:
        return "20-50万円"
    elif a < 1000000:
        return "50-100万円"
    elif a < 3000000:
        return "100-300万円"
    elif a < 5000000:
        return "300-500万円"
    else:
        return "500万円以上"


def extract_region(case_name):
    """案件名から地域情報を抽出"""
    prefectures = [
        "愛知", "岐阜", "三重", "静岡", "長野", "石川", "富山", "福井",
        "東京", "大阪", "神奈川", "埼玉", "千葉", "兵庫", "京都", "奈良",
        "滋賀", "和歌山", "新潟", "山梨", "茨城", "栃木", "群馬",
    ]
    special = {"東京": "東京都", "大阪": "大阪府", "京都": "京都府"}
    for pref in prefectures:
        if pref in case_name:
            return special.get(pref, f"{pref}県")

    cities = {
        "名古屋": "愛知県", "豊橋": "愛知県", "豊田": "愛知県", "岡崎": "愛知県",
        "春日井": "愛知県", "一宮": "愛知県", "瀬戸": "愛知県", "半田": "愛知県",
        "東海": "愛知県", "大府": "愛知県", "知多": "愛知県", "昭和区": "愛知県",
        "中区": "愛知県", "千種": "愛知県", "名東": "愛知県", "緑区": "愛知県",
        "港区": "愛知県", "南区": "愛知県", "熱田": "愛知県", "天白": "愛知県",
        "津": "三重県", "四日市": "三重県", "鈴鹿": "三重県", "安城": "愛知県",
        "豊明": "愛知県", "岩塚": "愛知県", "稲沢": "愛知県",
        "岐阜": "岐阜県", "大垣": "岐阜県", "各務原": "岐阜県", "郡上": "岐阜県",
        "浜松": "静岡県", "沼津": "静岡県", "大井川": "静岡県",
        "高山": "岐阜県", "美浜": "愛知県",
    }
    for city, pref in cities.items():
        if city in case_name:
            return pref

    return "東海エリア"


# ── データ構築 ──

def build_case_data(records):
    """Lark受注台帳レコードから事例ページデータを構築"""
    # 受注案件のみ抽出
    won = []
    for r in records:
        info = extract_case_info(r)
        if info["is_non_case"]:
            continue
        if "受注" not in info["source"]:
            continue
        if info["amount"] <= 0:
            continue
        if not info["name"]:
            continue
        won.append(info)

    print(f"  受注案件（有効）: {len(won)}件")

    # 業種別に集計
    by_industry = defaultdict(lambda: {
        "cases": [], "total_revenue": 0, "count": 0,
        "services": defaultdict(int),
    })

    for r in won:
        ind = r["industry"]
        by_industry[ind]["cases"].append(r)
        by_industry[ind]["total_revenue"] += r["amount"]
        by_industry[ind]["count"] += 1
        by_industry[ind]["services"][r["service"]] += 1

    # 事例データ構築（業種別に代表事例を選定）
    case_sections = []
    for ind in INDUSTRY_ORDER:
        data = by_industry.get(ind)
        if not data or data["count"] == 0:
            continue

        display = INDUSTRY_DISPLAY.get(ind, INDUSTRY_DISPLAY["その他"])

        # 代表事例を選定（金額降順、同一取引先は1件のみ）
        cases_sorted = sorted(data["cases"], key=lambda x: -x["amount"])
        selected = []
        seen_clients = set()
        for case in cases_sorted:
            client = case["client"]
            if client in seen_clients:
                continue
            seen_clients.add(client)

            site_name = extract_site_name(case["name"], client)
            region = extract_region(case["name"])
            svc_label = SERVICE_DISPLAY.get(case["service"], {}).get("label", case["service"])

            # 説明文: 現場名があれば表示、なければサービス種別の汎用説明
            if site_name:
                description = site_name
            else:
                description = _generic_description(case["service"])

            selected.append({
                "site_name": site_name,
                "region": region,
                "service": svc_label,
                "amount_range": anonymize_amount(case["amount"]),
                "description": description,
                "client_label": anonymize_client(client, ind),
            })
            if len(selected) >= 6:
                break

        section = {
            "industry": ind,
            "display": display,
            "count": data["count"],
            "total_revenue_range": anonymize_amount(data["total_revenue"] / data["count"]),
            "services": dict(data["services"]),
            "cases": selected,
        }
        case_sections.append(section)

    summary = {
        "total_won": len(won),
        "total_revenue": sum(r["amount"] for r in won),
        "industries": len(case_sections),
        "generated_at": datetime.now().isoformat(),
    }

    return {"summary": summary, "sections": case_sections}


def _generic_description(service):
    """現場名がない場合の汎用説明"""
    descs = {
        "現場空撮": "建設現場の定期空撮記録",
        "ドローン測量": "ドローン測量による出来形管理",
        "眺望撮影": "建設予定地の眺望シミュレーション撮影",
        "点検": "施設のドローン点検",
        "その他": "ドローン撮影業務",
    }
    return descs.get(service, "ドローン撮影業務")


# ── HTML生成 ──

def generate_html(page_data):
    """業種別フィルター付き事例ページHTMLを生成"""
    sections = page_data["sections"]
    summary = page_data["summary"]

    html_parts = []

    # サマリーセクション
    html_parts.append(f"""
<!-- 導入実績サマリー - 自動生成 {summary['generated_at'][:10]} -->
<div class="case-summary" style="background: linear-gradient(135deg, #1a3c6e 0%, #2e5d9e 100%); color: #fff; padding: 40px; border-radius: 12px; margin-bottom: 40px; text-align: center;">
  <h2 style="color: #fff; font-size: 28px; margin-bottom: 20px;">導入実績</h2>
  <div style="display: flex; justify-content: center; gap: 40px; flex-wrap: wrap;">
    <div>
      <div style="font-size: 42px; font-weight: bold;">{summary['total_won']}<span style="font-size: 18px;">件</span></div>
      <div style="font-size: 14px; opacity: 0.8;">受注実績</div>
    </div>
    <div>
      <div style="font-size: 42px; font-weight: bold;">{len(sections)}<span style="font-size: 18px;">業種</span></div>
      <div style="font-size: 14px; opacity: 0.8;">対応業種</div>
    </div>
  </div>
</div>
""")

    # 業種フィルターボタン
    filter_buttons = []
    filter_buttons.append(
        '<button class="case-filter-btn active" data-filter="all" '
        'style="margin: 4px; padding: 8px 16px; border: 2px solid #1a3c6e; '
        'border-radius: 20px; background: #1a3c6e; color: #fff; cursor: pointer; '
        'font-size: 14px;">すべて</button>'
    )
    for section in sections:
        ind = section["industry"]
        display = section["display"]
        slug = ind.replace(" ", "-")
        filter_buttons.append(
            f'<button class="case-filter-btn" data-filter="{slug}" '
            f'style="margin: 4px; padding: 8px 16px; border: 2px solid {display["color"]}; '
            f'border-radius: 20px; background: #fff; color: {display["color"]}; '
            f'cursor: pointer; font-size: 14px;">'
            f'{display["label"]}（{section["count"]}件）</button>'
        )

    html_parts.append(f"""
<!-- 業種フィルター -->
<div class="case-filters" style="text-align: center; margin-bottom: 30px;">
  {''.join(filter_buttons)}
</div>
""")

    # 各業種セクション
    for section in sections:
        ind = section["industry"]
        display = section["display"]
        slug = ind.replace(" ", "-")

        cases_html = []
        for case in section["cases"]:
            # 現場名の表示（あれば太字で表示）
            site_display = ""
            if case.get("site_name"):
                site_display = (
                    f'<div style="font-size: 15px; font-weight: bold; color: #222; '
                    f'margin-bottom: 6px;">{case["site_name"]}</div>'
                )

            cases_html.append(f"""
      <div class="case-card" style="background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
          <span style="background: {display['color']}; color: #fff; padding: 3px 10px; border-radius: 4px; font-size: 12px;">{case['service']}</span>
          <span style="color: #666; font-size: 13px;">{case['region']}</span>
        </div>
        {site_display}<p style="font-size: 14px; color: #555; margin: 4px 0 8px 0;">{case['client_label']}の案件</p>
        <div style="font-size: 13px; color: #888; border-top: 1px solid #f0f0f0; padding-top: 8px; margin-top: 8px;">
          契約金額帯: {case['amount_range']}
        </div>
      </div>""")

        # サービス内訳バッジ
        svc_badges = []
        for svc, cnt in sorted(section["services"].items(), key=lambda x: -x[1]):
            svc_label = SERVICE_DISPLAY.get(svc, {}).get("label", svc)
            svc_badges.append(
                f'<span style="background: #f5f5f5; padding: 4px 12px; border-radius: 12px; '
                f'font-size: 13px; margin: 2px;">{svc_label}: {cnt}件</span>'
            )

        html_parts.append(f"""
<!-- {display['label']} -->
<div class="case-section" data-industry="{slug}" style="margin-bottom: 40px;">
  <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px;">
    <div style="width: 4px; height: 28px; background: {display['color']}; border-radius: 2px;"></div>
    <h3 style="font-size: 22px; color: #333; margin: 0;">{display['label']}</h3>
    <span style="background: {display['color']}; color: #fff; padding: 2px 10px; border-radius: 12px; font-size: 13px;">{section['count']}件</span>
  </div>
  <p style="color: #666; margin-bottom: 12px; padding-left: 16px;">{display['description']}</p>
  <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; padding-left: 16px;">
    {''.join(svc_badges)}
  </div>
  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px;">
    {''.join(cases_html)}
  </div>
</div>
""")

    # CTA セクション
    html_parts.append("""
<!-- CTA -->
<div style="background: #f8f9fa; border: 2px solid #1a3c6e; border-radius: 12px; padding: 40px; text-align: center; margin-top: 40px;">
  <h3 style="font-size: 22px; color: #1a3c6e; margin-bottom: 12px;">お見積り・ご相談は無料です</h3>
  <p style="color: #555; margin-bottom: 20px;">現場の課題に合わせた最適なプランをご提案します。<br>まずはお気軽にお問い合わせください。</p>
  <div style="display: flex; justify-content: center; gap: 16px; flex-wrap: wrap;">
    <a href="/contact/" style="display: inline-block; background: #1a3c6e; color: #fff; padding: 14px 40px; border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold;">お問い合わせはこちら</a>
    <a href="tel:052-627-7010" style="display: inline-block; background: #fff; color: #1a3c6e; padding: 14px 40px; border-radius: 6px; text-decoration: none; font-size: 16px; font-weight: bold; border: 2px solid #1a3c6e;">052-627-7010</a>
  </div>
</div>
""")

    # フィルターJS
    html_parts.append("""
<script>
document.addEventListener('DOMContentLoaded', function() {
  var btns = document.querySelectorAll('.case-filter-btn');
  var sections = document.querySelectorAll('.case-section');
  btns.forEach(function(btn) {
    btn.addEventListener('click', function() {
      btns.forEach(function(b) {
        b.style.background = '#fff';
        b.style.color = b.style.borderColor || '#1a3c6e';
        b.classList.remove('active');
      });
      btn.style.background = btn.style.borderColor;
      btn.style.color = '#fff';
      btn.classList.add('active');
      var filter = btn.getAttribute('data-filter');
      sections.forEach(function(sec) {
        if (filter === 'all' || sec.getAttribute('data-industry') === filter) {
          sec.style.display = '';
        } else {
          sec.style.display = 'none';
        }
      });
    });
  });
});
</script>
""")

    return "\n".join(html_parts)


# ── メイン処理 ──

def main():
    dry_run = "--dry-run" in sys.argv
    notify = "--notify" in sys.argv

    print("=" * 60)
    print("  事例ページ統合自動更新（v2）")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 1. Lark CRM から受注台帳を取得
    print("\nLark CRM接続中...")
    token = lark_get_token()
    print("受注台帳を取得中...")
    records = lark_list_records(token, ORDER_TABLE_ID)
    print(f"  全レコード: {len(records)}件")

    # 2. 事例データを構築
    print("\n事例データ構築中...")
    page_data = build_case_data(records)
    print(f"  業種セクション: {len(page_data['sections'])}件")
    for sec in page_data["sections"]:
        print(f"    {sec['industry']}: {sec['count']}件, 代表事例{len(sec['cases'])}件")

    # 3. JSON保存
    date_str = datetime.now().strftime("%Y%m%d")
    json_path = CONTENT_DIR / f"case_page_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(page_data, f, ensure_ascii=False, indent=2)
    print(f"\nJSON出力: {json_path}")

    # 4. HTML生成
    print("\nHTML生成中...")
    html = generate_html(page_data)
    html_path = CONTENT_DIR / f"case_page_html_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML出力: {html_path}")
    print(f"  サイズ: {len(html):,} bytes")

    if dry_run:
        print("\n[dry-run] WordPress更新をスキップ")
        print("  本番実行: python3 auto_case_updater.py")
        print(f"  HTMLプレビュー: {html_path}")
        return

    # 5. wp_safe_deploy.py 経由でWordPress更新
    print("\nWordPress更新中（wp_safe_deploy.py経由）...")
    sys.path.insert(0, str(SCRIPT_DIR))
    from wp_safe_deploy import safe_update_page

    # 事例ページはページコンテンツブロック（H1・meta descriptionはWP側で管理）
    # CTA・電話番号・問い合わせリンクは全てHTML内に含まれている
    # review_agentの「article」プロファイルはフルページ前提のため、
    # ページコンテンツブロックでは誤検知が発生しやすい
    # → deploy プロファイル（秘密情報漏洩チェック）で検証する
    ok = safe_update_page(CASES_PAGE_ID, html, profile="deploy")
    if not ok:
        print("WordPress更新失敗")
        sys.exit(1)

    print("WordPress更新完了")

    # 6. Lark通知
    if notify:
        summary = page_data["summary"]
        msg = (
            f"事例ページ自動更新完了\n"
            f"受注実績: {summary['total_won']}件\n"
            f"業種: {summary['industries']}種\n"
            f"更新日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        send_lark_dm(token, msg)
        print("[Lark通知送信完了]")

    print("\n" + "=" * 60)
    print("  完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
