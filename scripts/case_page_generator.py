#!/usr/bin/env python3
"""
事例ページHTML生成スクリプト（ローカルCSV版）
受注台帳の分類データから業種別×サービス別の匿名化された事例ページHTMLを生成

匿名化ルール:
  - 顧客名（取引先名）: 匿名（業種表記）
  - 現場名: そのまま表示OK（公知の施設名・現場名）
  - 金額は範囲表記

注: 本番運用は auto_case_updater.py（Lark CRM直接取得版）を使用
    このスクリプトはローカルCSVからのテスト・プレビュー用

Usage:
  python3 case_page_generator.py --dry-run     # HTML生成のみ（WP更新なし）
  python3 case_page_generator.py               # 生成 + WP更新
  python3 case_page_generator.py --json        # JSON出力のみ

出力:
  - content/case_page_html_YYYYMMDD.html  事例ページHTML
  - content/case_page_data_YYYYMMDD.json  構造化データ
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent
CONTENT_DIR = PROJECT_DIR / "content"
DATA_DIR = PROJECT_DIR / "data"
CONTENT_DIR.mkdir(exist_ok=True)

CSV_PATH = DATA_DIR / "order_classification.csv"

# カテゴリ正規化マップ
SERVICE_MAP = {
    "空撮": "現場空撮",
    "現場空撮": "現場空撮",
    "ドローン測量": "ドローン測量",
    "眺望撮影": "眺望撮影",
    "点検": "点検",
    "その他": "その他",
    "": "その他",
}

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

    # 市区名からの推定
    cities = {
        "名古屋": "愛知県", "豊橋": "愛知県", "豊田": "愛知県", "岡崎": "愛知県",
        "春日井": "愛知県", "一宮": "愛知県", "瀬戸": "愛知県", "半田": "愛知県",
        "東海": "愛知県", "大府": "愛知県", "知多": "愛知県", "昭和区": "愛知県",
        "中区": "愛知県", "千種": "愛知県", "名東": "愛知県", "緑区": "愛知県",
        "港区": "愛知県", "南区": "愛知県", "熱田": "愛知県", "天白": "愛知県",
        "津": "三重県", "四日市": "三重県", "鈴鹿": "三重県",
        "岐阜": "岐阜県", "大垣": "岐阜県", "各務原": "岐阜県",
        "浜松": "静岡県", "沼津": "静岡県",
    }
    for city, pref in cities.items():
        if city in case_name:
            return pref

    return "東海エリア"


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


def get_case_description(case_name, client_name, service):
    """現場名があれば表示、なければサービス種別の汎用説明を返す

    匿名化ルール:
      - 顧客名（取引先名）: 絶対に出さない
      - 現場名: そのまま表示OK
    """
    site = extract_site_name(case_name, client_name)
    if site:
        return site

    GENERIC = {
        "現場空撮": "建設現場の定期空撮記録",
        "ドローン測量": "ドローン測量による出来形管理",
        "眺望撮影": "建設予定地の眺望シミュレーション撮影",
        "点検": "施設のドローン点検",
        "その他": "ドローン撮影業務",
    }
    return GENERIC.get(service, "ドローン撮影業務")


def load_data():
    """CSVデータを読み込み、分類済みレコードを返す"""
    records = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("非案件", "").strip() == "Y":
                continue
            amount = float(row.get("受注金額", 0) or 0)
            industry = INDUSTRY_MAP.get(row.get("業種", "").strip(), "その他")
            service = SERVICE_MAP.get(row.get("サービス種別", "").strip(), "その他")
            source = row.get("出典", "")
            is_won = "受注100" in source

            records.append({
                "案件名": row.get("案件名", ""),
                "取引先名": row.get("取引先名", ""),
                "受注金額": amount,
                "業種": industry,
                "サービス": service,
                "受注": is_won,
                "出典": source,
                "地域": extract_region(row.get("案件名", "")),
            })
    return records


def build_case_page_data(records):
    """事例ページ用の構造化データを生成"""
    # 受注案件のみ抽出
    won = [r for r in records if r["受注"] and r["受注金額"] > 0]

    # 業種別に集計
    by_industry = defaultdict(lambda: {
        "cases": [], "total_revenue": 0, "count": 0,
        "services": defaultdict(int),
    })

    for r in won:
        ind = r["業種"]
        by_industry[ind]["cases"].append(r)
        by_industry[ind]["total_revenue"] += r["受注金額"]
        by_industry[ind]["count"] += 1
        by_industry[ind]["services"][r["サービス"]] += 1

    # 事例データ構築（業種別に代表事例を選定）
    case_sections = []
    for ind in INDUSTRY_ORDER:
        data = by_industry.get(ind)
        if not data or data["count"] == 0:
            continue

        display = INDUSTRY_DISPLAY.get(ind, INDUSTRY_DISPLAY["その他"])

        # 代表事例を選定（金額降順、同一取引先は1件のみ）
        cases_sorted = sorted(data["cases"], key=lambda x: -x["受注金額"])
        selected = []
        seen_clients = set()
        for case in cases_sorted:
            client = case["取引先名"]
            if client in seen_clients:
                continue
            seen_clients.add(client)
            site_name = extract_site_name(case["案件名"], case["取引先名"])
            description = get_case_description(case["案件名"], case["取引先名"], case["サービス"])
            selected.append({
                "site_name": site_name,
                "region": case["地域"],
                "service": SERVICE_DISPLAY.get(case["サービス"], {}).get("label", case["サービス"]),
                "amount_range": anonymize_amount(case["受注金額"]),
                "description": description,
                "client_label": INDUSTRY_DISPLAY.get(ind, INDUSTRY_DISPLAY["その他"])["label"],
            })
            if len(selected) >= 5:
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

    # サマリー統計
    summary = {
        "total_won": len(won),
        "total_revenue": sum(r["受注金額"] for r in won),
        "industries": len(case_sections),
        "generated_at": datetime.now().isoformat(),
    }

    return {"summary": summary, "sections": case_sections}


def generate_html(page_data):
    """事例ページ用HTMLを生成"""
    sections = page_data["sections"]
    summary = page_data["summary"]

    html_parts = []

    # サマリーセクション
    html_parts.append(f"""
<!-- 導入実績サマリー -->
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
    filter_buttons.append('<button class="case-filter-btn active" data-filter="all" style="margin: 4px; padding: 8px 16px; border: 2px solid #1a3c6e; border-radius: 20px; background: #1a3c6e; color: #fff; cursor: pointer; font-size: 14px;">すべて</button>')
    for section in sections:
        ind = section["industry"]
        display = section["display"]
        slug = ind.replace(" ", "-")
        filter_buttons.append(
            f'<button class="case-filter-btn" data-filter="{slug}" style="margin: 4px; padding: 8px 16px; border: 2px solid {display["color"]}; border-radius: 20px; background: #fff; color: {display["color"]}; cursor: pointer; font-size: 14px;">{display["label"]}（{section["count"]}件）</button>'
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
        for i, case in enumerate(section["cases"]):
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
        {site_display}<p style="font-size: 14px; color: #555; margin: 4px 0 8px 0;">{case.get('client_label', '')}の案件</p>
        <div style="font-size: 13px; color: #888; border-top: 1px solid #f0f0f0; padding-top: 8px; margin-top: 8px;">
          契約金額帯: {case['amount_range']}
        </div>
      </div>""")

        # サービス内訳バッジ
        svc_badges = []
        for svc, cnt in sorted(section["services"].items(), key=lambda x: -x[1]):
            svc_label = SERVICE_DISPLAY.get(svc, {}).get("label", svc)
            svc_badges.append(f'<span style="background: #f5f5f5; padding: 4px 12px; border-radius: 12px; font-size: 13px; margin: 2px;">{svc_label}: {cnt}件</span>')

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
        b.style.color = b.getAttribute('data-color') || '#1a3c6e';
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


def main():
    dry_run = "--dry-run" in sys.argv
    json_only = "--json" in sys.argv

    print("=" * 60)
    print("  事例ページHTML生成")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # データ読み込み
    print("\nデータ読み込み中...")
    records = load_data()
    print(f"  有効案件: {len(records)}件")

    won = [r for r in records if r["受注"]]
    print(f"  受注案件: {len(won)}件")

    # 構造化データ生成
    print("\n事例データ構築中...")
    page_data = build_case_page_data(records)
    print(f"  業種セクション: {len(page_data['sections'])}件")
    for sec in page_data["sections"]:
        print(f"    {sec['industry']}: {sec['count']}件, 代表事例{len(sec['cases'])}件")

    # JSON出力
    date_str = datetime.now().strftime("%Y%m%d")
    json_path = CONTENT_DIR / f"case_page_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(page_data, f, ensure_ascii=False, indent=2)
    print(f"\nJSON出力: {json_path}")

    if json_only:
        print("\n[json-only] HTML生成をスキップ")
        return

    # HTML生成
    print("\nHTML生成中...")
    html = generate_html(page_data)
    html_path = CONTENT_DIR / f"case_page_html_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML出力: {html_path}")
    print(f"  サイズ: {len(html):,} bytes")

    if dry_run:
        print("\n[dry-run] WordPress更新をスキップ")
        print("  本番実行: python3 case_page_generator.py")
        return

    # WordPress更新はwp_safe_deploy.py経由で行う
    print("\nWordPress更新:")
    print("  事例ページHTMLが生成されました。")
    print("  WordPress反映は wp_safe_deploy.py 経由で実施してください。")
    print(f"  対象ページID: 4846")
    print(f"  HTMLファイル: {html_path}")

    print("\n" + "=" * 60)
    print("  完了")
    print("=" * 60)


if __name__ == "__main__":
    main()
