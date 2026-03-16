#!/usr/bin/env python3
"""
freee入金確認 & CRM受注台帳自動更新スクリプト

freee請求書のpayment_statusを監視し、入金済みの請求書を
CRM受注台帳の「入金日」フィールドに自動反映する。

トリガー条件:
  - freee請求書がpayment_status="settled"（入金済み）
  - CRM受注台帳の該当レコードに入金日が未入力

Usage:
  python3 freee_payment_checker.py              # ドライラン（確認のみ）
  python3 freee_payment_checker.py --execute     # 本番実行（CRM更新）
  python3 freee_payment_checker.py --check-only  # 未入金一覧の確認のみ
"""

import json
import shutil
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

BACKUP_DIR = SCRIPT_DIR.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

FREEE_API_BASE = "https://api.freee.co.jp"
FREEE_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"

# CRM Base settings
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

# freee partner_id -> CRM取引先名の逆引き（freee_invoice_creator.pyのPARTNER_MAPの逆）
# ※ 完全な逆引きではなくfreee側のpartner_nameを使うため、不要


# ──────────────────────────────────────────────
# Config管理
# ──────────────────────────────────────────────
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config):
    backup = CONFIG_FILE.with_suffix(".json.bak")
    shutil.copy2(CONFIG_FILE, backup)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────
# freee API
# ──────────────────────────────────────────────
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
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Token refresh failed: {e.code}")
        sys.exit(1)
    config["freee"]["access_token"] = result["access_token"]
    config["freee"]["refresh_token"] = result["refresh_token"]
    save_config(config)
    return config


def freee_api(config, method, path, body=None, retry_auth=True, base=None):
    freee = config["freee"]
    api_base = base or FREEE_API_BASE
    url = f"{api_base}{path}"

    if body is not None:
        data = json.dumps(body).encode()
    else:
        data = None

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {freee['access_token']}")
    req.add_header("Accept", "application/json")
    if data:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode()), config
    except urllib.error.HTTPError as e:
        if e.code == 401 and retry_auth:
            config = refresh_token(config)
            return freee_api(config, method, path, body, retry_auth=False, base=base)
        body_text = e.read().decode()
        print(f"[ERROR] freee API {method} {path}: {e.code}")
        print(f"  {body_text[:500]}")
        raise


# ──────────────────────────────────────────────
# Lark API
# ──────────────────────────────────────────────
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
        try:
            with urllib.request.urlopen(req) as r:
                resp = json.loads(r.read())
                items = resp.get("data", {}).get("items", [])
                records.extend(items)
                if not resp.get("data", {}).get("has_more"):
                    break
                page_token = resp["data"].get("page_token")
        except Exception as e:
            print(f"[ERROR] Lark API: {e}")
            break
        time.sleep(0.3)
    return records


def lark_update_record(token, table_id, record_id, fields):
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return resp.get("code") == 0
    except Exception as e:
        print(f"  [ERROR] Lark update: {e}")
        return False


# ──────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────
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


def notify_lark(config, message):
    """Lark Webhook通知を送信"""
    webhook_url = config.get("notifications", {}).get("lark_webhook_url", "")
    if not webhook_url or webhook_url.startswith("${"):
        return

    body = json.dumps({
        "msg_type": "text",
        "content": {"text": message},
    }).encode()

    try:
        req = urllib.request.Request(
            webhook_url, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            pass
    except Exception as e:
        print(f"  [WARN] Lark通知失敗: {e}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def get_all_freee_invoices(config):
    """freee iv APIから全請求書を取得"""
    all_invoices = []
    page = 1
    seen_ids = set()
    while page <= 20:
        url = f"/iv/invoices?company_id={config['freee']['company_id']}&per_page=100&page={page}"
        try:
            data, config = freee_api(config, "GET", url, base=FREEE_API_BASE)
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
            print(f"  [ERROR] freee請求書取得: {e}")
            break
    return all_invoices, config


def match_invoice_to_crm(invoice, crm_records):
    """freee請求書とCRM受注台帳レコードのマッチング

    マッチ条件（優先度順）:
    1. 備考フィールドにfreee請求書番号が含まれる（書き戻し済み）
    2. 取引先名 + 金額の一致
    """
    inv_number = invoice.get("invoice_number", "")
    inv_partner = invoice.get("partner_name", "")
    inv_amount = invoice.get("total_amount", 0)
    inv_amount_excl = invoice.get("amount_excluding_tax", 0)

    candidates = []

    for rec in crm_records:
        fields = rec.get("fields", {})
        case_name = extract_text(fields.get("案件名", ""))
        company = extract_text(fields.get("取引先", ""))
        invoice_amount = fields.get("請求金額")
        order_amount = fields.get("受注金額")
        payment_date = fields.get("入金日")
        memo = extract_text(fields.get("備考", ""))

        # 既に入金日が入っていればスキップ
        if payment_date:
            continue

        # マッチ方法1: 備考にfreee請求書番号が含まれる（最高信頼度）
        if inv_number and inv_number in memo:
            return rec, 10  # 最高スコア

        # マッチ方法2: 取引先名 + 金額
        company_match = False
        if inv_partner and company:
            # 部分一致チェック
            if inv_partner in company or company in inv_partner:
                company_match = True
            # 正規化して比較
            inv_p_clean = inv_partner.replace("株式会社", "").replace("有限会社", "").strip()
            c_clean = company.replace("株式会社", "").replace("有限会社", "").strip()
            if inv_p_clean and c_clean and (inv_p_clean in c_clean or c_clean in inv_p_clean):
                company_match = True

        if not company_match:
            continue

        # 金額チェック
        try:
            crm_amount = int(float(extract_text(str(invoice_amount)))) if invoice_amount else 0
        except (ValueError, TypeError):
            crm_amount = 0

        try:
            crm_order = int(float(extract_text(str(order_amount)))) if order_amount else 0
        except (ValueError, TypeError):
            crm_order = 0

        amount_match = False
        score = 0

        if crm_amount > 0 and crm_amount in (inv_amount, inv_amount_excl):
            amount_match = True
            score = 5
        elif crm_order > 0 and crm_order in (inv_amount, inv_amount_excl):
            amount_match = True
            score = 4
        elif crm_amount > 0 and inv_amount > 0:
            # 10%以内の誤差を許容
            ratio = abs(crm_amount - inv_amount) / max(inv_amount, 1)
            if ratio < 0.10:
                amount_match = True
                score = 3

        if amount_match:
            candidates.append((rec, score))

    if candidates:
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0]

    return None, 0


def main():
    execute = "--execute" in sys.argv
    check_only = "--check-only" in sys.argv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print("  freee入金確認 & CRM受注台帳自動更新")
    print(f"  モード: {'本番実行' if execute else 'チェックのみ' if check_only else 'ドライラン'}")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    config = load_config()

    # 1. freee請求書一覧取得
    print("\n[1/4] freee請求書取得...")
    all_invoices, config = get_all_freee_invoices(config)
    print(f"  全請求書: {len(all_invoices)}件")

    # 入金済み / 未入金 に分類
    settled = [inv for inv in all_invoices if inv.get("payment_status") == "settled"]
    unsettled = [inv for inv in all_invoices if inv.get("payment_status") != "settled"]

    print(f"  入金済み: {len(settled)}件")
    print(f"  未入金: {len(unsettled)}件")

    # 2. CRM受注台帳取得
    print("\n[2/4] CRM受注台帳取得...")
    lark_token = lark_get_token(config)
    crm_records = lark_list_records(lark_token, ORDER_TABLE_ID)
    print(f"  全レコード: {len(crm_records)}件")

    # 入金日が未入力のレコードを抽出
    unpaid_crm = []
    for rec in crm_records:
        fields = rec.get("fields", {})
        if not fields.get("入金日"):
            unpaid_crm.append(rec)
    print(f"  入金日未入力: {len(unpaid_crm)}件")

    # 3. マッチング: freee入金済み請求書 vs CRM入金日未入力レコード
    print("\n[3/4] freee入金済み請求書 vs CRM入金未反映のマッチング...")

    updates = []  # (crm_record, freee_invoice, match_score)

    for inv in settled:
        matched_rec, score = match_invoice_to_crm(inv, unpaid_crm)
        if matched_rec and score >= 3:
            updates.append({
                "crm_record_id": matched_rec["record_id"],
                "crm_case_name": extract_text(matched_rec.get("fields", {}).get("案件名", "")),
                "crm_company": extract_text(matched_rec.get("fields", {}).get("取引先", "")),
                "freee_invoice_number": inv.get("invoice_number", ""),
                "freee_partner_name": inv.get("partner_name", ""),
                "freee_amount": inv.get("total_amount", 0),
                "freee_payment_date": inv.get("payment_date", ""),
                "match_score": score,
            })

    print(f"  入金反映候補: {len(updates)}件")

    if updates:
        print(f"\n  --- 入金反映候補 ---")
        total = 0
        for i, u in enumerate(updates, 1):
            total += u["freee_amount"]
            score_label = "確定" if u["match_score"] >= 5 else "高信頼" if u["match_score"] >= 4 else "要確認"
            print(f"  {i:3d}. {u['freee_partner_name'][:15]:15s} | {u['crm_case_name'][:30]:30s} | "
                  f"{format_yen(u['freee_amount']):>12}円 | 入金日: {u['freee_payment_date']} | {score_label}")
        print(f"\n  入金反映額合計: {format_yen(total)}円")

    # 未入金一覧（check-only時に表示）
    if unsettled:
        overdue = []
        today = date.today()
        for inv in unsettled:
            payment_date = inv.get("payment_date", "")
            if payment_date:
                try:
                    pd = date.fromisoformat(payment_date)
                    if pd < today:
                        overdue.append(inv)
                except (ValueError, TypeError):
                    pass

        if overdue:
            print(f"\n  [警告] 支払期限超過: {len(overdue)}件")
            overdue_total = 0
            for inv in overdue:
                amt = inv.get("total_amount", 0)
                overdue_total += amt
                print(f"    {inv.get('invoice_number', ''):>16} | {inv.get('partner_name', '')[:20]:20s} | "
                      f"{format_yen(amt):>12}円 | 期限: {inv.get('payment_date', '')}")
            print(f"    超過合計: {format_yen(overdue_total)}円")

    if check_only:
        print("\n[CHECK-ONLY] 確認完了。")
        return

    if not updates:
        print("\n  CRM更新対象の案件はありません。")
        return

    # バックアップ
    backup_path = BACKUP_DIR / f"{timestamp}_payment_check_candidates.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(updates, f, ensure_ascii=False, indent=2)
    print(f"\n  バックアップ: {backup_path}")

    if not execute:
        print("\n[DRY-RUN] CRM更新をスキップ。")
        print("  本番実行するには: python3 freee_payment_checker.py --execute")
        return

    # 4. CRM受注台帳の「入金日」を更新
    print("\n[4/4] CRM受注台帳更新...")
    success = 0
    fail = 0

    for u in updates:
        payment_date_str = u["freee_payment_date"]
        if not payment_date_str:
            print(f"  SKIP: {u['crm_case_name'][:30]} (入金日不明)")
            continue

        # Lark Baseの日付フィールドはミリ秒タイムスタンプ
        try:
            pd = date.fromisoformat(payment_date_str)
            ts_ms = int(datetime(pd.year, pd.month, pd.day).timestamp() * 1000)
        except (ValueError, TypeError):
            print(f"  SKIP: {u['crm_case_name'][:30]} (日付解析失敗: {payment_date_str})")
            continue

        ok = lark_update_record(
            lark_token, ORDER_TABLE_ID, u["crm_record_id"],
            {"入金日": ts_ms}
        )
        if ok:
            success += 1
            print(f"  OK: {u['crm_company'][:15]} / {u['crm_case_name'][:30]} <- 入金日: {payment_date_str}")
        else:
            fail += 1
            print(f"  NG: {u['crm_company'][:15]} / {u['crm_case_name'][:30]}")
        time.sleep(0.3)

    # ログ保存
    log_path = BACKUP_DIR / f"{timestamp}_payment_check_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "mode": "execute",
            "total": len(updates),
            "success": success,
            "fail": fail,
            "updates": updates,
        }, f, ensure_ascii=False, indent=2)

    # Lark通知
    if success > 0:
        notify_lines = [f"[freee入金確認] {success}件の入金をCRM受注台帳に反映しました:"]
        for u in updates:
            notify_lines.append(f"  - {u['crm_company'][:15]} / {format_yen(u['freee_amount'])}円 ({u['freee_payment_date']})")
        notify_lark(config, "\n".join(notify_lines))

    print(f"\n{'='*70}")
    print(f"  完了: {success}件成功 / {fail}件失敗")
    print(f"  ログ: {log_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
