#!/usr/bin/env python3
"""
CRM受注台帳 → freee請求書 自動生成スクリプト

CRM受注台帳で請求準備ができた案件を検出し、freee iv APIで請求書を自動作成する。

トリガー条件:
  - 請求金額が入力済み
  - 請求日が入力済み
  - 入金日が未入力（未請求 or 未入金）

Usage:
  python3 freee_invoice_creator.py              # ドライラン（プレビューのみ）
  python3 freee_invoice_creator.py --execute     # 本番実行（請求書作成）
  python3 freee_invoice_creator.py --check-only  # 対象案件の確認のみ
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
from calendar import monthrange

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
BACKUP_DIR = SCRIPT_DIR.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

FREEE_API_BASE = "https://api.freee.co.jp"
FREEE_IV_BASE = "https://api.freee.co.jp/iv"
FREEE_TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"

# CRM Base settings
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

# freee template
TEMPLATE_ID = 1302995

# 取引先名寄せマッピング: CRM取引先名(部分一致) → freee partner_id
PARTNER_MAP = {
    "東海工測": 26310451,
    "揖斐川工業": 54576784,
    "柴田工業": 97205265,
    "和合コンサルタント": 104112752,
    "大同マシナリー": 76059089,
    "山旺建設": 83413989,
    "空有限会社": 111977510,
    "空 小林": 111977510,
    "ダイシンコンサルタント": 84410120,
    "日本アート": 62306372,
    "日本工営都市空間": 69954027,
    "株式会社禅": 77975834,
    "ナカサアンドパートナーズ": 80331695,
    "OFFice Rinon": 80488809,
    "有限会社芳賀土建": 38239626,
    "大成建設": 40811012,
    "ヨンソー開発": 44996020,
    "EcoFlow": 48327412,
    "セキド": 49025967,
    "和建技術": 49444583,
    "大成機工": 49773908,
    "前田建設工業": 49804584,
    "五洋建設": 50491230,
    "中日本高速道路": 51961088,
    "日本ガイシ": 52219906,
    "中京電設": 53921964,
    "NUB PROJECT": 62136857,
    "NSPセントラル": 62447134,
    "富士物流": 62567923,
    "興永産業": 63338276,
    "アクアクリエイティブラボ": 63400164,
    "きずなう": 64432242,
    "王子製薬": 65240229,
    "リストインターナショナル": 65398035,
    "浜崎工業": 66033425,
    "アーバンプロジェクト": 66582908,
    "アクトリー": 66805391,
    "タカゼン": 67105423,
    "ユニファ": 67565131,
    "泉　直洋": 76209972,
    "マチスデザイン": 77645393,
    "カルチュア・コンビニエンス": 79457856,
    "ジッピープロダクション": 79963911,
    "ジャスト": 82104260,
    "Liberaware": 87203417,
    "中部EEN": 89955491,
    "シンエイライフ": 90829193,
    "イクシス": 90972628,
    "トラスコ中山": 91879170,
    "明和工業": 95573150,
    "アイダ設計": 95752597,
    "恒川建設": 97740473,
    "大王製紙": 103229273,
    "鴻池組": 103237533,
    "太平産業": 105832724,
    "東急建設": 106223942,
    "名邦テクノ": 106463520,
    "キナン": 110372903,
    "カギテック": 111991018,
    "ドットシンク": 113349116,
    "鳴子学区": 62573062,
    "オフィスリノン": 80488809,
    "Nacasa": 80331695,
}


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
        print(f"[ERROR] トークンリフレッシュ失敗: {e.code}")
        sys.exit(1)
    config["freee"]["access_token"] = result["access_token"]
    config["freee"]["refresh_token"] = result["refresh_token"]
    save_config(config)
    return config


def freee_api(config, method, path, body=None, retry_auth=True, base=None):
    """freee APIリクエスト"""
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
    """Larkタイムスタンプ（ミリ秒）をdate文字列に変換"""
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        return str(ts)
    except Exception:
        return None


def calc_payment_date(billing_date_str):
    """末締め翌15日の支払期限を計算"""
    bd = date.fromisoformat(billing_date_str)
    # 翌月15日
    if bd.month == 12:
        return date(bd.year + 1, 1, 15).isoformat()
    else:
        return date(bd.year, bd.month + 1, 15).isoformat()


def find_partner_id(company_name):
    """CRM取引先名からfreee partner_idを検索"""
    if not company_name:
        return None
    for key, pid in PARTNER_MAP.items():
        if key in company_name or company_name in key:
            return pid
    return None


def format_yen(amount):
    if amount is None:
        return "---"
    try:
        return f"{int(float(amount)):,}"
    except (ValueError, TypeError):
        return str(amount)


# ──────────────────────────────────────────────
# 通知
# ──────────────────────────────────────────────
def notify_unmatched_partners(config, candidates):
    """取引先未登録の候補をLark Webhookで通知"""
    unmatched_list = [c for c in candidates if not c["partner_id"]]
    if not unmatched_list:
        return

    webhook_url = config.get("notifications", {}).get("lark_webhook_url", "")
    if not webhook_url or webhook_url.startswith("${"):
        return  # Webhook未設定

    lines = ["[freee請求書] 取引先未登録の案件があります:"]
    for c in unmatched_list:
        lines.append(f"  - {c['company']} / {c['case_name'][:30]} / {format_yen(c['amount'])}円")
    lines.append("\nPARTNER_MAPへの追加が必要です。")

    body = json.dumps({
        "msg_type": "text",
        "content": {"text": "\n".join(lines)},
    }).encode()

    try:
        req = urllib.request.Request(
            webhook_url, data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            pass
        print("  取引先未登録の通知を送信しました。")
    except Exception as e:
        print(f"  [WARN] Lark通知送信失敗: {e}")


# ──────────────────────────────────────────────
# メイン処理
# ──────────────────────────────────────────────
def get_existing_freee_invoices(config):
    """freee iv APIから既存請求書を取得（重複チェック用）"""
    all_invoices = []
    page = 1
    seen_ids = set()
    while page <= 10:  # max 10 pages
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
        except Exception:
            break
    return all_invoices, config


def check_duplicate(candidate, existing_invoices):
    """既存freee請求書との重複チェック
    partner_id + 金額 + 請求日（30日以内）で判定。
    同一取引先に同額の別案件がある場合の誤判定を防止する。
    Returns: 重複する請求書番号 or None
    """
    for inv in existing_invoices:
        # partner_id一致が前提
        if inv.get("partner_id") != candidate["partner_id"]:
            continue

        # 金額一致チェック（税込 or 税抜）
        amount_match = False
        if inv.get("total_amount") == candidate["amount"]:
            amount_match = True
        elif inv.get("amount_excluding_tax") == candidate["amount"]:
            amount_match = True

        if not amount_match:
            continue

        # 請求日が近い場合のみ重複とみなす（30日以内）
        inv_billing = inv.get("billing_date", "")
        if inv_billing and candidate.get("billing_date"):
            try:
                inv_date = date.fromisoformat(inv_billing)
                cand_date = date.fromisoformat(candidate["billing_date"])
                if abs((inv_date - cand_date).days) > 30:
                    continue  # 請求日が30日以上離れていれば別案件
            except (ValueError, TypeError):
                pass  # 日付解析失敗時は金額一致のみで判定

        return inv.get("invoice_number")
    return None


def find_invoice_candidates(records):
    """請求書作成候補を抽出"""
    candidates = []
    for rec in records:
        fields = rec.get("fields", {})
        case_name = extract_text(fields.get("案件名", ""))
        company = extract_text(fields.get("取引先", ""))
        invoice_amount = fields.get("請求金額")
        billing_date = fields.get("請求日")
        payment_date = fields.get("入金日")
        order_amount = fields.get("受注金額")

        # 請求金額が必須
        if not invoice_amount and not order_amount:
            continue

        # 請求日が必須
        if not billing_date:
            continue

        # 入金日が入っていたらスキップ（入金済み）
        if payment_date:
            continue

        amount = invoice_amount or order_amount
        try:
            amount_val = int(float(extract_text(str(amount))))
        except (ValueError, TypeError):
            continue

        if amount_val <= 0:
            continue

        billing_date_str = ts_to_date(billing_date)
        if not billing_date_str:
            continue

        partner_id = find_partner_id(company)

        candidates.append({
            "record_id": rec["record_id"],
            "case_name": case_name,
            "company": company,
            "amount": amount_val,
            "billing_date": billing_date_str,
            "partner_id": partner_id,
            "service_type": extract_text(fields.get("サービス種別", "")),
        })

    return candidates


def create_freee_invoice(config, candidate):
    """freee iv APIで請求書を作成"""
    if not candidate["partner_id"]:
        return None, config, "取引先マッチングなし"

    payment_date = calc_payment_date(candidate["billing_date"])

    invoice_body = {
        "company_id": config["freee"]["company_id"],
        "template_id": TEMPLATE_ID,
        "billing_date": candidate["billing_date"],
        "payment_date": payment_date,
        "partner_id": candidate["partner_id"],
        "partner_title": "御中",
        "tax_entry_method": "out",
        "tax_fraction": "omit",
        "withholding_tax_entry_method": "out",
        "subject": candidate["case_name"][:50] if candidate["case_name"] else "",
        "lines": [
            {
                "type": "item",
                "description": candidate["case_name"] or candidate["service_type"] or "業務委託",
                "quantity": 1,
                "unit_price": f"{candidate['amount']}.0",
                "tax_rate": 10,
            }
        ],
    }

    try:
        result, config = freee_api(
            config, "POST", "/iv/invoices",
            body=invoice_body, base=FREEE_API_BASE,
        )
        invoice = result.get("invoice", {})
        return invoice, config, None
    except Exception as e:
        return None, config, str(e)


def main():
    execute = "--execute" in sys.argv
    check_only = "--check-only" in sys.argv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 70)
    print("  CRM受注台帳 → freee請求書 自動生成")
    print(f"  モード: {'本番実行' if execute else 'チェックのみ' if check_only else 'ドライラン'}")
    print(f"  実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    config = load_config()

    # 1. Lark CRM受注台帳を取得
    print("\n[1/5] CRM受注台帳取得...")
    lark_token = lark_get_token(config)
    all_records = lark_list_records(lark_token, ORDER_TABLE_ID)
    print(f"  全レコード: {len(all_records)}件")

    # 2. 請求書作成候補を抽出
    print("\n[2/5] 請求書作成候補の抽出...")
    candidates = find_invoice_candidates(all_records)
    print(f"  候補: {len(candidates)}件")

    if not candidates:
        print("\n  請求書作成対象の案件はありません。")
        print("  条件: 請求金額あり + 請求日あり + 入金日なし")
        return

    # 2.5. 既存freee請求書と重複チェック
    print("\n[2.5/5] 既存freee請求書との重複チェック...")
    existing_invoices, config = get_existing_freee_invoices(config)
    print(f"  既存請求書: {len(existing_invoices)}件")

    new_candidates = []
    dup_count = 0
    for c in candidates:
        dup_inv = check_duplicate(c, existing_invoices)
        if dup_inv:
            print(f"  重複: {c['company'][:15]} / {format_yen(c['amount'])}円 → 既存 {dup_inv}")
            dup_count += 1
        else:
            new_candidates.append(c)

    if dup_count:
        print(f"  {dup_count}件の重複を除外")
    candidates = new_candidates

    if not candidates:
        print("\n  重複チェック後、新規作成対象の案件はありません。")
        return

    # 候補一覧表示
    print(f"\n  --- 新規作成候補 ({len(candidates)}件) ---")
    total_amount = 0
    matched = 0
    unmatched = 0
    for i, c in enumerate(candidates, 1):
        partner_status = "OK" if c["partner_id"] else "取引先不明"
        if c["partner_id"]:
            matched += 1
        else:
            unmatched += 1
        total_amount += c["amount"]
        print(f"  {i:3d}. {c['company'][:15]:15s} | {c['case_name'][:30]:30s} | "
              f"{format_yen(c['amount']):>12}円 | {c['billing_date']} | {partner_status}")

    print(f"\n  合計: {format_yen(total_amount)}円")
    print(f"  取引先マッチ: {matched}件 / 未マッチ: {unmatched}件")

    # 取引先未登録の通知
    if unmatched > 0:
        notify_unmatched_partners(config, candidates)

    if check_only:
        print("\n[CHECK-ONLY] 候補確認完了。")
        return

    # 3. バックアップ
    print("\n[3/5] バックアップ...")
    backup_path = BACKUP_DIR / f"{timestamp}_invoice_create_candidates.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    print(f"  保存: {backup_path}")

    if not execute:
        print("\n[DRY-RUN] 請求書作成をスキップ。")
        print("  本番実行するには: python3 freee_invoice_creator.py --execute")
        return

    # 4. freee請求書作成
    print("\n[4/5] freee請求書作成...")
    results = []
    success = 0
    fail = 0
    skip = 0

    for i, c in enumerate(candidates, 1):
        if not c["partner_id"]:
            print(f"  {i:3d}. SKIP (取引先不明): {c['company']} / {c['case_name'][:30]}")
            skip += 1
            results.append({"candidate": c, "status": "skip", "reason": "取引先不明"})
            continue

        invoice, config, error = create_freee_invoice(config, c)
        if invoice:
            inv_num = invoice.get("invoice_number", "N/A")
            inv_id = invoice.get("id", "N/A")
            print(f"  {i:3d}. OK ({inv_num}): {c['company']} / {c['case_name'][:30]} / {format_yen(c['amount'])}円")
            success += 1
            results.append({
                "candidate": c,
                "status": "success",
                "invoice_number": inv_num,
                "invoice_id": inv_id,
            })
        else:
            print(f"  {i:3d}. FAIL: {c['company']} / {c['case_name'][:30]} — {error}")
            fail += 1
            results.append({"candidate": c, "status": "fail", "error": error})

        time.sleep(0.5)  # Rate limit

    # 5. CRM受注台帳にfreee請求書番号を書き戻し（既存備考を保持）
    print("\n[5/5] CRM受注台帳へ請求書番号を書き戻し...")
    # record_id -> 既存備考値のマップを構築
    record_memo_map = {}
    for rec in all_records:
        rid = rec.get("record_id")
        memo_val = extract_text(rec.get("fields", {}).get("備考", ""))
        record_memo_map[rid] = memo_val

    writeback_count = 0
    for r in results:
        if r["status"] == "success" and r.get("invoice_number"):
            record_id = r["candidate"]["record_id"]
            inv_num = r["invoice_number"]
            new_memo = f"freee請求書: {inv_num}"
            existing_memo = record_memo_map.get(record_id, "").strip()
            if existing_memo:
                # 既存備考に同じ請求書番号が含まれていたらスキップ
                if inv_num in existing_memo:
                    print(f"  SKIP: {record_id} (既に記載済み: {inv_num})")
                    writeback_count += 1
                    continue
                # 既存備考の末尾に追記
                new_memo = f"{existing_memo}\n{new_memo}"
            ok = lark_update_record(
                lark_token, ORDER_TABLE_ID, record_id,
                {"備考": new_memo}
            )
            if ok:
                writeback_count += 1
                print(f"  OK: {record_id} <- {inv_num}")
            else:
                print(f"  NG: {record_id} <- {inv_num}")
            time.sleep(0.3)
    print(f"  書き戻し完了: {writeback_count}件")

    # ログ保存
    log_path = BACKUP_DIR / f"{timestamp}_invoice_create_log.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": timestamp,
            "mode": "execute",
            "total": len(candidates),
            "success": success,
            "fail": fail,
            "skip": skip,
            "results": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*70}")
    print(f"  完了: {success}件成功 / {fail}件失敗 / {skip}件スキップ")
    print(f"  ログ: {log_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
