#!/usr/bin/env python3
"""
受注台帳 業種別×サービス別 分類スクリプト
受注台帳を業種・サービス種別に自動分類し、CSVとクロス集計を出力

使用法:
  python3 order_classifier.py              # 分類+CSV出力のみ
  python3 order_classifier.py --writeback  # Lark Baseに書き戻し
  python3 order_classifier.py --all        # 支払通知含む全件表示
"""

import json
import csv
import re
import time
import urllib.request
from pathlib import Path
from datetime import datetime
from collections import defaultdict

CONFIG_FILE = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
OUTPUT_DIR = Path("/mnt/c/Users/USER/Documents/_data/tas-automation/data")

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
ORDER_TABLE_ID = "tbldLj2iMJYocct6"
COMPANY_TABLE_ID = "tblTfGScQIdLTYxA"

# ── 経理/非案件パターン（除外候補） ──
NON_CASE_PATTERNS = [
    r"支払通知書",
    r"支払明細書",
    r"支払明細",
    r"営業代行",
]

# ── 業種分類ルール（キーワードベース） ──
INDUSTRY_RULES = [
    ("ゼネコン", [
        "建設", "組", "工業", "工務", "土木", "JV", "ＪＶ",
        "鳶", "基礎", "舗装", "造園", "電工", "設備工",
        "鉄工", "管工", "塗装", "防水", "解体", "重機",
    ]),
    ("コンサルタント", [
        "コンサルタント", "コンサル", "設計", "技研",
        "地質", "エンジニア", "計画",
    ]),
    ("測量会社", [
        "測量", "工測",
    ]),
    ("不動産", [
        "不動産", "デベロッパー", "地所", "アセット",
        "プロパティ", "リアルティ", "リアル",
    ]),
    ("官公庁", [
        "市役所", "県庁", "国交省", "国土交通", "事務所",
        "整備局", "振興局", "管理所", "ダム", "河川",
        "港湾", "空港", "自治体", "公社", "公団",
        "水道局", "教育委員会", "農林",
    ]),
    ("メーカー", [
        "製作所", "製薬", "メーカー", "電機", "電器",
        "化学", "素材", "材料", "製造",
    ]),
    ("住宅・ハウスメーカー", [
        "ハウス", "住宅", "ホーム", "リフォーム",
    ]),
]

# ── サービス分類ルール ──
SERVICE_RULES = [
    ("土量計算", [
        "土量", "土工", "盛土", "切土", "残土", "掘削",
        "造成", "法面", "のり面", "埋立", "嵩上",
    ]),
    ("3Dモデリング", [
        "3D", "３Ｄ", "モデル", "点群", "レーザー",
        "スキャン", "BIM", "CIM", "オルソ",
        "SfM", "写真測量",
    ]),
    ("現況測量", [
        "現況", "地形", "横断", "縦断",
        "座標", "基準点", "水準",
    ]),
    ("点検", [
        "点検", "インフラ", "橋梁", "護岸",
        "堤防", "擁壁", "トンネル", "損傷", "クラック",
        "ひび割れ", "劣化",
    ]),
    ("眺望撮影", [
        "眺望", "パノラマ", "景観", "全景", "俯瞰",
    ]),
    ("空撮", [
        "空撮", "撮影", "ドローン撮影",
    ]),
    ("進捗管理", [
        "進捗", "定期", "出来形", "月次", "工程",
    ]),
    ("測量", [
        "測量",
    ]),
]


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


def lark_add_field(token, table_id, field_name, field_type=1):
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/fields"
    )
    data = json.dumps({"field_name": field_name, "type": field_type}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            if resp.get("code") == 0:
                fid = resp["data"]["field"]["field_id"]
                print(f"  フィールド追加成功: {field_name} -> {fid}")
                return fid
            else:
                print(f"  フィールド追加スキップ: {field_name} code={resp.get('code')} msg={resp.get('msg')}")
                return None
    except Exception as e:
        print(f"  フィールド追加エラー: {field_name} -> {e}")
        return None


def lark_get_fields(token, table_id):
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CRM_BASE_TOKEN}/tables/{table_id}/fields?page_size=100"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            resp = json.loads(r.read())
            return resp.get("data", {}).get("items", [])
    except Exception as e:
        print(f"フィールド取得エラー: {e}")
        return []


def lark_update_record(token, table_id, record_id, fields):
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
            return resp.get("code") == 0
    except:
        return False


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        texts = []
        for item in value:
            if isinstance(item, dict):
                texts.append(item.get("text", item.get("name", "")))
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(t for t in texts if t)
    if isinstance(value, dict):
        return value.get("text", value.get("name", ""))
    return ""


def is_non_case(case_name):
    """経理データ・非案件かどうか判定"""
    for pat in NON_CASE_PATTERNS:
        if re.search(pat, case_name):
            return True
    return False


def classify_industry(client_name, crm_industry=None):
    """業種を推定（CRM業種 > キーワード > 末尾パターン）"""
    # 1. CRM取引先テーブルの業種があればそれを正規化して使う
    if crm_industry:
        ind_str = crm_industry if isinstance(crm_industry, str) else str(crm_industry)
        # CRMの業種値をマッピング
        mapping = {
            "ゼネコン": "ゼネコン",
            "建設会社": "ゼネコン",
            "総合建設": "ゼネコン",
            "サブコン": "ゼネコン",
            "専門工事": "ゼネコン",
            "建設コンサル": "コンサルタント",
            "コンサル": "コンサルタント",
            "設計事務所": "コンサルタント",
            "測量会社": "測量会社",
            "不動産": "不動産",
            "デベロッパー": "不動産",
            "官公庁": "官公庁",
            "自治体": "官公庁",
            "メーカー": "メーカー",
            "住宅": "住宅・ハウスメーカー",
            "ハウスメーカー": "住宅・ハウスメーカー",
            "IT": "その他",
            "保育": "その他",
        }
        for key, val in mapping.items():
            if key in ind_str:
                return val

    # 2. 官公庁：末尾パターン
    if re.search(r'[都道府県市町村区]$', client_name.strip()):
        return "官公庁"
    # 学校・教育機関
    if re.search(r'(高等学校|中学校|小学校|大学|学園|高校)', client_name):
        return "官公庁"

    # 3. キーワード判定
    for industry, keywords in INDUSTRY_RULES:
        for kw in keywords:
            if kw in client_name:
                return industry

    return "その他"


def classify_service(case_name, client_name="", industry=""):
    """サービス種別を推定"""
    all_text = f"{case_name} {client_name}"

    for service, keywords in SERVICE_RULES:
        for kw in keywords:
            if kw in all_text:
                return service

    # 取引先名から推定（案件名にサービス内容がない場合）
    CLIENT_SERVICE_MAP = {
        # 撮影系の取引先
        "JUST": "空撮",
        "日本アート": "空撮",
        "写真通信": "空撮",
        "ジッピープロダクション": "空撮",
        "Nacasa": "空撮",
        "アクアクリエイティブ": "空撮",
        "マチスデザイン": "空撮",
        "オフィスリノン": "空撮",
        "アーバンプロジェクト": "空撮",
        "CCC": "空撮",
        # 点検系
        "イクシス": "点検",
        # 谷本ドローン（下請け撮影）
        "谷本ドローン": "空撮",
        # 工場空撮
        "大同マシナリー": "現場空撮",
        "トラスコ中山": "現場空撮",
        # その他推定可能
        "日本工営": "ドローン測量",
        "ユニファ": "空撮",
        "DNPグラフィカ": "空撮",
    }
    for key, svc in CLIENT_SERVICE_MAP.items():
        if key in client_name:
            return svc

    # 業種ベースのデフォルト推定
    INDUSTRY_DEFAULT_SERVICE = {
        "ゼネコン": "現場空撮",      # 建設現場の撮影・進捗
        "コンサルタント": "ドローン測量",
        "測量会社": "ドローン測量",
        "官公庁": "ドローン測量",
    }
    if industry in INDUSTRY_DEFAULT_SERVICE:
        return INDUSTRY_DEFAULT_SERVICE[industry]

    # 案件名のヒント
    if re.search(r'工場|プラント|センター|倉庫|物流', case_name):
        return "現場空撮"
    if re.search(r'河川|砂防|堤防|護岸', case_name):
        return "ドローン測量"
    if re.search(r'マンション|住宅|ハウス|店|モール|ららぽーと', case_name):
        return "現場空撮"
    if re.search(r'高速|道路|JV|ＪＶ', case_name):
        return "点検"

    return "その他"


def main():
    import sys
    writeback = "--writeback" in sys.argv
    show_all = "--all" in sys.argv

    print("=" * 60)
    print("受注台帳 業種別 x サービス別 分類")
    print(f"実行日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)

    token = lark_get_token()

    # 1. 取引先テーブル取得（業種データ活用）
    print("\n[1] 取引先テーブルを取得中...")
    companies = lark_list_records(token, COMPANY_TABLE_ID)

    # 取引先名 -> {業種, 正式名} のマップを構築
    company_industry = {}  # 名前(部分) -> 業種
    for c in companies:
        f = c.get("fields", {})
        full_name = extract_text(f.get("会社名（正式）", ""))
        short_name = extract_text(f.get("会社名（略称）", ""))
        industry_raw = f.get("業種", [])
        # 業種はsingle_select(type=4)配列
        if isinstance(industry_raw, list):
            ind = ", ".join(str(x) for x in industry_raw) if industry_raw else ""
        elif isinstance(industry_raw, str):
            ind = industry_raw
        else:
            ind = str(industry_raw) if industry_raw else ""

        for name in [full_name, short_name]:
            if name and name.strip():
                company_industry[name.strip()] = ind

    print(f"  取引先マスタ: {len(company_industry)}件（業種付き）")

    # 2. 受注台帳取得
    print("\n[2] 受注台帳を取得中...")
    records = lark_list_records(token, ORDER_TABLE_ID)
    print(f"  全レコード: {len(records)}件")

    if not records:
        print("ERROR: レコード取得失敗")
        return

    # 3. 分類実行
    print("\n[3] 分類実行中...")
    results = []
    skipped = 0

    for record in records:
        fields = record.get("fields", {})
        record_id = record.get("record_id", "")

        case_name = extract_text(fields.get("案件名", ""))
        client_name = extract_text(fields.get("取引先", ""))
        amount = fields.get("受注金額", 0) or 0
        if isinstance(amount, str):
            amount = float(amount.replace(",", "")) if amount else 0
        source = extract_text(fields.get("出典", ""))
        route = extract_text(fields.get("経路", ""))
        sales = extract_text(fields.get("担当営業", ""))

        # 非案件判定
        non_case = is_non_case(case_name)
        if non_case and not show_all:
            skipped += 1
            continue

        # 取引先マスタから業種を検索（部分一致）
        crm_industry = None
        for comp_name, ind in company_industry.items():
            if not ind:
                continue
            # 双方向部分一致
            if (client_name and comp_name and
                (client_name in comp_name or comp_name in client_name
                 or client_name.replace("株式会社", "").replace("　", "").strip()
                    in comp_name.replace("株式会社", "").replace("　", "").strip())):
                crm_industry = ind
                break

        # 分類
        industry = classify_industry(client_name, crm_industry)
        service = classify_service(case_name, client_name, industry)

        results.append({
            "record_id": record_id,
            "案件名": case_name,
            "取引先名": client_name,
            "受注金額": amount,
            "出典": source,
            "経路": route,
            "担当営業": sales,
            "業種": industry,
            "サービス種別": service,
            "CRM業種": crm_industry or "",
            "非案件": "Y" if non_case else "",
        })

    print(f"  分類対象: {len(results)}件（除外: {skipped}件）")

    # 4. CSV出力
    print("\n[4] CSV出力...")
    csv_path = OUTPUT_DIR / "order_classification.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "record_id", "案件名", "取引先名", "受注金額",
            "出典", "経路", "担当営業", "業種", "サービス種別",
            "CRM業種", "非案件"
        ])
        writer.writeheader()
        writer.writerows(results)
    print(f"  出力先: {csv_path}")

    # 5. クロス集計（案件のみ）
    case_results = [r for r in results if not r["非案件"]]
    print(f"\n{'=' * 70}")
    print(f"【クロス集計: 業種 x サービス種別】（案件{len(case_results)}件）")
    print("=" * 70)

    cross_count = defaultdict(lambda: defaultdict(int))
    cross_amount = defaultdict(lambda: defaultdict(float))
    industry_totals = defaultdict(int)
    service_totals = defaultdict(int)
    industry_amounts = defaultdict(float)
    service_amounts = defaultdict(float)

    for r in case_results:
        ind = r["業種"]
        svc = r["サービス種別"]
        amt = r["受注金額"] if isinstance(r["受注金額"], (int, float)) else 0
        cross_count[ind][svc] += 1
        cross_amount[ind][svc] += amt
        industry_totals[ind] += 1
        service_totals[svc] += 1
        industry_amounts[ind] += amt
        service_amounts[svc] += amt

    industries = sorted(industry_totals.keys(), key=lambda x: industry_totals[x], reverse=True)
    services = sorted(service_totals.keys(), key=lambda x: service_totals[x], reverse=True)

    # 件数テーブル
    col_w = max(10, max((len(s) * 2 + 2 for s in services), default=10))
    header_w = 20
    print(f"\n{'[件数]':s}")
    print(f"{'':>{header_w}s}", end="")
    for svc in services:
        print(f"{svc:>{col_w}s}", end="")
    print(f"{'合計':>{col_w}s}")
    print("-" * (header_w + col_w * (len(services) + 1)))

    for ind in industries:
        print(f"{ind:>{header_w}s}", end="")
        for svc in services:
            cnt = cross_count[ind][svc]
            print(f"{cnt:>{col_w}d}", end="")
        print(f"{industry_totals[ind]:>{col_w}d}")

    print("-" * (header_w + col_w * (len(services) + 1)))
    print(f"{'合計':>{header_w}s}", end="")
    for svc in services:
        print(f"{service_totals[svc]:>{col_w}d}", end="")
    print(f"{len(case_results):>{col_w}d}")

    # 金額テーブル
    print(f"\n\n{'[金額: 万円]':s}")
    print(f"{'':>{header_w}s}", end="")
    for svc in services:
        print(f"{svc:>{col_w}s}", end="")
    print(f"{'合計':>{col_w}s}")
    print("-" * (header_w + col_w * (len(services) + 1)))

    for ind in industries:
        print(f"{ind:>{header_w}s}", end="")
        for svc in services:
            amt = cross_amount[ind][svc] / 10000
            print(f"{amt:>{col_w}.0f}", end="")
        print(f"{industry_amounts[ind]/10000:>{col_w}.0f}")

    print("-" * (header_w + col_w * (len(services) + 1)))
    print(f"{'合計':>{header_w}s}", end="")
    for svc in services:
        print(f"{service_amounts[svc]/10000:>{col_w}.0f}", end="")
    total_amount = sum(industry_amounts.values())
    print(f"{total_amount/10000:>{col_w}.0f}")

    # 業種別TOP取引先
    print(f"\n\n【業種別 主要取引先】")
    industry_clients = defaultdict(lambda: defaultdict(int))
    industry_client_amounts = defaultdict(lambda: defaultdict(float))
    for r in case_results:
        if r["取引先名"]:
            industry_clients[r["業種"]][r["取引先名"]] += 1
            amt = r["受注金額"] if isinstance(r["受注金額"], (int, float)) else 0
            industry_client_amounts[r["業種"]][r["取引先名"]] += amt

    for ind in industries:
        clients = sorted(industry_clients[ind].items(), key=lambda x: x[1], reverse=True)
        top = clients[:5]
        print(f"\n  {ind} ({industry_totals[ind]}件 / {industry_amounts[ind]/10000:.0f}万円):")
        for name, cnt in top:
            amt = industry_client_amounts[ind][name] / 10000
            print(f"    {name}: {cnt}件 ({amt:.0f}万円)")

    # サービス別サマリー
    print(f"\n\n【サービス種別サマリー】")
    for svc in services:
        avg = service_amounts[svc] / service_totals[svc] / 10000 if service_totals[svc] else 0
        print(f"  {svc}: {service_totals[svc]}件 / {service_amounts[svc]/10000:.0f}万円 (平均{avg:.1f}万円)")

    # 6. Lark Baseへの書き戻し
    if writeback:
        print(f"\n\n[6] Lark Base書き戻し中...")

        existing_fields = lark_get_fields(token, ORDER_TABLE_ID)
        existing_names = {f["field_name"] for f in existing_fields}

        if "業種" not in existing_names:
            lark_add_field(token, ORDER_TABLE_ID, "業種", 1)
            time.sleep(0.5)
        if "サービス種別" not in existing_names:
            lark_add_field(token, ORDER_TABLE_ID, "サービス種別", 1)
            time.sleep(0.5)

        success = 0
        fail = 0
        for i, r in enumerate(results):
            ok = lark_update_record(token, ORDER_TABLE_ID, r["record_id"], {
                "業種": r["業種"],
                "サービス種別": r["サービス種別"],
            })
            if ok:
                success += 1
            else:
                fail += 1
            if (i + 1) % 50 == 0:
                print(f"    進捗: {i+1}/{len(results)}")
            time.sleep(0.15)

        print(f"  書き戻し完了: 成功{success}件 / 失敗{fail}件")
    else:
        print(f"\n\n* Lark Baseへの書き戻しは --writeback オプションで実行")

    print(f"\n{'=' * 70}")
    print(f"完了: {len(results)}件分類 -> {csv_path}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
