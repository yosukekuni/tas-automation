#!/usr/bin/env python3
"""
AIバリューアップ リード監視（15分毎）
新規リードがLark Baseに追加されたら即座にCEOへLark Bot通知

Usage:
  python3 ai_valueup_lead_monitor.py
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "ai_valueup_monitor_state.json"
TABLE_IDS_FILE = SCRIPT_DIR / "ai_valueup_table_ids.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"
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
    req = urllib.request.Request(f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def send_lark_dm(token, text):
    data = json.dumps({
        "receive_id": CEO_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  DM送信エラー: {e}")


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"known_ids": []}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_lead_table_id():
    if TABLE_IDS_FILE.exists():
        with open(TABLE_IDS_FILE) as f:
            ids = json.load(f)
        return ids.get("AI_VU_リード")
    return None


def main():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] AI ValueUp リード監視")

    table_id = get_lead_table_id()
    if not table_id:
        print("  AI_VU_リード テーブル未作成。スキップ。")
        return

    token = get_token()
    state = load_state()
    known_ids = set(state.get("known_ids", []))

    # Fetch all leads
    url = f"/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
    res = api_get(token, url)
    records = res.get("data", {}).get("items", [])

    new_leads = []
    for rec in records:
        rid = rec["record_id"]
        if rid not in known_ids:
            fields = rec.get("fields", {})
            company = str(fields.get("会社名", "") or "")
            name = str(fields.get("担当者名", "") or "")
            email = str(fields.get("メール", "") or "")
            source = str(fields.get("流入元", "") or "")
            industry = str(fields.get("関心業種", "") or "")

            new_leads.append({
                "rid": rid,
                "company": company,
                "name": name,
                "email": email,
                "source": source,
                "industry": industry,
            })
            known_ids.add(rid)

    if new_leads:
        print(f"  🆕 新規リード: {len(new_leads)}件")

        # Notify CEO
        lines = [f"🆕 AI ValueUp 新規リード ({len(new_leads)}件)"]
        for lead in new_leads:
            lines.append(f"\n• {lead['company']} / {lead['name']}")
            if lead['email']:
                lines.append(f"  📧 {lead['email']}")
            if lead['source']:
                lines.append(f"  流入: {lead['source']}")
            if lead['industry']:
                lines.append(f"  業種: {lead['industry']}")

        send_lark_dm(token, "\n".join(lines))
        print("  CEO通知完了")
    else:
        print("  新規リードなし")

    # Save state
    state["known_ids"] = list(known_ids)
    state["last_check"] = datetime.now().isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
