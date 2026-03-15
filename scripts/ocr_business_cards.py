#!/usr/bin/env python3
"""
名刺OCRスクリプト
Google Drive上の名刺画像をClaude Vision APIでOCR → CRM連絡先テーブルに登録

使い方:
  python scripts/ocr_business_cards.py --dry-run    # OCRのみ（CRM書き込みなし）
  python scripts/ocr_business_cards.py --send        # OCR + CRM連絡先登録
  python scripts/ocr_business_cards.py --send --skip-existing  # 既存連絡先はスキップ
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
import csv
from datetime import datetime

import gspread
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- Config ---
CONFIG_PATH = '/mnt/c/Users/USER/Documents/_data/automation_config.json'
with open(CONFIG_PATH) as f:
    config = json.load(f)

ANTHROPIC_API_KEY = config['anthropic']['api_key']
LARK_APP_ID = config['lark']['app_id']
LARK_APP_SECRET = config['lark']['app_secret']
CRM_BASE_ID = 'BodWbgw6DaHP8FspBTYjT8qSpOe'
CONTACT_TABLE_ID = 'tblN53hFIQoo4W8j'

GOOGLE_CREDS_PATH = '/mnt/c/Users/USER/Documents/_data/google_service_account.json'

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ocr_results')
os.makedirs(RESULTS_DIR, exist_ok=True)

# Rate limiting
CLAUDE_DELAY = 2  # seconds between Claude API calls
LARK_DELAY = 0.3  # seconds between Lark API calls


def get_google_services():
    creds = Credentials.from_service_account_file(
        GOOGLE_CREDS_PATH,
        scopes=['https://www.googleapis.com/auth/spreadsheets',
                'https://www.googleapis.com/auth/drive.readonly'])
    gc = gspread.authorize(creds)
    drive = build('drive', 'v3', credentials=creds)
    return gc, drive


def get_lark_token():
    resp = requests.post(
        'https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': LARK_APP_ID, 'app_secret': LARK_APP_SECRET},
        timeout=10)
    return resp.json()['tenant_access_token']


def get_business_card_entries(gc):
    """スプレッドシートから名刺のファイルIDと客先情報を取得"""
    entries = []

    # 初回フォーム: 名刺=col23(idx23), 会社=col1, 訪問日=col6, メール=col3
    sh1 = gc.open_by_key('1-_FyyH4tuoUs9EJihdmU6PpsXCcVGbv1MeROmrGZrfk')
    vals1 = sh1.sheet1.get_all_values()
    for row in vals1[1:]:
        if len(row) > 23 and row[23].strip():
            company = row[1].strip()
            visit_date = row[6].strip()
            email = row[3].strip()
            rep = 'masaki' if 'amicus' in email else 'niimi' if 'hysy' in email else 'other'
            urls = row[23].strip().split(',')
            for url in urls:
                m = re.search(r'id=([a-zA-Z0-9_-]+)', url.strip())
                if m:
                    entries.append({
                        'file_id': m.group(1),
                        'company': company,
                        'visit_date': visit_date,
                        'rep': rep,
                        'source': '初回フォーム',
                    })

    # 2回目フォーム: 名刺=col22(idx22), 会社=col1
    sh2 = gc.open_by_key('19wPY4AJAbQxw40lbzOcv6KkajKvE9e92HZEs62bwdFo')
    vals2 = sh2.sheet1.get_all_values()
    for row in vals2[1:]:
        if len(row) > 22 and row[22].strip():
            company = row[1].strip()
            visit_date = row[4].strip()
            email = row[2].strip()
            rep = 'masaki' if 'amicus' in email else 'niimi' if 'hysy' in email else 'other'
            urls = row[22].strip().split(',')
            for url in urls:
                m = re.search(r'id=([a-zA-Z0-9_-]+)', url.strip())
                if m:
                    entries.append({
                        'file_id': m.group(1),
                        'company': company,
                        'visit_date': visit_date,
                        'rep': rep,
                        'source': '2回目フォーム',
                    })

    return entries


def download_image(drive, file_id):
    """Google Driveから画像をダウンロード"""
    try:
        meta = drive.files().get(fileId=file_id, fields='name,mimeType,size').execute()
        content = drive.files().get_media(fileId=file_id).execute()
        return content, meta.get('mimeType', 'image/jpeg'), meta.get('name', '')
    except Exception as e:
        print(f"  DL失敗 {file_id}: {e}")
        return None, None, None


def resize_image(image_data, max_bytes=3_800_000):
    """画像が大きすぎる場合にリサイズ"""
    if len(image_data) <= max_bytes:
        return image_data, 'image/jpeg'
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_data))
        # 段階的にリサイズ
        for quality in [85, 70, 50]:
            for scale in [1.0, 0.75, 0.5]:
                buf = io.BytesIO()
                if scale < 1.0:
                    new_size = (int(img.width * scale), int(img.height * scale))
                    resized = img.resize(new_size, Image.LANCZOS)
                else:
                    resized = img
                resized = resized.convert('RGB')
                resized.save(buf, format='JPEG', quality=quality)
                if buf.tell() <= max_bytes:
                    return buf.getvalue(), 'image/jpeg'
        # 最終手段: 小さくする
        buf = io.BytesIO()
        img = img.resize((img.width // 3, img.height // 3), Image.LANCZOS).convert('RGB')
        img.save(buf, format='JPEG', quality=50)
        return buf.getvalue(), 'image/jpeg'
    except ImportError:
        print("  WARNING: Pillow未インストール。リサイズスキップ。")
        return image_data, 'image/jpeg'


def ocr_business_card(image_data, mime_type):
    """Claude Vision APIで名刺をOCR"""
    # base64後5MB超過を防ぐ（raw 3.8MB ≈ base64 5.1MB）
    if len(image_data) > 3_800_000:
        image_data, mime_type = resize_image(image_data)
        print(f"  リサイズ: {len(image_data)/1024:.0f}KB")

    b64 = base64.b64encode(image_data).decode('utf-8')

    # mime_type正規化
    if mime_type not in ['image/jpeg', 'image/png', 'image/gif', 'image/webp']:
        mime_type = 'image/jpeg'

    resp = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers={
            'x-api-key': ANTHROPIC_API_KEY,
            'anthropic-version': '2023-06-01',
            'content-type': 'application/json',
        },
        json={
            'model': 'claude-sonnet-4-20250514',
            'max_tokens': 1024,
            'messages': [{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': mime_type,
                            'data': b64,
                        }
                    },
                    {
                        'type': 'text',
                        'text': '''この名刺の情報を以下のJSON形式で抽出してください。読み取れない項目はnullにしてください。

{
  "company_name": "会社名（正式名称）",
  "person_name": "氏名（漢字）",
  "person_name_kana": "氏名（フリガナ/ローマ字、あれば）",
  "title": "役職",
  "department": "部署",
  "phone": "電話番号（代表/直通）",
  "mobile": "携帯電話番号",
  "fax": "FAX番号",
  "email": "メールアドレス",
  "address": "住所",
  "url": "WebサイトURL"
}

JSONのみを出力してください。説明文は不要です。'''
                    }
                ]
            }]
        },
        timeout=30)

    # 529/overloaded リトライ（最大3回）
    for retry in range(3):
        if resp.status_code != 529:
            break
        wait = 10 * (retry + 1)
        print(f"  Claude API overloaded, retrying in {wait}s... (attempt {retry+2}/4)")
        time.sleep(wait)
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': 'claude-sonnet-4-20250514',
                'max_tokens': 1024,
                'messages': [{
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image',
                            'source': {
                                'type': 'base64',
                                'media_type': mime_type,
                                'data': b64,
                            }
                        },
                        {
                            'type': 'text',
                            'text': '''この名刺の情報を以下のJSON形式で抽出してください。読み取れない項目はnullにしてください。

{
  "company_name": "会社名（正式名称）",
  "person_name": "氏名（漢字）",
  "person_name_kana": "氏名（フリガナ/ローマ字、あれば）",
  "title": "役職",
  "department": "部署",
  "phone": "電話番号（代表/直通）",
  "mobile": "携帯電話番号",
  "fax": "FAX番号",
  "email": "メールアドレス",
  "address": "住所",
  "url": "WebサイトURL"
}

JSONのみを出力してください。説明文は不要です。'''
                        }
                    ]
                }]
            },
            timeout=30)

    if resp.status_code != 200:
        print(f"  Claude API error: {resp.status_code} {resp.text[:200]}")
        return None

    data = resp.json()
    text = data['content'][0]['text']

    # JSONを抽出（配列対応: 複数名刺の場合は最初の1枚を返す）
    # まずコードブロックを除去
    clean_text = re.sub(r'```json\s*', '', text)
    clean_text = re.sub(r'```\s*', '', clean_text)

    # 配列 or オブジェクトを試行
    try:
        parsed = json.loads(clean_text.strip())
        if isinstance(parsed, list):
            return parsed  # 複数名刺→リストとして返す
        return parsed
    except json.JSONDecodeError:
        pass

    # フォールバック: 最初のJSONオブジェクトを抽出
    json_match = re.search(r'\{[\s\S]*?\}(?=\s*[,\]\n]|\s*$)', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            print(f"  JSON parse error: {text[:200]}")
            return None
    return None


def get_existing_contacts(token):
    """既存の連絡先を全件取得してインデックス化"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    contacts = []
    page_token = None

    while True:
        payload = {'page_size': 200}
        if page_token:
            payload['page_token'] = page_token
        resp = requests.post(
            f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE_ID}/records/search',
            headers=headers, json=payload, timeout=15)
        data = resp.json()
        if data.get('code') != 0:
            print(f"Lark error: {data}")
            break
        contacts.extend(data['data'].get('items', []))
        if data['data'].get('has_more'):
            page_token = data['data']['page_token']
        else:
            break
        time.sleep(LARK_DELAY)

    # インデックス: (会社名正規化, 氏名正規化) → record
    index = {}
    for c in contacts:
        f = c.get('fields', {})
        company_raw = f.get('会社名', '')
        name_raw = f.get('氏名', '')
        if isinstance(company_raw, list) and company_raw:
            company_raw = company_raw[0].get('text', '')
        if isinstance(name_raw, list) and name_raw:
            name_raw = name_raw[0].get('text', '')
        if isinstance(company_raw, str) and isinstance(name_raw, str):
            key = (normalize(company_raw), normalize(name_raw))
            index[key] = c
    return index


def normalize(s):
    """正規化: 空白除去、株式会社等除去"""
    if not isinstance(s, str):
        return ''
    s = re.sub(r'[\s　]+', '', s)
    s = s.replace('株式会社', '').replace('（株）', '').replace('(株)', '')
    s = s.replace('有限会社', '').replace('（有）', '').replace('(有)', '')
    return s


def create_contact(token, ocr_data, entry):
    """CRM連絡先テーブルにレコード作成"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    fields = {}

    if ocr_data.get('company_name'):
        fields['会社名'] = ocr_data['company_name']
    elif entry.get('company'):
        fields['会社名'] = entry['company']

    if ocr_data.get('person_name'):
        fields['氏名'] = ocr_data['person_name']

    if ocr_data.get('title'):
        dept = ocr_data.get('department', '') or ''
        title = ocr_data['title']
        fields['役職'] = f"{dept}　{title}".strip() if dept else title

    if ocr_data.get('email'):
        fields['メールアドレス'] = ocr_data['email']

    if ocr_data.get('phone'):
        fields['電話番号'] = ocr_data['phone']
    elif ocr_data.get('mobile'):
        fields['電話番号'] = ocr_data['mobile']

    # 備考にOCR全情報を記録
    memo_parts = []
    if ocr_data.get('address'):
        memo_parts.append(f"住所: {ocr_data['address']}")
    if ocr_data.get('mobile') and ocr_data.get('phone'):
        memo_parts.append(f"携帯: {ocr_data['mobile']}")
    if ocr_data.get('fax'):
        memo_parts.append(f"FAX: {ocr_data['fax']}")
    if ocr_data.get('url'):
        memo_parts.append(f"URL: {ocr_data['url']}")
    if ocr_data.get('person_name_kana'):
        memo_parts.append(f"フリガナ: {ocr_data['person_name_kana']}")
    memo_parts.append(f"[名刺OCR] {entry.get('visit_date','')} {entry.get('source','')}")
    fields['備考・メモ'] = '\n'.join(memo_parts)

    if not fields.get('氏名'):
        return None, "氏名なし"

    payload = {'fields': fields}
    resp = requests.post(
        f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE_ID}/records',
        headers=headers, json=payload, timeout=10)
    data = resp.json()
    if data.get('code') == 0:
        return data['data']['record']['record_id'], None
    else:
        return None, data.get('msg', 'unknown error')


def main():
    parser = argparse.ArgumentParser(description='名刺OCR → CRM連絡先登録')
    parser.add_argument('--send', action='store_true', help='CRM連絡先テーブルに登録')
    parser.add_argument('--dry-run', action='store_true', help='OCRのみ（デフォルト）')
    parser.add_argument('--skip-existing', action='store_true', help='既存連絡先はスキップ')
    parser.add_argument('--limit', type=int, default=0, help='処理件数制限（0=全件）')
    parser.add_argument('--resume', type=int, default=0, help='指定インデックスから再開')
    parser.add_argument('--retry-csv', type=str, default='', help='前回結果CSVからOCR_FAILのみリトライ')
    args = parser.parse_args()

    if not args.send:
        args.dry_run = True

    print(f"=== 名刺OCR {'(dry-run)' if args.dry_run else '→ CRM登録'} ===")
    print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Google services
    gc, drive = get_google_services()

    # スプレッドシートから名刺エントリ取得
    print("スプレッドシート読み込み中...")
    entries = get_business_card_entries(gc)
    print(f"  名刺エントリ: {len(entries)}件")

    # 重複除去（同じfile_idは1回だけ）
    seen_ids = set()
    unique_entries = []
    for e in entries:
        if e['file_id'] not in seen_ids:
            seen_ids.add(e['file_id'])
            unique_entries.append(e)
    entries = unique_entries
    print(f"  ユニーク: {len(entries)}件")

    # retry-csv: 前回失敗分のみフィルタ
    if args.retry_csv:
        fail_ids = set()
        with open(args.retry_csv, 'r', encoding='utf-8-sig') as rf:
            reader = csv.DictReader(rf)
            for row in reader:
                if row.get('status') in ('OCR_FAIL', 'DL_FAIL'):
                    fail_ids.add(row['file_id'])
        entries = [e for e in entries if e['file_id'] in fail_ids]
        print(f"  リトライ対象: {len(entries)}件 (from {args.retry_csv})")

    # 既存連絡先
    existing_index = {}
    if args.skip_existing or not args.dry_run:
        print("既存連絡先読み込み中...")
        lark_token = get_lark_token()
        existing_index = get_existing_contacts(lark_token)
        print(f"  既存: {len(existing_index)}件")
    else:
        lark_token = get_lark_token()

    # resume
    start_idx = args.resume
    if start_idx > 0:
        print(f"  インデックス {start_idx} から再開")

    # 処理件数
    end_idx = len(entries) if args.limit == 0 else min(start_idx + args.limit, len(entries))

    # 結果CSVファイル
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = os.path.join(RESULTS_DIR, f'ocr_results_{timestamp}.csv')
    csv_file = open(csv_path, 'w', newline='', encoding='utf-8-sig')
    writer = csv.writer(csv_file)
    writer.writerow(['idx', 'file_id', 'company_sheets', 'company_ocr', 'person_name',
                     'title', 'phone', 'email', 'address', 'status', 'record_id'])

    stats = {'ocr_ok': 0, 'ocr_fail': 0, 'dl_fail': 0, 'created': 0, 'skipped': 0, 'error': 0}

    for i in range(start_idx, end_idx):
        entry = entries[i]
        print(f"\n[{i+1}/{len(entries)}] {entry['company']} ({entry['rep']})")

        # ダウンロード
        image_data, mime_type, filename = download_image(drive, entry['file_id'])
        if not image_data:
            stats['dl_fail'] += 1
            writer.writerow([i, entry['file_id'], entry['company'], '', '', '', '', '', '', 'DL_FAIL', ''])
            continue

        print(f"  DL: {filename} ({len(image_data)/1024:.0f}KB)")

        # 非画像ファイルをスキップ（音声ファイル等が混在）
        if mime_type and not mime_type.startswith('image/'):
            print(f"  → 画像ではないためスキップ ({mime_type})")
            stats['skipped'] += 1
            writer.writerow([i, entry['file_id'], entry['company'], '', '', '', '', '', '', f'SKIP_NOT_IMAGE:{mime_type}', ''])
            continue

        # OCR
        ocr_data = ocr_business_card(image_data, mime_type)
        time.sleep(CLAUDE_DELAY)

        if not ocr_data:
            stats['ocr_fail'] += 1
            writer.writerow([i, entry['file_id'], entry['company'], '', '', '', '', '', '', 'OCR_FAIL', ''])
            continue

        # 複数名刺対応（リストの場合は全件処理）
        cards = ocr_data if isinstance(ocr_data, list) else [ocr_data]
        stats['ocr_ok'] += 1

        for card_idx, card in enumerate(cards):
            company_ocr = card.get('company_name', '') or ''
            person_name = card.get('person_name', '') or ''
            title = card.get('title', '') or ''
            phone = card.get('phone', '') or card.get('mobile', '') or ''
            email = card.get('email', '') or ''
            address = card.get('address', '') or ''

            suffix = f" [card {card_idx+1}/{len(cards)}]" if len(cards) > 1 else ""
            print(f"  OCR{suffix}: {company_ocr} | {person_name} | {title} | {phone} | {email}")

            # 既存チェック
            if args.skip_existing and person_name:
                key = (normalize(company_ocr or entry['company']), normalize(person_name))
                if key in existing_index:
                    print(f"  → 既存スキップ")
                    stats['skipped'] += 1
                    writer.writerow([i, entry['file_id'], entry['company'], company_ocr, person_name,
                                    title, phone, email, address, 'SKIPPED', ''])
                    continue

            # CRM登録
            if args.send and person_name:
                record_id, err = create_contact(lark_token, card, entry)
                time.sleep(LARK_DELAY)
                if record_id:
                    print(f"  → CRM登録: {record_id}")
                    stats['created'] += 1
                    writer.writerow([i, entry['file_id'], entry['company'], company_ocr, person_name,
                                    title, phone, email, address, 'CREATED', record_id])
                    key = (normalize(company_ocr or entry['company']), normalize(person_name))
                    existing_index[key] = True
                else:
                    print(f"  → CRM登録失敗: {err}")
                    stats['error'] += 1
                    writer.writerow([i, entry['file_id'], entry['company'], company_ocr, person_name,
                                    title, phone, email, address, f'ERROR:{err}', ''])
            elif not person_name:
                print(f"  → 氏名なしスキップ")
                stats['skipped'] += 1
                writer.writerow([i, entry['file_id'], entry['company'], company_ocr, person_name,
                                title, phone, email, address, 'NO_NAME', ''])
            else:
                writer.writerow([i, entry['file_id'], entry['company'], company_ocr, person_name,
                                title, phone, email, address, 'DRY_RUN', ''])

    csv_file.close()

    print(f"\n=== 完了 ===")
    print(f"OCR成功: {stats['ocr_ok']} / OCR失敗: {stats['ocr_fail']} / DL失敗: {stats['dl_fail']}")
    print(f"CRM登録: {stats['created']} / スキップ: {stats['skipped']} / エラー: {stats['error']}")
    print(f"結果CSV: {csv_path}")
    print(f"終了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
