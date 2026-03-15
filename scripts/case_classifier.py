#!/usr/bin/env python3
"""
受注台帳 業種別×サービス別 分類スクリプト

受注台帳185件を業種カテゴリ・サービスカテゴリに分類し、
クロス集計レポートを出力する。

業種カテゴリ:
  ゼネコン / 建設コンサルタント / 測量会社 / 不動産 / 官公庁 / その他

サービスカテゴリ:
  ドローン測量 / 現場空撮 / 眺望撮影 / 点検 / その他

Usage:
  python3 case_classifier.py --dry-run     # 分析+レポート出力のみ（書き込みなし）
  python3 case_classifier.py               # 分類実行 + 受注台帳フィールド更新
  python3 case_classifier.py --verbose     # 詳細ログ付き

出力:
  - コンソールにクロス集計表
  - data/case_classification.json に分類結果JSON
  - 受注台帳の「業種」「サービス種別」フィールドを更新（dry-run以外）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── 設定 ──
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

_LOCAL_CONFIG = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
_SCRIPT_CONFIG = SCRIPT_DIR / "automation_config.json"
CONFIG_FILE = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _SCRIPT_CONFIG

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = os.environ.get("LARK_APP_ID") or CONFIG["lark"]["app_id"]
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET") or CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = os.environ.get("CRM_BASE_TOKEN") or CONFIG["lark"]["crm_base_token"]

# テーブルID
TABLE_ORDERS = "tbldLj2iMJYocct6"   # 受注台帳
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"  # 取引先

# ── 分類定義 ──
# 業種カテゴリ（受注台帳の既存値 → 統一カテゴリ）
INDUSTRY_CATEGORY_MAP = {
    "ゼネコン": "ゼネコン",
    "コンサルタント": "建設コンサルタント",
    "建設コンサルタント": "建設コンサルタント",
    "測量会社": "測量会社",
    "不動産": "不動産",
    "官公庁": "官公庁",
    "メーカー": "その他",
    "その他": "その他",
}

# 取引先名のキーワード → 業種カテゴリ推定
INDUSTRY_KEYWORDS = [
    # ゼネコン・建設会社
    (["建設", "組", "工業", "工務", "土木", "ハウス", "住宅", "鹿島", "大林", "清水",
      "大成", "竹中", "前田", "フジタ", "戸田", "五洋", "西松", "熊谷", "奥村",
      "三井住友建設", "安藤ハザマ", "鉄建", "東急建設", "長谷工"], "ゼネコン"),
    # 建設コンサルタント（「設計」は住宅メーカーと紛らわしいため除外）
    (["コンサル", "技研", "エンジニア", "技術コンサル", "調査設計", "地質"], "建設コンサルタント"),
    # 測量会社
    (["測量", "測地", "サーベイ", "工測"], "測量会社"),
    # 不動産
    (["不動産", "リアル", "地所", "デベロッパー", "マンション"], "不動産"),
    # 官公庁
    (["市役所", "県庁", "町役場", "村役場", "国土交通", "農林水産", "環境省",
      "防衛省", "整備局", "事務所", "市 ", "県 ", "町 ", "村 "], "官公庁"),
]

# サービスカテゴリ（受注台帳の既存値 → 統一カテゴリ）
SERVICE_CATEGORY_MAP = {
    "ドローン測量": "ドローン測量",
    "現場空撮": "現場空撮",
    "空撮": "現場空撮",
    "眺望撮影": "眺望撮影",
    "点検": "点検",
    "その他": "その他",
}

# 案件名のキーワード → サービスカテゴリ推定
SERVICE_KEYWORDS = [
    (["土量", "出来高", "出来形", "体積", "盛土", "切土", "残土"], "ドローン測量"),
    (["測量", "3D", "三次元", "点群", "オルソ", "UAV測量", "i-Con"], "ドローン測量"),
    (["空撮", "撮影", "現場撮影", "進捗撮影", "記録撮影", "工事撮影"], "現場空撮"),
    (["眺望", "パノラマ", "マンション"], "眺望撮影"),
    (["点検", "インフラ", "橋梁", "屋根", "外壁", "赤外線", "サーモ"], "点検"),
    (["スキャン", "レーザー", "TLS"], "ドローン測量"),
]

# 業種カテゴリの順序（レポート表示用）
INDUSTRY_ORDER = ["ゼネコン", "建設コンサルタント", "測量会社", "不動産", "官公庁", "その他"]
SERVICE_ORDER = ["ドローン測量", "現場空撮", "眺望撮影", "点検", "その他"]


# ── Lark API共通 ──
def lark_get_token():
    """テナントアクセストークンを取得"""
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
        if "tenant_access_token" not in resp:
            print(f"[ERROR] トークン取得失敗: {resp}")
            sys.exit(1)
        return resp["tenant_access_token"]


def get_all_records(token, table_id):
    """テーブルの全レコードをページネーション付きで取得"""
    records = []
    page_token = None
    while True:
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500")
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    if not body:
                        print(f"[WARN] Empty response (attempt {attempt+1}/3)")
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
                print(f"[WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if result is None:
            print(f"[ERROR] Failed to fetch records after 3 attempts for table {table_id}")
            break
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def batch_update_records(token, table_id, records_to_update):
    """レコードを一括更新（最大500件/回）"""
    success_count = 0
    fail_count = 0
    for i in range(0, len(records_to_update), 500):
        batch = records_to_update[i:i+500]
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records/batch_update")
        payload = {
            "records": [
                {"record_id": rec_id, "fields": fields}
                for rec_id, fields in batch
            ]
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                result = json.loads(r.read())
                if result.get("code") == 0:
                    success_count += len(batch)
                else:
                    print(f"[WARN] バッチ更新エラー: {result.get('msg')}")
                    fail_count += len(batch)
        except urllib.error.HTTPError as e:
            print(f"[ERROR] バッチ更新HTTPエラー: {e.code} {e.read().decode()}")
            fail_count += len(batch)
        time.sleep(0.5)
    return success_count, fail_count


# ── 分類ロジック ──
def classify_industry(existing_value, company_name, account_industry=None):
    """
    業種を分類する。
    優先順位:
      1. 受注台帳の既存「業種」値をマッピング
      2. 取引先テーブルの「業種」値
      3. 取引先名からキーワード推定
    """
    # 1. 既存値のマッピング
    if existing_value and existing_value.strip():
        mapped = INDUSTRY_CATEGORY_MAP.get(existing_value.strip())
        if mapped:
            return mapped, "既存値"

    # 2. 取引先テーブルの業種（複数選択なのでリストの場合あり）
    if account_industry:
        if isinstance(account_industry, list):
            for item in account_industry:
                name = item.get("name", "") if isinstance(item, dict) else str(item)
                # 取引先テーブルの業種選択肢をマッピング
                for key, cat in [
                    ("ゼネコン", "ゼネコン"), ("サブコン", "ゼネコン"),
                    ("土木", "ゼネコン"), ("建設会社", "ゼネコン"),
                    ("コンサル", "建設コンサルタント"),
                    ("測量", "測量会社"),
                    ("不動産", "不動産"),
                    ("砕石", "その他"), ("採石", "その他"),
                    ("残土", "その他"), ("鉱山", "その他"),
                    ("工場", "その他"), ("物流", "その他"),
                    ("解体", "その他"), ("レンタル", "その他"),
                    ("メーカー", "その他"),
                ]:
                    if key in name:
                        return cat, f"取引先テーブル({name})"
        elif isinstance(account_industry, str) and account_industry.strip():
            mapped = INDUSTRY_CATEGORY_MAP.get(account_industry.strip())
            if mapped:
                return mapped, f"取引先テーブル({account_industry})"

    # 3. 取引先名からキーワード推定
    if company_name:
        name_lower = company_name.lower()
        for keywords, category in INDUSTRY_KEYWORDS:
            for kw in keywords:
                if kw in name_lower:
                    return category, f"キーワード({kw})"

    return "その他", "推定不可"


def classify_service(existing_value, case_name):
    """
    サービスを分類する。
    優先順位:
      1. 受注台帳の既存「サービス種別」値をマッピング
      2. 案件名からキーワード推定
    """
    # 1. 既存値のマッピング
    if existing_value and existing_value.strip():
        mapped = SERVICE_CATEGORY_MAP.get(existing_value.strip())
        if mapped:
            return mapped, "既存値"

    # 2. 案件名からキーワード推定
    if case_name:
        name_lower = case_name.lower()
        for keywords, category in SERVICE_KEYWORDS:
            for kw in keywords:
                if kw in name_lower:
                    return category, f"キーワード({kw})"

    return "その他", "推定不可"


def normalize_company_name(name):
    """会社名を正規化"""
    if not name:
        return ""
    name = name.replace(" ", "").replace("\u3000", "").strip()
    for prefix in ["株式会社", "(株)", "（株）", "有限会社", "(有)", "（有）"]:
        name = name.replace(prefix, "")
    return name.strip()


# ── レポート出力 ──
def print_cross_table(matrix, industry_totals, service_totals, grand_total):
    """業種×サービスのクロス集計表を出力"""
    # ヘッダー
    col_width = 14
    header = f"{'業種':^{col_width}}"
    for svc in SERVICE_ORDER:
        header += f" | {svc:^{col_width}}"
    header += f" | {'合計':^8}"
    print(header)
    print("-" * len(header))

    # 各行
    for ind in INDUSTRY_ORDER:
        row = f"{ind:<{col_width}}"
        for svc in SERVICE_ORDER:
            count = matrix.get((ind, svc), 0)
            pct = (count / grand_total * 100) if grand_total > 0 else 0
            cell = f"{count:>3} ({pct:4.1f}%)"
            row += f" | {cell:^{col_width}}"
        total = industry_totals.get(ind, 0)
        pct_total = (total / grand_total * 100) if grand_total > 0 else 0
        row += f" | {total:>3} ({pct_total:4.1f}%)"
        print(row)

    # フッター
    print("-" * len(header))
    footer = f"{'合計':<{col_width}}"
    for svc in SERVICE_ORDER:
        total = service_totals.get(svc, 0)
        pct = (total / grand_total * 100) if grand_total > 0 else 0
        cell = f"{total:>3} ({pct:4.1f}%)"
        footer += f" | {cell:^{col_width}}"
    footer += f" | {grand_total:>3} (100%)"
    print(footer)


def print_revenue_table(revenue_matrix, revenue_industry, revenue_service, total_revenue):
    """業種×サービスの売上クロス集計表を出力"""
    col_width = 16
    header = f"{'業種（売上万円）':^{col_width}}"
    for svc in SERVICE_ORDER:
        header += f" | {svc:^{col_width}}"
    header += f" | {'合計':^12}"
    print(header)
    print("-" * len(header))

    for ind in INDUSTRY_ORDER:
        row = f"{ind:<{col_width}}"
        for svc in SERVICE_ORDER:
            amount = revenue_matrix.get((ind, svc), 0)
            cell = f"{amount/10000:>10,.0f}" if amount > 0 else f"{'—':>10}"
            row += f" | {cell:^{col_width}}"
        total = revenue_industry.get(ind, 0)
        row += f" | {total/10000:>8,.0f}"
        print(row)

    print("-" * len(header))
    footer = f"{'合計':<{col_width}}"
    for svc in SERVICE_ORDER:
        total = revenue_service.get(svc, 0)
        cell = f"{total/10000:>10,.0f}" if total > 0 else f"{'—':>10}"
        footer += f" | {cell:^{col_width}}"
    footer += f" | {total_revenue/10000:>8,.0f}"
    print(footer)


# ── メイン処理 ──
def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 70)
    print("  受注台帳 業種別×サービス別 分類")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  モード: {'ドライラン（分析のみ）' if dry_run else '本番更新'}")
    print("=" * 70)

    # トークン取得
    token = lark_get_token()

    # データ取得
    print("\nデータ取得中...")
    print("  受注台帳...", end="", flush=True)
    orders = get_all_records(token, TABLE_ORDERS)
    print(f" {len(orders)}件")

    print("  取引先テーブル...", end="", flush=True)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f" {len(accounts)}件")

    # 取引先のrecord_id→情報マッピング（名前正規化でもマッチ）
    account_by_name = {}
    for acc in accounts:
        f = acc.get("fields", {})
        formal = f.get("会社名（正式）", "")
        short = f.get("会社名（略称）", "")
        industry = f.get("業種", None)
        info = {"industry": industry, "formal": formal, "short": short}

        if formal:
            account_by_name[normalize_company_name(formal)] = info
        if short:
            account_by_name[normalize_company_name(short)] = info

    print(f"  取引先名マッチ用インデックス: {len(account_by_name)}件")

    # ── 分類処理 ──
    print("\n分類処理中...")
    classified = []
    records_to_update = []

    # クロス集計用
    matrix = defaultdict(int)          # (業種, サービス) -> count
    revenue_matrix = defaultdict(float)  # (業種, サービス) -> 金額合計
    industry_totals = defaultdict(int)
    service_totals = defaultdict(int)
    revenue_industry = defaultdict(float)
    revenue_service = defaultdict(float)
    total_revenue = 0

    # 分類理由の集計
    industry_reasons = defaultdict(int)
    service_reasons = defaultdict(int)

    for order in orders:
        fields = order.get("fields", {})
        record_id = order.get("record_id", "")

        case_name = fields.get("案件名", "") or ""
        company = fields.get("取引先", "") or ""
        existing_industry = fields.get("業種", "") or ""
        existing_service = fields.get("サービス種別", "") or ""
        amount = fields.get("受注金額") or fields.get("請求金額") or 0

        # 取引先テーブルから業種情報を取得
        normalized = normalize_company_name(company)
        account_info = account_by_name.get(normalized)
        account_industry = account_info["industry"] if account_info else None

        # 分類実行
        ind_category, ind_reason = classify_industry(
            existing_industry, company, account_industry
        )
        svc_category, svc_reason = classify_service(
            existing_service, case_name
        )

        # 集計
        matrix[(ind_category, svc_category)] += 1
        industry_totals[ind_category] += 1
        service_totals[svc_category] += 1
        industry_reasons[ind_reason] += 1
        service_reasons[svc_reason] += 1

        if amount and isinstance(amount, (int, float)):
            revenue_matrix[(ind_category, svc_category)] += amount
            revenue_industry[ind_category] += amount
            revenue_service[svc_category] += amount
            total_revenue += amount

        entry = {
            "record_id": record_id,
            "案件名": case_name,
            "取引先": company,
            "業種カテゴリ": ind_category,
            "業種分類理由": ind_reason,
            "サービスカテゴリ": svc_category,
            "サービス分類理由": svc_reason,
            "受注金額": amount,
        }
        classified.append(entry)

        # 更新対象の判定（既存値と異なる場合のみ更新）
        update_fields = {}
        if existing_industry != ind_category:
            update_fields["業種"] = ind_category
        if existing_service != svc_category:
            update_fields["サービス種別"] = svc_category

        if update_fields:
            records_to_update.append((record_id, update_fields))

        if verbose:
            print(f"  {case_name[:40]:40s} | {company[:20]:20s} | "
                  f"{ind_category} ({ind_reason}) | {svc_category} ({svc_reason})")

    grand_total = len(orders)

    # ── レポート出力 ──
    print("\n" + "=" * 70)
    print("  件数クロス集計（業種 x サービス）")
    print("=" * 70)
    print_cross_table(matrix, industry_totals, service_totals, grand_total)

    if total_revenue > 0:
        print("\n" + "=" * 70)
        print("  売上クロス集計（業種 x サービス）単位: 万円")
        print("=" * 70)
        print_revenue_table(revenue_matrix, revenue_industry, revenue_service, total_revenue)

    # 分類理由の内訳
    print("\n" + "=" * 70)
    print("  分類理由の内訳")
    print("=" * 70)
    print("\n  [業種カテゴリ]")
    for reason, count in sorted(industry_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:30s}: {count:>4}件")
    print("\n  [サービスカテゴリ]")
    for reason, count in sorted(service_reasons.items(), key=lambda x: -x[1]):
        print(f"    {reason:30s}: {count:>4}件")

    # 更新対象の確認
    print(f"\n更新対象: {len(records_to_update)}件 / {grand_total}件")
    if records_to_update and verbose:
        print("  更新内容（最大20件）:")
        for rec_id, fields in records_to_update[:20]:
            # 対応する分類結果を探す
            entry = next((e for e in classified if e["record_id"] == rec_id), None)
            name = entry["案件名"][:30] if entry else rec_id
            print(f"    {name}: {fields}")

    # ── JSON出力 ──
    output_path = DATA_DIR / "case_classification.json"
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_records": grand_total,
        "summary": {
            "industry": {ind: industry_totals.get(ind, 0) for ind in INDUSTRY_ORDER},
            "service": {svc: service_totals.get(svc, 0) for svc in SERVICE_ORDER},
            "cross_table": {
                f"{ind}_{svc}": matrix.get((ind, svc), 0)
                for ind in INDUSTRY_ORDER for svc in SERVICE_ORDER
            },
            "revenue": {
                "total": total_revenue,
                "by_industry": {ind: revenue_industry.get(ind, 0) for ind in INDUSTRY_ORDER},
                "by_service": {svc: revenue_service.get(svc, 0) for svc in SERVICE_ORDER},
            },
        },
        "records": classified,
        "update_candidates": len(records_to_update),
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nJSON出力: {output_path}")

    # ── 書き込み ──
    if dry_run:
        print("\n" + "=" * 70)
        print("  ドライラン完了。書き込みは行いません。")
        print(f"  本番実行: python3 {Path(__file__).name}")
        print("=" * 70)
        return

    if not records_to_update:
        print("\n更新不要（全レコード分類済み）")
        return

    print(f"\n受注台帳を更新中... ({len(records_to_update)}件)")
    # スナップショット保存（データ変更前の安全策）
    snapshot_path = DATA_DIR / f"case_classifier_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    snapshot = []
    for order in orders:
        record_id = order.get("record_id", "")
        if any(rid == record_id for rid, _ in records_to_update):
            snapshot.append({
                "record_id": record_id,
                "fields": {
                    "業種": order.get("fields", {}).get("業種", ""),
                    "サービス種別": order.get("fields", {}).get("サービス種別", ""),
                }
            })
    with open(snapshot_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)
    print(f"  スナップショット保存: {snapshot_path}")

    success, fail = batch_update_records(token, TABLE_ORDERS, records_to_update)
    print(f"  成功: {success}件 / 失敗: {fail}件")

    print("\n" + "=" * 70)
    print("  分類・更新完了")
    print("=" * 70)


if __name__ == "__main__":
    main()
