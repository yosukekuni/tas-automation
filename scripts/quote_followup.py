#!/usr/bin/env python3
"""
見積送付後フォローメール自動化
見積提出ステージの案件に対し、経過日数に応じた3段階フォローメールを自動生成・送信

Usage:
  python3 quote_followup.py --list       # 対象案件一覧のみ表示
  python3 quote_followup.py --dry-run    # メール生成（送信しない）
  python3 quote_followup.py --notify     # 國本さんにDMで対象一覧を通知
  python3 quote_followup.py --send       # フォローメールをLark IM経由で担当営業に送信

フォロー段階:
  3日後:  軽い確認（ご検討状況はいかがでしょうか）
  7日後:  価値提供（類似事例のご紹介）
  14日後: 最終フォロー（他社との比較検討のお手伝い）
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
STATE_FILE = SCRIPT_DIR / "quote_followup_state.json"
LOG_FILE = SCRIPT_DIR / "quote_followup.log"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]

# CRM table IDs
TABLE_DEALS = "tbl1rM86nAw9l3bP"
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"

# Lark IM
OWNER_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"  # 國本さん

# 営業担当 open_id（Lark IM送信先）
REP_OPEN_IDS = {
    "新美 光": "ou_189dc637b61a83b886d356becb3ae18e",
    "ユーザー550372": None,  # 政木: open_id未設定（設定後に追加）
}

REP_SIGNATURES = {
    "新美 光": {"display": "新美 光", "email": "niimi@tokaiair.com"},
    "ユーザー550372": {"display": "政木 勇治", "email": "y-masaki@riseasone.jp"},
}

COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "services": [
        "ドローン測量（公共測量対応・i-Construction）",
        "3次元点群計測・図面化",
        "建物赤外線調査（外壁タイル浮き等）",
        "眺望撮影・空撮",
        "太陽光パネル点検",
    ],
}

# フォロー段階定義
FOLLOWUP_STAGES = [
    {"day": 3, "key": "day3", "label": "3日後確認", "tone": "軽い確認"},
    {"day": 7, "key": "day7", "label": "7日後事例紹介", "tone": "価値提供"},
    {"day": 14, "key": "day14", "label": "14日後最終", "tone": "最終フォロー"},
]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


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


def send_lark_dm(token, text, open_id=None):
    """Lark Bot DMでテキスト送信。長文は分割送信。"""
    target = open_id or OWNER_OPEN_ID
    chunks = split_message(text, 3500)

    for chunk in chunks:
        data = json.dumps({
            "receive_id": target,
            "msg_type": "text",
            "content": json.dumps({"text": chunk})
        }).encode()
        req = urllib.request.Request(
            "https://open.larksuite.com/open-apis/im/v1/messages?receive_id_type=open_id",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req) as r:
                resp = json.loads(r.read())
                if resp.get("code") != 0:
                    log(f"  Lark DM error: {resp.get('msg', 'unknown')}")
                    return False
        except urllib.error.HTTPError as e:
            log(f"  Lark DM error: {e.code} {e.read().decode()}")
            return False
        if len(chunks) > 1:
            time.sleep(0.5)
    return True


def split_message(text, limit):
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line[:limit]
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def find_quote_targets(deals):
    """ステージ=「見積提出」の案件を抽出し、経過日数を計算"""
    targets = []
    now = datetime.now()

    for rec in deals:
        f = rec.get("fields", {})
        record_id = rec.get("record_id", "")

        # ステージチェック: 「見積提出」のみ
        stage = str(f.get("商談ステージ", "") or "")
        if stage != "見積提出":
            continue

        # 見積提出日の取得
        # まずフィールドから直接取得を試みる
        quote_date = None

        # 「見積提出日」フィールドがあれば使う
        for date_field in ["見積提出日", "見積日", "提出日"]:
            val = f.get(date_field)
            if val:
                if isinstance(val, (int, float)):
                    quote_date = datetime.fromtimestamp(val / 1000)
                elif isinstance(val, str):
                    try:
                        quote_date = datetime.strptime(val, "%Y-%m-%d")
                    except ValueError:
                        pass
                break

        # 日付フィールドがない場合、「最終更新日」や「更新日時」を使う
        if not quote_date:
            for fallback in ["最終更新日", "更新日時", "最終活動日"]:
                val = f.get(fallback)
                if val and isinstance(val, (int, float)):
                    quote_date = datetime.fromtimestamp(val / 1000)
                    break

        # それでもなければレコードの更新日時を使う
        if not quote_date:
            last_modified = rec.get("last_modified_time")
            if last_modified:
                quote_date = datetime.fromtimestamp(last_modified / 1000)

        if not quote_date:
            continue

        days_elapsed = (now - quote_date).days

        # 担当営業
        rep_field = f.get("担当営業", [])
        rep_name = ""
        if isinstance(rep_field, list):
            for p in rep_field:
                if isinstance(p, dict):
                    rep_name = p.get("name", "")
                elif isinstance(p, str):
                    rep_name = p
        elif isinstance(rep_field, str):
            rep_name = rep_field

        # 取引先リンク
        account_links = f.get("取引先", [])
        account_id = ""
        if isinstance(account_links, list):
            for link in account_links:
                if isinstance(link, dict):
                    account_id = link.get("record_id", "")
                elif isinstance(link, str):
                    account_id = link

        deal_name = str(f.get("商談名", "") or "(名前なし)")
        hearing = str(f.get("ヒアリング内容（まとめ）", "") or "")
        notes = str(f.get("備考", "") or "")
        category = str(f.get("客先カテゴリ", "") or "")
        product = str(f.get("商材", "") or "")
        temp = str(f.get("温度感スコア", "") or "")

        targets.append({
            "record_id": record_id,
            "deal_name": deal_name,
            "stage": stage,
            "temp": temp,
            "rep_name": rep_name,
            "quote_date": quote_date.strftime("%Y-%m-%d"),
            "days_elapsed": days_elapsed,
            "hearing": hearing,
            "notes": notes,
            "category": category,
            "product": product,
            "account_id": account_id,
            "fields": f,
        })

    return targets


def determine_followup_stage(days_elapsed, record_id, state):
    """経過日数から送るべきフォロー段階を判定。既送は除外。"""
    sent = state.get(record_id, {}).get("sent_stages", [])

    for fs in reversed(FOLLOWUP_STAGES):  # 14日→7日→3日の順にチェック
        if days_elapsed >= fs["day"] and fs["key"] not in sent:
            return fs
    return None


def find_account_name(accounts, account_id):
    for rec in accounts:
        if rec.get("record_id") == account_id:
            return str(rec.get("fields", {}).get("会社名", "") or "")
    return ""


def find_contact_for_account(contacts, account_name):
    if not account_name:
        return None
    for rec in contacts:
        f = rec.get("fields", {})
        company = str(f.get("会社名", "") or "")
        if account_name in company or (company and company in account_name):
            return {
                "name": str(f.get("氏名", "") or ""),
                "title": str(f.get("役職", "") or ""),
                "email": str(f.get("メールアドレス", "") or ""),
                "phone": str(f.get("電話番号", "") or ""),
                "company": company,
            }
        # 取引先リンクフィールドチェック
        account_link = f.get("取引先", "")
        if isinstance(account_link, list):
            for item in account_link:
                text_val = item.get("text_value", "") if isinstance(item, dict) else str(item)
                if account_name in text_val:
                    return {
                        "name": str(f.get("氏名", "") or ""),
                        "title": str(f.get("役職", "") or ""),
                        "email": str(f.get("メールアドレス", "") or ""),
                        "phone": str(f.get("電話番号", "") or ""),
                        "company": text_val or company,
                    }
    return None


def generate_followup_email(target, contact, stage):
    """Claude APIでフォロー段階に応じたメール生成"""
    rep_info = REP_SIGNATURES.get(target["rep_name"], {
        "display": target["rep_name"] or "営業担当",
        "email": "",
    })

    context_parts = [
        f"商談先: {contact.get('company', target['deal_name'])} {contact.get('name', '')} {contact.get('title', '')} 様",
        f"見積提出日: {target['quote_date']}（{target['days_elapsed']}日経過）",
    ]
    if target["temp"]:
        context_parts.append(f"温度感: {target['temp']}")
    if target["category"]:
        context_parts.append(f"業種: {target['category']}")
    if target["product"]:
        context_parts.append(f"関心商材: {target['product']}")
    if target["hearing"]:
        context_parts.append(f"ヒアリング内容:\n{target['hearing']}")
    if target["notes"]:
        context_parts.append(f"備考:\n{target['notes']}")

    context = "\n".join(context_parts)

    # 段階別プロンプト
    stage_prompts = {
        "day3": """【メール目的】見積送付後3日の軽い確認
- 「お見積りの内容についてご不明点はございませんか」程度の軽いトーン
- 押し売り感を出さない
- 質問があればいつでもどうぞ、という姿勢""",
        "day7": """【メール目的】見積送付後7日の価値提供
- 類似業種・類似案件での導入事例を紹介する形で価値を伝える
- ドローン測量のメリットを具体的な数値で示す（コスト削減、工期短縮等）
- 「ちなみに最近の事例では…」という自然な流れ""",
        "day14": """【メール目的】見積送付後14日の最終フォロー
- 他社との比較検討中であれば相談に乗る姿勢
- 見積条件の調整余地があることをさりげなく示唆
- 「今回は見送り」でも構わないという余裕感
- これが最後のフォローであることを暗に示す""",
    }

    prompt = f"""あなたは東海エアサービス株式会社の営業担当 {rep_info['display']} として、
見積送付後のフォローメールを作成してください。

【会社情報】
{COMPANY_INFO['name']}
サービス: {', '.join(COMPANY_INFO['services'])}
HP: {COMPANY_INFO['url']}

【商談コンテキスト】
{context}

{stage_prompts[stage['key']]}

【メール作成ルール】
1. 件名と本文を出力（件名は「件名：」で始める）
2. 相手の業種・関心に合わせた内容にする
3. 簡潔に（本文300文字以内）
4. 敬語は丁寧すぎず、ビジネスライクに
5. 社外秘情報は含めない

【出力形式】
件名：〇〇〇
---
（本文）
---
{COMPANY_INFO['name']}
{rep_info['display']}
"""

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": prompt}]
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            result = json.loads(r.read())
            text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    text += block["text"]
            return text
    except Exception as e:
        return f"[ERROR] Claude API failed: {e}"


def main():
    args = sys.argv[1:]
    mode_list = "--list" in args
    mode_dry = "--dry-run" in args
    mode_notify = "--notify" in args
    mode_send = "--send" in args

    if not any([mode_list, mode_dry, mode_notify, mode_send]):
        mode_dry = True  # デフォルトはドライラン

    log("見積送付後フォローメール自動化")
    log(f"  モード: {'一覧' if mode_list else '通知' if mode_notify else '送信' if mode_send else 'ドライラン'}")
    print()

    token = lark_get_token()

    # CRMデータ取得
    log("CRMデータ取得中...")
    deals = get_all_records(token, TABLE_DEALS)
    contacts = get_all_records(token, TABLE_CONTACTS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)
    log(f"  商談: {len(deals)}件 / 連絡先: {len(contacts)}件 / 取引先: {len(accounts)}件")

    # 見積提出案件を抽出
    targets = find_quote_targets(deals)
    log(f"  見積提出ステージ: {len(targets)}件")

    if not targets:
        log("見積提出ステージの案件なし。終了。")
        # 対象なし時はLark DM送信しない（ノイズ削減）
        return

    # 状態ファイル読み込み
    state = load_state()

    # フォロー対象の判定
    followup_actions = []
    for t in targets:
        fs = determine_followup_stage(t["days_elapsed"], t["record_id"], state)
        if fs:
            # 取引先名取得
            account_name = ""
            if t["account_id"]:
                account_name = find_account_name(accounts, t["account_id"])

            # 連絡先検索
            search_name = account_name or t["deal_name"]
            contact = find_contact_for_account(contacts, search_name)
            if not contact:
                # deal_nameから推測
                for rec in contacts:
                    cf = rec.get("fields", {})
                    company = str(cf.get("会社名", "") or "")
                    if company and company in t["deal_name"]:
                        contact = {
                            "name": str(cf.get("氏名", "") or ""),
                            "title": str(cf.get("役職", "") or ""),
                            "email": str(cf.get("メールアドレス", "") or ""),
                            "phone": str(cf.get("電話番号", "") or ""),
                            "company": company,
                        }
                        break
            if not contact:
                contact = {
                    "name": "", "title": "ご担当者", "email": "",
                    "phone": "", "company": search_name or t["deal_name"],
                }

            followup_actions.append({
                "target": t,
                "stage": fs,
                "contact": contact,
                "account_name": account_name,
            })

    # 一覧表示
    print(f"\nフォロー対象: {len(followup_actions)}件（全見積提出: {len(targets)}件）")
    print("─" * 60)

    for fa in followup_actions:
        t = fa["target"]
        fs = fa["stage"]
        rep_display = REP_SIGNATURES.get(t["rep_name"], {}).get("display", t["rep_name"])
        temp_mark = f" [{t['temp']}]" if t["temp"] else ""
        print(f"  {t['deal_name']}{temp_mark}")
        print(f"    担当: {rep_display} / 見積提出: {t['quote_date']}（{t['days_elapsed']}日経過）")
        print(f"    フォロー: {fs['label']}（{fs['tone']}）")
        print(f"    連絡先: {fa['contact'].get('company', '')} {fa['contact'].get('name', '')} <{fa['contact'].get('email', 'メールなし')}>")
        print()

    if not followup_actions:
        log("フォロー送信が必要な案件なし（全て送信済みまたは期間外）")
        # 対象なし時はLark DM送信しない（ノイズ削減）
        return

    if mode_list:
        return

    # --notify: 國本さんにDMで一覧を送信
    if mode_notify:
        msg = "見積フォロー対象一覧\n\n"
        for fa in followup_actions:
            t = fa["target"]
            fs = fa["stage"]
            rep_display = REP_SIGNATURES.get(t["rep_name"], {}).get("display", t["rep_name"])
            msg += f"- {t['deal_name']}（{t['days_elapsed']}日経過）\n"
            msg += f"  {fs['label']} / 担当: {rep_display}\n"
            msg += f"  連絡先: {fa['contact'].get('name', '')} <{fa['contact'].get('email', 'なし')}>\n\n"
        msg += f"合計: {len(followup_actions)}件"
        send_lark_dm(token, msg)
        log("國本さんにDM送信完了")

        if not mode_send and not mode_dry:
            return

    # メール生成 & 送信
    generated = []
    for fa in followup_actions:
        t = fa["target"]
        fs = fa["stage"]
        contact = fa["contact"]

        print(f"\n{'='*60}")
        log(f"メール生成中: {t['deal_name']}（{fs['label']}）")

        email_text = generate_followup_email(t, contact, fs)
        print(f"\n{email_text}")

        generated.append({
            "record_id": t["record_id"],
            "deal_name": t["deal_name"],
            "stage_key": fs["key"],
            "stage_label": fs["label"],
            "contact_email": contact.get("email", ""),
            "rep_name": t["rep_name"],
            "email_text": email_text,
        })

        if mode_send:
            # 担当営業のopen_idがあればDMで送信、なければ國本さんに送信
            rep_open_id = REP_OPEN_IDS.get(t["rep_name"])
            dm_target = rep_open_id or OWNER_OPEN_ID
            dm_label = REP_SIGNATURES.get(t["rep_name"], {}).get("display", t["rep_name"]) if rep_open_id else "國本さん（担当open_id未設定）"

            dm_text = f"[見積フォロー] {t['deal_name']}（{fs['label']}）\n"
            dm_text += f"宛先: {contact.get('company', '')} {contact.get('name', '')} <{contact.get('email', 'なし')}>\n"
            dm_text += f"{'─'*40}\n"
            dm_text += email_text

            log(f"  Lark DM送信先: {dm_label}")
            success = send_lark_dm(token, dm_text, dm_target)
            if success:
                log("  DM送信完了")
                # 状態更新
                if t["record_id"] not in state:
                    state[t["record_id"]] = {"deal_name": t["deal_name"], "sent_stages": []}
                state[t["record_id"]]["sent_stages"].append(fs["key"])
                state[t["record_id"]][f"{fs['key']}_sent_at"] = datetime.now().isoformat()
                save_state(state)
            else:
                log("  DM送信失敗")

        elif mode_dry:
            # ドライランでも状態は更新しない
            log("  (ドライラン: 送信スキップ)")

        time.sleep(1)  # API rate limit

    # サマリー
    print(f"\n{'='*60}")
    summary = f"見積フォロー自動生成完了\n\n"
    summary += f"対象: {len(generated)}件\n"
    for g in generated:
        rep_display = REP_SIGNATURES.get(g["rep_name"], {}).get("display", g["rep_name"])
        summary += f"  - {g['deal_name']}（{g['stage_label']}） → {rep_display}\n"
    print(summary)

    # ログ保存
    with open(LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(f"\n[{datetime.now().isoformat()}] Generated {len(generated)} quote followup emails\n")
        for g in generated:
            lf.write(f"  {g['deal_name']} ({g['stage_label']}) → {g['contact_email']}\n")


if __name__ == "__main__":
    main()
