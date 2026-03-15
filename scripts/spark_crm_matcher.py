#!/usr/bin/env python3
"""
Spark メール × Lark CRM 照合スクリプト
- Spark SQLite DBから案件関連メールの取引先メールアドレスを抽出
- Lark CRM連絡先テーブルと照合
- 未登録案件をCSV・レポートとして出力
"""

import sqlite3
import json
import csv
import os
import re
import time
from datetime import datetime
from collections import defaultdict
import requests

# === Config ===
CONFIG_PATH = "/mnt/c/Users/USER/Documents/_data/automation_config.json"
SPARK_DB = "/mnt/c/Users/USER/AppData/Local/Spark Desktop/core-data/databases/messages.sqlite"
SPARK_DB_COPY = "/tmp/spark_messages.sqlite"
OUTPUT_CSV = "/mnt/c/Users/USER/Documents/_data/tas-automation/data/unregistered_contacts.csv"
REPORT_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/docs/spark_crm_match_report.md"

# Business email accounts
BUSINESS_ACCOUNTS = {
    'info@tokaiair.com', 'tokai.airservice@gmail.com', 'sales@tokaiair.com',
    'yosuke.toyoda@gmail.com', 'y.toyoda@tokai-survey.com'
}

# Internal / exclude addresses
EXCLUDE_DOMAINS = {
    'tokaiair.com', 'tokai-survey.com', 'riseasone.jp',  # internal
    'gmail.com', 'yahoo.co.jp', 'hotmail.com', 'outlook.com', 'icloud.com',
    'googlemail.com', 'yahoo.com', 'outlook.jp', 'me.com',  # freemail (handle separately)
}

# Known internal/team addresses to exclude
EXCLUDE_ADDRESSES = {
    'yosuke.toyoda@gmail.com', 'tokai.airservice@gmail.com',
    'y-masaki@riseasone.jp', 'hysy2131@gmail.com',  # team members
    'info@tokaiair.com', 'sales@tokaiair.com', 'info_rei@tokaiair.com',
    'info@t-as.net', '8fields.info@gmail.com', 'kintsugi.official.jp@gmail.com',
    'y.toyoda@tokai-survey.com',
}

# Case keywords for filtering business emails
CASE_KEYWORDS = [
    '見積', '請求', '納品', '受注', '発注', '契約', '入札', '注文',
    '御見積', 'お見積', '報告書', '成果物', '業務', '計測', '撮影',
    '測量', 'ドローン', '点群', '空撮', '現場', '工事', '建設',
    '調査', '検査', 'パノラマ', '眺望', 'quote', 'invoice', 'delivery',
    '打ち合わせ', '打合せ', 'お打ち合わせ', '御礼', 'ご依頼',
]


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def get_lark_tenant_token(config):
    """Get Lark tenant access token"""
    url = "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": config['lark']['app_id'],
        "app_secret": config['lark']['app_secret']
    })
    data = resp.json()
    if data.get('code') != 0:
        raise Exception(f"Lark auth failed: {data}")
    return data['tenant_access_token']


def get_crm_contacts(token, base_token, table_id):
    """Fetch all contacts from Lark CRM"""
    contacts = []
    page_token = None
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records"

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}"
        }, params=params)
        data = resp.json()

        if data.get('code') != 0:
            print(f"CRM API error: {data}")
            break

        items = data.get('data', {}).get('items', [])
        for item in items:
            fields = item.get('fields', {})
            contacts.append({
                'record_id': item.get('record_id'),
                'fields': fields
            })

        if not data.get('data', {}).get('has_more'):
            break
        page_token = data['data'].get('page_token')
        time.sleep(0.2)

    return contacts


def get_crm_deals(token, base_token, table_id):
    """Fetch all deals from Lark CRM"""
    deals = []
    page_token = None
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records"

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(url, headers={
            "Authorization": f"Bearer {token}"
        }, params=params)
        data = resp.json()

        if data.get('code') != 0:
            print(f"Deals API error: {data}")
            break

        items = data.get('data', {}).get('items', [])
        for item in items:
            fields = item.get('fields', {})
            deals.append({
                'record_id': item.get('record_id'),
                'fields': fields
            })

        if not data.get('data', {}).get('has_more'):
            break
        page_token = data['data'].get('page_token')
        time.sleep(0.2)

    return deals


def extract_emails_from_field(field_value):
    """Extract email addresses from various Lark field formats"""
    emails = set()
    if isinstance(field_value, str):
        found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', field_value.lower())
        emails.update(found)
    elif isinstance(field_value, list):
        for item in field_value:
            if isinstance(item, dict):
                for v in item.values():
                    if isinstance(v, str):
                        found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', v.lower())
                        emails.update(found)
            elif isinstance(item, str):
                found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', item.lower())
                emails.update(found)
    return emails


def extract_spark_contacts(db_path):
    """Extract unique business email addresses from Spark DB"""
    import shutil
    # Copy DB to avoid lock issues
    shutil.copy2(db_path, SPARK_DB_COPY)

    conn = sqlite3.connect(SPARK_DB_COPY)
    cur = conn.cursor()

    # Get business account PKs
    cur.execute("SELECT pk, additionalInfo FROM accounts WHERE accountType = 0")
    accounts_raw = cur.fetchall()
    accounts = []
    for pk, info_json in accounts_raw:
        try:
            info = json.loads(info_json)
            email = info.get('accountAddress', '')
            accounts.append((pk, email))
        except (json.JSONDecodeError, TypeError):
            accounts.append((pk, ''))
    print(f"Accounts: {accounts}")

    # Build keyword pattern for SQL LIKE
    keyword_conditions = " OR ".join([f"subject LIKE '%{kw}%'" for kw in CASE_KEYWORDS])

    # Query messages with case-related subjects from business accounts
    query = f"""
    SELECT DISTINCT
        messageFromMailbox,
        messageFrom,
        subject,
        receivedDate,
        shortBody,
        messageTo,
        messageCc,
        inSent
    FROM messages
    WHERE ({keyword_conditions})
    AND messageFromMailbox IS NOT NULL
    AND messageFromMailbox != ''
    ORDER BY receivedDate DESC
    """

    cur.execute(query)
    rows = cur.fetchall()
    print(f"Case-related messages found: {len(rows)}")

    # Collect unique external contacts
    contacts = {}  # email -> {name, company, subjects, last_date, count}

    # First pass: identify emails we've SENT TO (bidirectional = real business contact)
    sent_to_emails = set()
    received_from_emails = set()

    for row in rows:
        from_mailbox = (row[0] or '').lower().strip()
        in_sent = row[7]
        message_to = (row[5] or '').lower().strip()
        message_cc = (row[6] or '').lower().strip()

        if from_mailbox in EXCLUDE_ADDRESSES or in_sent == 1:
            for field in [message_to, message_cc]:
                found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', field)
                sent_to_emails.update(found)
        else:
            if from_mailbox and '@' in from_mailbox:
                received_from_emails.add(from_mailbox)

    # Bidirectional contacts (we both sent and received) = high confidence
    bidirectional = sent_to_emails & received_from_emails
    print(f"    Bidirectional contacts: {len(bidirectional)}")
    print(f"    Sent-to only: {len(sent_to_emails - received_from_emails)}")
    print(f"    Received-from only: {len(received_from_emails - sent_to_emails)}")

    # Include: bidirectional + sent-to (we actively emailed them)
    relevant_emails = sent_to_emails  # Anyone we've sent case-related email to

    for row in rows:
        from_mailbox = (row[0] or '').lower().strip()
        from_name = (row[1] or '').strip()
        subject = (row[2] or '').strip()
        received_date = row[3]
        short_body = (row[4] or '').strip()
        message_to = (row[5] or '').lower().strip()
        message_cc = (row[6] or '').lower().strip()
        in_sent = row[7]

        # Convert timestamp
        if received_date and received_date > 0:
            try:
                date_str = datetime.fromtimestamp(received_date).strftime('%Y-%m-%d')
            except (ValueError, OSError):
                date_str = 'unknown'
        else:
            date_str = 'unknown'

        # Collect all email addresses from this message
        all_emails_in_msg = set()

        # If sent by us, look at To/Cc for external contacts
        if from_mailbox in EXCLUDE_ADDRESSES or in_sent == 1:
            # Extract from To and Cc
            for field in [message_to, message_cc]:
                found = re.findall(r'[\w.+-]+@[\w.-]+\.\w+', field)
                all_emails_in_msg.update(found)
        else:
            # Only include received emails from contacts we've also sent to (bidirectional)
            if from_mailbox in relevant_emails:
                all_emails_in_msg.add(from_mailbox)

        for email in all_emails_in_msg:
            email = email.lower().strip()
            if email in EXCLUDE_ADDRESSES:
                continue
            if not email or '@' not in email:
                continue

            domain = email.split('@')[1]

            # Skip system/newsletter/noreply/bulk emails
            skip_patterns = [
                'noreply', 'no-reply', 'no_reply', 'donotreply', 'do-not-reply',
                'mailer-daemon', 'postmaster', 'bounce',
                'notification', 'alert@', 'system@',
                'wordpress', 'cloudflare', 'litespeed', 'wp-',
                'newsletter', 'news@', 'magazine@', 'press@',
                'marketing', 'campaign', 'promo', 'offer@', 'directoffer',
                'info@mail.', 'mail-info@', 'mail-news@', 'information@mail.',
                'haishin', 'member@', 'members@', 'e-club@', 'club@',
                'unknown@unknown', 'phish@',
                'touroku-', 'keiyaku@city',
                # Known non-business services
                'google.com', 'facebook', 'twitter', 'linkedin',
                'amazon', 'apple.com', 'microsoft',
                'rakuten', 'yahoo.co.jp',
                'vpass.ne.jp', 'burgerking',
                # Bulk mail services
                '@mail.', '@service.', '@info.',
            ]
            if any(x in email for x in skip_patterns):
                continue

            # Determine name from From header if this is the sender
            name = ''
            if email == from_mailbox:
                name = from_name
                # Clean up name - remove email part if present
                name = re.sub(r'<.*?>', '', name).strip()
                name = re.sub(r'[\"\']', '', name).strip()

            if email not in contacts:
                contacts[email] = {
                    'name': name,
                    'domain': domain,
                    'subjects': [],
                    'last_date': date_str,
                    'first_date': date_str,
                    'count': 0
                }

            contacts[email]['count'] += 1
            if name and not contacts[email]['name']:
                contacts[email]['name'] = name
            if date_str != 'unknown':
                if contacts[email]['last_date'] == 'unknown' or date_str > contacts[email]['last_date']:
                    contacts[email]['last_date'] = date_str
                if contacts[email]['first_date'] == 'unknown' or date_str < contacts[email]['first_date']:
                    contacts[email]['first_date'] = date_str
            if subject and len(contacts[email]['subjects']) < 5:
                if subject not in contacts[email]['subjects']:
                    contacts[email]['subjects'].append(subject)

    conn.close()
    return contacts


def guess_company(email, name, domain):
    """Guess company name from email domain and name"""
    # Known mappings
    domain_company = {
        'st-koo.co.jp': '空（st-koo）',
        'dmc.dentsu.co.jp': '電通名鉄コミュニケーションズ',
        'meikokensetsu.co.jp': '名工建設',
        'wagoco.com': '和合コンサルタント',
        'sanyo-kensetu.co.jp': '三洋建設',
        's1bata.co.jp': '一柳',
        'tanimotodrone.com': '谷本ドローン',
        'kagitec.com': 'カギテック',
        'global.komatsu': 'コマツ',
        'ixs.co.jp': 'IXS（イクス）',
        'obayashi.co.jp': '大林組',
        'kajima.com': '鹿島建設',
        'shimz.co.jp': '清水建設',
        'taisei.co.jp': '大成建設',
        'maeda.co.jp': '前田建設',
        'hazama.co.jp': 'ハザマ',
        'nishimatsu.co.jp': '西松建設',
        'toda.co.jp': '戸田建設',
        'penta-ocean.co.jp': '五洋建設',
        'tokyu-cnst.co.jp': '東急建設',
        'fujita.co.jp': 'フジタ',
        'konoike.co.jp': '鴻池組',
        'kumagai.co.jp': '熊谷組',
    }

    if domain in domain_company:
        return domain_company[domain]

    # Try to extract from domain
    if domain not in EXCLUDE_DOMAINS:
        company = domain.split('.')[0]
        # Clean up
        company = company.replace('-', ' ').replace('_', ' ')
        return company

    return name or email


def main():
    print("=" * 60)
    print("Spark × Lark CRM 照合")
    print("=" * 60)

    # 1. Load config
    config = load_config()
    print("\n[1] Config loaded")

    # 2. Extract Spark contacts
    print("\n[2] Extracting contacts from Spark DB...")
    spark_contacts = extract_spark_contacts(SPARK_DB)
    print(f"    Unique external emails: {len(spark_contacts)}")

    # 3. Get Lark CRM data
    print("\n[3] Fetching Lark CRM data...")
    token = get_lark_tenant_token(config)
    print(f"    Tenant token obtained")

    crm_base = config['lark']['crm_base_token']

    # Fetch contacts
    crm_contacts = get_crm_contacts(token, crm_base, 'tblN53hFIQoo4W8j')
    print(f"    CRM contacts: {len(crm_contacts)}")

    # Fetch deals
    crm_deals = get_crm_deals(token, crm_base, 'tbl1rM86nAw9l3bP')
    print(f"    CRM deals: {len(crm_deals)}")

    # 4. Extract CRM email addresses
    print("\n[4] Extracting CRM email addresses...")
    crm_emails = set()
    crm_email_to_record = {}

    for contact in crm_contacts:
        fields = contact['fields']
        for key, val in fields.items():
            extracted = extract_emails_from_field(val)
            for em in extracted:
                crm_emails.add(em)
                crm_email_to_record[em] = {
                    'record_id': contact['record_id'],
                    'fields': fields
                }

    # Also extract emails from company/deal records
    crm_deal_emails = set()
    for deal in crm_deals:
        fields = deal['fields']
        for key, val in fields.items():
            extracted = extract_emails_from_field(val)
            crm_deal_emails.update(extracted)

    all_crm_emails = crm_emails | crm_deal_emails
    print(f"    CRM unique emails (contacts): {len(crm_emails)}")
    print(f"    CRM unique emails (deals): {len(crm_deal_emails)}")
    print(f"    CRM total unique emails: {len(all_crm_emails)}")

    # Also extract company domains from CRM for domain-level matching
    crm_domains = set()
    for em in all_crm_emails:
        if '@' in em:
            crm_domains.add(em.split('@')[1])

    # 5. Match
    print("\n[5] Matching...")
    matched = {}
    unmatched = {}
    domain_matched = {}  # Not exact email match but same domain exists in CRM

    for email, info in spark_contacts.items():
        domain = info['domain']
        if email in all_crm_emails:
            matched[email] = info
        elif domain in crm_domains and domain not in EXCLUDE_DOMAINS:
            domain_matched[email] = info
            domain_matched[email]['match_type'] = 'domain'
        else:
            unmatched[email] = info

    print(f"    Exact match (in CRM): {len(matched)}")
    print(f"    Domain match (company in CRM, person not): {len(domain_matched)}")
    print(f"    Unmatched (not in CRM): {len(unmatched)}")

    # 6. Filter unmatched to business-relevant only
    # Separate freemail vs corporate
    unmatched_corporate = {}
    unmatched_freemail = {}

    for email, info in unmatched.items():
        domain = info['domain']
        if domain in EXCLUDE_DOMAINS:
            # Freemail - only include if high count or clear business context
            if info['count'] >= 3:
                unmatched_freemail[email] = info
        else:
            unmatched_corporate[email] = info

    print(f"    Unmatched corporate: {len(unmatched_corporate)}")
    print(f"    Unmatched freemail (3+ interactions): {len(unmatched_freemail)}")

    # 7. Sort by relevance (count * recency)
    all_unregistered = {}
    all_unregistered.update(unmatched_corporate)
    all_unregistered.update(unmatched_freemail)
    all_unregistered.update(domain_matched)

    sorted_unregistered = sorted(
        all_unregistered.items(),
        key=lambda x: (x[1]['last_date'] if x[1]['last_date'] != 'unknown' else '0000', x[1]['count']),
        reverse=True
    )

    # 8. Output CSV
    print(f"\n[6] Writing CSV: {OUTPUT_CSV}")
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow([
            'メールアドレス', '名前', '推定会社名', 'ドメイン',
            'メール件数', '最終接触日', '初回接触日', 'マッチ種別', '案件概要'
        ])
        for email, info in sorted_unregistered:
            company = guess_company(email, info['name'], info['domain'])
            match_type = info.get('match_type', '未登録')
            subjects = ' / '.join(info['subjects'][:3])
            writer.writerow([
                email, info['name'], company, info['domain'],
                info['count'], info['last_date'], info['first_date'],
                match_type, subjects
            ])

    # 9. Generate report
    print(f"\n[7] Writing report: {REPORT_PATH}")

    report = f"""# Spark × Lark CRM 照合レポート

**作成日**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
**照合元**: Spark Desktop SQLite DB (157,681通)
**照合先**: Lark CRM Base (連絡先 tblN53hFIQoo4W8j / 商談 tbl1rM86nAw9l3bP)

---

## サマリー

| 項目 | 件数 |
|------|-----:|
| Spark案件関連ユニークメール | {len(spark_contacts)} |
| CRM登録済み（完全一致） | {len(matched)} |
| CRM登録済み（ドメイン一致・担当者違い） | {len(domain_matched)} |
| **CRM未登録（法人メール）** | **{len(unmatched_corporate)}** |
| CRM未登録（フリーメール・3回以上） | {len(unmatched_freemail)} |
| **要対応合計** | **{len(all_unregistered)}** |

---

## CRM登録済み（完全一致）

| # | メールアドレス | 名前 | メール件数 | 最終接触日 |
|---|-------------|------|--------:|----------|
"""
    for i, (email, info) in enumerate(sorted(matched.items(), key=lambda x: x[1]['count'], reverse=True), 1):
        report += f"| {i} | {email} | {info['name']} | {info['count']} | {info['last_date']} |\n"

    report += f"""
---

## CRM未登録：法人メール（要登録）

| # | メールアドレス | 名前 | 推定会社名 | 件数 | 最終接触日 | 案件概要 |
|---|-------------|------|----------|----:|----------|--------|
"""
    for i, (email, info) in enumerate(sorted(unmatched_corporate.items(),
            key=lambda x: (x[1]['last_date'] if x[1]['last_date'] != 'unknown' else '0000', x[1]['count']),
            reverse=True), 1):
        company = guess_company(email, info['name'], info['domain'])
        subjects = ' / '.join(info['subjects'][:2])
        report += f"| {i} | {email} | {info['name']} | {company} | {info['count']} | {info['last_date']} | {subjects} |\n"

    if domain_matched:
        report += f"""
---

## ドメイン一致・担当者未登録（要追加登録）

会社自体はCRMに存在するが、この担当者のメールアドレスが未登録。

| # | メールアドレス | 名前 | ドメイン | 件数 | 最終接触日 | 案件概要 |
|---|-------------|------|--------|----:|----------|--------|
"""
        for i, (email, info) in enumerate(sorted(domain_matched.items(),
                key=lambda x: x[1]['count'], reverse=True), 1):
            subjects = ' / '.join(info['subjects'][:2])
            report += f"| {i} | {email} | {info['name']} | {info['domain']} | {info['count']} | {info['last_date']} | {subjects} |\n"

    if unmatched_freemail:
        report += f"""
---

## フリーメール（3回以上やり取り）

個人メールアドレスだが案件関連のやり取りあり。

| # | メールアドレス | 名前 | 件数 | 最終接触日 | 案件概要 |
|---|-------------|------|----:|----------|--------|
"""
        for i, (email, info) in enumerate(sorted(unmatched_freemail.items(),
                key=lambda x: x[1]['count'], reverse=True), 1):
            subjects = ' / '.join(info['subjects'][:2])
            report += f"| {i} | {email} | {info['name']} | {info['count']} | {info['last_date']} | {subjects} |\n"

    report += f"""
---

## 次のアクション

1. **即時**: 法人メール未登録分をCRM連絡先テーブルに一括登録
2. **即時**: ドメイン一致分を既存取引先の追加連絡先として登録
3. **確認**: フリーメールの担当者を特定し、法人メールを取得
4. **商談作成**: 未登録案件のうち直近6ヶ月以内のものを商談として登録

---

*Generated by spark_crm_matcher.py*
"""

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)

    print("\n" + "=" * 60)
    print("完了!")
    print(f"CSV: {OUTPUT_CSV}")
    print(f"Report: {REPORT_PATH}")
    print("=" * 60)


if __name__ == '__main__':
    main()
