#!/usr/bin/env python3
"""
PDFダウンロード型リード獲得（施策2: ユーザー生成シグナル蓄積）

tokaiair.com: 土量計算ツール結果のPDFダウンロード
tomoshi.jp: 属人化リスク診断結果のPDFダウンロード

Cloudflare Worker と連携:
  1. ユーザーがツールで計算/診断
  2. 結果DL時にメール入力（Worker側でバリデーション）
  3. Worker → 本スクリプトのWebhook → CRMにリード登録
  4. DL回数をカウント → 社会的証明として公開

本スクリプトは以下を担当:
  - Webhook受信処理（GitHub Actions cronではなくWorkerからのPOST）
  - CRMへのリード登録
  - DL統計の集計・WordPress更新
  - 社会的証明用カウンター管理

Usage:
    python3 pdf_lead_capture.py --stats            # DL統計確認
    python3 pdf_lead_capture.py --update-counter    # WPのカウンター更新
    python3 pdf_lead_capture.py --register EMAIL TOOL_TYPE  # 手動リード登録
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config
from lib.lark_api import lark_get_token, lark_list_records, lark_create_record

# CRM テーブル
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_DEALS = "tbl1rM86nAw9l3bP"

# 統計ファイル
STATS_FILE = SCRIPT_DIR / "data" / "pdf_lead_stats.json"

# ツール種別
TOOL_TYPES = {
    "earthwork_calc": {
        "name": "土量計算ツール",
        "site": "tokaiair",
        "deal_source": "土量計算ツールDL",
    },
    "risk_assessment": {
        "name": "属人化リスク診断",
        "site": "tomoshi",
        "deal_source": "属人化診断DL",
    },
}


def load_stats():
    """DL統計を読み込み"""
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "total_downloads": 0,
        "by_tool": {},
        "by_month": {},
        "leads": [],
    }


def save_stats(stats):
    """DL統計を保存"""
    STATS_FILE.parent.mkdir(exist_ok=True)
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)


def register_lead(cfg, email, tool_type, company="", name=""):
    """CRMにリード登録"""
    if tool_type not in TOOL_TYPES:
        print(f"[ERROR] 不明なツール種別: {tool_type}")
        return False

    tool_info = TOOL_TYPES[tool_type]
    token = lark_get_token(cfg)

    # 既存連絡先チェック（重複防止）
    contacts = lark_list_records(token, TABLE_CONTACTS, cfg=cfg)
    existing = None
    for c in contacts:
        f = c.get("fields", {})
        contact_email = ""
        email_val = f.get("メールアドレス", "")
        if isinstance(email_val, list):
            for item in email_val:
                if isinstance(item, dict):
                    contact_email = item.get("text", "")
                else:
                    contact_email = str(item)
        else:
            contact_email = str(email_val)

        if contact_email.lower() == email.lower():
            existing = c
            break

    if existing:
        print(f"  既存連絡先: {email} (record_id={existing['record_id']})")
    else:
        # 新規連絡先作成
        fields = {
            "メールアドレス": email,
            "リードソース": tool_info["deal_source"],
        }
        if name:
            fields["氏名"] = name
        if company:
            fields["会社名"] = company

        result = lark_create_record(token, TABLE_CONTACTS, fields, cfg=cfg)
        if result.get("code") == 0:
            print(f"  連絡先作成: {email}")
        else:
            print(f"  連絡先作成失敗: {result}")

    # DL統計更新
    stats = load_stats()
    stats["total_downloads"] += 1
    stats.setdefault("by_tool", {}).setdefault(tool_type, 0)
    stats["by_tool"][tool_type] += 1

    month_key = datetime.now().strftime("%Y-%m")
    stats.setdefault("by_month", {}).setdefault(month_key, 0)
    stats["by_month"][month_key] += 1

    stats.setdefault("leads", []).append({
        "email": email,
        "tool": tool_type,
        "timestamp": datetime.now().isoformat(),
    })
    # リスト肥大化防止
    if len(stats["leads"]) > 1000:
        stats["leads"] = stats["leads"][-500:]

    save_stats(stats)
    print(f"  DL統計更新: 累計{stats['total_downloads']}件")
    return True


def get_public_counter():
    """公開用カウンター（社会的証明用の丸め数値）"""
    stats = load_stats()
    total = stats.get("total_downloads", 0)

    # 1000単位で丸める（見栄えのため）
    if total < 100:
        return f"{total}件"
    elif total < 1000:
        return f"{(total // 100) * 100}件以上"
    else:
        return f"{(total // 1000) * 1000:,}件以上"


def show_stats():
    """統計表示"""
    stats = load_stats()
    print("=== PDFダウンロード統計 ===")
    print(f"累計DL数: {stats.get('total_downloads', 0)}件")
    print(f"公開表示: 「累計{get_public_counter()}の見積試算に利用」")
    print()
    print("ツール別:")
    for tool, count in stats.get("by_tool", {}).items():
        name = TOOL_TYPES.get(tool, {}).get("name", tool)
        print(f"  {name}: {count}件")
    print()
    print("月別:")
    for month, count in sorted(stats.get("by_month", {}).items()):
        print(f"  {month}: {count}件")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PDFリード獲得")
    parser.add_argument("--stats", action="store_true", help="統計表示")
    parser.add_argument("--update-counter", action="store_true", help="WPカウンター更新")
    parser.add_argument("--register", nargs=2, metavar=("EMAIL", "TOOL_TYPE"),
                        help="手動リード登録")
    args = parser.parse_args()

    if not any([args.stats, args.update_counter, args.register]):
        parser.print_help()
        sys.exit(1)

    if args.stats:
        show_stats()

    if args.register:
        cfg = load_config()
        email, tool_type = args.register
        register_lead(cfg, email, tool_type)

    if args.update_counter:
        counter = get_public_counter()
        print(f"公開カウンター: 「累計{counter}の見積試算に利用」")
        print("[TODO] WordPressへの自動更新はwp_safe_deploy.py経由で実装")


if __name__ == "__main__":
    main()
