#!/usr/bin/env python3
"""
被リンク獲得パイプライン（施策3: 被リンク獲得の自動化）

以下のリストを自動生成:
  a. 業界メディア・ポータルサイト（ドローン系、建設IT系）
  b. 公的機関ディレクトリ（商工会議所、中小企業基盤整備機構）
  c. 地元メディア
  d. まとめ・比較サイト

各登録先のURL + 申請手順 + 下書きメール文面を生成。

Usage:
    python3 backlink_outreach.py --generate    # リスト生成
    python3 backlink_outreach.py --drafts      # メール下書き生成
    python3 backlink_outreach.py --status       # 進捗確認
    python3 backlink_outreach.py --site tokaiair  # tokaiair.comのみ
    python3 backlink_outreach.py --site tomoshi    # tomoshi.jpのみ
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR.parent / "content" / "backlink_outreach"


# ── 被リンク獲得先リスト ──

TOKAIAIR_TARGETS = [
    # カテゴリA: 業界メディア・ポータル
    {
        "category": "業界メディア",
        "name": "DRONE.jp",
        "url": "https://www.drone.jp/",
        "type": "プレスリリース掲載",
        "steps": [
            "お問い合わせフォームからプレスリリース掲載依頼",
            "「ドローン測量の実績データ公開」をニュースバリューとして提案",
            "市場レポートページへのリンクを含める",
        ],
        "priority": "高",
        "status": "未着手",
    },
    {
        "category": "業界メディア",
        "name": "ドローンジャーナル",
        "url": "https://dronejournal.impress.co.jp/",
        "type": "取材依頼・寄稿",
        "steps": [
            "編集部に取材提案メール送信",
            "テーマ: 「中小測量会社のドローン活用実態」",
            "自社データに基づく記事を寄稿提案",
        ],
        "priority": "高",
        "status": "未着手",
    },
    {
        "category": "業界メディア",
        "name": "建設ITワールド",
        "url": "https://ken-it.world/",
        "type": "事例掲載",
        "steps": [
            "掲載依頼フォームから応募",
            "「ドローン測量×DX」の事例として提案",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "業界メディア",
        "name": "日経クロステック",
        "url": "https://xtech.nikkei.com/",
        "type": "プレスリリース",
        "steps": [
            "PR TIMESまたは直接プレスリリース配信",
            "「東海エリア初のドローン測量市場レポート公開」として配信",
        ],
        "priority": "中",
        "status": "未着手",
    },

    # カテゴリB: 公的機関
    {
        "category": "公的機関",
        "name": "名古屋商工会議所",
        "url": "https://www.nagoya-cci.or.jp/",
        "type": "会員企業紹介・事業者検索登録",
        "steps": [
            "会員であれば事業者検索に自社情報登録",
            "「ドローン測量」カテゴリでの登録申請",
            "会報誌への寄稿打診",
        ],
        "priority": "高",
        "status": "未着手",
    },
    {
        "category": "公的機関",
        "name": "愛知県産業振興課",
        "url": "https://www.pref.aichi.jp/sangyoshinko/",
        "type": "事業者データベース登録",
        "steps": [
            "あいちの技術・製品ガイドへの登録申請",
            "ドローン測量を得意技術として申請",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "公的機関",
        "name": "中小企業基盤整備機構（J-Net21）",
        "url": "https://j-net21.smrj.go.jp/",
        "type": "事例掲載",
        "steps": [
            "「ビジネスQ&A」「事例集」への掲載依頼",
            "「ドローン活用で測量効率化」のテーマで応募",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "公的機関",
        "name": "国土交通省 i-Construction",
        "url": "https://www.mlit.go.jp/tec/i-construction/",
        "type": "活用事例",
        "steps": [
            "i-Construction事例集への掲載申請",
            "国交省の地方整備局担当にコンタクト",
        ],
        "priority": "高",
        "status": "未着手",
    },

    # カテゴリC: 地域メディア
    {
        "category": "地域メディア",
        "name": "名古屋経済新聞",
        "url": "https://nagoya.keizai.biz/",
        "type": "プレスリリース掲載",
        "steps": [
            "プレスリリース投稿フォームから送信",
            "「名古屋発ドローン測量会社がデータレポート公開」",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "地域メディア",
        "name": "中部経済新聞",
        "url": "https://www.chukei-news.co.jp/",
        "type": "取材依頼",
        "steps": [
            "編集部にプレスリリース送付",
            "中部エリアのDX事例として提案",
        ],
        "priority": "低",
        "status": "未着手",
    },

    # カテゴリD: 比較・まとめサイト
    {
        "category": "比較サイト",
        "name": "ドローン測量比較まとめ系ブログ",
        "url": "検索で特定",
        "type": "掲載依頼",
        "steps": [
            "Google で「ドローン測量 おすすめ」「ドローン測量 比較」を検索",
            "まとめ記事の著者にメールで掲載依頼",
            "自社の強み（実績データ公開・東海エリア特化）を訴求",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "比較サイト",
        "name": "EMEAO!（エミーオ）",
        "url": "https://emeao.jp/",
        "type": "サービス登録",
        "steps": [
            "ドローン測量カテゴリでの事業者登録",
            "対応エリア: 愛知・岐阜・三重・静岡",
        ],
        "priority": "低",
        "status": "未着手",
    },
]

TOMOSHI_TARGETS = [
    {
        "category": "業界メディア",
        "name": "事業承継ひろば",
        "url": "https://jigyoshokei.go.jp/",
        "type": "事例掲載",
        "steps": [
            "事業承継・引継ぎ支援センター経由で事例提出",
            "「AI活用による事業承継支援」として掲載依頼",
        ],
        "priority": "高",
        "status": "未着手",
    },
    {
        "category": "業界メディア",
        "name": "M&A Online",
        "url": "https://maonline.jp/",
        "type": "寄稿",
        "steps": [
            "寄稿提案メール送信",
            "「AI×事業承継で属人化リスクを可視化」テーマ",
        ],
        "priority": "中",
        "status": "未着手",
    },
    {
        "category": "公的機関",
        "name": "中小企業庁 事業承継ポータル",
        "url": "https://shoukei.smrj.go.jp/",
        "type": "支援機関登録",
        "steps": [
            "事業承継支援機関としての登録申請",
            "AI活用のユニークな支援手法をPR",
        ],
        "priority": "高",
        "status": "未着手",
    },
    {
        "category": "地域メディア",
        "name": "名古屋商工会議所",
        "url": "https://www.nagoya-cci.or.jp/",
        "type": "セミナー開催・紹介",
        "steps": [
            "事業承継セミナー登壇の打診",
            "「AI活用で事業承継を加速」テーマ",
        ],
        "priority": "高",
        "status": "未着手",
    },
]


# ── メールテンプレート ──

EMAIL_TEMPLATES = {
    "プレスリリース掲載": {
        "subject": "【プレスリリース】{company} - {topic}",
        "body": """
{editor_name} 様

突然のご連絡失礼いたします。
{company}の{sender_name}と申します。

{media_name}に、弊社の取り組みについてプレスリリースの掲載をお願いしたくご連絡いたしました。

■ トピック
{topic}

■ 概要
{summary}

■ ニュースバリュー
{news_value}

■ 掲載可能な素材
- プレスリリース本文（テキスト/PDF）
- 写真素材（ドローン・現場写真）
- データ・グラフ素材

ご検討いただけますと幸いです。
詳細資料のご送付やインタビュー対応も可能です。

何卒よろしくお願いいたします。

{signature}
""",
    },
    "事例掲載": {
        "subject": "【事例掲載のお願い】{company} - {topic}",
        "body": """
ご担当者様

{company}の{sender_name}と申します。

{media_name}への事例掲載のご相談でご連絡いたしました。

弊社は{company_desc}を行っております。
{topic}について、御媒体の読者様にとっても参考になる事例かと存じます。

■ 事例概要
{summary}

■ 提供可能な情報
- 導入前後の比較データ
- 担当者インタビュー
- 写真・動画素材

ご検討いただけますと幸いです。

{signature}
""",
    },
    "寄稿": {
        "subject": "【寄稿のご提案】{topic} - {company}",
        "body": """
{editor_name} 様

{company}の{sender_name}と申します。

{media_name}への寄稿をご提案させていただきたく、ご連絡いたしました。

■ テーマ
{topic}

■ 概要
{summary}

■ 筆者プロフィール
{author_profile}

■ 想定文字数
2,000〜3,000字程度

ご興味をお持ちいただけましたら、構成案をお送りいたします。

{signature}
""",
    },
}


def generate_target_list(site="all"):
    """ターゲットリストを生成"""
    targets = {}
    if site in ("all", "tokaiair"):
        targets["tokaiair"] = TOKAIAIR_TARGETS
    if site in ("all", "tomoshi"):
        targets["tomoshi"] = TOMOSHI_TARGETS
    return targets


def generate_email_drafts(targets, site_key):
    """メール下書きを生成"""
    drafts = []

    if site_key == "tokaiair":
        company = "東海エアサービス株式会社"
        company_desc = "愛知県名古屋市を拠点にドローン測量サービス"
        sender = "國本 洋輔"
        topic_default = "東海エリア初のドローン測量市場レポート（自社実績ベース）公開"
        news_value = "業界初の実績ベース市場レポートを一般公開。AIで量産されるSEO記事と差別化する「実データの公開資産化」戦略。"
        signature = "國本 洋輔\n東海エアサービス株式会社\nTEL: 052-720-5885\nhttps://www.tokaiair.com/\ninfo@tokaiair.com"
    else:
        company = "TOMOSHI"
        company_desc = "AI技術を活用した事業承継支援"
        sender = "國本 洋輔"
        topic_default = "AI×事業承継で属人化リスクを可視化する新サービス"
        news_value = "中小企業の「暗黙知」をAIで定量化し、事業承継のリスクを見える化する先進的アプローチ。"
        signature = "國本 洋輔\nTOMOSHI\nhttps://tomoshi.jp/\ninfo@tomoshi.jp"

    for target in targets:
        template_type = target["type"]
        template = EMAIL_TEMPLATES.get(template_type)
        if not template:
            continue

        draft = {
            "to": target["name"],
            "target_url": target["url"],
            "subject": template["subject"].format(
                company=company,
                topic=topic_default,
            ),
            "body": template["body"].format(
                editor_name="ご担当者",
                company=company,
                company_desc=company_desc,
                sender_name=sender,
                media_name=target["name"],
                topic=topic_default,
                summary=f"弊社の実績データに基づく{topic_default}について",
                news_value=news_value,
                author_profile=f"{sender}（{company}代表）",
                signature=signature,
            ),
            "priority": target["priority"],
            "status": "下書き",
        }
        drafts.append(draft)

    return drafts


def save_outputs(targets, drafts, site):
    """成果物を保存"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ターゲットリスト
    for site_key, target_list in targets.items():
        path = OUTPUT_DIR / f"{site_key}_targets.json"
        path.write_text(
            json.dumps(target_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  保存: {path}")

    # メール下書き
    for site_key, draft_list in drafts.items():
        path = OUTPUT_DIR / f"{site_key}_email_drafts.json"
        path.write_text(
            json.dumps(draft_list, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"  保存: {path}")

    # マークダウンサマリー
    md_lines = [
        "# 被リンク獲得ターゲットリスト",
        f"生成日: {datetime.now().strftime('%Y-%m-%d')}",
        "",
    ]

    for site_key, target_list in targets.items():
        md_lines.append(f"## {site_key}")
        md_lines.append("")

        for cat in ["業界メディア", "公的機関", "地域メディア", "比較サイト"]:
            cat_targets = [t for t in target_list if t["category"] == cat]
            if cat_targets:
                md_lines.append(f"### {cat}")
                for t in cat_targets:
                    md_lines.append(
                        f"- **{t['name']}** ({t['url']}) "
                        f"[{t['type']}] 優先度:{t['priority']}"
                    )
                    for step in t["steps"]:
                        md_lines.append(f"  - {step}")
                md_lines.append("")

    summary_path = OUTPUT_DIR / "backlink_targets_summary.md"
    summary_path.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"  保存: {summary_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="被リンク獲得パイプライン")
    parser.add_argument("--generate", action="store_true", help="リスト生成")
    parser.add_argument("--drafts", action="store_true", help="メール下書き生成")
    parser.add_argument("--status", action="store_true", help="進捗確認")
    parser.add_argument("--site", choices=["tokaiair", "tomoshi", "all"],
                        default="all", help="対象サイト")
    args = parser.parse_args()

    if not any([args.generate, args.drafts, args.status]):
        parser.print_help()
        sys.exit(1)

    print("=== 被リンク獲得パイプライン ===")

    if args.generate or args.drafts:
        targets = generate_target_list(args.site)

        drafts = {}
        if args.drafts:
            for site_key, target_list in targets.items():
                drafts[site_key] = generate_email_drafts(target_list, site_key)
                print(f"  {site_key}: {len(drafts[site_key])}件の下書き生成")

        save_outputs(targets, drafts, args.site)
        print("=== 完了 ===")

    if args.status:
        if OUTPUT_DIR.exists():
            for f in sorted(OUTPUT_DIR.iterdir()):
                print(f"  {f.name}")
        else:
            print("  まだ生成されていません。--generate を実行してください。")


if __name__ == "__main__":
    main()
