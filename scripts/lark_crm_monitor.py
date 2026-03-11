#!/usr/bin/env python3
"""
Lark CRM Form Submission Monitor
新規問い合わせ・商談報告のリアルタイム監視 & 携帯プッシュ通知

Usage:
  python3 lark_crm_monitor.py          # 1回実行（新着チェック + 期限超過チェック）
  python3 lark_crm_monitor.py --loop   # 常駐モード（5分間隔で監視）
  python3 lark_crm_monitor.py --init   # 初期化（現在のレコード数を記録）
  python3 lark_crm_monitor.py --quality # データ品質チェック
  python3 lark_crm_monitor.py --overdue # 期限超過アクションチェック

通知先:
  1. Lark Webhook（グループチャット → 携帯プッシュ通知）
  2. Lark Bot（個人メッセージ → CEO・担当営業に直接通知）
  3. ログファイル（crm_notifications.log）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config ──
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "crm_monitor_state.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

# Tables to monitor
MONITORED_TABLES = {
    "連絡先": {
        "table_id": "tblN53hFIQoo4W8j",
        "key_fields": ["会社名", "氏名", "メールアドレス", "電話番号", "お問い合わせ内容（自由記述）"],
        "alert_emoji": "📩",
        "alert_label": "【新規問い合わせ】",
        "priority": "high",  # Always notify CEO
    },
    "商談": {
        "table_id": "tbl1rM86nAw9l3bP",
        "key_fields": ["商談名", "担当営業", "客先カテゴリ", "温度感スコア", "ヒアリング内容（まとめ）"],
        "alert_emoji": "📋",
        "alert_label": "【商談報告】",
        "priority": "normal",
    },
}

# CEO notification target
CEO_EMAIL = "yosuke.toyoda@gmail.com"
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# Sales rep mapping (Lark display name → email for Lark Bot DM)
# Updated when we discover actual Lark user IDs
SALES_REPS = {
    "新美光": None,   # Set Lark user_id or email when available
    "政木": None,      # Set Lark user_id or email when available
}


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def lark_get_record_count(token, table_id):
    """Get total record count for a table"""
    url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=1"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
        return result.get("data", {}).get("total", 0)


def lark_get_latest_records(token, table_id, count=5):
    """Get the latest N records from a table"""
    all_records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            data = result.get("data", {})
            all_records.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            time.sleep(0.3)
    return all_records[-count:] if len(all_records) >= count else all_records


def lark_send_webhook(text):
    """Send notification via Lark webhook (group chat → mobile push)"""
    webhook = CONFIG.get("notifications", {}).get("lark_webhook_url", "")
    if not webhook:
        return False
    data = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
    req = urllib.request.Request(webhook, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
        return True
    except Exception as e:
        print(f"  Webhook error: {e}")
        return False


def lark_send_bot_message(token, user_identifier, text, id_type="email"):
    """Send personal message via Lark Bot (direct mobile push notification)

    id_type: "email", "user_id", or "open_id"
    """
    if not user_identifier:
        return False

    data = json.dumps({
        "receive_id": user_identifier,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()

    req = urllib.request.Request(
        f"https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type={id_type}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                print(f"  Bot message sent to {user_identifier}")
                return True
            else:
                print(f"  Bot message error: {result.get('msg', 'unknown')}")
                return False
    except Exception as e:
        print(f"  Bot message failed: {e}")
        return False


def lark_get_user_by_email(token, email):
    """Look up Lark user by email to get their user_id"""
    data = json.dumps({"emails": [email]}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/contact/v3/users/batch_get_id?user_id_type=user_id",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            items = result.get("data", {}).get("user_list", [])
            if items and items[0].get("user_id"):
                return items[0]["user_id"]
    except Exception:
        pass
    return None


# ── State Management ──
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── Notification ──
def send_notification(token, subject, body, priority="normal", sales_rep_name=None):
    """Send notification via all available channels"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    full_msg = f"{subject}\n{now}\n\n{body}"

    # 1. Lark Webhook (group chat → all members get mobile push)
    webhook_sent = lark_send_webhook(full_msg)

    # 2. Lark Bot → CEO (direct personal message = mobile push notification)
    if priority == "high" or not webhook_sent:
        lark_send_bot_message(token, CEO_EMAIL, full_msg, id_type="email")

    # 3. Lark Bot → Sales rep (if deal has assigned sales rep)
    if sales_rep_name:
        rep_id = SALES_REPS.get(sales_rep_name)
        if rep_id:
            lark_send_bot_message(token, rep_id, full_msg)

    # 4. Console output (for cron logs)
    print(f"\n{'='*60}")
    print(f"🔔 {subject} ({now})")
    print(f"{'='*60}")
    print(body)
    if webhook_sent:
        print("[通知: Webhook ✅]")
    else:
        print("[通知: Webhook未設定 — Lark Bot DMで代替]")
    print(f"{'='*60}\n")

    # 5. Write to notification log file
    log_file = SCRIPT_DIR / "crm_notifications.log"
    with open(log_file, "a") as f:
        f.write(f"\n[{now}] {subject}\n{body}\n{'─'*40}\n")

    return webhook_sent


# ── Main Logic ──
def check_for_new_records():
    """Check all monitored tables for new records"""
    state = load_state()
    token = lark_get_token()
    new_records_found = False

    for table_name, table_config in MONITORED_TABLES.items():
        table_id = table_config["table_id"]
        current_count = lark_get_record_count(token, table_id)
        prev_count = state.get(table_id, {}).get("count", 0)

        if prev_count == 0:
            state[table_id] = {"count": current_count, "last_check": datetime.now().isoformat()}
            print(f"[INIT] {table_name}: {current_count} records (baseline set)")
            continue

        new_count = current_count - prev_count
        if new_count > 0:
            new_records_found = True
            print(f"[NEW] {table_name}: {new_count} new records detected ({prev_count} → {current_count})")

            # Get the new records
            latest = lark_get_latest_records(token, table_id, count=new_count)

            for rec in latest:
                fields = rec.get("fields", {})

                # Extract sales rep name for targeted notification
                sales_rep = None
                担当 = fields.get("担当営業")
                if isinstance(担当, list) and 担当:
                    # Lark Person field returns list of user objects
                    for person in 担当:
                        if isinstance(person, dict):
                            sales_rep = person.get("name", "")
                        elif isinstance(person, str):
                            sales_rep = person

                # Build notification message
                details = []
                for field_name in table_config["key_fields"]:
                    value = fields.get(field_name, "")
                    if value and value != "N/A":
                        if isinstance(value, list):
                            if field_name == "担当営業":
                                # Person field
                                names = []
                                for v in value:
                                    if isinstance(v, dict):
                                        names.append(v.get("name", str(v)))
                                    else:
                                        names.append(str(v))
                                value = ", ".join(names)
                            else:
                                value = ", ".join(str(v) for v in value)
                        elif isinstance(value, dict):
                            value = str(value)
                        if len(str(value)) > 200:
                            value = str(value)[:200] + "..."
                        details.append(f"  {field_name}: {value}")

                if details:
                    subject = f"{table_config['alert_emoji']} {table_config['alert_label']}"
                    body = "\n".join(details)
                    send_notification(
                        token, subject, body,
                        priority=table_config.get("priority", "normal"),
                        sales_rep_name=sales_rep
                    )

            time.sleep(0.5)
        else:
            print(f"[OK] {table_name}: no new records ({current_count})")

        state[table_id] = {"count": current_count, "last_check": datetime.now().isoformat()}
        time.sleep(0.3)

    save_state(state)
    return new_records_found


def check_data_quality():
    """Check CRM data quality and flag issues"""
    token = lark_get_token()

    all_deals = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/tbl1rM86nAw9l3bP/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            data = result.get("data", {})
            all_deals.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            time.sleep(0.3)

    no_stage = 0
    no_next_action = 0
    warm_or_hot_no_action = []
    no_deal_name = 0

    for rec in all_deals:
        fields = rec.get("fields", {})
        deal_name = fields.get("商談名", "") or ""
        stage = fields.get("商談ステージ", "")
        next_action = fields.get("次アクション", "")
        temp = fields.get("温度感スコア", "")

        if not deal_name:
            no_deal_name += 1
        if not stage:
            no_stage += 1
        if not next_action:
            no_next_action += 1
        if temp in ("Hot", "Warm") and not next_action:
            warm_or_hot_no_action.append(deal_name or "(名前なし)")

    report_lines = [
        f"📊 CRMデータ品質レポート",
        f"",
        f"商談総数: {len(all_deals)}",
        f"商談名なし: {no_deal_name}",
        f"ステージ未設定: {no_stage}",
        f"次アクション未設定: {no_next_action}",
    ]

    if warm_or_hot_no_action:
        report_lines.append(f"")
        report_lines.append(f"⚠️ Warm/Hot案件で次アクション未設定: {len(warm_or_hot_no_action)}件")
        for name in warm_or_hot_no_action[:10]:
            report_lines.append(f"  - {name}")
        if len(warm_or_hot_no_action) > 10:
            report_lines.append(f"  ... 他{len(warm_or_hot_no_action)-10}件")

    send_notification(lark_get_token(), "CRMデータ品質アラート", "\n".join(report_lines), priority="normal")
    return len(warm_or_hot_no_action)


def check_overdue_actions():
    """Check for Hot/Warm deals with overdue next action dates.

    Improved v2: Smart filtering to reduce noise.
    - 30日超過 → 自動で「要クローズ判断」に分類（毎回通知しない）
    - 次アクション未設定 → 除外（アクションなしを通知しても無意味）
    - Hot案件のみ即時通知（Top5）、Warmは週次サマリーのみ
    - テスト商談・空名は除外
    """
    token = lark_get_token()

    # Fetch all deals
    all_deals = []
    page_token = None
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/tbl1rM86nAw9l3bP/records?page_size=500"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            data = result.get("data", {})
            all_deals.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            time.sleep(0.3)

    now = datetime.now()
    urgent_deals = []    # Hot + 1-30日超過 → 即時通知
    stale_deals = []     # 30日超過 → 週次サマリーのみ
    warm_deals = []      # Warm + 1-30日超過 → 週次サマリーのみ

    # Test/junk name patterns to skip
    junk_patterns = ["テスト", "test", "サンプル", "sample", "ダミー"]

    for rec in all_deals:
        fields = rec.get("fields", {})
        temp = fields.get("温度感スコア", "")
        stage = fields.get("商談ステージ", "")
        next_action_date = fields.get("次アクション日", "")

        # Only Hot/Warm, skip 不在/失注/受注, must have a date
        if temp not in ("Hot", "Warm"):
            continue
        if stage in ("不在", "失注", "受注"):
            continue
        if not next_action_date:
            continue

        # Next action text — skip if no action is set
        next_action = fields.get("次アクション", "")
        if isinstance(next_action, list):
            next_action = ", ".join(str(a) for a in next_action)
        next_action_other = fields.get("次アクション：その他", "") or ""
        action_text = next_action
        if next_action_other:
            action_text = f"{next_action} {next_action_other}"
        if not action_text or action_text.strip() in ("", "None", "なし"):
            continue

        # Parse date (Lark stores as Unix timestamp in milliseconds)
        try:
            if isinstance(next_action_date, (int, float)):
                action_dt = datetime.fromtimestamp(next_action_date / 1000)
            else:
                continue
        except (ValueError, OSError):
            continue

        overdue_days = (now - action_dt).days
        if overdue_days <= 0:
            continue

        # Resolve deal name: prefer 商談名, fallback to 新規取引先名
        deal_name = fields.get("商談名", "") or fields.get("新規取引先名", "") or ""
        if not deal_name or any(p in deal_name.lower() for p in junk_patterns):
            continue

        # Extract sales rep name
        sales_rep = ""
        tantou = fields.get("担当営業", "")
        if isinstance(tantou, list) and tantou:
            for person in tantou:
                if isinstance(person, dict):
                    sales_rep = person.get("name", "")
                elif isinstance(person, str):
                    sales_rep = person

        deal_info = {
            "deal_name": deal_name,
            "sales_rep": sales_rep,
            "action_date": action_dt.strftime("%Y-%m-%d"),
            "overdue_days": overdue_days,
            "next_action": action_text,
            "temp": temp,
        }

        if overdue_days > 30:
            stale_deals.append(deal_info)
        elif temp == "Hot":
            urgent_deals.append(deal_info)
        else:
            warm_deals.append(deal_info)

    # Sort urgent by overdue days
    urgent_deals.sort(key=lambda x: x["overdue_days"], reverse=True)

    total = len(urgent_deals) + len(warm_deals) + len(stale_deals)
    print(f"[OVERDUE] 検出: urgent(Hot)={len(urgent_deals)}, warm={len(warm_deals)}, stale(30日超)={len(stale_deals)}")

    if not urgent_deals and not warm_deals and not stale_deals:
        print("[OK] 期限超過のHot/Warm案件なし")
        return 0

    # === Immediate notification: Hot deals only, Top 5 ===
    if urgent_deals:
        top = urgent_deals[:5]
        lines = [f"[要対応] Hot案件 期限超過（{len(urgent_deals)}件中Top{len(top)}）\n"]
        for d in top:
            lines.append(
                f"{d['deal_name']}（{d['sales_rep']}）\n"
                f"  {d['overdue_days']}日超過 | {d['next_action']}\n"
            )
        if len(urgent_deals) > 5:
            lines.append(f"... 他{len(urgent_deals)-5}件")

        full_msg = "\n".join(lines)
        sent = lark_send_bot_message(token, CEO_OPEN_ID, full_msg, id_type="open_id")
        if sent:
            print(f"  CEO DM: Hot案件{len(top)}件送信")
        else:
            lark_send_bot_message(token, CEO_EMAIL, full_msg, id_type="email")
    else:
        print("  Hot案件の期限超過なし — 即時通知スキップ")

    # === Stale deals: log only (30日超過は週次サマリーで別途対応) ===
    if stale_deals:
        print(f"  [INFO] 30日超過（要クローズ判断）: {len(stale_deals)}件")
        for d in stale_deals[:5]:
            print(f"    - {d['deal_name']}（{d['overdue_days']}日超過, {d['sales_rep']}）")

    # === Warm deals: log only (週次サマリーで対応) ===
    if warm_deals:
        print(f"  [INFO] Warm期限超過（週次サマリー対象）: {len(warm_deals)}件")

    # Console summary
    print(f"\n{'='*60}")
    print(f"期限超過サマリー ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"  Hot即時通知: {len(urgent_deals)}件")
    print(f"  Warm(週次): {len(warm_deals)}件")
    print(f"  30日超過(要判断): {len(stale_deals)}件")
    print(f"{'='*60}\n")

    # Write to log
    log_file = SCRIPT_DIR / "crm_notifications.log"
    with open(log_file, "a") as f:
        f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 期限超過サマリー: "
                f"urgent={len(urgent_deals)}, warm={len(warm_deals)}, stale={len(stale_deals)}\n{'─'*40}\n")

    return total


def main():
    args = sys.argv[1:]

    if "--init" in args:
        print("Initializing monitor state...")
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        check_for_new_records()
        print("State initialized. Future runs will detect new records.")
        return

    if "--loop" in args:
        interval = 300  # 5 minutes
        print(f"Starting CRM monitor (checking every {interval}s)...")
        while True:
            try:
                check_for_new_records()
            except Exception as e:
                print(f"[ERROR] {datetime.now()}: {e}")
            time.sleep(interval)

    if "--quality" in args:
        print("Running data quality check...")
        issues = check_data_quality()
        print(f"Found {issues} Warm/Hot deals without next action")
        return

    if "--overdue" in args:
        print("Running overdue action check...")
        overdue = check_overdue_actions()
        print(f"Found {overdue} overdue Hot/Warm deals")
        return

    # Default: single check (new records + overdue actions)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for new CRM records...")
    found = check_for_new_records()
    if not found:
        print("No new records.")

    # Also check for overdue actions on every run
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for overdue actions...")
    try:
        check_overdue_actions()
    except Exception as e:
        print(f"[ERROR] Overdue check failed: {e}")


if __name__ == "__main__":
    main()
