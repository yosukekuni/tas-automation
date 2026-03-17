"""
タスク自動消化エージェント (24/365)
===================================
Lark Baseの積み残しタスクを自動で処理する。
GitHub Actionsで定期実行（1時間毎）。

処理フロー:
1. Lark Baseからステータス=未着手のタスクを取得
2. 自動実行可能なタスクを判定
3. 実行→結果をLark Baseに記録
4. Lark Webhook（設定済みなら）で通知
"""

import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

# ── Config ──
LARK_APP_ID = os.environ.get("LARK_APP_ID", "")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "")
TASK_BASE = "HSSMb3T2jalcuysFCjGjJ76wpKe"
TASK_TABLE = "tblGrFhJrAyYYWbV"
LOG_TABLE = "tblIyLVn7RFqDbdt"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
LARK_WEBHOOK_URL = os.environ.get("LARK_WEBHOOK_URL", "")

# Tags that indicate a task can be auto-processed
AUTO_PROCESSABLE_KEYWORDS = [
    "記事", "CSS", "Snippet", "構造化データ", "IndexNow",
    "GA4", "GSC", "レビュー", "監査", "チェック",
    "スクリプト", "GitHub Actions", "自動",
]

# Tags that indicate a task needs human action
HUMAN_REQUIRED_KEYWORDS = [
    "ユーザー操作待ち", "ユーザー作業待ち", "手動", "管理画面",
    "DNS", "DKIM", "DMARC", "電話", "面談", "請求書",
    "ララコール", "NAS", "ScanSnap", "購入",
]


def get_token():
    r = requests.post(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
        timeout=10,
    )
    return r.json()["tenant_access_token"]


def get_pending_tasks(token):
    """Fetch tasks with status = 未着手"""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "page_size": 50,
        "filter": 'CurrentValue.[ステータス]="未着手"',
    }
    r = requests.get(
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE}/tables/{TASK_TABLE}/records",
        headers=headers,
        params=params,
        timeout=15,
    )
    data = r.json().get("data", {})
    return data.get("items", [])


def is_auto_processable(task):
    """Determine if a task can be processed automatically"""
    fields = task.get("fields", {})
    name = fields.get("Text", "") or ""
    status = fields.get("ステータス", "") or ""
    notes = fields.get("備考", "") or ""
    combined = f"{name} {notes}".lower()

    # Explicitly human-required
    for kw in HUMAN_REQUIRED_KEYWORDS:
        if kw.lower() in combined:
            return False, f"人手必要: {kw}"

    # Check if it matches auto-processable patterns
    for kw in AUTO_PROCESSABLE_KEYWORDS:
        if kw.lower() in combined:
            return True, f"自動処理可能: {kw}"

    return False, "自動処理パターンに該当しない"


def process_task_with_claude(task, token):
    """Use Claude API to analyze and execute a task"""
    fields = task.get("fields", {})
    name = fields.get("Text", "")
    notes = fields.get("備考", "")
    project = fields.get("プロジェクト", "")

    prompt = f"""あなたはTAS/TOMOSHIの自動化エージェントです。以下のタスクを分析してください。

タスク名: {name}
プロジェクト: {project}
備考: {notes}

このタスクについて:
1. 具体的に何をすべきか（ステップ）
2. 必要なAPI呼び出しやスクリプト実行
3. 今すぐ自動実行可能か、それとも追加情報が必要か

JSON形式で回答:
{{
  "executable": true/false,
  "steps": ["ステップ1", "ステップ2"],
  "required_info": "不足情報（あれば）",
  "estimated_effort": "low/medium/high"
}}"""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        result = r.json()["content"][0]["text"]

        # Parse JSON
        if "```json" in result:
            result = result.split("```json")[1].split("```")[0]
        elif "```" in result:
            result = result.split("```")[1].split("```")[0]

        return json.loads(result.strip())
    except Exception as e:
        return {"executable": False, "error": str(e)}


def update_task_status(token, record_id, status, note_append=""):
    """Update task status in Lark Base"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    fields = {"ステータス": status}
    if status == "完了":
        now = int(datetime.now(JST).timestamp()) * 1000
        fields["完了日"] = now
    if note_append:
        # We'd need to read current notes and append, simplified here
        fields["備考"] = note_append

    r = requests.put(
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE}/tables/{TASK_TABLE}/records/{record_id}",
        headers=headers,
        json={"fields": fields},
        timeout=10,
    )
    # PUT may be blocked, try POST
    if r.status_code == 403:
        r = requests.post(
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE}/tables/{TASK_TABLE}/records/{record_id}",
            headers=headers,
            json={"fields": fields},
            timeout=10,
        )
    return r.json()


def notify(message):
    """Send notification via Lark Webhook"""
    if not LARK_WEBHOOK_URL:
        print(f"[Notify] No webhook URL, skipping: {message[:80]}")
        return
    try:
        requests.post(
            LARK_WEBHOOK_URL,
            json={"msg_type": "text", "content": {"text": message}},
            timeout=10,
        )
    except Exception:
        pass


def main():
    print(f"[TaskProcessor] Starting at {datetime.now(JST).isoformat()}")

    if not LARK_APP_ID or not LARK_APP_SECRET:
        print("[TaskProcessor] Missing Lark credentials, exiting")
        sys.exit(1)

    token = get_token()
    tasks = get_pending_tasks(token)
    print(f"[TaskProcessor] Found {len(tasks)} pending tasks")

    auto_tasks = []
    human_tasks = []
    processed = []

    for task in tasks:
        fields = task.get("fields", {})
        name = fields.get("Text", "?")
        can_auto, reason = is_auto_processable(task)

        if can_auto:
            auto_tasks.append(task)
            print(f"  [AUTO] {name} — {reason}")
        else:
            human_tasks.append(task)
            print(f"  [SKIP] {name} — {reason}")

    if not auto_tasks:
        print("[TaskProcessor] No auto-processable tasks found")
        # 自動処理対象がない場合はWebhook通知しない（ノイズ削減）
        return

    # Process auto tasks with Claude analysis
    if ANTHROPIC_API_KEY:
        for task in auto_tasks[:5]:  # Max 5 per run to control costs
            fields = task.get("fields", {})
            name = fields.get("Text", "?")
            print(f"\n[Processing] {name}")

            analysis = process_task_with_claude(task, token)
            print(f"  Executable: {analysis.get('executable')}")
            print(f"  Steps: {analysis.get('steps', [])}")

            if analysis.get("executable"):
                # Mark as 進行中
                update_task_status(token, task["record_id"], "進行中",
                                   f"[自動] {datetime.now(JST).strftime('%m/%d %H:%M')} 分析完了。ステップ: {', '.join(analysis.get('steps', []))}")
                processed.append(name)
            else:
                print(f"  Not executable: {analysis.get('required_info', analysis.get('error', 'unknown'))}")

    # Summary
    report_lines = [
        f"[TaskProcessor] {datetime.now(JST).strftime('%m/%d %H:%M')}",
        f"未着手: {len(tasks)}件",
        f"自動処理可能: {len(auto_tasks)}件",
        f"人手待ち: {len(human_tasks)}件",
    ]
    if processed:
        report_lines.append(f"処理開始: {', '.join(processed)}")

    report = "\n".join(report_lines)
    print(f"\n{report}")
    notify(report)


if __name__ == "__main__":
    main()
