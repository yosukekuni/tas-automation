#!/usr/bin/env python3
"""
実績ページ自動更新スクリプト
受注台帳（Lark Base）の新規レコード → 導入事例ページ（WordPress）に自動追加

処理:
1. 受注台帳から「受注」ステータスのレコードを取得
2. 現在のWordPress実績ページのTSVと比較
3. 新規案件があればMapbox衛星画像を取得→WPメディアアップロード
4. TSVに行を追加→ページ更新
5. Lark Bot DMで通知
"""

import json
import re
import os
import time
import urllib.request
import urllib.parse
import base64
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "case_updater_state.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

# WordPress
WP_BASE = "https://tokaiair.com/wp-json/wp/v2"
WP_AUTH = base64.b64encode(
    f"{CONFIG['wordpress']['user']}:{CONFIG['wordpress']['app_password']}".encode()
).decode()

# Lark
LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
ORDER_TABLE_ID = "tbldLj2iMJYocct6"  # 受注台帳
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"   # 商談テーブル
OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# Mapbox
MAPBOX_TOKEN = CONFIG.get("mapbox", {}).get("token", "")

# WordPress 実績ページ
CASES_PAGE_ID = 4846


def lark_get_token():
    data = json.dumps({"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET}).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["tenant_access_token"]


def send_lark_dm(token, text):
    data = json.dumps({
        "receive_id": OWNER_OPEN_ID,
        "msg_type": "text",
        "content": json.dumps({"text": text})
    }).encode()
    req = urllib.request.Request(
        "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"  Lark DM error: {e}")


def lark_list_records(token, table_id, filter_expr=None, page_size=500):
    """Lark Baseからレコード一覧取得"""
    records = []
    page_token = None
    while True:
        url = f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            url += f"&page_token={page_token}"

        body = {}
        if filter_expr:
            body["filter"] = filter_expr

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body else None,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST" if body else "GET"
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


def get_current_cases_from_wp():
    """WordPress実績ページから現在のTSVデータを取得"""
    req = urllib.request.Request(
        f"{WP_BASE}/pages/{CASES_PAGE_ID}?context=edit",
        headers={"Authorization": f"Basic {WP_AUTH}"}
    )
    with urllib.request.urlopen(req) as r:
        page = json.loads(r.read())

    raw = page["content"]["raw"]
    m = re.search(r'<script id="cases-csv"[^>]*>\n?(.*?)\n?</script>', raw, re.DOTALL)
    if not m:
        return [], raw

    tsv = m.group(1).strip()
    lines = tsv.split('\n')
    headers = lines[0].split('\t')

    existing = []
    for line in lines[1:]:
        cols = line.split('\t')
        if cols and cols[0].strip():
            existing.append(cols[0].strip())

    return existing, raw


def geocode(query):
    """Nominatimで住所→緯度経度"""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        'q': query, 'format': 'json', 'limit': 1, 'countrycodes': 'jp'
    })
    req = urllib.request.Request(url, headers={'User-Agent': 'TAS-CaseUpdater/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            results = json.loads(r.read())
            if results:
                return float(results[0]['lat']), float(results[0]['lon'])
    except Exception as e:
        print(f"  Geocoding error: {e}")
    return None, None


def get_satellite_image(lat, lon, case_idx):
    """Mapbox衛星画像を取得してWordPressにアップロード"""
    url = f"https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon},{lat},16,0/400x300@2x?access_token={MAPBOX_TOKEN}"

    req = urllib.request.Request(url, headers={'User-Agent': 'TAS-CaseUpdater/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            img_data = r.read()
    except Exception as e:
        print(f"  Mapbox image fetch error: {e}")
        return ""

    # Upload to WordPress
    filename = f"tas-case-auto-{case_idx}.jpg"
    req = urllib.request.Request(
        f"{WP_BASE}/media",
        data=img_data,
        headers={
            'Authorization': f'Basic {WP_AUTH}',
            'Content-Type': 'image/jpeg',
            'Content-Disposition': f'attachment; filename="{filename}"',
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            return result.get('source_url', '')
    except Exception as e:
        print(f"  WP media upload error: {e}")
        return ""


def extract_case_info(record):
    """受注台帳レコードから実績情報を抽出"""
    fields = record.get("fields", {})

    # 現場名（案件名から取得）
    name = ""
    if isinstance(fields.get("案件名"), str):
        name = fields["案件名"]
    elif isinstance(fields.get("案件名"), list):
        for item in fields["案件名"]:
            if isinstance(item, dict):
                name = item.get("text", "")
            elif isinstance(item, str):
                name = item
            if name:
                break

    # 取引先名
    client = ""
    if isinstance(fields.get("取引先名"), str):
        client = fields["取引先名"]
    elif isinstance(fields.get("取引先名"), list):
        for item in fields["取引先名"]:
            if isinstance(item, dict):
                client = item.get("text", item.get("name", ""))
            elif isinstance(item, str):
                client = item
            if client:
                break

    # 出典（ステータス判定に使用）
    source = ""
    if isinstance(fields.get("出典"), str):
        source = fields["出典"]

    # 取引先（リンクフィールド）
    if not client:
        linked = fields.get("取引先", [])
        if isinstance(linked, list):
            for item in linked:
                if isinstance(item, dict):
                    client = item.get("text", item.get("name", ""))
                elif isinstance(item, str):
                    client = item
                if client:
                    break
        elif isinstance(linked, str):
            client = linked

    # 金額
    amount = fields.get("受注金額", 0) or 0

    return {
        "name": name.strip(),
        "client": client.strip(),
        "source": source,
        "amount": amount,
        "record_id": record.get("record_id", ""),
    }


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed_records": [], "last_run": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def main():
    import sys
    print("=== 実績ページ自動更新 ===")

    state = load_state()
    token = lark_get_token()

    # 1. 受注台帳から受注レコードを取得
    print("受注台帳を取得中...")
    records = lark_list_records(token, ORDER_TABLE_ID)
    print(f"  全レコード: {len(records)}件")

    # 受注ステータスのみ抽出
    won_records = []
    for r in records:
        info = extract_case_info(r)
        if "受注" in info["source"] and info["name"]:
            won_records.append(info)

    print(f"  受注レコード: {len(won_records)}件")

    # 2. 現在のWP実績ページのケース名を取得
    print("WordPress実績ページを取得中...")
    existing_names, page_raw = get_current_cases_from_wp()
    print(f"  既存ケース: {len(existing_names)}件")

    # 3. 新規案件を特定
    new_cases = []
    for info in won_records:
        # 名前の部分一致で既存チェック
        is_existing = False
        for existing in existing_names:
            if info["name"] in existing or existing in info["name"]:
                is_existing = True
                break

        if not is_existing and info["record_id"] not in state["processed_records"]:
            new_cases.append(info)

    if not new_cases:
        print("新規追加なし")
        state["last_run"] = datetime.now().isoformat()
        save_state(state)
        return

    print(f"\n新規追加: {len(new_cases)}件")
    for c in new_cases:
        print(f"  - {c['name']} ({c['client']})")

    if "--dry-run" in sys.argv:
        print("\n[dry-run] 実際の更新はスキップ")
        return

    # 4. 各新規案件の座標取得 + 衛星画像
    tsv_new_lines = []
    for i, case in enumerate(new_cases):
        print(f"\n処理中: {case['name']}")

        # Geocode
        lat, lon = geocode(case["name"])
        if lat is None:
            lat, lon = geocode(case["client"])

        coord_str = f"{lat}, {lon}" if lat else ""

        # Satellite image
        img_url = ""
        if lat and lon:
            img_url = get_satellite_image(lat, lon, f"{int(time.time())}-{i}")
            time.sleep(1)

        # 属性判定
        attr = ""
        client_lower = case["client"].lower()
        if any(k in client_lower for k in ["建設", "組", "工業", "工務"]):
            attr = "ゼネコン"
        elif any(k in client_lower for k in ["市", "県", "町", "村", "国土"]):
            attr = "官公庁"
        elif any(k in client_lower for k in ["製作所", "製薬", "メーカー"]):
            attr = "メーカー"

        # TSV行を構築（ヘッダー: 現場 緯度経度 元請・発注 属性 施設種類 施工内容 平米数 参考単価 参考額 画像URL）
        tsv_line = f"{case['name']}\t{coord_str}\t{case['client']}\t{attr}\t\t\t\t\t\t{img_url}"
        tsv_new_lines.append(tsv_line)

        state["processed_records"].append(case["record_id"])
        print(f"  → 座標: {coord_str or 'なし'}, 画像: {'あり' if img_url else 'なし'}")
        time.sleep(1.5)

    # 5. WordPressページ更新
    if tsv_new_lines:
        print(f"\nWordPressページ更新中...")

        # TSVの末尾（</script>の前）に新しい行を追加
        insert_point = page_raw.rfind("\n</script>")
        if insert_point == -1:
            print("ERROR: TSV挿入ポイントが見つかりません")
            return

        new_tsv_block = "\n".join(tsv_new_lines)
        new_raw = page_raw[:insert_point] + "\n" + new_tsv_block + page_raw[insert_point:]

        # WordPress更新
        data = json.dumps({"content": new_raw}).encode()
        req = urllib.request.Request(
            f"{WP_BASE}/pages/{CASES_PAGE_ID}",
            data=data,
            headers={"Authorization": f"Basic {WP_AUTH}", "Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                print(f"  更新完了: {result['modified']}")
        except Exception as e:
            print(f"  更新失敗: {e}")
            return

    # 6. 状態保存
    state["last_run"] = datetime.now().isoformat()
    save_state(state)

    # 7. Lark通知
    if "--notify" in sys.argv:
        msg = f"📋 実績ページ自動更新\n{len(new_cases)}件追加:\n"
        for c in new_cases:
            msg += f"  - {c['name']}（{c['client']}）\n"
        msg += f"\n合計: {len(existing_names) + len(new_cases)}件"
        send_lark_dm(token, msg)
        print("[Lark通知送信完了]")

    print(f"\n=== 完了: {len(new_cases)}件追加 ===")


if __name__ == "__main__":
    main()
