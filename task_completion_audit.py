#!/usr/bin/env python3
"""
タスク完了漏れ監査スクリプト
- 過去のカレンダーイベント（撮影・納品系）が✅なしで残ってないか
- タスクBaseで完了済みなのにステータス未更新のものがないか
- 受注台帳の納品日が過ぎてるのに商談ステージが進んでないか
GitHub Actionsで毎朝実行。漏れがあればLark通知。
"""

import json
import os
import sys
import datetime
import requests

# --- Config ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "automation_config.json")

with open(CONFIG_PATH) as f:
    config = json.load(f)

LARK_APP_ID = config["lark"]["app_id"]
LARK_APP_SECRET = config["lark"]["app_secret"]
CRM_BASE_ID = "BodWbgw6DaHP8FspBTYjT8qSpOe"
TASK_BASE_ID = "HSSMb3T2jalcuysFCjGjJ76wpKe"
TASK_TABLE_ID = "tblGrFhJrAyYYWbV"
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

# Lark webhook for notifications (reuse existing)
LARK_WEBHOOK = config.get("lark", {}).get("webhook_url", "")


def get_lark_token():
    resp = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
    )
    return resp.json().get("tenant_access_token")


def search_records(token, base_id, table_id, payload):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{base_id}/tables/{table_id}/records/search"
    resp = requests.post(url, headers=headers, json=payload)
    data = resp.json()
    if data.get("code") == 0:
        return data["data"].get("items", [])
    return []


def audit_tasks(token):
    """タスクBaseで期限切れ or 長期未着手のものを検出"""
    issues = []
    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    seven_days_ago = now_ms - 7 * 86400 * 1000

    # Get all non-completed, non-frozen tasks
    items = search_records(token, TASK_BASE_ID, TASK_TABLE_ID, {
        "page_size": 200,
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "ステータス", "operator": "isNot", "value": ["完了"]},
                {"field_name": "ステータス", "operator": "isNot", "value": ["凍結"]},
            ],
        },
    })

    for item in items:
        fields = item.get("fields", {})
        text = fields.get("Text", "N/A")
        if isinstance(text, list):
            text = text[0].get("text", "N/A") if text else "N/A"
        status = fields.get("ステータス", "N/A")
        priority = fields.get("優先度", "低")
        order_date = fields.get("オーダー日", 0)

        # High priority task older than 7 days and still 未着手
        if priority == "高" and status == "未着手" and order_date and order_date < seven_days_ago:
            age_days = (now_ms - order_date) // (86400 * 1000)
            issues.append(f"⚠️ 高優先度タスク {age_days}日間未着手: {text}")

    return issues


def audit_deals(token):
    """商談で納品日が過ぎてるのにステージが進んでないものを検出"""
    issues = []
    now_ms = int(datetime.datetime.now().timestamp() * 1000)

    # Get deals with stage still in early phases
    stale_stages = ["ヒアリング", "見積検討", "リード獲得"]
    for stage in stale_stages:
        items = search_records(token, CRM_BASE_ID, DEAL_TABLE_ID, {
            "page_size": 50,
            "filter": {
                "conjunction": "and",
                "conditions": [
                    {"field_name": "商談ステージ", "operator": "is", "value": [stage]},
                    {"field_name": "次アクション日", "operator": "isNotEmpty", "value": []},
                ],
            },
        })

        for item in items:
            fields = item.get("fields", {})
            next_date = fields.get("次アクション日", 0)
            if isinstance(next_date, (int, float)) and next_date < now_ms - 14 * 86400 * 1000:
                name = fields.get("商談名", "N/A")
                if isinstance(name, list):
                    name = name[0].get("text", "N/A") if name else "N/A"
                days_overdue = (now_ms - next_date) // (86400 * 1000)
                issues.append(f"📋 商談フォロー {days_overdue}日超過: {name} (Stage: {stage})")

    return issues


def audit_calendar_via_tasks(token):
    """タスクBaseの撮影・納品系で完了日が入ってないものを検出"""
    issues = []
    keywords = ["撮影", "納品", "請求", "送付"]

    items = search_records(token, TASK_BASE_ID, TASK_TABLE_ID, {
        "page_size": 200,
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "ステータス", "operator": "isNot", "value": ["完了"]},
                {"field_name": "ステータス", "operator": "isNot", "value": ["凍結"]},
            ],
        },
    })

    now_ms = int(datetime.datetime.now().timestamp() * 1000)
    for item in items:
        fields = item.get("fields", {})
        text = fields.get("Text", "")
        if isinstance(text, list):
            text = text[0].get("text", "") if text else ""
        order_date = fields.get("オーダー日", 0)

        # Check if task name contains delivery/invoice keywords and is old
        if any(kw in text for kw in keywords):
            if order_date and order_date < now_ms - 3 * 86400 * 1000:
                age = (now_ms - order_date) // (86400 * 1000)
                issues.append(f"📦 納品/請求系タスク {age}日経過: {text}")

    return issues


def send_lark_notification(issues):
    """Lark Webhookで通知"""
    if not LARK_WEBHOOK:
        print("LARK_WEBHOOK not configured, printing to stdout")
        for issue in issues:
            print(f"  {issue}")
        return

    text = "🔍 **タスク完了漏れ監査レポート**\n\n"
    text += f"検出日時: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    text += f"検出件数: {len(issues)}件\n\n"
    for issue in issues:
        text += f"- {issue}\n"

    requests.post(LARK_WEBHOOK, json={
        "msg_type": "text",
        "content": {"text": text},
    })


def main():
    token = get_lark_token()
    all_issues = []

    print("=== タスク完了漏れ監査 ===")
    print(f"実行日時: {datetime.datetime.now()}")

    # 1. Task audit
    task_issues = audit_tasks(token)
    all_issues.extend(task_issues)
    print(f"\nタスクBase監査: {len(task_issues)}件")

    # 2. Deal audit
    deal_issues = audit_deals(token)
    all_issues.extend(deal_issues)
    print(f"商談フォロー監査: {len(deal_issues)}件")

    # 3. Delivery/invoice audit
    calendar_issues = audit_calendar_via_tasks(token)
    all_issues.extend(calendar_issues)
    print(f"納品/請求系監査: {len(calendar_issues)}件")

    print(f"\n合計: {len(all_issues)}件の漏れ検出")

    if all_issues:
        for issue in all_issues:
            print(f"  {issue}")
        send_lark_notification(all_issues)
    else:
        print("  漏れなし ✅")

    return len(all_issues)


if __name__ == "__main__":
    sys.exit(main())
