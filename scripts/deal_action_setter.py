#!/usr/bin/env python3
"""
Hot/Warm商談特定 & 次アクション自動設定スクリプト
集客構造改善P1-03: 即時売上機会の掘り起こし

Usage:
  python3 deal_action_setter.py --dry-run    # プレビューのみ（デフォルト）
  python3 deal_action_setter.py --execute    # 本番実行（レコード更新）
  python3 deal_action_setter.py --report     # レポート生成のみ
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
REPORT_DIR = SCRIPT_DIR.parent / "docs"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")


# ── Lark API ──

def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def fetch_all_records(token, table_id):
    records = []
    page_token = None
    page = 0
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
        if result.get("code") != 0:
            print(f"API Error: {result}", file=sys.stderr)
            break
        data = result.get("data", {})
        items = data.get("items", [])
        records.extend(items)
        page += 1
        print(f"  Page {page}: {len(items)} records (total: {len(records)})", file=sys.stderr)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        time.sleep(0.3)
    return records


def update_record(token, table_id, record_id, fields):
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            if resp.get("code") != 0:
                print(f"  Update error: {resp.get('msg', 'unknown')} (record: {record_id})", file=sys.stderr)
                return False
            return True
    except urllib.error.HTTPError as e:
        print(f"  HTTP error: {e.code} (record: {record_id})", file=sys.stderr)
        return False


# ── Field Helpers ──

def safe_get(fields, key, default=""):
    val = fields.get(key)
    if val is None:
        return default
    if isinstance(val, list):
        if len(val) == 0:
            return default
        if isinstance(val[0], dict):
            return val[0].get("text", val[0].get("name", str(val[0])))
        return str(val[0])
    if isinstance(val, dict):
        return val.get("text", val.get("name", str(val)))
    return str(val)


def ts_to_date(ms_val):
    if not ms_val:
        return None
    try:
        ts = int(ms_val) / 1000
        return datetime.fromtimestamp(ts)
    except Exception:
        return None


def parse_date_field(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return ts_to_date(val)
    if isinstance(val, str):
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                pass
        return ts_to_date(val)
    return None


def next_business_day(base_date, days_ahead):
    """base_dateからdays_ahead営業日後の日付を返す"""
    d = base_date
    count = 0
    while count < days_ahead:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 月-金
            count += 1
    return d


# ── Deal Classification ──

def classify_deals(records):
    """全商談をHot/Warm/Cold/Closed/Unknownに分類"""
    deals = []
    for r in records:
        f = r.get("fields", {})
        record_id = r.get("record_id", "")

        # 基本情報（商談名がなければ対象物件名や商談IDで代替）
        name = safe_get(f, "商談名") or safe_get(f, "対象物件・現場名") or safe_get(f, "商談ID") or ""
        stage = safe_get(f, "商談ステージ")
        temp = safe_get(f, "温度感スコア")
        rep = safe_get(f, "担当営業")
        next_action = safe_get(f, "次アクション")
        next_action_date = safe_get(f, "次アクション日")
        result = safe_get(f, "結果")
        hearing = safe_get(f, "ヒアリング内容（まとめ）")
        category = safe_get(f, "客先カテゴリ")
        deal_form = safe_get(f, "商談形態")
        new_existing = safe_get(f, "新規・既存客の別")
        competition = safe_get(f, "競合有無")
        memo = safe_get(f, "商談内での気づき・備考")
        absent_action = safe_get(f, "不在時の対応")

        # 金額
        amt_str = safe_get(f, "見積・予算金額") or safe_get(f, "確定金額") or safe_get(f, "売上計上額")
        try:
            amount = float(amt_str) if amt_str else 0
        except (ValueError, TypeError):
            amount = 0

        # 日付
        deal_date = parse_date_field(safe_get(f, "商談日"))
        created = ts_to_date(r.get("created_time"))
        updated = ts_to_date(r.get("last_modified_time"))

        # 最終活動日（最も新しい日付）
        dates = [d for d in [updated, deal_date, created] if d]
        last_activity = max(dates) if dates else None
        days_since = (NOW - last_activity).days if last_activity else 9999

        deals.append({
            "record_id": record_id,
            "name": name,
            "stage": stage,
            "temp": temp,
            "rep": rep,
            "next_action": next_action,
            "next_action_date": next_action_date,
            "result": result,
            "hearing": hearing,
            "category": category,
            "deal_form": deal_form,
            "new_existing": new_existing,
            "competition": competition,
            "memo": memo,
            "absent_action": absent_action,
            "amount": amount,
            "deal_date": deal_date,
            "created": created,
            "updated": updated,
            "last_activity": last_activity,
            "days_since": days_since,
            "raw_fields": f,
        })

    return deals


def is_closed(deal):
    """受注/失注/クローズ済みか判定"""
    result = (deal["result"] or "").strip()
    stage = (deal["stage"] or "").strip()

    closed_results = ["受注", "失注", "受注済", "失注済", "キャンセル", "辞退", "見送り"]
    closed_stages = ["受注", "失注", "クローズ", "完了", "納品完了"]

    if any(r in result for r in closed_results):
        return True
    if any(s in stage for s in closed_stages):
        return True
    return False


def classify_temperature(deal):
    """
    Hot/Warm/Cold分類ロジック:
    Hot: 温度感Hot or 30日以内更新 or 見積提出済み
    Warm: 温度感Warm or 60日以内に接点
    Cold: それ以外
    """
    if is_closed(deal):
        return "Closed"

    temp = (deal["temp"] or "").lower().strip()
    stage = (deal["stage"] or "").strip()
    days = deal["days_since"]

    # Hot判定
    hot_temps = ["hot", "ホット", "a", "高"]
    if any(t in temp for t in hot_temps):
        return "Hot"
    if stage in ["見積提出", "提案", "見積依頼"]:
        return "Hot"
    if days <= 30 and stage not in ["", "(未設定)", "不在"]:
        return "Hot"

    # Warm判定
    warm_temps = ["warm", "ウォーム", "b", "中"]
    if any(t in temp for t in warm_temps):
        return "Warm"
    if days <= 60:
        return "Warm"
    if stage in ["ヒアリング", "商談", "初回接触", "フォロー中", "不在"]:
        if days <= 90:
            return "Warm"

    # Cold
    return "Cold"


def estimate_stage(deal):
    """ステージ未設定の商談に対し、利用可能な情報から推定"""
    stage = (deal["stage"] or "").strip()
    if stage and stage != "(未設定)":
        return stage  # 既にステージ設定済み

    hearing = deal["hearing"] or ""
    memo = deal["memo"] or ""
    deal_form = deal["deal_form"] or ""
    result = deal["result"] or ""
    absent = deal["absent_action"] or ""
    amount = deal["amount"]
    days = deal["days_since"]

    # 結果があればクローズ系
    if "受注" in result:
        return "受注"
    if "失注" in result or "見送り" in result:
        return "失注"

    # 見積金額があれば見積提出
    if amount > 0:
        return "見積提出"

    # ヒアリング内容があればヒアリング済み
    if len(hearing) > 10:
        return "ヒアリング"

    # 不在だった場合
    if absent and ("不在" in absent or "留守" in absent):
        return "初回接触"

    # 商談形態から推定
    if "飛び込み" in deal_form or "テレアポ" in deal_form or "新規" in deal_form:
        return "初回接触"
    if "紹介" in deal_form or "問合せ" in deal_form or "Web" in deal_form:
        return "ヒアリング"

    # 長期放置は凍結候補
    if days > 180:
        return "凍結"

    return "初回接触"  # デフォルト


def determine_next_action(deal, classification):
    """商談の状態に応じた次アクションと日付を決定"""
    stage = deal["stage"] or estimate_stage(deal)
    days = deal["days_since"]
    existing_action = (deal["next_action"] or "").strip()
    existing_date = (deal["next_action_date"] or "").strip()

    # 既に次アクションが設定済みの場合はスキップ
    skip_actions = ["", "(未設定)", "なし", "無し", "未定", "営業見込みなし", "None"]
    if existing_action and existing_action not in skip_actions:
        return None, None, "skip_existing"

    # クローズ済みはスキップ
    if classification == "Closed":
        return None, None, "skip_closed"

    # Coldはスキップ（対象外）
    if classification == "Cold":
        return None, None, "skip_cold"

    # ── アクション決定 ──
    action = ""
    action_date = NOW
    reason = ""

    if stage == "見積提出":
        action = "フォロー電話"
        action_date = next_business_day(NOW, 3)
        reason = "見積提出済み→3営業日後フォロー"

    elif stage in ["提案", "見積依頼"]:
        action = "見積作成・提出"
        action_date = next_business_day(NOW, 2)
        reason = "提案/見積依頼→2営業日後に見積提出"

    elif stage == "ヒアリング":
        if days <= 14:
            action = "提案資料作成"
            action_date = next_business_day(NOW, 3)
            reason = "ヒアリング済み（新鮮）→提案資料準備"
        else:
            action = "状況確認電話"
            action_date = next_business_day(NOW, 1)
            reason = "ヒアリング後停滞→状況確認"

    elif stage == "初回接触":
        if days <= 7:
            action = "ヒアリング電話"
            action_date = next_business_day(NOW, 1)
            reason = "初回接触直後→翌営業日ヒアリング"
        elif days <= 30:
            action = "フォロー電話"
            action_date = next_business_day(NOW, 1)
            reason = "初回接触後経過→フォロー"
        else:
            action = "状況確認メール"
            action_date = NOW
            reason = "初回接触後長期→即日メール確認"

    elif stage == "フォロー中":
        action = "状況確認電話"
        action_date = next_business_day(NOW, 1)
        reason = "フォロー中→翌営業日電話"

    elif stage == "凍結":
        action = "掘り起こしメール"
        action_date = next_business_day(NOW, 5)
        reason = "長期凍結→掘り起こし"

    else:
        # ステージ未設定 or その他
        if days <= 30:
            action = "状況確認電話"
            action_date = next_business_day(NOW, 1)
            reason = "ステージ不明（新しい）→状況確認"
        elif days <= 90:
            action = "状況確認メール"
            action_date = NOW
            reason = "ステージ不明（停滞気味）→メール確認"
        else:
            action = "掘り起こしメール"
            action_date = next_business_day(NOW, 5)
            reason = "長期停滞→掘り起こし"

    return action, action_date, reason


# ── Main ──

def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args or not any(a in args for a in ["--execute", "--report"])
    execute = "--execute" in args
    report_only = "--report" in args

    mode = "EXECUTE" if execute else "REPORT" if report_only else "DRY-RUN"
    print(f"=== Hot/Warm商談特定 & 次アクション設定 [{mode}] ===")
    print(f"日時: {NOW.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. トークン取得
    print("1. Larkトークン取得...", file=sys.stderr)
    token = get_token()

    # 2. 商談データ取得
    print("2. 商談レコード取得...", file=sys.stderr)
    records = fetch_all_records(token, TABLE_DEALS)
    print(f"   取得完了: {len(records)}件", file=sys.stderr)

    # 3. 分類
    print("3. 商談分類中...", file=sys.stderr)
    deals = classify_deals(records)

    # Hot/Warm/Cold/Closed分類
    classified = {"Hot": [], "Warm": [], "Cold": [], "Closed": []}
    for d in deals:
        cls = classify_temperature(d)
        d["classification"] = cls
        classified[cls].append(d)

    print(f"   Hot: {len(classified['Hot'])}件 / Warm: {len(classified['Warm'])}件 / Cold: {len(classified['Cold'])}件 / Closed: {len(classified['Closed'])}件", file=sys.stderr)

    # 4. ステージ推定 & 次アクション決定
    print("4. 次アクション決定中...", file=sys.stderr)

    # 対象: Hot + Warm
    targets = classified["Hot"] + classified["Warm"]
    actions_to_set = []
    stage_to_set = []
    skipped = {"skip_existing": 0, "skip_closed": 0, "skip_cold": 0}

    for d in targets:
        # ステージ未設定の場合は推定
        original_stage = d["stage"]
        estimated = False
        if not original_stage or original_stage in ["", "(未設定)"]:
            estimated_stage = estimate_stage(d)
            d["estimated_stage"] = estimated_stage
            estimated = True
            stage_to_set.append(d)
        else:
            d["estimated_stage"] = original_stage

        # 次アクション決定
        action, action_date, reason = determine_next_action(d, d["classification"])
        d["new_action"] = action
        d["new_action_date"] = action_date
        d["action_reason"] = reason

        if action:
            actions_to_set.append(d)
        else:
            skipped[reason] = skipped.get(reason, 0) + 1

    # ── 結果表示 ──
    print(f"\n{'='*70}")
    print(f"分類結果サマリー")
    print(f"{'='*70}")
    print(f"  総商談数:     {len(deals)}件")
    print(f"  Hot:          {len(classified['Hot'])}件")
    print(f"  Warm:         {len(classified['Warm'])}件")
    print(f"  Cold:         {len(classified['Cold'])}件")
    print(f"  Closed:       {len(classified['Closed'])}件")
    print(f"  ステージ推定: {len(stage_to_set)}件")
    print(f"  アクション設定対象: {len(actions_to_set)}件")
    print(f"  スキップ（既存アクションあり）: {skipped.get('skip_existing', 0)}件")
    print()

    # Hot商談一覧
    print(f"\n{'='*70}")
    print(f"Hot商談一覧 ({len(classified['Hot'])}件)")
    print(f"{'='*70}")
    for d in sorted(classified["Hot"], key=lambda x: x["days_since"]):
        stage_display = d["estimated_stage"] if d.get("estimated_stage") else d["stage"]
        stage_mark = " [推定]" if d.get("estimated_stage") and (not d["stage"] or d["stage"] == "(未設定)") else ""
        action_display = d.get("new_action") or "-"
        action_date_display = d["new_action_date"].strftime("%Y-%m-%d") if d.get("new_action_date") else "-"
        deal_name = d["name"][:35] if d["name"] else "(名前なし)"
        days_display = f"{d['days_since']}日前" if d["days_since"] < 9999 else "不明"
        print(f"  {deal_name:35s} | {d['rep'][:10]:10s} | {stage_display}{stage_mark} | {days_display:>8s} | {action_display} ({action_date_display})")

    # Warm商談一覧
    print(f"\n{'='*70}")
    print(f"Warm商談一覧 ({len(classified['Warm'])}件)")
    print(f"{'='*70}")
    for d in sorted(classified["Warm"], key=lambda x: x["days_since"]):
        stage_display = d["estimated_stage"] if d.get("estimated_stage") else d["stage"]
        stage_mark = " [推定]" if d.get("estimated_stage") and (not d["stage"] or d["stage"] == "(未設定)") else ""
        action_display = d.get("new_action") or "-"
        action_date_display = d["new_action_date"].strftime("%Y-%m-%d") if d.get("new_action_date") else "-"
        deal_name = d["name"][:35] if d["name"] else "(名前なし)"
        days_display = f"{d['days_since']}日前" if d["days_since"] < 9999 else "不明"
        print(f"  {deal_name:35s} | {d['rep'][:10]:10s} | {stage_display}{stage_mark} | {days_display:>8s} | {action_display} ({action_date_display})")

    # アクション設定詳細
    print(f"\n{'='*70}")
    print(f"次アクション設定対象 ({len(actions_to_set)}件)")
    print(f"{'='*70}")
    for d in actions_to_set:
        action_date_str = d["new_action_date"].strftime("%Y-%m-%d") if d["new_action_date"] else "-"
        print(f"  [{d['classification']}] {d['name'][:30]}")
        print(f"    担当: {d['rep']} | ステージ: {d['estimated_stage']} | 経過: {d['days_since']}日")
        print(f"    次アクション: {d['new_action']} / 日付: {action_date_str}")
        print(f"    理由: {d['action_reason']}")
        print()

    # 5. レポート生成
    report = generate_report(deals, classified, actions_to_set, stage_to_set, skipped)
    report_path = REPORT_DIR / "hot_warm_deals_report.md"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nレポート保存: {report_path}", file=sys.stderr)

    if report_only:
        print("\n[REPORT] レポート生成完了。レコード更新は行いません。")
        return

    # 6. レコード更新
    if execute:
        print(f"\n{'='*70}")
        print(f"レコード更新実行中...")
        print(f"{'='*70}")

        success = 0
        fail = 0

        for d in actions_to_set:
            fields_to_update = {}

            # 次アクション
            if d["new_action"]:
                fields_to_update["次アクション"] = [d["new_action"]]
            if d["new_action_date"]:
                # Lark Baseの日付フィールドはミリ秒タイムスタンプ
                fields_to_update["次アクション日"] = int(d["new_action_date"].timestamp() * 1000)

            # ステージ推定結果の反映
            if d.get("estimated_stage") and (not d["stage"] or d["stage"] in ["", "(未設定)"]):
                fields_to_update["商談ステージ"] = d["estimated_stage"]

            if fields_to_update:
                print(f"  更新: {d['name'][:30]} -> {fields_to_update}")
                ok = update_record(token, TABLE_DEALS, d["record_id"], fields_to_update)
                if ok:
                    success += 1
                else:
                    fail += 1
                time.sleep(0.3)  # Rate limit

        print(f"\n更新完了: 成功 {success}件 / 失敗 {fail}件")

    else:
        print(f"\n[DRY-RUN] レコード更新はスキップしました。")
        print(f"  本番実行: python3 deal_action_setter.py --execute")
        print()

        # Dry-run: 更新予定内容を表示
        print(f"更新予定:")
        for d in actions_to_set:
            fields_preview = {}
            if d["new_action"]:
                fields_preview["次アクション"] = d["new_action"]
            if d["new_action_date"]:
                fields_preview["次アクション日"] = d["new_action_date"].strftime("%Y-%m-%d")
            if d.get("estimated_stage") and (not d["stage"] or d["stage"] in ["", "(未設定)"]):
                fields_preview["商談ステージ"] = d["estimated_stage"]
            print(f"  {d['name'][:35]} -> {fields_preview}")


def generate_report(deals, classified, actions_to_set, stage_to_set, skipped):
    """Markdownレポート生成"""
    lines = []
    lines.append(f"# Hot/Warm商談分析レポート")
    lines.append(f"")
    lines.append(f"生成日: {TODAY}")
    lines.append(f"目的: 集客構造改善P1-03 即時売上機会の掘り起こし")
    lines.append(f"")

    # サマリー
    lines.append(f"## サマリー")
    lines.append(f"")
    lines.append(f"| 分類 | 件数 | 割合 |")
    lines.append(f"|------|------|------|")
    total = len(deals)
    for cls in ["Hot", "Warm", "Cold", "Closed"]:
        cnt = len(classified[cls])
        lines.append(f"| {cls} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"| **合計** | **{total}** | 100% |")
    lines.append(f"")

    lines.append(f"- ステージ推定対象: {len(stage_to_set)}件")
    lines.append(f"- 次アクション設定対象: {len(actions_to_set)}件")
    lines.append(f"- スキップ（既存アクションあり）: {skipped.get('skip_existing', 0)}件")
    lines.append(f"")

    # Hot商談
    lines.append(f"## Hot商談 ({len(classified['Hot'])}件)")
    lines.append(f"")
    if classified["Hot"]:
        lines.append(f"| 商談名 | 担当 | ステージ | 経過日数 | 次アクション | 日付 |")
        lines.append(f"|--------|------|----------|----------|-------------|------|")
        for d in sorted(classified["Hot"], key=lambda x: x["days_since"]):
            stage_display = d.get("estimated_stage", d["stage"]) or "(未設定)"
            stage_mark = " *推定*" if d.get("estimated_stage") and (not d["stage"] or d["stage"] == "(未設定)") else ""
            action = d.get("new_action", "-") or "-"
            action_date = d["new_action_date"].strftime("%m/%d") if d.get("new_action_date") else "-"
            name_short = d["name"][:25] if d["name"] else "(名前なし)"
            lines.append(f"| {name_short} | {d['rep'][:6]} | {stage_display}{stage_mark} | {d['days_since']}日 | {action} | {action_date} |")
    lines.append(f"")

    # Warm商談
    lines.append(f"## Warm商談 ({len(classified['Warm'])}件)")
    lines.append(f"")
    if classified["Warm"]:
        lines.append(f"| 商談名 | 担当 | ステージ | 経過日数 | 次アクション | 日付 |")
        lines.append(f"|--------|------|----------|----------|-------------|------|")
        for d in sorted(classified["Warm"], key=lambda x: x["days_since"]):
            stage_display = d.get("estimated_stage", d["stage"]) or "(未設定)"
            stage_mark = " *推定*" if d.get("estimated_stage") and (not d["stage"] or d["stage"] == "(未設定)") else ""
            action = d.get("new_action", "-") or "-"
            action_date = d["new_action_date"].strftime("%m/%d") if d.get("new_action_date") else "-"
            name_short = d["name"][:25] if d["name"] else "(名前なし)"
            lines.append(f"| {name_short} | {d['rep'][:6]} | {stage_display}{stage_mark} | {d['days_since']}日 | {action} | {action_date} |")
    lines.append(f"")

    # 担当者別集計
    lines.append(f"## 担当者別集計")
    lines.append(f"")
    rep_stats = defaultdict(lambda: {"Hot": 0, "Warm": 0, "Cold": 0, "Closed": 0, "actions": 0})
    for d in deals:
        rep = d["rep"] or "(未設定)"
        rep_stats[rep][d["classification"]] += 1
    for d in actions_to_set:
        rep = d["rep"] or "(未設定)"
        rep_stats[rep]["actions"] += 1

    lines.append(f"| 担当 | Hot | Warm | Cold | Closed | アクション設定 |")
    lines.append(f"|------|-----|------|------|--------|--------------|")
    for rep in sorted(rep_stats.keys()):
        s = rep_stats[rep]
        lines.append(f"| {rep} | {s['Hot']} | {s['Warm']} | {s['Cold']} | {s['Closed']} | {s['actions']} |")
    lines.append(f"")

    # アクション種別集計
    lines.append(f"## 設定アクション種別")
    lines.append(f"")
    action_counter = Counter()
    for d in actions_to_set:
        action_counter[d["new_action"]] += 1
    lines.append(f"| アクション | 件数 |")
    lines.append(f"|------------|------|")
    for act, cnt in action_counter.most_common():
        lines.append(f"| {act} | {cnt} |")
    lines.append(f"")

    # ステージ推定結果
    if stage_to_set:
        lines.append(f"## ステージ推定結果 ({len(stage_to_set)}件)")
        lines.append(f"")
        estimated_counter = Counter()
        for d in stage_to_set:
            estimated_counter[d["estimated_stage"]] += 1
        lines.append(f"| 推定ステージ | 件数 |")
        lines.append(f"|-------------|------|")
        for stg, cnt in estimated_counter.most_common():
            lines.append(f"| {stg} | {cnt} |")
        lines.append(f"")

    # 金額上位のHot/Warm案件
    amount_deals = [d for d in classified["Hot"] + classified["Warm"] if d["amount"] > 0]
    if amount_deals:
        lines.append(f"## 金額上位Hot/Warm案件")
        lines.append(f"")
        lines.append(f"| 商談名 | 分類 | 金額 | 担当 | ステージ |")
        lines.append(f"|--------|------|------|------|----------|")
        for d in sorted(amount_deals, key=lambda x: -x["amount"])[:15]:
            amt_display = f"{d['amount']:,.0f}" if d["amount"] >= 10000 else f"{d['amount']:,.0f}"
            lines.append(f"| {d['name'][:25]} | {d['classification']} | {amt_display}円 | {d['rep'][:6]} | {d.get('estimated_stage', d['stage'])} |")
        lines.append(f"")

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*生成: deal_action_setter.py / {NOW.strftime('%Y-%m-%d %H:%M')}*")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
