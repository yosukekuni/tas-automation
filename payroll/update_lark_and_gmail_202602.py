#!/usr/bin/env python3
"""
2026年2月度 給与確定 - Lark Base更新 + Gmail下書き作成

1. 経費精算ログテーブル (tbliYwPFbxxINAfk): 漏れていた2月分を追加
2. 給与計算テーブル (tbllGwzN1GWwdd4L): 経費精算・差引支払額を更新
3. Gmail下書き作成 (HTML形式)
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ==================== 設定 ====================
LARK_API_BASE = "https://open.larksuite.com/open-apis"
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
TABLE_EXPENSE_LOG = "tbliYwPFbxxINAfk"
TABLE_PAYROLL = "tbllGwzN1GWwdd4L"


def load_lark_config():
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        Path("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/automation_config.json"),
    ]:
        if p.exists():
            with open(p) as f:
                cfg = json.load(f)
            if not str(cfg.get("lark", {}).get("app_id", "")).startswith("${"):
                return cfg
    return {
        "lark": {
            "app_id": os.environ.get("LARK_APP_ID", ""),
            "app_secret": os.environ.get("LARK_APP_SECRET", ""),
        }
    }


def lark_api(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    encoded = json.dumps(data).encode() if data else None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=encoded, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                if result.get("code", 0) != 0:
                    print(f"  API error: code={result.get('code')} msg={result.get('msg')}")
                    if attempt < 2:
                        time.sleep(3)
                        continue
                return result
        except Exception as e:
            print(f"  API request failed (attempt {attempt+1}): {e}")
            if attempt < 2:
                time.sleep(3)
            else:
                raise
    return None


def get_token(config):
    result = lark_api(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": config["lark"]["app_id"], "app_secret": config["lark"]["app_secret"]},
    )
    return result["tenant_access_token"]


# ==================== Task 1: 経費精算ログテーブル ====================
def get_existing_expense_records(token):
    """既存の経費精算レコードを取得して申請IDを確認"""
    search_body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "対象者", "operator": "contains", "value": ["新美"]},
            ],
        },
        "page_size": 100,
    }
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_EXPENSE_LOG}/records/search",
        method="POST", data=search_body, token=token,
    )
    if result and result.get("code") == 0:
        items = result.get("data", {}).get("items", [])
        print(f"  既存経費精算レコード: {len(items)}件")
        return items
    return []


def get_expense_table_fields(token):
    """テーブルのフィールド定義を取得"""
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_EXPENSE_LOG}/fields",
        method="GET", token=token,
    )
    if result and result.get("code") == 0:
        fields = result.get("data", {}).get("items", [])
        print(f"  経費精算テーブル フィールド数: {len(fields)}")
        for f in fields:
            print(f"    {f.get('field_name')}: {f.get('type')} (id={f.get('field_id')})")
        return fields
    return []


def create_expense_records(token, records_to_add):
    """経費精算レコードをバッチ作成"""
    if not records_to_add:
        print("  追加レコードなし")
        return

    # バッチ作成（最大500件/回）
    data = {"records": [{"fields": r} for r in records_to_add]}
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_EXPENSE_LOG}/records/batch_create",
        method="POST", data=data, token=token,
    )
    if result and result.get("code") == 0:
        created = result.get("data", {}).get("records", [])
        print(f"  経費精算レコード {len(created)}件 作成完了")
    else:
        print(f"  経費精算レコード作成エラー: {result}")


# ==================== Task 2: 給与計算テーブル ====================
def get_payroll_fields(token):
    """給与計算テーブルのフィールド定義を取得"""
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/fields",
        method="GET", token=token,
    )
    if result and result.get("code") == 0:
        fields = result.get("data", {}).get("items", [])
        print(f"  給与計算テーブル フィールド数: {len(fields)}")
        for f in fields:
            print(f"    {f.get('field_name')}: {f.get('type')} (id={f.get('field_id')})")
        return fields
    return []


def find_payroll_record(token, month="2602"):
    """給与計算テーブルから対象月レコードを検索"""
    search_body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "対象月", "operator": "is", "value": [month]},
                {"field_name": "対象者", "operator": "contains", "value": ["新美"]},
            ],
        },
        "page_size": 10,
    }
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/records/search",
        method="POST", data=search_body, token=token,
    )
    if result and result.get("code") == 0:
        items = result.get("data", {}).get("items", [])
        if items:
            rec = items[0]
            print(f"  給与計算レコード発見: record_id={rec.get('record_id')}")
            fields = rec.get("fields", {})
            for k, v in fields.items():
                print(f"    {k}: {v}")
            return rec
    print("  給与計算レコードが見つかりません")
    return None


def update_payroll_record(token, record_id, update_fields):
    """給与計算レコードを更新"""
    data = {"fields": update_fields}
    result = lark_api(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/records/{record_id}",
        method="PUT", data=data, token=token,
    )
    if result and result.get("code") == 0:
        print(f"  給与計算レコード更新完了: {record_id}")
        return True
    else:
        print(f"  給与計算レコード更新エラー: {result}")
        return False


# ==================== Task 3: Gmail下書き ====================
def create_gmail_draft():
    """Gmail下書きを作成（HTML形式）"""
    import base64
    from email.mime.text import MIMEText
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    import pickle

    # OAuth認証
    SCOPES = ['https://www.googleapis.com/auth/gmail.compose']
    token_path = Path("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/gmail_token.pickle")
    creds_path = Path("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/gmail_credentials.json")

    creds = None
    if token_path.exists():
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, 'wb') as f:
                pickle.dump(creds, f)
        else:
            print("  Gmail OAuth認証が必要です。gmail_token.pickleが見つかりません。")
            return False

    service = build('gmail', 'v1', credentials=creds)

    html_body = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">

<p>新美様</p>

<p>お疲れさまです。東海エアサービスの國本です。<br>
2026年2月度の給与明細をお送りします。</p>

<table style="border-collapse: collapse; width: 100%; margin: 16px 0;">
<tr style="background: #1a365d; color: white;">
  <th style="padding: 8px 12px; text-align: left;">項目</th>
  <th style="padding: 8px 12px; text-align: right;">金額</th>
</tr>
<tr style="background: #f7fafc;">
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0;">基本報酬（現場）</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0;">&yen;111,000</td>
</tr>
<tr>
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0;">基本報酬（内業）</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0;">&yen;10,560</td>
</tr>
<tr style="background: #f7fafc;">
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0;">車両手当</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0;">&yen;7,000</td>
</tr>
<tr>
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0;">経費精算（非課税・全10件）</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0;">&yen;22,205</td>
</tr>
<tr style="background: #f7fafc;">
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0; color: #718096;">課税対象額</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0; color: #718096;">&yen;128,560</td>
</tr>
<tr>
  <td style="padding: 8px 12px; border-bottom: 1px solid #e2e8f0; color: #718096;">源泉徴収税</td>
  <td style="padding: 8px 12px; text-align: right; border-bottom: 1px solid #e2e8f0; color: #718096;">&yen;0</td>
</tr>
<tr style="background: #ebf4ff;">
  <td style="padding: 10px 12px; font-weight: bold; font-size: 1.1em; color: #1a365d;">差引支払額</td>
  <td style="padding: 10px 12px; text-align: right; font-weight: bold; font-size: 1.1em; color: #2b6cb0;">&yen;150,765</td>
</tr>
</table>

<p style="font-size: 0.9em; color: #555;">
<strong>経費精算内訳（全10件）:</strong><br>
ガソリン代 7件: &yen;12,135（809km）<br>
実費精算 3件: &yen;10,070（高速&yen;8,000 / 駐車場&yen;600 / 公共交通機関&yen;1,470）
</p>

<p>お振込は <strong>3月16日</strong> を予定しております。</p>

<p style="font-size: 0.9em; color: #555;">
※ スプレッドシートにも反映済みです。詳細明細は添付PDFまたはスプレッドシートの「2602」シートをご確認ください。
</p>

<p>よろしくお願いいたします。</p>

<p style="font-size: 0.85em; color: #888; border-top: 1px solid #e2e8f0; padding-top: 8px; margin-top: 24px;">
東海エアサービス株式会社<br>
國本 洋輔<br>
info@tokaiair.com
</p>

</body>
</html>"""

    message = MIMEText(html_body, 'html', 'utf-8')
    message['to'] = 'h.niimi@tokaiair.com'
    message['subject'] = '【東海エアサービス】2026年2月度 給与明細'

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()

    print(f"  Gmail下書き作成完了: draft_id={draft.get('id')}")
    return True


# ==================== メイン ====================
def main():
    config = load_lark_config()
    token = get_token(config)
    print(f"Lark token取得完了\n")

    # --- Task 1: 経費精算ログテーブル ---
    print("=== Task 1: 経費精算ログテーブル ===")
    # まずフィールド定義を確認
    expense_fields = get_expense_table_fields(token)

    # 既存レコード確認
    existing = get_existing_expense_records(token)
    existing_ids = set()
    for rec in existing:
        fields = rec.get("fields", {})
        eid = None
        for key in ["申請ID", "ID", "expense_id", "Text"]:
            if key in fields:
                val = fields[key]
                if isinstance(val, list):
                    eid = val[0].get("text", "") if isinstance(val[0], dict) else str(val[0])
                else:
                    eid = str(val)
                break
        if eid:
            existing_ids.add(eid)
    print(f"  既存申請ID: {existing_ids}")

    # 2月分全10件の経費精算データ
    feb_expenses = [
        {"申請ID": "202602020001", "日付": "2026-02-02", "対象者": "新美光", "対象月": "2602",
         "内容": "尾鷲港測量 交通費", "種別": "ガソリン代", "距離km": 421, "金額": 6315},
        {"申請ID": "202602030001", "日付": "2026-02-02", "対象者": "新美光", "対象月": "2602",
         "内容": "尾鷲港 高速道路", "種別": "高速代", "距離km": 0, "金額": 8000},
        {"申請ID": "202602050001", "日付": "2026-02-05", "対象者": "新美光", "対象月": "2602",
         "内容": "昭和区ロケハン+営業", "種別": "ガソリン代", "距離km": 78, "金額": 1170},
        {"申請ID": "202602050002", "日付": "2026-02-05", "対象者": "新美光", "対象月": "2602",
         "内容": "昭和区 駐車場", "種別": "駐車場代", "距離km": 0, "金額": 600},
        {"申請ID": "202602120001", "日付": "2026-02-12", "対象者": "新美光", "対象月": "2602",
         "内容": "営業", "種別": "ガソリン代", "距離km": 70, "金額": 1050},
        {"申請ID": "202602170001", "日付": "2026-02-17", "対象者": "新美光", "対象月": "2602",
         "内容": "営業", "種別": "ガソリン代", "距離km": 89, "金額": 1335},
        {"申請ID": "202602200001", "日付": "2026-02-20", "対象者": "新美光", "対象月": "2602",
         "内容": "営業", "種別": "ガソリン代", "距離km": 79, "金額": 1185},
        {"申請ID": "202602240001", "日付": "2026-02-24", "対象者": "新美光", "対象月": "2602",
         "内容": "営業", "種別": "ガソリン代", "距離km": 8, "金額": 120},
        {"申請ID": "202602250001", "日付": "2026-02-24", "対象者": "新美光", "対象月": "2602",
         "内容": "公共交通機関", "種別": "公共交通機関費", "距離km": 0, "金額": 1470},
        {"申請ID": "202602260001", "日付": "2026-02-26", "対象者": "新美光", "対象月": "2602",
         "内容": "三河エリア営業", "種別": "ガソリン代", "距離km": 64, "金額": 960},
    ]

    # フィールド名をテーブル定義に合わせてマッピング
    field_names = {f.get("field_name") for f in expense_fields}
    print(f"  テーブルフィールド名: {field_names}")

    # 既存にないものだけ追加
    to_add = []
    for exp in feb_expenses:
        if exp["申請ID"] not in existing_ids:
            # フィールド名がテーブルに存在するもののみ設定
            record = {}
            for key, val in exp.items():
                if key in field_names:
                    if key == "日付":
                        # 日付フィールドはミリ秒タイムスタンプに変換
                        from datetime import datetime
                        dt = datetime.strptime(val, "%Y-%m-%d")
                        record[key] = int(dt.timestamp() * 1000)
                    else:
                        record[key] = val
                elif key == "申請ID" and "Text" in field_names:
                    record["Text"] = val
            to_add.append(record)
            print(f"  追加予定: {exp['申請ID']} {exp['内容']}")
        else:
            print(f"  既存: {exp['申請ID']} {exp['内容']}")

    if to_add:
        create_expense_records(token, to_add)
    else:
        print("  2月分の追加レコードなし")

    # --- Task 2: 給与計算テーブル ---
    print("\n=== Task 2: 給与計算テーブル ===")
    payroll_fields = get_payroll_fields(token)
    payroll_field_names = {f.get("field_name") for f in payroll_fields}
    print(f"  給与計算フィールド名: {payroll_field_names}")

    rec = find_payroll_record(token, "2602")
    if rec:
        record_id = rec.get("record_id")
        # 更新フィールドを構築
        update = {}
        field_map = {
            "ガソリン距離km": 809,
            "ガソリン代": 12135,
            "高速代": 8000,
            "駐車場代": 600,
            "公共交通機関費": 1470,
            "経費精算合計": 22205,
            "総支給額": 150765,
            "差引支払額": 150765,
            "ステータス": "確定",
        }
        for key, val in field_map.items():
            if key in payroll_field_names:
                update[key] = val

        if update:
            print(f"  更新フィールド: {update}")
            update_payroll_record(token, record_id, update)
        else:
            print("  更新対象フィールドなし（フィールド名不一致の可能性）")
    else:
        print("  2602のレコードが見つかりません。手動確認が必要です。")

    # --- Task 3: Gmail下書き ---
    print("\n=== Task 3: Gmail下書き ===")
    try:
        create_gmail_draft()
    except Exception as e:
        print(f"  Gmail下書きエラー: {e}")
        print("  → MCP Gmail toolで作成してください")

    print("\n=== 全タスク完了 ===")


if __name__ == "__main__":
    main()
