#!/usr/bin/env python3
"""
TOMOSHI LP作成・更新スクリプト
「事業の灯を、消さない。」

当面はtokaiair.com/services/ai-valueup/を更新（独立ドメイン取得まで）
独立ドメイン取得後はそちらに移行

Usage:
  python3 tomoshi_lp.py             # 既存ページを更新
  python3 tomoshi_lp.py --publish   # 公開
  python3 tomoshi_lp.py --new       # 新規作成
"""

import json
import os
import sys
import base64
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "automation_config.json"

with open(CONFIG_FILE) as f:
    CONFIG = json.load(f)

WP_BASE = CONFIG["wordpress"]["base_url"]
WP_USER = CONFIG["wordpress"]["user"]
WP_APP_PASSWORD = CONFIG["wordpress"]["app_password"]
WP_AUTH = base64.b64encode(f"{WP_USER}:{WP_APP_PASSWORD}".encode()).decode()

# 既存ページID（ai_valueup_lp.pyで作成済み）
EXISTING_PAGE_ID = 5937


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


def build_lp_html():
    """TOMOSHI LP - 「事業の灯を、消さない。」"""

    # カラー定義
    navy = "#1a2a3a"
    amber = "#e8a838"
    warm_bg = "#fdf8f0"
    dark_bg = "#1a2a3a"
    text = "#333"
    muted = "#666"

    html = f"""
<!-- wp:group {{"style":{{"spacing":{{"padding":{{"top":"0px","bottom":"0px"}}}}}},"layout":{{"type":"constrained","contentSize":"960px"}}}} -->
<div class="wp-block-group" style="padding-top:0;padding-bottom:0">

<!-- ═══════════════════ HERO ═══════════════════ -->
<div style="background:{dark_bg};color:#fff;padding:80px 24px;text-align:center;margin:0 -24px">
<p style="font-size:.85rem;letter-spacing:4px;color:{amber};font-weight:600;margin:0 0 1rem">T O M O S H I</p>
<h1 style="font-size:2.4rem;line-height:1.5;margin:0 0 1.5rem;font-weight:700;color:#fff">事業の灯を、消さない。</h1>
<p style="font-size:1.1rem;color:#ccc;max-width:560px;margin:0 auto 2.5rem;line-height:1.8">
後継者がいなくても、廃業しなくていい。<br>
あなたが灯した事業を、仕組みで守り、次につなぐ。
</p>
<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap">
<a href="/contact/" style="display:inline-block;padding:16px 36px;background:{amber};color:{navy};text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem">まずは相談する</a>
<a href="tel:05071177141" style="display:inline-block;padding:16px 36px;border:2px solid #fff;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:1rem">050-7117-7141</a>
</div>
</div>

<!-- ═══════════════════ 社会課題 ═══════════════════ -->
<div style="padding:4rem 0;text-align:center">
<p style="font-size:3rem;font-weight:700;color:{navy};margin:0">127万社</p>
<p style="font-size:1.1rem;color:{muted};margin:.5rem 0 2rem">後継者不在で廃業の危機にある日本の中小企業の数。</p>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:2rem;max-width:720px;margin:0 auto">
<div>
<p style="font-size:2.2rem;font-weight:700;color:#c0392b;margin:0">年間5万社</p>
<p style="font-size:.85rem;color:{muted};margin:.3rem 0 0">黒字なのに廃業する企業数</p>
</div>
<div>
<p style="font-size:2.2rem;font-weight:700;color:#c0392b;margin:0">70歳超</p>
<p style="font-size:.85rem;color:{muted};margin:.3rem 0 0">中小企業経営者の平均年齢</p>
</div>
<div>
<p style="font-size:2.2rem;font-weight:700;color:#c0392b;margin:0">650万人</p>
<p style="font-size:.85rem;color:{muted};margin:.3rem 0 0">廃業で失われる雇用</p>
</div>
</div>
</div>

<!-- ═══════════════════ なぜ廃業するのか ═══════════════════ -->
<div style="background:{warm_bg};border-radius:16px;padding:3rem;margin:2rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin:0 0 1rem;color:{navy}">なぜ、黒字なのに廃業するのか？</h2>
<p style="text-align:center;color:{muted};margin:0 0 2rem;font-size:1rem">原因は赤字ではありません。<strong>「社長にしかできない」状態</strong>が問題です。</p>

<div style="background:#fff;border-radius:12px;padding:2rem;font-size:.95rem;line-height:2;color:{text}">
<p style="margin:0;font-weight:700">社長の頭の中に全てがある：</p>
<p style="margin:.5rem 0 0;padding-left:1rem">
顧客情報 → 社長の携帯と記憶<br>
見積ノウハウ → 社長の経験と勘<br>
請求・入金 → 奥さんのExcel<br>
営業・受注 → 社長の人脈<br>
経営数字 → 社長の頭の中
</p>
<p style="margin:1.5rem 0 0;font-weight:700;color:#c0392b;text-align:center;font-size:1.05rem">
社長 = 会社そのもの → 社長が抜けたら会社が止まる → 誰にも渡せない
</p>
</div>

<p style="text-align:center;margin:2rem 0 0;font-size:1rem;color:{text}">
しかし、これらの業務の大半は<br>
<strong>「社長にしかできない判断」ではなく、情報の転記・加工・通知</strong>。<br>
つまり、<strong>仕組みに置き換えられるものが、属人化しているだけ</strong>です。
</p>
</div>

<!-- ═══════════════════ TOMOSHIがやること ═══════════════════ -->
<div style="padding:4rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin:0 0 .5rem;color:{navy}">TOMOSHIがやること</h2>
<p style="text-align:center;color:{muted};margin:0 0 3rem">社長の頭の中にある業務を、仕組みに移し替えます。</p>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:2rem">

<div style="text-align:center;padding:2rem">
<p style="font-size:2.5rem;margin:0 0 .5rem">1</p>
<h3 style="font-size:1.15rem;color:{navy};margin:0 0 .5rem">可視化する</h3>
<p style="font-size:.9rem;color:{muted};margin:0">全ての業務フローを洗い出し、「社長にしかできないこと」と「仕組みに移せること」を仕分けます。</p>
</div>

<div style="text-align:center;padding:2rem">
<p style="font-size:2.5rem;margin:0 0 .5rem">2</p>
<h3 style="font-size:1.15rem;color:{navy};margin:0 0 .5rem">仕組みに移す</h3>
<p style="font-size:.9rem;color:{muted};margin:0">顧客管理、見積、請求、レポート、メール対応を自動化。社長がいなくても回る状態を作ります。</p>
</div>

<div style="text-align:center;padding:2rem">
<p style="font-size:2.5rem;margin:0 0 .5rem">3</p>
<h3 style="font-size:1.15rem;color:{navy};margin:0 0 .5rem">渡せる状態にする</h3>
<p style="font-size:.9rem;color:{muted};margin:0">マニュアル・システム一式を整備。後継者や新オーナーが安心して引き継げる状態を証明します。</p>
</div>

</div>
</div>

<!-- ═══════════════════ 導入効果 ═══════════════════ -->
<div style="background:{dark_bg};color:#fff;border-radius:16px;padding:3rem;margin:2rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin:0 0 2rem;color:#fff">変わるもの</h2>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:0;max-width:720px;margin:0 auto">

<div style="padding:1.5rem;border-bottom:1px solid rgba(255,255,255,.1)">
<p style="font-size:.85rem;color:{amber};margin:0">社長依存度</p>
<p style="margin:.3rem 0 0"><span style="color:#888;text-decoration:line-through">100%</span> → <span style="font-size:1.3rem;font-weight:700;color:{amber}">10〜20%</span></p>
</div>

<div style="padding:1.5rem;border-bottom:1px solid rgba(255,255,255,.1)">
<p style="font-size:.85rem;color:{amber};margin:0">業務の再現性</p>
<p style="margin:.3rem 0 0"><span style="color:#888;text-decoration:line-through">社長の勘</span> → <span style="font-size:1.3rem;font-weight:700;color:{amber}">マニュアル＋システム</span></p>
</div>

<div style="padding:1.5rem;border-bottom:1px solid rgba(255,255,255,.1)">
<p style="font-size:.85rem;color:{amber};margin:0">引き継ぎの安心感</p>
<p style="margin:.3rem 0 0"><span style="color:#888;text-decoration:line-through">不安（何もわからない）</span> → <span style="font-size:1.3rem;font-weight:700;color:{amber}">全て見える化済み</span></p>
</div>

<div style="padding:1.5rem;border-bottom:1px solid rgba(255,255,255,.1)">
<p style="font-size:.85rem;color:{amber};margin:0">売却時の評価</p>
<p style="margin:.3rem 0 0"><span style="color:#888;text-decoration:line-through">年利益の1〜2倍</span> → <span style="font-size:1.3rem;font-weight:700;color:{amber}">年利益の3〜5倍</span></p>
</div>

</div>
</div>

<!-- ═══════════════════ 対象業種 ═══════════════════ -->
<div style="padding:4rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin:0 0 .5rem;color:{navy}">こんな会社の灯を守ります</h2>
<p style="text-align:center;color:{muted};margin:0 0 2rem">「社長が全て」の業種ほど、効果が大きい。</p>

<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem">

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">🏭</span>
<div><strong style="color:{navy}">製造業・町工場</strong><br><span style="font-size:.85rem;color:{muted}">見積は社長の勘、図面は社長の頭の中 → 全てデータベース化</span></div>
</div>

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">📋</span>
<div><strong style="color:{navy}">税理士・会計事務所</strong><br><span style="font-size:.85rem;color:{muted}">顧問先300社の仕訳が属人化 → 自動分類・レポート生成</span></div>
</div>

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">🏗️</span>
<div><strong style="color:{navy}">建設・リフォーム</strong><br><span style="font-size:.85rem;color:{muted}">現場管理・見積・下請け手配が全て社長 → 工程管理を仕組み化</span></div>
</div>

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">🚗</span>
<div><strong style="color:{navy}">中古車販売</strong><br><span style="font-size:.85rem;color:{muted}">仕入れの目利きが社長だけ → 価格データベース＋在庫最適化</span></div>
</div>

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">⚰️</span>
<div><strong style="color:{navy}">葬儀業</strong><br><span style="font-size:.85rem;color:{muted}">24時間社長の携帯対応 → 受付・手配・在庫管理を自動化</span></div>
</div>

<div style="display:flex;align-items:flex-start;gap:1rem;padding:1.2rem;border:1px solid #e8e0d8;border-radius:10px;background:#fff">
<span style="font-size:1.8rem;flex-shrink:0">🏥</span>
<div><strong style="color:{navy}">調剤薬局</strong><br><span style="font-size:.85rem;color:{muted}">在庫管理が勘頼み → 需要予測＋期限管理を自動化</span></div>
</div>

</div>
</div>

<!-- ═══════════════════ メッセージ ═══════════════════ -->
<div style="background:{warm_bg};border-radius:16px;padding:3rem;margin:2rem 0;text-align:center">
<h2 style="font-size:1.3rem;color:{navy};margin:0 0 1.5rem">閉める前に、一度だけご相談ください。</h2>
<p style="font-size:1rem;color:{text};max-width:560px;margin:0 auto;line-height:2">
「後継者がいないから閉める」<br>
「自分がいないと回らないから売れない」<br><br>
そう思っていませんか？<br><br>
あなたが40年かけて積み上げたもの——<br>
お客様との信頼、社員の技術、地域での信用。<br><br>
それを消す必要はありません。<br>
<strong>仕組みに移し替えれば、事業は続けられます。</strong>
</p>
</div>

<!-- ═══════════════════ FAQ ═══════════════════ -->
<div style="padding:3rem 0">
<h2 style="font-size:1.5rem;text-align:center;margin:0 0 2rem;color:{navy}">よくある質問</h2>

<div style="border-bottom:1px solid #e0e0e0;padding:1.5rem 0">
<p style="font-weight:700;color:{navy};margin:0 0 .5rem">Q. うちのような小さな会社でも対象になりますか？</p>
<p style="color:{muted};margin:0">A. はい。年商数百万円〜数千万円、従業員1〜20名程度の会社が最も効果を発揮します。小さいからこそ、短期間で仕組み化が完了します。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.5rem 0">
<p style="font-weight:700;color:{navy};margin:0 0 .5rem">Q. パソコンに詳しくないのですが大丈夫ですか？</p>
<p style="color:{muted};margin:0">A. 大丈夫です。専門知識は一切不要です。社長やスタッフの方にお話を聞かせていただくだけで、こちらで全て構築します。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.5rem 0">
<p style="font-weight:700;color:{navy};margin:0 0 .5rem">Q. 社員の雇用は守られますか？</p>
<p style="color:{muted};margin:0">A. はい。業務の自動化は「社員を減らす」ためではなく、「社長がいなくても社員が働ける状態を作る」ためのものです。雇用と取引先の維持を最優先にしています。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.5rem 0">
<p style="font-weight:700;color:{navy};margin:0 0 .5rem">Q. 費用はどれくらいかかりますか？</p>
<p style="color:{muted};margin:0">A. 初回は無料で業務診断レポートをお出しします。その上で、やるかやらないかをご判断いただけます。正式なプログラムの費用は個別にご相談ください。</p>
</div>

<div style="border-bottom:1px solid #e0e0e0;padding:1.5rem 0">
<p style="font-weight:700;color:{navy};margin:0 0 .5rem">Q. 秘密は守られますか？</p>
<p style="color:{muted};margin:0">A. NDA（秘密保持契約）を締結してから着手します。経営情報や顧客データは厳重に管理いたします。</p>
</div>
</div>

<!-- ═══════════════════ FINAL CTA ═══════════════════ -->
<div style="background:linear-gradient(135deg,{navy} 0%,#2d4a6c 100%);color:#fff;border-radius:16px;padding:3.5rem;text-align:center;margin:2rem 0">
<p style="font-size:.85rem;letter-spacing:3px;color:{amber};margin:0 0 .5rem">T O M O S H I</p>
<h2 style="color:#fff;font-size:1.5rem;margin:0 0 1rem">事業の灯を、消さない。</h2>
<p style="color:#ccc;margin:0 0 2rem;font-size:1rem">まずはお話をお聞かせください。<br>業務診断レポートを無料でお出しします。</p>
<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap">
<a href="/contact/" style="display:inline-block;padding:16px 40px;background:{amber};color:{navy};text-decoration:none;border-radius:8px;font-weight:700;font-size:1.05rem">無料相談する</a>
<a href="tel:05071177141" style="display:inline-block;padding:16px 40px;border:2px solid #fff;color:#fff;text-decoration:none;border-radius:8px;font-weight:700;font-size:1.05rem">050-7117-7141</a>
</div>
</div>

<!-- ═══════════════════ FOOTER ═══════════════════ -->
<div style="text-align:center;padding:2rem 0;color:#999;font-size:.8rem">
<p style="margin:0">TOMOSHI｜事業の灯を、消さない。</p>
<p style="margin:.3rem 0">運営: 東海エアサービス株式会社　名古屋市</p>
</div>

</div>
<!-- /wp:group -->
"""
    return html.strip()


def build_schemas():
    """Structured data for TOMOSHI"""
    faq_schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": "小さな会社でもTOMOSHIの事業承継支援の対象になりますか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "はい。年商数百万円〜数千万円、従業員1〜20名程度の中小・零細企業が最も効果を発揮します。"
                }
            },
            {
                "@type": "Question",
                "name": "TOMOSHIの業務自動化にパソコンの知識は必要ですか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "一切不要です。社長やスタッフにお話を聞かせていただくだけで、こちらで全て構築します。"
                }
            },
            {
                "@type": "Question",
                "name": "事業承継で社員の雇用は守られますか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "はい。業務の自動化は社長がいなくても社員が働ける状態を作るためのものです。雇用と取引先の維持を最優先にしています。"
                }
            },
            {
                "@type": "Question",
                "name": "TOMOSHIの費用はどれくらいですか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "初回は無料で業務診断レポートをお出しします。その上でやるかやらないかをご判断いただけます。"
                }
            },
            {
                "@type": "Question",
                "name": "後継者がいなくても事業は続けられますか？",
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": "はい。TOMOSHIは社長の頭の中にある業務を仕組みに移し替えることで、社長依存度を100%から10〜20%に下げ、後継者や新オーナーが安心して引き継げる状態を作ります。"
                }
            }
        ]
    }

    service_schema = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": "TOMOSHI 事業承継バリューアップ",
        "description": "後継者不在の中小企業の業務を自動化し、社長依存を解消。事業の灯を消さずに次につなぐプログラム。",
        "provider": {
            "@type": "Organization",
            "name": "TOMOSHI",
            "url": "https://www.tokaiair.com/services/ai-valueup/",
            "telephone": "050-7117-7141"
        },
        "areaServed": "JP",
        "serviceType": "事業承継支援・業務自動化"
    }

    return {"faq": faq_schema, "service": service_schema}


def update_page(publish=False, create_new=False):
    content = build_lp_html()
    status = "publish" if publish else "draft"

    page_data = {
        "title": "TOMOSHI｜事業の灯を、消さない。",
        "content": content,
        "status": status,
        "slug": "ai-valueup",
        "meta": {
            "_yoast_wpseo_title": "TOMOSHI｜事業の灯を、消さない。― 事業承継×業務自動化",
            "_yoast_wpseo_metadesc": "後継者がいなくても廃業しなくていい。TOMOSHIは属人的な業務を仕組みに移し替え、社長がいなくても回る会社を作ります。業務診断レポート無料。",
        }
    }

    if create_new:
        result = wp_request("pages", method="POST", data=page_data)
        if result:
            print(f"✓ New page created: ID {result['id']} ({status})")
            print(f"  URL: {result.get('link', 'N/A')}")
            return result["id"]
    else:
        result = wp_request(f"pages/{EXISTING_PAGE_ID}", method="POST", data=page_data)
        if result:
            print(f"✓ Page updated: ID {result['id']} ({status})")
            print(f"  URL: {result.get('link', 'N/A')}")
            return result["id"]

    print("✗ Failed")
    return None


def main():
    publish = "--publish" in sys.argv
    create_new = "--new" in sys.argv

    print("=" * 60)
    print("TOMOSHI LP — 事業の灯を、消さない。")
    print("=" * 60)

    page_id = update_page(publish=publish, create_new=create_new)
    if page_id:
        schemas = build_schemas()
        schema_file = SCRIPT_DIR / "tomoshi_schemas.json"
        with open(schema_file, "w") as f:
            json.dump(schemas, f, ensure_ascii=False, indent=2)
        print(f"  Schemas saved: {schema_file}")


if __name__ == "__main__":
    main()
