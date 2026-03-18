#!/usr/bin/env python3
"""
メールナーチャリングシーケンス自動化

2つのシーケンスを管理:
  1. 問い合わせ後ナーチャリング（5通）: Day 0/3/7/14/30
  2. 納品後リピート促進（3通）: Day 1/30/90

Usage:
  python3 email_nurturing_sequences.py --scan          # 新規対象を検出→キューに追加
  python3 email_nurturing_sequences.py --send          # 送信時刻が来たメールを送信
  python3 email_nurturing_sequences.py --dry-run       # 送信せず内容を表示
  python3 email_nurturing_sequences.py --list          # キュー一覧表示
  python3 email_nurturing_sequences.py --scan --send   # 検出+送信を一括実行
"""

import json
import os
import sys
import time
import base64
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"
# GitHub Actions対応: ローカルになければtas-automation/scripts/配下を探す
if not CONFIG_FILE.exists():
    CONFIG_FILE = SCRIPT_DIR / "tas-automation" / "scripts" / "automation_config.json"

STATE_FILE = SCRIPT_DIR / "nurturing_state.json"
QUEUE_FILE = SCRIPT_DIR / "nurturing_queue.json"
LOG_FILE = SCRIPT_DIR / "nurturing_email.log"

# ── 設定読み込み（環境変数 > config file） ──
def load_config():
    cfg = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
    return {
        "lark_app_id": os.environ.get("LARK_APP_ID", cfg.get("lark", {}).get("app_id", "")),
        "lark_app_secret": os.environ.get("LARK_APP_SECRET", cfg.get("lark", {}).get("app_secret", "")),
        "crm_base_token": os.environ.get("CRM_BASE_TOKEN", cfg.get("lark", {}).get("crm_base_token", "")),
        "wp_base_url": cfg.get("wordpress", {}).get("base_url", "https://tokaiair.com/wp-json/wp/v2").replace("/wp/v2", ""),
        "wp_user": os.environ.get("WP_USER", cfg.get("wordpress", {}).get("user", "")),
        "wp_app_password": os.environ.get("WP_APP_PASSWORD", cfg.get("wordpress", {}).get("app_password", "")),
        "anthropic_api_key": os.environ.get("ANTHROPIC_API_KEY", cfg.get("anthropic", {}).get("api_key", "")),
        "lark_webhook_url": os.environ.get("LARK_WEBHOOK_URL", cfg.get("notifications", {}).get("lark_webhook_url", "")),
    }

CONFIG = load_config()

# CRM Table IDs
TABLE_CONTACTS = "tblN53hFIQoo4W8j"
TABLE_ORDERS = "tbldLj2iMJYocct6"  # 受注台帳
TABLE_ACCOUNTS = "tblTfGScQIdLTYxA"
TABLE_EMAIL_LOG = "tblfBahatPZMJEM5"

# Lark open_ids
CEO_OPEN_ID = "ou_d2e2e520a442224ea9d987c6186341ce"

# セーフガード設定
MAX_SENDS_PER_DAY = 15         # 1日の送信上限（5→15に引き上げ）

# テスト・無効レコードの除外パターン
EXCLUDE_PATTERNS = [
    "test", "annai", "テスト", "dummy", "sample",
    "@example.com", "@test.com",
]


def run_email_review(subject, body, to_email, from_email="info@tokaiair.com"):
    """送信前にreview_agent.pyのemailプロファイルでチェック。CRITICAL=送信中止"""
    try:
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        from review_agent import review
        content = f"To: {to_email}\nFrom: {from_email}\nSubject: {subject}\n\n{body}"
        result = review("email", content, output_json=True)
        return result
    except Exception as e:
        log(f"  レビューエージェント実行エラー（送信は続行）: {e}")
        return {"verdict": "OK", "issues": [], "summary": f"レビュースキップ: {e}"}


COMPANY_INFO = {
    "name": "東海エアサービス株式会社",
    "url": "https://www.tokaiair.com/",
    "phone": "052-720-5885",
    "mobile": "050-7117-7141",
    "email": "info@tokaiair.com",
    "services": [
        "ドローン測量（公共測量対応・i-Construction）",
        "3次元点群計測・図面化",
        "建物赤外線調査（外壁タイル浮き等）",
        "眺望撮影・空撮",
        "太陽光パネル点検",
    ],
}

SIGNATURE_HTML = f"""
<br>
<div style="border-top:1px solid #ccc;padding-top:12px;margin-top:20px;font-size:13px;color:#555;">
  <strong>{COMPANY_INFO['name']}</strong><br>
  TEL: {COMPANY_INFO['phone']}<br>
  Web: <a href="{COMPANY_INFO['url']}">{COMPANY_INFO['url']}</a><br>
  Email: {COMPANY_INFO['email']}
</div>
"""

SIGNATURE_TEXT = f"""
──────────────────
{COMPANY_INFO['name']}
TEL: {COMPANY_INFO['phone']}
Web: {COMPANY_INFO['url']}
Email: {COMPANY_INFO['email']}
"""

# ──────────────────────────────────────────
# シーケンス1: 問い合わせ後ナーチャリング（5通）
# ──────────────────────────────────────────
INQUIRY_SEQUENCE = [
    {
        "step": 1,
        "day": 0,
        "key": "inquiry_day0",
        "label": "お問い合わせお礼",
        "subject": "お問い合わせありがとうございます｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>この度は{company_name}にお問い合わせいただき、誠にありがとうございます。</p>

<p>ご依頼内容を確認のうえ、担当者より改めてご連絡いたします。<br>
通常、1営業日以内にご回答しておりますので、少々お待ちください。</p>

<p>お急ぎの場合は、お電話でもお気軽にご連絡ください。<br>
TEL: <a href="tel:{phone}">{phone}</a></p>

<p>今後ともよろしくお願いいたします。</p>
""",
        "text": """{contact_name} 様

この度は{company_name}にお問い合わせいただき、誠にありがとうございます。

ご依頼内容を確認のうえ、担当者より改めてご連絡いたします。
通常、1営業日以内にご回答しておりますので、少々お待ちください。

お急ぎの場合は、お電話でもお気軽にご連絡ください。
TEL: {phone}

今後ともよろしくお願いいたします。
""",
    },
    {
        "step": 2,
        "day": 3,
        "key": "inquiry_day3",
        "label": "よくある疑問3選",
        "subject": "ドローン測量でよくある疑問3選｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>先日はお問い合わせいただきありがとうございました。<br>
{company_name}の國本です。</p>

<p>ドローン測量をご検討中のお客様からよくいただくご質問を3つご紹介します。</p>

<h3 style="color:#1a5276;margin-bottom:4px;">Q1. 従来測量と比べてどのくらい早いですか？</h3>
<p style="margin-top:4px;">一般的な現場（1〜5ha）で、<strong>現場作業は従来の約1/3〜1/5の時間</strong>で完了します。<br>
交通規制や立入制限のある現場でも、上空からの計測で効率的に対応できます。</p>

<h3 style="color:#1a5276;margin-bottom:4px;">Q2. 精度はどのくらいですか？</h3>
<p style="margin-top:4px;">GCP（地上基準点）を設置することで、<strong>水平・垂直ともに±3cm以内</strong>の精度を確保。<br>
国土交通省のi-Construction基準に準拠した公共測量にも対応しています。</p>

<h3 style="color:#1a5276;margin-bottom:4px;">Q3. 費用はどのくらいですか？</h3>
<p style="margin-top:4px;">現場の規模や条件によりますが、<strong>従来測量と同等〜2割減</strong>が目安です。<br>
人件費・工期短縮を含めたトータルコストで比較すると、大幅なコスト削減になるケースが多いです。</p>

<p>詳しくは費用相場の解説記事もご参考ください：<br>
<a href="https://www.tokaiair.com/drone-survey-cost/">ドローン測量の費用相場｜料金体系と見積のポイント</a></p>

<p>ご不明点がございましたら、お気軽にご連絡ください。</p>
""",
        "text": """{contact_name} 様

先日はお問い合わせいただきありがとうございました。
{company_name}の國本です。

ドローン測量をご検討中のお客様からよくいただくご質問を3つご紹介します。

■ Q1. 従来測量と比べてどのくらい早いですか？
一般的な現場（1〜5ha）で、現場作業は従来の約1/3〜1/5の時間で完了します。
交通規制や立入制限のある現場でも、上空からの計測で効率的に対応できます。

■ Q2. 精度はどのくらいですか？
GCP（地上基準点）を設置することで、水平・垂直ともに±3cm以内の精度を確保。
国土交通省のi-Construction基準に準拠した公共測量にも対応しています。

■ Q3. 費用はどのくらいですか？
現場の規模や条件によりますが、従来測量と同等〜2割減が目安です。
人件費・工期短縮を含めたトータルコストで比較すると、大幅なコスト削減になるケースが多いです。

詳しくはこちら: https://www.tokaiair.com/drone-survey-cost/

ご不明点がございましたら、お気軽にご連絡ください。
""",
    },
    {
        "step": 3,
        "day": 7,
        "key": "inquiry_day7",
        "label": "導入事例紹介",
        "subject": "導入事例：工期50%短縮を実現したドローン測量｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
先日のお問い合わせ、その後いかがでしょうか。</p>

<p>今回は、実際にドローン測量を導入いただいたお客様の事例をご紹介します。</p>

<div style="background:#f0f7fb;border-left:4px solid #2e86c1;padding:16px;margin:16px 0;">
  <strong style="color:#1a5276;">【事例】建設コンサルタント会社様 ― 道路改良工事の測量</strong><br><br>
  <strong>課題：</strong>山間部の広範囲な現場で、従来測量では3日以上かかっていた<br>
  <strong>導入後：</strong>ドローン測量により<strong>現場作業1日で完了</strong>。点群データから3D図面を自動生成<br>
  <strong>効果：</strong>
  <ul style="margin:8px 0;">
    <li>現場作業日数: 3日 → 1日（<strong>67%短縮</strong>）</li>
    <li>データ処理: 点群から等高線・断面図を自動生成</li>
    <li>安全性: 急斜面への立入不要に</li>
  </ul>
</div>

<p>弊社では名古屋・東海エリアを中心に、<strong>年間100件以上</strong>のドローン測量実績がございます。<br>
実績一覧はこちらからご覧いただけます：<br>
<a href="https://www.tokaiair.com/cases/">施工実績一覧</a></p>

<p>「うちの現場でも使えるかな？」というご相談だけでも歓迎です。<br>
お気軽にお問い合わせください。</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
先日のお問い合わせ、その後いかがでしょうか。

今回は、実際にドローン測量を導入いただいたお客様の事例をご紹介します。

━━━━━━━━━━━━━━━━━━━━━━━
【事例】建設コンサルタント会社様 ― 道路改良工事の測量

課題: 山間部の広範囲な現場で、従来測量では3日以上かかっていた
導入後: ドローン測量により現場作業1日で完了。点群データから3D図面を自動生成
効果:
  ・現場作業日数: 3日→1日（67%短縮）
  ・データ処理: 点群から等高線・断面図を自動生成
  ・安全性: 急斜面への立入不要に
━━━━━━━━━━━━━━━━━━━━━━━

弊社では名古屋・東海エリアを中心に、年間100件以上のドローン測量実績がございます。
実績一覧: https://www.tokaiair.com/cases/

「うちの現場でも使えるかな？」というご相談だけでも歓迎です。
お気軽にお問い合わせください。
""",
    },
    {
        "step": 4,
        "day": 14,
        "key": "inquiry_day14",
        "label": "無料現場診断の案内",
        "subject": "無料現場診断のご案内｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
お問い合わせいただいてから2週間ほど経ちましたが、ご検討状況はいかがでしょうか。</p>

<p>「興味はあるけど、自分の現場にドローン測量が合うかわからない」<br>
というお声をよくいただきます。</p>

<p>そこで、<strong>無料の現場診断</strong>をご案内しています。</p>

<div style="background:#fef9e7;border-left:4px solid #f39c12;padding:16px;margin:16px 0;">
  <strong style="color:#7d6608;">【無料現場診断】</strong><br><br>
  ・現場の図面や写真をお送りいただくだけでOK<br>
  ・ドローン測量の適用可否・概算費用・想定スケジュールをご回答<br>
  ・もちろん、お見積りの義務はありません<br>
  ・所要時間: ご連絡から<strong>2営業日以内</strong>にご回答
</div>

<p>「まずは話だけ聞きたい」でも構いません。<br>
ご希望でしたら、このメールへの返信、またはお電話にてお気軽にお申し付けください。</p>

<p>TEL: <a href="tel:{phone}">{phone}</a>（平日 9:00〜18:00）</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
お問い合わせいただいてから2週間ほど経ちましたが、ご検討状況はいかがでしょうか。

「興味はあるけど、自分の現場にドローン測量が合うかわからない」
というお声をよくいただきます。

そこで、無料の現場診断をご案内しています。

【無料現場診断】
  ・現場の図面や写真をお送りいただくだけでOK
  ・ドローン測量の適用可否・概算費用・想定スケジュールをご回答
  ・もちろん、お見積りの義務はありません
  ・所要時間: ご連絡から2営業日以内にご回答

「まずは話だけ聞きたい」でも構いません。
ご希望でしたら、このメールへの返信、またはお電話にてお気軽にお申し付けください。

TEL: {phone}（平日 9:00〜18:00）
""",
    },
    {
        "step": 5,
        "day": 30,
        "key": "inquiry_day30",
        "label": "フォローアップ",
        "subject": "その後いかがですか？｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
約1ヶ月前にお問い合わせいただきましたが、その後いかがでしょうか。</p>

<p>もし現時点ではご予定がない場合でも、将来の参考としてお気軽にご連絡ください。<br>
弊社では以下のようなご相談にも対応しております。</p>

<ul>
  <li>「来年度の予算取りのために概算が知りたい」</li>
  <li>「他社の見積りと比較したい」</li>
  <li>「i-Constructionへの対応方法を知りたい」</li>
</ul>

<p>また、ドローン測量に関する最新の情報を弊社サイトで発信しています。<br>
<a href="{site_url}">東海エアサービス公式サイト</a></p>

<p>何かございましたら、いつでもお声がけください。<br>
今後ともよろしくお願いいたします。</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
約1ヶ月前にお問い合わせいただきましたが、その後いかがでしょうか。

もし現時点ではご予定がない場合でも、将来の参考としてお気軽にご連絡ください。
弊社では以下のようなご相談にも対応しております。

  ・「来年度の予算取りのために概算が知りたい」
  ・「他社の見積りと比較したい」
  ・「i-Constructionへの対応方法を知りたい」

また、ドローン測量に関する最新の情報を弊社サイトで発信しています。
{site_url}

何かございましたら、いつでもお声がけください。
今後ともよろしくお願いいたします。
""",
    },
]

# ──────────────────────────────────────────
# シーケンス2: 納品後リピート促進（3通）
# ──────────────────────────────────────────
DELIVERY_SEQUENCE = [
    {
        "step": 1,
        "day": 1,
        "key": "delivery_day1",
        "label": "納品御礼＋データ活用案内",
        "subject": "納品御礼とデータ活用のご案内｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
この度は弊社にご依頼いただき、誠にありがとうございました。</p>

<p>納品データについて、ご不明点やご要望がございましたらお気軽にご連絡ください。</p>

<p>納品データの活用方法として、以下のような用途でお使いいただけます。</p>

<div style="background:#f0f7fb;border-left:4px solid #2e86c1;padding:16px;margin:16px 0;">
  <strong style="color:#1a5276;">【納品データの活用例】</strong><br><br>
  <strong>点群データ（LAS/LAZ）</strong><br>
  ・土量計算、断面図作成に直接利用可能<br>
  ・CADソフト（AutoCAD、Civil 3D等）へのインポート<br><br>
  <strong>オルソ画像（TIFF/PDF）</strong><br>
  ・現況把握、施工管理の基礎資料として<br>
  ・発注者への報告書添付用<br><br>
  <strong>3Dモデル</strong><br>
  ・施工シミュレーション、出来形管理<br>
  ・BIM/CIMとの連携
</div>

<p>「こういう形で使いたいけど加工できる？」といったご相談も承ります。<br>
データ変換や追加処理も対応可能です。</p>

<p>引き続きよろしくお願いいたします。</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
この度は弊社にご依頼いただき、誠にありがとうございました。

納品データについて、ご不明点やご要望がございましたらお気軽にご連絡ください。

納品データの活用方法として、以下のような用途でお使いいただけます。

【納品データの活用例】
■ 点群データ（LAS/LAZ）
  ・土量計算、断面図作成に直接利用可能
  ・CADソフト（AutoCAD、Civil 3D等）へのインポート

■ オルソ画像（TIFF/PDF）
  ・現況把握、施工管理の基礎資料として
  ・発注者への報告書添付用

■ 3Dモデル
  ・施工シミュレーション、出来形管理
  ・BIM/CIMとの連携

「こういう形で使いたいけど加工できる？」といったご相談も承ります。
データ変換や追加処理も対応可能です。

引き続きよろしくお願いいたします。
""",
    },
    {
        "step": 2,
        "day": 30,
        "key": "delivery_day30",
        "label": "定期測量のご提案",
        "subject": "定期測量でコスト削減｜継続利用のご案内｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
先日はご依頼いただきありがとうございました。<br>
納品データはお役に立てておりますでしょうか。</p>

<p>今回は、<strong>定期測量</strong>をご活用いただいているお客様の事例をご紹介します。</p>

<div style="background:#f0f7fb;border-left:4px solid #2e86c1;padding:16px;margin:16px 0;">
  <strong style="color:#1a5276;">【定期測量のメリット】</strong><br><br>
  <strong>1. コスト削減</strong><br>
  年間契約や複数回セットで、<strong>1回あたりの単価が10〜20%お得</strong>に。<br>
  GCP設置を初回に行えば、2回目以降の現場作業が大幅に効率化されます。<br><br>
  <strong>2. 経時変化の把握</strong><br>
  同じ条件で定期計測することで、<strong>施工進捗の正確な把握</strong>が可能。<br>
  切土・盛土の土量変化を時系列で管理できます。<br><br>
  <strong>3. i-Construction対応</strong><br>
  出来形管理の各段階（着工前・中間・完成）をドローン測量でカバー。<br>
  発注者への提出資料がスムーズに作成できます。
</div>

<p>年間の測量計画がございましたら、お得なパッケージプランをご提案いたします。<br>
まずは「来期これくらいの現場がある」程度のご連絡でOKです。</p>

<p>お気軽にご相談ください。</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
先日はご依頼いただきありがとうございました。
納品データはお役に立てておりますでしょうか。

今回は、定期測量をご活用いただいているお客様の事例をご紹介します。

【定期測量のメリット】

■ 1. コスト削減
年間契約や複数回セットで、1回あたりの単価が10〜20%お得に。
GCP設置を初回に行えば、2回目以降の現場作業が大幅に効率化されます。

■ 2. 経時変化の把握
同じ条件で定期計測することで、施工進捗の正確な把握が可能。
切土・盛土の土量変化を時系列で管理できます。

■ 3. i-Construction対応
出来形管理の各段階（着工前・中間・完成）をドローン測量でカバー。
発注者への提出資料がスムーズに作成できます。

年間の測量計画がございましたら、お得なパッケージプランをご提案いたします。
まずは「来期これくらいの現場がある」程度のご連絡でOKです。

お気軽にご相談ください。
""",
    },
    {
        "step": 3,
        "day": 90,
        "key": "delivery_day90",
        "label": "近況伺い＋新サービス案内",
        "subject": "ご無沙汰しております｜新サービスのご案内｜{company_name}",
        "html": """
<p>{contact_name} 様</p>

<p>{company_name}の國本です。<br>
ご無沙汰しております。以前ご依頼いただいた際は大変ありがとうございました。</p>

<p>その後、新たな測量のご予定やお困りごとはございませんか？</p>

<p>弊社では最近、以下の新しいサービスにも力を入れています。</p>

<div style="background:#f0f7fb;border-left:4px solid #2e86c1;padding:16px;margin:16px 0;">
  <strong style="color:#1a5276;">【サービスラインナップ】</strong><br><br>
  <strong>ドローン測量（公共測量対応）</strong><br>
  ・i-Construction出来形管理、土量計算、地形測量<br><br>
  <strong>建物赤外線調査</strong><br>
  ・外壁タイル浮き調査、雨漏り調査、断熱性能調査<br>
  ・12条点検の赤外線調査にも対応<br><br>
  <strong>眺望撮影・空撮</strong><br>
  ・マンション眺望確認、建設予定地の周辺状況撮影<br><br>
  <strong>太陽光パネル点検</strong><br>
  ・赤外線カメラによるホットスポット検出
</div>

<p>「以前とは別の用途で使えるか聞きたい」というご相談も歓迎です。<br>
いつでもお気軽にご連絡ください。</p>

<p>今後ともよろしくお願いいたします。</p>
""",
        "text": """{contact_name} 様

{company_name}の國本です。
ご無沙汰しております。以前ご依頼いただいた際は大変ありがとうございました。

その後、新たな測量のご予定やお困りごとはございませんか？

弊社では最近、以下の新しいサービスにも力を入れています。

【サービスラインナップ】

■ ドローン測量（公共測量対応）
  ・i-Construction出来形管理、土量計算、地形測量

■ 建物赤外線調査
  ・外壁タイル浮き調査、雨漏り調査、断熱性能調査
  ・12条点検の赤外線調査にも対応

■ 眺望撮影・空撮
  ・マンション眺望確認、建設予定地の周辺状況撮影

■ 太陽光パネル点検
  ・赤外線カメラによるホットスポット検出

「以前とは別の用途で使えるか聞きたい」というご相談も歓迎です。
いつでもお気軽にご連絡ください。

今後ともよろしくお願いいたします。
""",
    },
]


# ── Lark API ──
def lark_get_token():
    data = json.dumps({
        "app_id": CONFIG["lark_app_id"],
        "app_secret": CONFIG["lark_app_secret"],
    }).encode()
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
        url = (
            f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
            f"{CONFIG['crm_base_token']}/tables/{table_id}/records?page_size=500"
        )
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


def create_record(token, table_id, fields):
    """Lark Baseにレコードを作成"""
    url = (
        f"https://open.larksuite.com/open-apis/bitable/v1/apps/"
        f"{CONFIG['crm_base_token']}/tables/{table_id}/records"
    )
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            result = json.loads(r.read())
            return result.get("data", {}).get("record", {}).get("record_id")
    except urllib.error.HTTPError as e:
        log(f"  Lark create record error: {e.code} {e.read().decode()}")
        return None


def send_lark_dm(token, open_id, text):
    if not open_id:
        return
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    for chunk in chunks:
        data = json.dumps({
            "receive_id": open_id,
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
            log(f"  Lark DM error: {e.code} {e.read().decode()}")
        time.sleep(0.3)


# ── WordPress wp_mail で送信 ──
def send_email_via_wordpress(to_email, subject, html_body, text_body,
                              from_name="東海エアサービス", from_email="info@tokaiair.com"):
    wp_auth = base64.b64encode(
        f"{CONFIG['wp_user']}:{CONFIG['wp_app_password']}".encode()
    ).decode()
    endpoint = CONFIG["wp_base_url"] + "/tas/v1/send-email"

    # HTML形式で送信（フォールバックはWP側で処理）
    full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Helvetica Neue',Arial,'Hiragino Kaku Gothic ProN',sans-serif;font-size:14px;line-height:1.7;color:#333;">
{html_body}
{SIGNATURE_HTML}
</body>
</html>"""

    data = json.dumps({
        "to": to_email,
        "subject": subject,
        "body": full_html,
        "from_name": from_name,
        "from_email": from_email,
        "headers": ["Content-Type: text/html; charset=UTF-8"],
    }).encode()

    req = urllib.request.Request(
        endpoint, data=data,
        headers={
            "Authorization": f"Basic {wp_auth}",
            "Content-Type": "application/json",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            return result.get("success", False)
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        log(f"  WordPress email error: {e.code} {body_text}")
        return False
    except Exception as e:
        log(f"  WordPress email error: {e}")
        return False


# ── State / Queue 管理 ──
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "inquiry_processed_ids": [],
        "delivery_processed_ids": [],
        "last_scan": None,
        "initialized": False,
    }


def save_state(state):
    # 古いIDを刈り込み
    for key in ("inquiry_processed_ids", "delivery_processed_ids"):
        if len(state.get(key, [])) > 500:
            state[key] = state[key][-300:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_queue():
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE) as f:
            return json.load(f)
    return []


def save_queue(queue):
    with open(QUEUE_FILE, "w") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


# ── テンプレート変数の展開 ──
def render_template(template, variables):
    """テンプレート文字列に変数を差し込む"""
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value))
    return result


# ── 送信日時の計算（営業日のみ、9:00に送信） ──
def calc_send_time(base_date, delay_days):
    """base_dateからdelay_days営業日後の9:00を返す"""
    if delay_days == 0:
        # Day 0は即座（ただし営業時間内なら即、時間外なら翌営業日9:00）
        now = datetime.now()
        if now.weekday() < 5 and 8 <= now.hour < 18:
            return now + timedelta(minutes=5)  # 5分後に送信
        else:
            next_day = now + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            return next_day.replace(hour=9, minute=0, second=0, microsecond=0)

    # delay_days > 0: カレンダー日数後の9:00（営業日調整）
    target = base_date + timedelta(days=delay_days)
    # 土日なら翌月曜に
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target.replace(hour=9, minute=0, second=0, microsecond=0)


# ── 連絡先からメール・名前を取得 ──
def extract_contact_info(contact_record):
    """連絡先レコードから情報を抽出"""
    f = contact_record.get("fields", {})
    name = str(f.get("氏名", "") or "")
    company = str(f.get("会社名", "") or "")
    email = str(f.get("メールアドレス", "") or "")
    title = str(f.get("役職", "") or "")
    return {
        "record_id": contact_record.get("record_id", ""),
        "name": name,
        "company": company,
        "email": email,
        "title": title,
    }


def find_contact_email_for_order(contacts, accounts, order_fields):
    """受注台帳レコードに紐づく連絡先のメールアドレスを検索"""
    # 1. 取引先リンクから会社名を取得
    account_name = ""
    account_links = order_fields.get("取引先", [])
    if isinstance(account_links, list):
        for link in account_links:
            if isinstance(link, dict):
                rid = link.get("record_id", "")
                for a in accounts:
                    if a.get("record_id") == rid:
                        account_name = str(a.get("fields", {}).get("会社名", "") or "")
                        break
    elif isinstance(account_links, str):
        account_name = account_links

    # テキスト値からも取得を試みる
    if not account_name:
        for link in (account_links if isinstance(account_links, list) else []):
            if isinstance(link, dict):
                tv = link.get("text_value", "") or link.get("text", "")
                if tv:
                    account_name = tv
                    break

    # 案件名からも推測
    order_name = str(order_fields.get("案件名", "") or order_fields.get("商談名", "") or "")

    # 連絡先を検索
    for c in contacts:
        cf = c.get("fields", {})
        company = str(cf.get("会社名", "") or "")
        email = str(cf.get("メールアドレス", "") or "")
        if not email or "@" not in email:
            continue

        if account_name and (account_name in company or company in account_name):
            return extract_contact_info(c)
        if order_name and company and company in order_name:
            return extract_contact_info(c)

    return None


# ── メールログテーブルへの記録 ──
def log_email_to_lark(token, sequence_type, step_key, to_email, to_name, subject, status):
    """メールログテーブルにレコードを追加して重複防止"""
    fields = {
        "シーケンス": sequence_type,
        "ステップ": step_key,
        "宛先メール": to_email,
        "宛先名": to_name,
        "件名": subject,
        "ステータス": status,
        "送信日時": int(datetime.now().timestamp() * 1000),
    }
    try:
        record_id = create_record(token, TABLE_EMAIL_LOG, fields)
        if record_id:
            log(f"  メールログ記録: {record_id}")
        return record_id
    except Exception as e:
        log(f"  メールログ記録エラー: {e}")
        return None


def check_already_sent(email_logs, to_email, step_key):
    """メールログテーブルで送信済みかチェック"""
    for rec in email_logs:
        f = rec.get("fields", {})
        log_email = str(f.get("宛先メール", "") or "")
        log_step = str(f.get("ステップ", "") or "")
        log_status = str(f.get("ステータス", "") or "")
        if log_email == to_email and log_step == step_key and log_status in ("sent", "送信済み"):
            return True
    return False


# ── スキャンモード: 新規対象を検出→キューに追加 ──
def scan_and_queue():
    log("ナーチャリング: 新規対象スキャン開始")

    token = lark_get_token()
    state = load_state()

    # CRMデータ取得
    log("  データ取得中...")
    contacts = get_all_records(token, TABLE_CONTACTS)
    orders = get_all_records(token, TABLE_ORDERS)
    accounts = get_all_records(token, TABLE_ACCOUNTS)

    # メールログ取得（重複チェック用）
    email_logs = []
    try:
        email_logs = get_all_records(token, TABLE_EMAIL_LOG)
    except Exception as e:
        log(f"  メールログ取得スキップ: {e}")

    log(f"  連絡先: {len(contacts)}件 / 受注台帳: {len(orders)}件 / "
        f"取引先: {len(accounts)}件 / メールログ: {len(email_logs)}件")

    queue = load_queue()
    queued_count = 0

    # 初回実行チェック
    if not state.get("initialized"):
        log("  初回実行: 30日以上前のレコードを処理済みとしてマーク（直近30日は対象）")
        cutoff = datetime.now() - timedelta(days=30)
        old_contact_ids = []
        for c in contacts:
            created = c.get("created_time")
            if isinstance(created, (int, float)) and created > 0:
                created_dt = datetime.fromtimestamp(created / 1000)
                if created_dt < cutoff:
                    old_contact_ids.append(c.get("record_id", ""))
            else:
                # 作成日時不明の場合は処理済みとする
                old_contact_ids.append(c.get("record_id", ""))
        old_order_ids = []
        for o in orders:
            created = o.get("created_time")
            if isinstance(created, (int, float)) and created > 0:
                created_dt = datetime.fromtimestamp(created / 1000)
                if created_dt < cutoff:
                    old_order_ids.append(o.get("record_id", ""))
            else:
                old_order_ids.append(o.get("record_id", ""))
        state["inquiry_processed_ids"] = old_contact_ids
        state["delivery_processed_ids"] = old_order_ids
        state["initialized"] = True
        state["last_scan"] = datetime.now().isoformat()
        save_state(state)
        log(f"  処理済みマーク: 連絡先{len(old_contact_ids)}件 / 受注{len(old_order_ids)}件")
        log(f"  直近30日の連絡先{len(contacts) - len(old_contact_ids)}件をナーチャリング対象として続行")
        # 初回でも直近レコードは処理するため、returnしない

    inquiry_processed = set(state.get("inquiry_processed_ids", []))
    delivery_processed = set(state.get("delivery_processed_ids", []))

    # ── シーケンス1: 問い合わせ後ナーチャリング ──
    log("\n  === シーケンス1: 問い合わせ後ナーチャリング ===")
    new_inquiries = 0

    for contact_rec in contacts:
        rid = contact_rec.get("record_id", "")
        if rid in inquiry_processed:
            continue

        info = extract_contact_info(contact_rec)
        if not info["email"] or "@" not in info["email"]:
            inquiry_processed.add(rid)
            continue

        # テスト・無効レコード除外
        email_lower = info["email"].lower()
        name_lower = (info["name"] or "").lower()
        if any(p in email_lower or p in name_lower for p in EXCLUDE_PATTERNS):
            log(f"  除外（テスト/無効）: {info['name']} <{info['email']}>")
            inquiry_processed.add(rid)
            continue

        # 問い合わせ日を取得
        f = contact_rec.get("fields", {})
        inquiry_date = None

        # 作成日時フィールド
        for date_field in ["作成日時", "問い合わせ日", "登録日"]:
            val = f.get(date_field)
            if val:
                if isinstance(val, (int, float)):
                    inquiry_date = datetime.fromtimestamp(val / 1000)
                elif isinstance(val, str):
                    try:
                        inquiry_date = datetime.fromisoformat(val)
                    except ValueError:
                        pass
                break

        # レコード作成日時をフォールバック
        if not inquiry_date:
            created = contact_rec.get("created_time")
            if created:
                inquiry_date = datetime.fromtimestamp(created / 1000)

        if not inquiry_date:
            inquiry_date = datetime.now()

        # 直近60日以内の問い合わせのみ対象
        days_since = (datetime.now() - inquiry_date).days
        if days_since > 60:
            inquiry_processed.add(rid)
            continue

        contact_name = info["name"] or "ご担当者"
        company_display = info["company"] or ""

        log(f"  新規問い合わせ: {company_display} {contact_name} <{info['email']}>"
            f" ({days_since}日前)")

        # 全ステップをキューに追加
        for step in INQUIRY_SEQUENCE:
            # 既に送信済みかチェック
            if check_already_sent(email_logs, info["email"], step["key"]):
                log(f"    {step['label']}: 送信済み。スキップ。")
                continue

            # キューに同じメール+ステップがないかチェック
            already_queued = any(
                q["to_email"] == info["email"] and q["step_key"] == step["key"]
                and q["status"] == "pending"
                for q in queue
            )
            if already_queued:
                continue

            # 過去のステップでまだ送信日が来ていないものはスキップしない（全て予約）
            send_at = calc_send_time(inquiry_date, step["day"])

            # 過去の送信予定日（既に過ぎている）はスキップ
            if send_at < datetime.now() and step["day"] > 0:
                # Day 0以外で送信予定日が過ぎていたらスキップ
                log(f"    {step['label']}: 送信予定日超過。スキップ。")
                continue

            variables = {
                "contact_name": contact_name,
                "company_name": COMPANY_INFO["name"],
                "phone": COMPANY_INFO["phone"],
                "site_url": COMPANY_INFO["url"],
            }

            queue_item = {
                "sequence": "inquiry",
                "step": step["step"],
                "step_key": step["key"],
                "label": step["label"],
                "contact_record_id": rid,
                "to_email": info["email"],
                "to_name": f"{company_display} {contact_name}".strip(),
                "subject": render_template(step["subject"], variables),
                "html_body": render_template(step["html"], variables),
                "text_body": render_template(step["text"], variables),
                "from_name": COMPANY_INFO["name"],
                "from_email": COMPANY_INFO["email"],
                "queued_at": datetime.now().isoformat(),
                "send_at": send_at.isoformat(),
                "status": "pending",
            }
            queue.append(queue_item)
            queued_count += 1

        inquiry_processed.add(rid)
        new_inquiries += 1

    log(f"  新規問い合わせ: {new_inquiries}件")

    # ── シーケンス2: 納品後リピート促進 ──
    log("\n  === シーケンス2: 納品後リピート促進 ===")
    new_deliveries = 0

    for order_rec in orders:
        rid = order_rec.get("record_id", "")
        if rid in delivery_processed:
            continue

        f = order_rec.get("fields", {})

        # 納品完了かどうかチェック
        # 受注台帳の「出典」列にステータスがある（受注/失注/Gmail/支払通知）
        status = str(f.get("出典", "") or f.get("ステータス", "") or "")
        stage = str(f.get("商談ステージ", "") or "")

        # 受注または納品完了のみ対象
        is_delivered = (
            status in ("受注", "納品完了") or
            stage in ("受注", "納品完了") or
            "受注" in status
        )
        if not is_delivered:
            delivery_processed.add(rid)
            continue

        # 納品日を取得
        delivery_date = None
        for date_field in ["納品日", "納品日時", "完了日", "受注日"]:
            val = f.get(date_field)
            if val:
                if isinstance(val, (int, float)):
                    delivery_date = datetime.fromtimestamp(val / 1000)
                elif isinstance(val, str):
                    try:
                        delivery_date = datetime.fromisoformat(val)
                    except ValueError:
                        pass
                break

        if not delivery_date:
            last_modified = order_rec.get("last_modified_time")
            if last_modified:
                delivery_date = datetime.fromtimestamp(last_modified / 1000)

        if not delivery_date:
            delivery_processed.add(rid)
            continue

        # 直近120日以内のみ対象
        days_since = (datetime.now() - delivery_date).days
        if days_since > 120:
            delivery_processed.add(rid)
            continue

        # 連絡先のメールアドレスを検索
        contact = find_contact_email_for_order(contacts, accounts, f)
        if not contact or not contact.get("email"):
            delivery_processed.add(rid)
            continue

        order_name = str(f.get("案件名", "") or f.get("商談名", "") or "(案件名なし)")
        contact_name = contact["name"] or "ご担当者"
        company_display = contact.get("company", "") or ""

        log(f"  納品完了: {order_name} → {company_display} {contact_name} <{contact['email']}>"
            f" ({days_since}日前)")

        # 全ステップをキューに追加
        for step in DELIVERY_SEQUENCE:
            if check_already_sent(email_logs, contact["email"], step["key"]):
                log(f"    {step['label']}: 送信済み。スキップ。")
                continue

            already_queued = any(
                q["to_email"] == contact["email"] and q["step_key"] == step["key"]
                and q["status"] == "pending"
                for q in queue
            )
            if already_queued:
                continue

            send_at = calc_send_time(delivery_date, step["day"])

            if send_at < datetime.now() and step["day"] > 1:
                log(f"    {step['label']}: 送信予定日超過。スキップ。")
                continue

            variables = {
                "contact_name": contact_name,
                "company_name": COMPANY_INFO["name"],
                "phone": COMPANY_INFO["phone"],
                "site_url": COMPANY_INFO["url"],
            }

            queue_item = {
                "sequence": "delivery",
                "step": step["step"],
                "step_key": step["key"],
                "label": step["label"],
                "contact_record_id": contact.get("record_id", ""),
                "order_record_id": rid,
                "to_email": contact["email"],
                "to_name": f"{company_display} {contact_name}".strip(),
                "subject": render_template(step["subject"], variables),
                "html_body": render_template(step["html"], variables),
                "text_body": render_template(step["text"], variables),
                "from_name": COMPANY_INFO["name"],
                "from_email": COMPANY_INFO["email"],
                "queued_at": datetime.now().isoformat(),
                "send_at": send_at.isoformat(),
                "status": "pending",
            }
            queue.append(queue_item)
            queued_count += 1

        delivery_processed.add(rid)
        new_deliveries += 1

    log(f"  新規納品完了: {new_deliveries}件")

    # 保存
    state["inquiry_processed_ids"] = list(inquiry_processed)
    state["delivery_processed_ids"] = list(delivery_processed)
    state["last_scan"] = datetime.now().isoformat()
    save_state(state)
    save_queue(queue)

    pending_count = len([q for q in queue if q["status"] == "pending"])
    log(f"\n  キュー追加: {queued_count}件 / 合計待機中: {pending_count}件")

    # CEOに通知
    if queued_count > 0:
        send_lark_dm(token, CEO_OPEN_ID,
            f"ナーチャリングキュー: {queued_count}件追加\n"
            f"問い合わせ: {new_inquiries}件 / 納品後: {new_deliveries}件\n"
            f"合計待機中: {pending_count}件")


# ── 送信モード ──
def send_queued_emails(dry_run=False):
    now = datetime.now()
    log(f"ナーチャリング: {'ドライラン' if dry_run else '送信'}モード")

    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]

    if not pending:
        log("  送信待ちなし")
        return

    log(f"  キュー内: {len(pending)}件")

    token = None
    if not dry_run:
        token = lark_get_token()

    # メールログ取得（重複チェック用）
    email_logs = []
    if token:
        try:
            email_logs = get_all_records(token, TABLE_EMAIL_LOG)
        except Exception:
            pass

    sent_count = 0
    skipped_count = 0

    for item in queue:
        if item["status"] != "pending":
            continue

        send_at = datetime.fromisoformat(item["send_at"])
        if now < send_at:
            remaining = send_at - now
            days = remaining.days
            hours = remaining.seconds // 3600
            log(f"  [{item['label']}] {item['to_name']} → {item['send_at']}"
                f" (あと{days}日{hours}時間)")
            continue

        # 送信前に再度重複チェック
        if email_logs and check_already_sent(email_logs, item["to_email"], item["step_key"]):
            log(f"  [{item['label']}] {item['to_email']}: 送信済み。スキップ。")
            item["status"] = "skipped"
            item["skipped_at"] = now.isoformat()
            item["skip_reason"] = "already_sent"
            skipped_count += 1
            continue

        seq_label = "問い合わせ" if item["sequence"] == "inquiry" else "納品後"
        log(f"\n  送信: [{seq_label}] {item['label']}")
        log(f"    宛先: {item['to_name']} <{item['to_email']}>")
        log(f"    件名: {item['subject']}")

        if dry_run:
            log(f"    [ドライラン] 送信スキップ")
            # テキスト版を表示
            print(f"\n    --- メール本文（テキスト版） ---")
            for line in item["text_body"].strip().split("\n"):
                print(f"    {line}")
            print(f"    --- ここまで ---\n")
            continue

        # 1日の送信上限チェック
        today = now.strftime("%Y-%m-%d")
        today_sent = sum(1 for q in queue if q.get("status") == "sent"
                         and q.get("sent_at", "").startswith(today))
        if today_sent + sent_count >= MAX_SENDS_PER_DAY:
            log(f"    送信上限({MAX_SENDS_PER_DAY}件/日)到達。残りは翌営業日。")
            send_lark_dm(token, CEO_OPEN_ID,
                f"ナーチャリングメール: 本日の送信上限({MAX_SENDS_PER_DAY}件)到達。")
            break

        # レビューエージェントによる送信前チェック
        review_result = run_email_review(
            item["subject"], item["text_body"],
            item["to_email"], item.get("from_email", COMPANY_INFO["email"]))
        if review_result["verdict"] == "NG":
            critical_issues = [i for i in review_result.get("issues", []) if i["severity"] == "CRITICAL"]
            issue_text = "\n".join(f"  - {i['description']}" for i in critical_issues)
            log(f"    レビューNG: {review_result['summary']}")
            item["status"] = "review_rejected"
            item["review_result"] = review_result["summary"]
            send_lark_dm(token, CEO_OPEN_ID,
                f"ナーチャリングメール送信ブロック（レビューNG）\n"
                f"[{seq_label}] {item['label']}\n"
                f"宛先: {item['to_email']}\n"
                f"理由:\n{issue_text}\n"
                f"手動確認が必要です")
            continue
        else:
            log(f"    レビューOK: {review_result['summary']}")

        # 送信
        success = send_email_via_wordpress(
            to_email=item["to_email"],
            subject=item["subject"],
            html_body=item["html_body"],
            text_body=item["text_body"],
            from_name=item.get("from_name", COMPANY_INFO["name"]),
            from_email=item.get("from_email", COMPANY_INFO["email"]),
        )

        if success:
            item["status"] = "sent"
            item["sent_at"] = now.isoformat()
            sent_count += 1
            log(f"    送信完了")

            # メールログテーブルに記録
            log_email_to_lark(
                token, item["sequence"], item["step_key"],
                item["to_email"], item["to_name"],
                item["subject"], "sent"
            )

            # CEO通知
            send_lark_dm(token, CEO_OPEN_ID,
                f"ナーチャリングメール送信\n"
                f"[{seq_label}] {item['label']}\n"
                f"宛先: {item['to_name']} <{item['to_email']}>\n"
                f"件名: {item['subject']}")
        else:
            item["status"] = "failed"
            item["failed_at"] = now.isoformat()
            log(f"    送信失敗")

            send_lark_dm(token, CEO_OPEN_ID,
                f"ナーチャリングメール送信失敗\n"
                f"[{seq_label}] {item['label']}\n"
                f"宛先: {item['to_email']}\n"
                f"手動対応が必要です")

        time.sleep(1)

    # 古いレコードのクリーンアップ（30日以上前の送信済み/スキップ済み）
    cutoff = (now - timedelta(days=30)).isoformat()
    queue = [
        q for q in queue
        if q["status"] == "pending"
        or q.get("sent_at", q.get("failed_at", q.get("skipped_at", ""))) > cutoff
    ]
    save_queue(queue)

    # ログ記録
    with open(LOG_FILE, "a", encoding="utf-8") as lf:
        lf.write(f"[{now.isoformat()}] sent={sent_count} skipped={skipped_count}\n")

    log(f"\n  送信: {sent_count}件 / スキップ: {skipped_count}件")


# ── キュー一覧表示 ──
def show_queue():
    queue = load_queue()
    pending = [q for q in queue if q["status"] == "pending"]
    sent = [q for q in queue if q["status"] == "sent"]
    failed = [q for q in queue if q["status"] == "failed"]
    skipped = [q for q in queue if q["status"] == "skipped"]

    print(f"ナーチャリングキュー状況:")
    print(f"  待機中: {len(pending)}件 / 送信済: {len(sent)}件 / "
          f"失敗: {len(failed)}件 / スキップ: {len(skipped)}件")

    # シーケンス別集計
    inq_pending = [q for q in pending if q["sequence"] == "inquiry"]
    del_pending = [q for q in pending if q["sequence"] == "delivery"]
    print(f"\n  問い合わせ後: {len(inq_pending)}件待機中")
    print(f"  納品後: {len(del_pending)}件待機中")

    if pending:
        print(f"\n  【待機中】")
        # 送信日時順にソート
        pending_sorted = sorted(pending, key=lambda q: q.get("send_at", ""))
        for q in pending_sorted[:20]:  # 最大20件表示
            seq_label = "問合せ" if q["sequence"] == "inquiry" else "納品後"
            print(f"    [{seq_label}] {q['label']} → {q['to_name']} <{q['to_email']}>"
                  f" (送信: {q['send_at'][:16]})")

        if len(pending) > 20:
            print(f"    ... 他 {len(pending) - 20}件")

    if sent:
        print(f"\n  【送信済（直近5件）】")
        for q in sent[-5:]:
            seq_label = "問合せ" if q["sequence"] == "inquiry" else "納品後"
            print(f"    [{seq_label}] {q['label']} → {q['to_email']}"
                  f" ({q.get('sent_at', '')[:16]})")

    if failed:
        print(f"\n  【失敗】")
        for q in failed:
            seq_label = "問合せ" if q["sequence"] == "inquiry" else "納品後"
            print(f"    [{seq_label}] {q['label']} → {q['to_email']}"
                  f" ({q.get('failed_at', '')[:16]})")


def main():
    args = sys.argv[1:]

    if "--list" in args:
        show_queue()
        return

    mode_scan = "--scan" in args
    mode_send = "--send" in args
    mode_dry = "--dry-run" in args

    # デフォルト: --dry-run
    if not any([mode_scan, mode_send, mode_dry]):
        mode_dry = True

    if mode_scan:
        scan_and_queue()

    if mode_send or mode_dry:
        send_queued_emails(dry_run=mode_dry)


if __name__ == "__main__":
    main()
