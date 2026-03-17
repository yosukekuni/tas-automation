#!/usr/bin/env python3
"""
daily_briefing.py - 日次モーニングレポート
毎朝7:00 JST（22:00 UTC前日）にGitHub Actionsで実行。
5セクションを集約してLark Bot DMでCEOに1メッセージ送信。

Usage:
  python daily_briefing.py              # 実行（Lark DM送信）
  python daily_briefing.py --dry-run    # ドライラン（送信しない）

Sections:
  1. 昨日の商談報告サマリー
  2. 今日の予定タスク
  3. CRMアラート要約
  4. GA4 前日PV（TOP5ページ）
  5. 入札情報新着
  6. freee未請求サマリー
  7. freee未入金サマリー
"""

import json
import os
import sys
import time
import ssl
import base64
import hashlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ──
SCRIPT_DIR = Path(__file__).parent
LOG_FILE = SCRIPT_DIR / "daily_briefing.log"

# Lark credentials
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
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
TASK_BASE_TOKEN = CONFIG["lark"].get("task_base_token", "HSSMb3T2jalcuysFCjGjJ76wpKe")

# CRM table IDs
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# Task management table
TASK_TABLE_ID = "tblGrFhJrAyYYWbV"

# CEO notification
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# GA4
GA4_PROPERTY_ID = CONFIG.get("google", {}).get("ga4_property_id", "499408061") or "499408061"
SERVICE_ACCOUNT_EMAIL = "service-account@drive-organizer-489313.iam.gserviceaccount.com"
GA4_SCOPES = "https://www.googleapis.com/auth/analytics.readonly"
GA4_API = f"https://analyticsdata.googleapis.com/v1beta/properties/{GA4_PROPERTY_ID}:runReport"

# State file for week-over-week comparison
STATE_FILE = SCRIPT_DIR / "daily_briefing_state.json"

# SSL context for gov sites
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Weekday names
WEEKDAY_JA = ["月", "火", "水", "木", "金", "土", "日"]

DRY_RUN = False


# ── Lark API helpers ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())["tenant_access_token"]


def lark_get_all_records(token, table_id, base_token=None):
    """Get all records from a Lark Bitable table."""
    bt = base_token or CRM_BASE_TOKEN
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{bt}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                d = result.get("data", {})
                records.extend(d.get("items", []))
                if not d.get("has_more"):
                    break
                page_token = d.get("page_token")
                time.sleep(0.3)
        except Exception as e:
            print(f"  [WARN] Lark API error: {e}")
            break
    return records


def lark_send_bot_message(token, open_id, text):
    """Send Lark Bot DM to CEO."""
    if DRY_RUN:
        print("[DRY-RUN] Lark DM not sent")
        return True
    data = json.dumps({
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                print("  Lark DM sent successfully")
                return True
            else:
                print(f"  Lark DM error: {result.get('msg', 'unknown')}")
                return False
    except Exception as e:
        print(f"  Lark DM failed: {e}")
        return False


# ── Field extraction helpers (from weekly_sales_report.py) ──
def extract_text(field_value):
    if isinstance(field_value, str):
        return field_value
    if isinstance(field_value, list):
        for item in field_value:
            if isinstance(item, dict):
                return item.get("text", "") or item.get("text_value", "") or ""
            if isinstance(item, str):
                return item
    return str(field_value or "")


def extract_rep_name(field_value):
    if isinstance(field_value, list):
        for p in field_value:
            if isinstance(p, dict):
                return p.get("name", "")
            if isinstance(p, str):
                return p
    return str(field_value or "")


def resolve_company_name(fields):
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
    deal_name = extract_text(fields.get("商談名", ""))
    if deal_name:
        return deal_name
    return extract_text(fields.get("新規取引先名", "")) or "(不明)"


# ── Section 1: 昨日の商談サマリー ──
def build_deal_summary(token):
    """商談テーブルから昨日更新された商談を集計"""
    try:
        deals = lark_get_all_records(token, TABLE_DEALS)
        now = datetime.now()
        yesterday_start = datetime(now.year, now.month, now.day) - timedelta(days=1)
        yesterday_end = yesterday_start + timedelta(days=1)
        yesterday_start_ms = int(yesterday_start.timestamp() * 1000)
        yesterday_end_ms = int(yesterday_end.timestamp() * 1000)

        new_deals = []
        updated_deals = []
        stage_changes = []
        rep_counts = {}
        hot_warm_count = 0

        for rec in deals:
            f = rec.get("fields", {})
            # Check record timestamps
            created_ts = rec.get("created_time")
            updated_ts = rec.get("last_modified_time")

            is_new = False
            is_updated = False

            if created_ts and yesterday_start_ms <= created_ts < yesterday_end_ms:
                is_new = True
            elif updated_ts and yesterday_start_ms <= updated_ts < yesterday_end_ms:
                is_updated = True

            if not is_new and not is_updated:
                continue

            company = resolve_company_name(f)
            stage = extract_text(f.get("商談ステージ", ""))
            temp = extract_text(f.get("温度感スコア", ""))
            rep = extract_rep_name(f.get("担当営業", []))

            if rep:
                rep_short = rep.replace("ユーザー550372", "政木")
                if "新美" in rep:
                    rep_short = "新美"
                elif "政木" in rep or "550372" in rep:
                    rep_short = "政木"
                rep_counts[rep_short] = rep_counts.get(rep_short, 0) + 1

            if temp in ("Hot", "Warm"):
                hot_warm_count += 1

            info = {"company": company, "stage": stage, "temp": temp, "rep": rep}
            if is_new:
                new_deals.append(info)
            else:
                updated_deals.append(info)
                if stage:
                    stage_changes.append(info)

        total = len(new_deals) + len(updated_deals)
        lines = [f"■ 昨日の商談 ({total}件更新)"]

        if total == 0:
            lines.append("  更新なし")
            return "\n".join(lines)

        rep_str = " / ".join(f"{k}: {v}件" for k, v in sorted(rep_counts.items()))
        lines.append(f"  新規: {len(new_deals)}件 / 更新: {len(updated_deals)}件")
        if rep_str:
            lines.append(f"  {rep_str}")
        lines.append(f"  Hot/Warm: {hot_warm_count}件")

        # Stage change details (max 5)
        for d in (new_deals + stage_changes)[:5]:
            rep_tag = f" ({d['rep'][:2]})" if d.get("rep") else ""
            temp_tag = f" [{d['temp']}]" if d.get("temp") else ""
            lines.append(f"  {d['company']} -> {d['stage']}{temp_tag}{rep_tag}")

        return "\n".join(lines)

    except Exception as e:
        return f"■ 昨日の商談\n  [取得失敗: {e}]"


# ── Section 2: 今日の予定タスク ──
def build_task_overview(token):
    """タスク管理Baseから今日期限・期限超過タスクを取得"""
    try:
        records = lark_get_all_records(token, TASK_TABLE_ID, base_token=TASK_BASE_TOKEN)
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        today_start = datetime(now.year, now.month, now.day)
        today_end = today_start + timedelta(days=1)

        due_today = []
        overdue = []

        for rec in records:
            f = rec.get("fields", {})
            # Skip completed tasks
            status = extract_text(f.get("ステータス", ""))
            if status in ("完了", "Done", "done"):
                continue

            # Check deadline
            deadline = f.get("期限")
            if not deadline:
                continue

            # Deadline can be timestamp (ms) or date string
            if isinstance(deadline, (int, float)):
                dl_dt = datetime.fromtimestamp(deadline / 1000)
            elif isinstance(deadline, str):
                try:
                    dl_dt = datetime.strptime(deadline[:10], "%Y-%m-%d")
                except ValueError:
                    continue
            else:
                continue

            task_name = extract_text(f.get("Text", "")) or extract_text(f.get("タスク名", "")) or "(無題)"
            dl_str = dl_dt.strftime("%m/%d")

            if dl_dt < today_start:
                overdue.append({"name": task_name, "deadline": dl_str})
            elif dl_dt < today_end:
                due_today.append({"name": task_name, "deadline": dl_str})

        total = len(due_today) + len(overdue)
        lines = [f"■ 今日のタスク ({total}件)"]

        if total == 0:
            lines.append("  期限タスクなし")
            return "\n".join(lines)

        if overdue:
            lines.append(f"  !! 期限超過: {len(overdue)}件")
            for t in overdue[:5]:
                lines.append(f"  [ ] {t['name']} (期限: {t['deadline']}) <- 超過")

        for t in due_today[:5]:
            lines.append(f"  [ ] {t['name']} (期限: 今日)")

        if total > 10:
            lines.append(f"  ...他 {total - 10}件")

        return "\n".join(lines)

    except Exception as e:
        return f"■ 今日のタスク\n  [取得失敗: {e}]"


# ── Section 3: CRMアラート要約 ──
def build_crm_alerts(token):
    """期限超過アクション・停滞商談をチェック"""
    try:
        deals = lark_get_all_records(token, TABLE_DEALS)
        now = datetime.now()
        now_ms = int(now.timestamp() * 1000)
        stagnant_threshold = timedelta(days=14)

        overdue_actions = []
        stagnant_deals = []
        data_quality = []

        for rec in deals:
            f = rec.get("fields", {})
            stage = extract_text(f.get("商談ステージ", ""))

            # Skip closed deals
            if stage in ("受注", "失注", ""):
                continue

            company = resolve_company_name(f)
            temp = extract_text(f.get("温度感スコア", ""))
            rep = extract_rep_name(f.get("担当営業", []))

            # 1. Overdue next actions
            next_date = f.get("次アクション日")
            if isinstance(next_date, (int, float)):
                if next_date < now_ms:
                    days_over = (now_ms - next_date) // (86400 * 1000)
                    overdue_actions.append({
                        "company": company,
                        "days": days_over,
                        "temp": temp,
                    })

            # 2. Stagnant deals (no update in 14+ days)
            updated_ts = rec.get("last_modified_time")
            if updated_ts:
                last_update = datetime.fromtimestamp(updated_ts / 1000)
                if now - last_update > stagnant_threshold:
                    stagnant_deals.append({
                        "company": company,
                        "days": (now - last_update).days,
                        "stage": stage,
                    })

            # 3. Data quality: Hot/Warm without rep
            if temp in ("Hot", "Warm") and not rep:
                data_quality.append({"company": company, "temp": temp, "issue": "担当未設定"})

        # Sort by severity
        overdue_actions.sort(key=lambda x: -x["days"])
        stagnant_deals.sort(key=lambda x: -x["days"])

        # Separate Hot/Warm (actionable) from Cold/None (bulk stale)
        hot_warm_overdue = [a for a in overdue_actions if a["temp"] in ("Hot", "Warm")]
        cold_overdue = [a for a in overdue_actions if a["temp"] not in ("Hot", "Warm")]

        actionable = len(hot_warm_overdue) + len(data_quality)
        lines = [f"■ CRMアラート (要対応: {actionable}件 / 全体: {len(overdue_actions) + len(stagnant_deals) + len(data_quality)}件)"]

        if actionable == 0 and not overdue_actions and not stagnant_deals:
            lines.append("  アラートなし")
            return "\n".join(lines)

        # Show Hot/Warm overdue first (these are actionable)
        if hot_warm_overdue:
            lines.append(f"  [!!] Hot/Warm期限超過: {len(hot_warm_overdue)}件")
            for a in hot_warm_overdue[:5]:
                lines.append(f"    -> {a['company']} ({a['days']}日超過) [{a['temp']}]")

        # Show cold overdue as summary only (not individually)
        if cold_overdue:
            lines.append(f"  [i] その他期限超過: {len(cold_overdue)}件 (大半がヒアリング/不在ステージ)")

        if stagnant_deals:
            lines.append(f"  [i] 停滞商談(14日+): {len(stagnant_deals)}件")

        if data_quality:
            lines.append(f"  [!] データ品質: {len(data_quality)}件")
            for d in data_quality[:2]:
                lines.append(f"    -> {d['company']} [{d['temp']}] {d['issue']}")

        return "\n".join(lines)

    except Exception as e:
        return f"■ CRMアラート\n  [取得失敗: {e}]"


# ── Section 4: GA4 前日PV ──
def _find_service_account_key():
    """Find Google service account key file."""
    # GitHub Actions path
    tmp_sa = Path("/tmp/google_sa.json")
    if tmp_sa.exists():
        return tmp_sa
    # Local config path
    sa_path = CONFIG.get("google", {}).get("service_account_json", "")
    if sa_path and Path(sa_path).exists():
        return Path(sa_path)
    # Search common locations
    for d in [
        Path("/mnt/c/Users/USER/Documents/_data"),
        Path("/mnt/c/Users/USER/Documents/_data").parent,
    ]:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.suffix == ".json" and ("drive-organizer" in f.name or "489313" in f.name):
                return f
    return None


def _get_google_access_token(key_path):
    """Get OAuth2 access token from service account JSON."""
    key_data = json.loads(Path(key_path).read_text(encoding="utf-8"))
    private_key_pem = key_data["private_key"]
    client_email = key_data.get("client_email", SERVICE_ACCOUNT_EMAIL)

    now_ts = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": client_email,
        "scope": GA4_SCOPES,
        "aud": "https://oauth2.googleapis.com/token",
        "iat": now_ts,
        "exp": now_ts + 3600,
    }

    def b64url(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header_b64 = b64url(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}".encode()

    # Try cryptography library
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt_token = f"{header_b64}.{payload_b64}.{b64url(signature)}"
    except ImportError:
        # Fallback: openssl
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as kf:
            kf.write(private_key_pem)
            kf_path = kf.name
        try:
            proc = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", kf_path],
                input=signing_input, capture_output=True
            )
            if proc.returncode != 0:
                raise RuntimeError(f"openssl failed: {proc.stderr.decode()}")
            signature = proc.stdout
            jwt_token = f"{header_b64}.{payload_b64}.{b64url(signature)}"
        finally:
            os.unlink(kf_path)

    # Exchange JWT for access token
    # Note: urlencode percent-encodes colons in grant_type, which Google rejects.
    # Construct body manually with pre-encoded grant_type.
    token_data = (
        "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer"
        f"&assertion={jwt_token}"
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    return result["access_token"]


def _ga4_run_report(google_token, body):
    """Execute GA4 runReport API call."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(GA4_API, data=data, headers={
        "Authorization": f"Bearer {google_token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        print(f"  GA4 API Error {e.code}: {error_body[:300]}")
        return None


def build_ga4_summary():
    """GA4 Data APIで前日PVを取得"""
    try:
        key_path = _find_service_account_key()
        if not key_path:
            return "■ GA4 昨日のアクセス\n  [SA鍵ファイル未発見]"

        google_token = _get_google_access_token(key_path)

        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        last_week_same_day = (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d")

        # Summary report (yesterday)
        summary_result = _ga4_run_report(google_token, {
            "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
            "metrics": [
                {"name": "screenPageViews"},
                {"name": "totalUsers"},
                {"name": "sessions"},
            ],
        })

        # Last week same day for comparison
        prev_result = _ga4_run_report(google_token, {
            "dateRanges": [{"startDate": last_week_same_day, "endDate": last_week_same_day}],
            "metrics": [
                {"name": "screenPageViews"},
                {"name": "totalUsers"},
                {"name": "sessions"},
            ],
        })

        # Top 5 pages (yesterday)
        pages_result = _ga4_run_report(google_token, {
            "dateRanges": [{"startDate": yesterday, "endDate": yesterday}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
            "limit": 5,
        })

        # Parse summary
        pv = users = sessions = 0
        if summary_result and "rows" in summary_result:
            row = summary_result["rows"][0]
            vals = [v.get("value", "0") for v in row.get("metricValues", [])]
            pv = int(vals[0]) if len(vals) > 0 else 0
            users = int(vals[1]) if len(vals) > 1 else 0
            sessions = int(vals[2]) if len(vals) > 2 else 0

        # Parse prev week for comparison
        prev_pv = 0
        if prev_result and "rows" in prev_result:
            prev_row = prev_result["rows"][0]
            prev_vals = [v.get("value", "0") for v in prev_row.get("metricValues", [])]
            prev_pv = int(prev_vals[0]) if prev_vals else 0

        pv_change = ""
        if prev_pv > 0:
            pct = ((pv - prev_pv) / prev_pv) * 100
            sign = "+" if pct >= 0 else ""
            pv_change = f" ({sign}{pct:.0f}% vs 先週同曜日)"

        lines = ["■ GA4 昨日のアクセス"]
        lines.append(f"  PV: {pv:,}{pv_change}")
        lines.append(f"  ユーザー: {users:,} / セッション: {sessions:,}")

        # Parse top pages
        if pages_result and "rows" in pages_result:
            lines.append("  ---")
            for row in pages_result["rows"][:5]:
                path = row["dimensionValues"][0]["value"]
                page_pv = int(row["metricValues"][0]["value"])
                # Shorten long paths
                if len(path) > 40:
                    path = path[:37] + "..."
                lines.append(f"  {path} ({page_pv})")

        # Save state for future comparisons
        _save_pv_state(yesterday, pv, users, sessions)

        return "\n".join(lines)

    except Exception as e:
        return f"■ GA4 昨日のアクセス\n  [取得失敗: {e}]"


def _save_pv_state(date_str, pv, users, sessions):
    """Save daily PV data for week-over-week comparison."""
    try:
        state = {}
        if STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        daily = state.get("daily_pv", {})
        daily[date_str] = {"pv": pv, "users": users, "sessions": sessions}
        # Keep only last 14 days
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        daily = {k: v for k, v in daily.items() if k >= cutoff}
        state["daily_pv"] = daily
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Section 5: 入札情報新着 ──
def build_bid_news():
    """bid_scanner.pyのロジックを簡易呼び出しして新着入札を取得"""
    try:
        # Try importing bid_scanner functions
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from bid_scanner import scan_ebisc, scan_cbr_static, deduplicate, load_seen_bids, filter_new_bids
            bids = []
            try:
                bids.extend(scan_ebisc(days=2))
            except Exception as e:
                print(f"  [bid] e-bisc error: {e}")
            try:
                bids.extend(scan_cbr_static())
            except Exception as e:
                print(f"  [bid] cbr error: {e}")

            bids = deduplicate(bids)
            seen = load_seen_bids()
            new_bids = filter_new_bids(bids, seen)
            # Don't save seen state in dry-run
            if not DRY_RUN:
                from bid_scanner import save_seen_bids
                save_seen_bids(seen)

        except ImportError:
            # Fallback: run bid_scanner as subprocess
            import subprocess
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "bid_scanner.py"), "--test", "--days", "2"],
                capture_output=True, text=True, timeout=120
            )
            # Parse output for bid count
            output = result.stdout
            if "該当する新規案件はありません" in output:
                new_bids = []
            else:
                new_bids = [{"案件名": "bid_scanner出力参照", "発注者": ""}]

        lines = [f"■ 入札情報 ({len(new_bids)}件)"]

        if not new_bids:
            lines.append("  新着なし")
            return "\n".join(lines)

        for bid in new_bids[:5]:
            title = bid.get("案件名", "")[:50]
            agency = bid.get("発注者", "")
            deadline = bid.get("締切日", "")
            deadline_str = f" (締切: {deadline})" if deadline else ""
            lines.append(f"  >> {title}{deadline_str}")
            if agency:
                lines.append(f"     {agency}")

        if len(new_bids) > 5:
            lines.append(f"  ...他 {len(new_bids) - 5}件")

        return "\n".join(lines)

    except Exception as e:
        return f"■ 入札情報\n  [取得失敗: {e}]"


# ── Section 6: freee未請求サマリー ──
def build_freee_unbilled_summary():
    """freee_invoice_creator.pyのロジックで未請求案件数を表示"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from freee_invoice_creator import (
                load_config as freee_load_config,
                lark_get_token as freee_lark_token,
                lark_list_records as freee_lark_list,
                find_invoice_candidates,
                format_yen,
                ORDER_TABLE_ID,
            )
            config = freee_load_config()
            token = freee_lark_token(config)
            records = freee_lark_list(token, ORDER_TABLE_ID)
            candidates = find_invoice_candidates(records)

            lines = [f"■ freee未請求 ({len(candidates)}件)"]
            if not candidates:
                lines.append("  未請求案件なし")
                return "\n".join(lines)

            total = sum(c["amount"] for c in candidates)
            matched = sum(1 for c in candidates if c["partner_id"])
            unmatched = len(candidates) - matched
            lines.append(f"  合計: {format_yen(total)}円")
            lines.append(f"  取引先マッチ済: {matched}件 / 未マッチ: {unmatched}件")
            for c in candidates[:3]:
                status = "OK" if c["partner_id"] else "!未マッチ"
                lines.append(f"  {c['company'][:15]} / {format_yen(c['amount'])}円 [{status}]")
            if len(candidates) > 3:
                lines.append(f"  ...他 {len(candidates) - 3}件")
            return "\n".join(lines)

        except ImportError as e:
            # Fallback: subprocess
            import subprocess
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "freee_invoice_creator.py"), "--check-only"],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout
            if "請求書作成対象の案件はありません" in output:
                return "■ freee未請求 (0件)\n  未請求案件なし"
            # Parse candidate count from output
            for line in output.split("\n"):
                if "候補:" in line:
                    return f"■ freee未請求\n  {line.strip()}"
            return f"■ freee未請求\n  {output[-200:]}"

    except Exception as e:
        return f"■ freee未請求\n  [取得失敗: {e}]"


# ── Section 7: freee未入金サマリー ──
def build_freee_unpaid_summary():
    """freee_payment_checker.pyのロジックで未入金・期限超過を表示"""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from freee_payment_checker import (
                load_config as pay_load_config,
                get_all_freee_invoices,
                format_yen,
            )
            from datetime import date as _date
            config = pay_load_config()
            all_invoices, config = get_all_freee_invoices(config)
            unsettled = [inv for inv in all_invoices if inv.get("payment_status") != "settled"]

            today = _date.today()
            overdue = []
            for inv in unsettled:
                pd_str = inv.get("payment_date", "")
                if pd_str:
                    try:
                        pd = _date.fromisoformat(pd_str)
                        if pd < today:
                            overdue.append(inv)
                    except (ValueError, TypeError):
                        pass

            lines = [f"■ freee未入金 ({len(unsettled)}件)"]
            if not unsettled:
                lines.append("  未入金なし")
                return "\n".join(lines)

            total = sum(inv.get("total_amount", 0) for inv in unsettled)
            lines.append(f"  未入金合計: {format_yen(total)}円")

            if overdue:
                overdue_total = sum(inv.get("total_amount", 0) for inv in overdue)
                lines.append(f"  [!!] 期限超過: {len(overdue)}件 ({format_yen(overdue_total)}円)")
                for inv in overdue[:3]:
                    lines.append(
                        f"    {inv.get('partner_name', '')[:15]} / "
                        f"{format_yen(inv.get('total_amount', 0))}円 / "
                        f"期限: {inv.get('payment_date', '')}"
                    )
                if len(overdue) > 3:
                    lines.append(f"    ...他 {len(overdue) - 3}件")
            else:
                lines.append("  期限超過なし")

            return "\n".join(lines)

        except ImportError:
            import subprocess
            result = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "freee_payment_checker.py"), "--check-only"],
                capture_output=True, text=True, timeout=120,
            )
            output = result.stdout
            lines = ["■ freee未入金"]
            for line in output.split("\n"):
                if "未入金:" in line or "支払期限超過:" in line:
                    lines.append(f"  {line.strip()}")
            if len(lines) == 1:
                lines.append("  (詳細取得不可)")
            return "\n".join(lines)

    except Exception as e:
        return f"■ freee未入金\n  [取得失敗: {e}]"


# ── Report formatter ──
def format_report(sections):
    now = datetime.now()
    weekday = WEEKDAY_JA[now.weekday()]
    header = (
        f"{'='*30}\n"
        f"日次モーニングレポート\n"
        f"{now.strftime('%Y/%m/%d')} ({weekday}) {now.strftime('%H:%M')}\n"
        f"{'='*30}"
    )
    footer = (
        f"{'='*30}\n"
        f"東海エアサービス 自動レポート"
    )
    body = "\n\n".join(sections)
    return f"{header}\n\n{body}\n\n{footer}"


# ── Main ──
def main():
    global DRY_RUN
    DRY_RUN = "--dry-run" in sys.argv

    now = datetime.now()
    print(f"[{now.strftime('%H:%M:%S')}] 日次モーニングレポート生成")
    print(f"  モード: {'ドライラン' if DRY_RUN else '本番'}")
    print()

    # Get Lark token
    print("  Lark認証中...")
    lark_token = lark_get_token()

    # Build each section independently
    sections = []

    print("  [1/7] 商談サマリー取得中...")
    sections.append(build_deal_summary(lark_token))

    print("  [2/7] タスク概要取得中...")
    sections.append(build_task_overview(lark_token))

    print("  [3/7] CRMアラート取得中...")
    sections.append(build_crm_alerts(lark_token))

    print("  [4/7] GA4データ取得中...")
    sections.append(build_ga4_summary())

    print("  [5/7] 入札情報取得中...")
    sections.append(build_bid_news())

    print("  [6/7] freee未請求チェック中...")
    sections.append(build_freee_unbilled_summary())

    print("  [7/7] freee未入金チェック中...")
    sections.append(build_freee_unpaid_summary())

    # Format final report
    report = format_report(sections)
    print()
    print("--- レポート内容 ---")
    print(report)
    print("--- ここまで ---")
    print()

    # Lark message limit: ~4096 chars. Split if needed.
    if len(report) > 3800:
        chunks = []
        current = ""
        for line in report.split("\n"):
            if len(current) + len(line) + 1 > 3800:
                chunks.append(current)
                current = line
            else:
                current += "\n" + line if current else line
        if current:
            chunks.append(current)
        print(f"  メッセージ分割: {len(chunks)}通")
        for i, chunk in enumerate(chunks):
            print(f"  [{i+1}/{len(chunks)}] 送信中...")
            lark_send_bot_message(lark_token, CEO_OPEN_ID, chunk)
            if i < len(chunks) - 1:
                time.sleep(1)
    else:
        lark_send_bot_message(lark_token, CEO_OPEN_ID, report)

    # Save log
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n[{now.isoformat()}] Report generated (dry_run={DRY_RUN}, len={len(report)})\n")

    print(f"\n[完了] {datetime.now().strftime('%H:%M:%S')}")


if __name__ == "__main__":
    main()
