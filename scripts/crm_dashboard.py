#!/usr/bin/env python3
"""
CRMダッシュボードスクリプト

受注台帳・商談テーブルからKPIを計算し、Lark Baseに書き込み。

計算項目:
  - パイプライン（商談ステージ別件数・金額）
  - 担当者KPI（新美・政木の商談数・受注率・平均単価）
  - 月次トレンド（月別商談数・受注金額推移）
  - 温度感分布（Hot/Warm/Cold/Unknown）

Usage:
  python3 crm_dashboard.py                # 計算 & Lark Base書き込み
  python3 crm_dashboard.py --dry-run      # 計算のみ（書き込みなし）
  python3 crm_dashboard.py --json         # JSON出力
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config
from lib.lark_api import lark_get_token, lark_list_records, lark_create_record, lark_update_record

# ── Constants ──
DEAL_TABLE_ID = "tbl1rM86nAw9l3bP"      # 商談テーブル
ORDER_TABLE_ID = "tbldLj2iMJYocct6"      # 受注台帳
ACCOUNT_TABLE_ID = "tblTfGScQIdLTYxA"    # 取引先

# ダッシュボード出力先（Lark Baseのタスク管理Baseを利用）
TASK_BASE_TOKEN = "HSSMb3T2jalcuysFCjGjJ76wpKe"

# 担当者名
REPS = {
    "新美": ["新美", "Niimi"],
    "政木": ["政木", "Masaki"],
}

# 商談ステージ定義
STAGES = {
    "初期商談": "initial",
    "提案中": "proposal",
    "見積提出": "quoted",
    "交渉中": "negotiation",
    "受注": "won",
    "失注": "lost",
    "保留": "hold",
}


def extract_text(value):
    """Lark Baseフィールド値からテキスト抽出"""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("text", item.get("name", str(item))))
            else:
                parts.append(str(item))
        return " ".join(parts)
    if isinstance(value, dict):
        return value.get("text", value.get("name", str(value)))
    return str(value) if value else ""


def extract_number(value):
    """Lark Baseフィールド値から数値抽出"""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("¥", "").strip())
        except (ValueError, AttributeError):
            return 0
    return 0


def extract_timestamp(value):
    """Lark Baseフィールド値からdatetime抽出"""
    if isinstance(value, (int, float)):
        # Unix timestamp (ms)
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
    return None


def identify_rep(fields):
    """担当者を特定"""
    for field_name in ["担当者", "営業担当", "担当"]:
        val = extract_text(fields.get(field_name, ""))
        if val:
            for rep_name, aliases in REPS.items():
                for alias in aliases:
                    if alias in val:
                        return rep_name
    return "その他"


def compute_pipeline(deals):
    """パイプライン（ステージ別集計）"""
    pipeline = defaultdict(lambda: {"count": 0, "amount": 0})

    for deal in deals:
        fields = deal.get("fields", {})
        stage = extract_text(fields.get("商談ステージ", ""))
        amount = extract_number(fields.get("商談金額", 0))

        if not stage or stage.strip() == "":
            stage = "未設定"

        pipeline[stage]["count"] += 1
        pipeline[stage]["amount"] += amount

    return dict(pipeline)


def compute_rep_kpi(deals):
    """担当者別KPI"""
    rep_stats = defaultdict(lambda: {
        "total_deals": 0,
        "won": 0,
        "lost": 0,
        "in_progress": 0,
        "total_amount": 0,
        "won_amount": 0,
        "avg_deal_size": 0,
    })

    for deal in deals:
        fields = deal.get("fields", {})
        rep = identify_rep(fields)
        stage = extract_text(fields.get("商談ステージ", ""))
        amount = extract_number(fields.get("商談金額", 0))

        rep_stats[rep]["total_deals"] += 1
        rep_stats[rep]["total_amount"] += amount

        if stage == "受注":
            rep_stats[rep]["won"] += 1
            rep_stats[rep]["won_amount"] += amount
        elif stage == "失注":
            rep_stats[rep]["lost"] += 1
        else:
            rep_stats[rep]["in_progress"] += 1

    # 受注率・平均単価計算
    for rep, stats in rep_stats.items():
        closed = stats["won"] + stats["lost"]
        stats["win_rate"] = round(stats["won"] / closed * 100, 1) if closed > 0 else 0
        stats["avg_deal_size"] = round(stats["total_amount"] / stats["total_deals"]) if stats["total_deals"] > 0 else 0
        stats["avg_won_size"] = round(stats["won_amount"] / stats["won"]) if stats["won"] > 0 else 0

    return dict(rep_stats)


def compute_monthly_trend(deals):
    """月次トレンド"""
    monthly = defaultdict(lambda: {"deals": 0, "amount": 0, "won": 0, "won_amount": 0})

    for deal in deals:
        fields = deal.get("fields", {})

        # 作成日を取得
        created = None
        for field_name in ["作成日", "作成日時", "Created"]:
            created = extract_timestamp(fields.get(field_name))
            if created:
                break

        if not created:
            continue

        month_key = created.strftime("%Y-%m")
        stage = extract_text(fields.get("商談ステージ", ""))
        amount = extract_number(fields.get("商談金額", 0))

        monthly[month_key]["deals"] += 1
        monthly[month_key]["amount"] += amount

        if stage == "受注":
            monthly[month_key]["won"] += 1
            monthly[month_key]["won_amount"] += amount

    # ソート
    return dict(sorted(monthly.items()))


def compute_temperature(deals):
    """温度感分布"""
    temp_dist = defaultdict(int)

    for deal in deals:
        fields = deal.get("fields", {})
        temp = extract_text(fields.get("温度感", ""))

        if not temp or temp.strip() == "":
            temp = "未設定"

        # 正規化
        temp_lower = temp.lower()
        if any(k in temp_lower for k in ["hot", "高", "ホット"]):
            temp_dist["Hot"] += 1
        elif any(k in temp_lower for k in ["warm", "中", "ウォーム"]):
            temp_dist["Warm"] += 1
        elif any(k in temp_lower for k in ["cold", "低", "コールド"]):
            temp_dist["Cold"] += 1
        else:
            temp_dist["未設定"] += 1

    return dict(temp_dist)


def format_amount(amount):
    """金額フォーマット"""
    if amount >= 10000:
        return f"{amount/10000:.1f}万円"
    return f"{amount:,.0f}円"


def print_dashboard(pipeline, rep_kpi, monthly, temperature, deal_count):
    """ダッシュボード出力"""
    print("\n" + "=" * 70)
    print(f"  CRM ダッシュボード - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # パイプライン
    print("\n--- パイプライン ---")
    print(f"{'ステージ':<12} {'件数':>6} {'金額':>14}")
    print("-" * 36)
    total_count = 0
    total_amount = 0
    for stage, data in sorted(pipeline.items(), key=lambda x: -x[1]["count"]):
        print(f"{stage:<12} {data['count']:>6} {format_amount(data['amount']):>14}")
        total_count += data["count"]
        total_amount += data["amount"]
    print("-" * 36)
    print(f"{'合計':<12} {total_count:>6} {format_amount(total_amount):>14}")

    # 担当者KPI
    print("\n--- 担当者KPI ---")
    print(f"{'担当者':<8} {'商談数':>6} {'受注':>4} {'失注':>4} {'受注率':>7} {'平均単価':>12}")
    print("-" * 50)
    for rep, stats in sorted(rep_kpi.items()):
        print(f"{rep:<8} {stats['total_deals']:>6} {stats['won']:>4} "
              f"{stats['lost']:>4} {stats['win_rate']:>6.1f}% "
              f"{format_amount(stats['avg_deal_size']):>12}")

    # 温度感
    print("\n--- 温度感分布 ---")
    for temp, count in sorted(temperature.items(), key=lambda x: -x[1]):
        bar = "#" * min(count, 50)
        pct = count / deal_count * 100 if deal_count > 0 else 0
        print(f"  {temp:<6} {count:>4} ({pct:>5.1f}%) {bar}")

    # 月次トレンド（直近6ヶ月）
    print("\n--- 月次トレンド（直近6ヶ月） ---")
    recent = list(monthly.items())[-6:]
    print(f"{'月':>8} {'商談数':>6} {'受注':>4} {'受注金額':>14}")
    print("-" * 38)
    for month, data in recent:
        print(f"{month:>8} {data['deals']:>6} {data['won']:>4} {format_amount(data['won_amount']):>14}")

    print("\n" + "=" * 70)


def write_to_lark(cfg, dashboard_data, dry_run=False):
    """ダッシュボードデータをLark Baseに書き込み

    タスク管理Baseの会話ログテーブルにダッシュボードサマリーを記録。
    """
    if dry_run:
        print("\n[DRY-RUN] Lark Base書き込みスキップ")
        return True

    print("\n[Lark] ダッシュボードデータ書き込み中...")
    token = lark_get_token(cfg)

    # サマリーテキスト構築
    pipeline = dashboard_data["pipeline"]
    rep_kpi = dashboard_data["rep_kpi"]
    temperature = dashboard_data["temperature"]
    monthly = dashboard_data["monthly"]

    # パイプラインサマリー
    pipeline_lines = []
    for stage, data in sorted(pipeline.items(), key=lambda x: -x[1]["count"]):
        pipeline_lines.append(f"{stage}: {data['count']}件 ({format_amount(data['amount'])})")

    # 担当者サマリー
    rep_lines = []
    for rep, stats in sorted(rep_kpi.items()):
        rep_lines.append(
            f"{rep}: 商談{stats['total_deals']}件 / 受注{stats['won']}件 / "
            f"受注率{stats['win_rate']}% / 平均{format_amount(stats['avg_deal_size'])}"
        )

    # 温度感サマリー
    temp_lines = []
    for temp, count in sorted(temperature.items(), key=lambda x: -x[1]):
        temp_lines.append(f"{temp}: {count}件")

    summary = (
        f"=== CRMダッシュボード {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n\n"
        f"[パイプライン]\n" + "\n".join(pipeline_lines) + "\n\n"
        f"[担当者KPI]\n" + "\n".join(rep_lines) + "\n\n"
        f"[温度感]\n" + "\n".join(temp_lines)
    )

    # 会話ログテーブルに記録
    # フィールド: セッション日時, セッション概要, 主要決定事項, 作成物, 積み残し, ユーザー指示メモ
    CONVERSATION_TABLE = "tblIyLVn7RFqDbdt"
    now_ms = int(datetime.now().timestamp() * 1000)
    try:
        result = lark_create_record(
            token,
            CONVERSATION_TABLE,
            fields={
                "セッション日時": now_ms,
                "セッション概要": f"CRMダッシュボード自動生成 {datetime.now().strftime('%Y-%m-%d')}",
                "主要決定事項": summary,
            },
            base_token=TASK_BASE_TOKEN,
        )
        if result.get("code") == 0 or result.get("data", {}).get("record"):
            print("  会話ログテーブルに記録完了")
        else:
            print(f"  記録失敗: {result.get('msg', 'unknown')}")
    except Exception as e:
        print(f"  Lark書き込みエラー（非致命的）: {e}")

    # JSONファイルにもバックアップ
    output_path = SCRIPT_DIR.parent / "data" / f"crm_dashboard_{datetime.now().strftime('%Y%m%d')}.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        # datetime以外のデータをJSON化
        serializable = {
            "generated_at": datetime.now().isoformat(),
            "pipeline": dashboard_data["pipeline"],
            "rep_kpi": dashboard_data["rep_kpi"],
            "temperature": dashboard_data["temperature"],
            "monthly": dashboard_data["monthly"],
            "total_deals": dashboard_data["total_deals"],
        }
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print(f"  JSON出力: {output_path}")

    return True


def main():
    dry_run = "--dry-run" in sys.argv
    json_output = "--json" in sys.argv

    cfg = load_config()

    # 商談データ取得
    print("[Step 1] 商談データ取得...")
    token = lark_get_token(cfg)
    deals = lark_list_records(token, DEAL_TABLE_ID, cfg=cfg)
    print(f"  商談レコード数: {len(deals)}")

    if not deals:
        print("商談データが取得できません。終了。")
        return False

    # KPI計算
    print("[Step 2] KPI計算...")
    pipeline = compute_pipeline(deals)
    rep_kpi = compute_rep_kpi(deals)
    monthly = compute_monthly_trend(deals)
    temperature = compute_temperature(deals)

    dashboard_data = {
        "pipeline": pipeline,
        "rep_kpi": rep_kpi,
        "monthly": monthly,
        "temperature": temperature,
        "total_deals": len(deals),
    }

    # 出力
    if json_output:
        serializable = {
            "generated_at": datetime.now().isoformat(),
            **dashboard_data,
        }
        print(json.dumps(serializable, ensure_ascii=False, indent=2))
        return True

    print_dashboard(pipeline, rep_kpi, monthly, temperature, len(deals))

    # Lark Base書き込み
    print("[Step 3] Lark Base書き込み...")
    write_to_lark(cfg, dashboard_data, dry_run=dry_run)

    print(f"\n完了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
