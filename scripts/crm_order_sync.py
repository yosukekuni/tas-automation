#!/usr/bin/env python3
"""
CRM受注台帳-商談ファジーマッチング & 温度感自動降格
Phase 1: 受注台帳181件 vs 商談「受注」ステージ1件のギャップを解消
Phase 2: Hot/Warm温度感の自動降格候補を特定

Usage:
  python3 crm_order_sync.py --order-sync    # 受注台帳-商談マッチング (dry-run)
  python3 crm_order_sync.py --temp-decay     # 温度感降格候補 (dry-run)
  python3 crm_order_sync.py --all            # 両方実行
  python3 crm_order_sync.py --execute        # 本番実行（--order-sync or --temp-decayと併用）
"""

import json
import os
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path
from difflib import SequenceMatcher
from collections import defaultdict

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

# ── Config ──
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
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]

TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ORDERS = "tbldLj2iMJYocct6"

CONTENT_DIR = Path("/mnt/c/Users/USER/Documents/_data/content")


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def fetch_all_records(token, table_id):
    """全レコード取得（ページネーション対応）"""
    all_records = []
    page_token = None
    page = 0
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500"
        )
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


def lark_update_record(token, table_id, record_id, fields):
    """Update an existing record"""
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/records/{record_id}"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data, method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                return True
            else:
                print(f"  Update error: {result.get('msg', 'unknown')}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"  Update failed: {e}", file=sys.stderr)
        return False


# ── Text Normalization for Fuzzy Matching ──
# Corporate suffix patterns to strip for matching
CORP_SUFFIXES = [
    r"株式会社", r"㈱", r"有限会社", r"㈲", r"合同会社",
    r"一般社団法人", r"一般財団法人", r"公益社団法人", r"公益財団法人",
    r"社会福祉法人", r"医療法人", r"学校法人", r"宗教法人",
    r"特定非営利活動法人", r"NPO法人",
]

BRANCH_SUFFIXES = [
    r"中部支店", r"名古屋支店", r"東海支店", r"本店", r"本社",
    r"支店", r"支社", r"営業所", r"出張所", r"事業所", r"事業部",
    r"東京本社", r"大阪支店", r"愛知支店", r"三重支店", r"岐阜支店",
    r"静岡支店", r"中部支社", r"名古屋事業所",
]


def normalize_company_name(name: str) -> str:
    """会社名を正規化（表記揺れ対応）"""
    if not name:
        return ""
    # Unicode正規化（全角→半角等）
    name = unicodedata.normalize("NFKC", name)
    # 全角スペース→半角
    name = name.replace("\u3000", " ")
    # 前後の空白・括弧除去
    name = name.strip()
    # 法人格除去
    for suffix in CORP_SUFFIXES:
        name = re.sub(suffix, "", name)
    # 支店・営業所除去
    for suffix in BRANCH_SUFFIXES:
        name = re.sub(suffix, "", name)
    # 前後のスペース・記号クリーンアップ
    name = re.sub(r"[\s　()（）]+", "", name)
    return name.strip()


def fuzzy_match_score(name1: str, name2: str) -> float:
    """2つの会社名のマッチスコア（0.0-1.0）"""
    n1 = normalize_company_name(name1)
    n2 = normalize_company_name(name2)
    if not n1 or not n2:
        return 0.0
    # 短すぎる名前は信頼度が低い（3文字未満は完全一致のみ）
    if len(n1) < 3 or len(n2) < 3:
        return 1.0 if n1 == n2 else 0.0
    # 完全一致
    if n1 == n2:
        return 1.0
    # 片方が片方を含む（短い方が3文字以上の場合のみ）
    shorter = min(len(n1), len(n2))
    if shorter >= 3 and (n1 in n2 or n2 in n1):
        # 長さの比率で微調整（あまりに長さが違うと信頼度下げる）
        ratio = shorter / max(len(n1), len(n2))
        return 0.90 + 0.10 * ratio  # 0.90-1.00
    # SequenceMatcher
    return SequenceMatcher(None, n1, n2).ratio()


# ── Field Extraction Helpers ──
def extract_text_field(fields, key):
    """Larkフィールドからテキスト値を安全に取得"""
    val = fields.get(key)
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                text = item.get("text", "") or item.get("name", "")
                if text:
                    return text
            elif isinstance(item, str) and item:
                return item
        return ""
    if isinstance(val, dict):
        return val.get("text", "") or val.get("name", "") or str(val)
    return str(val)


def extract_deal_company(fields):
    """商談テーブルから取引先名を取得（リンクフィールド優先）"""
    # 1. 取引先リンクフィールド
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
    # 2. 新規取引先名
    new_name = fields.get("新規取引先名", "")
    if new_name:
        return new_name
    # 3. 商談名（最後の手段）
    return fields.get("商談名", "") or ""


def extract_order_company(fields):
    """受注台帳テーブルから取引先名を取得"""
    # テキストフィールドの可能性
    name = extract_text_field(fields, "取引先名")
    if name:
        return name
    # リンクフィールドの可能性
    name = extract_text_field(fields, "取引先")
    if name:
        return name
    # 案件名から推測
    return extract_text_field(fields, "案件名") or ""


def ts_to_datetime(ms_val):
    """ミリ秒タイムスタンプをdatetimeに変換"""
    if not ms_val:
        return None
    try:
        ts = int(ms_val) / 1000
        return datetime.fromtimestamp(ts)
    except (ValueError, OSError, TypeError):
        return None


def extract_sales_rep(fields):
    """担当営業名を取得"""
    tantou = fields.get("担当営業", "")
    if isinstance(tantou, list) and tantou:
        for person in tantou:
            if isinstance(person, dict):
                return person.get("name", "")
            elif isinstance(person, str):
                return person
    return ""


# ── Phase 1: Order-Deal Fuzzy Matching ──
def run_order_sync(execute=False):
    """受注台帳と商談のファジーマッチング"""
    print("=" * 60)
    print("Phase 1: 受注台帳-商談ファジーマッチング")
    print("=" * 60)

    token = lark_get_token()

    print("\n[1/4] 受注台帳レコード取得中...")
    orders = fetch_all_records(token, TABLE_ORDERS)
    print(f"  受注台帳: {len(orders)}件")

    print("\n[2/4] 商談レコード取得中...")
    deals = fetch_all_records(token, TABLE_DEALS)
    print(f"  商談: {len(deals)}件")

    # Parse orders
    order_list = []
    for rec in orders:
        f = rec.get("fields", {})
        company = extract_order_company(f)
        order_list.append({
            "record_id": rec.get("record_id", ""),
            "company": company,
            "company_normalized": normalize_company_name(company),
            "project": extract_text_field(f, "案件名"),
            "amount": f.get("受注金額", 0) or f.get("金額", 0) or 0,
            "date": ts_to_datetime(f.get("受注日")) or ts_to_datetime(rec.get("created_time")),
            "raw_fields": f,
        })

    # Parse deals
    deal_list = []
    for rec in deals:
        f = rec.get("fields", {})
        company = extract_deal_company(f)
        stage = extract_text_field(f, "商談ステージ")
        deal_list.append({
            "record_id": rec.get("record_id", ""),
            "company": company,
            "company_normalized": normalize_company_name(company),
            "deal_name": extract_text_field(f, "商談名"),
            "stage": stage,
            "temperature": extract_text_field(f, "温度感スコア"),
            "sales_rep": extract_sales_rep(f),
            "created": ts_to_datetime(rec.get("created_time")),
            "updated": ts_to_datetime(rec.get("last_modified_time")),
            "raw_fields": f,
        })

    # Find deals already in 受注 stage
    already_won = {d["record_id"] for d in deal_list if d["stage"] == "受注"}
    print(f"\n  商談「受注」ステージ: {len(already_won)}件")

    # ── Fuzzy matching ──
    print("\n[3/4] ファジーマッチング実行中...")
    MATCH_THRESHOLD = 0.80  # Minimum score to consider a match

    matches = []  # (order, deal, score)
    unmatched_orders = []

    for order in order_list:
        if not order["company"]:
            unmatched_orders.append((order, "取引先名が空"))
            continue

        best_match = None
        best_score = 0.0

        for deal in deal_list:
            if not deal["company"]:
                continue
            score = fuzzy_match_score(order["company"], deal["company"])
            if score > best_score:
                best_score = score
                best_match = deal

            # Also try matching order project name against deal company/name
            if order["project"]:
                score2 = fuzzy_match_score(order["project"], deal["company"])
                if score2 > best_score:
                    best_score = score2
                    best_match = deal

        if best_match and best_score >= MATCH_THRESHOLD:
            matches.append((order, best_match, best_score))
        else:
            reason = f"最高スコア {best_score:.2f} < {MATCH_THRESHOLD}" if best_match else "マッチ候補なし"
            unmatched_orders.append((order, reason))

    # Deduplicate: multiple orders may match the same deal.
    # We want unique deals that should be marked 受注.
    # Keep the best-scoring match per deal_record_id.
    deal_best_match = {}  # deal_record_id -> (order, deal, score)
    for order, deal, score in matches:
        rid = deal["record_id"]
        if rid not in deal_best_match or score > deal_best_match[rid][2]:
            deal_best_match[rid] = (order, deal, score)

    unique_matches = list(deal_best_match.values())

    # Categorize
    exact_matches = [(o, d, s) for o, d, s in unique_matches if s >= 0.95]
    fuzzy_matches = [(o, d, s) for o, d, s in unique_matches if 0.80 <= s < 0.95]
    already_won_matches = [(o, d, s) for o, d, s in unique_matches if d["record_id"] in already_won]
    new_won_candidates = [(o, d, s) for o, d, s in unique_matches if d["record_id"] not in already_won]

    print(f"\n  マッチ結果:")
    print(f"    受注台帳→商談 マッチ件数（重複含む）: {len(matches)}件")
    print(f"    ユニーク商談マッチ: {len(unique_matches)}件")
    print(f"    -- 完全一致 (>=0.95): {len(exact_matches)}件")
    print(f"    -- ファジー (0.80-0.94): {len(fuzzy_matches)}件")
    print(f"    既に受注ステージ: {len(already_won_matches)}件")
    print(f"    受注ステージ更新候補: {len(new_won_candidates)}件")
    print(f"    マッチなし: {len(unmatched_orders)}件")

    # Count how many orders each matched deal covers
    deal_order_count = defaultdict(int)
    for order, deal, score in matches:
        deal_order_count[deal["record_id"]] += 1

    # ── Generate Report ──
    print("\n[4/4] レポート生成中...")
    report = generate_order_sync_report(
        orders=order_list,
        deals=deal_list,
        matches=unique_matches,
        exact_matches=exact_matches,
        fuzzy_matches=fuzzy_matches,
        already_won_matches=already_won_matches,
        new_won_candidates=new_won_candidates,
        unmatched_orders=unmatched_orders,
        deal_order_count=deal_order_count,
    )

    report_path = CONTENT_DIR / "crm_order_sync_dryrun.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  レポート保存: {report_path}")

    # ── Execute if requested ──
    if execute:
        print("\n[EXECUTE] 本番実行: 商談ステージを「受注」に更新...")
        updated = 0
        # Only update exact matches (>=0.95) for safety
        safe_candidates = [(o, d, s) for o, d, s in new_won_candidates if s >= 0.95]
        for order, deal, score in safe_candidates:
            print(f"  Updating: {deal['deal_name'] or deal['company']} (score={score:.2f})")
            success = lark_update_record(token, TABLE_DEALS, deal["record_id"], {
                "商談ステージ": "受注"
            })
            if success:
                updated += 1
            time.sleep(0.3)
        print(f"\n  更新完了: {updated}/{len(safe_candidates)}件")
    else:
        print("\n  [DRY-RUN] 本番実行するには --execute を追加してください")

    return matches, unmatched_orders


def generate_order_sync_report(orders, deals, matches, exact_matches, fuzzy_matches,
                                already_won_matches, new_won_candidates, unmatched_orders,
                                deal_order_count=None):
    """マッチング結果のMarkdownレポート生成"""
    deal_order_count = deal_order_count or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# CRM受注台帳-商談マッチングレポート (dry-run)",
        f"",
        f"生成日: {now}",
        f"",
        f"## サマリー",
        f"",
        f"| 指標 | 件数 |",
        f"|------|------|",
        f"| 受注台帳レコード数 | {len(orders)} |",
        f"| 商談レコード数 | {len(deals)} |",
        f"| ユニーク商談マッチ | {len(matches)} |",
        f"| -- 完全一致 (>=0.95) | {len(exact_matches)} |",
        f"| -- ファジー (0.80-0.94) | {len(fuzzy_matches)} |",
        f"| 既に受注ステージ | {len(already_won_matches)} |",
        f"| **受注ステージ更新候補** | **{len(new_won_candidates)}** |",
        f"| マッチなし | {len(unmatched_orders)} |",
        f"",
        f"## 受注ステージ更新候補 ({len(new_won_candidates)}件)",
        f"",
        f"以下の商談を「受注」ステージに更新すべき候補です。",
        f"",
    ]

    if new_won_candidates:
        # Sort by score descending
        sorted_candidates = sorted(new_won_candidates, key=lambda x: x[2], reverse=True)

        lines.append("### 高信頼度 (score >= 0.95) -- 自動更新可能")
        lines.append("")
        high_conf = [(o, d, s) for o, d, s in sorted_candidates if s >= 0.95]
        if high_conf:
            lines.append("| # | 受注台帳 取引先 | 商談 取引先 | スコア | 受注件数 | 商談現ステージ | 担当 |")
            lines.append("|---|-----------------|-------------|--------|----------|----------------|------|")
            for i, (order, deal, score) in enumerate(high_conf, 1):
                oc = deal_order_count.get(deal["record_id"], 1)
                lines.append(
                    f"| {i} | {order['company']} | {deal['company']} | {score:.2f} | "
                    f"{oc} | {deal['stage'] or '(未設定)'} | {deal['sales_rep']} |"
                )
            lines.append("")
        else:
            lines.append("(該当なし)")
            lines.append("")

        lines.append("### 要目視確認 (0.80 <= score < 0.95)")
        lines.append("")
        low_conf = [(o, d, s) for o, d, s in sorted_candidates if s < 0.95]
        if low_conf:
            lines.append("| # | 受注台帳 取引先 | 商談 取引先 | スコア | 受注件数 | 商談現ステージ | 担当 |")
            lines.append("|---|-----------------|-------------|--------|----------|----------------|------|")
            for i, (order, deal, score) in enumerate(low_conf, 1):
                oc = deal_order_count.get(deal["record_id"], 1)
                lines.append(
                    f"| {i} | {order['company']} | {deal['company']} | {score:.2f} | "
                    f"{oc} | {deal['stage'] or '(未設定)'} | {deal['sales_rep']} |"
                )
            lines.append("")
        else:
            lines.append("(該当なし)")
            lines.append("")

    # Already matched
    lines.append(f"## 既にマッチ済み（受注ステージ）({len(already_won_matches)}件)")
    lines.append("")
    if already_won_matches:
        lines.append("| # | 受注台帳 取引先 | 商談 取引先 | スコア |")
        lines.append("|---|-----------------|-------------|--------|")
        for i, (order, deal, score) in enumerate(sorted(already_won_matches, key=lambda x: x[2], reverse=True)[:20], 1):
            lines.append(f"| {i} | {order['company']} | {deal['company']} | {score:.2f} |")
        if len(already_won_matches) > 20:
            lines.append(f"| ... | (他{len(already_won_matches)-20}件) | | |")
        lines.append("")

    # Unmatched
    lines.append(f"## マッチなし ({len(unmatched_orders)}件)")
    lines.append("")
    lines.append("商談テーブルに対応するレコードが見つからなかった受注台帳レコード。")
    lines.append("新規の取引先、または商談未登録の受注。")
    lines.append("")
    if unmatched_orders:
        lines.append("| # | 受注台帳 取引先 | 案件名 | 理由 |")
        lines.append("|---|-----------------|--------|------|")
        for i, (order, reason) in enumerate(unmatched_orders[:50], 1):
            lines.append(f"| {i} | {order['company']} | {order['project']} | {reason} |")
        if len(unmatched_orders) > 50:
            lines.append(f"| ... | (他{len(unmatched_orders)-50}件) | | |")
        lines.append("")

    lines.append("---")
    lines.append(f"生成: crm_order_sync.py --order-sync (dry-run)")
    lines.append(f"実行: `python3 crm_order_sync.py --order-sync --execute` で本番更新")

    return "\n".join(lines)


# ── Phase 2: Temperature Decay ──
def run_temp_decay(execute=False):
    """Hot/Warm温度感の自動降格候補を特定"""
    print("=" * 60)
    print("Phase 2: 温度感自動降格候補")
    print("=" * 60)

    token = lark_get_token()

    print("\n[1/3] 商談レコード取得中...")
    deals = fetch_all_records(token, TABLE_DEALS)
    print(f"  商談: {len(deals)}件")

    now = datetime.now()
    HOT_DECAY_DAYS = 90   # Hot + 90日超停滞 → Warm
    WARM_DECAY_DAYS = 180  # Warm + 180日超停滞 → Cold

    junk_patterns = ["テスト", "test", "サンプル", "sample", "ダミー"]

    hot_to_warm = []
    warm_to_cold = []
    active_hot = []
    active_warm = []

    print("\n[2/3] 温度感分析中...")
    for rec in deals:
        f = rec.get("fields", {})
        temp = extract_text_field(f, "温度感スコア")
        stage = extract_text_field(f, "商談ステージ")

        # Skip terminal stages
        if stage in ("失注", "受注"):
            continue

        # Only process Hot and Warm
        if temp not in ("Hot", "Warm"):
            continue

        deal_name = extract_text_field(f, "商談名") or extract_deal_company(f) or ""
        if not deal_name or any(p in deal_name.lower() for p in junk_patterns):
            continue

        # Determine last activity date
        last_activity = None

        # Check 商談日
        deal_date = f.get("商談日", "")
        if isinstance(deal_date, (int, float)) and deal_date > 0:
            last_activity = ts_to_datetime(deal_date)

        # Check 次アクション日
        next_action_date = f.get("次アクション日", "")
        if isinstance(next_action_date, (int, float)) and next_action_date > 0:
            nad = ts_to_datetime(next_action_date)
            if nad and nad > now:
                # Future action planned, not stagnant
                if temp == "Hot":
                    active_hot.append({
                        "deal_name": deal_name,
                        "next_action": extract_text_field(f, "次アクション"),
                        "next_action_date": nad.strftime("%Y-%m-%d"),
                    })
                else:
                    active_warm.append({
                        "deal_name": deal_name,
                        "next_action": extract_text_field(f, "次アクション"),
                        "next_action_date": nad.strftime("%Y-%m-%d"),
                    })
                continue
            if nad and (last_activity is None or nad > last_activity):
                last_activity = nad

        # Fallback: record last_modified_time
        if last_activity is None:
            last_activity = ts_to_datetime(rec.get("last_modified_time"))

        if last_activity is None:
            # No date info at all - flag as needing attention
            if temp == "Hot":
                hot_to_warm.append({
                    "record_id": rec.get("record_id", ""),
                    "deal_name": deal_name,
                    "company": extract_deal_company(f),
                    "stage": stage or "(未設定)",
                    "sales_rep": extract_sales_rep(f),
                    "days_stagnant": "不明",
                    "last_activity": "不明",
                    "current_temp": "Hot",
                    "proposed_temp": "Warm",
                })
            continue

        days_inactive = (now - last_activity).days

        if temp == "Hot":
            if days_inactive > HOT_DECAY_DAYS:
                hot_to_warm.append({
                    "record_id": rec.get("record_id", ""),
                    "deal_name": deal_name,
                    "company": extract_deal_company(f),
                    "stage": stage or "(未設定)",
                    "sales_rep": extract_sales_rep(f),
                    "days_stagnant": days_inactive,
                    "last_activity": last_activity.strftime("%Y-%m-%d"),
                    "current_temp": "Hot",
                    "proposed_temp": "Warm",
                })
            else:
                active_hot.append({
                    "deal_name": deal_name,
                    "days_since_activity": days_inactive,
                    "last_activity": last_activity.strftime("%Y-%m-%d"),
                })

        elif temp == "Warm":
            if days_inactive > WARM_DECAY_DAYS:
                warm_to_cold.append({
                    "record_id": rec.get("record_id", ""),
                    "deal_name": deal_name,
                    "company": extract_deal_company(f),
                    "stage": stage or "(未設定)",
                    "sales_rep": extract_sales_rep(f),
                    "days_stagnant": days_inactive,
                    "last_activity": last_activity.strftime("%Y-%m-%d"),
                    "current_temp": "Warm",
                    "proposed_temp": "Cold",
                })
            else:
                active_warm.append({
                    "deal_name": deal_name,
                    "days_since_activity": days_inactive,
                    "last_activity": last_activity.strftime("%Y-%m-%d"),
                })

    print(f"\n  結果:")
    print(f"    Hot → Warm 降格候補: {len(hot_to_warm)}件")
    print(f"    Warm → Cold 降格候補: {len(warm_to_cold)}件")
    print(f"    アクティブ Hot: {len(active_hot)}件")
    print(f"    アクティブ Warm: {len(active_warm)}件")

    # ── Generate Report ──
    print("\n[3/3] レポート生成中...")
    report = generate_temp_decay_report(
        hot_to_warm=hot_to_warm,
        warm_to_cold=warm_to_cold,
        active_hot=active_hot,
        active_warm=active_warm,
    )

    report_path = CONTENT_DIR / "crm_temp_decay_dryrun.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n  レポート保存: {report_path}")

    # ── Execute if requested ──
    if execute:
        print("\n[EXECUTE] 本番実行: 温度感を降格...")
        updated = 0
        all_candidates = hot_to_warm + warm_to_cold
        for candidate in all_candidates:
            rid = candidate["record_id"]
            new_temp = candidate["proposed_temp"]
            print(f"  Updating: {candidate['deal_name']} → {new_temp}")
            success = lark_update_record(token, TABLE_DEALS, rid, {
                "温度感スコア": new_temp
            })
            if success:
                updated += 1
            time.sleep(0.3)
        print(f"\n  更新完了: {updated}/{len(all_candidates)}件")
    else:
        print("\n  [DRY-RUN] 本番実行するには --execute を追加してください")

    return hot_to_warm, warm_to_cold


def generate_temp_decay_report(hot_to_warm, warm_to_cold, active_hot, active_warm):
    """温度感降格候補のMarkdownレポート生成"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_decay = len(hot_to_warm) + len(warm_to_cold)
    total_active = len(active_hot) + len(active_warm)

    lines = [
        f"# CRM温度感降格候補レポート (dry-run)",
        f"",
        f"生成日: {now}",
        f"",
        f"## ルール",
        f"- Hot + 90日超停滞 → **Warm** に降格",
        f"- Warm + 180日超停滞 → **Cold** に降格",
        f"- 失注/受注ステージは対象外",
        f"- 将来の次アクション日がある商談は対象外（アクティブ扱い）",
        f"",
        f"## サマリー",
        f"",
        f"| 指標 | 件数 |",
        f"|------|------|",
        f"| Hot → Warm 降格候補 | {len(hot_to_warm)} |",
        f"| Warm → Cold 降格候補 | {len(warm_to_cold)} |",
        f"| **降格候補 合計** | **{total_decay}** |",
        f"| アクティブ Hot | {len(active_hot)} |",
        f"| アクティブ Warm | {len(active_warm)} |",
        f"| アクティブ合計 | {total_active} |",
        f"",
    ]

    # Hot → Warm
    lines.append(f"## Hot → Warm 降格候補 ({len(hot_to_warm)}件)")
    lines.append("")
    if hot_to_warm:
        # Sort by days_stagnant descending
        sorted_hw = sorted(hot_to_warm, key=lambda x: x["days_stagnant"] if isinstance(x["days_stagnant"], int) else 9999, reverse=True)
        lines.append("| # | 商談名 | 取引先 | ステージ | 停滞日数 | 最終活動日 | 担当 |")
        lines.append("|---|--------|--------|----------|----------|------------|------|")
        for i, c in enumerate(sorted_hw, 1):
            lines.append(
                f"| {i} | {c['deal_name']} | {c['company']} | {c['stage']} | "
                f"{c['days_stagnant']}日 | {c['last_activity']} | {c['sales_rep']} |"
            )
        lines.append("")
    else:
        lines.append("(該当なし)")
        lines.append("")

    # Warm → Cold
    lines.append(f"## Warm → Cold 降格候補 ({len(warm_to_cold)}件)")
    lines.append("")
    if warm_to_cold:
        sorted_wc = sorted(warm_to_cold, key=lambda x: x["days_stagnant"] if isinstance(x["days_stagnant"], int) else 9999, reverse=True)
        lines.append("| # | 商談名 | 取引先 | ステージ | 停滞日数 | 最終活動日 | 担当 |")
        lines.append("|---|--------|--------|----------|----------|------------|------|")
        for i, c in enumerate(sorted_wc, 1):
            lines.append(
                f"| {i} | {c['deal_name']} | {c['company']} | {c['stage']} | "
                f"{c['days_stagnant']}日 | {c['last_activity']} | {c['sales_rep']} |"
            )
        lines.append("")
    else:
        lines.append("(該当なし)")
        lines.append("")

    # Active Hot
    lines.append(f"## アクティブ Hot ({len(active_hot)}件)")
    lines.append("")
    if active_hot:
        lines.append("| # | 商談名 | 最終活動日 | 備考 |")
        lines.append("|---|--------|------------|------|")
        for i, h in enumerate(active_hot, 1):
            note = ""
            if "next_action_date" in h:
                note = f"次アクション: {h.get('next_action', '')} ({h['next_action_date']})"
            elif "days_since_activity" in h:
                note = f"最終活動から{h['days_since_activity']}日"
            lines.append(f"| {i} | {h['deal_name']} | {h.get('last_activity', '')} | {note} |")
        lines.append("")

    # Active Warm
    lines.append(f"## アクティブ Warm ({len(active_warm)}件)")
    lines.append("")
    if active_warm:
        lines.append("| # | 商談名 | 最終活動日 | 備考 |")
        lines.append("|---|--------|------------|------|")
        for i, w in enumerate(active_warm, 1):
            note = ""
            if "next_action_date" in w:
                note = f"次アクション: {w.get('next_action', '')} ({w['next_action_date']})"
            elif "days_since_activity" in w:
                note = f"最終活動から{w['days_since_activity']}日"
            lines.append(f"| {i} | {w['deal_name']} | {w.get('last_activity', '')} | {note} |")
        lines.append("")

    lines.append("---")
    lines.append(f"生成: crm_order_sync.py --temp-decay (dry-run)")
    lines.append(f"実行: `python3 crm_order_sync.py --temp-decay --execute` で本番更新")

    return "\n".join(lines)


# ── Main ──
def main():
    args = sys.argv[1:]

    if not args or "--help" in args or "-h" in args:
        print(__doc__)
        return

    execute = "--execute" in args

    if "--all" in args:
        run_order_sync(execute=execute)
        print()
        run_temp_decay(execute=execute)
    elif "--order-sync" in args:
        run_order_sync(execute=execute)
    elif "--temp-decay" in args:
        run_temp_decay(execute=execute)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
