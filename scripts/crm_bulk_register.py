#!/usr/bin/env python3
"""
Spark未登録取引先・連絡先 CRM一括登録スクリプト

Usage:
  python3 crm_bulk_register.py --dry-run    # 登録対象をプレビュー（API呼び出しなし）
  python3 crm_bulk_register.py              # 実際にCRM登録を実行
  python3 crm_bulk_register.py --domain-only # ドメイン一致（連絡先のみ追加）のみ実行

優先度フィルタ:
  - メール件数3件以上 OR 直近6ヶ月以内に接触
  - メルマガ・営業メール等のノイズを除外
  - フリーメール（gmail, yahoo等）を取引先登録から除外

処理:
  1. 既存CRM取引先を取得し、会社名・ドメインで重複チェック
  2. 未登録の取引先をCRM取引先テーブルに登録
  3. 連絡先をCRM連絡先テーブルに登録（取引先リンク付き）
  4. ドメイン一致は連絡先のみ追加
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── Config ──
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
CSV_FILE = DATA_DIR / "unregistered_contacts.csv"

for _p in [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]:
    if _p.exists():
        with open(_p) as f:
            _cfg = json.load(f)
        if not str(_cfg.get("lark", {}).get("app_id", "")).startswith("${"):
            CONFIG = _cfg
            break
else:
    raise FileNotFoundError("automation_config.json not found")

if "CONFIG" not in dir():
    CONFIG = _cfg

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

# CRM Table IDs
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"

# フリーメールドメイン（取引先登録除外）
FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.co.jp", "yahoo.ne.jp", "yahoo.com", "icloud.com",
    "hotmail.com", "outlook.com", "outlook.jp", "me.com",
    "live.jp", "msn.com", "nifty.com", "biglobe.ne.jp",
    "softbank.ne.jp", "docomo.ne.jp", "ezweb.ne.jp", "au.com",
}

# ノイズ除外（メルマガ・ベンダー通知等）
NOISE_PATTERNS = [
    r"info@sekido-rc\.com",     # セキド（ドローン販売、メルマガ）
    r".*@uluru\.jp",            # NJSS（入札情報サービス）
    r"creative-team@jetb",      # JetB（Web制作、サポート）
    r"info@jetb\.co\.jp",
    r"mikami@taxer\.info",      # 三上税理士法人（税務）
    r"aya\.kuni716@gmail",      # 家族
    r"amicus_55ikubakka@icloud", # 政木（社内）
    r"hysy213@yahoo",           # 個人（フリーメール）
    r"jp-worldbank@ipsos",      # 世界銀行調査
    r"digital\.shien@nipc",     # にいがた産業創造機構
    r"cbr-kanrengyou@mlit",     # 中部地方整備局（官公庁）
    r"njss_purchase_order",     # NJSS発注通知
    r".*@daiogroup\.com",       # 大王製紙（見積のみ、レスポンスなし）
]

# ドメイン単位で除外（メルマガ・ベンダー・非案件先）
NOISE_DOMAINS = {
    "sekido-rc.com",        # セキド（ドローン販売、メルマガ）
    "sekidopartners.com",   # セキドパートナーズ（メルマガ）
    "ecoflow.com",          # EcoFlow（メルマガ）
    "craft-bank.com",       # CraftBank（マッチングサービス）
    "kankocho.biz",         # 官公庁ビジネス（メルマガ）
    "terra-mapper.com",     # TerraMapper（サービス通知）
    "ikea.com",             # IKEA（非案件）
    "his.ae",               # HIS Dubai（非案件）
    "nextage.jp",           # ネクステージ（非案件）
    "tsukumo.co.jp",        # ツクモ（PC販売）
    "imageone.co.jp",       # イメージワン（メルマガ）
    "lim-japan.com",        # LIM Japan（非案件）
    "list.co.jp",           # リスト（非案件）
    "pref.aichi.lg.jp",     # 愛知県庁（官公庁）
    "mlit.go.jp",           # 国交省（官公庁）
    "nipc.or.jp",           # にいがた産業創造機構
    "ipsos.co.jp",          # イプソス（調査会社）
    "uluru.jp",             # NJSS（入札情報サービス）
    "jetb.co.jp",           # JetB（Web制作、サポート）
    "taxer.info",           # 三上税理士法人
    "daiogroup.com",        # 大王製紙
    "aiweb.or.jp",          # 愛知県Webアーカイブ
    "hotta-me.com",         # 非案件
    "asgm.jp",              # 非案件
    "aga-adk.com",          # ADK関連（非案件）
    "adk.jp",               # ADK（非案件）
    "gnagai-office.com",    # 税理士事務所
    "ka-mo-me.com",         # 非案件
    "kyotonoma.com",        # 非案件
    "infield-gr.com",       # 非案件
    "jfn87.co.jp",          # JFN（ラジオ）
    "shinwa-ent.co.jp",     # 非案件
    "ce-kk.co.jp",          # 非案件
    "ys-consultancy.com",   # 非案件
    "token.co.jp",          # トケン（非案件）
    "mri.co.jp",            # 三菱総研（非案件）
    "nipponeexpress.com",   # 日本通運（typo版ドメイン、nipponexpressと重複）
}

# 会社名推定の補正マップ
COMPANY_NAME_MAP = {
    "dmc.dentsu.co.jp": "電通名鉄コミュニケーションズ",
    "ntp-g.com": "NTPグループ（ボルボ・カー昭和）",
    "dot-think.com": "ドットシンク",
    "st-kooco.jp": "エスティーコーコ",
    "kagitec.com": "カギテック",
    "fcgr.jp": "福井コンピュータ",
    "ixs.co.jp": "イクシス",
    "meikokensetsu.co.jp": "名工建設",
    "tanimotodrone.com": "谷本ドローン",
    "parond.com": "パロンド",
    "nts.yamaichi-techno.jp": "山一テクノ NTS",
    "global.komatsu": "コマツ",
    "s1bata.co.jp": "一柳建設",
    "autocover.jp": "AutoCover",
    "sanyo-kensetu.co.jp": "三洋建設",
    "df-sgs.co.jp": "SGS",
    "jcity.maeda.co.jp": "前田建設工業 Jシティ",
    "tokyu-cnst.co.jp": "東急建設",
    "k-ohba.co.jp": "大場建設",
    "nipponexpress.com": "日本通運（NX）",
    "nipponeexpress.com": "日本通運（NX）",
    "tokura.co.jp": "戸倉建設",
    "kinan.co.jp": "キナン",
    "taiyokenki.com": "太陽建機レンタル",
    "m-ss.co.jp": "丸栄産商",
    "imip.co.jp": "イミップ",
    "meitolink.com": "名東リンク",
    "daisen-g.com": "大仙グループ",
    "tokai-survey.com": "東海測量",
    "kajima.com": "鹿島建設",
}

# ── 6ヶ月前の日付 ──
SIX_MONTHS_AGO = datetime(2025, 9, 14)


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
        if "tenant_access_token" not in resp:
            print(f"[ERROR] Token acquisition failed: {resp}")
            sys.exit(1)
        return resp["tenant_access_token"]


def get_all_records(token, table_id):
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
        if result.get("code") != 0:
            print(f"[ERROR] API error: {result.get('msg')}")
            break
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def create_record(token, table_id, fields):
    url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
           f"{CRM_BASE_TOKEN}/tables/{table_id}/records")
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                record_id = result.get("data", {}).get("record", {}).get("record_id", "")
                return record_id
            else:
                print(f"  [ERROR] Create failed: {result.get('msg', 'unknown')} | code={result.get('code')}")
                return None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  [ERROR] HTTP {e.code}: {body[:200]}")
        return None


def batch_create_records(token, table_id, records_fields):
    """Batch create records (max 500 per call)"""
    created_ids = []
    for i in range(0, len(records_fields), 500):
        batch = records_fields[i:i+500]
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records/batch_create")
        payload = {
            "records": [{"fields": f} for f in batch]
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as r:
                result = json.loads(r.read())
                if result.get("code") == 0:
                    records = result.get("data", {}).get("records", [])
                    for rec in records:
                        created_ids.append(rec.get("record_id", ""))
                    print(f"  Batch created {len(records)} records")
                else:
                    print(f"  [ERROR] Batch create: {result.get('msg')} | code={result.get('code')}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"  [ERROR] HTTP {e.code}: {body[:200]}")
        time.sleep(0.5)
    return created_ids


# ── Data Loading ──
def load_csv():
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def is_noise(email):
    for pattern in NOISE_PATTERNS:
        if re.match(pattern, email, re.IGNORECASE):
            return True
    # ドメイン単位チェック
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in NOISE_DOMAINS:
        return True
    return False


def is_priority(row):
    """3件以上 or 直近6ヶ月以内"""
    count = int(row.get("メール件数", "0"))
    if count >= 3:
        return True
    last = row.get("最終接触日", "")
    if last:
        try:
            ld = datetime.strptime(last, "%Y-%m-%d")
            if ld >= SIX_MONTHS_AGO:
                return True
        except ValueError:
            pass
    return False


def resolve_company_name(row):
    """推定会社名を補正"""
    domain = row.get("ドメイン", "")
    csv_name = row.get("推定会社名", "").strip()

    if domain in COMPANY_NAME_MAP:
        return COMPANY_NAME_MAP[domain]
    if csv_name and csv_name not in ("yahoo", "icloud", "gmail"):
        return csv_name
    return domain


def extract_person_name(row):
    """名前フィールドからメアドやゴミを除去して氏名を返す"""
    name = row.get("名前", "").strip()
    email = row.get("メールアドレス", "")

    if not name or name == email:
        return ""
    # Remove company prefixes like "㈱カギテック "
    name = re.sub(r"^[㈱株式会社（）\(\)]+\s*\S+\s+", "", name)
    # If it looks like an email, skip
    if "@" in name:
        return ""
    # Remove 【】 brackets
    name = re.sub(r"【.*?】", "", name).strip()
    return name


def field_str(fields, key):
    """Extract string from Lark field (handles text arrays, links etc.)"""
    val = fields.get(key, "")
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        texts = []
        for item in val:
            if isinstance(item, dict):
                texts.append(item.get("text", str(item)))
            else:
                texts.append(str(item))
        return " ".join(texts).strip()
    if isinstance(val, dict):
        return val.get("text", str(val)).strip()
    return str(val).strip() if val else ""


# ── Main Logic ──
def main():
    dry_run = "--dry-run" in sys.argv
    domain_only = "--domain-only" in sys.argv

    print("=" * 60)
    print("Spark未登録取引先 CRM一括登録")
    print(f"Mode: {'DRY-RUN (API呼び出しなし)' if dry_run else 'LIVE'}")
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    # 1. Load CSV
    print("\n[1/5] CSVデータ読み込み...")
    all_rows = load_csv()
    print(f"  全{len(all_rows)}件")

    # 2. Filter: priority + noise removal
    print("\n[2/5] 優先度フィルタリング...")
    domain_rows = [r for r in all_rows if r.get("マッチ種別") == "domain"]
    unregistered_rows = [r for r in all_rows if r.get("マッチ種別") != "domain"]

    priority_rows = []
    noise_skipped = []
    low_priority = []

    for r in unregistered_rows:
        email = r.get("メールアドレス", "")
        if is_noise(email):
            noise_skipped.append(r)
            continue
        if is_priority(r):
            priority_rows.append(r)
        else:
            low_priority.append(r)

    print(f"  未登録: {len(unregistered_rows)}件")
    print(f"  -> 優先(3件以上 or 6ヶ月以内): {len(priority_rows)}件")
    print(f"  -> ノイズ除外: {len(noise_skipped)}件")
    print(f"  -> 低優先(スキップ): {len(low_priority)}件")
    print(f"  ドメイン一致(連絡先のみ): {len(domain_rows)}件")

    if domain_only:
        priority_rows = []
        print("  --domain-only: 未登録はスキップ")

    # 3. Get existing CRM data for dedup
    print("\n[3/5] CRM既存データ取得...")
    token = lark_get_token()

    existing_accounts = get_all_records(token, TABLE_ACCOUNTS)
    existing_contacts = get_all_records(token, TABLE_CONTACTS)
    print(f"  既存取引先: {len(existing_accounts)}件")
    print(f"  既存連絡先: {len(existing_contacts)}件")

    # Build dedup sets
    existing_account_names = set()
    existing_account_domains = {}  # domain -> record_id
    account_name_to_id = {}  # name -> record_id

    for acc in existing_accounts:
        f = acc.get("fields", {})
        rid = acc.get("record_id", "")
        # 取引先テーブルは「会社名（正式）」「会社名（略称）」の2フィールド
        for key in ["会社名（正式）", "会社名（略称）"]:
            name = field_str(f, key)
            if name:
                normalized = name.strip().replace("　", " ")
                existing_account_names.add(normalized)
                account_name_to_id[normalized] = rid

    existing_contact_emails = set()
    for con in existing_contacts:
        f = con.get("fields", {})
        email = field_str(f, "メールアドレス")
        if email:
            existing_contact_emails.add(email.lower())

    print(f"  既存取引先名: {len(existing_account_names)}件")
    print(f"  既存連絡先メール: {len(existing_contact_emails)}件")

    # 4. Group by domain -> company
    print("\n[4/5] 取引先グルーピング...")

    # Group priority rows by domain
    domain_groups = {}
    for r in priority_rows:
        domain = r.get("ドメイン", "")
        if domain in FREE_MAIL_DOMAINS or domain in NOISE_DOMAINS:
            continue
        if domain not in domain_groups:
            domain_groups[domain] = {
                "company_name": resolve_company_name(r),
                "contacts": [],
                "domain": domain,
                "total_emails": 0,
                "latest_contact": "",
            }
        domain_groups[domain]["contacts"].append(r)
        domain_groups[domain]["total_emails"] += int(r.get("メール件数", "0"))
        last = r.get("最終接触日", "")
        if last > domain_groups[domain]["latest_contact"]:
            domain_groups[domain]["latest_contact"] = last

    # Sort by total email count (most active first)
    sorted_domains = sorted(domain_groups.values(), key=lambda x: -x["total_emails"])

    print(f"  取引先候補(ドメイン別): {len(sorted_domains)}件")

    # Dedup check (exact match or partial match)
    new_accounts = []
    dup_accounts = []
    for grp in sorted_domains:
        name = grp["company_name"]
        normalized = name.strip().replace("　", " ")
        is_dup = False
        for existing_name in existing_account_names:
            if normalized == existing_name or normalized in existing_name or existing_name in normalized:
                is_dup = True
                grp["matched_account_id"] = account_name_to_id.get(existing_name, "")
                break
        if is_dup:
            dup_accounts.append(grp)
        else:
            new_accounts.append(grp)

    print(f"  -> 新規取引先: {len(new_accounts)}件")
    print(f"  -> 既存重複(スキップ): {len(dup_accounts)}件")

    # Domain match contacts
    domain_contacts = []
    for r in domain_rows:
        email = r.get("メールアドレス", "").lower()
        if email not in existing_contact_emails and not is_noise(email):
            domain_contacts.append(r)

    print(f"  ドメイン一致 新規連絡先: {len(domain_contacts)}件")

    # 5. Register
    print("\n[5/5] CRM登録...")
    print("-" * 60)

    accounts_created = 0
    contacts_created = 0
    errors = []

    # 5a. Create new accounts + contacts
    print(f"\n--- 新規取引先 {len(new_accounts)}社 ---")
    for i, grp in enumerate(new_accounts, 1):
        company = grp["company_name"]
        domain = grp["domain"]
        total = grp["total_emails"]
        latest = grp["latest_contact"]
        contact_count = len(grp["contacts"])

        print(f"\n[{i}/{len(new_accounts)}] {company} ({domain})")
        print(f"  メール計{total}通 / 連絡先{contact_count}名 / 最終接触: {latest}")

        if dry_run:
            print(f"  [DRY-RUN] 取引先を登録予定")
            accounts_created += 1
            for r in grp["contacts"]:
                email = r.get("メールアドレス", "").lower()
                name = extract_person_name(r)
                if email not in existing_contact_emails:
                    print(f"  [DRY-RUN] 連絡先: {name or '(名前不明)'} <{email}>")
                    contacts_created += 1
                else:
                    print(f"  [SKIP] 連絡先既存: {email}")
            continue

        # Create account
        account_fields = {
            "会社名（正式）": company,
            "会社名（略称）": company,
        }
        account_id = create_record(token, TABLE_ACCOUNTS, account_fields)
        if account_id:
            accounts_created += 1
            print(f"  -> 取引先作成: {account_id}")
            time.sleep(0.3)

            # Create contacts linked to this account
            for r in grp["contacts"]:
                email = r.get("メールアドレス", "").lower()
                name = extract_person_name(r)
                if email in existing_contact_emails:
                    print(f"  [SKIP] 連絡先既存: {email}")
                    continue

                contact_fields = {
                    "メールアドレス": email,
                    "会社名": company,
                    "取引先": [account_id],
                }
                if name:
                    contact_fields["氏名"] = name

                cid = create_record(token, TABLE_CONTACTS, contact_fields)
                if cid:
                    contacts_created += 1
                    existing_contact_emails.add(email)
                    print(f"  -> 連絡先作成: {name or email} ({cid})")
                else:
                    errors.append(f"Contact create failed: {email}")
                time.sleep(0.3)
        else:
            errors.append(f"Account create failed: {company}")

    # 5b. Domain match: contacts only
    print(f"\n--- ドメイン一致 連絡先追加 {len(domain_contacts)}件 ---")
    for i, r in enumerate(domain_contacts, 1):
        email = r.get("メールアドレス", "").lower()
        name = extract_person_name(r)
        domain = r.get("ドメイン", "")
        company = resolve_company_name(r)

        # Find matching account
        matched_account_id = None
        for acc in existing_accounts:
            f = acc.get("fields", {})
            for key in ["会社名（正式）", "会社名（略称）"]:
                acc_name = field_str(f, key)
                if acc_name and company and (company in acc_name or acc_name in company):
                    matched_account_id = acc.get("record_id")
                    break
            if matched_account_id:
                break

        print(f"\n[{i}/{len(domain_contacts)}] {name or '(名前不明)'} <{email}> -> {company}")

        if email in existing_contact_emails:
            print(f"  [SKIP] 連絡先既存")
            continue

        if dry_run:
            acct_info = f"account={matched_account_id}" if matched_account_id else "account未特定"
            print(f"  [DRY-RUN] 連絡先登録予定 ({acct_info})")
            contacts_created += 1
            continue

        contact_fields = {
            "メールアドレス": email,
            "会社名": company,
        }
        if name:
            contact_fields["氏名"] = name
        if matched_account_id:
            contact_fields["取引先"] = [matched_account_id]

        cid = create_record(token, TABLE_CONTACTS, contact_fields)
        if cid:
            contacts_created += 1
            existing_contact_emails.add(email)
            print(f"  -> 連絡先作成: {cid}")
        else:
            errors.append(f"Domain contact failed: {email}")
        time.sleep(0.3)

    # 5c. Dup accounts: check for new contacts
    print(f"\n--- 既存取引先の新規連絡先 {len(dup_accounts)}社 ---")
    dup_contacts_added = 0
    for grp in dup_accounts:
        company = grp["company_name"]
        account_id = grp.get("matched_account_id", "")

        new_contacts_in_dup = []
        for r in grp["contacts"]:
            email = r.get("メールアドレス", "").lower()
            if email not in existing_contact_emails:
                new_contacts_in_dup.append(r)

        if not new_contacts_in_dup:
            continue

        print(f"\n  {company}: 新規連絡先{len(new_contacts_in_dup)}名")
        for r in new_contacts_in_dup:
            email = r.get("メールアドレス", "").lower()
            name = extract_person_name(r)

            if dry_run:
                print(f"  [DRY-RUN] {name or '(名前不明)'} <{email}>")
                dup_contacts_added += 1
                continue

            contact_fields = {
                "メールアドレス": email,
                "会社名": company,
            }
            if name:
                contact_fields["氏名"] = name
            if account_id:
                contact_fields["取引先"] = [account_id]

            cid = create_record(token, TABLE_CONTACTS, contact_fields)
            if cid:
                dup_contacts_added += 1
                existing_contact_emails.add(email)
                print(f"  -> {name or email} ({cid})")
            else:
                errors.append(f"Dup account contact failed: {email}")
            time.sleep(0.3)

    contacts_created += dup_contacts_added

    # Summary
    print("\n" + "=" * 60)
    print("登録結果サマリー")
    print("=" * 60)
    print(f"  新規取引先: {accounts_created}社")
    print(f"  新規連絡先: {contacts_created}名")
    if dup_contacts_added:
        print(f"    (うち既存取引先への連絡先追加: {dup_contacts_added}名)")
    if errors:
        print(f"  エラー: {len(errors)}件")
        for e in errors[:10]:
            print(f"    - {e}")
    if dry_run:
        print(f"\n  *** DRY-RUN完了。実行するには --dry-run を外してください ***")
    print()


if __name__ == "__main__":
    main()
