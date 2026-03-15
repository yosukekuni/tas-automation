#!/usr/bin/env python3
"""
業種別事例PDF自動生成スクリプト
受注台帳データから匿名化した導入事例集を生成

Usage:
  python3 case_study_generator.py --industry ゼネコン
  python3 case_study_generator.py --industry コンサルタント
  python3 case_study_generator.py --all
  python3 case_study_generator.py --list           # 業種一覧表示
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from reportlab.lib.styles import getSampleStyleSheet
except ImportError:
    print("ERROR: reportlab が未インストールです。")
    print("  pip install reportlab")
    sys.exit(1)

# ── 定数 ──────────────────────────────────────────
COMPANY = {
    "name": "東海エアサービス株式会社",
    "zip": "〒465-0077",
    "addr": "愛知県名古屋市名東区植園町1-9-3 LM1205",
    "email": "info@tokaiair.com",
    "url": "https://www.tokaiair.com",
    "tel": "",
}

FONT_REGULAR_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicR.ttc"
FONT_BOLD_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicB.ttc"
FONT_REGULAR = "BIZUDGothic"
FONT_BOLD = "BIZUDGothicBold"

DATA_CSV = Path(__file__).parent.parent / "data" / "order_classification.csv"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "case_studies"

PAGE_W, PAGE_H = A4
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
MARGIN_T = 20 * mm
MARGIN_B = 20 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

# ブランドカラー
COLOR_PRIMARY = colors.HexColor("#1a3c6e")
COLOR_ACCENT = colors.HexColor("#2e7d32")
COLOR_LIGHT_BG = colors.HexColor("#f0f4fa")
COLOR_LIGHT_GREEN = colors.HexColor("#e8f5e9")
COLOR_GRAY = colors.HexColor("#666666")
COLOR_LIGHT_GRAY = colors.HexColor("#eeeeee")

# 業種ごとの表示設定
INDUSTRY_CONFIG = {
    "ゼネコン": {
        "title": "建設業界向け",
        "subtitle": "ドローン空撮・現場記録 導入事例集",
        "description": "大手ゼネコン様を中心に、建設現場の進捗管理・竣工記録に\nドローン空撮をご活用いただいています。",
        "challenges": [
            "高所・広域の現場全景撮影にコストと時間がかかる",
            "定期的な進捗記録の撮影体制が確保できない",
            "工事の出来形管理に客観的な記録が必要",
        ],
        "solutions": [
            "ドローンによる低コスト・短時間の全景撮影",
            "月次〜週次の定期撮影プランでの継続支援",
            "高解像度写真・4K動画による正確な記録",
        ],
        "case_templates": [
            {
                "scenario": "大型商業施設の新築工事",
                "challenge": "延床面積10,000m2超の現場を月次で記録したいが、\n従来の高所作業車では1回あたり半日以上かかっていた。",
                "solution": "ドローン定期撮影プラン（月1回）を導入。\n撮影〜写真納品まで毎回2時間で完了。",
                "effect": "撮影コスト約70%削減 / 工期中の全景記録を完全網羅\n/ 発注者への報告資料の品質が大幅向上",
            },
            {
                "scenario": "工場・物流施設の建設進捗管理",
                "challenge": "広大な敷地の出来形を正確に把握したいが、\n地上からの写真では全体像が掴めなかった。",
                "solution": "4K空撮動画＋高解像度写真の定期撮影を実施。\n指定アングルから毎回同条件で撮影し比較可能に。",
                "effect": "施工ステップごとの変化を可視化 / 遠隔地の本社\nへのリアルタイム報告が可能に",
            },
            {
                "scenario": "道路・橋梁工事の竣工記録",
                "challenge": "交通規制下での撮影は安全管理が厳しく、\n従来手法では十分な記録が残せなかった。",
                "solution": "ドローンにより交通に影響なく上空から撮影。\n竣工前後の比較記録を短時間で取得。",
                "effect": "安全リスクゼロの撮影体制を実現 /\n発注者提出用の高品質な竣工写真を納品",
            },
        ],
    },
    "コンサルタント": {
        "title": "建設コンサルタント業界向け",
        "subtitle": "ドローン測量 導入事例集",
        "description": "河川・砂防・造成などの測量業務において、\nドローン測量による高精度データ取得をご支援しています。",
        "challenges": [
            "従来測量では広域・険しい地形のデータ取得に時間がかかる",
            "測量コストの削減と精度の両立が求められる",
            "3Dデータ・点群データの活用ニーズが増加",
        ],
        "solutions": [
            "ドローン写真測量・LiDAR測量による広域データ取得",
            "従来測量比で大幅な工期短縮",
            "点群データ・3Dモデル・オルソ画像の納品",
        ],
        "case_templates": [
            {
                "scenario": "河川・砂防施設の広域測量",
                "challenge": "複数箇所の河川測量を短期間で完了させる必要が\nあったが、従来のTS測量では数週間を要する計画だった。",
                "solution": "ドローン写真測量により広域データを一括取得。\n点群データ・オルソ画像・横断図を納品。",
                "effect": "現場作業日数を約80%短縮 /\n成果品の精度はi-Construction基準を満足",
            },
            {
                "scenario": "造成地の土量算出",
                "challenge": "広大な造成現場の土量を正確に把握したいが、\n地形が複雑で従来測量では精度が出しにくかった。",
                "solution": "ドローン測量で高密度点群データを取得し、\n3Dモデルから正確な土量を自動算出。",
                "effect": "従来比で測量コスト約60%削減 /\n高精度な土量データで設計変更に迅速対応",
            },
            {
                "scenario": "急傾斜地の地形調査",
                "challenge": "人の立ち入りが困難な急傾斜地の現況を\n把握する必要があったが、安全面で課題があった。",
                "solution": "ドローンにより安全に上空から撮影。\n写真測量で詳細な地形モデルを構築。",
                "effect": "作業員の安全を確保しつつ高精度データを取得 /\n防災計画の基礎資料として活用",
            },
        ],
    },
    "不動産": {
        "title": "不動産業界向け",
        "subtitle": "ドローン空撮・眺望撮影 導入事例集",
        "description": "マンション眺望撮影・物件空撮など、\n不動産の販売促進にドローン撮影をご活用いただいています。",
        "challenges": [
            "建設前の高層階からの眺望を事前に確認したい",
            "物件の魅力を伝える高品質な空撮写真が必要",
            "航空法の許可取得・安全管理に不安がある",
        ],
        "solutions": [
            "指定高度・方角での精密な眺望シミュレーション撮影",
            "プロフェッショナルな空撮写真・動画の提供",
            "航空法申請から撮影・納品までワンストップ対応",
        ],
        "case_templates": [
            {
                "scenario": "分譲マンションの眺望シミュレーション",
                "challenge": "建設予定地から各階の眺望を事前に把握し、\n販売資料に使用したかったが手段がなかった。",
                "solution": "ドローンで指定高度（5F/10F/15F相当）から\n全方位の眺望写真を撮影。パノラマ画像で納品。",
                "effect": "モデルルーム来場者への訴求力が向上 /\n眺望を理由にした上層階の成約率が改善",
            },
        ],
    },
    "官公庁": {
        "title": "官公庁・教育機関向け",
        "subtitle": "ドローン測量・教育支援 導入事例集",
        "description": "官公庁・教育機関でのドローン活用を支援しています。\n測量実習・施設点検等にご利用いただけます。",
        "challenges": [
            "ドローン活用の知見・ノウハウが不足している",
            "安全かつ法令遵守での運用が求められる",
            "限られた予算内で効果的な活用方法を模索",
        ],
        "solutions": [
            "ドローン測量の実習・デモンストレーション支援",
            "国交省登録講習機関としての安心の運用体制",
            "目的に合わせた柔軟なプラン提案",
        ],
        "case_templates": [
            {
                "scenario": "工業高校でのドローン測量実習",
                "challenge": "生徒にドローン測量の最新技術を体験させたいが、\n機材も知見も不足していた。",
                "solution": "ドローン測量のデモンストレーションと\n実習プログラムを提供。実データで成果品作成を体験。",
                "effect": "生徒の測量技術への関心が向上 /\n学校のカリキュラムにドローン測量が定着",
            },
        ],
    },
    "測量会社": {
        "title": "測量会社向け",
        "subtitle": "ドローン測量パートナーシップ 導入事例集",
        "description": "測量会社様のドローン測量業務をサポートしています。\n外注先・パートナーとしてご活用いただけます。",
        "challenges": [
            "ドローン測量の需要増に自社リソースだけでは対応困難",
            "ドローン操縦の技術習得・機材投資のハードルが高い",
            "繁忙期の人手不足を補う信頼できるパートナーが必要",
        ],
        "solutions": [
            "ドローン撮影のアウトソーシングで初期投資不要",
            "経験豊富なパイロットによる確実な現場対応",
            "測量成果品の品質管理・精度検証まで対応",
        ],
        "case_templates": [
            {
                "scenario": "ドローン測量業務の外注パートナー",
                "challenge": "ドローン測量の引き合いが増えているが、\n自社で機材投資・パイロット育成する余裕がなかった。",
                "solution": "撮影業務をアウトソーシング。\n測量計画に基づき必要なデータを取得・納品。",
                "effect": "初期投資ゼロでドローン測量サービスを提供可能に /\n繁忙期の案件取りこぼしを解消",
            },
        ],
    },
    "メーカー": {
        "title": "製造業向け",
        "subtitle": "ドローン活用 導入事例集",
        "description": "工場施設の点検・記録にドローンを活用いただいています。\n高所点検や広大な敷地の効率的な管理を支援します。",
        "challenges": [
            "広大な工場敷地の定期的な記録・管理が煩雑",
            "高所設備の点検に足場組みのコストと安全リスク",
            "施設の経年変化を客観的に記録する手段が限られる",
        ],
        "solutions": [
            "ドローンによる広域・高所の効率的な撮影記録",
            "足場不要の点検で大幅なコスト削減",
            "定期撮影による経年変化の可視化",
        ],
        "case_templates": [
            {
                "scenario": "工場敷地の定期空撮記録",
                "challenge": "広大な工場敷地全体の経年変化を\n把握する手段が限られ、管理が後手に回っていた。",
                "solution": "ドローンによる定期空撮で敷地全体を記録。\n高解像度写真と4K動画で変化を可視化。",
                "effect": "施設管理の効率化 /\n設備更新計画の意思決定材料として活用",
            },
        ],
    },
    "その他": {
        "title": "各業界向け",
        "subtitle": "ドローン撮影 導入事例集",
        "description": "イベント撮影・施設空撮・プロモーション撮影など、\n幅広い業界でドローン撮影をご活用いただいています。",
        "challenges": [
            "高品質な空撮映像を低コストで制作したい",
            "プロモーション素材の撮影手段が限られている",
            "ドローン撮影の手配・許可取得の方法がわからない",
        ],
        "solutions": [
            "プロフェッショナルな空撮写真・4K動画の制作",
            "企画・ロケハン・撮影・編集までワンストップ対応",
            "航空法申請・保険・安全管理すべてお任せ",
        ],
        "case_templates": [
            {
                "scenario": "施設・イベントのプロモーション空撮",
                "challenge": "施設のPR素材を制作したかったが、\nヘリコプター空撮は高額で予算に合わなかった。",
                "solution": "ドローンによる高品質な空撮写真・4K動画を制作。\n企画・撮影・簡易編集までワンストップ対応。",
                "effect": "従来のヘリ空撮比で費用を大幅削減 /\nWebサイト・SNSでの反応が向上",
            },
            {
                "scenario": "大規模施設の現況記録",
                "challenge": "広大な敷地の全景を把握したいが、\n地上からの撮影では全体像を伝えられなかった。",
                "solution": "ドローンで複数高度・複数アングルから撮影。\n定期的な記録撮影プランを提案。",
                "effect": "経営層・ステークホルダーへの報告資料の\n説得力が大幅に向上",
            },
            {
                "scenario": "ゴルフ場・リゾート施設の空撮",
                "challenge": "広大な施設の魅力を伝える映像素材が\n不足しており、集客に苦戦していた。",
                "solution": "ドローンによるダイナミックな空撮映像を制作。\n季節ごとの魅力を映像で訴求。",
                "effect": "Webサイトのコンバージョン率向上 /\nSNSでのシェア・拡散に貢献",
            },
        ],
    },
}

# 金額の範囲表記マッピング
def anonymize_amount(amount: float) -> str:
    """金額を範囲表記に匿名化"""
    a = int(amount)
    if a < 50000:
        return "5万円未満"
    elif a < 100000:
        return "5万円〜10万円"
    elif a < 200000:
        return "10万円〜20万円"
    elif a < 500000:
        return "20万円〜50万円"
    elif a < 1000000:
        return "50万円〜100万円"
    elif a < 3000000:
        return "100万円〜300万円"
    elif a < 5000000:
        return "300万円〜500万円"
    else:
        return "500万円以上"


def anonymize_project_name(name: str) -> str:
    """案件名から固有名詞を除去して内容のみ残す"""
    # 「取引先名_場所/案件内容」形式 → 場所/案件内容部分のみ
    if "_" in name:
        name = name.split("_", 1)[1]
    # 具体的な場所名をぼかす
    return name


def classify_service(service: str) -> str:
    """サービス種別を表示用に変換"""
    mapping = {
        "現場空撮": "建設現場空撮",
        "ドローン測量": "ドローン測量",
        "空撮": "空撮撮影",
        "眺望撮影": "眺望撮影",
        "点検": "施設点検",
        "その他": "ドローン活用",
    }
    return mapping.get(service, service or "ドローン活用")


# ── フォント登録 ──────────────────────────────────
def register_fonts():
    if not os.path.exists(FONT_REGULAR_PATH):
        print(f"WARNING: フォント未検出: {FONT_REGULAR_PATH}")
        print("  Windows日本語フォント(BIZ UDゴシック)が必要です。")
        sys.exit(1)
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_BOLD_PATH, subfontIndex=0))


# ── データ読み込み ────────────────────────────────
def load_data(csv_path: Path) -> list:
    """CSVを読み込み、有効な案件レコードを返す"""
    records = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 非案件を除外
            if row.get("非案件", "").strip() == "Y":
                continue
            # 金額0以下を除外
            try:
                amount = float(row.get("受注金額", 0) or 0)
            except (ValueError, TypeError):
                continue
            if amount <= 0:
                continue
            records.append({
                "案件名": row.get("案件名", ""),
                "取引先名": row.get("取引先名", ""),
                "受注金額": amount,
                "出典": row.get("出典", ""),
                "業種": row.get("業種", "").strip(),
                "サービス種別": row.get("サービス種別", "").strip(),
            })
    return records


def filter_by_industry(records: list, industry: str) -> list:
    """業種でフィルタ（受注案件を優先）"""
    matched = [r for r in records if r["業種"] == industry]
    # 受注案件を優先（出典に「受注100」を含む）
    won = [r for r in matched if "受注100" in r.get("出典", "")]
    others = [r for r in matched if "受注100" not in r.get("出典", "")]
    return won + others


def build_case_studies(records: list, industry: str, max_cases: int = 3) -> list:
    """受注実績からケーススタディを構築（匿名化・テンプレート統合）"""
    config = INDUSTRY_CONFIG.get(industry, INDUSTRY_CONFIG["その他"])
    templates = config.get("case_templates", [])

    cases = []
    seen_companies = set()
    label_counter = 0
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    for r in records:
        if len(cases) >= max_cases:
            break
        # 同一取引先は1件のみ（代表的な案件を採用）
        company = r["取引先名"]
        if company in seen_companies:
            continue
        seen_companies.add(company)

        anon_label = f"{labels[label_counter]}社" if label_counter < len(labels) else f"企業{label_counter + 1}"

        service = classify_service(r["サービス種別"])
        amount_range = anonymize_amount(r["受注金額"])

        # テンプレートからストーリーを割り当て
        tmpl = templates[label_counter % len(templates)] if templates else {
            "scenario": "ドローン活用",
            "challenge": "従来手法では対応が困難な業務があった。",
            "solution": "ドローンを活用した効率的な対応を実施。",
            "effect": "コスト削減と業務効率化を実現。",
        }
        label_counter += 1

        cases.append({
            "label": anon_label,
            "service": service,
            "amount_range": amount_range,
            "project_hint": anonymize_project_name(r["案件名"]),
            "scenario": tmpl["scenario"],
            "challenge": tmpl["challenge"],
            "solution": tmpl["solution"],
            "effect": tmpl["effect"],
        })

    return cases


def compute_stats(records: list) -> dict:
    """業種の集計統計を計算"""
    won = [r for r in records if "受注100" in r.get("出典", "")]
    amounts = [r["受注金額"] for r in won]

    # サービス種別の集計
    service_counts = defaultdict(int)
    for r in won:
        service_counts[classify_service(r["サービス種別"])] += 1

    return {
        "total_cases": len(won),
        "total_inquiries": len(records),
        "avg_amount": sum(amounts) / len(amounts) if amounts else 0,
        "min_amount": min(amounts) if amounts else 0,
        "max_amount": max(amounts) if amounts else 0,
        "services": dict(service_counts),
    }


# ── PDF描画 ────────────────────────────────────────
def draw_text_wrapped(c, text: str, x: float, y: float, max_width: float,
                      font: str, size: float, leading: float = None) -> float:
    """テキストを折り返して描画、最終Y座標を返す"""
    if leading is None:
        leading = size * 1.5
    c.setFont(font, size)
    # 簡易的な文字数ベースの折り返し
    chars_per_line = int(max_width / (size * 0.55))
    lines = []
    for paragraph in text.split("\n"):
        while len(paragraph) > chars_per_line:
            lines.append(paragraph[:chars_per_line])
            paragraph = paragraph[chars_per_line:]
        lines.append(paragraph)

    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def draw_cover_page(c, industry: str, config: dict, stats: dict):
    """表紙ページを描画"""
    # 背景のアクセントバー（上部）
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H - 8 * mm, PAGE_W, 8 * mm, stroke=0, fill=1)

    # メインタイトル
    y = PAGE_H - 60 * mm
    c.setFont(FONT_BOLD, 14)
    c.setFillColor(COLOR_PRIMARY)
    c.drawCentredString(PAGE_W / 2, y, config["title"])
    y -= 18 * mm

    c.setFont(FONT_BOLD, 26)
    c.setFillColor(colors.black)
    # タイトルが長い場合分割
    subtitle = config["subtitle"]
    c.drawCentredString(PAGE_W / 2, y, subtitle)
    y -= 4 * mm

    # タイトル下のライン
    c.setStrokeColor(COLOR_PRIMARY)
    c.setLineWidth(2)
    line_w = 80 * mm
    c.line((PAGE_W - line_w) / 2, y, (PAGE_W + line_w) / 2, y)
    y -= 20 * mm

    # 説明文
    c.setFillColor(COLOR_GRAY)
    c.setFont(FONT_REGULAR, 11)
    for line in config["description"].split("\n"):
        tw = c.stringWidth(line, FONT_REGULAR, 11)
        c.drawString((PAGE_W - tw) / 2, y, line)
        y -= 6 * mm

    y -= 15 * mm

    # 実績サマリーボックス
    box_w = 140 * mm
    box_h = 35 * mm
    box_x = (PAGE_W - box_w) / 2
    c.setFillColor(COLOR_LIGHT_BG)
    c.setStrokeColor(COLOR_PRIMARY)
    c.setLineWidth(1.5)
    c.roundRect(box_x, y - box_h, box_w, box_h, 5, stroke=1, fill=1)

    c.setFillColor(COLOR_PRIMARY)
    c.setFont(FONT_BOLD, 12)
    c.drawCentredString(PAGE_W / 2, y - 10 * mm, "— 導入実績 —")

    c.setFont(FONT_BOLD, 16)
    c.setFillColor(colors.black)
    stats_text = f"受注実績  {stats['total_cases']}件"
    c.drawCentredString(PAGE_W / 2, y - 22 * mm, stats_text)

    if stats["avg_amount"] > 0:
        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(COLOR_GRAY)
        avg_range = anonymize_amount(stats["avg_amount"])
        c.drawCentredString(PAGE_W / 2, y - 30 * mm, f"案件単価帯: {avg_range}")

    y -= box_h + 20 * mm

    # サービス内訳
    if stats["services"]:
        c.setFont(FONT_BOLD, 11)
        c.setFillColor(COLOR_PRIMARY)
        c.drawCentredString(PAGE_W / 2, y, "ご利用サービス内訳")
        y -= 8 * mm

        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(colors.black)
        for svc, cnt in sorted(stats["services"].items(), key=lambda x: -x[1]):
            line = f"・{svc}  {cnt}件"
            tw = c.stringWidth(line, FONT_REGULAR, 10)
            c.drawString((PAGE_W - tw) / 2, y, line)
            y -= 5.5 * mm

    # フッタ: 社名
    y = MARGIN_B + 30 * mm
    c.setFont(FONT_BOLD, 12)
    c.setFillColor(COLOR_PRIMARY)
    c.drawCentredString(PAGE_W / 2, y, COMPANY["name"])
    y -= 6 * mm
    c.setFont(FONT_REGULAR, 9)
    c.setFillColor(COLOR_GRAY)
    c.drawCentredString(PAGE_W / 2, y, f"{COMPANY['url']}  |  {COMPANY['email']}")

    # 下部アクセントバー
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, 0, PAGE_W, 5 * mm, stroke=0, fill=1)


def draw_page_header(c, config: dict):
    """共通ページヘッダーを描画、開始Y座標を返す"""
    y = PAGE_H - MARGIN_T
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, stroke=0, fill=1)
    c.setFont(FONT_BOLD, 10)
    c.setFillColor(COLOR_PRIMARY)
    c.drawString(MARGIN_L, y, f"{config['title']} {config['subtitle']}")
    y -= 3 * mm
    c.setStrokeColor(COLOR_PRIMARY)
    c.setLineWidth(1)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 12 * mm
    return y


def draw_challenges_page(c, industry: str, config: dict, stats: dict, page_num: int):
    """課題と解決策ページを描画"""
    y = draw_page_header(c, config)

    # 課題セクション
    c.setFont(FONT_BOLD, 14)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, y, "こんなお悩みはありませんか?")
    y -= 4 * mm
    c.setStrokeColor(COLOR_LIGHT_GRAY)
    c.setLineWidth(0.5)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 10 * mm

    for challenge in config["challenges"]:
        # 課題カード
        card_h = 18 * mm
        c.setFillColor(colors.HexColor("#fef2f2"))
        c.setStrokeColor(colors.HexColor("#f5c6cb"))
        c.setLineWidth(0.5)
        c.roundRect(MARGIN_L, y - card_h, CONTENT_W, card_h, 3, stroke=1, fill=1)

        c.setFont(FONT_BOLD, 11)
        c.setFillColor(colors.HexColor("#c62828"))
        c.drawString(MARGIN_L + 5 * mm, y - 7 * mm, "BEFORE")
        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(colors.HexColor("#555555"))
        c.drawString(MARGIN_L + 28 * mm, y - 7 * mm, challenge)

        # 矢印風の「解決」テキスト
        c.setFont(FONT_REGULAR, 8)
        c.setFillColor(COLOR_ACCENT)
        c.drawRightString(PAGE_W - MARGIN_R - 5 * mm, y - 13 * mm, ">>> 解決")

        y -= card_h + 3 * mm

    y -= 8 * mm

    # 解決策セクション
    c.setFont(FONT_BOLD, 14)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, y, "東海エアサービスが解決します")
    y -= 4 * mm
    c.setStrokeColor(COLOR_LIGHT_GRAY)
    c.setLineWidth(0.5)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 10 * mm

    for solution in config["solutions"]:
        card_h = 18 * mm
        c.setFillColor(COLOR_LIGHT_GREEN)
        c.setStrokeColor(colors.HexColor("#c8e6c9"))
        c.setLineWidth(0.5)
        c.roundRect(MARGIN_L, y - card_h, CONTENT_W, card_h, 3, stroke=1, fill=1)

        c.setFont(FONT_BOLD, 11)
        c.setFillColor(COLOR_ACCENT)
        c.drawString(MARGIN_L + 5 * mm, y - 7 * mm, "AFTER")
        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(colors.HexColor("#333333"))
        c.drawString(MARGIN_L + 25 * mm, y - 7 * mm, solution)

        y -= card_h + 3 * mm

    y -= 10 * mm

    # 実績サマリー（コンパクト版）
    if stats["total_cases"] > 0:
        summary_h = 16 * mm
        c.setFillColor(COLOR_LIGHT_BG)
        c.setStrokeColor(COLOR_PRIMARY)
        c.setLineWidth(1)
        c.roundRect(MARGIN_L, y - summary_h, CONTENT_W, summary_h, 3, stroke=1, fill=1)

        c.setFont(FONT_BOLD, 11)
        c.setFillColor(COLOR_PRIMARY)
        c.drawString(MARGIN_L + 5 * mm, y - 6 * mm, "導入実績")
        c.setFont(FONT_BOLD, 14)
        c.drawString(MARGIN_L + 35 * mm, y - 6 * mm, f"{stats['total_cases']}件")

        # サービス内訳を横並び表示
        c.setFont(FONT_REGULAR, 9)
        c.setFillColor(COLOR_GRAY)
        svc_text = " / ".join(f"{svc} {cnt}件" for svc, cnt in
                              sorted(stats["services"].items(), key=lambda x: -x[1]))
        c.drawString(MARGIN_L + 5 * mm, y - 12 * mm, f"内訳: {svc_text}")

    draw_footer(c, page_num)


def _wrap_text_lines(text: str, font_name: str, font_size: float, max_width: float, c) -> list:
    """テキストを指定幅で折り返し、行のリストを返す（実測幅ベース）"""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            test = current + ch
            if c.stringWidth(test, font_name, font_size) > max_width:
                if current:
                    lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
    return lines


def draw_case_detail_pages(c, industry: str, config: dict, cases: list, start_page: int) -> int:
    """事例詳細ページを描画（各事例にストーリー付き）、次のページ番号を返す"""
    if not cases:
        y = draw_page_header(c, config)
        c.setFont(FONT_BOLD, 13)
        c.setFillColor(colors.black)
        c.drawString(MARGIN_L, y, "導入事例")
        y -= 10 * mm
        c.setFont(FONT_REGULAR, 10)
        c.setFillColor(COLOR_GRAY)
        c.drawString(MARGIN_L + 5 * mm, y, "現在、この業種のご導入実績を蓄積中です。")
        c.drawString(MARGIN_L + 5 * mm, y - 6 * mm, "お気軽にお問い合わせください。")
        draw_footer(c, start_page)
        return start_page + 1

    y = draw_page_header(c, config)
    page_num = start_page

    # セクションタイトル
    c.setFont(FONT_BOLD, 14)
    c.setFillColor(colors.black)
    c.drawString(MARGIN_L, y, "導入事例")
    y -= 4 * mm
    c.setStrokeColor(COLOR_LIGHT_GRAY)
    c.setLineWidth(0.5)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 8 * mm

    # レイアウト定数
    FONT_SIZE = 7.5
    LINE_H = 3.5 * mm
    LABEL_H = 6 * mm
    TEXT_PAD = 2.5 * mm  # カラム内テキスト左右パディング
    COL_GAP = 3 * mm
    HEADER_H = 9 * mm

    card_x = MARGIN_L
    card_w = CONTENT_W
    col_w = (card_w - COL_GAP * 2) / 3
    text_w = col_w - TEXT_PAD * 2

    for i, case in enumerate(cases):
        # 各カラムのテキスト行数を事前計算して高さを決定
        sections = [
            ("課題", case["challenge"], colors.HexColor("#fef2f2"),
             colors.HexColor("#f5c6cb"), colors.HexColor("#c62828")),
            ("解決策", case["solution"], COLOR_LIGHT_BG,
             colors.HexColor("#b3d4fc"), COLOR_PRIMARY),
            ("効果", case["effect"], COLOR_LIGHT_GREEN,
             colors.HexColor("#c8e6c9"), COLOR_ACCENT),
        ]

        max_lines = 0
        section_lines = []
        for _, text, _, _, _ in sections:
            wrapped = _wrap_text_lines(text, FONT_REGULAR, FONT_SIZE, text_w, c)
            section_lines.append(wrapped)
            max_lines = max(max_lines, len(wrapped))

        section_h = LABEL_H + TEXT_PAD + max_lines * LINE_H + TEXT_PAD
        total_card_h = HEADER_H + 2 * mm + section_h + 6 * mm  # ヘッダー+カラム+金額帯+余白

        if y - total_card_h < MARGIN_B + 12 * mm:
            draw_footer(c, page_num)
            c.showPage()
            page_num += 1
            y = draw_page_header(c, config)

        # ── 事例ヘッダー ──
        c.setFillColor(COLOR_PRIMARY)
        c.roundRect(card_x, y - HEADER_H, card_w, HEADER_H, 3, stroke=0, fill=1)
        c.setFont(FONT_BOLD, 11)
        c.setFillColor(colors.white)
        header_text = f"事例 {i + 1}: {case['label']}  |  {case['scenario']}"
        # ヘッダーテキストが長すぎる場合は切り詰め
        max_header_w = card_w - 40 * mm
        while c.stringWidth(header_text, FONT_BOLD, 11) > max_header_w and len(header_text) > 10:
            header_text = header_text[:-2] + "..."
        c.drawString(card_x + 4 * mm, y - 6.5 * mm, header_text)

        # サービス種別バッジ（ヘッダー右側）
        badge_text = case["service"]
        badge_w = c.stringWidth(badge_text, FONT_REGULAR, 7.5) + 5 * mm
        badge_x = card_x + card_w - badge_w - 4 * mm
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.white)
        c.roundRect(badge_x, y - 7.5 * mm, badge_w, 5 * mm, 2, stroke=1, fill=0)
        c.setFont(FONT_REGULAR, 7.5)
        c.drawString(badge_x + 2.5 * mm, y - 6 * mm, badge_text)

        y -= HEADER_H + 1.5 * mm

        # ── 3カラム描画 ──
        for j, ((label, text, bg, border, accent), wrapped) in enumerate(zip(sections, section_lines)):
            sx = card_x + j * (col_w + COL_GAP)

            # カラム背景
            c.setFillColor(bg)
            c.setStrokeColor(border)
            c.setLineWidth(0.6)
            c.roundRect(sx, y - section_h, col_w, section_h, 3, stroke=1, fill=1)

            # ラベルバー
            c.setFillColor(accent)
            c.roundRect(sx, y - LABEL_H, col_w, LABEL_H, 3, stroke=0, fill=1)
            c.setFont(FONT_BOLD, 8.5)
            c.setFillColor(colors.white)
            c.drawCentredString(sx + col_w / 2, y - LABEL_H + 1.5 * mm, label)

            # テキスト
            c.setFont(FONT_REGULAR, FONT_SIZE)
            c.setFillColor(colors.HexColor("#333333"))
            ty = y - LABEL_H - TEXT_PAD - LINE_H * 0.6
            for line_text in wrapped:
                c.drawString(sx + TEXT_PAD, ty, line_text)
                ty -= LINE_H

        y -= section_h + 1 * mm

        # 金額帯
        c.setFont(FONT_REGULAR, 8)
        c.setFillColor(COLOR_GRAY)
        c.drawRightString(card_x + card_w, y,
                          f"ご契約金額帯: {case['amount_range']}")
        y -= 8 * mm

    draw_footer(c, page_num)
    return page_num + 1


def draw_cta_page(c, industry: str, config: dict, page_num: int):
    """CTA（問い合わせ誘導）ページを描画"""
    y = PAGE_H - MARGIN_T

    # ヘッダー
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, PAGE_H - 3 * mm, PAGE_W, 3 * mm, stroke=0, fill=1)

    c.setFont(FONT_BOLD, 10)
    c.setFillColor(COLOR_PRIMARY)
    c.drawString(MARGIN_L, y, f"{config['title']} {config['subtitle']}")
    y -= 3 * mm
    c.setStrokeColor(COLOR_PRIMARY)
    c.setLineWidth(1)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 30 * mm

    # メッセージ
    c.setFont(FONT_BOLD, 18)
    c.setFillColor(colors.black)
    msg = "まずはお気軽にご相談ください"
    tw = c.stringWidth(msg, FONT_BOLD, 18)
    c.drawString((PAGE_W - tw) / 2, y, msg)
    y -= 15 * mm

    c.setFont(FONT_REGULAR, 11)
    c.setFillColor(COLOR_GRAY)
    lines = [
        "現場の課題やご要望をお聞かせいただければ、",
        "最適なドローン活用プランをご提案いたします。",
        "",
        "お見積りは無料です。",
    ]
    for line in lines:
        if line:
            tw = c.stringWidth(line, FONT_REGULAR, 11)
            c.drawString((PAGE_W - tw) / 2, y, line)
        y -= 7 * mm

    y -= 10 * mm

    # サービスメリットボックス
    benefits = [
        ("無料お見積り", "現場条件に合わせた最適プランをお見積り"),
        ("ワンストップ対応", "航空法申請・撮影・データ処理まで一括"),
        ("東海三県対応", "愛知・岐阜・三重を中心に機動的に対応"),
        ("安心の実績", "建設・測量業界での豊富な対応実績"),
    ]

    box_w = 70 * mm
    box_h = 25 * mm
    gap = 8 * mm
    total_w = box_w * 2 + gap
    start_x = (PAGE_W - total_w) / 2

    for idx, (title, desc) in enumerate(benefits):
        col = idx % 2
        row = idx // 2
        bx = start_x + col * (box_w + gap)
        by = y - row * (box_h + gap)

        c.setFillColor(COLOR_LIGHT_BG)
        c.setStrokeColor(COLOR_PRIMARY)
        c.setLineWidth(0.8)
        c.roundRect(bx, by - box_h, box_w, box_h, 3, stroke=1, fill=1)

        c.setFont(FONT_BOLD, 11)
        c.setFillColor(COLOR_PRIMARY)
        c.drawCentredString(bx + box_w / 2, by - 10 * mm, title)

        c.setFont(FONT_REGULAR, 8)
        c.setFillColor(COLOR_GRAY)
        # 説明文の折り返し
        chars = int(box_w / (8 * 0.55))
        if len(desc) > chars:
            line1 = desc[:chars]
            line2 = desc[chars:]
            c.drawCentredString(bx + box_w / 2, by - 16 * mm, line1)
            c.drawCentredString(bx + box_w / 2, by - 20 * mm, line2)
        else:
            c.drawCentredString(bx + box_w / 2, by - 17 * mm, desc)

    y -= 2 * (box_h + gap) + 20 * mm

    # 問い合わせ先ボックス
    contact_h = 45 * mm
    contact_w = 130 * mm
    contact_x = (PAGE_W - contact_w) / 2
    c.setFillColor(COLOR_PRIMARY)
    c.roundRect(contact_x, y - contact_h, contact_w, contact_h, 5, stroke=0, fill=1)

    cy = y - 10 * mm
    c.setFont(FONT_BOLD, 14)
    c.setFillColor(colors.white)
    c.drawCentredString(PAGE_W / 2, cy, "お問い合わせ")
    cy -= 10 * mm

    c.setFont(FONT_REGULAR, 11)
    c.drawCentredString(PAGE_W / 2, cy, COMPANY["name"])
    cy -= 7 * mm

    c.setFont(FONT_REGULAR, 10)
    contact_lines = [
        f"メール: {COMPANY['email']}",
        f"Web: {COMPANY['url']}",
        f"{COMPANY['zip']} {COMPANY['addr']}",
    ]
    for line in contact_lines:
        c.drawCentredString(PAGE_W / 2, cy, line)
        cy -= 6 * mm

    # フッタ
    draw_footer(c, page_num)


def draw_footer(c, page_num: int):
    """ページフッタ"""
    c.setFont(FONT_REGULAR, 7)
    c.setFillColor(COLOR_GRAY)
    c.drawCentredString(PAGE_W / 2, MARGIN_B - 5 * mm,
                        f"{COMPANY['name']}  |  {COMPANY['url']}")
    c.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 5 * mm, f"- {page_num} -")

    # 下部アクセントバー
    c.setFillColor(COLOR_PRIMARY)
    c.rect(0, 0, PAGE_W, 3 * mm, stroke=0, fill=1)


# ── PDF生成メイン ──────────────────────────────────
def generate_case_study_pdf(industry: str, records: list, output_dir: Path) -> Path:
    """業種別事例PDFを生成"""
    register_fonts()

    config = INDUSTRY_CONFIG.get(industry)
    if not config:
        print(f"WARNING: 業種 '{industry}' の設定がありません。デフォルト設定を使用します。")
        config = INDUSTRY_CONFIG["その他"].copy()
        config["title"] = f"{industry}向け"

    filtered = filter_by_industry(records, industry)
    stats = compute_stats(filtered)
    cases = build_case_studies(filtered, industry, max_cases=3)

    # ファイル名
    safe_industry = industry.replace("/", "_").replace(" ", "")
    filename = f"事例集_{safe_industry}_{datetime.now().strftime('%Y%m%d')}.pdf"
    output_path = output_dir / filename

    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle(f"{config['title']} {config['subtitle']}")
    c.setAuthor(COMPANY["name"])

    # ページ1: 表紙
    draw_cover_page(c, industry, config, stats)
    c.showPage()

    # ページ2: 課題と解決策
    draw_challenges_page(c, industry, config, stats, page_num=2)
    c.showPage()

    # ページ3+: 事例詳細（事例数に応じて複数ページになる場合あり）
    next_page = draw_case_detail_pages(c, industry, config, cases, start_page=3)
    c.showPage()

    # 最終ページ: CTA
    draw_cta_page(c, industry, config, page_num=next_page)
    c.showPage()

    c.save()
    return output_path


# ── CLI ────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="業種別事例PDF自動生成")
    parser.add_argument("--industry", help="業種名（例: ゼネコン, コンサルタント, 不動産, 官公庁）")
    parser.add_argument("--all", action="store_true", help="全業種一括生成")
    parser.add_argument("--list", action="store_true", help="業種一覧と件数を表示")
    parser.add_argument("--csv", help=f"入力CSVパス（デフォルト: {DATA_CSV}）")
    parser.add_argument("--output-dir", help=f"出力ディレクトリ（デフォルト: {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--min-cases", type=int, default=0,
                        help="最低受注件数（この件数未満の業種はスキップ）")
    args = parser.parse_args()

    csv_path = Path(args.csv) if args.csv else DATA_CSV
    if not csv_path.exists():
        print(f"ERROR: CSVファイルが見つかりません: {csv_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_data(csv_path)
    print(f"読み込み: {len(records)}件の有効レコード")

    # 業種集計
    industry_counts = defaultdict(int)
    industry_won = defaultdict(int)
    for r in records:
        ind = r["業種"]
        if ind:
            industry_counts[ind] += 1
            if "受注100" in r.get("出典", ""):
                industry_won[ind] += 1

    if args.list:
        print("\n業種一覧:")
        print(f"{'業種':<15} {'全案件':>6} {'受注':>6}")
        print("-" * 30)
        for ind, cnt in sorted(industry_counts.items(), key=lambda x: -x[1]):
            won = industry_won.get(ind, 0)
            configured = "○" if ind in INDUSTRY_CONFIG else "×"
            print(f"{ind:<15} {cnt:>6} {won:>6}  設定:{configured}")
        return

    if args.industry:
        industries = [args.industry]
    elif args.all:
        industries = [ind for ind in industry_counts.keys()
                      if industry_won.get(ind, 0) >= args.min_cases]
    else:
        parser.print_help()
        print("\nERROR: --industry または --all を指定してください。")
        sys.exit(1)

    generated = []
    for industry in industries:
        won_count = industry_won.get(industry, 0)
        total_count = industry_counts.get(industry, 0)
        if total_count == 0 and not args.industry:
            print(f"SKIP: {industry} - レコードなし")
            continue

        print(f"\n生成中: {industry}（受注{won_count}件 / 全{total_count}件）")
        output_path = generate_case_study_pdf(industry, records, output_dir)
        generated.append((industry, output_path))
        print(f"  → {output_path}")

    print(f"\n完了: {len(generated)}件のPDFを生成しました")
    for ind, path in generated:
        print(f"  {ind}: {path}")


if __name__ == "__main__":
    main()
