#!/usr/bin/env python3
"""
Lark Bot コマンド実行スクリプト
携帯のLark DMから受信したメッセージをClaude APIで解釈・実行し、結果をLark DMで返信。

環境変数:
  LARK_COMMAND_MESSAGE    受信メッセージ本文
  LARK_COMMAND_SENDER     送信者 open_id
  LARK_COMMAND_MESSAGE_ID メッセージID

Usage:
  python3 lark_command_executor.py
"""

import json
import os
import subprocess
import sys
import time
import traceback
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Config ──
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

LARK_APP_ID = CONFIG["lark"]["app_id"]
LARK_APP_SECRET = CONFIG["lark"]["app_secret"]
CRM_BASE_TOKEN = CONFIG["lark"]["crm_base_token"]
CLAUDE_API_KEY = CONFIG["anthropic"]["api_key"]

# 國本さんの open_id
OWNER_OPEN_ID = os.environ.get("LARK_COMMAND_SENDER", "ou_d2e2e520a442224ea9d987c6186341ce")
MESSAGE = os.environ.get("LARK_COMMAND_MESSAGE", "").strip()
MESSAGE_ID = os.environ.get("LARK_COMMAND_MESSAGE_ID", "")

# Lark DM 文字制限
MAX_DM_LENGTH = 2000

# 利用可能なスクリプト
AVAILABLE_SCRIPTS = {
    "lark_crm_monitor.py": "CRM監視・品質チェック（--quality で品質レポート）",
    "weekly_sales_kpi.py": "週次営業KPIレポート生成",
    "auto_followup_email.py": "フォローメール生成（--list で対象一覧）",
    "ga4_analytics.py": "GA4/GSCデータ取得・分析",
    "site_health_audit.py": "サイトヘルスチェック",
    "bid_scanner.py": "入札情報スキャン",
    "lead_nurturing.py": "リードナーチャリング実行",
    "auto_case_updater.py": "実績ページ自動更新",
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


def send_lark_dm(token, text, open_id=None):
    """Lark Bot DMでテキスト送信。長文は分割送信。"""
    target = open_id or OWNER_OPEN_ID
    chunks = split_message(text, MAX_DM_LENGTH)

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
            urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            print(f"Lark DM error: {e.code} {e.read().decode()}")
        if len(chunks) > 1:
            time.sleep(0.5)


def split_message(text, limit):
    """テキストをlimit文字以下のチャンクに分割。行単位で分割。"""
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line[:limit]  # 1行がlimit超える場合は切り詰め
        else:
            current = current + "\n" + line if current else line
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


# ── CRM サマリ取得 ──
def get_crm_summary(token):
    """商談テーブルのステージ別サマリを返す。"""
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/{CRM_BASE_TOKEN}"
        f"/tables/tbl1rM86nAw9l3bP/records?page_size=500"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
    except Exception as e:
        return f"CRMデータ取得エラー: {e}"

    records = result.get("data", {}).get("items", [])
    total = len(records)

    # ステージ別集計
    stage_counts = {}
    temp_counts = {}
    no_stage = 0
    no_action = 0

    for rec in records:
        fields = rec.get("fields", {})
        stage = fields.get("ステージ")
        if isinstance(stage, list):
            stage = stage[0] if stage else None

        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        else:
            no_stage += 1

        temp = fields.get("温度感スコア")
        if isinstance(temp, list):
            temp = temp[0] if temp else None
        if temp:
            temp_counts[temp] = temp_counts.get(temp, 0) + 1

        action = fields.get("次アクション")
        if not action:
            no_action += 1

    lines = [f"商談サマリ ({datetime.now().strftime('%Y-%m-%d %H:%M')})", f"総件数: {total}件", ""]
    lines.append("【ステージ別】")
    for s, c in sorted(stage_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {s}: {c}件")
    lines.append(f"  未設定: {no_stage}件")
    lines.append("")
    lines.append("【温度感別】")
    for t, c in sorted(temp_counts.items(), key=lambda x: -x[1]):
        lines.append(f"  {t}: {c}件")
    lines.append("")
    lines.append(f"次アクション未設定: {no_action}件")

    return "\n".join(lines)


# ── サイトチェック ──
def check_site_health():
    """主要ページのステータスコード確認。"""
    pages = [
        ("トップ", "https://www.tokaiair.com/"),
        ("サービス", "https://www.tokaiair.com/services/"),
        ("お問い合わせ", "https://www.tokaiair.com/contact/"),
        ("実績", "https://www.tokaiair.com/case-library/cases/"),
        ("コラム", "https://www.tokaiair.com/column/"),
        ("採用", "https://www.tokaiair.com/recruit/"),
        ("FAQ", "https://www.tokaiair.com/faq/"),
        ("会社情報", "https://www.tokaiair.com/company/"),
    ]
    results = []
    all_ok = True
    for name, url in pages:
        try:
            req = urllib.request.Request(url, method="HEAD")
            req.add_header("User-Agent", "TAS-HealthCheck/1.0")
            with urllib.request.urlopen(req, timeout=10) as r:
                code = r.getcode()
                status = "OK" if code == 200 else f"WARNING({code})"
                if code != 200:
                    all_ok = False
        except Exception as e:
            status = f"ERROR({e})"
            all_ok = False
        results.append(f"  {name}: {status}")

    header = "サイトヘルスチェック" + (" - 全ページ正常" if all_ok else " - 異常あり")
    return header + "\n" + "\n".join(results)


# ── スクリプト実行 ──
def run_script(script_name, args=None):
    """指定スクリプトを実行して出力を返す。"""
    script_path = SCRIPT_DIR / script_name
    if not script_path.exists():
        return f"エラー: {script_name} が見つかりません"

    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=480,  # 8分タイムアウト
            cwd=str(SCRIPT_DIR),
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[stderr]\n{result.stderr}" if result.stderr else ""
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(出力なし)"
    except subprocess.TimeoutExpired:
        return f"エラー: {script_name} がタイムアウトしました（8分）"
    except Exception as e:
        return f"エラー: {script_name} 実行失敗 - {e}"


# ── キーワードマッチ（無料） ──
def keyword_match(msg):
    """定型コマンドはClaude APIを使わずキーワードで直接マッチ。"""
    m = msg.lower().strip()
    # CRM系
    if any(k in m for k in ["crm", "商談", "ステージ", "パイプライン"]):
        return {"action": "crm_summary"}
    # サイトチェック
    if any(k in m for k in ["サイトチェック", "サイト確認", "サイト大丈夫", "site"]):
        return {"action": "site_check"}
    # 検証
    if any(k in m for k in ["検証", "verify", "チェックバック"]):
        return {"action": "run_script", "script": "verify_tasks.py", "args": []}
    # KPI
    if any(k in m for k in ["kpi", "営業数字", "週次", "売上"]):
        return {"action": "run_script", "script": "weekly_sales_kpi.py", "args": []}
    # 入札
    if any(k in m for k in ["入札", "bid"]):
        return {"action": "run_script", "script": "bid_scanner.py", "args": []}
    # GA4
    if any(k in m for k in ["ga4", "アクセス", "pv", "流入"]):
        return {"action": "run_script", "script": "ga4_analytics.py", "args": []}
    # フォロー
    if any(k in m for k in ["フォロー対象", "フォローメール", "followup"]):
        return {"action": "run_script", "script": "auto_followup_email.py", "args": ["--list"]}
    # 品質
    if any(k in m for k in ["品質", "データ品質", "quality"]):
        return {"action": "run_script", "script": "lark_crm_monitor.py", "args": ["--quality"]}
    # 実績更新
    if any(k in m for k in ["実績更新", "ケース更新", "case update"]):
        return {"action": "run_script", "script": "auto_case_updater.py", "args": ["--dry-run"]}
    # マッチなし → Claude APIに委譲
    return None


# ── Claude API でコマンド解釈 ──
def interpret_with_claude(message):
    """
    Claude APIでメッセージを解釈し、実行すべきアクションを返す。
    戻り値: {"action": "...", "script": "...", "args": [...], "response": "..."}
    """
    system_prompt = """あなたは東海エアサービスの業務自動化アシスタントです。
ユーザーからの指示を解釈し、実行すべきアクションをJSON形式で返してください。

利用可能なアクション:
1. {"action": "crm_summary"} - CRM状況・商談サマリを表示
2. {"action": "site_check"} - サイトヘルスチェック
3. {"action": "run_script", "script": "<script_name>", "args": ["--flag"]} - スクリプト実行
4. {"action": "direct_response", "response": "回答テキスト"} - 直接回答（情報提供・質問への回答）

利用可能なスクリプト:
- lark_crm_monitor.py (--quality: 品質チェック, --init: 初期化)
- weekly_sales_kpi.py (週次KPIレポート)
- auto_followup_email.py (--list: 対象一覧, --send: 送信)
- ga4_analytics.py (GA4/GSC分析)
- site_health_audit.py (詳細サイト監査)
- bid_scanner.py (入札情報スキャン)
- lead_nurturing.py (リードナーチャリング)
- auto_case_updater.py (実績ページ更新)

マッピング例:
- 「CRM状況」「商談どうなってる」→ crm_summary
- 「サイトチェック」「サイト大丈夫？」→ site_check
- 「入札」「入札情報」→ run_script bid_scanner.py
- 「KPI」「営業数字」→ run_script weekly_sales_kpi.py
- 「品質チェック」「データ品質」→ run_script lark_crm_monitor.py --quality
- 「フォロー対象」→ run_script auto_followup_email.py --list
- 「GA4」「アクセス状況」→ run_script ga4_analytics.py
- 「ナーチャリング」→ run_script lead_nurturing.py
- 判断つかない場合 → direct_response で何ができるか案内

JSONのみ返してください。説明は不要です。"""

    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 500,
        "system": system_prompt,
        "messages": [{"role": "user", "content": message}],
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
        content = result["content"][0]["text"].strip()
        # JSONブロックを抽出
        if "```" in content:
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        return json.loads(content)
    except Exception as e:
        print(f"Claude API error: {e}")
        return {"action": "direct_response", "response": f"Claude APIエラー: {e}"}


# ── メイン処理 ──
def main():
    if not MESSAGE:
        print("No message received")
        return

    print(f"Received command: {MESSAGE}")
    print(f"Sender: {OWNER_OPEN_ID}")
    print(f"Timestamp: {datetime.now().isoformat()}")

    token = lark_get_token()

    try:
        # キーワードマッチ（Claude API不要・無料）
        action = keyword_match(MESSAGE)
        if action is None:
            # マッチしない場合のみClaude APIで解釈
            action = interpret_with_claude(MESSAGE)
        print(f"Interpreted action: {json.dumps(action, ensure_ascii=False)}")

        result_text = ""

        if action["action"] == "crm_summary":
            result_text = get_crm_summary(token)

        elif action["action"] == "site_check":
            result_text = check_site_health()

        elif action["action"] == "run_script":
            script = action.get("script", "")
            args = action.get("args", [])
            if script not in AVAILABLE_SCRIPTS:
                result_text = f"不明なスクリプト: {script}\n利用可能: {', '.join(AVAILABLE_SCRIPTS.keys())}"
            else:
                result_text = f"実行中: {script} {' '.join(args)}\n\n"
                result_text += run_script(script, args)

        elif action["action"] == "direct_response":
            result_text = action.get("response", "処理完了")

        else:
            result_text = f"不明なアクション: {action}"

        # 結果が長すぎる場合はClaude APIで要約
        if len(result_text) > MAX_DM_LENGTH * 3:
            result_text = summarize_with_claude(result_text)

        # 結果をLark DMで返信
        send_lark_dm(token, result_text)
        print(f"Result sent ({len(result_text)} chars)")

    except Exception as e:
        error_msg = f"コマンド実行エラー:\n{traceback.format_exc()}"
        print(error_msg)
        send_lark_dm(token, f"エラーが発生しました:\n{str(e)[:500]}")


def summarize_with_claude(text):
    """長い結果をClaude APIで要約する。"""
    data = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1500,
        "system": "以下のレポート出力を2000文字以内に要約してください。重要な数値・エラー・アクション項目を優先的に残してください。",
        "messages": [{"role": "user", "content": text[:10000]}],
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
        return result["content"][0]["text"].strip()
    except Exception:
        # 要約失敗時は先頭を切り詰め
        return text[:MAX_DM_LENGTH - 50] + "\n\n...(以下省略)"


if __name__ == "__main__":
    main()
