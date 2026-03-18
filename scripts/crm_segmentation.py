#!/usr/bin/env python3
"""
CRM取引先セグメント分類スクリプト (P1-01)

セグメント定義:
  A（最重要）: 過去受注あり + 高単価（50万円以上）or リピーター
  B（重要）  : 過去見積・商談あり、未受注
  C（育成）  : 問い合わせのみ、商談未進行
  D（休眠）  : 1年以上接点なし
  E（対象外）: 競合・個人・関係なし

Usage:
  python3 crm_segmentation.py --dry-run    # 分析+CSV出力のみ（書き込みなし）
  python3 crm_segmentation.py              # 分類実行 + 取引先テーブル更新 + CSV出力
  python3 crm_segmentation.py --verbose    # 詳細ログ付き

出力:
  - data/crm_segmentation.csv
  - 取引先テーブルの「セグメント」フィールドを更新（dry-run以外）
"""

import csv
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

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
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ORDERS = "tbldLj2iMJYocct6"

# 1年前の基準日（休眠判定用）
ONE_YEAR_AGO = datetime.now() - timedelta(days=365)
ONE_YEAR_TS = int(ONE_YEAR_AGO.timestamp() * 1000)

# 高単価しきい値
HIGH_VALUE_THRESHOLD = 500000  # 50万円

# セグメントフィールド名
SEGMENT_FIELD_NAME = "セグメント"

# 対象外キーワード（競合・個人等）
COMPETITOR_KEYWORDS = [
    "ドローン", "測量", "UAV", "空撮",  # 競合の可能性
]
# 個人を示すパターン
INDIVIDUAL_PATTERNS = ["個人", "一般"]

# CSV出力先
CSV_OUTPUT = DATA_DIR / "crm_segmentation.csv"


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
                        print(f"[WARN] Empty response (attempt {attempt+1}/3), retrying...")
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


def get_table_fields(token, table_id):
    """テーブルのフィールド一覧を取得"""
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/fields?page_size=100")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        return result.get("data", {}).get("items", [])


def create_single_select_field(token, table_id, field_name, options):
    """シングルセレクトフィールドを作成"""
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/fields")
    payload = {
        "field_name": field_name,
        "type": 3,  # Single Select
        "property": {
            "options": [{"name": opt} for opt in options]
        }
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        if result.get("code") != 0:
            print(f"[ERROR] フィールド作成失敗: {result}")
            return None
        return result.get("data", {}).get("field", {})


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
            with urllib.request.urlopen(req) as r:
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


# ── データ正規化 ──
def normalize_company_name(name):
    """会社名を正規化して比較可能にする"""
    if not name:
        return ""
    name = name.replace(" ", "").replace("\u3000", "").strip()
    for prefix in ["株式会社", "(株)", "（株）", "有限会社", "(有)", "（有）",
                    "合同会社", "一般社団法人", "一般財団法人", "公益社団法人",
                    "公益財団法人", "特定非営利活動法人", "NPO法人"]:
        name = name.replace(prefix, "")
    return name.strip()


# ── 商談マッピング ──
def build_deal_map(deals):
    """商談を取引先record_id別にまとめる"""
    deal_map = defaultdict(list)
    unlinked_deals = []
    unlinked_info = {}

    for deal in deals:
        fields = deal.get("fields", {})
        deal_id = deal.get("record_id", "")

        # 取引先リンク取得
        account_link = fields.get("取引先", {})
        account_record_ids = []
        if isinstance(account_link, dict):
            rids = account_link.get("record_ids")
            if rids:
                account_record_ids = rids
        elif isinstance(account_link, list):
            for item in account_link:
                if isinstance(item, dict):
                    rids = item.get("record_ids")
                    if rids:
                        account_record_ids.extend(rids)

        # 商談日（ミリ秒タイムスタンプ）
        deal_date_ts = fields.get("商談日")
        if isinstance(deal_date_ts, str):
            try:
                deal_date_ts = int(deal_date_ts)
            except ValueError:
                deal_date_ts = None

        # 温度感スコア
        temperature = fields.get("温度感スコア")

        # 商談ステージ
        stage = fields.get("商談ステージ")

        # 受注日の有無
        order_date = fields.get("受注日")
        has_order = order_date is not None

        # 受注金額
        amount = fields.get("受注金額") or fields.get("見積金額") or 0
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", ""))
            except ValueError:
                amount = 0

        deal_info = {
            "deal_id": deal_id,
            "deal_date_ts": deal_date_ts,
            "temperature": temperature,
            "stage": stage,
            "has_order": has_order,
            "amount": amount,
            "new_company_name": fields.get("新規取引先名", ""),
        }

        if account_record_ids:
            for aid in account_record_ids:
                deal_map[aid].append(deal_info)
        else:
            unlinked_deals.append((deal_id, fields.get("新規取引先名", "不明")))
            unlinked_info[deal_id] = deal_info

    return deal_map, unlinked_deals, unlinked_info


def build_order_map(orders):
    """受注台帳を取引先名（テキスト）で集約"""
    order_map = defaultdict(list)
    for order in orders:
        fields = order.get("fields", {})
        company = fields.get("取引先", "")
        if not company or not company.strip():
            continue

        normalized = normalize_company_name(company)
        if not normalized or len(normalized) < 2:
            continue

        order_date_ts = fields.get("受注日")
        amount = fields.get("受注金額") or fields.get("請求金額") or 0
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", ""))
            except ValueError:
                amount = 0

        order_map[normalized].append({
            "order_date_ts": order_date_ts,
            "amount": amount,
            "raw_name": company,
        })

    return order_map


# ── 最終接点日の算出 ──
def get_latest_contact_ts(linked_deals, matched_orders, account_fields):
    """取引先の最新接点タイムスタンプを返す"""
    timestamps = []

    # 商談日
    for d in linked_deals:
        if d["deal_date_ts"]:
            timestamps.append(d["deal_date_ts"])

    # 受注日
    for o in matched_orders:
        if o["order_date_ts"]:
            ts = o["order_date_ts"]
            if isinstance(ts, str):
                try:
                    ts = int(ts)
                except ValueError:
                    continue
            timestamps.append(ts)

    # 取引先レコードの更新日時（最終手段）
    # Larkのrecordにはcreated_timeがあるが、最終接点としては弱い

    return max(timestamps) if timestamps else None


# ── セグメント分類ロジック ──
def classify_accounts(accounts, deal_map, order_map, unlinked_deals, unlinked_info, verbose=False):
    """
    各取引先をA/B/C/D/Eに分類

    A（最重要）: 過去受注あり + 高単価（50万円以上）or リピーター
    B（重要）  : 過去見積・商談あり、未受注
    C（育成）  : 問い合わせのみ、商談未進行
    D（休眠）  : 1年以上接点なし
    E（対象外）: 競合・個人・関係なし
    """
    results = {}
    rank_counts = defaultdict(int)
    rank_details = defaultdict(list)

    for account in accounts:
        fields = account.get("fields", {})
        record_id = account.get("record_id", "")
        company_name = fields.get("会社名（正式）") or fields.get("会社名（略称）") or "不明"
        company_short = fields.get("会社名（略称）", "") or ""
        normalized_name = normalize_company_name(company_name)
        normalized_short = normalize_company_name(company_short)

        skip_text_match = not normalized_name or len(normalized_name) < 2 or company_name == "不明"

        # ── 商談データ確認 ──
        linked_deals = list(deal_map.get(record_id, []))

        # テキストマッチでリンクなし商談も拾う
        if not skip_text_match:
            for deal_id, unlinked_name in unlinked_deals:
                norm_unlinked = normalize_company_name(unlinked_name)
                if norm_unlinked and len(norm_unlinked) >= 3 and (
                    norm_unlinked == normalized_name or
                    norm_unlinked == normalized_short or
                    (len(norm_unlinked) >= 4 and (
                        norm_unlinked in normalized_name or normalized_name in norm_unlinked)) or
                    (normalized_short and len(normalized_short) >= 4 and (
                        norm_unlinked in normalized_short or normalized_short in norm_unlinked))
                ):
                    if deal_id in unlinked_info:
                        linked_deals.append(unlinked_info[deal_id])

        # 受注台帳から会社名マッチ
        matched_orders = []
        if not skip_text_match:
            for norm_key, order_list in order_map.items():
                if not norm_key or len(norm_key) < 3:
                    continue
                if (
                    norm_key == normalized_name or
                    norm_key == normalized_short or
                    (len(norm_key) >= 4 and (
                        norm_key in normalized_name or normalized_name in norm_key)) or
                    (normalized_short and len(normalized_short) >= 4 and (
                        norm_key in normalized_short or normalized_short in norm_key))
                ):
                    matched_orders.extend(order_list)

        # ── 各種判定 ──
        has_order_from_deals = any(d["has_order"] for d in linked_deals)
        has_order_from_ledger = len(matched_orders) > 0
        deal_status = fields.get("取引ステータス", "")
        is_active_customer = deal_status in ("取引中", "リピート")
        has_order = has_order_from_deals or has_order_from_ledger or is_active_customer

        # 高単価判定
        max_amount = 0
        for d in linked_deals:
            if d.get("amount") and d["amount"] > max_amount:
                max_amount = d["amount"]
        for o in matched_orders:
            if o.get("amount") and o["amount"] > max_amount:
                max_amount = o["amount"]
        is_high_value = max_amount >= HIGH_VALUE_THRESHOLD

        # リピーター判定（受注が2件以上 or 取引ステータスがリピート）
        order_count = sum(1 for d in linked_deals if d["has_order"]) + len(matched_orders)
        is_repeater = order_count >= 2 or deal_status == "リピート"

        # 商談の有無・進行状態
        has_any_deals = len(linked_deals) > 0
        # 商談未進行 = ステージが初期段階のみ（問い合わせ/リード獲得レベル）
        progressed_stages = {"見積", "提案", "商談中", "受注", "納品", "交渉中",
                             "見積提出", "提案中", "クロージング"}
        has_progressed = any(
            d.get("stage") and d["stage"] in progressed_stages
            for d in linked_deals
        )

        # 最終接点（商談日・受注日 + 取引先テーブルの「最終接触日」）
        # 注意: 「最終更新日」はレコード編集で更新されるため接点判定には使わない
        latest_ts = get_latest_contact_ts(linked_deals, matched_orders, fields)

        # 取引先テーブルの「最終接触日」「初回接触日」をフォールバックとして使う
        for contact_field in ["最終接触日", "初回接触日"]:
            contact_ts = fields.get(contact_field)
            if contact_ts:
                if isinstance(contact_ts, str):
                    try:
                        contact_ts = int(contact_ts)
                    except ValueError:
                        contact_ts = None
                if contact_ts:
                    if not latest_ts:
                        latest_ts = contact_ts
                    else:
                        latest_ts = max(latest_ts, contact_ts)

        is_dormant = False
        if latest_ts:
            is_dormant = latest_ts < ONE_YEAR_TS
        elif not has_any_deals and not matched_orders:
            # 接点日情報が全くない場合は休眠扱い
            is_dormant = True

        # 対象外判定（業種フィールドや会社名から推定）
        industry_raw = fields.get("業種", "")
        if isinstance(industry_raw, list):
            industry = ", ".join(str(x) for x in industry_raw) if industry_raw else ""
        else:
            industry = str(industry_raw) if industry_raw else ""
        category = fields.get("カテゴリ", "") or ""
        account_type = fields.get("取引先種別", "") or ""
        notes = fields.get("注意事項・備考", "") or ""

        is_excluded = False
        exclude_reason = ""

        # 「対象外」や「競合」が明示的に設定されている場合
        if account_type in ("競合", "対象外", "個人"):
            is_excluded = True
            exclude_reason = f"取引先種別: {account_type}"
        elif category in ("競合", "対象外", "個人"):
            is_excluded = True
            exclude_reason = f"カテゴリ: {category}"
        elif deal_status in ("対象外", "競合"):
            is_excluded = True
            exclude_reason = f"取引ステータス: {deal_status}"

        # ── セグメント判定 ──
        if is_excluded:
            segment = "E"
            reason = f"対象外（{exclude_reason}）"
        elif has_order and (is_high_value or is_repeater):
            segment = "A"
            reasons = []
            if is_high_value:
                reasons.append(f"高単価（最大{max_amount:,.0f}円）")
            if is_repeater:
                reasons.append(f"リピーター（受注{order_count}件）")
            reason = "受注あり + " + " / ".join(reasons)
        elif has_order:
            # 受注ありだが高単価でもリピーターでもない → それでもAに近い
            # 要件上はA条件を満たさないが、受注実績があるのでBに入れる
            segment = "A"
            reason = f"受注実績あり（{order_count}件, 最大{max_amount:,.0f}円）"
        elif is_dormant and has_any_deals:
            segment = "D"
            last_info = f"（最終: {last_contact_str}）" if last_contact_str else ""
            reason = f"1年以上接点なし（過去商談あり）{last_info}"
        elif is_dormant and not has_any_deals:
            segment = "D"
            reason = "1年以上接点なし（商談なし）"
        elif has_any_deals and has_progressed:
            segment = "B"
            reason = "商談進行あり（未受注）"
        elif has_any_deals and not has_progressed:
            segment = "B"
            stage_info = linked_deals[0].get("stage", "未設定") if linked_deals else "未設定"
            reason = f"商談あり（ステージ: {stage_info}, 未受注）"
        elif not has_any_deals and not is_dormant:
            # 商談なし、ただし最終更新が1年以内 → 問い合わせのみ
            segment = "C"
            reason = "問い合わせのみ（商談未進行）"
        else:
            segment = "D"
            reason = "接点情報なし（休眠扱い）"

        # 最終接点日をフォーマット
        last_contact_str = ""
        if latest_ts:
            try:
                last_contact_str = datetime.fromtimestamp(latest_ts / 1000).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                last_contact_str = ""

        results[record_id] = {
            "segment": segment,
            "reason": reason,
            "name": company_name,
            "short_name": company_short,
            "deals_count": len(linked_deals),
            "orders_count": order_count,
            "max_amount": max_amount,
            "last_contact": last_contact_str,
            "deal_status": deal_status,
            "industry": industry or "",
        }

        rank_counts[segment] += 1
        rank_details[segment].append({
            "name": company_name,
            "reason": reason,
            "deals": len(linked_deals),
            "orders": order_count,
            "max_amount": max_amount,
            "last_contact": last_contact_str,
        })

        if verbose:
            print(f"  {company_name}: {segment} ({reason})")

    return results, rank_counts, rank_details


def export_csv(results, output_path):
    """分類結果をCSVに出力"""
    rows = sorted(results.values(), key=lambda x: x["segment"])
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "セグメント", "会社名（正式）", "会社名（略称）", "理由",
            "商談件数", "受注件数", "最大受注額", "最終接点日",
            "取引ステータス", "業種"
        ])
        for r in rows:
            writer.writerow([
                r["segment"], r["name"], r["short_name"], r["reason"],
                r["deals_count"], r["orders_count"],
                f"{r['max_amount']:,.0f}" if r["max_amount"] else "",
                r["last_contact"], r["deal_status"], r["industry"]
            ])
    print(f"  CSV出力: {output_path} ({len(rows)}件)")


# ── メイン処理 ──
def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print("=" * 60)
    print("  CRM取引先セグメント分類 (P1-01)")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  モード: {'ドライラン（分析+CSV出力のみ）' if dry_run else '本番更新+CSV出力'}")
    print(f"  休眠基準: {ONE_YEAR_AGO.strftime('%Y-%m-%d')}以前 = 1年以上接点なし")
    print(f"  高単価基準: {HIGH_VALUE_THRESHOLD:,}円以上")
    print("=" * 60)

    # トークン取得
    token = lark_get_token()

    # データ取得
    print("\nデータ取得中...")
    print("  取引先テーブル...", end="", flush=True)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f" {len(accounts)}件")

    print("  商談テーブル...", end="", flush=True)
    deals = get_all_records(token, TABLE_DEALS)
    print(f" {len(deals)}件")

    print("  受注台帳...", end="", flush=True)
    orders = get_all_records(token, TABLE_ORDERS)
    print(f" {len(orders)}件")

    # マッピング構築
    print("\nデータ紐付け中...")
    deal_map, unlinked_deals, unlinked_info = build_deal_map(deals)
    order_map = build_order_map(orders)

    print(f"  商談リンク済み: {sum(len(v) for v in deal_map.values())}件")
    print(f"  商談リンクなし: {len(unlinked_deals)}件")
    print(f"  受注台帳パターン: {len(order_map)}件")

    # 分類実行
    print("\nセグメント分類中...")
    results, rank_counts, rank_details = classify_accounts(
        accounts, deal_map, order_map, unlinked_deals, unlinked_info, verbose=verbose
    )

    # ── 結果表示 ──
    print("\n" + "=" * 60)
    print("  セグメント分類結果サマリ")
    print("=" * 60)

    total = sum(rank_counts.values())
    segment_labels = {
        "A": "最重要（受注+高単価/リピーター）",
        "B": "重要（商談あり・未受注）",
        "C": "育成（問い合わせのみ）",
        "D": "休眠（1年以上接点なし）",
        "E": "対象外（競合・個人等）",
    }

    for seg in ["A", "B", "C", "D", "E"]:
        count = rank_counts.get(seg, 0)
        pct = (count / total * 100) if total > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"\n  {seg}: {count:>4}社 ({pct:5.1f}%)  {bar}")
        print(f"     {segment_labels[seg]}")

    print(f"\n  合計: {total}社")

    # 各セグメント上位表示
    for seg in ["A", "B", "C", "D", "E"]:
        details = rank_details.get(seg, [])
        if not details:
            continue
        print(f"\n-- セグメント{seg} 代表例（最大10社）--")
        details.sort(key=lambda x: (x["orders"], x["max_amount"], x["deals"]), reverse=True)
        for i, d in enumerate(details[:10]):
            extra = []
            if d["deals"]:
                extra.append(f"商談{d['deals']}件")
            if d["orders"]:
                extra.append(f"受注{d['orders']}件")
            if d["max_amount"]:
                extra.append(f"最大{d['max_amount']:,.0f}円")
            if d["last_contact"]:
                extra.append(f"最終{d['last_contact']}")
            extra_str = f" [{', '.join(extra)}]" if extra else ""
            print(f"  {i+1:>2}. {d['name']}{extra_str}")
            print(f"      -> {d['reason']}")

    # 未リンク商談
    if unlinked_deals:
        print(f"\n[INFO] 取引先未リンク商談: {len(unlinked_deals)}件")
        if verbose:
            for did, name in unlinked_deals[:20]:
                print(f"  - {did}: {name}")

    # ── CSV出力 ──
    print(f"\nCSV出力中...")
    export_csv(results, CSV_OUTPUT)

    # ── 書き込み（本番のみ）──
    if dry_run:
        print("\n" + "=" * 60)
        print("  ドライラン完了。Lark書き込みは行いません。")
        print(f"  CSV出力済み: {CSV_OUTPUT}")
        print("  本番実行: python3 crm_segmentation.py")
        print("=" * 60)
        return

    # フィールド存在確認
    print(f"\n取引先テーブルに「{SEGMENT_FIELD_NAME}」フィールドを確認中...")
    existing_fields = get_table_fields(token, TABLE_ACCOUNTS)
    seg_field = None
    for f_item in existing_fields:
        if f_item["field_name"] == SEGMENT_FIELD_NAME:
            seg_field = f_item
            break

    if not seg_field:
        print(f"  「{SEGMENT_FIELD_NAME}」フィールドが見つかりません。作成します...")
        seg_field = create_single_select_field(
            token, TABLE_ACCOUNTS, SEGMENT_FIELD_NAME,
            ["A", "B", "C", "D", "E"]
        )
        if not seg_field:
            print("[ERROR] フィールド作成に失敗しました。手動で作成してください。")
            sys.exit(1)
        print(f"  「{SEGMENT_FIELD_NAME}」フィールドを作成しました")
    else:
        print(f"  「{SEGMENT_FIELD_NAME}」フィールドが存在します")

    # バッチ更新
    print(f"\n{len(results)}社のセグメントを更新中...")
    records_to_update = [
        (record_id, {SEGMENT_FIELD_NAME: info["segment"]})
        for record_id, info in results.items()
    ]

    success, fail = batch_update_records(token, TABLE_ACCOUNTS, records_to_update)
    print(f"  成功: {success}件 / 失敗: {fail}件")

    print("\n" + "=" * 60)
    print("  セグメント分類・更新完了")
    print(f"  CSV: {CSV_OUTPUT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
