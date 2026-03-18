#!/usr/bin/env python3
"""
freee請求書ベースの現場名をCRM受注台帳に反映するスクリプト

site_name_correction_list_v2.md カテゴリA（24件）を対象に、
受注台帳の「案件名」フィールドをfreee請求書の現場名で更新する。

Usage:
  python3 freee_site_name_updater.py              # 実行
  python3 freee_site_name_updater.py --dry-run     # プレビューのみ
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── Config ──
SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

# ── カテゴリA: freee現場名特定済み 24件 ──
# (受注台帳の案件名, freee現場名) のマッピング
# 同じ案件名に複数のfreee請求書がある場合は、案件名+取引先で特定
CATEGORY_A = [
    {
        "id": 1,
        "current_name": "日本アート_東海市分譲地",
        "company": "日本アート",
        "freee_invoice": "INV-0000000003",
        "freee_site_name": "瑞浪市　分譲地撮影（UAV）",
        "amount": 160600,
    },
    {
        "id": 2,
        "current_name": "揖斐川工業株式会社_名古屋埠頭",
        "company": "揖斐川工業株式会社",
        "freee_invoice": "INV-0000000007",
        "freee_site_name": "名古屋埠頭様　３６０°動画撮影　附帯業務",
        "amount": 110000,
    },
    {
        "id": 3,
        "current_name": "2024年4月15日 支払通知書 ご送付",
        "company": "東海工測",
        "freee_invoice": "INV-0000000009",
        "freee_site_name": "㈱奥村組　掛川市逆川　UAV三次元計測（土量計測）",
        "amount": 343816,
    },
    {
        "id": 4,
        "current_name": "揖斐川工業株式会社_名古屋埠頭",
        "company": "揖斐川工業株式会社",
        "freee_invoice": "INV-0000000011",
        "freee_site_name": "高高度海上空撮（静止画）",
        "amount": 82500,
    },
    {
        "id": 5,
        "current_name": "揖斐川工業株式会社_名古屋埠頭",
        "company": "揖斐川工業株式会社",
        "freee_invoice": "INV-0000000010",
        "freee_site_name": "360度VR　ドローン撮影・編集",
        "amount": 805750,
    },
    {
        "id": 6,
        "current_name": "6月5日ドローン撮影 御請求書につきまして",
        "company": "東海工測",
        "freee_invoice": "INV-0000000019",
        "freee_site_name": "土量計測",
        "amount": 983835,
    },
    {
        "id": 7,
        "current_name": "揖斐川工業株式会社_名古屋埠頭",
        "company": "揖斐川工業株式会社",
        "freee_invoice": "INV-0000000020",
        "freee_site_name": "名古屋埠頭様　動画　追加編集業務",
        "amount": 165000,
    },
    {
        "id": 8,
        "current_name": "山旺建設　株式会社　豊明支店_ロピア 半田店",
        "company": "山旺建設",
        "freee_invoice": "INV-0000000022",
        "freee_site_name": "ロピア半田店　静止画空撮",
        "amount": 76230,
    },
    {
        "id": 9,
        "current_name": "ダイシンコンサルタント(株)　田口_中津川　4箇所の河川",
        "company": "ダイシンコンサルタント",
        "freee_invoice": "INV-0000000024",
        "freee_site_name": "見積費用請求（3件分）",
        "amount": 423802,
    },
    {
        "id": 10,
        "current_name": "大同マシナリー株式会社_大同特殊鋼(株) 星崎工場 3次元計測",
        "company": "大同マシナリー株式会社",
        "freee_invoice": "INV-0000000028",
        "freee_site_name": "建屋　内外部　３次元計測",
        "amount": 2706000,
    },
    {
        "id": 11,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000038",
        "freee_site_name": "UAV空撮　静止画　ダイジェット工業株式会社　三重事業所　工具工場",
        "amount": 82500,
    },
    {
        "id": 12,
        "current_name": "大同マシナリー株式会社_大同特殊鋼(株) 星崎工場 3次元計測",
        "company": "大同マシナリー株式会社",
        "freee_invoice": "INV-0000000041",
        "freee_site_name": "大同特殊鋼　星崎工場　3次元計測",
        "amount": 1454750,
    },
    {
        "id": 13,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000045",
        "freee_site_name": "UAV空撮　静止画　ヒガシ２１",
        "amount": 102850,
    },
    {
        "id": 14,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000046",
        "freee_site_name": "UAV空撮　静止画　松川レピヤン 第3工場",
        "amount": 126500,
    },
    {
        "id": 15,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000047",
        "freee_site_name": "UAV空撮　静止画　水菱プラスチック(株) 吉備工場",
        "amount": 132000,
    },
    {
        "id": 16,
        "current_name": "山旺建設　株式会社　豊明支店_ロピア 半田店",
        "company": "山旺建設",
        "freee_invoice": "INV-0000000049",
        "freee_site_name": "杉国工業株式会社　本社工場　静止画空撮",
        "amount": 70950,
    },
    {
        "id": 17,
        "current_name": "2025年8月15日 支払通知書のご送付",
        "company": "東海工測",
        "freee_invoice": "INV-0000000050",
        "freee_site_name": "３次元データ測量",
        "amount": 692242,
    },
    {
        "id": 18,
        "current_name": "営業代行",
        "company": "東海工測",
        "freee_invoice": "INV-0000000051",
        "freee_site_name": "UAV土量計測",
        "amount": 418770,
    },
    {
        "id": 19,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000052",
        "freee_site_name": "UAV空撮　静止画　ＮＴＮ（株）精密樹脂製作所",
        "amount": 108900,
    },
    {
        "id": 20,
        "current_name": "柴田工業株式会社_穴太970",
        "company": "柴田工業株式会社",
        "freee_invoice": "INV-0000000053",
        "freee_site_name": "UAV空撮　静止画　NTN磐田製作所 CVJ工場　他　近接３工場",
        "amount": 148500,
    },
    {
        "id": 21,
        "current_name": "株式会社和合コンサルタント_松阪・尾鷲・熊野建設事務所管内 3次元点群",
        "company": "株式会社和合コンサルタント",
        "freee_invoice": "INV-0000000055",
        "freee_site_name": "松阪・尾鷲・熊野建設事務所管内 3次元点群測量業務　出来高請求（2026年1月分）",
        "amount": 4106080,
    },
    {
        "id": 22,
        "current_name": "株式会社和合コンサルタント_松阪・尾鷲・熊野建設事務所管内 3次元点群",
        "company": "株式会社和合コンサルタント",
        "freee_invoice": "INV-0000000056",
        "freee_site_name": "松阪・尾鷲・熊野建設事務所管内 3次元点群測量業務　出来高請求（2026年1月分）",
        "amount": 3960000,
    },
    {
        "id": 23,
        "current_name": "昭和区広路町マンション眺望撮影　ロケハン・測量・RTK運用検証実施分",
        "company": "空 小林",
        "freee_invoice": "INV-0000000057",
        "freee_site_name": "昭和区広路町マンション眺望撮影　ロケハン・測量・RTK運用検証実施分",
        "amount": 478500,
    },
    {
        "id": 24,
        "current_name": "株式会社和合コンサルタント_松阪・尾鷲・熊野建設事務所管内 3次元点群",
        "company": "株式会社和合コンサルタント",
        "freee_invoice": "INV-0000000058",
        "freee_site_name": "松阪・尾鷲・熊野建設事務所管内 3次元点群測量業務　最終精算分",
        "amount": 990000,
    },
]


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
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
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
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
            print(f"Lark API error: {e}")
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
            if resp.get("code") != 0:
                print(f"  Update error: {resp.get('msg', 'unknown')} (record: {record_id})")
                return False
            return True
    except Exception as e:
        print(f"  Update exception: {e} (record: {record_id})")
        return False


def extract_text(value):
    """Larkフィールド値からテキスト抽出"""
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


def match_record_to_freee(record, freee_entries):
    """受注台帳レコードとfreeeエントリのマッチング

    マッチ条件:
    1. 案件名の部分一致
    2. 金額の一致（請求金額 or 受注金額）
    3. 取引先名の部分一致
    """
    fields = record.get("fields", {})
    case_name = extract_text(fields.get("案件名", ""))
    company = extract_text(fields.get("取引先", ""))
    invoice_amount = extract_text(fields.get("請求金額", ""))
    order_amount = extract_text(fields.get("受注金額", ""))

    matches = []
    for entry in freee_entries:
        # 案件名一致チェック
        name_match = False
        if entry["current_name"] and entry["current_name"] in case_name:
            name_match = True
        elif case_name and case_name in entry["current_name"]:
            name_match = True

        if not name_match:
            continue

        # 金額一致チェック（追加の識別に使用）
        amount_match = False
        try:
            inv_amt = int(invoice_amount) if invoice_amount else 0
            ord_amt = int(order_amount) if order_amount else 0
            freee_amt_excl = int(entry["amount"] / 1.1)  # 税抜概算
            if entry["amount"] in (inv_amt, ord_amt):
                amount_match = True
            elif freee_amt_excl in (inv_amt, ord_amt):
                amount_match = True
            # 10%以内の誤差も許容
            elif inv_amt > 0 and abs(inv_amt - entry["amount"]) / entry["amount"] < 0.15:
                amount_match = True
            elif ord_amt > 0 and abs(ord_amt - entry["amount"]) / entry["amount"] < 0.15:
                amount_match = True
        except (ValueError, ZeroDivisionError):
            pass

        # 取引先一致チェック
        company_match = False
        if entry["company"] and entry["company"] in company:
            company_match = True
        elif company and company in entry["company"]:
            company_match = True

        if name_match:
            score = 1
            if amount_match:
                score += 2
            if company_match:
                score += 1
            matches.append((entry, score))

    if not matches:
        return None
    # 最高スコアを返す
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[0][0]


def main():
    dry_run = "--dry-run" in sys.argv
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("freee請求書 現場名 → CRM受注台帳 更新")
    print(f"対象: カテゴリA {len(CATEGORY_A)}件")
    print(f"モード: {'DRY-RUN' if dry_run else '本番更新'}")
    print("=" * 60)

    # 1. Larkトークン取得
    print("\n[1/4] Lark認証...")
    token = lark_get_token()
    print("  OK")

    # 2. 受注台帳の全レコード取得
    print("\n[2/4] 受注台帳レコード取得...")
    all_records = lark_list_records(token, ORDER_TABLE_ID)
    print(f"  {len(all_records)}件取得")

    # 3. マッチングと更新準備
    print("\n[3/4] レコードマッチング...")

    # 同じ案件名が複数あるケースに対応するため、
    # freeeエントリごとにマッチしたレコードを記録して重複使用を防ぐ
    used_record_ids = set()
    updates = []  # (record_id, old_fields, new_case_name, freee_entry)
    unmatched = []

    # 直接マッピング: 前回更新で名前が変わっているケースや、
    # CRM上の案件名がfreeeと異なるケースに対応するため、
    # 請求金額＋取引先名で特定するハードコードマッピング
    AMOUNT_BASED_MAP = {
        # (freee_id, amount) -> record_id (Larkの実データから特定)
        # 揖斐川: INV-10 805,750 = inv=1024000の揖斐川レコードは既にマッチ
        #   INV-20 165,000 → 揖斐川の別レコードが必要だが存在しない（2件しかない）
        # 柴田: 金額でマッチ
        # 山旺: 金額でマッチ
        # 和合: 金額でマッチ
    }

    for entry in CATEGORY_A:
        # 候補レコードを名前一致 + 金額一致 + 取引先一致で探す
        candidates = []
        for rec in all_records:
            if rec["record_id"] in used_record_ids:
                continue
            fields = rec.get("fields", {})
            case_name = extract_text(fields.get("案件名", ""))
            company = extract_text(fields.get("取引先", ""))
            invoice_amount = extract_text(fields.get("請求金額", ""))
            order_amount = extract_text(fields.get("受注金額", ""))

            try:
                inv_amt = int(float(invoice_amount)) if invoice_amount else 0
                ord_amt = int(float(order_amount)) if order_amount else 0
            except ValueError:
                inv_amt = 0
                ord_amt = 0

            # 取引先一致チェック
            company_match = False
            if entry["company"] and entry["company"] in company:
                company_match = True
            elif company and company in entry["company"]:
                company_match = True

            # 案件名一致チェック
            name_match = False
            if entry["current_name"] and entry["current_name"] in case_name:
                name_match = True
            elif case_name and len(case_name) > 3 and case_name in entry["current_name"]:
                name_match = True

            # 金額完全一致チェック
            amount_exact = entry["amount"] in (inv_amt, ord_amt)

            # 金額近似一致チェック（15%以内）
            amount_close = False
            if not amount_exact and inv_amt > 0:
                if abs(inv_amt - entry["amount"]) / max(entry["amount"], 1) < 0.15:
                    amount_close = True

            # マッチ条件:
            # 1) 案件名一致（取引先任意）
            # 2) 取引先一致 + 金額完全一致（案件名不要）
            if not name_match and not (company_match and amount_exact):
                continue

            # スコア計算
            score = 0
            if name_match:
                score += 2
            if company_match:
                score += 1
            if amount_exact:
                score += 4
            elif amount_close:
                score += 2

            candidates.append((rec, score))

        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_rec = candidates[0][0]
            used_record_ids.add(best_rec["record_id"])

            # 新しい案件名を生成: 取引先名_freee現場名
            company_prefix = entry["company"]
            freee_name = entry["freee_site_name"]
            new_case_name = f"{company_prefix}_{freee_name}"

            updates.append({
                "record_id": best_rec["record_id"],
                "old_fields": best_rec.get("fields", {}),
                "old_case_name": extract_text(best_rec.get("fields", {}).get("案件名", "")),
                "new_case_name": new_case_name,
                "freee_entry": entry,
                "match_score": candidates[0][1],
            })
            print(f"  #{entry['id']:2d} MATCH (score={candidates[0][1]}): {extract_text(best_rec.get('fields', {}).get('案件名', ''))} -> {new_case_name}")
        else:
            unmatched.append(entry)
            print(f"  #{entry['id']:2d} UNMATCHED: {entry['current_name']}")

    print(f"\n  マッチ: {len(updates)}件 / 未マッチ: {len(unmatched)}件")

    if unmatched:
        print("\n  未マッチ一覧:")
        for e in unmatched:
            print(f"    #{e['id']}: {e['current_name']} ({e['company']})")

    # 4. バックアップ & 更新
    print("\n[4/4] バックアップ & 更新...")

    # バックアップ保存
    backup_data = []
    for u in updates:
        backup_data.append({
            "record_id": u["record_id"],
            "old_case_name": u["old_case_name"],
            "new_case_name": u["new_case_name"],
            "freee_invoice": u["freee_entry"]["freee_invoice"],
            "freee_amount": u["freee_entry"]["amount"],
            "match_score": u["match_score"],
            "old_fields": {k: extract_text(v) for k, v in u["old_fields"].items()
                          if k in ("案件名", "取引先", "受注金額", "請求金額", "サービス種別", "業種")},
        })

    backup_path = BACKUP_DIR / "20260315_freee_site_update_backup.json"
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup_data, f, ensure_ascii=False, indent=2)
    print(f"  バックアップ保存: {backup_path}")

    if dry_run:
        print("\n[DRY-RUN] 更新プレビュー:")
        for u in updates:
            print(f"  {u['record_id']}: {u['old_case_name']} -> {u['new_case_name']}")
        print(f"\n[DRY-RUN] 完了。{len(updates)}件の更新候補。")
        return

    # 本番更新
    success = 0
    fail = 0
    log_lines = [f"freee Site Name Update Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]

    for u in updates:
        ok = lark_update_record(token, ORDER_TABLE_ID, u["record_id"],
                                {"案件名": u["new_case_name"]})
        if ok:
            success += 1
            log_lines.append(f"OK  {u['record_id']} | {u['old_case_name']} -> {u['new_case_name']}")
            print(f"  OK: {u['old_case_name']} -> {u['new_case_name']}")
        else:
            fail += 1
            log_lines.append(f"NG  {u['record_id']} | {u['old_case_name']} -> {u['new_case_name']}")
            print(f"  NG: {u['old_case_name']}")
        time.sleep(0.3)

    log_lines.insert(1, f"Total: {success} success, {fail} fail\n")

    # ログ保存
    log_path = BACKUP_DIR / "20260315_freee_site_update_log.txt"
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
    print(f"\n  ログ保存: {log_path}")

    print(f"\n完了: {success}件成功 / {fail}件失敗")


if __name__ == "__main__":
    main()
