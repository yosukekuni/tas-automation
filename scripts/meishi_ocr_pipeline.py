#!/usr/bin/env python3
"""
名刺OCR → CRM連絡先統合パイプライン
Google Drive上の名刺写真をClaude Vision APIでOCR → CRM連絡先テーブルに新規追加/既存更新

Usage:
    python3 scripts/meishi_ocr_pipeline.py [--dry-run] [--limit N]
"""

import json
import re
import sys
import os
import time
import base64
import argparse
from datetime import datetime

import gspread
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- Config ---
CONFIG_PATH = '/mnt/c/Users/USER/Documents/_data/automation_config.json'
SA_PATH = '/mnt/c/Users/USER/Documents/_data/google_service_account.json'
OUTPUT_DIR = '/mnt/c/Users/USER/Documents/_data/content'
BACKUP_DIR = '/mnt/c/Users/USER/Documents/_data/tas-automation/backups'

CRM_BASE_ID = 'BodWbgw6DaHP8FspBTYjT8qSpOe'
CONTACT_TABLE = 'tblN53hFIQoo4W8j'
DEAL_TABLE = 'tbl1rM86nAw9l3bP'
COMPANY_TABLE = 'tblTfGScQIdLTYxA'

SHEET1_KEY = '1-_FyyH4tuoUs9EJihdmU6PpsXCcVGbv1MeROmrGZrfk'
SHEET2_KEY = '19wPY4AJAbQxw40lbzOcv6KkajKvE9e92HZEs62bwdFo'

NIIMI_ID = 'ou_189dc637b61a83b886d356becb3ae18e'
MASAKI_ID = 'ou_6ee633b968b9229655813af6e3a47e9f'

EMAIL_REP = {
    'amicus_55ikubakka@icloud.com': 'masaki',
    'hysy2131@gmail.com': 'niimi',
    'kurotiku916@gmail.com': 'tamura',
}

GIFU_MIE = ['岐阜', '三重', '四日市', '津市', '桑名', '鈴鹿', '伊勢', '大垣', '各務原',
            '多治見', '松阪', '名張', '亀山', '養老', '菰野', '東員']


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_lark_token(config):
    resp = requests.post(
        'https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': config['lark']['app_id'],
              'app_secret': config['lark']['app_secret']})
    return resp.json().get('tenant_access_token')


def get_drive_service():
    creds = Credentials.from_service_account_file(
        SA_PATH,
        scopes=['https://www.googleapis.com/auth/drive.readonly'])
    return build('drive', 'v3', credentials=creds)


def get_sheets_service():
    creds = Credentials.from_service_account_file(
        SA_PATH,
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.readonly'])
    return gspread.authorize(creds)


def extract_drive_ids(url_text):
    """Extract Google Drive file IDs from URL text"""
    return re.findall(r'id=([a-zA-Z0-9_-]+)', str(url_text))


def determine_rep(email, all_text=''):
    rep = EMAIL_REP.get(email, 'unknown')
    if rep == 'tamura':
        if any(kw in all_text for kw in GIFU_MIE):
            return 'masaki'
        return 'niimi'
    return rep


def normalize_company(name):
    name = name.strip()
    name = re.sub(r'[\s\u3000]+', '', name)
    name = name.replace('株式会社', '').replace('（株）', '').replace('(株)', '')
    name = name.replace('有限会社', '').replace('（有）', '').replace('(有)', '')
    return name


# ─── Phase 1: Extract sheet data with media file IDs ───

def extract_sheet_records(gc):
    """Extract all records from both sheets with media file IDs"""
    print('[1/6] スプレッドシート読み込み中...')

    sh1 = gc.open_by_key(SHEET1_KEY)
    records1 = sh1.sheet1.get_all_records()

    sh2 = gc.open_by_key(SHEET2_KEY)
    records2 = sh2.sheet1.get_all_records()

    all_records = []

    for r in records1:
        company = r.get('客先名（会社名）', '').strip()
        if not company:
            continue
        meishi_urls = str(r.get('名刺', ''))
        audio_urls = str(r.get('ヒアリング内容 音声データ', ''))
        email = r.get('メールアドレス', '')
        all_text = company + ' ' + str(r.get('備考・メモ', '')) + ' ' + str(r.get('訪問先名・現場名', ''))
        all_records.append({
            'company': company,
            'visit_date': r.get('訪問日時', ''),
            'hearing': r.get('【重要】ヒアリング内容', ''),
            'score': str(r.get('温度感スコア', '')),
            'email': email,
            'rep': determine_rep(email, all_text),
            'contact_name': r.get('客先対応者名', ''),
            'decision_maker': r.get('決裁者名', ''),
            'decision_maker_title': r.get('決裁者役職', ''),
            'decision_maker_contact': r.get('決裁者連絡先', ''),
            'category': r.get('客先カテゴリ', ''),
            'status': r.get('現在のステータス', ''),
            'next_action': r.get('次回アクション', ''),
            'location': r.get('訪問先名・現場名', ''),
            'memo': str(r.get('備考・メモ', '')),
            'meishi_ids': extract_drive_ids(meishi_urls),
            'audio_ids': extract_drive_ids(audio_urls),
            'source': 'sheet1'
        })

    for r in records2:
        company = r.get('訪問先名・現場名', '').strip()
        if not company:
            continue
        meishi_urls = str(r.get('名刺', ''))
        audio_urls = str(r.get('ヒアリング内容 音声データ', ''))
        email = r.get('メールアドレス', '')
        all_records.append({
            'company': company,
            'visit_date': r.get('訪問日時', ''),
            'hearing': r.get('【重要】ヒアリング内容', ''),
            'score': str(r.get('温度感スコア', '')),
            'email': email,
            'rep': determine_rep(email, company),
            'contact_name': '',
            'decision_maker': r.get('決裁者名', ''),
            'decision_maker_title': r.get('決裁者役職', ''),
            'decision_maker_contact': r.get('決裁者連絡先', ''),
            'category': '',
            'status': r.get('現在のステータス', ''),
            'next_action': r.get('次回アクション', ''),
            'location': company,
            'memo': str(r.get('備考・メモ', '')),
            'meishi_ids': extract_drive_ids(meishi_urls),
            'audio_ids': extract_drive_ids(audio_urls),
            'source': 'sheet2'
        })

    with_meishi = [r for r in all_records if r['meishi_ids']]
    with_audio = [r for r in all_records if r['audio_ids']]
    print(f'  全レコード: {len(all_records)}件')
    print(f'  名刺あり: {len(with_meishi)}件 ({sum(len(r["meishi_ids"]) for r in with_meishi)}ファイル)')
    print(f'  音声あり: {len(with_audio)}件 ({sum(len(r["audio_ids"]) for r in with_audio)}ファイル)')

    return all_records


# ─── Phase 2: OCR name cards with Claude Vision API ───

def ocr_name_card(drive_service, config, file_id):
    """Download and OCR a single name card image"""
    try:
        # Get file metadata
        meta = drive_service.files().get(fileId=file_id, fields='id,name,mimeType,size').execute()
        mime = meta.get('mimeType', '')
        if not mime.startswith('image/'):
            return None, f'Not an image: {mime}'

        # Download
        content = drive_service.files().get_media(fileId=file_id).execute()
        if len(content) > 10_000_000:  # 10MB limit
            return None, f'File too large: {len(content)} bytes'

        # OCR with Claude Vision
        b64 = base64.b64encode(content).decode()
        resp = requests.post('https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': config['anthropic']['api_key'],
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 1024,
                'messages': [{
                    'role': 'user',
                    'content': [{
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': mime, 'data': b64}
                    }, {
                        'type': 'text',
                        'text': ('この名刺から以下の情報をJSON形式で抽出してください。'
                                 '読めない項目はnullにしてください。余計なテキストは不要です。JSONのみ返してください。\n'
                                 '{"company": "会社名", "name": "氏名", "title": "役職", '
                                 '"department": "部署", "phone": "電話番号", "mobile": "携帯番号", '
                                 '"email": "メールアドレス", "address": "住所", "fax": "FAX番号", '
                                 '"url": "Webサイト"}')
                    }]
                }]
            },
            timeout=30)

        result = resp.json()
        if 'content' not in result:
            return None, f'API error: {result.get("error", result)}'

        text = result['content'][0]['text']
        # Extract JSON from response (may have markdown code block)
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            ocr_data = json.loads(json_match.group())
            ocr_data['_file_id'] = file_id
            ocr_data['_file_name'] = meta.get('name', '')
            return ocr_data, None
        return None, f'No JSON found in response: {text[:200]}'

    except Exception as e:
        return None, f'Error: {str(e)}'


def run_ocr_batch(records, drive_service, config, limit=None):
    """Run OCR on all name card images"""
    print('[2/6] 名刺OCR実行中...')

    meishi_records = [r for r in records if r['meishi_ids']]
    if limit:
        meishi_records = meishi_records[:limit]

    all_ocr_results = []
    errors = []
    processed = 0
    total_files = sum(len(r['meishi_ids']) for r in meishi_records)

    for rec in meishi_records:
        for file_id in rec['meishi_ids']:
            processed += 1
            print(f'  [{processed}/{total_files}] {rec["company"]} ({file_id[:12]}...)', end='', flush=True)

            ocr_data, err = ocr_name_card(drive_service, config, file_id)
            if ocr_data:
                ocr_data['_sheet_company'] = rec['company']
                ocr_data['_sheet_rep'] = rec['rep']
                ocr_data['_sheet_score'] = rec['score']
                ocr_data['_visit_date'] = rec['visit_date']
                all_ocr_results.append(ocr_data)
                print(f' -> {ocr_data.get("name", "?")} ({ocr_data.get("company", "?")})')
            else:
                errors.append({'file_id': file_id, 'company': rec['company'], 'error': err})
                print(f' -> ERROR: {err}')

            time.sleep(0.5)  # Rate limit

    print(f'  OCR完了: {len(all_ocr_results)}件成功 / {len(errors)}件エラー')

    # Save OCR results
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    ocr_path = os.path.join(BACKUP_DIR, f'meishi_ocr_{ts}.json')
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(ocr_path, 'w') as f:
        json.dump({'results': all_ocr_results, 'errors': errors}, f, ensure_ascii=False, indent=2)
    print(f'  OCR結果保存: {ocr_path}')

    return all_ocr_results, errors


# ─── Phase 3: Fetch CRM contacts for deduplication ───

def fetch_crm_contacts(token):
    """Fetch all CRM contacts"""
    print('[3/6] CRM連絡先取得中...')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE}/records/search'

    all_contacts = []
    page_token = None
    for _ in range(20):
        payload = {'page_size': 200}
        if page_token:
            payload['page_token'] = page_token
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        if data.get('code') == 0:
            all_contacts.extend(data['data'].get('items', []))
            if not data['data'].get('has_more'):
                break
            page_token = data['data']['page_token']
        else:
            print(f'  Error: {data}')
            break
        time.sleep(0.2)

    print(f'  CRM連絡先: {len(all_contacts)}件')
    return all_contacts


def fetch_crm_deals(token):
    """Fetch all CRM deals"""
    print('  CRM商談取得中...')
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{DEAL_TABLE}/records/search'

    all_deals = []
    page_token = None
    seen_ids = set()
    for _ in range(20):
        payload = {'page_size': 200}
        if page_token:
            payload['page_token'] = page_token
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        data = resp.json()
        if data.get('code') == 0:
            for item in data['data'].get('items', []):
                if item['record_id'] not in seen_ids:
                    seen_ids.add(item['record_id'])
                    all_deals.append(item)
            if not data['data'].get('has_more'):
                break
            page_token = data['data']['page_token']
        else:
            print(f'  Error: {data}')
            break
        time.sleep(0.2)

    print(f'  CRM商談: {len(all_deals)}件')
    return all_deals


# ─── Phase 4: Deduplication and matching ───

def build_contact_index(contacts):
    """Build index for contact deduplication"""
    index = {
        'by_email': {},
        'by_phone': {},
        'by_name_company': {},
    }

    for c in contacts:
        fields = c.get('fields', {})

        # Email index
        email_val = fields.get('メールアドレス', '')
        if isinstance(email_val, list) and email_val:
            for ev in email_val:
                if isinstance(ev, dict):
                    email = ev.get('text', '').lower().strip()
                    if email:
                        index['by_email'][email] = c

        # Phone index
        phone_val = fields.get('電話番号', '')
        if isinstance(phone_val, str):
            phone_clean = re.sub(r'[\s\-\(\)]+', '', phone_val)
            if phone_clean:
                index['by_phone'][phone_clean] = c

        # Name + company index
        name_val = fields.get('氏名', '')
        company_val = fields.get('会社名', '')
        name = ''
        company = ''
        if isinstance(name_val, list) and name_val:
            name = name_val[0].get('text', '') if isinstance(name_val[0], dict) else str(name_val[0])
        if isinstance(company_val, list) and company_val:
            company = company_val[0].get('text', '') if isinstance(company_val[0], dict) else str(company_val[0])

        if name and company:
            key = normalize_company(company) + '_' + name.replace(' ', '').replace('\u3000', '')
            index['by_name_company'][key] = c

    return index


def find_existing_contact(ocr_data, index):
    """Check if OCR result matches existing CRM contact"""
    # Match by email (strongest)
    email = (ocr_data.get('email') or '').lower().strip()
    if email and email in index['by_email']:
        return index['by_email'][email], 'email'

    # Match by phone
    for phone_field in ['phone', 'mobile']:
        phone = ocr_data.get(phone_field) or ''
        phone_clean = re.sub(r'[\s\-\(\)]+', '', phone)
        if phone_clean and phone_clean in index['by_phone']:
            return index['by_phone'][phone_clean], 'phone'

    # Match by name + company
    name = (ocr_data.get('name') or '').replace(' ', '').replace('\u3000', '')
    company = normalize_company(ocr_data.get('company') or '')
    if name and company:
        key = company + '_' + name
        if key in index['by_name_company']:
            return index['by_name_company'][key], 'name_company'

    return None, None


def deduplicate_ocr_results(ocr_results, contact_index):
    """Classify OCR results as new or existing"""
    print('[4/6] 重複チェック中...')

    new_contacts = []
    existing_updates = []
    skipped = []

    # Also deduplicate within OCR results themselves
    seen_emails = set()
    seen_names = set()

    for ocr in ocr_results:
        email = (ocr.get('email') or '').lower().strip()
        name = (ocr.get('name') or '').replace(' ', '').replace('\u3000', '')
        company = normalize_company(ocr.get('company') or '')

        # Skip if no useful data
        if not name and not email:
            skipped.append({'data': ocr, 'reason': 'no name or email'})
            continue

        # Check internal duplicates
        dedup_key = email if email else (company + '_' + name)
        if email and email in seen_emails:
            skipped.append({'data': ocr, 'reason': 'duplicate within batch (email)'})
            continue
        if not email and dedup_key in seen_names:
            skipped.append({'data': ocr, 'reason': 'duplicate within batch (name)'})
            continue

        if email:
            seen_emails.add(email)
        seen_names.add(dedup_key)

        # Check CRM
        existing, match_type = find_existing_contact(ocr, contact_index)
        if existing:
            existing_updates.append({
                'ocr': ocr,
                'existing': existing,
                'match_type': match_type
            })
        else:
            new_contacts.append(ocr)

    print(f'  新規連絡先: {len(new_contacts)}件')
    print(f'  既存更新候補: {len(existing_updates)}件')
    print(f'  スキップ: {len(skipped)}件')

    return new_contacts, existing_updates, skipped


# ─── Phase 5: CRM operations ───

def build_contact_record(ocr):
    """Build CRM contact record from OCR data"""
    rep_map = {'masaki': MASAKI_ID, 'niimi': NIIMI_ID}

    fields = {}

    # 会社名
    company = ocr.get('company') or ocr.get('_sheet_company', '')
    if company:
        fields['会社名'] = company

    # 氏名
    name = ocr.get('name', '')
    if name:
        fields['氏名'] = name

    # 役職
    parts = []
    if ocr.get('department'):
        parts.append(ocr['department'])
    if ocr.get('title'):
        parts.append(ocr['title'])
    if parts:
        fields['役職'] = ' '.join(parts)

    # メールアドレス
    email = ocr.get('email', '')
    if email:
        fields['メールアドレス'] = email

    # 電話番号
    phones = []
    if ocr.get('phone'):
        phones.append(ocr['phone'])
    if ocr.get('mobile'):
        phones.append(ocr['mobile'])
    if phones:
        fields['電話番号'] = ' / '.join(phones)

    # 営業担当
    rep_id = rep_map.get(ocr.get('_sheet_rep', ''))
    if rep_id:
        fields['営業担当'] = [{'id': rep_id}]

    # 接触チャネル
    fields['接触チャネル'] = '飛び込み営業'

    # 温度感スコア
    score = ocr.get('_sheet_score', '')
    if score and score != '' and score != 'nan':
        fields['温度感スコア'] = score

    # 備考
    memo_parts = []
    if ocr.get('address'):
        memo_parts.append(f'住所: {ocr["address"]}')
    if ocr.get('fax'):
        memo_parts.append(f'FAX: {ocr["fax"]}')
    if ocr.get('url'):
        memo_parts.append(f'Web: {ocr["url"]}')
    memo_parts.append(f'名刺OCR取込 ({datetime.now().strftime("%Y-%m-%d")})')
    if ocr.get('_file_name'):
        memo_parts.append(f'ファイル: {ocr["_file_name"]}')
    fields['備考・メモ'] = '\n'.join(memo_parts)

    return fields


def create_contacts_batch(token, new_contacts, dry_run=False):
    """Create new contacts in CRM"""
    print('[5/6] CRM連絡先作成中...')

    if not new_contacts:
        print('  新規連絡先なし')
        return []

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    url = f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE}/records/batch_create'

    created = []
    for i in range(0, len(new_contacts), 50):
        batch = new_contacts[i:i+50]
        records = [{'fields': build_contact_record(ocr)} for ocr in batch]

        if dry_run:
            for rec in records:
                f = rec['fields']
                print(f'  [DRY] {f.get("会社名", "?")} / {f.get("氏名", "?")} / {f.get("メールアドレス", "")}')
            created.extend(batch)
            continue

        resp = requests.post(url, headers=headers, json={'records': records}, timeout=30)
        data = resp.json()
        if data.get('code') == 0:
            created.extend(batch)
            print(f'  バッチ {i//50+1}: {len(batch)}件作成完了')
        else:
            print(f'  バッチ {i//50+1}: エラー: {data.get("msg", data)}')
        time.sleep(0.3)

    print(f'  作成完了: {len(created)}/{len(new_contacts)}件')
    return created


# ─── Phase 6: Report ───

def generate_report(all_records, ocr_results, errors, new_contacts, existing_updates, skipped, created):
    """Generate integration report"""
    print('[6/6] レポート生成中...')

    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    report = f"""# スプレッドシート名刺OCR → CRM統合レポート
生成日時: {ts}

## 概要
| 項目 | 件数 |
|------|------|
| スプレッドシートレコード数 | {len(all_records)} |
| 名刺ファイル数 | {sum(len(r['meishi_ids']) for r in all_records)} |
| OCR成功 | {len(ocr_results)} |
| OCRエラー | {len(errors)} |
| 新規連絡先（CRM追加） | {len(new_contacts)} |
| 既存連絡先（CRM既存） | {len(existing_updates)} |
| スキップ（重複等） | {len(skipped)} |
| CRM作成完了 | {len(created)} |

## 新規追加連絡先一覧
| 会社名 | 氏名 | 役職 | メール | 電話 |
|--------|------|------|--------|------|
"""
    for ocr in new_contacts:
        company = ocr.get('company', '-')
        name = ocr.get('name', '-')
        title = ocr.get('title', '-')
        email = ocr.get('email', '-')
        phone = ocr.get('phone', '-') or ocr.get('mobile', '-')
        report += f'| {company} | {name} | {title} | {email} | {phone} |\n'

    if existing_updates:
        report += f"""
## 既存連絡先（更新不要）
| 会社名 | 氏名 | マッチ方法 |
|--------|------|-----------|
"""
        for item in existing_updates:
            ocr = item['ocr']
            report += f'| {ocr.get("company", "-")} | {ocr.get("name", "-")} | {item["match_type"]} |\n'

    if errors:
        report += f"""
## OCRエラー
| 会社名 | ファイルID | エラー |
|--------|-----------|--------|
"""
        for err in errors:
            report += f'| {err["company"]} | {err["file_id"][:20]}... | {err["error"][:50]} |\n'

    if skipped:
        report += f"""
## スキップ
| 理由 | 件数 |
|------|------|
"""
        reasons = {}
        for s in skipped:
            r = s['reason']
            reasons[r] = reasons.get(r, 0) + 1
        for reason, count in reasons.items():
            report += f'| {reason} | {count} |\n'

    report += f"""
## 音声データ（未処理）
| 項目 | 件数 |
|------|------|
| 音声ファイル数 | {sum(len(r['audio_ids']) for r in all_records)} |
| 音声付きレコード数 | {sum(1 for r in all_records if r['audio_ids'])} |

> 音声データの文字起こし・要約は別パイプライン（audio_transcription_pipeline.py）で処理予定。
> Whisper API または Google Speech-to-Text の導入が必要。
"""

    output_path = os.path.join(OUTPUT_DIR, 'sheets_media_integration.md')
    with open(output_path, 'w') as f:
        f.write(report)
    print(f'  レポート保存: {output_path}')

    return report


# ─── Main ───

def main():
    parser = argparse.ArgumentParser(description='名刺OCR → CRM連絡先統合')
    parser.add_argument('--dry-run', action='store_true', help='CRM書き込みをスキップ')
    parser.add_argument('--limit', type=int, help='処理する名刺レコード数の上限')
    parser.add_argument('--skip-ocr', action='store_true', help='OCRをスキップし保存済み結果を使用')
    parser.add_argument('--ocr-file', type=str, help='OCR結果JSONファイルパス')
    args = parser.parse_args()

    print('=' * 60)
    print('名刺OCR → CRM連絡先統合パイプライン')
    print('=' * 60)
    if args.dry_run:
        print('  *** DRY RUN モード ***')

    config = load_config()
    token = get_lark_token(config)

    # Phase 1: Extract sheet data
    gc = get_sheets_service()
    all_records = extract_sheet_records(gc)

    # Phase 2: OCR
    if args.skip_ocr and args.ocr_file:
        print('[2/6] 保存済みOCR結果を読み込み中...')
        with open(args.ocr_file) as f:
            ocr_data = json.load(f)
        ocr_results = ocr_data['results']
        errors = ocr_data.get('errors', [])
        print(f'  OCR結果: {len(ocr_results)}件 / エラー: {len(errors)}件')
    else:
        drive = get_drive_service()
        ocr_results, errors = run_ocr_batch(all_records, drive, config, limit=args.limit)

    # Phase 3: Fetch CRM contacts
    contacts = fetch_crm_contacts(token)
    contact_index = build_contact_index(contacts)

    # Phase 4: Deduplication
    new_contacts, existing_updates, skipped = deduplicate_ocr_results(ocr_results, contact_index)

    # Phase 5: CRM creation
    created = create_contacts_batch(token, new_contacts, dry_run=args.dry_run)

    # Phase 6: Report
    report = generate_report(all_records, ocr_results, errors, new_contacts, existing_updates, skipped, created)

    print('\n' + '=' * 60)
    print('パイプライン完了')
    print('=' * 60)

    return new_contacts, existing_updates, errors


if __name__ == '__main__':
    main()
