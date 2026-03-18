#!/usr/bin/env python3
"""
AIバリューアップ事業部 CRM テーブル作成
Lark Base APIで3テーブルを既存CRM Baseに追加

Usage:
  python3 ai_valueup_crm_setup.py           # テーブル作成
  python3 ai_valueup_crm_setup.py --check   # 既存テーブル確認
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

BASE_URL = "https://open.larksuite.com/open-apis"


def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def api_get(token, path):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def api_post(token, path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"  API Error {e.code}: {err[:300]}")
        return {"code": e.code, "msg": err}


def list_tables(token):
    """List existing tables in CRM Base"""
    res = api_get(token, f"/bitable/v1/apps/{CRM_BASE_TOKEN}/tables")
    if res.get("code") == 0:
        tables = res["data"].get("items", [])
        print(f"\n既存テーブル ({len(tables)}件):")
        for t in tables:
            print(f"  {t['name']:20s} → {t['table_id']}")
        return tables
    else:
        print(f"  テーブル一覧取得失敗: {res.get('msg', '')[:200]}")
        return []


def create_table(token, name, fields):
    """Create a new table with fields"""
    body = {
        "table": {
            "name": name,
            "default_view_name": "全件",
            "fields": fields
        }
    }
    res = api_post(token, f"/bitable/v1/apps/{CRM_BASE_TOKEN}/tables", body)
    if res.get("code") == 0:
        table_id = res["data"]["table_id"]
        print(f"  ✓ テーブル作成: {name} → {table_id}")
        return table_id
    else:
        print(f"  ✗ テーブル作成失敗: {name} - {res.get('msg', '')[:200]}")
        return None


def setup_tables(token):
    """Create all 3 AI ValueUp tables"""

    # Check existing tables to avoid duplicates
    existing = list_tables(token)
    existing_names = {t["name"] for t in existing}

    results = {}

    # ── Table 1: AI_VU_案件 ──────────────────────────
    table_name = "AI_VU_案件"
    if table_name in existing_names:
        print(f"\n  ⏭ {table_name} は既に存在。スキップ。")
        results[table_name] = next(t["table_id"] for t in existing if t["name"] == table_name)
    else:
        print(f"\n  Creating {table_name}...")
        fields = [
            {"field_name": "案件名", "type": 1},              # Text
            {"field_name": "対象企業名", "type": 1},
            {"field_name": "業種", "type": 3, "property": {    # SingleSelect
                "options": [
                    {"name": "製造業・町工場"},
                    {"name": "税理士・会計事務所"},
                    {"name": "建設・リフォーム"},
                    {"name": "中古車販売"},
                    {"name": "葬儀業"},
                    {"name": "調剤薬局"},
                    {"name": "飲食"},
                    {"name": "農業"},
                    {"name": "その他"},
                ]
            }},
            {"field_name": "従業員数", "type": 2},             # Number
            {"field_name": "年商(万円)", "type": 2},
            {"field_name": "紹介元", "type": 3, "property": {
                "options": [
                    {"name": "会社買取センター"},
                    {"name": "事業承継支援センター"},
                    {"name": "地銀・信金"},
                    {"name": "税理士紹介"},
                    {"name": "Web問い合わせ"},
                    {"name": "直接"},
                    {"name": "その他"},
                ]
            }},
            {"field_name": "ステージ", "type": 3, "property": {
                "options": [
                    {"name": "リード"},
                    {"name": "初回面談"},
                    {"name": "診断中"},
                    {"name": "提案済"},
                    {"name": "契約"},
                    {"name": "実施中"},
                    {"name": "完了"},
                    {"name": "失注"},
                ]
            }},
            {"field_name": "月次固定費(万円)", "type": 2},
            {"field_name": "自動化対象業務", "type": 4, "property": {  # MultiSelect
                "options": [
                    {"name": "CRM・顧客管理"},
                    {"name": "見積・請求"},
                    {"name": "メール自動化"},
                    {"name": "KPIレポート"},
                    {"name": "在庫管理"},
                    {"name": "予約管理"},
                    {"name": "入札スキャン"},
                    {"name": "SEO・Web"},
                    {"name": "工程管理"},
                    {"name": "その他"},
                ]
            }},
            {"field_name": "現在バリュエーション(万円)", "type": 2},
            {"field_name": "目標バリュエーション(万円)", "type": 2},
            {"field_name": "次アクション", "type": 1},
            {"field_name": "次アクション期日", "type": 5},     # Date
            {"field_name": "メモ", "type": 1},
        ]
        tid = create_table(token, table_name, fields)
        results[table_name] = tid
        time.sleep(0.5)

    # ── Table 2: AI_VU_タスク ──────────────────────────
    table_name = "AI_VU_タスク"
    if table_name in existing_names:
        print(f"\n  ⏭ {table_name} は既に存在。スキップ。")
        results[table_name] = next(t["table_id"] for t in existing if t["name"] == table_name)
    else:
        print(f"\n  Creating {table_name}...")
        fields = [
            {"field_name": "タスク名", "type": 1},
            {"field_name": "案件名", "type": 1},              # Manual link (text reference)
            {"field_name": "ステータス", "type": 3, "property": {
                "options": [
                    {"name": "未着手"},
                    {"name": "進行中"},
                    {"name": "完了"},
                    {"name": "保留"},
                ]
            }},
            {"field_name": "フェーズ", "type": 3, "property": {
                "options": [
                    {"name": "M1 可視化"},
                    {"name": "M2 構築"},
                    {"name": "M3 定着"},
                ]
            }},
            {"field_name": "期限", "type": 5},
            {"field_name": "工数(時間)", "type": 2},
            {"field_name": "メモ", "type": 1},
        ]
        tid = create_table(token, table_name, fields)
        results[table_name] = tid
        time.sleep(0.5)

    # ── Table 3: AI_VU_リード ──────────────────────────
    table_name = "AI_VU_リード"
    if table_name in existing_names:
        print(f"\n  ⏭ {table_name} は既に存在。スキップ。")
        results[table_name] = next(t["table_id"] for t in existing if t["name"] == table_name)
    else:
        print(f"\n  Creating {table_name}...")
        fields = [
            {"field_name": "会社名", "type": 1},
            {"field_name": "担当者名", "type": 1},
            {"field_name": "メール", "type": 1},
            {"field_name": "電話", "type": 1},
            {"field_name": "流入元", "type": 3, "property": {
                "options": [
                    {"name": "LP"},
                    {"name": "紹介"},
                    {"name": "セミナー"},
                    {"name": "記事"},
                    {"name": "SNS"},
                    {"name": "電話"},
                    {"name": "その他"},
                ]
            }},
            {"field_name": "関心業種", "type": 4, "property": {
                "options": [
                    {"name": "製造業"},
                    {"name": "税理士"},
                    {"name": "建設"},
                    {"name": "中古車"},
                    {"name": "葬儀"},
                    {"name": "薬局"},
                    {"name": "飲食"},
                    {"name": "その他"},
                ]
            }},
            {"field_name": "ステータス", "type": 3, "property": {
                "options": [
                    {"name": "新規"},
                    {"name": "連絡済"},
                    {"name": "面談済"},
                    {"name": "案件化"},
                    {"name": "失注"},
                ]
            }},
            {"field_name": "初回接触日", "type": 5},
            {"field_name": "メモ", "type": 1},
        ]
        tid = create_table(token, table_name, fields)
        results[table_name] = tid
        time.sleep(0.5)

    return results


def main():
    check_only = "--check" in sys.argv

    print("=" * 60)
    print("AIバリューアップ事業部 CRM テーブルセットアップ")
    print("=" * 60)

    token = get_token()
    print(f"✓ Token取得")

    if check_only:
        list_tables(token)
        return

    results = setup_tables(token)

    print("\n" + "=" * 60)
    print("結果:")
    for name, tid in results.items():
        status = "✓" if tid else "✗"
        print(f"  {status} {name}: {tid or 'FAILED'}")

    # Save table IDs for other scripts
    id_file = SCRIPT_DIR / "ai_valueup_table_ids.json"
    with open(id_file, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nTable IDs saved to: {id_file}")


if __name__ == "__main__":
    main()
