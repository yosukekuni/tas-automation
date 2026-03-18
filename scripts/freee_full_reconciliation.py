#!/usr/bin/env python3
"""
受注台帳 vs freee請求書 全体突合スクリプト

受注台帳181件を全て分類し、freee請求書20件との対応関係を網羅的に出力する。
チェックのみ（データ変更なし）。

分類:
  A. freee請求書あり & 入金済み
  B. freee請求書あり & 未入金（支払期限超過含む）
  C. 未請求（請求金額あり + 請求日あり + freee未発行）
  D. 請求準備中（請求金額 or 請求日が未入力）
  E. 入金済み（CRM上で入金日入力済み）
  F. その他（金額なし等）
"""

import json
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
import shutil
from datetime import datetime, date
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
FREEE_API_BASE = "https://api.freee.co.jp"
FREEE_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

OUTPUT_DIR = SCRIPT_DIR.parent / "content"
OUTPUT_DIR.mkdir(exist_ok=True)


def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    backup = CONFIG_FILE.with_suffix(".json.bak")
    shutil.copy2(CONFIG_FILE, backup)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def refresh_token(config):
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
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
    config["freee"]["access_token"] = result["access_token"]
    config["freee"]["refresh_token"] = result["refresh_token"]
    save_config(config)
    return config


def freee_api(config, method, path, retry_auth=True):
    freee = config["freee"]
    url = f"{FREEE_API_BASE}{path}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {freee['access_token']}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), config
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry_auth:
            config = refresh_token(config)
            return freee_api(config, method, path, retry_auth=False)
        raise


def lark_get_token(config):
    data = json.dumps({
        "app_id": config["lark"]["app_id"],
        "app_secret": config["lark"]["app_secret"],
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def lark_list_records(token, table_id, page_size=500):
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
            url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            items = resp.get("data", {}).get("items", [])
            records.extend(items)
            if not resp.get("data", {}).get("has_more"):
                break
            page_token = resp["data"].get("page_token")
        time.sleep(0.3)
    return records


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                texts.append(item.get("text", item.get("name", str(item))))
            else:
                texts.append(str(item))
        return ", ".join(texts) if texts else ""
    if isinstance(value, dict):
        return value.get("text", value.get("name", str(value)))
    return str(value) if value else ""


def ts_to_date(ts):
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        return str(ts)
    except Exception:
        return None


def format_yen(amount):
    if amount is None:
        return "---"
    try:
        return f"{int(float(amount)):,}"
    except (ValueError, TypeError):
        return str(amount)


def get_all_freee_invoices(config):
    all_invoices = []
    page = 1
    seen_ids = set()
    while page <= 20:
        url = f"/iv/invoices?company_id={config['freee']['company_id']}&per_page=100&page={page}"
        try:
            data, config = freee_api(config, "GET", url)
            invoices = data.get("invoices", [])
            new_count = 0
            for inv in invoices:
                if inv["id"] not in seen_ids:
                    seen_ids.add(inv["id"])
                    all_invoices.append(inv)
                    new_count += 1
            if new_count == 0:
                break
            page += 1
        except Exception as e:
            print(f"  [ERROR] freee: {e}")
            break
    return all_invoices, config


def match_crm_to_freee(crm_rec, freee_invoices):
    """CRMレコードに対応するfreee請求書を探す"""
    fields = crm_rec.get("fields", {})
    company = extract_text(fields.get("取引先", ""))
    invoice_amount = fields.get("請求金額")
    order_amount = fields.get("受注金額")
    memo = extract_text(fields.get("備考", ""))
    billing_date = ts_to_date(fields.get("請求日"))

    # 1. 備考にfreee請求書番号が含まれるか
    for inv in freee_invoices:
        inv_num = inv.get("invoice_number", "")
        if inv_num and inv_num in memo:
            return inv, "備考一致"

    # 2. 取引先名 + 金額
    try:
        crm_amount = int(float(extract_text(str(invoice_amount)))) if invoice_amount else 0
    except (ValueError, TypeError):
        crm_amount = 0
    try:
        crm_order = int(float(extract_text(str(order_amount)))) if order_amount else 0
    except (ValueError, TypeError):
        crm_order = 0

    for inv in freee_invoices:
        inv_partner = inv.get("partner_name", "")
        inv_amount = inv.get("total_amount", 0)
        inv_amount_excl = inv.get("amount_excluding_tax", 0)
        inv_billing = inv.get("billing_date", "")

        # 取引先一致チェック
        company_match = False
        if inv_partner and company:
            if inv_partner in company or company in inv_partner:
                company_match = True
            inv_clean = inv_partner.replace("株式会社", "").replace("有限会社", "").strip()
            c_clean = company.replace("株式会社", "").replace("有限会社", "").strip()
            if inv_clean and c_clean and (inv_clean in c_clean or c_clean in inv_clean):
                company_match = True

        if not company_match:
            continue

        # 金額一致チェック
        if crm_amount > 0 and crm_amount in (inv_amount, inv_amount_excl):
            return inv, "取引先+金額一致"
        if crm_order > 0 and crm_order in (inv_amount, inv_amount_excl):
            return inv, "取引先+受注金額一致"

        # 請求日が近い場合に金額近似もチェック
        if billing_date and inv_billing:
            try:
                bd = date.fromisoformat(billing_date)
                ibd = date.fromisoformat(inv_billing)
                if abs((bd - ibd).days) <= 30:
                    if crm_amount > 0 and inv_amount > 0:
                        ratio = abs(crm_amount - inv_amount) / max(inv_amount, 1)
                        if ratio < 0.11:  # 消費税差分を考慮
                            return inv, "取引先+金額近似"
            except (ValueError, TypeError):
                pass

    return None, None


def main():
    print("=" * 70)
    print("  受注台帳 vs freee請求書 全体突合チェック")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    config = load_config()

    # 1. データ取得
    print("\n[1/3] データ取得...")
    lark_token = lark_get_token(config)
    crm_records = lark_list_records(lark_token, ORDER_TABLE_ID)
    print(f"  CRM受注台帳: {len(crm_records)}件")

    freee_invoices, config = get_all_freee_invoices(config)
    print(f"  freee請求書: {len(freee_invoices)}件")

    # 2. 分類
    print("\n[2/3] 分類中...")

    cat_a = []  # freee請求書あり & 入金済み
    cat_b = []  # freee請求書あり & 未入金
    cat_c = []  # 未請求（条件揃い & freee未発行）
    cat_d = []  # 請求準備中
    cat_e = []  # CRM入金済み（freee無し）
    cat_f = []  # その他

    matched_freee_ids = set()

    for rec in crm_records:
        fields = rec.get("fields", {})
        case_name = extract_text(fields.get("案件名", ""))
        company = extract_text(fields.get("取引先", ""))
        invoice_amount = fields.get("請求金額")
        order_amount = fields.get("受注金額")
        billing_date_raw = fields.get("請求日")
        payment_date_raw = fields.get("入金日")
        memo = extract_text(fields.get("備考", ""))

        billing_date = ts_to_date(billing_date_raw)
        payment_date = ts_to_date(payment_date_raw)

        try:
            amount = int(float(extract_text(str(invoice_amount)))) if invoice_amount else 0
        except (ValueError, TypeError):
            amount = 0
        try:
            order_amt = int(float(extract_text(str(order_amount)))) if order_amount else 0
        except (ValueError, TypeError):
            order_amt = 0

        display_amount = amount or order_amt

        entry = {
            "record_id": rec["record_id"],
            "case_name": case_name,
            "company": company,
            "invoice_amount": amount,
            "order_amount": order_amt,
            "display_amount": display_amount,
            "billing_date": billing_date,
            "payment_date": payment_date,
            "memo": memo,
        }

        # CRM上で入金済み
        if payment_date:
            entry["category"] = "E"
            cat_e.append(entry)
            continue

        # freee請求書とマッチング
        matched_inv, match_reason = match_crm_to_freee(rec, freee_invoices)

        if matched_inv:
            entry["freee_invoice_number"] = matched_inv.get("invoice_number", "")
            entry["freee_payment_status"] = matched_inv.get("payment_status", "")
            entry["freee_amount"] = matched_inv.get("total_amount", 0)
            entry["freee_payment_date"] = matched_inv.get("payment_date", "")
            entry["freee_billing_date"] = matched_inv.get("billing_date", "")
            entry["match_reason"] = match_reason
            matched_freee_ids.add(matched_inv["id"])

            if matched_inv.get("payment_status") == "settled":
                entry["category"] = "A"
                cat_a.append(entry)
            else:
                # 支払期限超過チェック
                pd_str = matched_inv.get("payment_date", "")
                overdue = False
                if pd_str:
                    try:
                        if date.fromisoformat(pd_str) < date.today():
                            overdue = True
                    except (ValueError, TypeError):
                        pass
                entry["overdue"] = overdue
                entry["category"] = "B"
                cat_b.append(entry)
        else:
            # freee未発行
            if display_amount > 0 and billing_date:
                entry["category"] = "C"
                cat_c.append(entry)
            elif display_amount > 0 or order_amt > 0:
                entry["category"] = "D"
                cat_d.append(entry)
            else:
                entry["category"] = "F"
                cat_f.append(entry)

    # freee側にあるがCRMにマッチしなかった請求書
    unmatched_freee = [inv for inv in freee_invoices if inv["id"] not in matched_freee_ids]

    # 3. レポート生成
    print("\n[3/3] レポート生成中...")

    today_str = date.today().isoformat()
    lines = []
    lines.append(f"# freee未請求案件チェック & 受注台帳突合レポート")
    lines.append(f"")
    lines.append(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"")
    lines.append(f"## サマリー")
    lines.append(f"")
    lines.append(f"| 項目 | 件数 | 金額 |")
    lines.append(f"|------|------|------|")
    lines.append(f"| CRM受注台帳 全レコード | {len(crm_records)} | - |")
    lines.append(f"| freee請求書 全件 | {len(freee_invoices)} | - |")
    lines.append(f"| A. freee発行済み & 入金済み | {len(cat_a)} | {format_yen(sum(e['display_amount'] for e in cat_a))}円 |")
    lines.append(f"| B. freee発行済み & 未入金 | {len(cat_b)} | {format_yen(sum(e['display_amount'] for e in cat_b))}円 |")
    lines.append(f"| C. 未請求（freee未発行・条件揃い） | {len(cat_c)} | {format_yen(sum(e['display_amount'] for e in cat_c))}円 |")
    lines.append(f"| D. 請求準備中（金額 or 日付不足） | {len(cat_d)} | {format_yen(sum(e['display_amount'] for e in cat_d))}円 |")
    lines.append(f"| E. CRM入金済み（freee無し） | {len(cat_e)} | {format_yen(sum(e['display_amount'] for e in cat_e))}円 |")
    lines.append(f"| F. その他（金額なし等） | {len(cat_f)} | - |")
    lines.append(f"| freee側CRM未マッチ | {len(unmatched_freee)} | {format_yen(sum(inv.get('total_amount', 0) for inv in unmatched_freee))}円 |")

    # --- カテゴリB: 未入金（最重要） ---
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## B. freee発行済み & 未入金（{len(cat_b)}件）")
    lines.append(f"")
    if cat_b:
        overdue_items = [e for e in cat_b if e.get("overdue")]
        current_items = [e for e in cat_b if not e.get("overdue")]

        if overdue_items:
            lines.append(f"### 支払期限超過（{len(overdue_items)}件）")
            lines.append(f"")
            lines.append(f"| # | 取引先 | 案件名 | freee番号 | 金額 | 請求日 | 支払期限 |")
            lines.append(f"|---|--------|--------|-----------|------|--------|----------|")
            overdue_total = 0
            for i, e in enumerate(sorted(overdue_items, key=lambda x: x.get("freee_payment_date", "")), 1):
                overdue_total += e["display_amount"]
                lines.append(f"| {i} | {e['company'][:20]} | {e['case_name'][:30]} | {e.get('freee_invoice_number', '')} | {format_yen(e['display_amount'])}円 | {e.get('freee_billing_date', '')} | {e.get('freee_payment_date', '')} |")
            lines.append(f"| | | **合計** | | **{format_yen(overdue_total)}円** | | |")
            lines.append(f"")

        if current_items:
            lines.append(f"### 支払期限内（{len(current_items)}件）")
            lines.append(f"")
            for i, e in enumerate(current_items, 1):
                lines.append(f"- {e['company'][:20]} / {e['case_name'][:30]} / {format_yen(e['display_amount'])}円 / 期限: {e.get('freee_payment_date', 'N/A')}")
            lines.append(f"")
    else:
        lines.append(f"該当なし")
        lines.append(f"")

    # --- カテゴリC: 未請求 ---
    lines.append(f"## C. 未請求 - freee未発行（{len(cat_c)}件）")
    lines.append(f"")
    lines.append(f"請求金額・請求日が入力済みだが、freeeに対応する請求書がない案件。")
    lines.append(f"")
    if cat_c:
        lines.append(f"| # | 取引先 | 案件名 | 請求金額 | 請求日 |")
        lines.append(f"|---|--------|--------|----------|--------|")
        c_total = 0
        for i, e in enumerate(sorted(cat_c, key=lambda x: x.get("billing_date", "") or ""), 1):
            c_total += e["display_amount"]
            lines.append(f"| {i} | {e['company'][:20]} | {e['case_name'][:35]} | {format_yen(e['display_amount'])}円 | {e.get('billing_date', '')} |")
        lines.append(f"| | | **合計** | **{format_yen(c_total)}円** | |")
        lines.append(f"")
    else:
        lines.append(f"該当なし")
        lines.append(f"")

    # --- カテゴリD: 請求準備中 ---
    lines.append(f"## D. 請求準備中（{len(cat_d)}件）")
    lines.append(f"")
    lines.append(f"受注金額はあるが、請求金額 or 請求日が未入力の案件。")
    lines.append(f"")
    if cat_d:
        lines.append(f"| # | 取引先 | 案件名 | 受注/請求金額 | 請求日 | 不足項目 |")
        lines.append(f"|---|--------|--------|-------------|--------|----------|")
        for i, e in enumerate(cat_d[:30], 1):  # 上位30件のみ表示
            missing = []
            if not e["invoice_amount"]:
                missing.append("請求金額")
            if not e["billing_date"]:
                missing.append("請求日")
            lines.append(f"| {i} | {e['company'][:20]} | {e['case_name'][:30]} | {format_yen(e['display_amount'])}円 | {e.get('billing_date', '-')} | {', '.join(missing)} |")
        if len(cat_d) > 30:
            lines.append(f"| | | ... 他{len(cat_d) - 30}件 | | | |")
        lines.append(f"")
    else:
        lines.append(f"該当なし")
        lines.append(f"")

    # --- freee側CRM未マッチ ---
    if unmatched_freee:
        lines.append(f"## freee請求書でCRM未マッチ（{len(unmatched_freee)}件）")
        lines.append(f"")
        lines.append(f"freee上に請求書があるが、CRM受注台帳のどのレコードにも対応しない請求書。")
        lines.append(f"")
        lines.append(f"| # | freee番号 | 取引先 | 金額 | 請求日 | ステータス |")
        lines.append(f"|---|-----------|--------|------|--------|----------|")
        for i, inv in enumerate(unmatched_freee, 1):
            status = "入金済み" if inv.get("payment_status") == "settled" else "未入金"
            lines.append(f"| {i} | {inv.get('invoice_number', '')} | {inv.get('partner_name', '')[:20]} | {format_yen(inv.get('total_amount', 0))}円 | {inv.get('billing_date', '')} | {status} |")
        lines.append(f"")

    # --- カテゴリA: 入金済み ---
    lines.append(f"## A. freee発行済み & 入金済み（{len(cat_a)}件）")
    lines.append(f"")
    if cat_a:
        for i, e in enumerate(cat_a, 1):
            lines.append(f"- {e['company'][:20]} / {e['case_name'][:30]} / {format_yen(e['display_amount'])}円")
    else:
        lines.append(f"該当なし（freee上で入金済みの請求書が0件のため）")
    lines.append(f"")

    # --- カテゴリE: CRM入金済み ---
    lines.append(f"## E. CRM入金済み（{len(cat_e)}件）")
    lines.append(f"")
    if cat_e:
        lines.append(f"CRM上で入金日が入力済みの案件（正常完了）。合計: {format_yen(sum(e['display_amount'] for e in cat_e))}円")
        lines.append(f"")
        lines.append(f"※ 詳細リストは省略（{len(cat_e)}件）")
    else:
        lines.append(f"該当なし（全181件で入金日が未入力）")
    lines.append(f"")

    # --- アクション提案 ---
    lines.append(f"---")
    lines.append(f"")
    lines.append(f"## 推奨アクション")
    lines.append(f"")

    if cat_b:
        overdue_items = [e for e in cat_b if e.get("overdue")]
        overdue_total = sum(e["display_amount"] for e in overdue_items)
        if overdue_items:
            lines.append(f"### 1. 支払期限超過の入金確認（最優先）")
            lines.append(f"- {len(overdue_items)}件、合計{format_yen(overdue_total)}円が支払期限超過")
            lines.append(f"- freee上で全件「未入金」ステータス → 実際の入金状況をfreee会計 or 銀行口座で確認")
            lines.append(f"- 入金済みならfreee請求書のステータスを「入金済み」に更新")
            lines.append(f"- 本当に未入金なら督促対応")
            lines.append(f"")

    if cat_c:
        lines.append(f"### 2. 未請求案件のfreee請求書発行（{len(cat_c)}件）")
        lines.append(f"- `python3 scripts/freee_invoice_creator.py --execute` で一括発行可能")
        lines.append(f"- 2023年の古い案件が含まれている点に注意（既に別途請求済みの可能性あり）")
        lines.append(f"")

    if cat_e and len(cat_e) == 0:
        lines.append(f"### 3. CRM入金日の一括入力")
        lines.append(f"- CRM受注台帳の入金日が全件未入力 → freee入金済み分をCRMに反映すべき")
        lines.append(f"- `python3 scripts/freee_payment_checker.py --execute` で自動反映可能")
        lines.append(f"")

    if unmatched_freee:
        lines.append(f"### {'4' if cat_c else '3'}. freee未マッチ請求書の確認")
        lines.append(f"- {len(unmatched_freee)}件のfreee請求書がCRMのどのレコードにも対応していない")
        lines.append(f"- CRM受注台帳への登録漏れ、または取引先名の不一致の可能性")
        lines.append(f"")

    report_text = "\n".join(lines)

    # ファイル出力
    output_path = OUTPUT_DIR / "freee_invoice_check_20260317.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    # JSON出力（詳細データ）
    json_path = SCRIPT_DIR / "data" / "freee_reconciliation_20260317.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "crm_total": len(crm_records),
                "freee_total": len(freee_invoices),
                "cat_a_invoiced_paid": len(cat_a),
                "cat_b_invoiced_unpaid": len(cat_b),
                "cat_c_unbilled": len(cat_c),
                "cat_d_preparing": len(cat_d),
                "cat_e_crm_paid": len(cat_e),
                "cat_f_other": len(cat_f),
                "freee_unmatched": len(unmatched_freee),
            },
            "cat_b_unpaid": cat_b,
            "cat_c_unbilled": cat_c,
            "cat_d_preparing": cat_d,
            "unmatched_freee": [
                {
                    "invoice_number": inv.get("invoice_number"),
                    "partner_name": inv.get("partner_name"),
                    "total_amount": inv.get("total_amount"),
                    "billing_date": inv.get("billing_date"),
                    "payment_status": inv.get("payment_status"),
                }
                for inv in unmatched_freee
            ],
        }, f, ensure_ascii=False, indent=2)

    print(f"\n  レポート: {output_path}")
    print(f"  詳細JSON: {json_path}")

    # コンソールサマリー
    print(f"\n{'='*70}")
    print(f"  突合結果サマリー")
    print(f"{'='*70}")
    print(f"  CRM受注台帳: {len(crm_records)}件")
    print(f"  freee請求書: {len(freee_invoices)}件")
    print(f"  ---")
    print(f"  A. freee発行済み & 入金済み:    {len(cat_a):>4}件")
    print(f"  B. freee発行済み & 未入金:      {len(cat_b):>4}件  ({format_yen(sum(e['display_amount'] for e in cat_b))}円)")
    overdue_items = [e for e in cat_b if e.get("overdue")]
    if overdue_items:
        print(f"     うち支払期限超過:            {len(overdue_items):>4}件  ({format_yen(sum(e['display_amount'] for e in overdue_items))}円)")
    print(f"  C. 未請求（freee未発行）:       {len(cat_c):>4}件  ({format_yen(sum(e['display_amount'] for e in cat_c))}円)")
    print(f"  D. 請求準備中:                  {len(cat_d):>4}件")
    print(f"  E. CRM入金済み:                 {len(cat_e):>4}件")
    print(f"  F. その他:                      {len(cat_f):>4}件")
    print(f"  ---")
    print(f"  freee側CRM未マッチ:             {len(unmatched_freee):>4}件")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
