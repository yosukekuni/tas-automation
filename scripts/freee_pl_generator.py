#!/usr/bin/env python3
"""
freee月次P&L（損益計算書）自動取得スクリプト

処理:
1. freee APIから会計年度情報を取得し、fiscal_yearとmonthを正しくマッピング
2. 月次試算表（PL）を取得（累計値→前月差分で月次値を算出）
3. 未入金請求書一覧を取得
4. JSON出力 + コンソールサマリー表示

Usage:
  python freee_pl_generator.py              # 直近12ヶ月
  python freee_pl_generator.py --months 6   # 直近6ヶ月
  python freee_pl_generator.py --all        # 全期間（全会計年度）
"""

import json
import shutil
import sys
import argparse
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date
from pathlib import Path
from calendar import monthrange

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

PL_OUTPUT = DATA_DIR / "freee_monthly_pl.json"
UNPAID_OUTPUT = DATA_DIR / "freee_unpaid_invoices.json"

FREEE_API_BASE = "https://api.freee.co.jp"
FREEE_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"


# ──────────────────────────────────────────────
# Config管理
# ──────────────────────────────────────────────
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    """automation_config.jsonを更新（バックアップ取ってから）"""
    backup = CONFIG_FILE.with_suffix(".json.bak")
    shutil.copy2(CONFIG_FILE, backup)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    print(f"  config更新済み（バックアップ: {backup.name}）")


# ──────────────────────────────────────────────
# freee API
# ──────────────────────────────────────────────
def refresh_token(config):
    """access_tokenをリフレッシュしてconfigを更新"""
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
        body = e.read().decode()
        print(f"[ERROR] トークンリフレッシュ失敗: {e.code} {body}")
        sys.exit(1)

    config["freee"]["access_token"] = result["access_token"]
    config["freee"]["refresh_token"] = result["refresh_token"]
    save_config(config)
    print("  access_tokenリフレッシュ完了")
    return config


def api_request(config, path, params=None, retry_auth=True):
    """freee APIリクエスト（401時は自動リフレッシュ再試行）"""
    freee = config["freee"]
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
            print("\n  401 Unauthorized → トークンリフレッシュ中...")
            config = refresh_token(config)
            return api_request(config, path, params, retry_auth=False)
        body = e.read().decode()
        raise FreeeAPIError(e.code, body, path)


class FreeeAPIError(Exception):
    def __init__(self, code, body, path):
        self.code = code
        self.body = body
        self.path = path
        super().__init__(f"API {path}: {code} {body}")


# ──────────────────────────────────────────────
# 会計年度ロジック
# ──────────────────────────────────────────────
def get_fiscal_years(config):
    """会社情報から全会計年度を取得して返す。
    Returns: list of dict with 'start_date', 'end_date', sorted by start_date
    """
    company_id = config["freee"]["company_id"]
    data, config = api_request(config, f"/api/1/companies/{company_id}")
    company = data.get("company", {})
    fiscal_years = company.get("fiscal_years", [])

    # start_dateでソート
    result = []
    for fy in fiscal_years:
        result.append({
            "id": fy["id"],
            "start_date": fy["start_date"],
            "end_date": fy["end_date"],
        })
    result.sort(key=lambda x: x["start_date"])
    return result, config


def calendar_month_to_fiscal(fiscal_years, cal_year, cal_month):
    """カレンダー年月(2025, 6) → (fiscal_year番号, month番号) に変換。
    freee APIのfiscal_yearは会計年度のstart_dateの年、
    monthは1〜12でstart_monthから数えた通し番号。

    Returns: (fiscal_year, api_month) or None if not in any fiscal year.
    """
    target = date(cal_year, cal_month, 1)

    for fy in fiscal_years:
        start = date.fromisoformat(fy["start_date"])
        end = date.fromisoformat(fy["end_date"])

        if start <= target <= end:
            # fiscal_yearパラメータ = start_dateの年
            fiscal_year_num = start.year

            # monthパラメータ = カレンダー月番号（freeeはそのまま月番号を使う）
            return fiscal_year_num, cal_month

    return None


def get_fiscal_year_months(fy):
    """会計年度dictからカレンダー月リスト [(year, month), ...] を返す"""
    start = date.fromisoformat(fy["start_date"])
    end = date.fromisoformat(fy["end_date"])
    months = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


# ──────────────────────────────────────────────
# データ取得
# ──────────────────────────────────────────────
def fetch_pl_cumulative(config, fiscal_year, start_month, end_month):
    """試算表PLの累計値を取得"""
    company_id = config["freee"]["company_id"]
    params = {
        "company_id": company_id,
        "fiscal_year": fiscal_year,
        "start_month": start_month,
        "end_month": end_month,
    }
    try:
        data, config = api_request(config, "/api/1/reports/trial_pl", params)
        return data, config
    except FreeeAPIError as e:
        if e.code == 400:
            return None, config
        raise


def extract_balances_map(pl_data):
    """trial_plレスポンスからバランスデータを抽出。
    Returns:
        categories: {(category_name, hierarchy): closing_balance}
        items: {account_item_name: {details...}}
    """
    if not pl_data:
        return {}, {}

    balances = pl_data.get("trial_pl", {}).get("balances", [])
    categories = {}  # (category_name, hierarchy) -> closing_balance
    items = {}       # account_item_name -> full item dict

    for item in balances:
        hierarchy = item.get("hierarchy_level", 0)
        category = item.get("account_category_name", "")
        item_name = item.get("account_item_name", "") or ""
        closing = item.get("closing_balance", 0) or 0

        # カテゴリ小計行（account_item_nameが空）
        if category and not item_name:
            categories[(category, hierarchy)] = closing

        # 勘定科目行
        if item_name:
            items[item_name] = {
                "account_item_name": item_name,
                "account_category_name": category,
                "hierarchy_level": hierarchy,
                "closing_balance": closing,
            }

    return categories, items


def compute_monthly_pl(config, fiscal_years, month_list):
    """月リストに対して月次P&Lを計算。
    freee trial_plは期首からの累計なので、前月累計との差分で月次値を算出。
    """
    monthly_data = []

    # 会計年度ごとにグループ化
    fy_groups = {}  # fiscal_year_num -> [(cal_year, cal_month), ...]
    for cal_year, cal_month in month_list:
        result = calendar_month_to_fiscal(fiscal_years, cal_year, cal_month)
        if result:
            fy_num, _ = result
            fy_groups.setdefault(fy_num, []).append((cal_year, cal_month))

    for fy_num in sorted(fy_groups.keys()):
        months_in_fy = fy_groups[fy_num]

        # この会計年度の月を期首から順にソート
        months_in_fy.sort()

        # 前月の累計を保持
        prev_categories = {}
        prev_details = {}

        # 該当会計年度の期首月を特定
        fy_info = None
        for fy in fiscal_years:
            start = date.fromisoformat(fy["start_date"])
            if start.year == fy_num:
                fy_info = fy
                break

        if not fy_info:
            continue

        fy_start = date.fromisoformat(fy_info["start_date"])
        fy_all_months = get_fiscal_year_months(fy_info)

        for cal_year, cal_month in fy_all_months:
            ym = f"{cal_year}/{cal_month:02d}"
            is_target = (cal_year, cal_month) in months_in_fy

            if is_target:
                print(f"  取得中: {ym}...", end="", flush=True)

            # 期首から当月までの累計を取得
            pl_data, config = fetch_pl_cumulative(config, fy_num, fy_start.month, cal_month)

            if not pl_data:
                if is_target:
                    print(" データなし")
                continue

            curr_categories, curr_details = extract_balances_map(pl_data)

            if is_target:
                # 月次値 = 当月累計 - 前月累計
                # freee PLカテゴリ構造:
                #   h=1: 売上高 / 売上総損益金額 / 営業損益金額 / 経常損益金額
                #        税引前当期純損益金額 / 当期純損益金額
                #   h=2: 売上高 / 売上原価 / 販売管理費 / 営業外収益 / 営業外費用
                #        特別利益 / 特別損失 / 法人税等

                # 売上: h=1の「売上高」
                revenue_cum = curr_categories.get(("売上高", 1), 0)
                revenue_prev = prev_categories.get(("売上高", 1), 0)

                # 費用: h=2の費用系カテゴリ合計
                expense_cats = ("売上原価", "販売管理費", "販売費及び一般管理費",
                                "営業外費用", "特別損失")
                expense_cum = sum(curr_categories.get((c, 2), 0) for c in expense_cats)
                expense_prev = sum(prev_categories.get((c, 2), 0) for c in expense_cats)

                revenue = revenue_cum - revenue_prev
                expense = expense_cum - expense_prev
                profit = revenue - expense

                # 科目別の月次値
                details = {}
                for item_name, curr in curr_details.items():
                    prev_closing = prev_details.get(item_name, {}).get("closing_balance", 0)
                    monthly_val = curr["closing_balance"] - prev_closing
                    if monthly_val != 0:
                        details[item_name] = {
                            "account_item_name": item_name,
                            "account_category_name": curr["account_category_name"],
                            "hierarchy_level": curr["hierarchy_level"],
                            "monthly_amount": monthly_val,
                            "cumulative": curr["closing_balance"],
                        }

                monthly_data.append({
                    "year_month": ym,
                    "year": cal_year,
                    "month": cal_month,
                    "revenue": revenue,
                    "expense": expense,
                    "profit": profit,
                    "details": details,
                })
                print(f" OK (売上: {format_yen(revenue)})")

            prev_categories = curr_categories
            prev_details = curr_details

    return monthly_data, config


def fetch_unpaid_invoices(config):
    """未入金請求書一覧を取得"""
    company_id = config["freee"]["company_id"]
    all_invoices = []
    offset = 0
    limit = 100

    while True:
        params = {
            "company_id": company_id,
            "payment_status": "unsettled",
            "limit": limit,
            "offset": offset,
        }
        try:
            data, config = api_request(config, "/api/1/invoices", params)
            invoices = data.get("invoices", [])
            all_invoices.extend(invoices)
            if len(invoices) < limit:
                break
            offset += limit
        except FreeeAPIError:
            break

    return all_invoices, config


# ──────────────────────────────────────────────
# 表示
# ──────────────────────────────────────────────
def format_yen(amount):
    """金額を日本円表示"""
    if amount is None:
        return "¥0"
    if amount < 0:
        return f"¥-{abs(amount):,.0f}"
    return f"¥{amount:,.0f}"


def print_monthly_summary(monthly_data):
    """月次サマリーをコンソール表示"""
    print("\n" + "=" * 70)
    print("  freee 月次損益計算書サマリー")
    print("=" * 70)

    if not monthly_data:
        print("  データなし")
        print("=" * 70)
        return

    total_revenue = 0
    total_expense = 0

    for entry in monthly_data:
        ym = entry["year_month"]
        rev = entry.get("revenue", 0)
        exp = entry.get("expense", 0)
        profit = entry.get("profit", 0)
        total_revenue += rev
        total_expense += exp

        status = "+" if profit >= 0 else "-"
        print(f"  {ym}  売上: {format_yen(rev):>14}  費用: {format_yen(exp):>14}  "
              f"利益: {format_yen(profit):>14}  {status}")

    print("-" * 70)
    total_profit = total_revenue - total_expense
    n = len(monthly_data)
    print(f"  合計      売上: {format_yen(total_revenue):>14}  費用: {format_yen(total_expense):>14}  "
          f"利益: {format_yen(total_profit):>14}")
    print(f"  月平均    売上: {format_yen(total_revenue/n):>14}  費用: {format_yen(total_expense/n):>14}  "
          f"利益: {format_yen(total_profit/n):>14}")
    print("=" * 70)


def print_unpaid_summary(invoices):
    """未入金請求書サマリー"""
    if not invoices:
        print("\n  未入金請求書: なし")
        return

    print(f"\n  未入金請求書: {len(invoices)}件")
    print("-" * 60)
    total = 0
    for inv in invoices:
        partner = inv.get("partner_name", "不明")
        amount = inv.get("total_amount", 0)
        due = inv.get("due_date", "未設定")
        number = inv.get("invoice_number", "")
        total += amount
        print(f"  {number:>10}  {partner:<20}  {format_yen(amount):>12}  期限: {due}")
    print("-" * 60)
    print(f"  未入金合計: {format_yen(total)}")


# ──────────────────────────────────────────────
# 月リスト生成
# ──────────────────────────────────────────────
def generate_month_list(months=12):
    """直近Nヶ月のリスト[(year, month), ...]を返す"""
    today = date.today()
    result = []
    y, m = today.year, today.month
    for _ in range(months):
        result.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    result.reverse()
    return result


def generate_all_months(fiscal_years):
    """全会計年度の全月を返す"""
    result = []
    for fy in fiscal_years:
        months = get_fiscal_year_months(fy)
        result.extend(months)
    # 重複排除・ソート
    return sorted(set(result))


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="freee月次P&L取得")
    parser.add_argument("--months", type=int, default=12, help="取得月数（デフォルト: 12）")
    parser.add_argument("--all", action="store_true", help="全期間取得（全会計年度）")
    args = parser.parse_args()

    # Config読み込み・バリデーション
    config = load_config()
    if "freee" not in config:
        print("[ERROR] automation_config.jsonにfreeeキーがありません")
        sys.exit(1)

    required_keys = ["client_id", "client_secret", "access_token", "refresh_token", "company_id"]
    missing = [k for k in required_keys if k not in config["freee"]]
    if missing:
        print(f"[ERROR] freee設定に不足: {', '.join(missing)}")
        sys.exit(1)

    print(f"freee P&L取得開始 (company_id: {config['freee']['company_id']})")

    # 会計年度情報を取得
    print("  会計年度情報取得中...", end="", flush=True)
    fiscal_years, config = get_fiscal_years(config)
    print(f" {len(fiscal_years)}期")
    for fy in fiscal_years:
        print(f"    {fy['start_date']} 〜 {fy['end_date']}")

    # 月リスト生成
    if args.all:
        month_list = generate_all_months(fiscal_years)
        if month_list:
            print(f"  全期間モード: {month_list[0][0]}/{month_list[0][1]:02d} 〜 "
                  f"{month_list[-1][0]}/{month_list[-1][1]:02d} ({len(month_list)}ヶ月)")
        else:
            print("  [ERROR] 会計年度データがありません")
            sys.exit(1)
    else:
        month_list = generate_month_list(args.months)
        # 会計年度に含まれる月だけにフィルタ
        valid_months = []
        for y, m in month_list:
            if calendar_month_to_fiscal(fiscal_years, y, m):
                valid_months.append((y, m))
        if not valid_months:
            print(f"  直近{args.months}ヶ月に該当する会計年度がありません。--all で全期間を試してください。")
            # 全期間にフォールバック
            valid_months = generate_all_months(fiscal_years)
            if not valid_months:
                print("  [ERROR] 取得可能なデータがありません")
                sys.exit(1)
            print(f"  フォールバック: 全期間 ({len(valid_months)}ヶ月)")
        month_list = valid_months
        print(f"  対象期間: {month_list[0][0]}/{month_list[0][1]:02d} 〜 "
              f"{month_list[-1][0]}/{month_list[-1][1]:02d}")

    # 月次P&L取得（累計差分方式）
    monthly_data, config = compute_monthly_pl(config, fiscal_years, month_list)

    # 未入金請求書取得
    print("  未入金請求書取得中...", end="", flush=True)
    unpaid_invoices, config = fetch_unpaid_invoices(config)
    print(f" {len(unpaid_invoices)}件")

    # JSON出力: P&L
    pl_output = {
        "generated_at": datetime.now().isoformat(),
        "company_id": config["freee"]["company_id"],
        "period": (f"{month_list[0][0]}/{month_list[0][1]:02d} - "
                   f"{month_list[-1][0]}/{month_list[-1][1]:02d}"),
        "note": "月次値は期首からの累計差分で算出",
        "monthly": monthly_data,
        "summary": {
            "total_revenue": sum(m["revenue"] for m in monthly_data),
            "total_expense": sum(m["expense"] for m in monthly_data),
            "total_profit": sum(m["profit"] for m in monthly_data),
            "months_count": len(monthly_data),
            "avg_revenue": (sum(m["revenue"] for m in monthly_data)
                            / max(len(monthly_data), 1)),
            "avg_expense": (sum(m["expense"] for m in monthly_data)
                            / max(len(monthly_data), 1)),
            "avg_profit": (sum(m["profit"] for m in monthly_data)
                           / max(len(monthly_data), 1)),
        },
    }

    with open(PL_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(pl_output, f, indent=2, ensure_ascii=False)
    print(f"\n  P&L出力: {PL_OUTPUT}")

    # JSON出力: 未入金請求書
    unpaid_output = {
        "generated_at": datetime.now().isoformat(),
        "company_id": config["freee"]["company_id"],
        "count": len(unpaid_invoices),
        "total_amount": sum(inv.get("total_amount", 0) for inv in unpaid_invoices),
        "invoices": [
            {
                "invoice_number": inv.get("invoice_number", ""),
                "partner_name": inv.get("partner_name", ""),
                "total_amount": inv.get("total_amount", 0),
                "due_date": inv.get("due_date", ""),
                "issue_date": inv.get("issue_date", ""),
                "invoice_status": inv.get("invoice_status", ""),
                "payment_status": inv.get("payment_status", ""),
            }
            for inv in unpaid_invoices
        ],
    }

    with open(UNPAID_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(unpaid_output, f, indent=2, ensure_ascii=False)
    print(f"  未入金出力: {UNPAID_OUTPUT}")

    # コンソールサマリー
    print_monthly_summary(monthly_data)
    print_unpaid_summary(unpaid_invoices)

    print(f"\n完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
