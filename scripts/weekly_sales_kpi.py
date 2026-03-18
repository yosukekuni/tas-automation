#!/usr/bin/env python3
"""
週次営業KPIレポート自動生成
毎週月曜朝に実行 → Lark通知でCEOに送信

Usage:
  python3 weekly_sales_kpi.py          # 先週分レポート
  python3 weekly_sales_kpi.py --month  # 今月分レポート
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

# Lark Mail config
MAILBOX = "info@tokaiair.com"

# Spark local DB (fallback for historical emails)
SPARK_DB_PATHS = [
    Path("/tmp/spark_messages.sqlite"),  # copied from live DB
]

# Sales rep names in CRM
REPS = ["新美 光", "ユーザー550372"]  # ユーザー550372 = 政木
REP_DISPLAY = {"新美 光": "新美", "ユーザー550372": "政木"}

# KPI targets
TARGETS = {
    "weekly_activities": 10,  # 週間活動数目標
    "hearing_rate": 0.5,      # ヒアリング到達率目標
    "next_action_set": 1.0,   # 次アクション設定率目標（100%）
    "estimate_rate": 0.3,     # 見積提出率目標
}


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
        result = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                    if not body:
                        print(f"[WARN] Empty response (attempt {attempt+1}/3), retrying...")
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
                print(f"[WARN] API error (attempt {attempt+1}/3): {e}")
                time.sleep(5 * (attempt + 1))
        if result is None:
            print(f"[ERROR] Failed to fetch records after 3 attempts for table {table_id}")
            break
        d = result.get("data", {})
        records.extend(d.get("items", []))
        if not d.get("has_more"):
            break
        page_token = d.get("page_token")
        time.sleep(0.3)
    return records


def get_recent_emails(token, days=7):
    """Lark Mail APIから直近のメール取得 → 取引先ごとの最終連絡日を返す"""
    contact_activity = {}  # domain/email -> latest date
    try:
        # Get message ID list
        msg_ids = []
        page_token = None
        for _ in range(5):  # max 5 pages = 1000 messages
            url = f"https://open.larksuite.com/open-apis/mail/v1/user_mailboxes/{MAILBOX}/messages?folder_id=INBOX&page_size=200"
            if page_token:
                url += f"&page_token={page_token}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req) as r:
                result = json.loads(r.read())
                d = result.get("data", {})
                msg_ids.extend(d.get("items", []))
                if not d.get("has_more"):
                    break
                page_token = d.get("page_token")
                time.sleep(0.3)

        # Fetch individual messages (limit to recent 50 for speed)
        cutoff = datetime.now() - timedelta(days=days)
        for mid in msg_ids[:50]:
            try:
                encoded_mid = urllib.parse.quote(str(mid), safe="")
                url = f"https://open.larksuite.com/open-apis/mail/v1/user_mailboxes/{MAILBOX}/messages/{encoded_mid}"
                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req) as r:
                    msg = json.loads(r.read()).get("data", {}).get("message", {})

                ts = msg.get("internal_date", 0)
                if isinstance(ts, str):
                    ts = int(ts)
                # internal_date is epoch milliseconds
                dt = datetime.fromtimestamp(ts / 1000) if ts > 1e12 else datetime.fromtimestamp(ts) if ts > 0 else None
                if not dt or dt < cutoff:
                    continue

                # Collect all external addresses
                sender = msg.get("head_from", {}).get("mail_address", "")
                to_list = [t.get("mail_address", "") for t in msg.get("to", [])]
                all_addrs = [sender] + to_list
                for addr in all_addrs:
                    if addr and "@tokaiair.com" not in addr and "@" in addr and "larksuite.com" not in addr:
                        domain = addr.split("@")[1]
                        if domain not in contact_activity or contact_activity[domain] < dt:
                            contact_activity[domain] = dt
                        if addr not in contact_activity or contact_activity[addr] < dt:
                            contact_activity[addr] = dt
                time.sleep(0.2)
            except Exception:
                continue
    except Exception as e:
        print(f"[Mail API取得エラー: {e}]")
    return contact_activity


def get_spark_email_activity(days=14):
    """Spark SQLiteキャッシュから直近のメール活動を取得"""
    contact_activity = {}
    import sqlite3
    for db_path in SPARK_DB_PATHS:
        if not db_path.exists():
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cutoff = datetime.now() - timedelta(days=days)
            cutoff_ts = int(cutoff.timestamp())
            cur = conn.execute("""
                SELECT messageFromMailbox, receivedDate FROM messages
                WHERE receivedDate > ? AND messageFromMailbox NOT LIKE '%tokaiair.com%'
                  AND messageFromMailbox IS NOT NULL AND messageFromMailbox != ''
                ORDER BY receivedDate DESC LIMIT 500
            """, (cutoff_ts,))
            for row in cur:
                addr, ts = row
                if not addr or "@" not in addr:
                    continue
                dt = datetime.fromtimestamp(ts) if ts else None
                if not dt:
                    continue
                domain = addr.split("@")[1]
                if domain not in contact_activity or contact_activity[domain] < dt:
                    contact_activity[domain] = dt
                if addr not in contact_activity or contact_activity[addr] < dt:
                    contact_activity[addr] = dt
            conn.close()
        except Exception as e:
            print(f"[Spark DB読取エラー: {e}]")
    return contact_activity


def cross_check_crm_vs_email(deals, accounts, contacts, email_activity, token):
    """CRMステータスとメール実態の矛盾を検出"""
    now = datetime.now()
    discrepancies = []

    # Build account domain map from contacts
    contact_domains = {}  # account_name -> set of email domains
    for rec in contacts:
        f = rec.get("fields", {})
        email = str(f.get("メールアドレス", "") or "")
        account = f.get("取引先", "")
        if isinstance(account, list):
            for a in account:
                if isinstance(a, dict):
                    account = a.get("text_value", str(a))
                    break
        if email and "@" in email and account:
            domain = email.split("@")[1]
            if account not in contact_domains:
                contact_domains[account] = set()
            contact_domains[account].add(domain)
            contact_domains[account].add(email)

    for rec in deals:
        f = rec.get("fields", {})
        stage = str(f.get("商談ステージ", "") or "")
        temp = str(f.get("温度感スコア", "") or "")
        deal_name = str(f.get("商談名", "") or "")

        if temp not in ("Hot", "Warm"):
            continue

        # Find associated email domain
        account = f.get("取引先", "")
        if isinstance(account, list):
            for a in account:
                if isinstance(a, dict):
                    account = a.get("text_value", str(a))
                    break
        account = str(account)

        # Check if any email activity exists for this account
        domains = contact_domains.get(account, set())
        latest_email = None
        for d in domains:
            if d in email_activity and (latest_email is None or email_activity[d] > latest_email):
                latest_email = email_activity[d]

        if latest_email:
            days_since = (now - latest_email).days
            if days_since > 14 and temp == "Hot":
                discrepancies.append({
                    "type": "hot_no_recent_email",
                    "deal": deal_name[:30],
                    "temp": temp,
                    "last_email": latest_email.strftime("%m/%d"),
                    "days": days_since,
                })
        else:
            # Hot/Warm but NO email record at all
            if temp == "Hot":
                discrepancies.append({
                    "type": "hot_no_email_record",
                    "deal": deal_name[:30],
                    "temp": temp,
                    "last_email": "なし",
                    "days": -1,
                })

    return discrepancies


def send_webhook(text):
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


def generate_report(period="week"):
    token = lark_get_token()
    now = datetime.now()

    if period == "month":
        start_date = now.replace(day=1)
        period_label = f"{now.year}年{now.month}月"
    else:
        # Last 7 days
        start_date = now - timedelta(days=7)
        period_label = f"{start_date.strftime('%m/%d')}〜{now.strftime('%m/%d')}"

    start_ts = int(start_date.timestamp() * 1000)

    # Get all deals, accounts, contacts
    deals = get_all_records(token, "tbl1rM86nAw9l3bP")
    contacts = get_all_records(token, "tblN53hFIQoo4W8j")
    accounts = get_all_records(token, "tblTfGScQIdLTYxA")

    # Get email activity from multiple sources
    print("[メール履歴を照合中...]")
    email_activity = get_recent_emails(token, days=14)
    spark_activity = get_spark_email_activity(days=14)
    # Merge (latest wins)
    for k, v in spark_activity.items():
        if k not in email_activity or email_activity[k] < v:
            email_activity[k] = v

    # Cross-check CRM vs actual email activity
    discrepancies = cross_check_crm_vs_email(deals, accounts, contacts, email_activity, token)

    # Filter by period and rep
    rep_data = defaultdict(lambda: {
        "total": 0,
        "stages": defaultdict(int),
        "hot_warm": 0,
        "next_action_set": 0,
        "next_action_overdue": 0,
        "new_customers": 0,
        "existing_customers": 0,
        "deals_with_amount": 0,
        "total_amount": 0,
    })

    stale_deals = []  # No activity for 14+ days

    for rec in deals:
        f = rec.get("fields", {})

        # Get rep name
        rep_field = f.get("担当営業", [])
        rep_name = ""
        if isinstance(rep_field, list):
            for p in rep_field:
                if isinstance(p, dict):
                    rep_name = p.get("name", "")
                elif isinstance(p, str):
                    rep_name = p

        if rep_name not in REPS:
            continue

        # Check date
        deal_date = f.get("商談日")
        if not isinstance(deal_date, (int, float)):
            continue

        if deal_date < start_ts:
            # Check for stale deals (has next_action_date in the past)
            next_date = f.get("次アクション日")
            if isinstance(next_date, (int, float)):
                next_dt = datetime.fromtimestamp(next_date / 1000)
                if next_dt < now - timedelta(days=14):
                    stage = str(f.get("商談ステージ", "") or "")
                    temp = str(f.get("温度感スコア", "") or "")
                    if stage not in ("不在", "") and temp in ("Hot", "Warm"):
                        deal_name = str(f.get("商談名", "") or "(名前なし)")
                        stale_deals.append({
                            "rep": REP_DISPLAY.get(rep_name, rep_name),
                            "name": deal_name[:30],
                            "temp": temp,
                            "overdue_days": (now - next_dt).days,
                        })
            continue

        rd = rep_data[rep_name]
        rd["total"] += 1

        stage = str(f.get("商談ステージ", "") or "(未設定)")
        rd["stages"][stage] += 1

        temp = str(f.get("温度感スコア", "") or "")
        if temp in ("Hot", "Warm"):
            rd["hot_warm"] += 1

        next_action = f.get("次アクション", "")
        next_date = f.get("次アクション日")
        if next_action:
            rd["next_action_set"] += 1
        if isinstance(next_date, (int, float)) and next_date < int(now.timestamp() * 1000):
            rd["next_action_overdue"] += 1

        new_existing = str(f.get("新規・既存客の別", "") or "")
        if "新規" in new_existing:
            rd["new_customers"] += 1
        else:
            rd["existing_customers"] += 1

        amt = f.get("見積・予算金額")
        if amt:
            try:
                rd["total_amount"] += float(amt)
                rd["deals_with_amount"] += 1
            except (ValueError, TypeError):
                pass

    # Build report
    lines = [
        f"📊 営業KPIレポート（{period_label}）",
        f"生成: {now.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    for rep_name in REPS:
        display = REP_DISPLAY.get(rep_name, rep_name)
        rd = rep_data[rep_name]

        if rd["total"] == 0:
            lines.append(f"■ {display}: 活動なし ⚠️")
            lines.append("")
            continue

        hearing = rd["stages"].get("ヒアリング", 0)
        hearing_rate = hearing / rd["total"] * 100 if rd["total"] > 0 else 0
        absent = rd["stages"].get("不在", 0)
        absent_rate = absent / rd["total"] * 100 if rd["total"] > 0 else 0
        next_rate = rd["next_action_set"] / rd["total"] * 100 if rd["total"] > 0 else 0

        # Status emoji
        activity_ok = "✅" if rd["total"] >= TARGETS["weekly_activities"] else "⚠️"
        hearing_ok = "✅" if hearing_rate >= TARGETS["hearing_rate"] * 100 else "⚠️"

        lines.extend([
            f"■ {display}",
            f"  活動数: {rd['total']}件 {activity_ok}（目標{TARGETS['weekly_activities']}件）",
            f"  ヒアリング: {hearing}件 ({hearing_rate:.0f}%) {hearing_ok}",
            f"  不在: {absent}件 ({absent_rate:.0f}%)",
            f"  Hot/Warm: {rd['hot_warm']}件",
            f"  次アクション設定: {next_rate:.0f}%",
            f"  次アクション期限切れ: {rd['next_action_overdue']}件",
            f"  新規/既存: {rd['new_customers']}/{rd['existing_customers']}",
        ])
        if rd["total_amount"] > 0:
            lines.append(f"  見積金額合計: ¥{rd['total_amount']:,.0f}")
        lines.append("")

    # Stale deals alert
    if stale_deals:
        lines.extend([
            f"⚠️ フォロー遅延（Hot/Warm案件）: {len(stale_deals)}件",
        ])
        for sd in sorted(stale_deals, key=lambda x: -x["overdue_days"])[:10]:
            lines.append(f"  [{sd['rep']}] {sd['name']} ({sd['temp']}) — {sd['overdue_days']}日超過")
        lines.append("")

    # CRM vs Email discrepancies
    if discrepancies:
        lines.extend([
            f"🔍 CRM×メール照合アラート: {len(discrepancies)}件",
        ])
        for d in discrepancies:
            if d["type"] == "hot_no_recent_email":
                lines.append(f"  ⚠️ {d['deal']} ({d['temp']}) — 最終メール{d['last_email']}（{d['days']}日前）")
            elif d["type"] == "hot_no_email_record":
                lines.append(f"  ❌ {d['deal']} ({d['temp']}) — メール記録なし（CRMだけHot）")
        lines.append("")

    # Email activity summary
    if email_activity:
        recent_count = sum(1 for dt in email_activity.values() if (now - dt).days <= 7)
        lines.extend([
            f"📧 メール活動（直近7日）: {recent_count}件の外部ドメインとやり取り",
            "",
        ])

    # Summary
    total_all = sum(rd["total"] for rd in rep_data.values())
    lines.extend([
        "─" * 30,
        f"チーム合計: {total_all}件",
        f"受注: 0件（前週比±0）",
        "",
        "※ 改善ポイント:",
        "  1. ヒアリング後に必ず見積提出 or デモ飛行を提案",
        "  2. 次アクション期限切れは当日中にフォロー",
        "  3. Hot/Warm案件は國本にエスカレーション",
    ])

    report = "\n".join(lines)

    # Output
    print(report)

    # Send webhook
    sent = send_webhook(report)
    if sent:
        print("\n[Webhook送信完了]")

    # Save to log
    log_file = SCRIPT_DIR / "weekly_kpi.log"
    with open(log_file, "a") as lf:
        lf.write(f"\n{'='*50}\n{report}\n")

    return report


def main():
    args = sys.argv[1:]
    if "--month" in args:
        generate_report("month")
    else:
        generate_report("week")


if __name__ == "__main__":
    main()
