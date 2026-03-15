#!/usr/bin/env python3
"""
Google Sheets → Lark CRM 同期スクリプト
営業訪問記録フォーム（初回・2回目以降）をマスターとしてCRMに統合
- メールアドレスで担当営業を判定（amicus=政木, hysy=新美, kurotiku=田村→エリアで振分）
- CRMにない会社は新規作成
- CRMにある会社は担当営業の修正
"""

import json
import re
import time
import gspread
from google.oauth2.service_account import Credentials
import requests

# --- Config ---
with open('/mnt/c/Users/USER/Documents/_data/automation_config.json') as f:
    config = json.load(f)

LARK_APP_ID = config['lark']['app_id']
LARK_APP_SECRET = config['lark']['app_secret']
CRM_BASE_ID = 'BodWbgw6DaHP8FspBTYjT8qSpOe'
DEAL_TABLE_ID = 'tbl1rM86nAw9l3bP'

NIIMI_ID = 'ou_189dc637b61a83b886d356becb3ae18e'
MASAKI_ID = 'ou_6ee633b968b9229655813af6e3a47e9f'

# Email → rep mapping
EMAIL_REP = {
    'amicus_55ikubakka@icloud.com': 'masaki',
    'hysy2131@gmail.com': 'niimi',
    'kurotiku916@gmail.com': 'tamura',  # 退職→エリアで振分
}

# Area keywords for 田村 reassignment
GIFU_MIE = ['岐阜', '三重', '四日市', '津市', '桑名', '鈴鹿', '伊勢', '大垣', '各務原',
            '多治見', '松阪', '名張', '亀山', '養老', '菰野', '東員']


def get_lark_token():
    resp = requests.post(
        'https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': LARK_APP_ID, 'app_secret': LARK_APP_SECRET})
    return resp.json().get('tenant_access_token')


def get_sheets_data():
    creds = Credentials.from_service_account_file(
        '/mnt/c/Users/USER/Documents/_data/google_service_account.json',
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.readonly'])
    gc = gspread.authorize(creds)

    sh1 = gc.open_by_key('1-_FyyH4tuoUs9EJihdmU6PpsXCcVGbv1MeROmrGZrfk')
    data1 = sh1.sheet1.get_all_records()

    sh2 = gc.open_by_key('19wPY4AJAbQxw40lbzOcv6KkajKvE9e92HZEs62bwdFo')
    data2 = sh2.sheet1.get_all_records()

    return data1, data2


def normalize_company(name):
    """会社名の正規化"""
    name = name.strip()
    name = re.sub(r'[\s　]+', '', name)
    name = name.replace('株式会社', '').replace('（株）', '').replace('(株)', '')
    name = name.replace('有限会社', '').replace('（有）', '')
    return name


def determine_rep(email, all_text=''):
    """メールアドレスからrep判定。田村はエリアで振分"""
    rep = EMAIL_REP.get(email, 'unknown')
    if rep == 'tamura':
        if any(kw in all_text for kw in GIFU_MIE):
            return 'masaki'
        return 'niimi'  # デフォルトは新美（愛知）
    return rep


def get_all_crm_deals(token):
    """CRMの全商談を取得"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{DEAL_TABLE_ID}/records/search'

    all_deals = []
    page_token = None
    while True:
        payload = {'page_size': 200}
        if page_token:
            payload['page_token'] = page_token
        resp = requests.post(url, headers=headers, json=payload)
        data = resp.json()
        if data.get('code') == 0:
            all_deals.extend(data['data'].get('items', []))
            if data['data'].get('has_more'):
                page_token = data['data']['page_token']
            else:
                break
        else:
            print(f'Error fetching deals: {data}')
            break
        time.sleep(0.2)
    return all_deals


def build_crm_index(deals):
    """CRMの会社名インデックスを構築"""
    index = {}
    for deal in deals:
        fields = deal.get('fields', {})
        for field_name in ['商談名', '新規取引先名']:
            val = fields.get(field_name, '')
            if isinstance(val, list):
                for v in val:
                    if isinstance(v, dict) and 'text' in v:
                        norm = normalize_company(v['text'])
                        # Remove date suffix
                        norm = re.sub(r'_\d{4}/\d{2}/\d{2}$', '', norm)
                        if norm and len(norm) >= 2:
                            if norm not in index:
                                index[norm] = []
                            index[norm].append(deal)
            elif isinstance(val, str) and val:
                norm = normalize_company(val)
                norm = re.sub(r'_\d{4}/\d{2}/\d{2}$', '', norm)
                if norm and len(norm) >= 2:
                    if norm not in index:
                        index[norm] = []
                    index[norm].append(deal)
    return index


def find_in_crm(company_name, crm_index):
    """スプシの会社名でCRMを検索"""
    norm = normalize_company(company_name)
    if norm in crm_index:
        return crm_index[norm]
    # Partial match
    for key, deals in crm_index.items():
        if len(norm) >= 3 and norm in key:
            return deals
        if len(key) >= 3 and key in norm:
            return deals
    return []


def main():
    print('=== Google Sheets → CRM 同期 ===')

    # 1. Get data
    print('Sheets読み込み中...')
    first_visits, followups = get_sheets_data()
    print(f'  初回: {len(first_visits)}件 / 2回目以降: {len(followups)}件')

    print('CRM読み込み中...')
    token = get_lark_token()
    crm_deals = get_all_crm_deals(token)
    print(f'  CRM商談: {len(crm_deals)}件')

    crm_index = build_crm_index(crm_deals)

    # 2. Analyze
    needs_rep_fix = []  # CRMにあるが担当が違う
    not_in_crm = []     # CRMにない
    already_ok = 0

    all_records = []
    for r in first_visits:
        company = r.get('客先名（会社名）', '').strip()
        if not company:
            continue
        email = r.get('メールアドレス', '')
        all_text = company + ' ' + r.get('備考・メモ', '') + ' ' + r.get('訪問先名・現場名', '')
        rep = determine_rep(email, all_text)
        all_records.append({
            'company': company,
            'email': email,
            'rep': rep,
            'score': r.get('温度感スコア', ''),
            'hearing': r.get('【重要】ヒアリング内容', ''),
            'visit_date': r.get('訪問日時', ''),
            'status': r.get('現在のステータス', ''),
            'next_action': r.get('次回アクション', ''),
            'category': r.get('客先カテゴリ', ''),
            'location': r.get('訪問先名・現場名', ''),
            'source': '初回訪問フォーム',
        })

    for r in followups:
        company = r.get('訪問先名・現場名', '').strip()
        if not company:
            continue
        email = r.get('メールアドレス', '')
        all_text = company + ' ' + r.get('備考・メモ', '')
        rep = determine_rep(email, all_text)
        all_records.append({
            'company': company,
            'email': email,
            'rep': rep,
            'score': r.get('温度感スコア', ''),
            'hearing': r.get('【重要】ヒアリング内容', ''),
            'visit_date': r.get('訪問日時', ''),
            'status': r.get('現在のステータス', ''),
            'next_action': r.get('次回アクション', ''),
            'category': '',
            'location': company,
            'source': '2回目以降フォーム',
        })

    # Deduplicate by company (keep latest)
    seen = {}
    for r in all_records:
        norm = normalize_company(r['company'])
        if norm not in seen or r['visit_date'] > seen[norm]['visit_date']:
            seen[norm] = r

    unique_records = list(seen.values())
    print(f'  ユニーク会社数: {len(unique_records)}')

    # 3. Cross-reference
    rep_id_map = {'masaki': MASAKI_ID, 'niimi': NIIMI_ID}

    for rec in unique_records:
        crm_matches = find_in_crm(rec['company'], crm_index)
        if crm_matches:
            # Check if rep is correct
            for deal in crm_matches:
                fields = deal.get('fields', {})
                current_rep = fields.get('担当営業', [])
                current_id = ''
                if isinstance(current_rep, list) and current_rep:
                    current_id = current_rep[0].get('id', '')

                correct_id = rep_id_map.get(rec['rep'], '')
                if correct_id and current_id != correct_id:
                    needs_rep_fix.append({
                        'record_id': deal['record_id'],
                        'company': rec['company'],
                        'correct_rep': rec['rep'],
                        'correct_id': correct_id,
                    })
                else:
                    already_ok += 1
        else:
            not_in_crm.append(rec)

    print(f'\n=== 突合結果 ===')
    print(f'担当正しい: {already_ok}件')
    print(f'担当修正要: {len(needs_rep_fix)}件')
    print(f'CRMにない: {len(not_in_crm)}件')

    # 4. Fix reps
    if needs_rep_fix:
        print(f'\n--- 担当修正 ---')
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        update_url = f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{DEAL_TABLE_ID}/records/batch_update'

        # Deduplicate by record_id
        fix_map = {}
        for fix in needs_rep_fix:
            fix_map[fix['record_id']] = fix
        unique_fixes = list(fix_map.values())

        for fix in unique_fixes[:20]:
            print(f'  {fix["company"]} → {fix["correct_rep"]}')

        # Batch update
        records = [{'record_id': f['record_id'], 'fields': {'担当営業': [{'id': f['correct_id']}]}}
                   for f in unique_fixes]

        success = 0
        for i in range(0, len(records), 50):
            batch = records[i:i+50]
            resp = requests.post(update_url, headers=headers, json={'records': batch})
            data = resp.json()
            if data.get('code') == 0:
                success += len(batch)
            else:
                print(f'  Error: {data.get("msg")}')
            time.sleep(0.3)
        print(f'  修正完了: {success}/{len(unique_fixes)}')

    # 5. Report CRM-missing records
    if not_in_crm:
        print(f'\n--- CRMにないレコード（上位30件） ---')
        for rec in not_in_crm[:30]:
            print(f'  [{rec["rep"]}] {rec["company"]} | {rec["score"]} | {rec["visit_date"]}')

    return needs_rep_fix, not_in_crm


if __name__ == '__main__':
    fixes, missing = main()
