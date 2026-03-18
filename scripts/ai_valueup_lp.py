#!/usr/bin/env python3
"""
AIバリューアップ事業部 LP作成スクリプト
WordPress REST APIで /services/ai-valueup/ ページを作成

Usage:
  python3 ai_valueup_lp.py             # ページ作成（ドラフト）
  python3 ai_valueup_lp.py --publish   # ページ作成（公開）
  python3 ai_valueup_lp.py --update    # 既存ページを更新
"""

import json
import os
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

WP_BASE = CONFIG["wordpress"]["base_url"]  # https://tokaiair.com/wp-json/wp/v2
WP_USER = CONFIG["wordpress"]["user"]
WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]
WP_AUTH = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()


def wp_request(endpoint, method="GET", data=None, params=None):
    url = f"{WP_BASE}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Basic {WP_AUTH}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP Error {e.code}: {e.read().decode()[:300]}")
        return None


def find_parent_page():
    """Find /services/ page ID to set as parent"""
    pages = wp_request("pages", params={"slug": "services", "per_page": 5})
    if pages:
        for p in pages:
            if p.get("slug") == "services":
                print(f"  Parent page found: /services/ (ID: {p['id']})")
                return p["id"]
    print("  Warning: /services/ page not found. Creating at root level.")
    return 0


def find_existing_page():
    """Check if ai-valueup page already exists"""
    pages = wp_request("pages", params={"slug": "ai-valueup", "per_page": 5})
    if pages:
        for p in pages:
            if p.get("slug") == "ai-valueup":
                print(f"  Existing page found: ID {p['id']}")
                return p["id"]
    return None


def build_lp_html():
    """Build the LP HTML content"""

    html = """
<!-- wp:group {"style":{"spacing":{"padding":{"top":"60px","bottom":"60px"}}},"layout":{"type":"constrained","contentSize":"960px"}} -->
<div class="wp-block-group" style="padding-top:60px;padding-bottom:60px">

<!-- HERO SECTION -->
<div style="text-align:center;margin-bottom:3rem">
<p style="font-size:.9rem;color:#e63946;font-weight:700;letter-spacing:2px;margin:0">AI VALUE-UP PROGRAM</p>
<h1 style="font-size:2.2rem;line-height:1.4;margin:.5rem 0 1rem">属人的な会社を、<br>AIで「売れる会社」に変える。</h1>
<p style="font-size:1.15rem;color:#555;max-width:640px;margin:0 auto 2rem">買収後1〜3ヶ月の業務自動化で、社長依存を解消。<br>バリュエーション3〜5倍を実現するプログラム。</p>
<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap">
<a href="/contact/" style="display:inline-block;padding:14px 32px;background:#1a3a5c;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem">無料相談する</a>
<a href="tel:05071177141" style="display:inline-block;padding:14px 32px;border:2px solid #1a3a5c;color:#1a3a5c;text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem">050-7117-7141</a>
</div>
</div>

<!-- PROBLEM SECTION -->
<div style="background:#f8f9fa;border-radius:12px;padding:2.5rem;margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:1.5rem">なぜ零細企業は売れないのか？</h2>
<div style="background:#fff;border-radius:8px;padding:1.5rem;font-family:monospace;font-size:.9rem;line-height:1.8;margin-bottom:1.5rem">
社長の頭の中に全てがある<br>
├── 顧客情報 → 社長の携帯と記憶<br>
├── 見積ノウハウ → 社長の経験と勘<br>
├── 請求・入金管理 → 奥さんのExcel<br>
├── 営業・受注 → 社長の人脈<br>
├── 現場手配 → 社長が毎朝電話<br>
└── 経営数字 → 社長の頭の中
</div>
<p style="text-align:center;font-size:1.1rem;font-weight:700;color:#e63946">社長 = 会社そのもの → 社長が抜けたら価値ゼロ → 買い手がつかない</p>
<p style="text-align:center;font-size:1rem;color:#555;margin-top:1rem">しかし実態は「社長にしかできない判断」ではなく、<strong>情報の転記・加工・通知</strong>。<br>つまり<strong>自動化できる業務が属人化しているだけ</strong>です。</p>
</div>

<!-- SOLUTION SECTION -->
<div style="margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:.5rem">解決策：AI業務自動化</h2>
<p style="text-align:center;color:#555;margin-bottom:2rem">最新のAI技術を活用し、日本語で指示するだけで業務システムを構築。<br>プログラマー不要。月額コスト数千円。</p>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem">

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">⚡</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">CRM・顧客管理</h3>
<p style="font-size:.9rem;color:#555;margin:0">問い合わせ→商談→受注を一元管理。15分毎の自動チェックで対応漏れゼロ。</p>
</div>

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">📊</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">KPIレポート自動生成</h3>
<p style="font-size:.9rem;color:#555;margin:0">営業成績・売上・利益率を自動集計。週次・月次レポートを0秒で作成。</p>
</div>

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">✉️</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">メール・フォロー自動化</h3>
<p style="font-size:.9rem;color:#555;margin:0">AIがヒアリング内容から最適なメールを自動生成。送信タイミングも自動最適化。</p>
</div>

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">💰</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">見積・請求の自動化</h3>
<p style="font-size:.9rem;color:#555;margin:0">過去の受注実績から概算見積を即時生成。見積作成30分→数秒に短縮。</p>
</div>

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">🔍</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">SEO・集客自動最適化</h3>
<p style="font-size:.9rem;color:#555;margin:0">アクセス解析→改善ポイント抽出→Webページ更新まで全自動。50ページを1日で改善。</p>
</div>

<div style="background:#fff;border:1px solid #e0e0e0;border-radius:12px;padding:1.5rem">
<p style="font-size:1.5rem;margin:0 0 .5rem">📋</p>
<h3 style="font-size:1.1rem;margin:0 0 .5rem">入札・案件スキャン</h3>
<p style="font-size:.9rem;color:#555;margin:0">官公庁の入札情報を毎朝自動チェック。業界の案件情報を見落としゼロに。</p>
</div>

</div>
</div>

<!-- PROOF SECTION -->
<div style="background:#1a3a5c;color:#fff;border-radius:12px;padding:2.5rem;margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:.5rem;color:#fff">自社での実証実績</h2>
<p style="text-align:center;color:#ccc;margin-bottom:2rem">東海エアサービス（ドローン測量・社員数名）で12の自動化を構築・稼働中</p>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.5rem;text-align:center">
<div>
<p style="font-size:2rem;font-weight:700;margin:0;color:#ffd166">3時間→15分</p>
<p style="font-size:.85rem;color:#ccc;margin:0">問い合わせ対応速度</p>
</div>
<div>
<p style="font-size:2rem;font-weight:700;margin:0;color:#ffd166">2時間→0</p>
<p style="font-size:.85rem;color:#ccc;margin:0">週次レポート作成</p>
</div>
<div>
<p style="font-size:2rem;font-weight:700;margin:0;color:#ffd166">月5,000円</p>
<p style="font-size:.85rem;color:#ccc;margin:0">システム運用コスト</p>
</div>
<div>
<p style="font-size:2rem;font-weight:700;margin:0;color:#ffd166">コード0行</p>
<p style="font-size:.85rem;color:#ccc;margin:0">日本語指示のみで構築</p>
</div>
</div>
</div>

<!-- TARGET INDUSTRIES -->
<div style="margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">対象業種</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem">

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">🏭</span>
<div><strong>製造業・町工場</strong><br><span style="font-size:.85rem;color:#555">見積自動算出・工程管理・受発注のデジタル化</span></div>
</div>

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">📋</span>
<div><strong>税理士・会計事務所</strong><br><span style="font-size:.85rem;color:#555">仕訳自動分類・月次レポート自動生成</span></div>
</div>

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">🏗️</span>
<div><strong>建設・リフォーム</strong><br><span style="font-size:.85rem;color:#555">現場写真→見積・工程管理・下請け手配自動化</span></div>
</div>

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">🚗</span>
<div><strong>中古車販売</strong><br><span style="font-size:.85rem;color:#555">在庫管理・価格予測・顧客フォロー自動化</span></div>
</div>

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">⚰️</span>
<div><strong>葬儀業</strong><br><span style="font-size:.85rem;color:#555">問い合わせ対応・見積・手配・在庫管理を自動化</span></div>
</div>

<div style="display:flex;align-items:center;gap:1rem;padding:1rem;border:1px solid #e0e0e0;border-radius:8px">
<span style="font-size:2rem">🏥</span>
<div><strong>調剤薬局・医療</strong><br><span style="font-size:.85rem;color:#555">在庫最適化・レセプト自動チェック・服薬フォロー</span></div>
</div>

</div>
</div>

<!-- 3-MONTH PROGRAM -->
<div style="margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">3ヶ月プログラム</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.5rem">

<div style="background:#e8f4f8;border-radius:12px;padding:2rem;text-align:center">
<p style="font-size:.85rem;color:#1a3a5c;font-weight:700;margin:0">MONTH 1</p>
<h3 style="font-size:1.3rem;margin:.5rem 0">可視化</h3>
<ul style="text-align:left;font-size:.9rem;color:#555;list-style:none;padding:0">
<li>✓ 全業務フローの洗い出し</li>
<li>✓ 属人的業務の特定・仕分け</li>
<li>✓ 自動化ロードマップ策定</li>
</ul>
</div>

<div style="background:#e8f4f8;border-radius:12px;padding:2rem;text-align:center">
<p style="font-size:.85rem;color:#1a3a5c;font-weight:700;margin:0">MONTH 2</p>
<h3 style="font-size:1.3rem;margin:.5rem 0">構築</h3>
<ul style="text-align:left;font-size:.9rem;color:#555;list-style:none;padding:0">
<li>✓ CRM・顧客管理の構築</li>
<li>✓ 見積・請求の自動化</li>
<li>✓ KPIレポート自動生成</li>
<li>✓ メール・通知の自動化</li>
</ul>
</div>

<div style="background:#e8f4f8;border-radius:12px;padding:2rem;text-align:center">
<p style="font-size:.85rem;color:#1a3a5c;font-weight:700;margin:0">MONTH 3</p>
<h3 style="font-size:1.3rem;margin:.5rem 0">定着</h3>
<ul style="text-align:left;font-size:.9rem;color:#555;list-style:none;padding:0">
<li>✓ 運用マニュアル整備</li>
<li>✓ 社長不在テスト（1週間）</li>
<li>✓ 引継ぎ資料の完備</li>
</ul>
</div>

</div>
</div>

<!-- BEFORE/AFTER TABLE -->
<div style="margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:1.5rem">導入効果</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<thead>
<tr style="background:#1a3a5c;color:#fff">
<th style="padding:12px 16px;text-align:left">項目</th>
<th style="padding:12px 16px;text-align:center">Before</th>
<th style="padding:12px 16px;text-align:center">After</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">社長依存度</td>
<td style="padding:12px 16px;text-align:center;color:#e63946;font-weight:700">100%</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0;font-weight:700">10〜20%</td>
</tr>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">業務の再現性</td>
<td style="padding:12px 16px;text-align:center;color:#e63946">なし</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0">マニュアル+システム化済み</td>
</tr>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">問い合わせ対応</td>
<td style="padding:12px 16px;text-align:center;color:#e63946">3時間</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0;font-weight:700">15分</td>
</tr>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">レポート作成</td>
<td style="padding:12px 16px;text-align:center;color:#e63946">2時間/週</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0;font-weight:700">0秒（全自動）</td>
</tr>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">想定売却倍率</td>
<td style="padding:12px 16px;text-align:center;color:#e63946">年利益の1〜2倍</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0;font-weight:700">年利益の3〜5倍</td>
</tr>
</tbody>
</table>
</div>

<!-- COST COMPARISON -->
<div style="background:#f8f9fa;border-radius:12px;padding:2.5rem;margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:1.5rem">他の手段との比較</h2>
<table style="width:100%;border-collapse:collapse;font-size:.95rem">
<thead>
<tr style="background:#333;color:#fff">
<th style="padding:12px 16px;text-align:left">手段</th>
<th style="padding:12px 16px;text-align:center">初期費用</th>
<th style="padding:12px 16px;text-align:center">月額</th>
<th style="padding:12px 16px;text-align:center">期間</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">SIer / システム開発</td>
<td style="padding:12px 16px;text-align:center">500〜1,000万円</td>
<td style="padding:12px 16px;text-align:center">保守10万円〜</td>
<td style="padding:12px 16px;text-align:center">6ヶ月〜1年</td>
</tr>
<tr style="border-bottom:1px solid #e0e0e0">
<td style="padding:12px 16px">SaaS複数導入</td>
<td style="padding:12px 16px;text-align:center">導入支援50万円〜</td>
<td style="padding:12px 16px;text-align:center">5〜15万円</td>
<td style="padding:12px 16px;text-align:center">3ヶ月〜</td>
</tr>
<tr style="background:#e8f4f8;font-weight:700">
<td style="padding:12px 16px">本プログラム</td>
<td style="padding:12px 16px;text-align:center">個別見積</td>
<td style="padding:12px 16px;text-align:center">月額運用費あり</td>
<td style="padding:12px 16px;text-align:center;color:#06d6a0">1〜3ヶ月</td>
</tr>
</tbody>
</table>
<p style="text-align:center;font-size:.85rem;color:#888;margin-top:1rem">※初回パイロット案件は特別条件でご相談可能</p>
</div>

<!-- FAQ SECTION -->
<div style="margin:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin-bottom:2rem">よくある質問</h2>

<div style="border-bottom:1px solid #e0e0e0;padding:1.2rem 0">
<p style="font-weight:700;margin:0 0 .5rem">Q. プログラミングの知識は必要ですか？</p>
<p style="color:#555;margin:0">A. 一切不要です。全ての構築は日本語の指示だけで完結します。社長様やスタッフの方にプログラミングスキルは求めません。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.2rem 0">
<p style="font-weight:700;margin:0 0 .5rem">Q. どんな規模の会社が対象ですか？</p>
<p style="color:#555;margin:0">A. 年商数百万円〜数千万円、従業員1〜20名程度の中小・零細企業が最も効果を発揮します。大企業向けのITシステムでは対応できなかった層です。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.2rem 0">
<p style="font-weight:700;margin:0 0 .5rem">Q. 自動化した後の保守は必要ですか？</p>
<p style="color:#555;margin:0">A. 月額の運用サポートプランをご用意しています。システムの安定稼働と改善を継続的にサポートします。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.2rem 0">
<p style="font-weight:700;margin:0 0 .5rem">Q. M&A仲介会社・事業承継コンサルとの違いは？</p>
<p style="color:#555;margin:0">A. 仲介やコンサルは「マッチング」が主業務。当社は「買収後の価値向上」に特化しています。社長がいなくても回る会社に実際に変えることで、買い手がつきやすくなります。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.2rem 0">
<p style="font-weight:700;margin:0 0 .5rem">Q. 秘密保持は大丈夫ですか？</p>
<p style="color:#555;margin:0">A. NDA（秘密保持契約）を締結した上で業務に着手します。お客様の業務データは厳重に管理いたします。</p>
</div>

</div>

<!-- FINAL CTA -->
<div style="background:linear-gradient(135deg,#1a3a5c 0%,#2d5a8c 100%);color:#fff;border-radius:12px;padding:3rem;text-align:center;margin:3rem 0">
<h2 style="color:#fff;font-size:1.5rem;margin:0 0 1rem">まずは1社、パイロットからはじめませんか？</h2>
<p style="color:#ccc;margin:0 0 2rem;font-size:1rem">初回は特別条件でご相談可能。お気軽にお問い合わせください。</p>
<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap">
<a href="/contact/" style="display:inline-block;padding:16px 36px;background:#ffd166;color:#1a3a5c;text-decoration:none;border-radius:8px;font-weight:700;font-size:1.05rem">無料相談する（最短当日回答）</a>
<a href="tel:05071177141" style="display:inline-block;padding:16px 36px;border:2px solid #fff;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:1.05rem">050-7117-7141</a>
</div>
</div>

<!-- COMPANY INFO -->
<div style="text-align:center;padding:2rem 0;color:#888;font-size:.85rem">
<p style="margin:0">運営: 東海エアサービス株式会社　代表 國本洋輔</p>
<p style="margin:.3rem 0">名古屋市 ｜ <a href="https://www.tokaiair.com/" style="color:#1a3a5c">tokaiair.com</a></p>
</div>

</div>
<!-- /wp:group -->
"""
    return html.strip()


def build_faq_schema():
    """FAQ structured data for SEO/AEO"""
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "AI業務自動化にプログラミングの知識は必要ですか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "一切不要です。全ての構築は日本語の指示だけで完結します。"
                }
            },
            {
                "@type": "Question",
                "name": "どんな規模の会社がAI業務自動化の対象ですか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "年商数百万円〜数千万円、従業員1〜20名程度の中小・零細企業が最も効果を発揮します。"
                }
            },
            {
                "@type": "Question",
                "name": "AI業務自動化の費用はいくらですか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "初期費用は個別見積、月額運用費ありのプランです。SIerの500〜1000万円やSaaS月額5〜15万円と比較して大幅に低コストで導入可能です。初回パイロット案件は特別条件でご相談可能です。"
                }
            },
            {
                "@type": "Question",
                "name": "事業承継・M&Aにおけるバリューアップとは？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "属人的な業務をAIで自動化し、社長依存度を100%から10〜20%に下げることで、想定売却倍率を年利益の1〜2倍から3〜5倍に引き上げるプログラムです。"
                }
            },
            {
                "@type": "Question",
                "name": "AI業務自動化にはどのくらいの期間がかかりますか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "標準3ヶ月プログラムです。1ヶ月目に業務可視化、2ヶ月目にシステム構築、3ヶ月目に定着・引継ぎを行います。"
                }
            }
        ]
    }


def build_service_schema():
    """Service structured data"""
    return {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": "AI業務自動化プログラム（事業承継バリューアップ）",
        "description": "買収後1〜3ヶ月の業務自動化で社長依存を解消し、バリュエーション3〜5倍を実現するプログラム",
        "provider": {
            "@type": "Organization",
            "name": "東海エアサービス株式会社",
            "url": "https://www.tokaiair.com/",
            "telephone": "050-7117-7141",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": "名古屋市",
                "addressCountry": "JP"
            }
        },
        "areaServed": "JP",
        "serviceType": "AI業務自動化・事業承継支援",
        "offers": {
            "@type": "Offer",
            "description": "初回パイロット案件は特別条件でご相談可能",
            "priceCurrency": "JPY"
        }
    }


def create_or_update_page(publish=False, update=False):
    """Create or update the AI ValueUp LP page"""
    content = build_lp_html()
    status = "publish" if publish else "draft"

    page_data = {
        "title": "AI業務自動化プログラム｜事業承継・バリューアップ支援",
        "content": content,
        "status": status,
        "slug": "ai-valueup",
        "meta": {
            "_yoast_wpseo_title": "AI業務自動化で事業承継を成功させる｜東海エアサービス",
            "_yoast_wpseo_metadesc": "属人的な中小企業の業務をAIで自動化し、社長依存度を解消。買収後1〜3ヶ月でバリュエーション3〜5倍を実現するプログラム。初回パイロット特別条件あり。",
        }
    }

    if update:
        existing_id = find_existing_page()
        if existing_id:
            result = wp_request(f"pages/{existing_id}", method="POST", data=page_data)
            if result:
                print(f"✓ Page updated: ID {result['id']}")
                print(f"  URL: {result.get('link', 'N/A')}")
                return result["id"]
            return None
        else:
            print("  Page not found. Creating new...")

    # Create new
    parent_id = find_parent_page()
    if parent_id:
        page_data["parent"] = parent_id

    result = wp_request("pages", method="POST", data=page_data)
    if result:
        print(f"✓ Page created: ID {result['id']} ({status})")
        print(f"  URL: {result.get('link', 'N/A')}")
        return result["id"]
    else:
        print("✗ Page creation failed")
        return None


def main():
    publish = "--publish" in sys.argv
    update = "--update" in sys.argv

    print("=" * 60)
    print("AIバリューアップ事業部 LP作成")
    print("=" * 60)

    page_id = create_or_update_page(publish=publish, update=update)
    if page_id:
        print(f"\n{'公開' if publish else 'ドラフト'}作成完了。")
        print(f"Page ID: {page_id}")

        # Output structured data for Code Snippets
        faq_schema = build_faq_schema()
        service_schema = build_service_schema()
        schemas = {"faq": faq_schema, "service": service_schema}
        schema_file = SCRIPT_DIR / "ai_valueup_schemas.json"
        with open(schema_file, "w") as f:
            json.dump(schemas, f, ensure_ascii=False, indent=2)
        print(f"  Structured data saved to: {schema_file}")
    else:
        print("\n作成失敗。")
        sys.exit(1)


if __name__ == "__main__":
    main()
