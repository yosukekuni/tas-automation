#!/usr/bin/env python3
"""3月分経費精算5件を経費精算ログテーブルに追加"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

LARK_API_BASE = "https://open.larksuite.com/open-apis"
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
TABLE_EXPENSE_LOG = "tbliYwPFbxxINAfk"


def load_config():
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        Path("/mnt/c/Users/USER/Documents/_data/tas-automation/scripts/automation_config.json"),
    ]:
        if p.exists():
            with open(p) as f:
                cfg = json.load(f)
            if not str(cfg.get("lark", {}).get("app_id", "")).startswith("${"):
                return cfg
    return {"lark": {"app_id": os.environ.get("LARK_APP_ID", ""), "app_secret": os.environ.get("LARK_APP_SECRET", "")}}


def lark_api(url, method="GET", data=None, token=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    encoded = json.dumps(data).encode() if data else None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=encoded, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                raise


def get_token(config):
    result = lark_api(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": config["lark"]["app_id"], "app_secret": config["lark"]["app_secret"]},
    )
    return result["tenant_access_token"]


def main():
    # タスク指示に「3月分5件も追加（202603030001〜202603120001）」とあるが
    # 具体的なデータが提供されていないため、ここではスキップしてメッセージを出す
    print("3月分経費精算データの具体的な内容（日付・金額・距離等）が")
    print("指示に含まれていないため、データ判明後に追加してください。")
    print()
    print("追加予定の申請ID:")
    print("  202603030001")
    print("  202603050001 (仮)")
    print("  202603050002 (仮)")
    print("  202603100001 (仮)")
    print("  202603120001")
    print()
    print("このスクリプトにデータを追記して実行するか、")
    print("Lark承認管理エクスポートから取得後に追加してください。")


if __name__ == "__main__":
    main()
