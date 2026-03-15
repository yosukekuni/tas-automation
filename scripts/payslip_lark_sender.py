#!/usr/bin/env python3
"""
給与明細 Lark Bot DM送信スクリプト

給与計算テーブル（ステータス=確定）のレコードを取得し、
Lark Interactive Card形式で給与明細を送信する。

フロー:
  1. 給与計算テーブルからステータス=確定のレコードを取得
  2. 國本にプレビューDM送信（確認用）
  3. --send 指定時: 対象者に給与明細カードを送信
  4. ステータスを「送信済み」に更新

使い方:
  python3 payslip_lark_sender.py --month 2602              # プレビューのみ（國本に確認DM）
  python3 payslip_lark_sender.py --month 2602 --send       # 対象者に送信
  python3 payslip_lark_sender.py --month 2602 --dry-run    # コンソール出力のみ
"""

import json
import os
import sys
import urllib.request
import urllib.error
import time
from pathlib import Path
from datetime import datetime

# Google Sheets（オプショナル）
try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    HAS_GSPREAD = True
except ImportError:
    HAS_GSPREAD = False

# ==================== 設定 ====================
SCRIPT_DIR = Path(__file__).parent
LARK_API_BASE = "https://open.larksuite.com/open-apis"
CRM_BASE_TOKEN = "BodWbgw6DaHP8FspBTYjT8qSpOe"
TABLE_PAYROLL = "tbllGwzN1GWwdd4L"

# 送信先マッピング
RECIPIENTS = {
    "新美光": {
        "open_id": "ou_189dc637b61a83b886d356becb3ae18e",
        "display_name": "新美 光",
    },
}

# 國本のopen_id（確認DM送信先）
KUNIMOTO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

API_MAX_RETRIES = 3
API_RETRY_DELAY = 5

# Google Sheets設定
GOOGLE_SA_KEY_PATHS = [
    Path("/mnt/c/Users/USER/Documents/_data/drive-organizer-489313-9230cf87e259.json"),
    Path("/tmp/google_sa.json"),
]
SPREADSHEET_ID = "1dJ2Yx2heeRU9gUnrAv3jrO00zrjxmt6Fo2CaaKnwI_w"

# Lark Drive設定
LARK_DRIVE_PAYROLL_FOLDER = ""  # Lark Drive フォルダトークン（未設定時はスキップ）


# ==================== Config ====================
def load_config():
    for p in [
        Path("/mnt/c/Users/USER/Documents/_data/automation_config.json"),
        SCRIPT_DIR / "automation_config.json",
    ]:
        if p.exists():
            with open(p) as f:
                cfg = json.load(f)
            if not str(cfg.get("lark", {}).get("app_id", "")).startswith("${"):
                return cfg
    return {
        "lark": {
            "app_id": os.environ.get("LARK_APP_ID", ""),
            "app_secret": os.environ.get("LARK_APP_SECRET", ""),
        }
    }


# ==================== Lark API ====================
def lark_api_request(url, method="GET", data=None, token=None, retries=API_MAX_RETRIES):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    encoded_data = json.dumps(data).encode() if data else None

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=encoded_data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                result = json.loads(r.read())
                if result.get("code", 0) != 0:
                    msg = result.get("msg", "unknown error")
                    print(f"  API error (code={result.get('code')}): {msg}")
                    if attempt < retries - 1:
                        time.sleep(API_RETRY_DELAY)
                        continue
                return result
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"  API request failed (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(API_RETRY_DELAY)
            else:
                raise
    return None


def lark_get_token(config):
    result = lark_api_request(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": config["lark"]["app_id"], "app_secret": config["lark"]["app_secret"]},
    )
    return result["tenant_access_token"]


def lark_send_card(token, open_id, card_content):
    """Lark Bot DMでInteractive Cardを送信"""
    data = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card_content, ensure_ascii=False),
    }
    result = lark_api_request(
        f"{LARK_API_BASE}/im/v1/messages?receive_id_type=open_id",
        method="POST",
        data=data,
        token=token,
    )
    if result and result.get("code") == 0:
        print(f"  Card sent to {open_id}")
        return True
    else:
        print(f"  Card send failed: {result}")
        return False


def lark_send_text(token, open_id, text):
    """Lark Bot DMでテキストメッセージを送信"""
    data = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }
    result = lark_api_request(
        f"{LARK_API_BASE}/im/v1/messages?receive_id_type=open_id",
        method="POST",
        data=data,
        token=token,
    )
    if result and result.get("code") == 0:
        print(f"  Text sent to {open_id}")
        return True
    return False


# ==================== 給与計算テーブル取得 ====================
def fetch_payroll_records(token, month):
    """給与計算テーブルからステータス=確定のレコードを取得"""
    search_body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "対象月", "operator": "is", "value": [month]},
                {"field_name": "ステータス", "operator": "is", "value": ["確定"]},
            ],
        },
        "page_size": 100,
    }

    result = lark_api_request(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/records/search?user_id_type=open_id",
        method="POST",
        data=search_body,
        token=token,
    )

    if not result or result.get("code") != 0:
        print(f"  Failed to fetch payroll records")
        return []

    return result.get("data", {}).get("items", [])


def fetch_payroll_records_by_status(token, month, status):
    """給与計算テーブルから指定ステータスのレコードを取得"""
    search_body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "対象月", "operator": "is", "value": [month]},
                {"field_name": "ステータス", "operator": "is", "value": [status]},
            ],
        },
        "page_size": 100,
    }
    result = lark_api_request(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/records/search?user_id_type=open_id",
        method="POST",
        data=search_body,
        token=token,
    )
    if not result or result.get("code") != 0:
        return []
    return result.get("data", {}).get("items", [])


def update_status(token, record_id, new_status):
    """ステータスを更新"""
    data = {"fields": {"ステータス": new_status}}
    result = lark_api_request(
        f"{LARK_API_BASE}/bitable/v1/apps/{CRM_BASE_TOKEN}/tables/{TABLE_PAYROLL}/records/{record_id}",
        method="PUT",
        data=data,
        token=token,
    )
    if result and result.get("code") == 0:
        print(f"  Status updated to '{new_status}' for {record_id}")
        return True
    return False


# ==================== カード生成 ====================
def _extract_text(val):
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, list):
        return ", ".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in val
        )
    if isinstance(val, dict):
        return val.get("text", "") or val.get("name", "")
    return str(val) if val is not None else ""


def _num(val):
    """数値フィールドからintを取得"""
    if val is None:
        return 0
    try:
        return int(float(str(val)))
    except (ValueError, TypeError):
        return 0


def build_payslip_card(fields, month):
    """給与明細のInteractive Cardを生成"""
    target = _extract_text(fields.get("対象者", ""))
    year = 2000 + int(month[:2])
    mon = int(month[2:])
    period = f"{year}年{mon}月分"

    full_days = _num(fields.get("フル出勤日数"))
    half_days = _num(fields.get("半日出勤日数"))
    solo_days = _num(fields.get("単独撮影日数"))
    multi_days = _num(fields.get("複数現場加算日数"))
    point_cloud = _num(fields.get("点群処理箇所数"))

    genba = _num(fields.get("基本報酬_現場"))
    naigyo = _num(fields.get("基本報酬_内業"))
    vehicle = _num(fields.get("車両手当"))

    gas_km = _num(fields.get("ガソリン距離km"))
    gas_cost = _num(fields.get("ガソリン代"))
    highway = _num(fields.get("高速代"))
    parking = _num(fields.get("駐車場代"))
    public_trans = _num(fields.get("公共交通機関費"))
    other = _num(fields.get("その他実費"))
    expense_total = _num(fields.get("経費精算合計"))

    taxable = _num(fields.get("課税対象額"))
    withholding = _num(fields.get("源泉徴収税"))
    gross = _num(fields.get("総支給額"))
    net = _num(fields.get("差引支払額"))

    note = _extract_text(fields.get("備考", ""))

    card = {
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": f"給与明細 {period}"},
        },
        "elements": [
            {
                "tag": "markdown",
                "content": f"**{target}** さん　{period} の給与明細です。",
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "**勤務実績**",
            },
            {
                "tag": "markdown",
                "content": (
                    f"フル出勤: **{full_days}日**"
                    + (f"　半日出勤: **{half_days}日**" if half_days else "")
                    + (f"　単独撮影: **{solo_days}日**" if solo_days else "")
                    + (f"　複数現場加算: **{multi_days}日**" if multi_days else "")
                    + (f"\n点群処理: **{point_cloud}箇所**" if point_cloud else "")
                ),
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "**報酬内訳**",
            },
            {
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "grey",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 3,
                        "elements": [
                            {"tag": "markdown", "content": "基本報酬（現場）"},
                            {"tag": "markdown", "content": "基本報酬（内業）"},
                            {"tag": "markdown", "content": "車両手当"},
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [
                            {"tag": "markdown", "content": f"**{genba:,}円**"},
                            {"tag": "markdown", "content": f"**{naigyo:,}円**"},
                            {"tag": "markdown", "content": f"**{vehicle:,}円**"},
                        ],
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "markdown",
                "content": "**経費精算**",
            },
            {
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "grey",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 3,
                        "elements": [
                            {"tag": "markdown", "content": f"ガソリン代（{gas_km}km）"},
                            {"tag": "markdown", "content": "高速代"},
                            {"tag": "markdown", "content": "駐車場代"},
                            {"tag": "markdown", "content": "公共交通機関費"},
                            {"tag": "markdown", "content": "その他実費"},
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [
                            {"tag": "markdown", "content": f"**{gas_cost:,}円**"},
                            {"tag": "markdown", "content": f"**{highway:,}円**"},
                            {"tag": "markdown", "content": f"**{parking:,}円**"},
                            {"tag": "markdown", "content": f"**{public_trans:,}円**"},
                            {"tag": "markdown", "content": f"**{other:,}円**"},
                        ],
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "column_set",
                "flex_mode": "none",
                "background_style": "default",
                "columns": [
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 3,
                        "elements": [
                            {"tag": "markdown", "content": "課税対象額"},
                            {"tag": "markdown", "content": "源泉徴収税"},
                            {"tag": "markdown", "content": "経費精算合計"},
                            {"tag": "markdown", "content": "**総支給額**"},
                            {"tag": "markdown", "content": "**差引支払額**"},
                        ],
                    },
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 2,
                        "elements": [
                            {"tag": "markdown", "content": f"{taxable:,}円"},
                            {"tag": "markdown", "content": f"-{withholding:,}円"},
                            {"tag": "markdown", "content": f"{expense_total:,}円"},
                            {"tag": "markdown", "content": f"**{gross:,}円**"},
                            {"tag": "markdown", "content": f"**{net:,}円**"},
                        ],
                    },
                ],
            },
        ],
    }

    if note:
        card["elements"].append({"tag": "hr"})
        card["elements"].append(
            {"tag": "markdown", "content": f"備考: {note}"}
        )

    card["elements"].append(
        {
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": f"東海エアサービス株式会社 | 自動生成 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                }
            ],
        }
    )

    return card


def build_confirmation_text(fields, month):
    """國本への確認用テキスト"""
    target = _extract_text(fields.get("対象者", ""))
    year = 2000 + int(month[:2])
    mon = int(month[2:])
    period = f"{year}年{mon}月分"

    lines = [
        f"[給与明細送信確認] {period} - {target}",
        "",
        f"基本報酬（現場）: {_num(fields.get('基本報酬_現場')):,}円",
        f"基本報酬（内業）: {_num(fields.get('基本報酬_内業')):,}円",
        f"車両手当: {_num(fields.get('車両手当')):,}円",
        f"経費精算合計: {_num(fields.get('経費精算合計')):,}円",
        f"課税対象額: {_num(fields.get('課税対象額')):,}円",
        f"源泉徴収税: {_num(fields.get('源泉徴収税')):,}円",
        f"総支給額: {_num(fields.get('総支給額')):,}円",
        f"差引支払額: {_num(fields.get('差引支払額')):,}円",
        "",
        "送信するには: python3 payslip_lark_sender.py --month {} --send".format(month),
    ]
    return "\n".join(lines)


# ==================== month auto解決 ====================
def resolve_month(month_arg: str) -> str:
    """--month auto: 前月をYYMM形式で返す"""
    if month_arg.lower() == "auto":
        now = datetime.now()
        if now.month == 1:
            prev_year = now.year - 1
            prev_month = 12
        else:
            prev_year = now.year
            prev_month = now.month - 1
        yymm = f"{prev_year % 100:02d}{prev_month:02d}"
        print(f"[auto] 前月を自動計算: {yymm}")
        return yymm
    return month_arg


# ==================== Google Sheets ステータス更新 ====================
def _find_sa_key() -> Path | None:
    for p in GOOGLE_SA_KEY_PATHS:
        if p.exists():
            return p
    return None


def update_sheets_status(month: str, new_status: str = "送信済み"):
    """Google Sheets の給与明細タブのステータスを更新"""
    if not HAS_GSPREAD:
        print("  [Sheets] gspread未インストール、スキップ")
        return False

    sa_key = _find_sa_key()
    if not sa_key:
        print("  [Sheets] SAキーファイルが見つかりません、スキップ")
        return False

    year = 2000 + int(month[:2])
    mon = int(month[2:])
    tab_name = f"{year}年{mon}月"

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = SACredentials.from_service_account_file(str(sa_key), scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SPREADSHEET_ID)
        ws = sh.worksheet(tab_name)

        # 「ステータス」セルを検索して更新
        cells = ws.findall("ステータス")
        for cell in cells:
            # ステータスの値は隣のセル（同じ行のB列）
            ws.update_cell(cell.row, cell.col + 1, new_status)
            print(f"  [Sheets] ステータスを '{new_status}' に更新")
            return True

        print(f"  [Sheets] ステータスセルが見つかりません")
        return False

    except Exception as e:
        print(f"  [Sheets] ステータス更新エラー: {e}")
        return False


# ==================== Lark Drive PDF保存 ====================
def upload_pdf_to_lark_drive(token, month: str):
    """PDFをLark Driveにアップロード"""
    if not LARK_DRIVE_PAYROLL_FOLDER:
        print("  [Lark Drive] フォルダトークン未設定、スキップ")
        return False

    pdf_path = Path(__file__).parent.parent / "payroll" / f"給与明細_新美光_{month}.pdf"
    if not pdf_path.exists():
        print(f"  [Lark Drive] PDFが見つかりません: {pdf_path}")
        return False

    try:
        # ファイルサイズ取得
        file_size = pdf_path.stat().st_size
        file_name = pdf_path.name

        # Step 1: アップロードURL取得
        data = {
            "file_name": file_name,
            "parent_type": "explorer",
            "parent_node": LARK_DRIVE_PAYROLL_FOLDER,
            "size": file_size,
        }
        result = lark_api_request(
            f"{LARK_API_BASE}/drive/v1/files/upload_all",
            method="POST",
            data=data,
            token=token,
        )
        if result and result.get("code") == 0:
            print(f"  [Lark Drive] アップロード完了: {file_name}")
            return True
        else:
            print(f"  [Lark Drive] アップロード失敗: {result}")
            return False
    except Exception as e:
        print(f"  [Lark Drive] エラー: {e}")
        return False


# ==================== メイン ====================
def main():
    import argparse

    parser = argparse.ArgumentParser(description="給与明細 Lark Bot DM送信")
    parser.add_argument("--month", required=True, help="対象月（YYMM形式: 2602等 / auto）")
    parser.add_argument("--send", action="store_true", help="対象者に送信（省略時はプレビューのみ）")
    parser.add_argument("--dry-run", action="store_true", help="コンソール出力のみ（DM送信なし）")
    args = parser.parse_args()

    # --month auto 解決
    month = resolve_month(args.month)

    config = load_config()
    token = lark_get_token(config)
    print(f"Token取得完了")

    # 給与計算テーブルから対象月の確定レコード取得
    # プレビューモード（--send なし）: ステータス=下書きも対象にする
    if args.send:
        records = fetch_payroll_records(token, month)
        if not records:
            print(f"ステータス=確定のレコードが見つかりません（対象月: {month}）")
            sys.exit(1)
    else:
        # プレビュー用: 下書き or 確定レコードを取得
        records = fetch_payroll_records(token, month)
        if not records:
            # 下書きも検索
            records = fetch_payroll_records_by_status(token, month, "下書き")
        if not records:
            print(f"対象レコードが見つかりません（対象月: {month}）")
            sys.exit(1)

    print(f"対象レコード: {len(records)}件")

    for rec in records:
        fields = rec.get("fields", {})
        record_id = rec.get("record_id", "")
        target = _extract_text(fields.get("対象者", ""))
        recipient = RECIPIENTS.get(target)

        print(f"\n--- {target} ---")

        # カード生成
        card = build_payslip_card(fields, month)

        if args.dry_run:
            print(json.dumps(card, indent=2, ensure_ascii=False))
            print(build_confirmation_text(fields, month))
            continue

        if args.send:
            # 対象者に送信
            if not recipient:
                print(f"  送信先が見つかりません: {target}")
                continue

            print(f"  送信先: {recipient['display_name']} ({recipient['open_id']})")
            success = lark_send_card(token, recipient["open_id"], card)

            if success:
                # Lark Baseステータスを送信済みに更新
                update_status(token, record_id, "送信済み")

                # Google Sheetsステータスを送信済みに更新
                update_sheets_status(month, "送信済み")

                # Lark DriveにPDF保存
                upload_pdf_to_lark_drive(token, month)

                # 國本に送信完了通知
                lark_send_text(
                    token,
                    KUNIMOTO_OPEN_ID,
                    f"給与明細を送信しました: {target} ({month})\n差引支払額: {_num(fields.get('差引支払額')):,}円",
                )
                # Gmail下書き作成は廃止
            else:
                print(f"  送信失敗")
        else:
            # プレビュー: 國本にのみ確認DM
            print("  プレビューモード: 國本に確認DMを送信")
            confirm_text = build_confirmation_text(fields, month)
            lark_send_text(token, KUNIMOTO_OPEN_ID, confirm_text)
            # カードプレビューも國本に送信
            lark_send_card(token, KUNIMOTO_OPEN_ID, card)

    print("\n完了")


if __name__ == "__main__":
    main()
