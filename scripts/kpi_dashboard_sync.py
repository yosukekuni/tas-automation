#!/usr/bin/env python3
"""
OKR/KPI/P&L ダッシュボードデータ同期スクリプト

全データソースからKPIを集約し、Lark Base「KPIダッシュボード」テーブルに投入する。
毎日1回（朝9時）GitHub Actions で実行。

データソース:
  1. freee API → 月次P&L（売上/粗利/営業利益）
  2. Lark CRM Base → 商談数/受注率/平均単価/パイプライン
  3. GA4（Lark Web分析Base経由） → PV/UU/CVR/問い合わせ数
  4. 受注台帳 → 月次受注実績

出力先:
  - Lark Base: KPIダッシュボードテーブル（月次レコード）
  - JSON: scripts/data/kpi_dashboard_latest.json
  - Lark Webhook: サマリー通知

Usage:
  python3 kpi_dashboard_sync.py                  # 全KPI同期
  python3 kpi_dashboard_sync.py --dry-run        # 計算のみ（書き込みなし）
  python3 kpi_dashboard_sync.py --month 2026-03  # 特定月のみ
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config
from lib.lark_api import (
    lark_get_token, lark_list_records, lark_create_record,
    lark_update_record, send_lark_webhook,
)

# ── Constants ──
FIXED_COST_MONTHLY = 693369  # 固定費/月

# CRM Base テーブルID
DEAL_TABLE = "tbl1rM86nAw9l3bP"       # 商談
ORDER_TABLE = "tbldLj2iMJYocct6"      # 受注台帳
ACCOUNT_TABLE = "tblTfGScQIdLTYxA"    # 取引先
CONTACT_TABLE = "tblN53hFIQoo4W8j"    # 連絡先

# Web分析Base
WEB_BASE_TOKEN = "Vy65bp8Wia7UkZs8CWCjPSqJpyf"
GA4_TREND_TABLE = "tblYHA6j48u7TiZj"  # 週次トレンド

# タスク管理Base（KPIダッシュボード出力先）
TASK_BASE_TOKEN = "HSSMb3T2jalcuysFCjGjJ76wpKe"

# freee API
FREEE_API_BASE = "https://api.freee.co.jp"
FREEE_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"

# 出力
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_JSON = DATA_DIR / "kpi_dashboard_latest.json"


# ──────────────────────────────────────────────
# freee P&L取得（freee_pl_generator.pyから最小限を抽出）
# ──────────────────────────────────────────────
def freee_refresh_token(config):
    """freee access_tokenリフレッシュ"""
    freee = config["freee"]
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": freee["client_id"],
        "client_secret": freee["client_secret"],
        "refresh_token": freee["refresh_token"],
        "redirect_uri": freee["redirect_uri"],
    }).encode()
    req = urllib.request.Request(FREEE_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] freeeトークンリフレッシュ失敗: {e.code}")
        return config
    config["freee"]["access_token"] = result["access_token"]
    config["freee"]["refresh_token"] = result["refresh_token"]
    # configファイルを更新
    config_path = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
    if config_path.exists():
        import shutil
        shutil.copy2(config_path, config_path.with_suffix(".json.bak"))
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    return config


def freee_api(config, path, params=None, retry_auth=True):
    """freee APIリクエスト"""
    freee = config.get("freee", {})
    if not freee.get("access_token"):
        return None, config
    url = f"{FREEE_API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {freee['access_token']}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), config
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry_auth:
            config = freee_refresh_token(config)
            return freee_api(config, path, params, retry_auth=False)
        print(f"[WARN] freee API {path}: {e.code}")
        return None, config


def fetch_freee_pl_months(config, target_months):
    """指定月のP&Lデータを取得。
    target_months: [(year, month), ...]
    Returns: {year_month_str: {revenue, expense, profit, details}}
    """
    freee = config.get("freee", {})
    company_id = freee.get("company_id")
    if not company_id:
        print("  [SKIP] freee未設定")
        return {}, config

    # company_idは文字列の場合もある
    company_id = int(company_id) if company_id else 0
    if not company_id:
        print("  [SKIP] freee company_id未設定")
        return {}, config

    # 会計年度取得
    data, config = freee_api(config, f"/api/1/companies/{company_id}")
    if not data:
        print("  [WARN] freee会社情報取得失敗")
        return {}, config

    fiscal_years = data.get("company", {}).get("fiscal_years", [])
    fiscal_years.sort(key=lambda x: x["start_date"])

    result = {}

    for cal_year, cal_month in target_months:
        ym = f"{cal_year}/{cal_month:02d}"
        target_date = date(cal_year, cal_month, 1)

        # 該当する会計年度を探す
        fy_num = None
        fy_start_month = None
        for fy in fiscal_years:
            start = date.fromisoformat(fy["start_date"])
            end = date.fromisoformat(fy["end_date"])
            if start <= target_date <= end:
                fy_num = start.year
                fy_start_month = start.month
                break

        if fy_num is None:
            continue

        # 当月までの累計
        params_curr = {
            "company_id": company_id,
            "fiscal_year": fy_num,
            "start_month": fy_start_month,
            "end_month": cal_month,
        }
        curr_data, config = freee_api(config, "/api/1/reports/trial_pl", params_curr)

        # 前月までの累計（期首月なら不要）
        prev_data = None
        if cal_month != fy_start_month:
            prev_month = cal_month - 1 if cal_month > 1 else 12
            params_prev = {
                "company_id": company_id,
                "fiscal_year": fy_num,
                "start_month": fy_start_month,
                "end_month": prev_month,
            }
            prev_data, config = freee_api(config, "/api/1/reports/trial_pl", params_prev)

        if not curr_data:
            continue

        # 累計値からカテゴリ別合計を抽出
        def extract_totals(pl_data):
            if not pl_data:
                return {}
            balances = pl_data.get("trial_pl", {}).get("balances", [])
            cats = {}
            for item in balances:
                cat = item.get("account_category_name", "")
                h = item.get("hierarchy_level", 0)
                name = item.get("account_item_name", "") or ""
                closing = item.get("closing_balance", 0) or 0
                if cat and not name:
                    cats[(cat, h)] = closing
            return cats

        curr_cats = extract_totals(curr_data)
        prev_cats = extract_totals(prev_data) if prev_data else {}

        revenue_cum = curr_cats.get(("売上高", 1), 0)
        revenue_prev = prev_cats.get(("売上高", 1), 0)

        expense_categories = ("売上原価", "販売管理費", "販売費及び一般管理費",
                              "営業外費用", "特別損失")
        expense_cum = sum(curr_cats.get((c, 2), 0) for c in expense_categories)
        expense_prev = sum(prev_cats.get((c, 2), 0) for c in expense_categories)

        # 粗利（売上高 - 売上原価）
        cogs_cum = curr_cats.get(("売上原価", 2), 0)
        cogs_prev = prev_cats.get(("売上原価", 2), 0)

        # 営業利益（売上総利益 - 販管費）
        sga_cum = curr_cats.get(("販売管理費", 2), 0) or curr_cats.get(("販売費及び一般管理費", 2), 0)
        sga_prev = prev_cats.get(("販売管理費", 2), 0) or prev_cats.get(("販売費及び一般管理費", 2), 0)

        revenue = revenue_cum - revenue_prev
        cogs = cogs_cum - cogs_prev
        gross_profit = revenue - cogs
        sga = sga_cum - sga_prev
        operating_profit = gross_profit - sga
        expense = expense_cum - expense_prev
        net_profit = revenue - expense

        result[ym] = {
            "revenue": revenue,
            "cogs": cogs,
            "gross_profit": gross_profit,
            "sga": sga,
            "operating_profit": operating_profit,
            "expense": expense,
            "net_profit": net_profit,
        }
        print(f"  P&L {ym}: 売上={format_yen(revenue)} 営業利益={format_yen(operating_profit)}")
        time.sleep(0.5)

    return result, config


# ──────────────────────────────────────────────
# CRM KPI集計
# ──────────────────────────────────────────────
def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", item.get("text_value", item.get("name", str(item)))))
            else:
                parts.append(str(item))
        return " ".join(parts)
    if isinstance(value, dict):
        return value.get("text", value.get("text_value", value.get("name", str(value))))
    return str(value) if value else ""


def extract_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("\\", "").strip())
        except (ValueError, AttributeError):
            return 0
    return 0


def extract_timestamp_month(value):
    """Larkフィールドから年月文字列を返す"""
    if isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(value / 1000)
            return f"{dt.year}/{dt.month:02d}"
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        for fmt in ["%Y-%m-%d", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(value, fmt)
                return f"{dt.year}/{dt.month:02d}"
            except ValueError:
                continue
    return None


def compute_crm_kpi(deals, orders, target_months_str):
    """月別CRM KPIを計算。
    Returns: {year_month: {deal_count, won_count, lost_count, win_rate, avg_deal_size, pipeline_amount}}
    """
    monthly = defaultdict(lambda: {
        "deal_count": 0,
        "won_count": 0,
        "lost_count": 0,
        "pipeline_amount": 0,
        "won_amount": 0,
        "hot_count": 0,
        "warm_count": 0,
    })

    for deal in deals:
        f = deal.get("fields", {})

        # 商談日から月を取得
        deal_date = f.get("商談日")
        ym = extract_timestamp_month(deal_date)
        if not ym or ym not in target_months_str:
            continue

        m = monthly[ym]
        m["deal_count"] += 1

        stage = extract_text(f.get("商談ステージ", ""))
        if stage == "受注":
            m["won_count"] += 1
        elif stage == "失注":
            m["lost_count"] += 1

        amount = extract_number(f.get("商談金額", 0)) or extract_number(f.get("見積・予算金額", 0))
        m["pipeline_amount"] += amount
        if stage == "受注":
            m["won_amount"] += amount

        temp = extract_text(f.get("温度感スコア", "")).lower()
        if "hot" in temp:
            m["hot_count"] += 1
        elif "warm" in temp:
            m["warm_count"] += 1

    # 受注台帳からも金額集計
    order_monthly = defaultdict(lambda: {"order_count": 0, "order_amount": 0})
    for order in orders:
        f = order.get("fields", {})
        # 受注日
        order_date = f.get("受注日") or f.get("作成日時")
        ym = extract_timestamp_month(order_date)
        if not ym or ym not in target_months_str:
            continue
        amount = extract_number(f.get("受注金額", 0)) or extract_number(f.get("金額", 0))
        order_monthly[ym]["order_count"] += 1
        order_monthly[ym]["order_amount"] += amount

    # マージ
    for ym in target_months_str:
        m = monthly[ym]
        o = order_monthly.get(ym, {})
        closed = m["won_count"] + m["lost_count"]
        m["win_rate"] = round(m["won_count"] / closed * 100, 1) if closed > 0 else 0
        m["avg_deal_size"] = round(m["pipeline_amount"] / m["deal_count"]) if m["deal_count"] > 0 else 0
        m["order_count"] = o.get("order_count", 0)
        m["order_amount"] = o.get("order_amount", 0)

    return dict(monthly)


# ──────────────────────────────────────────────
# Web KPI集計
# ──────────────────────────────────────────────
def compute_web_kpi(token, cfg, target_months_str):
    """Web分析BaseからGA4データを集計"""
    web_kpi = {}

    try:
        trend_records = lark_list_records(
            token, GA4_TREND_TABLE,
            base_token=WEB_BASE_TOKEN,
        )
    except Exception as e:
        print(f"  [WARN] Web分析データ取得失敗: {e}")
        return web_kpi

    # 週次データを月次に集約
    monthly_web = defaultdict(lambda: {
        "pageviews": 0,
        "users": 0,
        "sessions": 0,
        "inquiries": 0,
    })

    for rec in trend_records:
        f = rec.get("fields", {})
        week = extract_text(f.get("週", ""))
        if not week:
            continue

        # 週の日付から月を推定（YYYY-MM-DD形式想定）
        try:
            week_date = datetime.strptime(week[:10], "%Y-%m-%d")
            ym = f"{week_date.year}/{week_date.month:02d}"
        except (ValueError, IndexError):
            continue

        if ym not in target_months_str:
            continue

        m = monthly_web[ym]
        m["pageviews"] += extract_number(f.get("ページビュー", 0))
        m["users"] += extract_number(f.get("ユーザー数", 0))
        m["sessions"] += extract_number(f.get("セッション", 0))

    web_kpi = dict(monthly_web)
    return web_kpi


# ──────────────────────────────────────────────
# Lark Base書き込み
# ──────────────────────────────────────────────
def find_or_create_dashboard_table(token, cfg):
    """KPIダッシュボードテーブルを探す/作成する。
    タスク管理Base内に「KPIダッシュボード」テーブルを配置。

    Lark Bitable API でテーブル一覧を取得し、
    存在しなければ作成する。
    """
    # テーブル一覧取得
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE_TOKEN}/tables"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
    except Exception as e:
        print(f"  [ERROR] テーブル一覧取得失敗: {e}")
        return None

    tables = result.get("data", {}).get("items", [])
    for t in tables:
        if t.get("name") == "KPIダッシュボード":
            print(f"  KPIダッシュボードテーブル発見: {t['table_id']}")
            return t["table_id"]

    # テーブル作成
    print("  KPIダッシュボードテーブル作成中...")
    create_data = json.dumps({
        "table": {
            "name": "KPIダッシュボード",
            "fields": [
                {"field_name": "年月", "type": 1},           # テキスト
                {"field_name": "売上", "type": 2},           # 数値
                {"field_name": "売上原価", "type": 2},
                {"field_name": "粗利", "type": 2},
                {"field_name": "販管費", "type": 2},
                {"field_name": "営業利益", "type": 2},
                {"field_name": "純利益", "type": 2},
                {"field_name": "固定費カバー率", "type": 2},  # %
                {"field_name": "商談数", "type": 2},
                {"field_name": "受注数", "type": 2},
                {"field_name": "失注数", "type": 2},
                {"field_name": "受注率", "type": 2},          # %
                {"field_name": "受注金額", "type": 2},
                {"field_name": "平均商談単価", "type": 2},
                {"field_name": "Hot案件数", "type": 2},
                {"field_name": "Warm案件数", "type": 2},
                {"field_name": "PV", "type": 2},
                {"field_name": "UU", "type": 2},
                {"field_name": "セッション", "type": 2},
                {"field_name": "問い合わせ数", "type": 2},
                {"field_name": "CVR", "type": 2},             # %
                {"field_name": "更新日時", "type": 5},         # 日付
            ],
        }
    }).encode()

    req = urllib.request.Request(
        url, data=create_data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            table_id = result.get("data", {}).get("table_id")
            if table_id:
                print(f"  テーブル作成完了: {table_id}")
                return table_id
            else:
                print(f"  テーブル作成失敗: {result.get('msg', 'unknown')}")
                return None
    except Exception as e:
        print(f"  [ERROR] テーブル作成失敗: {e}")
        return None


def sync_to_lark_base(token, table_id, kpi_data, dry_run=False):
    """KPIデータをLark Baseに同期（upsert）"""
    if dry_run:
        print("\n[DRY-RUN] Lark Base書き込みスキップ")
        return

    # 既存レコードを取得（年月でマッチング）
    existing = lark_list_records(
        token, table_id,
        base_token=TASK_BASE_TOKEN,
    )
    existing_map = {}  # year_month -> record_id
    for rec in existing:
        ym = extract_text(rec.get("fields", {}).get("年月", ""))
        if ym:
            existing_map[ym] = rec.get("record_id")

    now_ms = int(datetime.now().timestamp() * 1000)

    for ym, data in sorted(kpi_data.items()):
        fields = {
            "年月": ym,
            "売上": data.get("revenue", 0),
            "売上原価": data.get("cogs", 0),
            "粗利": data.get("gross_profit", 0),
            "販管費": data.get("sga", 0),
            "営業利益": data.get("operating_profit", 0),
            "純利益": data.get("net_profit", 0),
            "固定費カバー率": data.get("fixed_cost_coverage", 0),
            "商談数": data.get("deal_count", 0),
            "受注数": data.get("won_count", 0) or data.get("order_count", 0),
            "失注数": data.get("lost_count", 0),
            "受注率": data.get("win_rate", 0),
            "受注金額": data.get("won_amount", 0) or data.get("order_amount", 0),
            "平均商談単価": data.get("avg_deal_size", 0),
            "Hot案件数": data.get("hot_count", 0),
            "Warm案件数": data.get("warm_count", 0),
            "PV": data.get("pageviews", 0),
            "UU": data.get("users", 0),
            "セッション": data.get("sessions", 0),
            "問い合わせ数": data.get("inquiries", 0),
            "CVR": data.get("cvr", 0),
            "更新日時": now_ms,
        }

        record_id = existing_map.get(ym)
        try:
            if record_id:
                lark_update_record(token, table_id, record_id, fields,
                                   base_token=TASK_BASE_TOKEN)
                print(f"  更新: {ym}")
            else:
                lark_create_record(token, table_id, fields,
                                   base_token=TASK_BASE_TOKEN)
                print(f"  新規: {ym}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [ERROR] {ym} 書き込み失敗: {e}")


# ──────────────────────────────────────────────
# サマリー通知
# ──────────────────────────────────────────────
def format_yen(amount):
    if amount is None:
        return "\\0"
    if amount < 0:
        return f"\\-{abs(amount):,.0f}"
    return f"\\{amount:,.0f}"


def generate_summary_text(kpi_data, current_month):
    """Webhook通知用サマリーテキスト生成"""
    d = kpi_data.get(current_month, {})

    revenue = d.get("revenue", 0)
    operating_profit = d.get("operating_profit", 0)
    coverage = d.get("fixed_cost_coverage", 0)
    deal_count = d.get("deal_count", 0)
    won_count = d.get("won_count", 0) or d.get("order_count", 0)
    win_rate = d.get("win_rate", 0)
    pv = d.get("pageviews", 0)
    users = d.get("users", 0)

    # ランウェイ計算（概算）
    if operating_profit > 0:
        runway_note = "黒字月"
    else:
        runway_note = f"固定費カバー率 {coverage:.0f}%"

    lines = [
        f"KPIダッシュボード更新 ({current_month})",
        f"更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "[P&L]",
        f"  売上: {format_yen(revenue)}",
        f"  営業利益: {format_yen(operating_profit)}",
        f"  {runway_note}",
        "",
        "[営業]",
        f"  商談数: {deal_count}件",
        f"  受注: {won_count}件 (受注率{win_rate:.1f}%)",
        "",
        "[Web]",
        f"  PV: {pv:,.0f} / UU: {users:,.0f}",
        "",
        f"固定費 {format_yen(FIXED_COST_MONTHLY)}/月 に対するカバー率: {coverage:.0f}%",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────
def main():
    dry_run = "--dry-run" in sys.argv
    target_month_arg = None
    if "--month" in sys.argv:
        idx = sys.argv.index("--month")
        if idx + 1 < len(sys.argv):
            target_month_arg = sys.argv[idx + 1]

    print(f"KPIダッシュボード同期開始 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    if dry_run:
        print("[DRY-RUN モード]")

    cfg = load_config()
    token = lark_get_token(cfg)

    # 対象月リスト（直近6ヶ月）
    today = date.today()
    if target_month_arg:
        try:
            parts = target_month_arg.split("-")
            target_months = [(int(parts[0]), int(parts[1]))]
        except (ValueError, IndexError):
            print(f"[ERROR] 月指定が不正: {target_month_arg} (YYYY-MM形式)")
            sys.exit(1)
    else:
        target_months = []
        y, m = today.year, today.month
        for _ in range(6):
            target_months.append((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1
        target_months.reverse()

    target_months_str = [f"{y}/{m:02d}" for y, m in target_months]
    current_month = f"{today.year}/{today.month:02d}"
    print(f"  対象月: {target_months_str[0]} ~ {target_months_str[-1]}")

    # ── Step 1: freee P&L ──
    print("\n[Step 1] freee P&L取得...")
    has_freee = "freee" in cfg and cfg["freee"].get("company_id")
    pl_data = {}
    if has_freee:
        try:
            pl_data, cfg = fetch_freee_pl_months(cfg, target_months)
        except Exception as e:
            print(f"  [ERROR] freee P&L取得失敗: {e}")
    else:
        print("  [SKIP] freee未設定 → JSONキャッシュを使用")
        # JSONキャッシュからフォールバック
        pl_json = DATA_DIR / "freee_monthly_pl.json"
        if pl_json.exists():
            cached = json.loads(pl_json.read_text())
            for entry in cached.get("monthly", []):
                ym = entry.get("year_month", "")
                if ym in target_months_str:
                    pl_data[ym] = {
                        "revenue": entry.get("revenue", 0),
                        "cogs": 0,
                        "gross_profit": entry.get("revenue", 0),
                        "sga": entry.get("expense", 0),
                        "operating_profit": entry.get("profit", 0),
                        "expense": entry.get("expense", 0),
                        "net_profit": entry.get("profit", 0),
                    }
            print(f"  キャッシュから{len(pl_data)}ヶ月分取得")

    # ── Step 2: CRM KPI ──
    print("\n[Step 2] CRM KPI集計...")
    try:
        deals = lark_list_records(token, DEAL_TABLE, cfg=cfg)
        orders = lark_list_records(token, ORDER_TABLE, cfg=cfg)
        print(f"  商談: {len(deals)}件 / 受注台帳: {len(orders)}件")
        crm_kpi = compute_crm_kpi(deals, orders, target_months_str)
    except Exception as e:
        print(f"  [ERROR] CRM KPI取得失敗: {e}")
        crm_kpi = {}

    # ── Step 3: Web KPI ──
    print("\n[Step 3] Web KPI集計...")
    try:
        web_kpi = compute_web_kpi(token, cfg, target_months_str)
        print(f"  Web KPI: {len(web_kpi)}ヶ月分")
    except Exception as e:
        print(f"  [ERROR] Web KPI取得失敗: {e}")
        web_kpi = {}

    # ── Step 4: 統合 ──
    print("\n[Step 4] KPIデータ統合...")
    kpi_data = {}
    for ym in target_months_str:
        pl = pl_data.get(ym, {})
        crm = crm_kpi.get(ym, {})
        web = web_kpi.get(ym, {})

        revenue = pl.get("revenue", 0)
        coverage = (revenue / FIXED_COST_MONTHLY * 100) if FIXED_COST_MONTHLY > 0 else 0

        sessions = web.get("sessions", 0)
        inquiries = web.get("inquiries", 0)
        cvr = (inquiries / sessions * 100) if sessions > 0 else 0

        kpi_data[ym] = {
            # P&L
            "revenue": revenue,
            "cogs": pl.get("cogs", 0),
            "gross_profit": pl.get("gross_profit", 0),
            "sga": pl.get("sga", 0),
            "operating_profit": pl.get("operating_profit", 0),
            "net_profit": pl.get("net_profit", 0),
            "fixed_cost_coverage": round(coverage, 1),
            # CRM
            "deal_count": crm.get("deal_count", 0),
            "won_count": crm.get("won_count", 0),
            "lost_count": crm.get("lost_count", 0),
            "win_rate": crm.get("win_rate", 0),
            "won_amount": crm.get("won_amount", 0),
            "order_count": crm.get("order_count", 0),
            "order_amount": crm.get("order_amount", 0),
            "avg_deal_size": crm.get("avg_deal_size", 0),
            "hot_count": crm.get("hot_count", 0),
            "warm_count": crm.get("warm_count", 0),
            # Web
            "pageviews": web.get("pageviews", 0),
            "users": web.get("users", 0),
            "sessions": sessions,
            "inquiries": inquiries,
            "cvr": round(cvr, 2),
        }

    # ── Step 5: コンソール出力 ──
    print("\n" + "=" * 80)
    print("  KPI ダッシュボード サマリー")
    print("=" * 80)
    print(f"{'月':>10} {'売上':>14} {'営業利益':>14} {'カバー率':>8} {'商談':>5} {'受注':>5} {'受注率':>7} {'PV':>8} {'UU':>8}")
    print("-" * 80)
    for ym in target_months_str:
        d = kpi_data.get(ym, {})
        print(f"{ym:>10} {format_yen(d.get('revenue', 0)):>14} "
              f"{format_yen(d.get('operating_profit', 0)):>14} "
              f"{d.get('fixed_cost_coverage', 0):>7.0f}% "
              f"{d.get('deal_count', 0):>5} "
              f"{d.get('won_count', 0) or d.get('order_count', 0):>5} "
              f"{d.get('win_rate', 0):>6.1f}% "
              f"{d.get('pageviews', 0):>8,.0f} "
              f"{d.get('users', 0):>8,.0f}")
    print("=" * 80)
    print(f"  固定費/月: {format_yen(FIXED_COST_MONTHLY)}")

    # ── Step 6: JSON出力 ──
    output = {
        "generated_at": datetime.now().isoformat(),
        "fixed_cost_monthly": FIXED_COST_MONTHLY,
        "target_months": target_months_str,
        "kpi": kpi_data,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  JSON出力: {OUTPUT_JSON}")

    # ── Step 7: Lark Base同期 ──
    print("\n[Step 7] Lark Base同期...")
    try:
        table_id = find_or_create_dashboard_table(token, cfg)
        if table_id:
            sync_to_lark_base(token, table_id, kpi_data, dry_run=dry_run)
        else:
            print("  [WARN] テーブルID取得失敗、スキップ")
    except Exception as e:
        print(f"  [ERROR] Lark Base同期失敗: {e}")

    # ── Step 8: Webhook通知 ──
    if not dry_run:
        print("\n[Step 8] サマリー通知...")
        summary = generate_summary_text(kpi_data, current_month)
        try:
            sent = send_lark_webhook(cfg, summary)
            if sent:
                print("  Webhook送信完了")
        except Exception as e:
            print(f"  [WARN] Webhook送信失敗: {e}")

    print(f"\n完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
