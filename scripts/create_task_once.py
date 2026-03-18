#!/usr/bin/env python3
"""
One-shot: 紹介パートナー制度設計タスクをLark Baseに登録して完了記録する
"""
import os
import json
import requests
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))

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


def create_task(token, name, status, project, notes):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "fields": {
            "Text": name,
            "ステータス": status,
            "プロジェクト": project,
            "備考": notes,
        }
    }
    r = requests.post(
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{TASK_BASE}/tables/{TASK_TABLE}/records",
        headers=headers,
        json=payload,
        timeout=15,
    )
    return r.json()


if __name__ == "__main__":
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    token = get_token()
    result = create_task(
        token,
        name="紹介パートナー制度設計",
        status="完了",
        project="新規チャネル開発",
        notes=(
            f"完了日時: {now}\n"
            "成果物: /mnt/c/Users/USER/tas-automation/docs/referral_partner_program.md\n"
            "内容: 測量・土木・不動産・建設系パートナー向け紹介手数料制度（成約額5〜10%）の設計書。"
            "パートナー対象・インセンティブ設計・紹介フロー・LP設計・リスク管理・CRM管理・実装ステップを含む。"
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("code") == 0:
        print("✅ タスク登録完了")
    else:
        print(f"❌ エラー: {result}")
