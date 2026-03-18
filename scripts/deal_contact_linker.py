#!/usr/bin/env python3
"""
商談-連絡先 自動リンク修復スクリプト

連絡先リンクが空の商談に対して、取引先名で連絡先テーブルを検索し、
マッチした連絡先をリンクとして設定する。

Usage:
  python3 deal_contact_linker.py --dry-run    # 修復対象を表示（変更なし）
  python3 deal_contact_linker.py --execute    # 本番実行（リンク設定）
  python3 deal_contact_linker.py --stats      # 統計情報のみ表示
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
SNAPSHOT_DIR = SCRIPT_DIR / "snapshots"
SNAPSHOT_DIR.mkdir(exist_ok=True)

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"


def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    if not body:
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError) as e:
                print(f"[WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if result is None:
            print(f"[ERROR] Failed to fetch records for table {table_id}")
            break
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def update_record(token, table_id, record_id, fields):
    """Lark Base レコードを更新"""
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("code", -1) == 0
    except urllib.error.HTTPError as e:
        print(f"  [ERROR] Update failed: {e.code} {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  [ERROR] Update failed: {e}")
        return False


def normalize_company(name):
    """会社名を正規化"""
    if not name:
        return ""
    normalized = re.sub(r'(株式会社|有限会社|合同会社|一般社団法人|公益社団法人|（株）|\(株\))', '', name)
    normalized = re.sub(r'[\s\u3000]+', '', normalized)
    return normalized.strip()


def company_match(name_a, name_b):
    """会社名の柔軟マッチング（双方向部分一致、最低2文字以上で部分一致）"""
    if not name_a or not name_b:
        return False
    if name_a == name_b:
        return True
    if len(name_a) >= 2 and name_a in name_b:
        return True
    if len(name_b) >= 2 and name_b in name_a:
        return True
    norm_a = normalize_company(name_a)
    norm_b = normalize_company(name_b)
    if not norm_a or not norm_b:
        return False
    if norm_a == norm_b:
        return True
    if len(norm_a) >= 2 and norm_a in norm_b:
        return True
    if len(norm_b) >= 2 and norm_b in norm_a:
        return True
    return False


def get_deal_name(fields):
    """商談名を取得"""
    deal_name_raw = fields.get("商談名", "")
    if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
        deal_name = deal_name_raw[0].get("text", "") or ""
    else:
        deal_name = str(deal_name_raw or "")
    if not deal_name:
        deal_name = str(fields.get("新規取引先名", "") or "")
    if not deal_name:
        account_links = fields.get("取引先", [])
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    text_arr = link.get("text_arr", [])
                    if text_arr:
                        deal_name = str(text_arr[0])
                        break
                    text = link.get("text", "")
                    if text:
                        deal_name = str(text)
                        break
    return deal_name or "(名前なし)"


def get_account_name(fields, accounts):
    """商談フィールドから取引先名を取得"""
    account_links = fields.get("取引先", [])
    if isinstance(account_links, list):
        for link in account_links:
            if isinstance(link, dict):
                rid = link.get("record_id", "")
                for a in accounts:
                    if a.get("record_id") == rid:
                        return str(a.get("fields", {}).get("会社名", "") or "")
    # 新規取引先名フィールドもチェック
    return str(fields.get("新規取引先名", "") or "")


def find_matching_contacts(account_name, deal_name, contacts):
    """取引先名・商談名で連絡先を検索。メールアドレスがある連絡先のみ返す"""
    matches = []

    for c in contacts:
        cf = c.get("fields", {})
        email = str(cf.get("メールアドレス", "") or "")
        if not email or "@" not in email:
            continue

        company = str(cf.get("会社名", "") or "")

        # 取引先名でマッチ
        if account_name and company_match(account_name, company):
            matches.append({
                "record_id": c.get("record_id", ""),
                "name": str(cf.get("氏名", "") or ""),
                "company": company,
                "email": email,
                "match_type": "account_name",
            })
            continue

        # 商談名でマッチ
        if deal_name and company and company_match(company, deal_name):
            matches.append({
                "record_id": c.get("record_id", ""),
                "name": str(cf.get("氏名", "") or ""),
                "company": company,
                "email": email,
                "match_type": "deal_name",
            })

    return matches


def main():
    args = sys.argv[1:]

    if not args or "--help" in args:
        print(__doc__)
        return

    dry_run = "--dry-run" in args
    execute = "--execute" in args
    stats_only = "--stats" in args

    if not dry_run and not execute and not stats_only:
        print("--dry-run, --execute, または --stats を指定してください")
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 商談-連絡先リンク修復{'（ドライラン）' if dry_run else ''}")
    print()

    token = lark_get_token()

    print("データ取得中...")
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    print(f"商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")
    print()

    # 連絡先リンクが空の商談を特定
    no_contact_deals = []
    has_contact_deals = 0

    for rec in deals:
        fields = rec.get("fields", {})
        contact_links = fields.get("主連絡先", [])
        has_contact = False
        if isinstance(contact_links, list) and contact_links:
            for link in contact_links:
                if isinstance(link, dict) and link.get("record_id"):
                    has_contact = True
                    break

        if has_contact:
            has_contact_deals += 1
        else:
            no_contact_deals.append(rec)

    print(f"連絡先リンクあり: {has_contact_deals}件")
    print(f"連絡先リンクなし: {len(no_contact_deals)}件")
    print()

    if stats_only:
        # 詳細統計
        linkable = 0
        for rec in no_contact_deals:
            fields = rec.get("fields", {})
            account_name = get_account_name(fields, accounts)
            deal_name = get_deal_name(fields)
            matches = find_matching_contacts(account_name, deal_name, contacts)
            if matches:
                linkable += 1
        print(f"リンク修復可能: {linkable}件 / {len(no_contact_deals)}件")
        return

    # スナップショット保存
    snapshot_file = SNAPSHOT_DIR / f"deal_contact_link_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    snapshot_data = []
    for rec in no_contact_deals:
        snapshot_data.append({
            "record_id": rec.get("record_id", ""),
            "deal_name": get_deal_name(rec.get("fields", {})),
            "contact_links_before": rec.get("fields", {}).get("主連絡先", []),
        })
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_data, f, ensure_ascii=False, indent=2)
    print(f"スナップショット保存: {snapshot_file}")
    print()

    # 修復処理
    linked = 0
    skipped = 0
    failed = 0

    for rec in no_contact_deals:
        rid = rec.get("record_id", "")
        fields = rec.get("fields", {})
        deal_name = get_deal_name(fields)
        account_name = get_account_name(fields, accounts)

        matches = find_matching_contacts(account_name, deal_name, contacts)
        if not matches:
            skipped += 1
            continue

        # 最初のマッチを使用（複数ある場合は全て表示）
        best = matches[0]
        contact_ids = [m["record_id"] for m in matches]

        if dry_run:
            match_info = ", ".join(f"{m['name']}({m['email']}, {m['match_type']})" for m in matches)
            print(f"  [修復] {deal_name} → {match_info}")
            linked += 1
        elif execute:
            print(f"  [修復] {deal_name} → {best['name']}({best['email']})", end="")
            # 連絡先リンクフィールドを更新
            success = update_record(token, TABLE_DEALS, rid, {
                "主連絡先": contact_ids
            })
            if success:
                print(" ... OK")
                linked += 1
            else:
                print(" ... FAILED")
                failed += 1
            time.sleep(0.5)  # API rate limit

    print()
    print(f"===== 結果 =====")
    print(f"対象: {len(no_contact_deals)}件")
    print(f"リンク設定{'予定' if dry_run else '完了'}: {linked}件")
    print(f"連絡先なし（スキップ）: {skipped}件")
    if failed:
        print(f"失敗: {failed}件")
    print(f"スナップショット: {snapshot_file}")


if __name__ == "__main__":
    main()
