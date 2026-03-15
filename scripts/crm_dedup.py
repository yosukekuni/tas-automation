#!/usr/bin/env python3
"""
CRM取引先テーブル 重複検出・名寄せ準備スクリプト

検出ロジック:
  1. 完全一致: 取引先名（正式）が完全に同じ
  2. 正規化一致: 法人格表記を除去して一致（株式会社の有無等）
  3. 部分一致: 短い名前が長い名前に含まれる（例: 前田建設 ⊂ 前田建設工業株式会社）
  4. ドメイン一致: 会社URLのドメインが同じ

データソース:
  - 取引先テーブル: tblTfGScQIdLTYxA
    - 名前: 会社名（正式）、会社名（略称）
    - URL: 会社URL
    - 関連: 商談一覧（リンク）、連絡先一覧（リンク）
  - 連絡先テーブル: tblN53hFIQoo4W8j（取引先リンクで紐付き数カウント）
  - 商談テーブル: tbl1rM86nAw9l3bP（取引先リンクで紐付き数カウント）
  - 受注台帳テーブル: tbldLj2iMJYocct6（取引先テキストで紐付き数カウント）

出力:
  - docs/crm_dedup_report.md
  - data/crm_dedup_candidates.csv

Usage:
  python3 crm_dedup.py           # 重複検出レポート生成
  python3 crm_dedup.py --verbose # 詳細ログ付き
"""

import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from itertools import combinations

# ── 設定 ──
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DOCS_DIR = SCRIPT_DIR.parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)

_LOCAL_CONFIG = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
_SCRIPT_CONFIG = SCRIPT_DIR / "automation_config.json"
CONFIG_FILE = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _SCRIPT_CONFIG

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = os.environ.get("LARK_APP_ID") or CONFIG["lark"]["app_id"]
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET") or CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = os.environ.get("CRM_BASE_TOKEN") or CONFIG["lark"]["crm_base_token"]

# テーブルID
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_ORDERS = "tbldLj2iMJYocct6"

# 法人格パターン（正規化用）
CORP_PATTERNS = [
    r"株式会社", r"\(株\)", r"（株）", r"㈱",
    r"有限会社", r"\(有\)", r"（有）", r"㈲",
    r"合同会社", r"合資会社", r"合名会社",
    r"一般社団法人", r"一般財団法人",
    r"公益社団法人", r"公益財団法人",
    r"社会福祉法人", r"医療法人",
    r"特定非営利活動法人", r"NPO法人",
    r"独立行政法人",
]

# 部分一致の最小文字数（短すぎる名前は誤検出が多い）
MIN_PARTIAL_MATCH_LEN = 4

VERBOSE = "--verbose" in sys.argv


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def debug(msg):
    if VERBOSE:
        print(f"  [DEBUG] {msg}")


# ── Lark API ──
def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
        if "tenant_access_token" not in resp:
            print(f"[ERROR] トークン取得失敗: {resp}")
            sys.exit(1)
        return resp["tenant_access_token"]


def get_all_records(token, table_id):
    records = []
    page_token = None
    while True:
        url = (f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
               f"{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size=500")
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


# ── 正規化ロジック ──
def normalize_name(name):
    """取引先名を正規化（法人格除去・全角半角統一・空白除去）"""
    if not name:
        return ""
    s = name.strip()
    # 全角英数 → 半角
    s = s.translate(str.maketrans(
        'ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９',
        'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    ))
    # 法人格パターン除去
    for pat in CORP_PATTERNS:
        s = re.sub(pat, "", s)
    # 空白除去（全角半角とも）
    s = re.sub(r'[\s　]+', '', s)
    return s.lower()


def extract_domain(url_str):
    """URLからドメインを抽出"""
    if not url_str:
        return None
    s = str(url_str).strip().lower()
    m = re.search(r'(?:https?://)?(?:www\.)?([\w.-]+\.\w+)', s)
    if m:
        return m.group(1)
    return None


def get_account_name(fields):
    """取引先フィールドから会社名を取得"""
    # 会社名（正式）を優先
    name = fields.get("会社名（正式）")
    if name and isinstance(name, str) and name.strip():
        return name.strip()
    # 会社名（略称）
    name = fields.get("会社名（略称）")
    if name and isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def get_link_record_ids(field_value):
    """Larkリンクフィールドからrecord_idリストを取得"""
    if not field_value:
        return []
    if isinstance(field_value, list):
        ids = []
        for item in field_value:
            if isinstance(item, dict):
                rec_ids = item.get("record_ids")
                if rec_ids and isinstance(rec_ids, list):
                    ids.extend(rec_ids)
        return ids
    return []


def count_deals_contacts_from_account(fields):
    """取引先レコードのリンクフィールドから商談・連絡先数を取得"""
    deal_ids = get_link_record_ids(fields.get("商談一覧"))
    contact_ids = get_link_record_ids(fields.get("連絡先一覧"))
    return len(deal_ids), len(contact_ids)


def build_order_counts_by_account_name(orders, account_names_map):
    """受注台帳の取引先テキストフィールドから取引先record_idに紐付けてカウント"""
    # account_names_map: normalized_name -> [record_id, ...]
    counts = defaultdict(int)
    for rec in orders:
        fields = rec.get("fields", {})
        client = fields.get("取引先")
        if not client or not isinstance(client, str):
            continue
        norm = normalize_name(client)
        # 正規化名で取引先を探す
        if norm in account_names_map:
            for rid in account_names_map[norm]:
                counts[rid] += 1
    return counts


# ── 重複検出 ──
def detect_duplicates(accounts):
    """重複候補を検出"""
    duplicates = []
    seen_pairs = set()

    def add_pair(match_type, a, b, reason):
        pair_key = tuple(sorted([a["record_id"], b["record_id"]]))
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            duplicates.append((match_type, a, b, reason))

    # レコード情報の構築
    rec_infos = []
    name_map = defaultdict(list)  # normalized_name -> [rec_info]
    domain_map = defaultdict(list)  # domain -> [rec_info]

    for rec in accounts:
        fields = rec.get("fields", {})
        rec_id = rec.get("record_id", "")
        name = get_account_name(fields)
        short_name = fields.get("会社名（略称）", "")
        if isinstance(short_name, str):
            short_name = short_name.strip()
        else:
            short_name = ""

        normalized = normalize_name(name)
        if not normalized:
            continue

        # 商談・連絡先数
        deal_count, contact_count = count_deals_contacts_from_account(fields)

        rec_info = {
            "record_id": rec_id,
            "name": name,
            "short_name": short_name,
            "normalized": normalized,
            "normalized_short": normalize_name(short_name) if short_name else "",
            "fields": fields,
            "deal_count": deal_count,
            "contact_count": contact_count,
            "segment": fields.get("セグメント", ""),
            "status": fields.get("取引ステータス", ""),
            "revenue": fields.get("年間売上", ""),
            "prefecture": fields.get("都道府県", ""),
        }

        # ドメイン
        url = fields.get("会社URL")
        domain = extract_domain(url) if url else None
        rec_info["domain"] = domain

        rec_infos.append(rec_info)
        name_map[normalized].append(rec_info)
        if domain:
            domain_map[domain].append(rec_info)

    log(f"有効な取引先数: {len(rec_infos)} / 正規化名グループ数: {len(name_map)}")

    # 1. 完全一致 & 正規化一致（同じ正規化名のグループ内で比較）
    for nname, recs in name_map.items():
        if len(recs) >= 2:
            for a, b in combinations(recs, 2):
                if a["name"] == b["name"]:
                    add_pair("完全一致", a, b, f"取引先名が完全一致: 「{a['name']}」")
                else:
                    add_pair("正規化一致", a, b,
                             f"正規化後一致: 「{a['name']}」≈「{b['name']}」")

    # 2. 略称と正式名の照合（正規化名が異なるが略称で一致）
    # 略称マップを構築
    short_name_map = defaultdict(list)
    for ri in rec_infos:
        if ri["normalized_short"] and ri["normalized_short"] != ri["normalized"]:
            short_name_map[ri["normalized_short"]].append(ri)

    for nname, recs in name_map.items():
        if nname in short_name_map:
            for a in recs:
                for b in short_name_map[nname]:
                    if a["record_id"] != b["record_id"]:
                        add_pair("略称一致", a, b,
                                 f"正式名/略称一致: 「{a['name']}」≈「{b['short_name']}」")

    # 3. 部分一致（正規化名の包含関係）
    for i, a in enumerate(rec_infos):
        if len(a["normalized"]) < MIN_PARTIAL_MATCH_LEN:
            continue
        for b in rec_infos[i+1:]:
            if len(b["normalized"]) < MIN_PARTIAL_MATCH_LEN:
                continue
            pair_key = tuple(sorted([a["record_id"], b["record_id"]]))
            if pair_key in seen_pairs:
                continue
            short, long_ = (a, b) if len(a["normalized"]) <= len(b["normalized"]) else (b, a)
            # 短い方が長い方に含まれ、かつ短い方が一定以上の長さ
            if (len(short["normalized"]) >= MIN_PARTIAL_MATCH_LEN
                    and short["normalized"] in long_["normalized"]
                    and short["normalized"] != long_["normalized"]):
                # 一般的すぎる語を除外
                generic = {"建設", "工業", "商事", "電気", "工務店", "技研", "コンサルタント",
                           "エンジニアリング", "サービス", "テック", "システム"}
                if short["normalized"] not in generic:
                    add_pair("部分一致", a, b,
                             f"「{short['name']}」⊂「{long_['name']}」")

    # 4. ドメイン一致
    for domain, recs in domain_map.items():
        if len(recs) >= 2:
            for a, b in combinations(recs, 2):
                add_pair("ドメイン一致", a, b, f"会社URLドメイン一致: {domain}")

    return duplicates


# ── レポート生成 ──
def generate_report(duplicates, accounts, order_counts):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(accounts)

    type_counts = defaultdict(int)
    for match_type, _, _, _ in duplicates:
        type_counts[match_type] += 1

    lines = [
        f"# CRM取引先 重複検出レポート",
        f"",
        f"生成日時: {now}",
        f"",
        f"## サマリー",
        f"",
        f"| 項目 | 件数 |",
        f"|------|------|",
        f"| 取引先レコード総数 | {total} |",
        f"| 重複候補ペア数 | {len(duplicates)} |",
    ]
    for t in ["完全一致", "正規化一致", "略称一致", "部分一致", "ドメイン一致"]:
        if t in type_counts:
            lines.append(f"| - {t} | {type_counts[t]} |")

    affected_ids = set()
    for _, a, b, _ in duplicates:
        affected_ids.add(a["record_id"])
        affected_ids.add(b["record_id"])
    lines.append(f"| 重複に関与するレコード数 | {len(affected_ids)} |")
    lines.append("")

    if not duplicates:
        lines.append("重複候補は検出されませんでした。")
        return "\n".join(lines)

    lines.extend([
        "## 重複候補リスト",
        "",
        "統合推奨は、商談・連絡先・受注の紐付き数が多い方を「残す」としています。",
        "",
    ])

    priority = {"完全一致": 0, "正規化一致": 1, "略称一致": 2, "ドメイン一致": 3, "部分一致": 4}
    duplicates_sorted = sorted(duplicates, key=lambda x: priority.get(x[0], 9))

    for idx, (match_type, a, b, reason) in enumerate(duplicates_sorted, 1):
        a_orders = order_counts.get(a["record_id"], 0)
        b_orders = order_counts.get(b["record_id"], 0)

        # 統合推奨スコア
        a_score = a["deal_count"] * 3 + a["contact_count"] * 2 + a_orders * 5
        b_score = b["deal_count"] * 3 + b["contact_count"] * 2 + b_orders * 5
        # 同スコアならセグメントが上の方を残す
        seg_rank = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
        if a_score == b_score:
            a_score += seg_rank.get(a["segment"], 0)
            b_score += seg_rank.get(b["segment"], 0)

        lines.extend([
            f"### #{idx} [{match_type}] {reason}",
            f"",
            f"| | レコードA | レコードB |",
            f"|---|---|---|",
            f"| 取引先名（正式） | {a['name']} | {b['name']} |",
            f"| 取引先名（略称） | {a['short_name']} | {b['short_name']} |",
            f"| record_id | `{a['record_id']}` | `{b['record_id']}` |",
            f"| セグメント | {a['segment'] or '-'} | {b['segment'] or '-'} |",
            f"| 取引ステータス | {a['status'] or '-'} | {b['status'] or '-'} |",
            f"| 都道府県 | {a['prefecture'] or '-'} | {b['prefecture'] or '-'} |",
            f"| 年間売上 | {a['revenue'] or '-'} | {b['revenue'] or '-'} |",
            f"| 紐付き商談数 | {a['deal_count']} | {b['deal_count']} |",
            f"| 紐付き連絡先数 | {a['contact_count']} | {b['contact_count']} |",
            f"| 紐付き受注数 | {a_orders} | {b_orders} |",
            f"| **統合推奨** | {'残す' if a_score >= b_score else '統合元'} | {'残す' if b_score > a_score else '統合元'} |",
            f"",
        ])

    # 統合ルール案
    lines.extend([
        "## 統合ルール案",
        "",
        "### 基本方針",
        "1. 商談・受注が多い方を残す（データ損失リスク最小化）",
        "2. 統合元の商談・連絡先・受注の取引先リンクを残す側のrecord_idに更新",
        "3. 統合元の固有情報（備考・URL・電話番号等）は残す側にマージ",
        "4. 統合元レコードは即削除せず「重複（統合済み）」タグを付与（ロールバック可能に）",
        "",
        "### 統合手順",
        "1. 本レポートをユーザーが確認・承認",
        "2. 各ペアについて残す側を最終決定",
        "3. 連絡先テーブルの「取引先」リンクフィールドを更新",
        "4. 商談テーブルの「取引先」リンクフィールドを更新（record_idsがある場合）",
        "5. 受注台帳テーブルの「取引先」テキストフィールドを更新",
        "6. 残す側に統合元の固有情報をマージ",
        "7. 統合元にタグ付与",
        "",
        "### 注意事項",
        "- 本レポートは検出のみ。自動統合は行わない",
        "- 部分一致は誤検出の可能性あり（要目視確認）",
        "- 受注台帳の「取引先」はテキストフィールドのため、名前の表記揺れで紐付けが不完全な場合がある",
        "",
    ])

    return "\n".join(lines)


def generate_csv(duplicates, order_counts):
    csv_path = DATA_DIR / "crm_dedup_candidates.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "番号", "一致タイプ", "理由",
            "A_record_id", "A_正式名", "A_略称", "A_セグメント", "A_ステータス",
            "A_商談数", "A_連絡先数", "A_受注数",
            "B_record_id", "B_正式名", "B_略称", "B_セグメント", "B_ステータス",
            "B_商談数", "B_連絡先数", "B_受注数",
            "統合推奨（残す側）"
        ])
        for idx, (match_type, a, b, reason) in enumerate(duplicates, 1):
            a_orders = order_counts.get(a["record_id"], 0)
            b_orders = order_counts.get(b["record_id"], 0)
            a_score = a["deal_count"] * 3 + a["contact_count"] * 2 + a_orders * 5
            b_score = b["deal_count"] * 3 + b["contact_count"] * 2 + b_orders * 5
            keep = "A" if a_score >= b_score else "B"
            writer.writerow([
                idx, match_type, reason,
                a["record_id"], a["name"], a["short_name"], a["segment"], a["status"],
                a["deal_count"], a["contact_count"], a_orders,
                b["record_id"], b["name"], b["short_name"], b["segment"], b["status"],
                b["deal_count"], b["contact_count"], b_orders,
                keep
            ])
    return csv_path


# ── メイン ──
def main():
    log("CRM取引先 重複検出を開始")

    token = lark_get_token()
    log("Larkトークン取得完了")

    log("取引先テーブルを取得中...")
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    log(f"取引先レコード数: {len(accounts)}")

    if not accounts:
        log("[ERROR] 取引先レコードが0件です")
        sys.exit(1)

    # 受注台帳（テキスト紐付け用）
    log("受注台帳テーブルを取得中...")
    orders = get_all_records(token, TABLE_ORDERS)
    log(f"受注台帳レコード数: {len(orders)}")

    # 受注台帳の取引先名 → 取引先record_idマッピング構築
    account_names_map = defaultdict(list)  # normalized_name -> [record_id]
    for rec in accounts:
        fields = rec.get("fields", {})
        name = get_account_name(fields)
        norm = normalize_name(name)
        if norm:
            account_names_map[norm].append(rec["record_id"])
        # 略称も登録
        short = fields.get("会社名（略称）", "")
        if isinstance(short, str) and short.strip():
            norm_short = normalize_name(short)
            if norm_short and norm_short != norm:
                account_names_map[norm_short].append(rec["record_id"])

    order_counts = build_order_counts_by_account_name(orders, account_names_map)
    log(f"受注紐付きあり取引先数: {len(order_counts)}")

    # 重複検出
    log("重複候補を検出中...")
    duplicates = detect_duplicates(accounts)
    log(f"重複候補ペア数: {len(duplicates)}")

    # レポート生成
    report = generate_report(duplicates, accounts, order_counts)
    report_path = DOCS_DIR / "crm_dedup_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    log(f"レポート出力: {report_path}")

    # CSV出力
    csv_path = generate_csv(duplicates, order_counts)
    log(f"CSV出力: {csv_path}")

    # サマリー
    print("\n" + "=" * 60)
    print("重複検出結果サマリー")
    print("=" * 60)
    print(f"取引先総数: {len(accounts)}")
    print(f"重複候補ペア数: {len(duplicates)}")

    type_counts = defaultdict(int)
    for match_type, _, _, _ in duplicates:
        type_counts[match_type] += 1
    for t in ["完全一致", "正規化一致", "略称一致", "部分一致", "ドメイン一致"]:
        if t in type_counts:
            print(f"  - {t}: {type_counts[t]}ペア")

    if duplicates:
        priority = {"完全一致": 0, "正規化一致": 1, "略称一致": 2, "ドメイン一致": 3, "部分一致": 4}
        print(f"\n全件:")
        for match_type, a, b, reason in sorted(duplicates, key=lambda x: priority.get(x[0], 9)):
            print(f"  [{match_type}] {reason}")

    print(f"\nレポート: {report_path}")
    print(f"CSV: {csv_path}")


if __name__ == "__main__":
    main()
