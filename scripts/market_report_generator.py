#!/usr/bin/env python3
"""
自社実績ベース市場レポート自動生成（施策1: 実データの公開資産化）

CRM受注台帳からドローン測量の統計データを集計し、
WordPressの固定ページとして月次自動更新する。

公開データ:
  - 業種別平均単価（建設/官公庁/不動産 etc.）
  - 季節変動（月別受注件数トレンド）
  - 面積帯別コスト曲線
  - 東海エリア市場動向サマリー

注意:
  - 具体的な顧客名・個別金額は絶対に出さない（統計・集計値のみ）
  - WordPress変更はwp_safe_deploy.py経由

Usage:
    python3 market_report_generator.py --dry-run     # プレビューのみ
    python3 market_report_generator.py --generate     # HTML生成→/tmp/market_report.html
    python3 market_report_generator.py --deploy        # WordPress固定ページに公開
    python3 market_report_generator.py --deploy --indexnow  # 公開後IndexNow通知

cron (GitHub Actions):
    毎月1日 9:00 JST
"""

import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config, get_wp_auth, get_wp_api_url
from lib.lark_api import lark_get_token, lark_list_records

# CRM テーブルID
TABLE_ORDERS = "tbldLj2iMJYocct6"

# WordPress固定ページID（初回は手動作成してIDを記入）
# TODO: ページ作成後にIDを設定
MARKET_REPORT_PAGE_ID = 7159

# 業種分類マッピング
INDUSTRY_MAP = {
    "建設": ["建設", "土木", "施工", "ゼネコン", "建築"],
    "官公庁": ["官公庁", "市役所", "県", "国交省", "自治体", "公共"],
    "不動産": ["不動産", "デベロッパー", "開発"],
    "測量・コンサル": ["測量", "コンサル", "設計"],
    "エネルギー": ["電力", "エネルギー", "太陽光", "メガソーラー"],
    "その他": [],
}

# 面積帯
AREA_BANDS = [
    (0, 1000, "~1,000m2"),
    (1000, 5000, "1,000~5,000m2"),
    (5000, 10000, "5,000~10,000m2"),
    (10000, 50000, "10,000~50,000m2"),
    (50000, float("inf"), "50,000m2~"),
]


def classify_industry(account_name, deal_name=""):
    """取引先名・商談名から業種を分類"""
    text = f"{account_name} {deal_name}".lower()
    for industry, keywords in INDUSTRY_MAP.items():
        if industry == "その他":
            continue
        for kw in keywords:
            if kw.lower() in text:
                return industry
    return "その他"


def classify_area_band(area_m2):
    """面積帯を分類"""
    if area_m2 is None or area_m2 <= 0:
        return None
    for low, high, label in AREA_BANDS:
        if low <= area_m2 < high:
            return label
    return None


def _field_str(fields, key, default=""):
    val = fields.get(key, default)
    if val is None:
        return default
    if isinstance(val, list):
        parts = []
        for item in val:
            if isinstance(item, dict):
                parts.append(
                    item.get("text", "")
                    or item.get("name", "")
                    or item.get("text_value", "")
                    or str(item)
                )
            else:
                parts.append(str(item))
        return ", ".join(parts) if parts else default
    return str(val)


def _field_num(fields, key, default=0):
    val = fields.get(key)
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _field_timestamp(fields, key):
    val = fields.get(key)
    if isinstance(val, (int, float)) and val > 0:
        return datetime.fromtimestamp(val / 1000)
    return None


def fetch_order_data(cfg):
    """CRM受注台帳から統計データを取得"""
    token = lark_get_token(cfg)
    records = lark_list_records(token, TABLE_ORDERS, cfg=cfg)
    print(f"  受注台帳: {len(records)}件取得")

    orders = []
    for rec in records:
        f = rec.get("fields", {})

        # 取引先名（リンクフィールドから取得）
        account_name = _field_str(f, "取引先", "")
        deal_name = _field_str(f, "現場名", "") or _field_str(f, "案件名", "")

        # 金額
        amount = _field_num(f, "受注金額", 0)
        if amount <= 0:
            amount = _field_num(f, "金額", 0)

        # 面積
        area = _field_num(f, "面積", 0) or _field_num(f, "対象面積", 0)

        # 受注日・納品日
        order_date = _field_timestamp(f, "受注日")
        delivery_date = _field_timestamp(f, "納品日")

        # ステータス
        status = _field_str(f, "ステータス", "")

        if amount > 0:
            orders.append({
                "account": account_name,
                "deal": deal_name,
                "amount": amount,
                "area": area if area > 0 else None,
                "order_date": order_date,
                "delivery_date": delivery_date,
                "status": status,
                "industry": classify_industry(account_name, deal_name),
            })

    print(f"  有効受注: {len(orders)}件（金額>0）")
    return orders


def compute_statistics(orders):
    """統計データを集計"""
    stats = {
        "total_orders": len(orders),
        "total_revenue": sum(o["amount"] for o in orders),
        "avg_amount": 0,
        "by_industry": {},
        "by_month": {},
        "by_area_band": {},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if orders:
        stats["avg_amount"] = stats["total_revenue"] / len(orders)

    # 業種別
    industry_data = defaultdict(lambda: {"count": 0, "total": 0, "amounts": []})
    for o in orders:
        ind = o["industry"]
        industry_data[ind]["count"] += 1
        industry_data[ind]["total"] += o["amount"]
        industry_data[ind]["amounts"].append(o["amount"])

    for ind, data in industry_data.items():
        data["avg"] = data["total"] / data["count"] if data["count"] > 0 else 0
        data["min"] = min(data["amounts"]) if data["amounts"] else 0
        data["max"] = max(data["amounts"]) if data["amounts"] else 0
        # 具体金額は出さず、レンジのみ
        del data["amounts"]
    stats["by_industry"] = dict(industry_data)

    # 月別（季節変動）
    month_data = defaultdict(lambda: {"count": 0, "total": 0})
    for o in orders:
        if o["order_date"]:
            key = o["order_date"].strftime("%Y-%m")
            month_data[key]["count"] += 1
            month_data[key]["total"] += o["amount"]
    stats["by_month"] = dict(sorted(month_data.items()))

    # 面積帯別
    area_data = defaultdict(lambda: {"count": 0, "total": 0, "amounts": []})
    for o in orders:
        if o["area"]:
            band = classify_area_band(o["area"])
            if band:
                area_data[band]["count"] += 1
                area_data[band]["total"] += o["amount"]
                area_data[band]["amounts"].append(o["amount"])

    for band, data in area_data.items():
        data["avg"] = data["total"] / data["count"] if data["count"] > 0 else 0
        data["unit_price"] = None
        # 面積帯の中央値から単価を推定
        del data["amounts"]
    stats["by_area_band"] = dict(area_data)

    return stats


def generate_html(stats):
    """WordPress用HTMLを生成（社外秘情報を含まない）"""
    now = stats["generated_at"]
    total = stats["total_orders"]

    # 業種別テーブル
    industry_rows = ""
    for ind, data in sorted(stats["by_industry"].items(), key=lambda x: -x[1]["count"]):
        pct = (data["count"] / total * 100) if total > 0 else 0
        avg_man = data["avg"] / 10000 if data["avg"] > 0 else 0
        industry_rows += f"""
        <tr>
            <td>{ind}</td>
            <td>{data['count']}件</td>
            <td>{pct:.0f}%</td>
            <td>{avg_man:.0f}万円</td>
        </tr>"""

    # 月別トレンド（直近12ヶ月）
    months = sorted(stats["by_month"].keys())[-12:]
    month_labels = json.dumps([m[-5:] for m in months])
    month_counts = json.dumps([stats["by_month"][m]["count"] for m in months])
    month_amounts = json.dumps(
        [round(stats["by_month"][m]["total"] / 10000) for m in months]
    )

    # 面積帯テーブル
    area_order = ["~1,000m2", "1,000~5,000m2", "5,000~10,000m2",
                  "10,000~50,000m2", "50,000m2~"]
    area_rows = ""
    for band in area_order:
        if band in stats["by_area_band"]:
            data = stats["by_area_band"][band]
            avg_man = data["avg"] / 10000 if data["avg"] > 0 else 0
            area_rows += f"""
            <tr>
                <td>{band}</td>
                <td>{data['count']}件</td>
                <td>{avg_man:.0f}万円</td>
            </tr>"""

    html = f"""
<!-- 東海エリア ドローン測量 市場レポート（自社実績ベース）-->
<!-- 最終更新: {now} / 自動生成: market_report_generator.py -->
<!-- 注意: 統計・集計値のみ。具体的な顧客名・個別金額は含まない -->

<div class="market-report" style="max-width: 900px; margin: 0 auto; font-family: sans-serif;">

<div style="background: #f0f4f8; border-radius: 8px; padding: 24px; margin-bottom: 32px;">
    <p style="font-size: 14px; color: #666; margin: 0 0 8px;">
        本レポートは東海エアサービス株式会社の実績データに基づく統計情報です。
        <strong>月次自動更新</strong>（最終更新: {now}）
    </p>
    <div style="display: flex; gap: 24px; flex-wrap: wrap;">
        <div style="text-align: center;">
            <div style="font-size: 36px; font-weight: bold; color: #1a56db;">{total}</div>
            <div style="font-size: 13px; color: #666;">累計案件数</div>
        </div>
        <div style="text-align: center;">
            <div style="font-size: 36px; font-weight: bold; color: #1a56db;">{stats['avg_amount']/10000:.0f}<span style="font-size: 18px;">万円</span></div>
            <div style="font-size: 13px; color: #666;">平均受注単価</div>
        </div>
    </div>
</div>

<h2 style="border-bottom: 2px solid #1a56db; padding-bottom: 8px;">業種別 受注傾向</h2>
<table style="width: 100%; border-collapse: collapse; margin-bottom: 32px;">
    <thead>
        <tr style="background: #f8fafc;">
            <th style="padding: 10px; text-align: left; border-bottom: 2px solid #e2e8f0;">業種</th>
            <th style="padding: 10px; text-align: right; border-bottom: 2px solid #e2e8f0;">件数</th>
            <th style="padding: 10px; text-align: right; border-bottom: 2px solid #e2e8f0;">構成比</th>
            <th style="padding: 10px; text-align: right; border-bottom: 2px solid #e2e8f0;">平均単価</th>
        </tr>
    </thead>
    <tbody>{industry_rows}
    </tbody>
</table>

<h2 style="border-bottom: 2px solid #1a56db; padding-bottom: 8px;">月別受注トレンド（直近12ヶ月）</h2>
<div style="margin-bottom: 32px;">
    <canvas id="monthlyChart" width="800" height="300"></canvas>
</div>

<h2 style="border-bottom: 2px solid #1a56db; padding-bottom: 8px;">面積帯別 コスト目安</h2>
<p style="font-size: 14px; color: #666;">ドローン測量の費用は対象面積によって大きく変動します。以下は当社実績の統計値です。</p>
<table style="width: 100%; border-collapse: collapse; margin-bottom: 32px;">
    <thead>
        <tr style="background: #f8fafc;">
            <th style="padding: 10px; text-align: left; border-bottom: 2px solid #e2e8f0;">対象面積</th>
            <th style="padding: 10px; text-align: right; border-bottom: 2px solid #e2e8f0;">実績件数</th>
            <th style="padding: 10px; text-align: right; border-bottom: 2px solid #e2e8f0;">平均費用</th>
        </tr>
    </thead>
    <tbody>{area_rows}
    </tbody>
</table>

<div style="background: #eff6ff; border-left: 4px solid #1a56db; padding: 16px; margin-top: 32px; border-radius: 0 8px 8px 0;">
    <p style="margin: 0; font-size: 14px;">
        <strong>データソースについて</strong><br>
        本レポートは東海エアサービス株式会社が実際に受注・納品したドローン測量案件の統計データです。
        第三者の推計や業界平均ではなく、<strong>実績に基づくオリジナルデータ</strong>です。
        個別案件の詳細や顧客情報は含まれていません。
    </p>
</div>

<div style="text-align: center; margin-top: 32px; padding: 24px; background: #f8fafc; border-radius: 8px;">
    <p style="font-size: 16px; margin: 0 0 12px;">御社の測量案件も無料でお見積りします</p>
    <a href="https://www.tokaiair.com/contact/" style="display: inline-block; background: #1a56db; color: #fff; padding: 12px 32px; border-radius: 6px; text-decoration: none; font-weight: bold;">
        無料見積もりを依頼する
    </a>
</div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    var ctx = document.getElementById('monthlyChart');
    if (ctx) {{
        new Chart(ctx, {{
            type: 'bar',
            data: {{
                labels: {month_labels},
                datasets: [{{
                    label: '受注件数',
                    data: {month_counts},
                    backgroundColor: 'rgba(26, 86, 219, 0.7)',
                    yAxisID: 'y'
                }}, {{
                    label: '受注額(万円)',
                    data: {month_amounts},
                    type: 'line',
                    borderColor: '#e63946',
                    backgroundColor: 'transparent',
                    yAxisID: 'y1'
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    y: {{ position: 'left', title: {{ display: true, text: '件数' }} }},
                    y1: {{ position: 'right', title: {{ display: true, text: '万円' }}, grid: {{ drawOnChartArea: false }} }}
                }}
            }}
        }});
    }}
}});
</script>
"""
    return html


def deploy_to_wordpress(cfg, html, dry_run=False):
    """WordPressに市場レポートページをデプロイ"""
    if MARKET_REPORT_PAGE_ID is None:
        print("[INFO] MARKET_REPORT_PAGE_ID が未設定です。")
        print("[INFO] WordPress管理画面で固定ページを作成し、IDを設定してください。")
        print("[INFO] slug: drone-survey-market-report")
        print("[INFO] title: 東海エリア ドローン測量 市場レポート（自社実績ベース）")
        # HTMLファイルとして出力
        out_path = Path("/tmp/market_report.html")
        out_path.write_text(html, encoding="utf-8")
        print(f"[INFO] HTMLを {out_path} に出力しました")
        return False

    if dry_run:
        print("[DRY-RUN] デプロイをスキップします")
        return True

    # wp_safe_deploy経由でデプロイ
    from wp_safe_deploy import safe_update_page
    result = safe_update_page(MARKET_REPORT_PAGE_ID, html)
    if result:
        print(f"[OK] ページID {MARKET_REPORT_PAGE_ID} を更新しました")
    return result


def submit_indexnow(cfg, page_slug="drone-survey-market-report"):
    """IndexNowに更新通知"""
    try:
        from indexnow_submit import submit_single
        api_key = cfg.get("indexnow", {}).get("api_key", "")
        if api_key:
            url = f"https://www.tokaiair.com/{page_slug}/"
            return submit_single(api_key, url)
    except Exception as e:
        print(f"[WARN] IndexNow通知失敗: {e}")
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="自社実績ベース市場レポート生成")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")
    parser.add_argument("--generate", action="store_true", help="HTML生成")
    parser.add_argument("--deploy", action="store_true", help="WordPress公開")
    parser.add_argument("--indexnow", action="store_true", help="IndexNow通知")
    parser.add_argument("--stats-json", action="store_true", help="統計JSONを出力")
    args = parser.parse_args()

    if not any([args.dry_run, args.generate, args.deploy, args.stats_json]):
        parser.print_help()
        sys.exit(1)

    cfg = load_config()
    print("=== 市場レポート生成 ===")

    # データ取得
    print("[1/4] CRM受注台帳からデータ取得...")
    orders = fetch_order_data(cfg)

    # 統計集計
    print("[2/4] 統計データ集計...")
    stats = compute_statistics(orders)
    print(f"  累計案件: {stats['total_orders']}件")
    print(f"  平均単価: {stats['avg_amount']/10000:.0f}万円")
    print(f"  業種: {len(stats['by_industry'])}分類")

    if args.stats_json:
        json_path = SCRIPT_DIR / "data" / "market_report_stats.json"
        json_path.parent.mkdir(exist_ok=True)
        json_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  統計JSON: {json_path}")

    # HTML生成
    print("[3/4] HTML生成...")
    html = generate_html(stats)

    if args.dry_run or args.generate:
        out_path = Path("/tmp/market_report.html")
        out_path.write_text(html, encoding="utf-8")
        print(f"  HTML出力: {out_path}")

    # デプロイ
    if args.deploy:
        print("[4/4] WordPressデプロイ...")
        deploy_to_wordpress(cfg, html, dry_run=args.dry_run)

        if args.indexnow:
            print("[+] IndexNow通知...")
            submit_indexnow(cfg)

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
