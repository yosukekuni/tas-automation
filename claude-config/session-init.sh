#!/bin/bash
# Claude Code Session Start Hook
# Fetches pending tasks from Lark Base and injects into context

CONFIG="/mnt/c/Users/USER/Documents/_data/automation_config.json"
BASE="HSSMb3T2jalcuysFCjGjJ76wpKe"
TABLE="tblGrFhJrAyYYWbV"

python3 - "$CONFIG" "$BASE" "$TABLE" << 'PYEOF'
import json, sys, requests

config_path, base_token, table_id = sys.argv[1], sys.argv[2], sys.argv[3]

try:
    config = json.load(open(config_path))
    app_id = config["lark"]["app_id"]
    app_secret = config["lark"]["app_secret"]

    # Get token
    resp = requests.post("https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
    token = resp.json()["tenant_access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch incomplete tasks (filter: ステータス != 完了)
    resp2 = requests.get(
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{base_token}/tables/{table_id}/records",
        headers=headers,
        params={"page_size": 100, "filter": 'NOT(CurrentValue.[ステータス]="完了")'},
        timeout=15)

    data = resp2.json().get("data", {})
    records = data.get("items", [])
    total = data.get("total", 0)

    if not records:
        print(f"[TaskSync] 未完了タスク: 0件")
        sys.exit(0)

    print(f"[TaskSync] 未完了タスク: {total}件")
    print("=" * 60)

    for r in records:
        f = r.get("fields", {})
        name = f.get("タスク名", "?")
        project = f.get("プロジェクト", "?")
        priority = f.get("優先度", "?")
        status = f.get("ステータス", "?")
        note = f.get("備考", "")
        print(f"- [{priority}][{project}] {name} ({status})")
        if note:
            print(f"  備考: {note[:80]}")

    print("=" * 60)

except Exception as e:
    print(f"[TaskSync] Error: {e}", file=sys.stderr)
    sys.exit(0)  # Don't block session on error
PYEOF
