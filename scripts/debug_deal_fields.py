#!/usr/bin/env python3
"""
Diagnostic: Dump field structure of recent deals to understand data format.
Run in GitHub Actions: python scripts/debug_deal_fields.py
"""
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
TABLE_DEALS = "tbl1rM86nAw9l3bP"

def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]

def main():
    token = lark_get_token()

    # Get all deals
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_DEALS}/records?page_size=500"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read())

    items = result.get("data", {}).get("items", [])
    print(f"Total deals (page 1): {len(items)}")

    # Find deals with recent dates (check all date-like fields)
    now = datetime.now()
    recent = []
    no_date = []

    for item in items:
        fields = item.get("fields", {})
        rid = item.get("record_id", "")

        deal_date = fields.get("商談日", None)
        created_time = item.get("created_time", 0)

        # Check if created in last 14 days
        if isinstance(created_time, (int, float)) and created_time > 0:
            ct = datetime.fromtimestamp(created_time / 1000)
            if (now - ct).days <= 14:
                recent.append(item)
                continue

        if deal_date is None or deal_date == "" or deal_date == 0:
            no_date.append(item)

    print(f"\nDeals created in last 14 days: {len(recent)}")
    print(f"Deals with no 商談日: {len(no_date)}")

    print("\n=== RECENT DEALS (last 14 days by created_time) ===")
    for item in recent[:20]:
        fields = item.get("fields", {})
        rid = item.get("record_id", "")
        ct = datetime.fromtimestamp(item.get("created_time", 0) / 1000)

        print(f"\n--- record_id: {rid} ---")
        print(f"  created_time: {ct.strftime('%Y-%m-%d %H:%M')}")

        # Show all field names and types
        for key, val in sorted(fields.items()):
            val_type = type(val).__name__
            if isinstance(val, (list, dict)):
                val_str = json.dumps(val, ensure_ascii=False)[:200]
            elif isinstance(val, (int, float)):
                # Try to interpret as timestamp
                if val > 1e12:
                    try:
                        dt = datetime.fromtimestamp(val / 1000)
                        val_str = f"{val} -> {dt.strftime('%Y-%m-%d %H:%M')}"
                    except:
                        val_str = str(val)
                else:
                    val_str = str(val)
            else:
                val_str = str(val)[:200]
            print(f"  {key} ({val_type}): {val_str}")

    # Also check state file
    state_file = SCRIPT_DIR / "thankyou_state.json"
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        pids = state.get("processed_ids", [])
        print(f"\n=== STATE ===")
        print(f"processed_ids count: {len(pids)}")
        print(f"last_check: {state.get('last_check')}")

        # Check how many recent deals are in processed_ids
        recent_in_state = sum(1 for item in recent if item.get("record_id") in set(pids))
        print(f"Recent deals already in processed_ids: {recent_in_state}/{len(recent)}")
    else:
        print("\n=== STATE: thankyou_state.json not found ===")

if __name__ == "__main__":
    main()
