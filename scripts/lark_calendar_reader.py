#!/usr/bin/env python3
"""
lark_calendar_reader.py - Larkカレンダー予定取得

前提: TAS-Automation Bot に以下の権限が必要:
  - calendar:calendar:readonly
  - calendar:calendar.event:read
（Lark管理コンソール > アプリ管理 > TAS-Automation > 権限管理で追加）

Usage:
  python lark_calendar_reader.py              # 今日の予定を表示
  python lark_calendar_reader.py --days 7     # 今後7日の予定
  python lark_calendar_reader.py --briefing   # daily_briefing用フォーマット
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── Configuration ──
SCRIPT_DIR = Path(__file__).parent

for _p in [
    Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
    SCRIPT_DIR / "automation_config.json",
]:
    if _p.exists():
        with open(_p) as f:
            _cfg = json.load(f)
        if not str(_cfg.get("lark", {}).get("app_id", "")).startswith("${"):
            CONFIG = _cfg
            break
else:
    raise FileNotFoundError("automation_config.json not found")

if "CONFIG" not in dir():
    CONFIG = _cfg

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]

# CEO open_id for calendar lookup
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"


def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["tenant_access_token"]


def get_primary_calendar_id(token):
    """Get the user's primary calendar ID."""
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/calendar/v4/calendars/primary",
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("data", {}).get("calendars", [{}])[0].get("calendar", {}).get("calendar_id")
    except Exception as e:
        print(f"  [WARN] Primary calendar lookup failed: {e}")
        return None


def list_calendar_events(token, calendar_id, start_time, end_time):
    """List events in a calendar within time range."""
    # Lark uses Unix timestamp in seconds (string)
    start_ts = str(int(start_time.timestamp()))
    end_ts = str(int(end_time.timestamp()))

    url = (
        f"https://open.larksuite.com/open-apis/calendar/v4/calendars/{calendar_id}/events"
        f"?start_time={start_ts}&end_time={end_ts}&page_size=50"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("data", {}).get("items", [])
    except Exception as e:
        print(f"  [WARN] Calendar events fetch failed: {e}")
        return []


def format_event(event):
    """Format a single event for display."""
    summary = event.get("summary", "(無題)")
    start = event.get("start_time", {})
    end = event.get("end_time", {})

    # Parse timestamps
    start_dt = None
    if isinstance(start, dict):
        ts = start.get("timestamp") or start.get("date")
        if ts:
            try:
                start_dt = datetime.fromtimestamp(int(ts))
            except (ValueError, TypeError):
                pass
    elif isinstance(start, str):
        try:
            start_dt = datetime.fromtimestamp(int(start))
        except (ValueError, TypeError):
            pass

    end_dt = None
    if isinstance(end, dict):
        ts = end.get("timestamp") or end.get("date")
        if ts:
            try:
                end_dt = datetime.fromtimestamp(int(ts))
            except (ValueError, TypeError):
                pass

    time_str = ""
    if start_dt:
        time_str = start_dt.strftime("%H:%M")
        if end_dt:
            time_str += f"-{end_dt.strftime('%H:%M')}"

    location = event.get("location", {}).get("name", "")
    loc_str = f" @{location}" if location else ""

    return f"  {time_str} {summary}{loc_str}"


def build_calendar_briefing(days=1):
    """Build calendar section for daily briefing."""
    try:
        token = lark_get_token()
        calendar_id = get_primary_calendar_id(token)

        if not calendar_id:
            return "■ 今日の予定\n  [カレンダーID取得失敗 - 権限を確認してください]"

        now = datetime.now()
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=days)

        events = list_calendar_events(token, calendar_id, start, end)

        if not events:
            label = "今日の予定" if days == 1 else f"今後{days}日の予定"
            return f"■ {label}\n  予定なし"

        lines = [f"■ 今日の予定 ({len(events)}件)"]
        for event in sorted(events, key=lambda e: e.get("start_time", {}).get("timestamp", "0")):
            lines.append(format_event(event))

        return "\n".join(lines)

    except Exception as e:
        return f"■ 今日の予定\n  [取得失敗: {e}]"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lark Calendar Reader")
    parser.add_argument("--days", type=int, default=1, help="Number of days to look ahead")
    parser.add_argument("--briefing", action="store_true", help="Output in briefing format")
    args = parser.parse_args()

    if args.briefing:
        print(build_calendar_briefing(args.days))
        return

    token = lark_get_token()
    print("Lark認証OK")

    calendar_id = get_primary_calendar_id(token)
    if not calendar_id:
        print("[ERROR] カレンダーID取得失敗")
        print("TAS-Automation Botに以下の権限が必要です:")
        print("  - calendar:calendar:readonly")
        print("  - calendar:calendar.event:read")
        print("Lark管理コンソール > アプリ管理 > TAS-Automation > 権限管理で追加してください")
        sys.exit(1)

    print(f"カレンダーID: {calendar_id}")

    now = datetime.now()
    start = datetime(now.year, now.month, now.day)
    end = start + timedelta(days=args.days)

    events = list_calendar_events(token, calendar_id, start, end)
    print(f"\n今後{args.days}日の予定: {len(events)}件")
    for event in events:
        print(format_event(event))


if __name__ == "__main__":
    main()
