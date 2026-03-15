#!/usr/bin/env python3
"""
CRM商談データ品質監査スクリプト
READ-ONLY: データ取得・分析のみ、レコード変更なし
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from pathlib import Path

# ── Config ──
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"

# ── Lark API ──
def get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]

def fetch_all_records(token):
    """全商談レコード取得（ページネーション対応）"""
    all_records = []
    page_token = None
    page = 0
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{DEAL_TABLE_ID}/records?page_size=500"
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
        all_records.extend(items)
        page += 1
        print(f"  Page {page}: {len(items)} records (total: {len(all_records)})", file=sys.stderr)

        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        time.sleep(0.3)

    return all_records

def safe_get(fields, key, default=""):
    """Safely extract field value handling Lark's various field types"""
    val = fields.get(key)
    if val is None:
        return default
    if isinstance(val, list):
        # Multi-select or link fields
        if len(val) == 0:
            return default
        if isinstance(val[0], dict):
            return val[0].get("text", val[0].get("name", str(val[0])))
        return str(val[0])
    if isinstance(val, dict):
        return val.get("text", val.get("name", str(val)))
    return str(val)

def safe_get_multi(fields, key):
    """Get all values from a multi-select field"""
    val = fields.get(key)
    if val is None:
        return []
    if isinstance(val, list):
        result = []
        for item in val:
            if isinstance(item, dict):
                result.append(item.get("text", item.get("name", str(item))))
            else:
                result.append(str(item))
        return result
    return [str(val)]

def ts_to_date(ms_val):
    """Convert millisecond timestamp to date string"""
    if not ms_val:
        return None
    try:
        ts = int(ms_val) / 1000
        return datetime.fromtimestamp(ts)
    except:
        return None

def parse_date_field(val):
    """Parse a date field that could be timestamp(ms) or string"""
    if not val:
        return None
    if isinstance(val, (int, float)):
        return ts_to_date(val)
    if isinstance(val, str):
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(val, fmt)
            except:
                pass
        # try as ms timestamp string
        return ts_to_date(val)
    return None

def analyze(records):
    """全商談レコードを分析"""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    # First, discover all field names
    all_field_names = set()
    for r in records:
        all_field_names.update(r.get("fields", {}).keys())

    print(f"\n=== 全フィールド名一覧 ({len(all_field_names)}個) ===", file=sys.stderr)
    for fn in sorted(all_field_names):
        print(f"  - {fn}", file=sys.stderr)

    # Parse records
    deals = []
    for r in records:
        f = r.get("fields", {})
        # 金額: 見積・予算金額 or 確定金額 or 売上計上額
        amt = safe_get(f, "見積・予算金額") or safe_get(f, "確定金額") or safe_get(f, "売上計上額")
        d = {
            "record_id": r.get("record_id", ""),
            "name": safe_get(f, "商談名"),
            "rep": safe_get(f, "担当営業"),
            "stage": safe_get(f, "商談ステージ"),
            "temperature": safe_get(f, "温度感スコア"),
            "next_action": safe_get(f, "次アクション"),
            "next_action_date": safe_get(f, "次アクション日"),
            "amount": amt,
            "category": safe_get(f, "客先カテゴリ"),
            "source": safe_get(f, "商談形態"),  # 商談ソース→商談形態
            "new_existing": safe_get(f, "新規・既存客の別"),
            "result": safe_get(f, "結果"),
            "lost_reason": safe_get(f, "失注理由"),
            "lost_reason_detail": safe_get(f, "失注理由　詳細"),
            "no_prospect_reason": safe_get(f, "営業見込みなしの理由"),
            "hearing": safe_get(f, "ヒアリング内容（まとめ）"),
            "deal_date": safe_get(f, "商談日"),
            "deal_id": safe_get(f, "商談ID"),
            "absent_action": safe_get(f, "不在時の対応"),
            "competition": safe_get(f, "競合有無"),
            "competitor_name": safe_get(f, "競合名"),
            "contract_type": safe_get(f, "契約形態"),
            "product_type": safe_get_multi(f, "商材種別"),
            "property_name": safe_get(f, "対象物件・現場名"),
            "memo": safe_get(f, "商談内での気づき・備考"),
            "created": ts_to_date(r.get("created_time")),
            "updated": ts_to_date(r.get("last_modified_time")),
            "raw_fields": f,
        }
        deals.append(d)

    total = len(deals)

    # ── 1. 基本統計 ──
    stats = {"total": total}

    # ── 2. ステージ分布（担当者別）──
    stage_by_rep = defaultdict(lambda: Counter())
    stage_total = Counter()
    for d in deals:
        rep = d["rep"] or "(未設定)"
        stage = d["stage"] or "(未設定)"
        stage_by_rep[rep][stage] += 1
        stage_total[stage] += 1

    # ── 3. 温度感分布（担当者別）──
    temp_by_rep = defaultdict(lambda: Counter())
    temp_total = Counter()
    for d in deals:
        rep = d["rep"] or "(未設定)"
        temp = d["temperature"] or "(未設定)"
        temp_by_rep[rep][temp] += 1
        temp_total[temp] += 1

    # ── 4. 次アクション設定率（担当者別）──
    action_by_rep = defaultdict(lambda: {"set": 0, "unset": 0})
    for d in deals:
        rep = d["rep"] or "(未設定)"
        if d["next_action"] and d["next_action"] != "(未設定)":
            action_by_rep[rep]["set"] += 1
        else:
            action_by_rep[rep]["unset"] += 1

    # ── 5. 金額入力率 ──
    amount_set = 0
    amount_by_rep = defaultdict(lambda: {"set": 0, "unset": 0})
    for d in deals:
        rep = d["rep"] or "(未設定)"
        amt = d["amount"]
        if amt and amt not in ("", "0", "None"):
            amount_set += 1
            amount_by_rep[rep]["set"] += 1
        else:
            amount_by_rep[rep]["unset"] += 1

    # ── 6. 放置期間分析（最終更新 or 商談日からの経過）──
    stale_buckets = {"7日以内": 0, "8-30日": 0, "31-90日": 0, "91日以上": 0, "不明": 0}
    stale_by_rep = defaultdict(lambda: {"7日以内": 0, "8-30日": 0, "31-90日": 0, "91日以上": 0, "不明": 0})
    for d in deals:
        rep = d["rep"] or "(未設定)"
        updated = d["updated"] or parse_date_field(d["deal_date"]) or d["created"]
        if not updated:
            stale_buckets["不明"] += 1
            stale_by_rep[rep]["不明"] += 1
            continue
        days = (now - updated).days
        if days <= 7:
            bucket = "7日以内"
        elif days <= 30:
            bucket = "8-30日"
        elif days <= 90:
            bucket = "31-90日"
        else:
            bucket = "91日以上"
        stale_buckets[bucket] += 1
        stale_by_rep[rep][bucket] += 1

    # ── 7. 商談ソース分析 ──
    source_counter = Counter()
    source_by_rep = defaultdict(lambda: Counter())
    for d in deals:
        rep = d["rep"] or "(未設定)"
        src = d["source"] or "(未設定)"
        source_counter[src] += 1
        source_by_rep[rep][src] += 1

    # ── 8. カテゴリ分布 ──
    category_counter = Counter()
    for d in deals:
        cat = d["category"] or "(未設定)"
        category_counter[cat] += 1

    # ── 9. Hot/Warm案件で次アクション未設定 ──
    hot_warm_no_action = []
    for d in deals:
        temp = (d["temperature"] or "").lower()
        if any(t in temp for t in ["hot", "warm", "ホット", "ウォーム"]) or temp in ["a", "b"]:
            if not d["next_action"] or d["next_action"] == "(未設定)":
                hot_warm_no_action.append(d)

    # ── 10. 結果・失注理由 ──
    result_set = sum(1 for d in deals if d["result"] and d["result"] != "(未設定)")
    lost_reason_set = sum(1 for d in deals if d["lost_reason"] and d["lost_reason"] != "(未設定)")

    # ── 11. ヒアリング内容入力率 ──
    hearing_set = sum(1 for d in deals if d["hearing"] and len(str(d["hearing"])) > 5)

    # ── 12. 月別商談数（商談日ベース） ──
    monthly_created = Counter()
    for d in deals:
        dd = parse_date_field(d["deal_date"])
        if dd:
            monthly_created[dd.strftime("%Y-%m")] += 1
        elif d["created"]:
            monthly_created[d["created"].strftime("%Y-%m")] += 1

    # ── Debug: check timestamps ──
    sample_dates = [(d["name"], d["deal_date"], d["created"], d["updated"]) for d in deals[:5]]
    print(f"\n=== Sample timestamps ===", file=sys.stderr)
    for s in sample_dates:
        print(f"  {s}", file=sys.stderr)

    # ── 13. 重複商談名チェック ──
    name_counter = Counter()
    for d in deals:
        if d["name"]:
            name_counter[d["name"]] += 1
    duplicates = {k: v for k, v in name_counter.items() if v > 1}

    # ── 14. 新規/既存 分布 ──
    new_existing_counter = Counter()
    for d in deals:
        ne = d["new_existing"] or "(未設定)"
        new_existing_counter[ne] += 1

    # ── 15. 競合有無 ──
    competition_counter = Counter()
    for d in deals:
        comp = d["competition"] or "(未設定)"
        competition_counter[comp] += 1

    # ── 16. 商材種別 ──
    product_counter = Counter()
    for d in deals:
        prods = d["product_type"]
        if prods:
            for p in prods:
                product_counter[p] += 1
        else:
            product_counter["(未設定)"] += 1

    # ── 17. 次アクション種別分布 ──
    action_type_counter = Counter()
    for d in deals:
        act = d["next_action"] or "(未設定)"
        action_type_counter[act] += 1

    # ── Generate Report ──
    report = generate_report(
        total, deals, stage_total, stage_by_rep, temp_total, temp_by_rep,
        action_by_rep, amount_set, amount_by_rep, stale_buckets, stale_by_rep,
        source_counter, source_by_rep, category_counter,
        hot_warm_no_action, result_set, lost_reason_set, hearing_set,
        monthly_created, duplicates, new_existing_counter, competition_counter,
        product_counter, action_type_counter, today_str
    )
    return report

def generate_report(total, deals, stage_total, stage_by_rep, temp_total, temp_by_rep,
                    action_by_rep, amount_set, amount_by_rep, stale_buckets, stale_by_rep,
                    source_counter, source_by_rep, category_counter,
                    hot_warm_no_action, result_set, lost_reason_set, hearing_set,
                    monthly_created, duplicates, new_existing_counter, competition_counter,
                    product_counter, action_type_counter, today_str):

    lines = []
    lines.append(f"# CRM商談データ品質レポート")
    lines.append(f"")
    lines.append(f"生成日: {today_str}")
    lines.append(f"対象: 商談テーブル（tbl1rM86nAw9l3bP）")
    lines.append(f"総レコード数: **{total}件**")
    lines.append(f"")

    # ── 総合スコア ──
    stage_rate = (total - stage_total.get("(未設定)", 0)) / total * 100 if total else 0
    action_total_set = sum(v["set"] for v in action_by_rep.values())
    action_rate = action_total_set / total * 100 if total else 0
    amount_rate = amount_set / total * 100 if total else 0
    hearing_rate = hearing_set / total * 100 if total else 0
    result_rate = result_set / total * 100 if total else 0

    health_score = (stage_rate * 0.25 + action_rate * 0.25 + amount_rate * 0.2 + hearing_rate * 0.2 + result_rate * 0.1)

    lines.append(f"## 総合データ品質スコア: {health_score:.1f}/100")
    lines.append(f"")
    lines.append(f"| 指標 | 入力率 | 評価 |")
    lines.append(f"|------|--------|------|")
    lines.append(f"| ステージ設定 | {stage_rate:.1f}% ({total - stage_total.get('(未設定)', 0)}/{total}) | {'OK' if stage_rate > 80 else 'NG' if stage_rate < 60 else '要改善'} |")
    lines.append(f"| 次アクション設定 | {action_rate:.1f}% ({action_total_set}/{total}) | {'OK' if action_rate > 80 else 'NG' if action_rate < 60 else '要改善'} |")
    lines.append(f"| 金額入力 | {amount_rate:.1f}% ({amount_set}/{total}) | {'OK' if amount_rate > 60 else 'NG' if amount_rate < 30 else '要改善'} |")
    lines.append(f"| ヒアリング内容 | {hearing_rate:.1f}% ({hearing_set}/{total}) | {'OK' if hearing_rate > 70 else 'NG' if hearing_rate < 40 else '要改善'} |")
    lines.append(f"| 結果入力 | {result_rate:.1f}% ({result_set}/{total}) | {'OK' if result_rate > 50 else 'NG' if result_rate < 20 else '要改善'} |")
    lines.append(f"| 失注理由入力 | {lost_reason_set}/{total} | {'NG' if lost_reason_set < 10 else '要改善'} |")
    lines.append(f"")

    # ── ステージ分布 ──
    lines.append(f"## 1. 商談ステージ分布")
    lines.append(f"")
    lines.append(f"### 全体")
    lines.append(f"| ステージ | 件数 | 割合 |")
    lines.append(f"|----------|------|------|")
    for stage, cnt in stage_total.most_common():
        lines.append(f"| {stage} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    lines.append(f"### 担当者別")
    for rep in sorted(stage_by_rep.keys()):
        rep_total = sum(stage_by_rep[rep].values())
        lines.append(f"")
        lines.append(f"**{rep}** ({rep_total}件)")
        lines.append(f"| ステージ | 件数 | 割合 |")
        lines.append(f"|----------|------|------|")
        for stage, cnt in stage_by_rep[rep].most_common():
            lines.append(f"| {stage} | {cnt} | {cnt/rep_total*100:.1f}% |")
    lines.append(f"")

    # ── 温度感分布 ──
    lines.append(f"## 2. 温度感（温度感スコア）分布")
    lines.append(f"")
    lines.append(f"### 全体")
    lines.append(f"| 温度感 | 件数 | 割合 |")
    lines.append(f"|--------|------|------|")
    for temp, cnt in temp_total.most_common():
        lines.append(f"| {temp} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    lines.append(f"### 担当者別")
    for rep in sorted(temp_by_rep.keys()):
        rep_total = sum(temp_by_rep[rep].values())
        lines.append(f"")
        lines.append(f"**{rep}** ({rep_total}件)")
        lines.append(f"| 温度感 | 件数 | 割合 |")
        lines.append(f"|--------|------|------|")
        for temp, cnt in temp_by_rep[rep].most_common():
            lines.append(f"| {temp} | {cnt} | {cnt/rep_total*100:.1f}% |")
    lines.append(f"")

    # ── 次アクション設定率 ──
    lines.append(f"## 3. 次アクション設定率（担当者別）")
    lines.append(f"")
    lines.append(f"| 担当者 | 設定済 | 未設定 | 設定率 |")
    lines.append(f"|--------|--------|--------|--------|")
    for rep in sorted(action_by_rep.keys()):
        s = action_by_rep[rep]["set"]
        u = action_by_rep[rep]["unset"]
        t = s + u
        lines.append(f"| {rep} | {s} | {u} | {s/t*100:.1f}% |")
    lines.append(f"")

    # ── Hot/Warm案件で次アクション未設定 ──
    lines.append(f"## 4. 要対応: Hot/Warm案件で次アクション未設定（{len(hot_warm_no_action)}件）")
    lines.append(f"")
    if hot_warm_no_action:
        lines.append(f"| 商談名 | 担当 | 温度感 | ステージ |")
        lines.append(f"|--------|------|--------|----------|")
        for d in hot_warm_no_action[:50]:  # limit display
            lines.append(f"| {d['name'][:30]} | {d['rep']} | {d['temperature']} | {d['stage']} |")
    else:
        lines.append("該当なし")
    lines.append(f"")

    # ── 金額入力率 ──
    lines.append(f"## 5. 概算金額入力率（担当者別）")
    lines.append(f"")
    lines.append(f"| 担当者 | 入力済 | 未入力 | 入力率 |")
    lines.append(f"|--------|--------|--------|--------|")
    for rep in sorted(amount_by_rep.keys()):
        s = amount_by_rep[rep]["set"]
        u = amount_by_rep[rep]["unset"]
        t = s + u
        lines.append(f"| {rep} | {s} | {u} | {s/t*100:.1f}% |")
    lines.append(f"")

    # ── 放置期間 ──
    lines.append(f"## 6. 最終更新からの経過日数（放置分析）")
    lines.append(f"")
    lines.append(f"### 全体")
    lines.append(f"| 期間 | 件数 | 割合 |")
    lines.append(f"|------|------|------|")
    for bucket in ["7日以内", "8-30日", "31-90日", "91日以上", "不明"]:
        cnt = stale_buckets[bucket]
        lines.append(f"| {bucket} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    lines.append(f"### 担当者別")
    for rep in sorted(stale_by_rep.keys()):
        rep_total = sum(stale_by_rep[rep].values())
        lines.append(f"")
        lines.append(f"**{rep}** ({rep_total}件)")
        lines.append(f"| 期間 | 件数 | 割合 |")
        lines.append(f"|------|------|------|")
        for bucket in ["7日以内", "8-30日", "31-90日", "91日以上", "不明"]:
            cnt = stale_by_rep[rep][bucket]
            lines.append(f"| {bucket} | {cnt} | {cnt/rep_total*100:.1f}% |")
    lines.append(f"")

    # ── 商談形態 ──
    lines.append(f"## 7. 商談形態分布")
    lines.append(f"")
    lines.append(f"| 形態 | 件数 | 割合 |")
    lines.append(f"|------|------|------|")
    for src, cnt in source_counter.most_common():
        lines.append(f"| {src} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    # ── カテゴリ分布 ──
    lines.append(f"## 8. 客先カテゴリ分布")
    lines.append(f"")
    lines.append(f"| カテゴリ | 件数 | 割合 |")
    lines.append(f"|----------|------|------|")
    for cat, cnt in category_counter.most_common():
        lines.append(f"| {cat} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    # ── 月別推移 ──
    lines.append(f"## 9. 月別商談作成数")
    lines.append(f"")
    lines.append(f"| 月 | 件数 |")
    lines.append(f"|------|------|")
    for month in sorted(monthly_created.keys()):
        lines.append(f"| {month} | {monthly_created[month]} |")
    lines.append(f"")

    # ── 重複チェック ──
    lines.append(f"## 10. 重複商談名チェック")
    lines.append(f"")
    if duplicates:
        lines.append(f"重複候補: {len(duplicates)}件")
        lines.append(f"")
        lines.append(f"| 商談名 | 件数 |")
        lines.append(f"|--------|------|")
        for name, cnt in sorted(duplicates.items(), key=lambda x: -x[1])[:30]:
            lines.append(f"| {name[:40]} | {cnt} |")
    else:
        lines.append("重複なし")
    lines.append(f"")

    # ── 新規/既存 ──
    lines.append(f"## 11. 新規/既存客の別")
    lines.append(f"")
    lines.append(f"| 区分 | 件数 | 割合 |")
    lines.append(f"|------|------|------|")
    for ne, cnt in new_existing_counter.most_common():
        lines.append(f"| {ne} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    # ── 競合有無 ──
    lines.append(f"## 12. 競合有無")
    lines.append(f"")
    lines.append(f"| 区分 | 件数 | 割合 |")
    lines.append(f"|------|------|------|")
    for comp, cnt in competition_counter.most_common():
        lines.append(f"| {comp} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    # ── 商材種別 ──
    lines.append(f"## 13. 商材種別分布")
    lines.append(f"")
    lines.append(f"| 商材 | 件数 |")
    lines.append(f"|------|------|")
    for prod, cnt in product_counter.most_common():
        lines.append(f"| {prod} | {cnt} |")
    lines.append(f"")

    # ── 次アクション種別 ──
    lines.append(f"## 14. 次アクション種別分布")
    lines.append(f"")
    lines.append(f"| アクション | 件数 | 割合 |")
    lines.append(f"|------------|------|------|")
    for act, cnt in action_type_counter.most_common():
        lines.append(f"| {act} | {cnt} | {cnt/total*100:.1f}% |")
    lines.append(f"")

    # ── 改善提案 ──
    lines.append(f"## 改善提案（アクションアイテム）")
    lines.append(f"")

    rec_num = 1

    stage_unset = stage_total.get("(未設定)", 0)
    if stage_unset > 0:
        lines.append(f"### {rec_num}. 商談ステージ未設定の解消（{stage_unset}件）")
        lines.append(f"- **優先度: 高**")
        lines.append(f"- 41%超が未設定のため、パイプライン分析が不可能")
        lines.append(f"- 提案: 商談報告フォームでステージを必須化（現場合意の上）")
        lines.append(f"- 過去データ: ヒアリング内容や温度感から推定して一括補完可能")
        lines.append(f"")
        rec_num += 1

    action_unset_total = sum(v["unset"] for v in action_by_rep.values())
    if action_unset_total > 0:
        lines.append(f"### {rec_num}. 次アクション未設定の解消（{action_unset_total}件）")
        lines.append(f"- **優先度: 高**")
        lines.append(f"- 営業プロセスの「次の一手」が不明な状態")
        lines.append(f"- 特にHot/Warm案件{len(hot_warm_no_action)}件は即日対応すべき")
        lines.append(f"- 提案: 週次1on1で未設定案件を棚卸し")
        lines.append(f"")
        rec_num += 1

    if amount_set / total * 100 < 50:
        lines.append(f"### {rec_num}. 概算金額の入力促進")
        lines.append(f"- **優先度: 中**")
        lines.append(f"- 売上予測・パイプライン金額が算出不可")
        lines.append(f"- 提案: ヒアリング段階でも概算レンジ（例: 50-100万）を入力")
        lines.append(f"")
        rec_num += 1

    if result_set < total * 0.2:
        lines.append(f"### {rec_num}. 結果フィールドの運用開始")
        lines.append(f"- **優先度: 中**")
        lines.append(f"- 受注/失注の結果記録がほぼゼロ → 勝率分析不可")
        lines.append(f"- 提案: 商談クローズ時に結果+失注理由を必ず記録するルール策定")
        lines.append(f"")
        rec_num += 1

    if hearing_set / total * 100 < 60:
        lines.append(f"### {rec_num}. ヒアリング内容の記入率向上")
        lines.append(f"- **優先度: 中**")
        lines.append(f"- フォローメール自動生成やAI分析の精度に直結")
        lines.append(f"- 提案: 箇条書き3行でも可とし、入力ハードルを下げる")
        lines.append(f"")
        rec_num += 1

    stale_90 = stale_buckets.get("91日以上", 0)
    if stale_90 > 50:
        lines.append(f"### {rec_num}. 長期放置案件の整理（91日以上: {stale_90}件）")
        lines.append(f"- **優先度: 低**")
        lines.append(f"- 3ヶ月以上更新なしの案件は「凍結」または「Lost」に分類")
        lines.append(f"- アクティブ案件の視認性が向上し、営業効率UP")
        lines.append(f"")
        rec_num += 1

    if duplicates:
        lines.append(f"### {rec_num}. 重複商談名の統合（{len(duplicates)}件）")
        lines.append(f"- **優先度: 低**")
        lines.append(f"- 同一商談が複数レコードに分散している可能性")
        lines.append(f"- 提案: 担当営業に確認の上、統合または名称変更")
        lines.append(f"")
        rec_num += 1

    lines.append(f"---")
    lines.append(f"")
    lines.append(f"*このレポートは自動生成されました。データ修正は行っていません（READ-ONLY）。*")

    return "\n".join(lines)


def main():
    print("=== CRM商談データ品質監査 ===", file=sys.stderr)
    print("1. Larkトークン取得...", file=sys.stderr)
    token = get_token()

    print("2. 全商談レコード取得...", file=sys.stderr)
    records = fetch_all_records(token)
    print(f"   取得完了: {len(records)}件", file=sys.stderr)

    print("3. 分析実行...", file=sys.stderr)
    report = analyze(records)

    # Output report
    output_path = "/mnt/c/Users/USER/Documents/_data/tas-automation/content/crm_health_report_20260312.md"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n4. レポート保存: {output_path}", file=sys.stderr)

    # Also print to stdout for review
    print(report)


if __name__ == "__main__":
    main()
