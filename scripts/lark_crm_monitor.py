#!/usr/bin/env python3
"""
Lark CRM Form Submission Monitor
新規問い合わせ・商談報告のリアルタイム監視 & 携帯プッシュ通知

Usage:
  python3 lark_crm_monitor.py              # 1回実行（新着チェック + 期限超過 + Hot/Warm未設定 + 停滞チェック）
  python3 lark_crm_monitor.py --loop       # 常駐モード（5分間隔で監視）
  python3 lark_crm_monitor.py --init       # 初期化（現在のレコード数を記録）
  python3 lark_crm_monitor.py --quality    # データ品質チェック
  python3 lark_crm_monitor.py --overdue    # 期限超過アクションチェック
  python3 lark_crm_monitor.py --stagnant   # 商談ステージ停滞チェック（14日以上変更なし）
  python3 lark_crm_monitor.py --weekly     # 週次サマリー（ステージ進捗率・アクション実行率）
  python3 lark_crm_monitor.py --dry-run    # 全チェック実行（通知送信なし、コンソール出力のみ）

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
STATE_FILE = SCRIPT_DIR / "crm_monitor_state.json"

# Config: prefer real credentials, fallback to local (GitHub Actions uses env placeholders)
for _p in [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]:
    if _p.exists():
        with open(_p) as f:
            _cfg = json.load(f)
        # Skip placeholder files (GitHub Actions template)
        if not str(_cfg.get("lark", {}).get("app_id", "")).startswith("${"):
            CONFIG = _cfg
            break
else:
    raise FileNotFoundError("automation_config.json not found")

if "CONFIG" not in dir():
    # Fallback: all files had placeholders, use the last one (GitHub Actions will substitute env vars)
    CONFIG = _cfg

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

# Sales rep mapping (Lark display name → notification config)
# open_id: Lark Bot DM用（内部ユーザー）
# email: メール送信用（外部委託はこちらを使用）
SALES_REPS = {
    "新美光": {"open_id": "ou_189dc637b61a83b886d356becb3ae18e", "email": "h.niimi@tokaiair.com"},
    "新美 光": {"open_id": "ou_189dc637b61a83b886d356becb3ae18e", "email": "h.niimi@tokaiair.com"},
    "政木": {"open_id": None, "email": "y-masaki@riseasone.jp"},
    "ユーザー550372": {"open_id": None, "email": "y-masaki@riseasone.jp"},  # 政木のLark表示名
    "政木 勇治": {"open_id": None, "email": "y-masaki@riseasone.jp"},
}

# Global dry-run flag (set via --dry-run)
DRY_RUN = False


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
    """Send notification via all available channels (skipped in DRY_RUN mode)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    full_msg = f"{subject}\n{now}\n\n{body}"

    # 4. Console output (for cron logs) — always shown
    print(f"\n{'='*60}")
    print(f"{'[DRY-RUN] ' if DRY_RUN else ''}🔔 {subject} ({now})")
    print(f"{'='*60}")
    print(body)

    if DRY_RUN:
        print("[DRY-RUN: 通知送信スキップ]")
        print(f"{'='*60}\n")
        return False

    # 1. Lark Webhook (group chat → all members get mobile push)
    webhook_sent = lark_send_webhook(full_msg)

    # 2. Lark Bot → CEO (direct personal message = mobile push notification)
    if priority == "high" or not webhook_sent:
        lark_send_bot_message(token, CEO_OPEN_ID, full_msg, id_type="open_id")

    # 3. Sales rep notification (Lark DM or email)
    if sales_rep_name:
        rep_cfg = SALES_REPS.get(sales_rep_name) or {}
        if isinstance(rep_cfg, dict) and rep_cfg.get("open_id"):
            lark_send_bot_message(token, rep_cfg["open_id"], full_msg, id_type="open_id")
        elif isinstance(rep_cfg, dict) and rep_cfg.get("email"):
            send_email_notification(rep_cfg["email"], "【CRM通知】新規レコード", full_msg)

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


def fetch_all_deals(token):
    """Fetch all records from 商談 table (shared helper to avoid duplicate API calls)"""
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
    return all_deals


def extract_sales_rep(fields):
    """Extract sales rep name from fields"""
    tantou = fields.get("担当営業", "")
    if isinstance(tantou, list) and tantou:
        for person in tantou:
            if isinstance(person, dict):
                return person.get("name", "")
            elif isinstance(person, str):
                return person
    return ""


def send_email_notification(to_email, subject, body):
    """WordPress wp_mail API経由でメール送信（政木など外部委託者向け）"""
    try:
        wp_config = CONFIG.get("wordpress", {})
        wp_base = wp_config.get("base_url", "").replace("/wp/v2", "")
        wp_user = wp_config.get("user", "")
        wp_pass = wp_config.get("app_password", "")
        if not all([wp_base, wp_user, wp_pass]):
            print(f"  WordPress config missing, email skipped: {to_email}")
            return False

        import base64
        wp_auth = base64.b64encode(f"{wp_user}:{wp_pass}".encode()).decode()
        endpoint = wp_base + "/tas/v1/send-email"
        data = json.dumps({
            "to": to_email,
            "subject": subject,
            "body": body,
            "from_name": "東海エアサービス",
            "from_email": "info@tokaiair.com",
        }).encode()
        req = urllib.request.Request(
            endpoint, data=data,
            headers={"Authorization": f"Basic {wp_auth}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("success", False)
    except Exception as e:
        print(f"  Email send error ({to_email}): {e}")
        return False


def resolve_deal_name(fields):
    """Resolve deal name: 取引先リンクフィールド → 商談名 → 新規取引先名 の優先順で取得"""
    # 1. 取引先リンクフィールド (type=21)
    company_link = fields.get("取引先", [])
    if isinstance(company_link, list) and company_link:
        for item in company_link:
            if isinstance(item, dict):
                name = item.get("text", "") or ""
                if name:
                    return name
                arr = item.get("text_arr", [])
                if arr:
                    return arr[0]
    # 2. 商談名
    deal_name = fields.get("商談名", "")
    if deal_name:
        return deal_name
    # 3. 新規取引先名
    return fields.get("新規取引先名", "") or "(名前なし)"


def check_action_reminders():
    """次アクション日の前日・当日・超過をチェックし、営業担当本人にLark DMでリマインド送信。

    - 前日: 「明日フォロー予定です」
    - 当日: 「本日フォロー予定です」
    - 1-7日超過: 「期限を過ぎています」（毎日朝1回）

    CEOにもサマリーを送信。
    """
    token = lark_get_token()
    all_deals = fetch_all_deals(token)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # State: avoid duplicate reminders within same day
    reminder_state_file = SCRIPT_DIR / "reminder_state.json"
    if reminder_state_file.exists():
        with open(reminder_state_file) as f:
            reminder_state = json.load(f)
    else:
        reminder_state = {"last_date": "", "sent_ids": []}

    # Reset sent_ids if new day
    if reminder_state.get("last_date") != today_str:
        reminder_state = {"last_date": today_str, "sent_ids": []}

    tomorrow_reminders = []  # 前日
    today_reminders = []     # 当日
    overdue_reminders = []   # 1-7日超過

    for rec in all_deals:
        record_id = rec.get("record_id", "")
        fields = rec.get("fields", {})
        temp = fields.get("温度感スコア", "")
        stage = fields.get("商談ステージ", "")
        next_action_date = fields.get("次アクション日", "")

        # Skip: no date, closed stages, cold/no-prospect
        if not next_action_date:
            continue
        if stage in ("失注", "受注"):
            continue
        if temp in ("Cold",):
            continue

        # Next action text
        next_action = fields.get("次アクション", "")
        if isinstance(next_action, list):
            next_action = ", ".join(str(a) for a in next_action)
        if not next_action or next_action.strip() in ("", "None", "営業見込みなし", "無し"):
            continue

        # Parse date
        try:
            if isinstance(next_action_date, (int, float)):
                action_dt = datetime.fromtimestamp(next_action_date / 1000)
            else:
                continue
        except (ValueError, OSError):
            continue

        diff_days = (now - action_dt).days  # positive = overdue

        if diff_days < -1 or diff_days > 7:
            continue  # Too far in future or too old

        # Already reminded today?
        if record_id in reminder_state.get("sent_ids", []):
            continue

        deal_name = resolve_deal_name(fields)
        sales_rep = extract_sales_rep(fields)
        next_action_other = fields.get("次アクション：その他", "") or ""
        action_text = next_action
        if next_action_other:
            action_text = f"{next_action} ({next_action_other})"

        info = {
            "record_id": record_id,
            "deal_name": deal_name,
            "sales_rep": sales_rep,
            "action_date": action_dt.strftime("%Y-%m-%d"),
            "diff_days": diff_days,
            "next_action": action_text,
            "temp": temp,
        }

        if diff_days == -1:
            tomorrow_reminders.append(info)
        elif diff_days == 0:
            today_reminders.append(info)
        elif 1 <= diff_days <= 7:
            overdue_reminders.append(info)

    all_reminders = tomorrow_reminders + today_reminders + overdue_reminders
    print(f"[REMIND] 前日={len(tomorrow_reminders)}, 当日={len(today_reminders)}, 超過(1-7日)={len(overdue_reminders)}")

    if not all_reminders:
        print("[OK] リマインド対象なし")
        return 0

    # Group by sales rep and send DMs
    by_rep = {}
    for r in all_reminders:
        rep = r["sales_rep"]
        if rep not in by_rep:
            by_rep[rep] = []
        by_rep[rep].append(r)

    sent_ids = []
    for rep_name, deals in by_rep.items():
        lines = [f"【フォローリマインド】{rep_name}さん\n"]
        for d in deals:
            if d["diff_days"] == -1:
                tag = "明日"
            elif d["diff_days"] == 0:
                tag = "本日"
            else:
                tag = f"{d['diff_days']}日超過"
            lines.append(
                f"・{d['deal_name']}（{d['temp']}）\n"
                f"  {tag} | {d['next_action']}\n"
            )
        msg = "\n".join(lines)

        # Send to sales rep (Lark DM or email)
        rep_config = SALES_REPS.get(rep_name) or SALES_REPS.get(rep_name.replace(" ", "")) or {}
        rep_open_id = rep_config.get("open_id") if isinstance(rep_config, dict) else None
        rep_email = rep_config.get("email") if isinstance(rep_config, dict) else None

        if DRY_RUN:
            method = "Lark DM" if rep_open_id else f"Email({rep_email})" if rep_email else "通知不可"
            print(f"  [DRY-RUN] {rep_name}: {len(deals)}件 → {method} (送信スキップ)")
            print(msg)
        elif rep_open_id:
            lark_send_bot_message(token, rep_open_id, msg, id_type="open_id")
            print(f"  {rep_name}にLark DM送信: {len(deals)}件")
        elif rep_email:
            send_email_notification(rep_email, f"【フォローリマインド】{len(deals)}件", msg)
            print(f"  {rep_name}にメール送信({rep_email}): {len(deals)}件")
        else:
            print(f"  {rep_name}: 通知先未設定のためスキップ")

        sent_ids.extend([d["record_id"] for d in deals])

    # CEO summary
    if all_reminders:
        summary_lines = [f"【本日のフォローリマインド】{len(all_reminders)}件\n"]
        for d in sorted(all_reminders, key=lambda x: x["diff_days"], reverse=True):
            if d["diff_days"] == -1:
                tag = "明日"
            elif d["diff_days"] == 0:
                tag = "本日"
            else:
                tag = f"{d['diff_days']}日超過"
            summary_lines.append(f"・{d['deal_name']}（{d['sales_rep']}, {tag}）→ {d['next_action']}")

        summary = "\n".join(summary_lines)
        if DRY_RUN:
            print(f"  [DRY-RUN] CEO summary:\n{summary}")
        else:
            lark_send_bot_message(token, CEO_OPEN_ID, summary, id_type="open_id")

    # Save state (skip in dry-run to avoid blocking real sends)
    if not DRY_RUN:
        reminder_state["sent_ids"].extend(sent_ids)
        with open(reminder_state_file, "w") as f:
            json.dump(reminder_state, f, ensure_ascii=False, indent=2)

    return len(all_reminders)


def check_data_quality():
    """Check CRM data quality and flag issues"""
    token = lark_get_token()
    all_deals = fetch_all_deals(token)

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
    all_deals = fetch_all_deals(token)

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    urgent_deals = []    # Hot + 1-30日超過 → 即時通知
    stale_deals = []     # 30日超過 → 週次サマリーのみ
    warm_deals = []      # Warm + 1-30日超過 → 週次サマリーのみ

    # State: avoid duplicate overdue notifications (1日1回まで per record)
    overdue_state_file = SCRIPT_DIR / "overdue_state.json"
    if overdue_state_file.exists():
        with open(overdue_state_file) as f:
            overdue_state = json.load(f)
    else:
        overdue_state = {"last_date": "", "notified_ids": []}

    # Reset if new day
    if overdue_state.get("last_date") != today_str:
        overdue_state = {"last_date": today_str, "notified_ids": []}

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

        # Resolve deal name: 取引先リンクフィールド → 商談名 → 新規取引先名
        deal_name = resolve_deal_name(fields)
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

        # Skip if already notified today
        record_id = rec.get("record_id", "")
        if record_id in overdue_state.get("notified_ids", []):
            continue

        if overdue_days > 30:
            stale_deals.append(deal_info)
        elif temp == "Hot":
            urgent_deals.append(deal_info)
            overdue_state["notified_ids"].append(record_id)
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
        if DRY_RUN:
            print(f"  [DRY-RUN] CEO DM: Hot案件{len(top)}件 (送信スキップ)")
            print(full_msg)
        else:
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

    # Save overdue state (prevent duplicate notifications)
    if not DRY_RUN:
        with open(overdue_state_file, "w") as f:
            json.dump(overdue_state, f, ensure_ascii=False)

    # Write to log
    log_file = SCRIPT_DIR / "crm_notifications.log"
    with open(log_file, "a") as f:
        f.write(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M')}] 期限超過サマリー: "
                f"urgent={len(urgent_deals)}, warm={len(warm_deals)}, stale={len(stale_deals)}\n{'─'*40}\n")

    return total


def check_hot_warm_no_action():
    """(a) Hot/Warm案件で次アクション未設定 → 即時アラート

    15分ごとの定期実行で毎回チェック。
    ただしノイズ防止のため、同じ案件は1日1回のみ通知（stateで管理）。
    """
    token = lark_get_token()
    all_deals = fetch_all_deals(token)
    state = load_state()

    # 通知済みレコードを追跡（1日単位でリセット）
    today_key = datetime.now().strftime("%Y-%m-%d")
    notified_today = state.get("hot_warm_notified", {})
    if notified_today.get("_date") != today_key:
        notified_today = {"_date": today_key}

    junk_patterns = ["テスト", "test", "サンプル", "sample", "ダミー"]
    alerts = []

    for rec in all_deals:
        fields = rec.get("fields", {})
        temp = fields.get("温度感スコア", "")
        if temp not in ("Hot", "Warm"):
            continue

        stage = fields.get("商談ステージ", "")
        if stage in ("失注", "受注"):
            continue

        next_action = fields.get("次アクション", "")
        if isinstance(next_action, list):
            next_action = ", ".join(str(a) for a in next_action)
        next_action_other = fields.get("次アクション：その他", "") or ""
        action_text = (next_action or "") + (f" {next_action_other}" if next_action_other else "")
        if action_text.strip() and action_text.strip() not in ("None", "なし"):
            continue  # action is set, skip

        deal_name = fields.get("商談名", "") or fields.get("新規取引先名", "") or ""
        if not deal_name or any(p in deal_name.lower() for p in junk_patterns):
            continue

        rec_id = rec.get("record_id", "")
        if rec_id in notified_today:
            continue  # already notified today

        sales_rep = extract_sales_rep(fields)
        alerts.append({
            "record_id": rec_id,
            "deal_name": deal_name,
            "temp": temp,
            "stage": stage or "(未設定)",
            "sales_rep": sales_rep,
        })
        notified_today[rec_id] = True

    print(f"[HOT/WARM未設定] 該当: {len(alerts)}件（本日未通知分）")

    if alerts:
        # Group by sales rep for targeted notifications
        by_rep = {}
        for a in alerts:
            rep = a["sales_rep"] or "未割当"
            by_rep.setdefault(rep, []).append(a)

        lines = [f"⚠️ Hot/Warm案件 次アクション未設定（{len(alerts)}件）\n"]
        for rep, deals in by_rep.items():
            lines.append(f"【{rep}】")
            for d in deals:
                lines.append(f"  [{d['temp']}] {d['deal_name']}（ステージ: {d['stage']}）")
            lines.append("")

        send_notification(
            token,
            "⚠️ 次アクション未設定アラート",
            "\n".join(lines),
            priority="high"
        )

        # Also send per-rep notification
        for rep, deals in by_rep.items():
            rep_cfg = SALES_REPS.get(rep) or {}
            rep_open_id = rep_cfg.get("open_id") if isinstance(rep_cfg, dict) else None
            rep_email = rep_cfg.get("email") if isinstance(rep_cfg, dict) else None
            if not DRY_RUN:
                rep_lines = [f"⚠️ {rep}さん: 次アクション未設定（{len(deals)}件）\n"]
                for d in deals:
                    rep_lines.append(f"  [{d['temp']}] {d['deal_name']}")
                rep_lines.append("\nCRMで次アクションを設定してください。")
                rep_msg = "\n".join(rep_lines)
                if rep_open_id:
                    lark_send_bot_message(token, rep_open_id, rep_msg, id_type="open_id")
                elif rep_email:
                    send_email_notification(rep_email, "【要対応】次アクション未設定", rep_msg)

    # Save notification state
    state["hot_warm_notified"] = notified_today
    save_state(state)
    return len(alerts)


def check_stagnant_deals():
    """(b) 商談ステージが14日以上変更なし → 停滞アラート

    Lark Bitableのレコード更新日時を利用。
    失注/受注/不在ステージは除外。1日1回の通知で十分（週次 or daily）。
    """
    token = lark_get_token()
    all_deals = fetch_all_deals(token)
    now = datetime.now()
    stagnant_threshold_days = 14

    junk_patterns = ["テスト", "test", "サンプル", "sample", "ダミー"]
    stagnant = []

    for rec in all_deals:
        fields = rec.get("fields", {})
        stage = fields.get("商談ステージ", "")
        temp = fields.get("温度感スコア", "")

        # Only check active deals (skip terminal stages and cold/unset)
        if stage in ("失注", "受注", "不在", ""):
            continue

        deal_name = fields.get("商談名", "") or fields.get("新規取引先名", "") or ""
        if not deal_name or any(p in deal_name.lower() for p in junk_patterns):
            continue

        # Use Lark record last_modified_time (Unix ms) as proxy for last activity
        # If 商談日 is available and more recent, use that instead
        last_activity = None

        # Check 商談日 field
        deal_date = fields.get("商談日", "")
        if isinstance(deal_date, (int, float)) and deal_date > 0:
            try:
                last_activity = datetime.fromtimestamp(deal_date / 1000)
            except (ValueError, OSError):
                pass

        # Check 次アクション日 — if in the future, deal is not stagnant
        next_action_date = fields.get("次アクション日", "")
        if isinstance(next_action_date, (int, float)) and next_action_date > 0:
            try:
                nad = datetime.fromtimestamp(next_action_date / 1000)
                if nad > now:
                    continue  # future action planned, not stagnant
                # If action date is more recent than deal date, use it
                if last_activity is None or nad > last_activity:
                    last_activity = nad
            except (ValueError, OSError):
                pass

        if last_activity is None:
            continue  # No date info, can't determine stagnation

        days_stagnant = (now - last_activity).days
        if days_stagnant >= stagnant_threshold_days:
            sales_rep = extract_sales_rep(fields)
            stagnant.append({
                "deal_name": deal_name,
                "stage": stage,
                "temp": temp or "(未設定)",
                "days_stagnant": days_stagnant,
                "last_activity": last_activity.strftime("%Y-%m-%d"),
                "sales_rep": sales_rep,
            })

    stagnant.sort(key=lambda x: x["days_stagnant"], reverse=True)
    print(f"[STAGNANT] {stagnant_threshold_days}日以上停滞: {len(stagnant)}件")

    if stagnant:
        # Group by rep
        by_rep = {}
        for d in stagnant:
            rep = d["sales_rep"] or "未割当"
            by_rep.setdefault(rep, []).append(d)

        lines = [f"🔄 商談ステージ停滞アラート（14日以上動きなし: {len(stagnant)}件）\n"]
        for rep, deals in by_rep.items():
            lines.append(f"【{rep}】{len(deals)}件")
            for d in deals[:5]:
                lines.append(
                    f"  {d['deal_name']}（{d['stage']}/{d['temp']}）"
                    f"— {d['days_stagnant']}日停滞（最終: {d['last_activity']}）"
                )
            if len(deals) > 5:
                lines.append(f"  ... 他{len(deals)-5}件")
            lines.append("")

        lines.append("→ ステージ更新 or 失注クローズの判断をお願いします。")

        send_notification(
            token,
            "🔄 商談停滞アラート",
            "\n".join(lines),
            priority="normal"
        )

    return len(stagnant)


def check_new_deal_missing_fields():
    """(c) 新規商談登録時にステージ・温度感未設定 → 入力催促アラート

    直近24時間以内に作成されたレコードで、ステージ or 温度感が未設定のものを検出。
    15分ごとの実行で拾うが、同一レコードは1日1回のみ通知。
    """
    token = lark_get_token()
    all_deals = fetch_all_deals(token)
    state = load_state()
    now = datetime.now()

    # 通知済みレコードを追跡
    today_key = now.strftime("%Y-%m-%d")
    notified_new = state.get("new_deal_notified", {})
    if notified_new.get("_date") != today_key:
        notified_new = {"_date": today_key}

    junk_patterns = ["テスト", "test", "サンプル", "sample", "ダミー"]
    incomplete = []

    for rec in all_deals:
        fields = rec.get("fields", {})
        rec_id = rec.get("record_id", "")

        # Check if created within last 24 hours using 商談日 or record creation
        # Lark API doesn't expose created_time directly in bitable, so use 商談日
        deal_date = fields.get("商談日", "")
        if isinstance(deal_date, (int, float)) and deal_date > 0:
            try:
                created = datetime.fromtimestamp(deal_date / 1000)
                hours_ago = (now - created).total_seconds() / 3600
                if hours_ago > 24:
                    continue
            except (ValueError, OSError):
                continue
        else:
            continue  # No date, can't determine if new

        deal_name = fields.get("商談名", "") or fields.get("新規取引先名", "") or ""
        if not deal_name or any(p in deal_name.lower() for p in junk_patterns):
            continue

        stage = fields.get("商談ステージ", "")
        temp = fields.get("温度感スコア", "")

        missing = []
        if not stage:
            missing.append("ステージ")
        if not temp:
            missing.append("温度感")

        if not missing:
            continue

        if rec_id in notified_new:
            continue

        sales_rep = extract_sales_rep(fields)
        incomplete.append({
            "record_id": rec_id,
            "deal_name": deal_name,
            "sales_rep": sales_rep,
            "missing": missing,
        })
        notified_new[rec_id] = True

    print(f"[NEW DEAL CHECK] 直近24h新規で未入力: {len(incomplete)}件")

    if incomplete:
        lines = [f"📝 新規商談 入力不足アラート（{len(incomplete)}件）\n"]
        for d in incomplete:
            lines.append(
                f"  {d['deal_name']}（{d['sales_rep'] or '担当未設定'}）"
                f"— 未入力: {', '.join(d['missing'])}"
            )
        lines.append("\n→ 商談報告後、ステージ・温度感を必ず設定してください。")

        send_notification(
            token,
            "📝 新規商談 入力催促",
            "\n".join(lines),
            priority="normal"
        )

        # Per-rep notification
        for d in incomplete:
            rep_cfg = SALES_REPS.get(d["sales_rep"]) or {}
            msg = (
                f"入力催促: {d['deal_name']}\n"
                f"未入力: {', '.join(d['missing'])}\n"
                f"CRMで設定をお願いします。"
            )
            if not DRY_RUN:
                if isinstance(rep_cfg, dict) and rep_cfg.get("open_id"):
                    lark_send_bot_message(token, rep_cfg["open_id"], msg, id_type="open_id")
                elif isinstance(rep_cfg, dict) and rep_cfg.get("email"):
                    send_email_notification(rep_cfg["email"], "【入力催促】CRM商談データ", msg)

    state["new_deal_notified"] = notified_new
    save_state(state)
    return len(incomplete)


def generate_weekly_summary():
    """(d) 週次サマリー：ステージ進捗率、アクション実行率、担当別パフォーマンス

    --weekly で実行。GitHub Actionsの weekly_kpi と同じタイミング（月曜9時）推奨。
    """
    token = lark_get_token()
    all_deals = fetch_all_deals(token)

    total = len(all_deals)
    stage_counts = {}
    temp_counts = {}
    no_stage = 0
    no_action = 0
    no_temp = 0
    by_rep = {}
    terminal_stages = ("受注", "失注")

    for rec in all_deals:
        fields = rec.get("fields", {})
        stage = fields.get("商談ステージ", "") or ""
        temp = fields.get("温度感スコア", "") or ""
        next_action = fields.get("次アクション", "")
        if isinstance(next_action, list):
            next_action = ", ".join(str(a) for a in next_action)
        sales_rep = extract_sales_rep(fields) or "未割当"

        # Stage distribution
        stage_label = stage or "(未設定)"
        stage_counts[stage_label] = stage_counts.get(stage_label, 0) + 1

        # Temp distribution
        temp_label = temp or "(未設定)"
        temp_counts[temp_label] = temp_counts.get(temp_label, 0) + 1

        if not stage:
            no_stage += 1
        if not temp:
            no_temp += 1
        if not next_action or str(next_action).strip() in ("", "None", "なし"):
            no_action += 1

        # Per-rep stats
        if sales_rep not in by_rep:
            by_rep[sales_rep] = {"total": 0, "no_stage": 0, "no_action": 0, "hot": 0, "warm": 0, "won": 0, "lost": 0}
        by_rep[sales_rep]["total"] += 1
        if not stage:
            by_rep[sales_rep]["no_stage"] += 1
        if not next_action or str(next_action).strip() in ("", "None", "なし"):
            by_rep[sales_rep]["no_action"] += 1
        if temp == "Hot":
            by_rep[sales_rep]["hot"] += 1
        elif temp == "Warm":
            by_rep[sales_rep]["warm"] += 1
        if stage == "受注":
            by_rep[sales_rep]["won"] += 1
        elif stage == "失注":
            by_rep[sales_rep]["lost"] += 1

    # Calculate rates
    stage_set_rate = ((total - no_stage) / total * 100) if total else 0
    action_set_rate = ((total - no_action) / total * 100) if total else 0
    temp_set_rate = ((total - no_temp) / total * 100) if total else 0

    lines = [
        f"📊 週次CRMサマリー ({datetime.now().strftime('%Y-%m-%d')})",
        f"{'='*50}",
        f"",
        f"■ 全体指標（商談{total}件）",
        f"  ステージ設定率: {stage_set_rate:.1f}% ({total - no_stage}/{total})",
        f"  温度感設定率:   {temp_set_rate:.1f}% ({total - no_temp}/{total})",
        f"  アクション設定率: {action_set_rate:.1f}% ({total - no_action}/{total})",
        f"",
        f"■ ステージ分布",
    ]
    for s, c in sorted(stage_counts.items(), key=lambda x: -x[1]):
        pct = c / total * 100 if total else 0
        bar = "█" * int(pct / 5)
        lines.append(f"  {s}: {c}件 ({pct:.1f}%) {bar}")

    lines.append(f"\n■ 温度感分布")
    for t, c in sorted(temp_counts.items(), key=lambda x: -x[1]):
        pct = c / total * 100 if total else 0
        lines.append(f"  {t}: {c}件 ({pct:.1f}%)")

    lines.append(f"\n■ 担当別パフォーマンス")
    for rep, stats in sorted(by_rep.items(), key=lambda x: -x[1]["total"]):
        if rep == "未割当":
            continue
        rep_stage_rate = ((stats["total"] - stats["no_stage"]) / stats["total"] * 100) if stats["total"] else 0
        rep_action_rate = ((stats["total"] - stats["no_action"]) / stats["total"] * 100) if stats["total"] else 0
        lines.append(
            f"  {rep}: {stats['total']}件 "
            f"(Hot:{stats['hot']}/Warm:{stats['warm']}/受注:{stats['won']}/失注:{stats['lost']}) "
            f"ステージ{rep_stage_rate:.0f}% アクション{rep_action_rate:.0f}%"
        )

    # Unassigned summary
    if "未割当" in by_rep:
        u = by_rep["未割当"]
        lines.append(f"\n  ⚠️ 担当未割当: {u['total']}件")

    send_notification(
        token,
        "📊 週次CRMサマリー",
        "\n".join(lines),
        priority="normal"
    )

    return {
        "total": total,
        "stage_set_rate": stage_set_rate,
        "action_set_rate": action_set_rate,
        "temp_set_rate": temp_set_rate,
    }


def main():
    global DRY_RUN
    args = sys.argv[1:]

    if "--dry-run" in args:
        DRY_RUN = True
        print("=" * 60)
        print("DRY-RUN MODE: 通知は送信されません（コンソール出力のみ）")
        print("=" * 60)

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
                check_hot_warm_no_action()
                check_new_deal_missing_fields()
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

    if "--remind" in args:
        print("Running action reminders...")
        count = check_action_reminders()
        print(f"Sent {count} reminders")
        return

    if "--stagnant" in args:
        print("Running stagnant deal check...")
        count = check_stagnant_deals()
        print(f"Found {count} stagnant deals (14+ days)")
        return

    if "--weekly" in args:
        print("Generating weekly summary...")
        result = generate_weekly_summary()
        print(f"Weekly summary: {result}")
        return

    # Default: single check (new records + overdue + hot/warm + new deal fields + stagnant)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for new CRM records...")
    found = check_for_new_records()
    if not found:
        print("No new records.")

    # Check for overdue actions
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for overdue actions...")
    try:
        check_overdue_actions()
    except Exception as e:
        print(f"[ERROR] Overdue check failed: {e}")

    # (a) Hot/Warm案件で次アクション未設定
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking Hot/Warm deals without next action...")
    try:
        check_hot_warm_no_action()
    except Exception as e:
        print(f"[ERROR] Hot/Warm no-action check failed: {e}")

    # (c) 新規商談の入力不足チェック
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking new deals for missing fields...")
    try:
        check_new_deal_missing_fields()
    except Exception as e:
        print(f"[ERROR] New deal field check failed: {e}")

    # (b2) フォローリマインド — 朝1回（8:00-9:00）
    current_hour = datetime.now().hour
    if current_hour == 8 or "--remind" in args:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Sending action reminders to sales reps...")
        try:
            check_action_reminders()
        except Exception as e:
            print(f"[ERROR] Action reminder failed: {e}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Reminder check skipped (runs at 08:xx only)")

    # (b) 停滞チェック — 1日1回で十分なので、8:00-9:00の実行時のみ
    if current_hour == 8 or "--stagnant" in args:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking for stagnant deals...")
        try:
            check_stagnant_deals()
        except Exception as e:
            print(f"[ERROR] Stagnant deal check failed: {e}")
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Stagnant check skipped (runs at 08:xx only)")


if __name__ == "__main__":
    main()
