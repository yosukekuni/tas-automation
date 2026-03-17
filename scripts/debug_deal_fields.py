#!/usr/bin/env python3
"""
Diagnostic: Dump field structure of recent deals to understand data format.
"""
import json
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

def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
    return records

def main():
    token = lark_get_token()
    deals = get_all_records(token, TABLE_DEALS)
    print(f"Total deals: {len(deals)}")

    # Show top-level keys of first record
    if deals:
        print(f"\nRecord top-level keys: {list(deals[0].keys())}")

    # Analyze all deal dates
    date_types = {}
    no_date_count = 0
    has_date_count = 0

    for item in deals:
        fields = item.get("fields", {})
        deal_date = fields.get("商談日", None)
        dt = type(deal_date).__name__
        if dt not in date_types:
            date_types[dt] = {"count": 0, "example": deal_date, "record_id": item.get("record_id")}
        date_types[dt]["count"] += 1

        if deal_date is None or deal_date == "" or deal_date == 0:
            no_date_count += 1
        else:
            has_date_count += 1

    print(f"\n=== 商談日 field type distribution ===")
    for dt, info in date_types.items():
        ex = info["example"]
        if isinstance(ex, (int, float)) and ex > 1e9:
            try:
                ts = datetime.fromtimestamp(ex / 1000)
                ex_str = f"{ex} -> {ts.strftime('%Y-%m-%d %H:%M')}"
            except:
                ex_str = str(ex)
        else:
            ex_str = str(ex)[:100]
        print(f"  {dt}: {info['count']} records (example: {ex_str}, rid: {info['record_id']})")

    print(f"\nHas 商談日: {has_date_count} / No 商談日: {no_date_count}")

    # Show the LAST 20 records (most recently added)
    print("\n=== LAST 20 RECORDS (by position in API response - likely newest) ===")
    for item in deals[-20:]:
        fields = item.get("fields", {})
        rid = item.get("record_id", "")

        deal_name_raw = fields.get("商談名", "")
        if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
            deal_name = deal_name_raw[0].get("text", "")
        else:
            deal_name = str(deal_name_raw or "(empty)")

        deal_date = fields.get("商談日", None)
        if isinstance(deal_date, (int, float)) and deal_date > 0:
            try:
                dt = datetime.fromtimestamp(deal_date / 1000)
                date_str = dt.strftime("%Y-%m-%d")
            except:
                date_str = f"raw={deal_date}"
        else:
            date_str = f"EMPTY (type={type(deal_date).__name__}, val={deal_date})"

        print(f"  {rid}: {deal_name[:40]} | 商談日={date_str}")

    # Show field names that contain "日" (date) for the last record
    print("\n=== ALL FIELDS of LAST RECORD ===")
    if deals:
        last = deals[-1]
        fields = last.get("fields", {})
        for key, val in sorted(fields.items()):
            vtype = type(val).__name__
            if isinstance(val, (list, dict)):
                val_str = json.dumps(val, ensure_ascii=False)[:300]
            elif isinstance(val, (int, float)):
                val_str = str(val)
                if val > 1e9:
                    try:
                        val_str += f" -> {datetime.fromtimestamp(val/1000).strftime('%Y-%m-%d %H:%M')}"
                    except:
                        pass
            else:
                val_str = str(val)[:300]
            print(f"  {key} ({vtype}): {val_str}")

    # State analysis
    state_file = SCRIPT_DIR / "thankyou_state.json"
    if state_file.exists():
        with open(state_file) as f:
            state = json.load(f)
        pids = set(state.get("processed_ids", []))
        print(f"\n=== STATE ===")
        print(f"processed_ids count: {len(pids)}")
        print(f"last_check: {state.get('last_check')}")

        all_ids = {r.get("record_id") for r in deals}
        print(f"Total deal IDs: {len(all_ids)}")
        print(f"IDs in state but NOT in deals: {len(pids - all_ids)}")
        print(f"IDs in deals but NOT in state: {len(all_ids - pids)}")

        # Show the "new" deals that would be detected
        new_ids = all_ids - pids
        print(f"\n=== 'NEW' DEALS (not in state, would be re-processed) ===")
        new_deals_info = []
        for item in deals:
            if item.get("record_id") in new_ids:
                fields = item.get("fields", {})
                deal_name_raw = fields.get("商談名", "")
                if isinstance(deal_name_raw, list) and deal_name_raw and isinstance(deal_name_raw[0], dict):
                    deal_name = deal_name_raw[0].get("text", "")
                else:
                    deal_name = str(deal_name_raw or "(empty)")
                deal_date = fields.get("商談日", None)
                if isinstance(deal_date, (int, float)) and deal_date > 0:
                    try:
                        dt = datetime.fromtimestamp(deal_date / 1000)
                        days = (datetime.now() - dt).days
                        date_str = f"{dt.strftime('%Y-%m-%d')} ({days}d ago)"
                    except:
                        date_str = f"raw={deal_date}"
                else:
                    date_str = f"EMPTY"
                new_deals_info.append((rid, deal_name, date_str))

        # Show first 10 and last 10
        print(f"  Total 'new' deals: {len(new_deals_info)}")
        for rid, name, date in new_deals_info[:5]:
            print(f"  FIRST: {name[:40]} | {date}")
        print("  ...")
        for rid, name, date in new_deals_info[-5:]:
            print(f"  LAST: {name[:40]} | {date}")

if __name__ == "__main__":
    main()
