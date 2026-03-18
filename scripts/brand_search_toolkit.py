#!/usr/bin/env python3
"""
ブランド指名検索増加ツールキット（施策5）

以下を生成:
  - 名刺・メール署名・見積書のURL統一テンプレート
  - 紙媒体QRコード → 検索誘導LP設計
  - X/LinkedIn投稿テンプレート（定期発信用）

Usage:
    python3 brand_search_toolkit.py --generate    # 全テンプレート生成
    python3 brand_search_toolkit.py --social       # SNS投稿テンプレートのみ
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "content" / "brand_toolkit"


# ── ブランド統一情報 ──

BRAND_INFO = {
    "tokaiair": {
        "company": "東海エアサービス株式会社",
        "url": "https://www.tokaiair.com/",
        "search_term": "ドローン測量 東海エアサービス",
        "tagline": "東海エリア特化のドローン測量",
        "phone": "052-720-5885",
        "email": "info@tokaiair.com",
        "address": "名古屋市",
    },
    "tomoshi": {
        "company": "TOMOSHI",
        "url": "https://tomoshi.jp/",
        "search_term": "TOMOSHI 事業承継",
        "tagline": "AI×事業承継で「見えないリスク」を可視化",
        "email": "info@tomoshi.jp",
    },
}


# ── メール署名テンプレート ──

EMAIL_SIGNATURES = {
    "tokaiair_ceo": """
━━━━━━━━━━━━━━━━━━━━━━━━━
國本 洋輔（くにもと ようすけ）
東海エアサービス株式会社 代表

ドローン測量のご相談はお気軽に
https://www.tokaiair.com/

TEL: 052-720-5885
MAIL: info@tokaiair.com

▼ 土量計算ツール（無料）
https://www.tokaiair.com/tools/earthwork/calculator/

▼ 東海エリア ドローン測量 市場レポート
https://www.tokaiair.com/drone-survey-market-report/
━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    "tokaiair_sales": """
━━━━━━━━━━━━━━━━━━━━━━━━━
{name}
東海エアサービス株式会社

TEL: 052-720-5885
MAIL: {email}
WEB: https://www.tokaiair.com/

「ドローン測量 東海エアサービス」で検索
━━━━━━━━━━━━━━━━━━━━━━━━━
""",
    "tomoshi": """
━━━━━━━━━━━━━━━━━━━━━━━━━
國本 洋輔
TOMOSHI | AI×事業承継

https://tomoshi.jp/
MAIL: info@tomoshi.jp

▼ 属人化リスク無料診断
https://tomoshi.jp/risk-assessment/
━━━━━━━━━━━━━━━━━━━━━━━━━
""",
}


# ── SNS投稿テンプレート ──

SOCIAL_TEMPLATES = {
    "tokaiair_x": [
        {
            "type": "実績紹介",
            "template": """ドローン測量の現場から。
{area_name}で{area_size}の測量を実施しました。

従来の人力測量と比較して:
- 作業時間: 約{time_saving}
- コスト: 約{cost_saving}

詳しい費用目安はこちら
https://www.tokaiair.com/drone-survey-market-report/

#ドローン測量 #建設DX #土量計算 #東海エリア""",
        },
        {
            "type": "知見共有",
            "template": """【ドローン測量Tips】{tip_title}

{tip_content}

当社の実績データに基づく費用目安は市場レポートで公開中:
https://www.tokaiair.com/drone-survey-market-report/

#ドローン測量 #建設DX #i-Construction""",
        },
        {
            "type": "データ発信",
            "template": """東海エリアのドローン測量、当社実績ベースの統計データを公開しています。

- 業種別の平均単価
- 面積帯別のコスト目安
- 季節変動トレンド

「ドローン測量の相場感が分からない」方はご参考に:
https://www.tokaiair.com/drone-survey-market-report/

#ドローン測量 #費用相場""",
        },
    ],
    "tokaiair_linkedin": [
        {
            "type": "ソートリーダーシップ",
            "template": """建設業界のDX推進において、ドローン測量はもはや「特殊技術」ではなく「標準ツール」になりつつあります。

当社（東海エアサービス株式会社）では、これまでの測量実績データを市場レポートとして公開しています。

なぜ自社データを公開するのか？
- 業界全体の透明性向上に貢献したい
- 「相場が分からない」という導入障壁を下げたい
- 実績データこそが最も信頼できる情報源

レポートはこちら:
https://www.tokaiair.com/drone-survey-market-report/

#建設DX #ドローン測量 #iConstruction #東海エリア""",
        },
    ],
    "tomoshi_x": [
        {
            "type": "課題提起",
            "template": """「社長が倒れたら会社が止まる」

この状態を放置していませんか？

属人化リスクは目に見えないからこそ危険。
AIで定量化すると、思わぬリスクが見えてきます。

無料診断はこちら:
https://tomoshi.jp/risk-assessment/

#事業承継 #属人化 #中小企業 #経営リスク""",
        },
        {
            "type": "知見共有",
            "template": """事業承継で最も見落とされがちなリスク:
「暗黙知の喪失」

マニュアルに書けない判断基準、人脈、ノウハウ。
これらを引き継げるかが承継成否を分けます。

TOMOSHIではAIを活用して暗黙知を可視化。
https://tomoshi.jp/

#事業承継 #AI活用 #暗黙知""",
        },
    ],
    "tomoshi_linkedin": [
        {
            "type": "ソートリーダーシップ",
            "template": """事業承継の本質的課題は「人」と「知識」の引き継ぎです。

財務・法務の承継は専門家がいますが、
「この取引先にはこう対応する」
「この現場ではこう判断する」
といった暗黙知の承継は手つかずのまま。

TOMOSHIでは、AI技術を活用してこの暗黙知を構造化・可視化し、
承継リスクの定量評価を行っています。

https://tomoshi.jp/

#事業承継 #中小企業 #AI #DX""",
        },
    ],
}


# ── QRコード設計 ──

QR_DESIGNS = {
    "tokaiair_card": {
        "url": "https://www.tokaiair.com/?utm_source=card&utm_medium=qr&utm_campaign=brand",
        "text": "ドローン測量のご相談は\n「東海エアサービス」で検索",
        "placement": "名刺裏面 右下",
    },
    "tokaiair_quote": {
        "url": "https://www.tokaiair.com/drone-survey-market-report/?utm_source=quote&utm_medium=qr",
        "text": "費用目安は市場レポートでご確認いただけます",
        "placement": "見積書フッター",
    },
    "tokaiair_pamphlet": {
        "url": "https://www.tokaiair.com/tools/earthwork/calculator/?utm_source=pamphlet&utm_medium=qr",
        "text": "無料 土量計算ツール",
        "placement": "パンフレット最終ページ",
    },
    "tomoshi_card": {
        "url": "https://tomoshi.jp/?utm_source=card&utm_medium=qr&utm_campaign=brand",
        "text": "「TOMOSHI 事業承継」で検索",
        "placement": "名刺裏面",
    },
}


def generate_all():
    """全テンプレートを生成"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # メール署名
    sig_path = OUTPUT_DIR / "email_signatures.md"
    sig_lines = ["# メール署名テンプレート", f"生成日: {datetime.now().strftime('%Y-%m-%d')}", ""]
    for key, sig in EMAIL_SIGNATURES.items():
        sig_lines.append(f"## {key}")
        sig_lines.append("```")
        sig_lines.append(sig.strip())
        sig_lines.append("```")
        sig_lines.append("")
    sig_path.write_text("\n".join(sig_lines), encoding="utf-8")
    print(f"  保存: {sig_path}")

    # SNS投稿テンプレート
    social_path = OUTPUT_DIR / "social_templates.json"
    social_path.write_text(
        json.dumps(SOCIAL_TEMPLATES, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  保存: {social_path}")

    # SNS投稿テンプレート（マークダウン版）
    social_md_path = OUTPUT_DIR / "social_templates.md"
    social_lines = [
        "# SNS投稿テンプレート",
        f"生成日: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## 運用ルール",
        "- 週2-3回の投稿を目標",
        "- 実績・データ系は月1-2回",
        "- Tips系は週1回",
        "- 社外秘（顧客名・具体金額）は絶対に含めない",
        "",
    ]
    for platform, templates in SOCIAL_TEMPLATES.items():
        social_lines.append(f"## {platform}")
        for t in templates:
            social_lines.append(f"### [{t['type']}]")
            social_lines.append("```")
            social_lines.append(t["template"].strip())
            social_lines.append("```")
            social_lines.append("")
    social_md_path.write_text("\n".join(social_lines), encoding="utf-8")
    print(f"  保存: {social_md_path}")

    # QRコード設計
    qr_path = OUTPUT_DIR / "qr_code_designs.md"
    qr_lines = [
        "# QRコード設計（ブランド検索誘導）",
        f"生成日: {datetime.now().strftime('%Y-%m-%d')}",
        "",
        "## 目的",
        "紙媒体からの流入を「ブランド検索」として計測可能にする。",
        "UTMパラメータ付きURLでQRコードを生成し、GA4で効果測定。",
        "",
    ]
    for key, design in QR_DESIGNS.items():
        qr_lines.append(f"### {key}")
        qr_lines.append(f"- URL: `{design['url']}`")
        qr_lines.append(f"- テキスト: {design['text']}")
        qr_lines.append(f"- 配置: {design['placement']}")
        qr_lines.append(f"- QR生成: https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={design['url']}")
        qr_lines.append("")
    qr_path.write_text("\n".join(qr_lines), encoding="utf-8")
    print(f"  保存: {qr_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ブランド検索増加ツールキット")
    parser.add_argument("--generate", action="store_true", help="全テンプレート生成")
    parser.add_argument("--social", action="store_true", help="SNSテンプレートのみ")
    args = parser.parse_args()

    if not any([args.generate, args.social]):
        parser.print_help()
        sys.exit(1)

    print("=== ブランド検索増加ツールキット ===")
    generate_all()
    print("=== 完了 ===")


if __name__ == "__main__":
    main()
