#!/usr/bin/env python3
"""
全タスクレコードをJSON出力する（監査用ワンショット）
"""
import os
import json
import requests

LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
TASK_BASE = "HSSMb3T2jalcuysFCjGjJ76wpKe"
TASK_TABLE = "tblGrFhJrAyYYWbV"


def get_token():
    r = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
        timeout=10,
    )
    return r.json()["tenant_access_token"]


def fetch_all_tasks(token):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE}/tables/{TASK_TABLE}/records/search"
    all_items = []
    page_token = None

    while True:
        payload = {"page_size": 200}
        if page_token:
            payload["page_token"] = page_token
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        data = r.json()
        if data.get("code") != 0:
            print(f"ERROR: {data}")
            break
        items = data.get("data", {}).get("items", [])
        all_items.extend(items)
        if not data["data"].get("has_more"):
            break
        page_token = data["data"].get("page_token")

    return all_items


def main():
    token = get_token()
    tasks = fetch_all_tasks(token)
    print(json.dumps(tasks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
