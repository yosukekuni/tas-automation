#!/usr/bin/env python3
"""
CRM連絡先データ修正・マージスクリプト

1. OCR登録の会社名誤りをスプレッドシート取引先名で補正
2. 簡易レコード（電話・メールなし）とOCRレコードの重複をマージ
3. 完全重複レコードを統合
"""
import csv
import json
import re
import time
import requests
from datetime import datetime

CONFIG_PATH = '/mnt/c/Users/USER/Documents/_data/automation_config.json'
with open(CONFIG_PATH) as f:
    config = json.load(f)

LARK_APP_ID = config['lark']['app_id']
LARK_APP_SECRET = config['lark']['app_secret']
CRM_BASE_ID = 'BodWbgw6DaHP8FspBTYjT8qSpOe'
CONTACT_TABLE_ID = 'tblN53hFIQoo4W8j'
DEAL_TABLE_ID = 'tbl1rM86nAw9l3bP'

LARK_DELAY = 0.3


def get_lark_token():
    resp = requests.post('https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': LARK_APP_ID, 'app_secret': LARK_APP_SECRET})
    return resp.json()['tenant_access_token']


def get_all_records(token, table_id):
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    records = []
    page_token = None
    while True:
        payload = {'page_size': 200}
        if page_token:
            payload['page_token'] = page_token
        data = None
        for attempt in range(3):
            try:
                r = requests.post(
                    f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{table_id}/records/search',
                    headers=headers, json=payload, timeout=30)
                if not r.text:
                    print(f"[WARN] Empty response (attempt {attempt+1}/3), retrying...")
                    time.sleep(5 * (attempt + 1))
                    continue
                data = r.json()
                break
            except (requests.exceptions.RequestException, json.JSONDecodeError, ValueError) as e:
                print(f"[WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if data is None:
            print(f"[ERROR] Failed to fetch records after 3 attempts for table {table_id}")
            break
        if data.get('code') != 0:
            print(f'Lark error: {data}')
            break
        records.extend(data['data'].get('items', []))
        if data['data'].get('has_more'):
            page_token = data['data']['page_token']
        else:
            break
        time.sleep(LARK_DELAY)
    return records


def get_text(val):
    if isinstance(val, list) and val:
        return val[0].get('text', '') if isinstance(val[0], dict) else str(val[0])
    if isinstance(val, str):
        return val
    return ''


def normalize(s):
    if not isinstance(s, str):
        return ''
    s = re.sub(r'[\s\u3000]+', '', s)
    s = s.replace('株式会社', '').replace('（株）', '').replace('(株)', '')
    s = s.replace('有限会社', '').replace('（有）', '').replace('(有)', '')
    return s


def extract_name(raw):
    """簡易レコードの氏名フィールドから実際の名前を抽出"""
    # 「○○部長」「工事部　若林嵩成」等のパターン
    raw = raw.strip()
    # 「部長」「課長」等の役職のみの場合
    if re.match(r'^(事務員|受付|受付女性|不在|不明|作業員|所長|他の作業員|現場の方|留守番.*|派遣.*|部長らしき方)$', raw):
        return None
    # 「工事部長　増田英樹」→「増田英樹」
    m = re.search(r'[　\s]+([^\s　]+[　\s]*[^\s　]+)$', raw)
    if m:
        name = m.group(1).strip()
        # 「○○様」の様を除去
        name = re.sub(r'様$', '', name)
        return name
    # 「代表取締役:北川英明」→「北川英明」
    m = re.search(r'[:：]+\s*(.+)', raw)
    if m:
        name = m.group(1).strip()
        name = re.sub(r'様$', '', name)
        return name
    # 「○○様」→「○○」
    name = re.sub(r'様$', '', raw)
    # 会社名そのままの場合はスキップ
    if normalize(name) == '':
        return None
    return name


def name_match(name1, name2):
    """名前の類似マッチ（姓のみ一致でもOK）"""
    if not name1 or not name2:
        return False
    n1 = re.sub(r'[\s\u3000　]+', '', name1)
    n2 = re.sub(r'[\s\u3000　]+', '', name2)
    if n1 == n2:
        return True
    # 姓だけで一致チェック（2文字以上）
    for n in [n1, n2]:
        if len(n) >= 2:
            other = n2 if n == n1 else n1
            if other.startswith(n[:2]) or n.startswith(other[:2]):
                return True
    return False


def update_record(token, record_id, fields):
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    resp = requests.put(
        f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE_ID}/records/{record_id}',
        headers=headers,
        json={'fields': fields},
        timeout=15)
    data = resp.json()
    if data.get('code') != 0:
        print(f'  UPDATE ERROR: {data.get("msg", data)}')
        return False
    return True


def delete_record(token, record_id):
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    resp = requests.delete(
        f'https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_ID}/tables/{CONTACT_TABLE_ID}/records/{record_id}',
        headers=headers,
        timeout=15)
    data = resp.json()
    if data.get('code') != 0:
        print(f'  DELETE ERROR: {data.get("msg", data)}')
        return False
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser(description='CRM連絡先 修正・マージ')
    parser.add_argument('--execute', action='store_true', help='実際に修正を実行（デフォルトはdry-run）')
    args = parser.parse_args()

    dry_run = not args.execute
    print(f"=== CRM連絡先 修正・マージ {'(dry-run)' if dry_run else '(実行モード)'} ===")
    print(f"開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    token = get_lark_token()

    # 全連絡先取得
    print("連絡先読み込み中...")
    contacts = get_all_records(token, CONTACT_TABLE_ID)
    print(f"  連絡先: {len(contacts)}件")

    # OCRレコードと簡易レコードに分類
    ocr_records = []  # [名刺OCR]マーク付き
    simple_records = []  # 電話・メールなし
    other_records = []

    for c in contacts:
        f = c.get('fields', {})
        memo = get_text(f.get('備考・メモ', ''))
        phone = get_text(f.get('電話番号', ''))
        email = get_text(f.get('メールアドレス', ''))

        if '名刺OCR' in memo:
            ocr_records.append(c)
        elif not phone.strip() and not email.strip():
            simple_records.append(c)
        else:
            other_records.append(c)

    print(f"  OCRレコード: {len(ocr_records)}件")
    print(f"  簡易レコード(連絡先なし): {len(simple_records)}件")
    print(f"  その他: {len(other_records)}件")

    # === STEP 1: OCR会社名補正 ===
    # OCR結果CSVから、スプレッドシート取引先名とOCR会社名の対応を取得
    print("\n--- STEP 1: OCR会社名補正 ---")
    csv_files = [
        'scripts/ocr_results/ocr_results_20260313_225557.csv',
        'scripts/ocr_results/ocr_results_20260313_233225.csv',
    ]

    # file_id → sheets_company のマッピング
    sheets_company_map = {}
    for csv_path in csv_files:
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('status') in ('CREATED', 'SKIPPED'):
                        fid = row.get('file_id', '')
                        sheets_co = row.get('company_sheets', '').strip()
                        ocr_co = row.get('company_ocr', '').strip()
                        if sheets_co and ocr_co and normalize(sheets_co) != normalize(ocr_co):
                            sheets_company_map[ocr_co] = sheets_co
        except FileNotFoundError:
            pass

    company_fixes = 0
    for c in ocr_records:
        f = c.get('fields', {})
        company = get_text(f.get('会社名', ''))
        if company in sheets_company_map:
            correct = sheets_company_map[company]
            print(f"  FIX: [{c['record_id']}] {company} → {correct}")
            if not dry_run:
                update_record(token, c['record_id'], {'会社名': correct})
                time.sleep(LARK_DELAY)
            company_fixes += 1

    print(f"  会社名補正: {company_fixes}件")

    # === STEP 2: 簡易レコードとOCRレコードのマージ ===
    print("\n--- STEP 2: 簡易レコード ↔ OCRレコード マージ ---")

    # OCRレコードのインデックス: (会社名正規化) → [records]
    ocr_by_company = {}
    for c in ocr_records:
        f = c.get('fields', {})
        company = get_text(f.get('会社名', ''))
        key = normalize(company)
        if key not in ocr_by_company:
            ocr_by_company[key] = []
        ocr_by_company[key].append(c)

    merge_count = 0
    delete_candidates = []

    for s in simple_records:
        sf = s.get('fields', {})
        s_company = get_text(sf.get('会社名', ''))
        s_name_raw = get_text(sf.get('氏名', ''))
        s_name = extract_name(s_name_raw)

        if not s_name:
            continue  # 名前が抽出できない場合はスキップ

        # 同じ会社のOCRレコードを検索
        s_key = normalize(s_company)
        ocr_candidates = ocr_by_company.get(s_key, [])

        # 会社名正規化でヒットしない場合、sheets_company_mapの逆引きも試す
        if not ocr_candidates:
            for ocr_co, sheets_co in sheets_company_map.items():
                if normalize(sheets_co) == s_key:
                    ocr_candidates.extend(ocr_by_company.get(normalize(ocr_co), []))

        for oc in ocr_candidates:
            of = oc.get('fields', {})
            o_name = get_text(of.get('氏名', ''))
            o_phone = get_text(of.get('電話番号', ''))
            o_email = get_text(of.get('メールアドレス', ''))
            o_title = get_text(of.get('役職', ''))
            o_memo = get_text(of.get('備考・メモ', ''))

            if name_match(s_name, o_name):
                print(f"  MERGE: [{s['record_id']}] {s_company} | {s_name_raw}")
                print(f"    ← [{oc['record_id']}] {get_text(of.get('会社名',''))} | {o_name} | {o_phone} | {o_email}")

                # 簡易レコードにOCRデータを上書き
                update_fields = {}
                if o_name:
                    update_fields['氏名'] = o_name
                if o_phone:
                    update_fields['電話番号'] = o_phone
                if o_email:
                    update_fields['メールアドレス'] = o_email
                if o_title:
                    update_fields['役職'] = o_title
                if o_memo:
                    # 既存メモを保持しつつOCRメモを追加
                    existing_memo = get_text(sf.get('備考・メモ', ''))
                    if existing_memo:
                        update_fields['備考・メモ'] = existing_memo + '\n' + o_memo
                    else:
                        update_fields['備考・メモ'] = o_memo

                if not dry_run and update_fields:
                    success = update_record(token, s['record_id'], update_fields)
                    time.sleep(LARK_DELAY)
                    if success:
                        # OCRレコードを削除候補に
                        delete_candidates.append(oc['record_id'])
                        merge_count += 1
                else:
                    merge_count += 1
                    delete_candidates.append(oc['record_id'])
                break

    print(f"  マージ対象: {merge_count}件")

    # === STEP 3: 重複削除 ===
    print("\n--- STEP 3: 重複レコード削除 ---")

    # 完全重複の検出（同じ会社+同じ名前、両方連絡先なし）
    seen = {}
    exact_dupes = []
    for c in contacts:
        f = c.get('fields', {})
        company = normalize(get_text(f.get('会社名', '')))
        name = normalize(get_text(f.get('氏名', '')))
        key = (company, name)
        if key in seen and key != ('', ''):
            # 情報が少ない方を削除候補に
            existing = seen[key]
            ef = existing.get('fields', {})
            cf = c.get('fields', {})

            e_info = bool(get_text(ef.get('電話番号', ''))) + bool(get_text(ef.get('メールアドレス', '')))
            c_info = bool(get_text(cf.get('電話番号', ''))) + bool(get_text(cf.get('メールアドレス', '')))

            if c_info >= e_info:
                # 新しい方が情報多い→古い方を削除
                delete_id = existing['record_id']
                seen[key] = c
            else:
                delete_id = c['record_id']

            if delete_id not in delete_candidates:
                exact_dupes.append(delete_id)
                print(f"  DUPE DELETE: {delete_id} ({get_text(f.get('会社名',''))} | {get_text(f.get('氏名',''))})")
        else:
            seen[key] = c

    print(f"  完全重複: {len(exact_dupes)}件")

    # マージ後のOCRレコード削除
    all_deletes = list(set(delete_candidates + exact_dupes))
    print(f"\n--- 削除実行 ---")
    print(f"  削除対象: {len(all_deletes)}件")

    if not dry_run:
        deleted = 0
        for rid in all_deletes:
            if delete_record(token, rid):
                deleted += 1
            time.sleep(LARK_DELAY)
        print(f"  削除完了: {deleted}件")

    # === サマリー ===
    print(f"\n=== 完了 ===")
    print(f"会社名補正: {company_fixes}件")
    print(f"マージ: {merge_count}件")
    print(f"重複削除: {len(exact_dupes)}件")
    print(f"OCRレコード削除（マージ済み）: {len(delete_candidates)}件")
    print(f"{'※ dry-runモード: 実際の変更なし' if dry_run else '実行完了'}")
    print(f"終了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == '__main__':
    main()
