#!/usr/bin/env python3
"""
CRM + Web分析 ダッシュボード生成スクリプト

Lark BaseからCRM・GA4・GSCデータを取得し、
HTMLダッシュボードを生成する。

Usage:
    python3 generate_dashboard.py
    # → dashboard.html を生成

Output:
    /mnt/c/Users/USER/Documents/_data/tas-automation/dashboard.html
"""

import json
import urllib.request
from datetime import datetime
from collections import Counter, defaultdict
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
OUTPUT_PATH = SCRIPT_DIR.parent / "dashboard.html"
CONFIG_PATH = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
SERVICE_ACCOUNT_PATH = Path("/mnt/c/Users/USER/Documents/_data/google_service_account.json")
PL_SPREADSHEET_ID = "1ag_f3oKcLIrqWzAj-21Owhlye-a7aNiyscRf71dBbbQ"
PL_SHEET_NAME = "2025年度"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_token(cfg):
    lark = cfg["lark"]
    data = json.dumps({"app_id": lark["app_id"], "app_secret": lark["app_secret"]}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())["tenant_access_token"]


def get_records(token, base_token, table_id, max_pages=5):
    records = []
    page_token = None
    for _ in range(max_pages):
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read())
        records.extend(data.get("data", {}).get("items", []))
        if not data.get("data", {}).get("has_more"):
            break
        page_token = data["data"].get("page_token")
    return records


def get_pl_data():
    """Google SheetsからP&Lデータを取得"""
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_PATH),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=creds)
    sheet = service.spreadsheets()

    # A1:S30 を一括取得（月次データは列H=index7 以降）
    result = sheet.values().get(
        spreadsheetId=PL_SPREADSHEET_ID,
        range=f"{PL_SHEET_NAME}!A1:S30"
    ).execute()
    rows = result.get("values", [])

    if len(rows) < 30:
        print(f"  P&Lデータ: {len(rows)}行（不足の可能性あり）")

    DATA_START_COL = 7  # 列H = index 7

    def parse_row(row_idx):
        """指定行の月次数値データを取得（列H以降）"""
        if row_idx >= len(rows):
            return []
        row = rows[row_idx]
        values = []
        for cell in row[DATA_START_COL:]:
            try:
                cleaned = str(cell).replace(",", "").replace("¥", "").replace("￥", "").replace(" ", "").replace("円", "")
                if cleaned in ("", "-", "―"):
                    values.append(0)
                else:
                    values.append(float(cleaned))
            except (ValueError, TypeError):
                values.append(0)
        return values

    # Row 2 (index 1): 月名（列H以降）
    months_row = rows[1] if len(rows) > 1 else []
    month_labels = []
    for m in months_row[DATA_START_COL:]:
        # 全角数字を半角に変換
        label = str(m)
        for zf, hf in zip("０１２３４５６７８９", "0123456789"):
            label = label.replace(zf, hf)
        month_labels.append(label)

    pl_data = {
        "months": month_labels,
        "revenue": parse_row(2),       # Row 3: 全売上
        "cost": parse_row(3),          # Row 4: 全コスト
        "operating_profit": parse_row(8),  # Row 9: 営業利益
        "net_profit": parse_row(9),    # Row 10: 純利益
        "tokai_revenue": parse_row(12),  # Row 13: 東海工測売上
        "direct_revenue": parse_row(29),  # Row 30: 直取引売上
    }
    return pl_data


def generate_dashboard():
    cfg = load_config()
    token = get_token(cfg)
    crm_base = cfg["lark"]["crm_base_token"]
    web_base = "Vy65bp8Wia7UkZs8CWCjPSqJpyf"

    print("データ取得中...")

    # P&L
    print("  P&Lデータ取得中...")
    try:
        pl = get_pl_data()
        print(f"  P&L: {len(pl['months'])}ヶ月分")
    except Exception as e:
        print(f"  P&L取得エラー: {e}")
        pl = {"months": [], "revenue": [], "cost": [], "operating_profit": [],
              "net_profit": [], "tokai_revenue": [], "direct_revenue": []}

    # CRM
    deals = get_records(token, crm_base, "tbl1rM86nAw9l3bP")
    orders = get_records(token, crm_base, "tbldLj2iMJYocct6")
    contacts = get_records(token, crm_base, "tblN53hFIQoo4W8j")

    # Web
    ga4_pages = get_records(token, web_base, "tbluRdPdhuyjH5a3")
    ga4_trend = get_records(token, web_base, "tblYHA6j48u7TiZj")
    ga4_sources = get_records(token, web_base, "tbl8fBPQMxlF2JyJ")
    gsc_queries = get_records(token, web_base, "tbl5sk2e1MfjtsUz")

    print(f"  商談: {len(deals)}, 受注: {len(orders)}, 連絡先: {len(contacts)}")
    print(f"  GA4ページ: {len(ga4_pages)}, トレンド: {len(ga4_trend)}, 流入: {len(ga4_sources)}, GSC: {len(gsc_queries)}")

    # === CRM集計 ===
    # 商談ステージ
    stage_counts = Counter()
    for d in deals:
        stage = d["fields"].get("商談ステージ") or "未設定"
        stage_counts[stage] += 1

    # 温度感
    temp_counts = Counter()
    for c in contacts:
        temp = c["fields"].get("温度感スコア") or "未設定"
        temp_counts[temp] += 1

    # 接触チャネル
    channel_counts = Counter()
    for c in contacts:
        ch = c["fields"].get("接触チャネル") or "未設定"
        channel_counts[ch] += 1

    # 流入元
    source_counts = Counter()
    for c in contacts:
        src = c["fields"].get("流入元") or "未設定"
        source_counts[src] += 1

    # 受注金額
    total_revenue = 0
    for o in orders:
        amount = o["fields"].get("受注金額") or o["fields"].get("金額") or 0
        if isinstance(amount, (int, float)):
            total_revenue += amount

    # === Web集計 ===
    # トップページ
    top_pages = sorted(ga4_pages, key=lambda x: x["fields"].get("ページビュー", 0) or 0, reverse=True)[:15]

    # トレンド（週次）
    trend_data = sorted(ga4_trend, key=lambda x: str(x["fields"].get("週", "")))

    # 流入経路
    top_sources = sorted(ga4_sources, key=lambda x: x["fields"].get("セッション", 0) or 0, reverse=True)[:10]

    # GSCクエリ
    top_queries = sorted(gsc_queries, key=lambda x: x["fields"].get("GSC検索クリック", 0) if "GSC検索クリック" in x["fields"] else 0, reverse=True)[:15]

    # === HTML生成 ===
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # P&L KPI値（直近月のデータ）
    latest_revenue = 0
    latest_profit = 0
    latest_month_label = ""
    if pl["revenue"]:
        # 直近のゼロでないデータを探す
        for i in range(len(pl["revenue"]) - 1, -1, -1):
            if pl["revenue"][i] != 0:
                latest_revenue = pl["revenue"][i]
                latest_profit = pl["net_profit"][i] if i < len(pl["net_profit"]) else 0
                latest_month_label = pl["months"][i] if i < len(pl["months"]) else ""
                break

    # KPIカード
    pl_kpi = ""
    if latest_month_label:
        pl_kpi = f"""
      <div class="kpi-card">
        <div class="kpi-value">&yen;{latest_revenue:,.0f}</div>
        <div class="kpi-label">{latest_month_label}月 売上</div>
      </div>
      <div class="kpi-card {'accent-green' if latest_profit >= 0 else 'accent-red'}">
        <div class="kpi-value">&yen;{latest_profit:,.0f}</div>
        <div class="kpi-label">{latest_month_label}月 純利益</div>
      </div>
"""

    kpi_cards = f"""
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-value">{len(deals)}</div>
        <div class="kpi-label">商談数</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{len(contacts)}</div>
        <div class="kpi-label">連絡先</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-value">{len(orders)}</div>
        <div class="kpi-label">受注件数</div>
      </div>
      <div class="kpi-card accent">
        <div class="kpi-value">&yen;{total_revenue:,.0f}</div>
        <div class="kpi-label">受注金額合計</div>
      </div>
      {pl_kpi}
    </div>
    """

    # 商談ステージ
    stage_rows = ""
    stage_colors = {"未設定": "#999", "リード獲得": "#3498db", "ヒアリング": "#e8a838",
                    "不在": "#95a5a6", "受注": "#27ae60", "見積検討": "#9b59b6"}
    for stage, count in stage_counts.most_common():
        pct = count / len(deals) * 100
        color = stage_colors.get(stage, "#666")
        stage_rows += f'<div class="bar-row"><span class="bar-label">{stage}</span><div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div><span class="bar-value">{count} ({pct:.0f}%)</span></div>\n'

    # 温度感
    temp_rows = ""
    temp_colors = {"Hot": "#c0392b", "Warm": "#e8a838", "Cold": "#3498db",
                   "不在のため不明": "#95a5a6", "不明": "#bdc3c7", "担当者不在": "#7f8c8d", "未設定": "#999"}
    for temp, count in temp_counts.most_common():
        pct = count / len(contacts) * 100
        color = temp_colors.get(temp, "#666")
        temp_rows += f'<div class="bar-row"><span class="bar-label">{temp}</span><div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div><span class="bar-value">{count}</span></div>\n'

    # 接触チャネル
    channel_rows = ""
    for ch, count in channel_counts.most_common():
        pct = count / len(contacts) * 100
        channel_rows += f'<div class="bar-row"><span class="bar-label">{ch}</span><div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:#e8a838"></div></div><span class="bar-value">{count}</span></div>\n'

    # safe get helper
    def sg(fields, key, default=0):
        v = fields.get(key)
        return v if v is not None else default

    # GA4トップページ
    pages_rows = ""
    for p in top_pages:
        f = p["fields"]
        path = str(sg(f, "ページパス", ""))[:50]
        pv = sg(f, "ページビュー", 0)
        users = sg(f, "ユーザー数", 0)
        bounce = sg(f, "直帰率", 0)
        if isinstance(bounce, (int, float)):
            bounce_str = f"{bounce:.0f}%" if bounce > 1 else f"{bounce*100:.0f}%"
        else:
            bounce_str = str(bounce)
        pv_n = pv if isinstance(pv, (int, float)) else 0
        users_n = users if isinstance(users, (int, float)) else 0
        pages_rows += f"<tr><td>{path}</td><td>{pv_n:,.0f}</td><td>{users_n:,.0f}</td><td>{bounce_str}</td></tr>\n"

    # GA4トレンド（Chart.js用データ）
    trend_labels = []
    trend_pv = []
    trend_users = []
    trend_sessions = []
    for t in trend_data:
        f = t["fields"]
        week = str(sg(f, "週", ""))[:10]
        trend_labels.append(f'"{week}"')
        trend_pv.append(str(sg(f, "ページビュー", 0) or 0))
        trend_users.append(str(sg(f, "ユーザー数", 0) or 0))
        trend_sessions.append(str(sg(f, "セッション", 0) or 0))

    # 流入経路
    source_rows = ""
    for s in top_sources:
        f = s["fields"]
        channel = str(sg(f, "チャネル", ""))
        source = str(sg(f, "ソース", ""))
        sessions = sg(f, "セッション", 0) or 0
        users = sg(f, "ユーザー数", 0) or 0
        sess_n = sessions if isinstance(sessions, (int, float)) else 0
        user_n = users if isinstance(users, (int, float)) else 0
        source_rows += f"<tr><td>{channel}</td><td>{source}</td><td>{sess_n:,.0f}</td><td>{user_n:,.0f}</td></tr>\n"

    # GSCクエリ
    query_rows = ""
    for q in top_queries:
        f = q["fields"]
        query = ""
        clicks = 0
        for k, v in f.items():
            if "クエリ" in k and isinstance(v, str):
                query = v[:40]
            if "クリック" in k and isinstance(v, (int, float)):
                clicks = int(v)
        if query:
            query_rows += f"<tr><td>{query}</td><td>{clicks:,}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TAS ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{--navy:#1a2a3a;--amber:#e8a838;--warm:#fdf8f0;--text:#333;--muted:#666;--red:#c0392b;--green:#27ae60}}
body{{font-family:-apple-system,'Noto Sans JP',sans-serif;background:#f0f2f5;color:var(--text);font-size:14px}}
.header{{background:var(--navy);color:#fff;padding:16px 24px;display:flex;justify-content:space-between;align-items:center}}
.header h1{{font-size:1.2rem;font-weight:700}}
.header .updated{{font-size:.8rem;color:#999}}
.container{{max-width:1200px;margin:0 auto;padding:16px}}
.section-title{{font-size:1rem;font-weight:700;color:var(--navy);margin:24px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--amber)}}
.section-title:first-child{{margin-top:0}}

/* KPI */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}}
.kpi-card{{background:#fff;border-radius:10px;padding:20px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.kpi-card.accent{{background:var(--navy);color:#fff}}
.kpi-card.accent .kpi-label{{color:var(--amber)}}
.kpi-value{{font-size:2rem;font-weight:900;line-height:1.2}}
.kpi-label{{font-size:.8rem;color:var(--muted);margin-top:4px}}

/* GRID */
.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.card{{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card h3{{font-size:.9rem;color:var(--navy);margin-bottom:12px}}

/* BAR CHART */
.bar-row{{display:flex;align-items:center;margin-bottom:6px;gap:8px}}
.bar-label{{width:80px;font-size:.8rem;color:var(--muted);text-align:right;flex-shrink:0}}
.bar-track{{flex:1;height:18px;background:#eee;border-radius:4px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:4px;transition:width .5s}}
.bar-value{{width:60px;font-size:.8rem;font-weight:600;flex-shrink:0}}

/* TABLE */
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th{{background:var(--navy);color:#fff;padding:8px 10px;text-align:left;font-weight:600;font-size:.8rem}}
td{{padding:6px 10px;border-bottom:1px solid #eee}}
tr:hover td{{background:var(--warm)}}

/* CHART */
.chart-container{{position:relative;height:250px}}

/* P&L */
.kpi-card.accent-green{{background:var(--green);color:#fff}}
.kpi-card.accent-green .kpi-label{{color:#c8f7c5}}
.kpi-card.accent-red{{background:var(--red);color:#fff}}
.kpi-card.accent-red .kpi-label{{color:#f5b7b1}}

@media(max-width:768px){{
  .grid-2{{grid-template-columns:1fr}}
  .kpi-grid{{grid-template-columns:repeat(2,1fr)}}
}}
</style>
</head>
<body>

<div class="header">
  <h1>TAS Dashboard</h1>
  <span class="updated">更新: {now}</span>
</div>

<div class="container">

  <!-- KPI -->
  {kpi_cards}

  <!-- P&L Section -->
  <h2 class="section-title">P&amp;L（損益計算書）</h2>
  <div class="card" style="margin-bottom:12px">
    <h3>売上・コスト・利益 月次推移</h3>
    <div class="chart-container" style="height:300px">
      <canvas id="plChart"></canvas>
    </div>
  </div>
  <div class="card" style="margin-bottom:12px">
    <h3>東海工測 vs 直取引 売上比率推移</h3>
    <div class="chart-container" style="height:250px">
      <canvas id="revenueBreakdownChart"></canvas>
    </div>
  </div>

  <!-- CRM Section -->
  <h2 class="section-title">CRM</h2>
  <div class="grid-2">
    <div class="card">
      <h3>商談ステージ（{len(deals)}件）</h3>
      {stage_rows}
    </div>
    <div class="card">
      <h3>温度感スコア（{len(contacts)}件）</h3>
      {temp_rows}
    </div>
  </div>
  <div class="grid-2" style="margin-top:12px">
    <div class="card">
      <h3>接触チャネル</h3>
      {channel_rows}
    </div>
    <div class="card">
      <h3>流入元</h3>
      {"".join(f'<div class="bar-row"><span class="bar-label">{src}</span><div class="bar-track"><div class="bar-fill" style="width:{cnt/len(contacts)*100}%;background:#3498db"></div></div><span class="bar-value">{cnt}</span></div>' for src, cnt in source_counts.most_common())}
    </div>
  </div>

  <!-- Web Section -->
  <h2 class="section-title">Web Analytics</h2>

  <!-- Trend Chart -->
  <div class="card" style="margin-bottom:12px">
    <h3>週次トレンド</h3>
    <div class="chart-container">
      <canvas id="trendChart"></canvas>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <h3>トップページ（PV順）</h3>
      <div style="max-height:400px;overflow-y:auto">
      <table>
        <thead><tr><th>ページ</th><th>PV</th><th>UU</th><th>直帰率</th></tr></thead>
        <tbody>{pages_rows}</tbody>
      </table>
      </div>
    </div>
    <div class="card">
      <h3>流入経路</h3>
      <table>
        <thead><tr><th>チャネル</th><th>ソース</th><th>セッション</th><th>UU</th></tr></thead>
        <tbody>{source_rows}</tbody>
      </table>
    </div>
  </div>

  <div class="card" style="margin-top:12px">
    <h3>検索クエリ（GSC クリック順）</h3>
    <div style="max-height:350px;overflow-y:auto">
    <table>
      <thead><tr><th>クエリ</th><th>クリック</th></tr></thead>
      <tbody>{query_rows}</tbody>
    </table>
    </div>
  </div>

</div>

<script>
// P&L Chart
(function() {{
  const plMonths = [{",".join(f'"{m}月"' for m in pl["months"])}];
  const plRevenue = [{",".join(str(v) for v in pl["revenue"])}];
  const plCost = [{",".join(str(v) for v in pl["cost"])}];
  const plOpProfit = [{",".join(str(v) for v in pl["operating_profit"])}];
  const plNetProfit = [{",".join(str(v) for v in pl["net_profit"])}];
  const tokaiRev = [{",".join(str(v) for v in pl["tokai_revenue"])}];
  const directRev = [{",".join(str(v) for v in pl["direct_revenue"])}];

  if (plMonths.length > 0) {{
    new Chart(document.getElementById('plChart'), {{
      type: 'bar',
      data: {{
        labels: plMonths,
        datasets: [
          {{label:'売上', data:plRevenue, backgroundColor:'rgba(52,152,219,.7)', order:2}},
          {{label:'コスト', data:plCost, backgroundColor:'rgba(231,76,60,.5)', order:3}},
          {{label:'営業利益', data:plOpProfit, type:'line', borderColor:'#e8a838', backgroundColor:'transparent', borderWidth:2, pointRadius:4, tension:.3, order:1}},
          {{label:'純利益', data:plNetProfit, type:'line', borderColor:'#27ae60', backgroundColor:'transparent', borderWidth:2, pointRadius:4, tension:.3, order:0}}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{position:'top', labels: {{font: {{size:11}}}}}},
          tooltip: {{callbacks: {{label: function(ctx) {{ return ctx.dataset.label + ': ¥' + ctx.parsed.y.toLocaleString(); }}}}}}
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            ticks: {{callback: function(v) {{ return '¥' + (v/10000).toFixed(0) + '万'; }}}}
          }}
        }}
      }}
    }});

    // Revenue breakdown chart
    new Chart(document.getElementById('revenueBreakdownChart'), {{
      type: 'bar',
      data: {{
        labels: plMonths,
        datasets: [
          {{label:'東海工測', data:tokaiRev, backgroundColor:'rgba(52,152,219,.7)'}},
          {{label:'直取引', data:directRev, backgroundColor:'rgba(232,168,56,.7)'}}
        ]
      }},
      options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
          legend: {{position:'top', labels: {{font: {{size:11}}}}}},
          tooltip: {{callbacks: {{label: function(ctx) {{ return ctx.dataset.label + ': ¥' + ctx.parsed.y.toLocaleString(); }}}}}}
        }},
        scales: {{
          x: {{stacked: true}},
          y: {{
            stacked: true,
            ticks: {{callback: function(v) {{ return '¥' + (v/10000).toFixed(0) + '万'; }}}}
          }}
        }}
      }}
    }});
  }}
}})();

// GA4 Trend Chart
new Chart(document.getElementById('trendChart'), {{
  type: 'line',
  data: {{
    labels: [{",".join(trend_labels)}],
    datasets: [
      {{label:'PV', data:[{",".join(trend_pv)}], borderColor:'#e8a838', backgroundColor:'rgba(232,168,56,.1)', fill:true, tension:.3}},
      {{label:'UU', data:[{",".join(trend_users)}], borderColor:'#3498db', backgroundColor:'rgba(52,152,219,.1)', fill:true, tension:.3}},
      {{label:'Session', data:[{",".join(trend_sessions)}], borderColor:'#27ae60', backgroundColor:'rgba(39,174,96,.1)', fill:true, tension:.3}}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{legend: {{position:'top', labels: {{font: {{size:11}}}}}}}},
    scales: {{y: {{beginAtZero:true}}}}
  }}
}});
</script>

</body>
</html>"""

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nダッシュボード生成完了: {OUTPUT_PATH}")


if __name__ == "__main__":
    generate_dashboard()
