#!/usr/bin/env python3
"""
受注台帳 → LP実績数値 自動連動スクリプト

受注台帳(Lark Base)から業種別集計を取得し、
WordPress LPの実績数値を最新データで更新する。

対象LP:
  - /lp/general-contractor/ (ID: 6148) ゼネコン向け
  - /lp/consultant/ (ID: 6149) コンサルタント向け

Usage:
  python3 lp_stats_sync.py                        # 全LP更新
  python3 lp_stats_sync.py --dry-run               # プレビューのみ
  python3 lp_stats_sync.py --lp general-contractor  # 特定LPのみ
  python3 lp_stats_sync.py --lp consultant           # 特定LPのみ
"""

import json
import os
import re
import sys
import time
import base64
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
BACKUP_DIR = SCRIPT_DIR.parent / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

# ── Config ──
CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
ORDER_TABLE_ID = "tbldLj2iMJYocct6"

WP_BASE_URL = CONFIG["wordpress"]["base_url"]
WP_USER = CONFIG["wordpress"]["user"]
WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]

# LP定義
LP_CONFIG = {
    "general-contractor": {
        "page_id": 6148,
        "industry": "ゼネコン",
        "slug": "general-contractor",
        "label": "ゼネコン向けLP",
    },
    "consultant": {
        "page_id": 6149,
        "industry": "建設コンサルタント",
        "industry_aliases": ["コンサルタント", "コンサル"],
        "slug": "consultant",
        "label": "コンサルタント向けLP",
    },
    "government": {
        "page_id": 6880,
        "industry": "官公庁",
        "slug": "government",
        "label": "官公庁向けLP",
    },
    "real-estate": {
        "page_id": 6882,
        "industry": "不動産",
        "industry_aliases": ["デベロッパー", "リアルティ"],
        "slug": "real-estate",
        "label": "不動産向けLP",
    },
    "inspection": {
        "page_id": 6884,
        "industry": "その他",
        "industry_aliases": [],
        "slug": "inspection",
        "label": "点検向けLP",
    },
}

# 業種分類キーワード（order_classifier.pyと同期）
INDUSTRY_RULES = {
    "ゼネコン": [
        "建設", "組", "工業", "工務", "土木", "JV", "ＪＶ",
        "鳶", "基礎", "舗装", "造園", "電工", "設備工",
        "鉄工", "管工", "塗装", "防水", "解体", "重機",
    ],
    "コンサルタント": [
        "コンサルタント", "コンサル", "設計", "技研",
        "地質", "エンジニア", "計画",
    ],
    "測量会社": ["測量", "工測"],
    "不動産": ["不動産", "デベロッパー", "地所"],
    "官公庁": ["市役所", "県庁", "事務所"],
    "メーカー": ["製作所", "製薬", "電機", "化学", "製造"],
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


def lark_list_records(token, table_id, page_size=500):
    records = []
    page_token = None
    while True:
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        )
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as r:
                resp = json.loads(r.read())
                items = resp.get("data", {}).get("items", [])
                records.extend(items)
                if not resp.get("data", {}).get("has_more"):
                    break
                page_token = resp["data"].get("page_token")
        except Exception as e:
            print(f"Lark API error: {e}")
            break
        time.sleep(0.3)
    return records


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item.get("text", item.get("name", str(item)))
            return str(item)
        return ""
    if isinstance(value, dict):
        return value.get("text", value.get("name", str(value)))
    return str(value) if value else ""


def classify_industry(company_name):
    """取引先名から業種を推定"""
    for industry, keywords in INDUSTRY_RULES.items():
        for kw in keywords:
            if kw in company_name:
                return industry
    return "その他"


# ── WordPress API ──
def wp_auth_header():
    creds = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()
    return f"Basic {creds}"


def wp_get_page(page_id):
    """WP REST APIでページ取得"""
    url = f"{WP_BASE_URL}/pages/{page_id}?context=edit"
    req = urllib.request.Request(
        url,
        headers={"Authorization": wp_auth_header()},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        print(f"  WP GET error: {e.code} {e.read().decode()[:200]}")
        return None


def update_stats_in_html(html, stats, lp_key):
    """LP HTMLの実績数値を更新

    対象パターン:
    - 「受注実績XX件」→ 最新件数に更新
    - 「XX社」→ 最新社数に更新
    - 「平均コスト削減XX%」等の数値更新
    """
    updated = html
    count = stats.get("count", 0)
    companies = stats.get("companies", 0)
    avg_price = stats.get("avg_price", 0)

    # 受注実績 XX件 パターン
    updated = re.sub(
        r'(受注実績\s*)[0-9０-９,]+(\s*件)',
        lambda m: f'{m.group(1)}{count}{m.group(2)}',
        updated
    )

    # 導入企業 XX社 / 取引先 XX社 パターン
    updated = re.sub(
        r'((?:導入企業|取引先|お取引先)\s*)[0-9０-９,]+(\s*社)',
        lambda m: f'{m.group(1)}{companies}{m.group(2)}',
        updated
    )

    # XX件の実績 パターン
    updated = re.sub(
        r'[0-9０-９,]+(\s*件の(?:実績|導入))',
        lambda m: f'{count}{m.group(1)}',
        updated
    )

    # 累計XX件 パターン
    updated = re.sub(
        r'(累計\s*)[0-9０-９,]+(\s*件)',
        lambda m: f'{m.group(1)}{count}{m.group(2)}',
        updated
    )

    # data属性やクラスで管理されている場合
    # data-stat-count="XX" パターン
    updated = re.sub(
        r'(data-stat-count\s*=\s*")[0-9]+(")',
        lambda m: f'{m.group(1)}{count}{m.group(2)}',
        updated
    )
    updated = re.sub(
        r'(data-stat-companies\s*=\s*")[0-9]+(")',
        lambda m: f'{m.group(1)}{companies}{m.group(2)}',
        updated
    )

    return updated


def aggregate_orders(records):
    """受注台帳レコードを業種別に集計"""
    # 非案件パターン除外
    non_case_patterns = [
        r"支払通知書", r"支払明細書", r"支払明細", r"営業代行",
    ]

    industry_stats = defaultdict(lambda: {
        "count": 0,
        "total_amount": 0,
        "companies": set(),
        "records": [],
    })

    for rec in records:
        fields = rec.get("fields", {})
        case_name = extract_text(fields.get("案件名", ""))
        company = extract_text(fields.get("取引先", ""))
        stage = extract_text(fields.get("出典", ""))

        # 非案件除外
        if any(re.search(p, case_name) for p in non_case_patterns):
            continue

        # 受注ステージのみカウント（出典=5_受注100%）
        if "受注" not in stage and "100" not in stage:
            # 受注金額がある場合も含める
            order_amount = extract_text(fields.get("受注金額", ""))
            if not order_amount or order_amount == "0":
                continue

        # 業種分類（フィールド値優先、なければ推定）
        industry = extract_text(fields.get("業種", ""))
        if not industry or industry == "その他":
            industry = classify_industry(company)

        # 金額
        try:
            amount = int(float(extract_text(fields.get("受注金額", "0") or "0")))
        except ValueError:
            amount = 0

        industry_stats[industry]["count"] += 1
        industry_stats[industry]["total_amount"] += amount
        if company:
            industry_stats[industry]["companies"].add(company)
        industry_stats[industry]["records"].append(case_name)

    # setをカウントに変換
    result = {}
    for ind, data in industry_stats.items():
        result[ind] = {
            "count": data["count"],
            "total_amount": data["total_amount"],
            "companies": len(data["companies"]),
            "avg_price": data["total_amount"] // max(data["count"], 1),
            "sample_records": data["records"][:5],
        }
    return result


def main():
    dry_run = "--dry-run" in sys.argv
    target_lp = None

    # --lp オプション解析
    if "--lp" in sys.argv:
        idx = sys.argv.index("--lp")
        if idx + 1 < len(sys.argv):
            target_lp = sys.argv[idx + 1]
            if target_lp not in LP_CONFIG:
                print(f"Error: unknown LP '{target_lp}'. Available: {', '.join(LP_CONFIG.keys())}")
                sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("受注台帳 → LP実績数値 自動連動")
    print(f"モード: {'DRY-RUN' if dry_run else '本番更新'}")
    if target_lp:
        print(f"対象LP: {target_lp}")
    print("=" * 60)

    # 1. Lark受注台帳から集計
    print("\n[1/4] Lark認証 & 受注台帳取得...")
    token = lark_get_token()
    records = lark_list_records(token, ORDER_TABLE_ID)
    print(f"  {len(records)}件取得")

    # 2. 業種別集計
    print("\n[2/4] 業種別集計...")
    stats = aggregate_orders(records)

    for ind, data in sorted(stats.items(), key=lambda x: x[1]["count"], reverse=True):
        print(f"  {ind}: {data['count']}件 / {data['companies']}社 / 平均{data['avg_price']:,}円")

    # 全体の合計も計算
    total_count = sum(d["count"] for d in stats.values())
    total_companies = len(set().union(*[
        set() for _ in stats.values()
    ]))  # 重複企業は後で修正

    # 3. LP更新対象の決定
    print("\n[3/4] LP更新...")
    lps_to_update = [target_lp] if target_lp else list(LP_CONFIG.keys())

    for lp_key in lps_to_update:
        lp = LP_CONFIG[lp_key]
        industry = lp["industry"]
        aliases = lp.get("industry_aliases", [])
        lp_stats = stats.get(industry, None)
        if lp_stats is None:
            for alias in aliases:
                lp_stats = stats.get(alias, None)
                if lp_stats:
                    break
        if lp_stats is None:
            lp_stats = {"count": 0, "companies": 0, "avg_price": 0}

        print(f"\n  --- {lp['label']} (ID: {lp['page_id']}) ---")
        print(f"  業種: {industry} (aliases: {aliases})")
        print(f"  受注件数: {lp_stats['count']}件")
        print(f"  取引先数: {lp_stats['companies']}社")
        print(f"  平均単価: {lp_stats['avg_price']:,}円")

        # WPページ取得
        print(f"  WPページ取得中...")
        page = wp_get_page(lp["page_id"])
        if not page:
            print(f"  ERROR: ページ取得失敗。スキップ。")
            continue

        content = page.get("content", {}).get("raw", "")
        if not content:
            content = page.get("content", {}).get("rendered", "")
        if not content:
            print(f"  WARNING: コンテンツが空です。スキップ。")
            continue

        # バックアップ
        backup_path = BACKUP_DIR / f"{timestamp}_lp_{lp_key}_backup.json"
        with open(backup_path, "w", encoding="utf-8") as f:
            json.dump({
                "page_id": lp["page_id"],
                "title": page.get("title", {}).get("raw", ""),
                "content": content,
                "timestamp": timestamp,
            }, f, ensure_ascii=False, indent=2)
        print(f"  バックアップ: {backup_path}")

        # HTML内の数値更新
        updated_content = update_stats_in_html(content, lp_stats, lp_key)

        if updated_content == content:
            print(f"  変更なし（数値パターンが見つからないか、既に最新）")
            # 差分がない場合でもレポートする
            continue

        # 差分表示
        print(f"  変更あり:")
        old_lines = content.split("\n")
        new_lines = updated_content.split("\n")
        for i, (old, new) in enumerate(zip(old_lines, new_lines)):
            if old != new:
                print(f"    L{i+1}: {old.strip()[:80]}")
                print(f"      -> {new.strip()[:80]}")

        if dry_run:
            print(f"  [DRY-RUN] 更新スキップ")
            continue

        # wp_safe_deploy経由でデプロイ
        print(f"  wp_safe_deploy経由でデプロイ...")
        sys.path.insert(0, str(SCRIPT_DIR))
        try:
            from wp_safe_deploy import safe_update_page
            ok = safe_update_page(lp["page_id"], updated_content, profile="article")
            if ok:
                print(f"  デプロイ完了")
            else:
                print(f"  デプロイ失敗（review_agentブロックの可能性）")
        except Exception as e:
            print(f"  デプロイエラー: {e}")

    # 4. サマリー
    print("\n[4/4] サマリー")
    print(f"  全業種合計: {total_count}件")
    for lp_key in lps_to_update:
        lp = LP_CONFIG[lp_key]
        industry = lp["industry"]
        aliases = lp.get("industry_aliases", [])
        lp_stats = stats.get(industry, None)
        if lp_stats is None:
            for alias in aliases:
                lp_stats = stats.get(alias, None)
                if lp_stats:
                    break
        if lp_stats is None:
            lp_stats = {"count": 0, "companies": 0}
        print(f"  {lp['label']}: {lp_stats['count']}件 / {lp_stats['companies']}社")

    print("\n完了")


if __name__ == "__main__":
    main()
