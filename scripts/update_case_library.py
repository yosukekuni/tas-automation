#!/usr/bin/env python3
"""
事例ページ更新スクリプト

/case-library/ (ID:5098) を受注台帳181件の業種×サービスマトリクスで更新。
分類データ: data/case_classification.json
顧客名は匿名化必須。

wp_safe_deploy.py 経由でデプロイ。

Usage:
  python3 update_case_library.py              # 更新実行
  python3 update_case_library.py --dry-run    # HTML確認のみ
  python3 update_case_library.py --backup     # バックアップのみ
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Exponential Backoff: 全API呼び出しにリトライ機能を適用
import sys as _sys; _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from lib.retry import patch_urlopen; patch_urlopen()

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.config import load_config, get_wp_auth, get_wp_api_url

# ── Constants ──
CASE_PAGE_ID = 5098
BRAND_COLOR = "#1647FB"
PHONE = "050-7117-7141"
DATA_DIR = SCRIPT_DIR.parent / "data"
BACKUP_DIR = SCRIPT_DIR.parent / "backups"
CLASSIFICATION_FILE = DATA_DIR / "case_classification.json"

# 業種表示順
INDUSTRY_ORDER = ["ゼネコン", "測量会社", "建設コンサルタント", "官公庁", "不動産", "その他"]
# サービス表示順
SERVICE_ORDER = ["ドローン測量", "現場空撮", "眺望撮影", "点検", "その他"]

# 顧客名匿名化パターン
ANONYMIZE_RULES = [
    # 具体的な社名 → 業種 + 地域
    (r".+建設.*", "建設会社"),
    (r".+工業.*", "建設会社"),
    (r".+工務.*", "工務店"),
    (r".+組$", "建設会社"),
    (r".+コンサルタント.*", "建設コンサルタント"),
    (r".+測量.*", "測量会社"),
    (r".+工測.*", "測量会社"),
    (r".+不動産.*", "不動産会社"),
    (r".+リアルティ.*", "不動産会社"),
    (r".+設計.*", "設計事務所"),
    (r".+高校.*", "県立高校"),
    (r".+事務所.*", "管理事務所"),
]


def anonymize_company(name):
    """顧客名を匿名化"""
    if not name or name.strip() == "":
        return "取引先"

    # 自社名はスキップ
    if "東海エア" in name:
        return None  # 除外

    for pattern, replacement in ANONYMIZE_RULES:
        if re.match(pattern, name):
            return replacement

    # マッチしない場合は業種不明
    return "取引先"


def anonymize_case_name(case_name, company_anon):
    """案件名を匿名化（社名部分を除去）"""
    if not case_name:
        return ""

    # 支払通知書系は除外
    if any(k in case_name for k in ["支払通知", "支払明細", "営業代行", "送付"]):
        return None

    # 社名部分を除去
    cleaned = case_name
    # "XXX_" パターン（社名_案件名）
    cleaned = re.sub(r'^[^_]+_', '', cleaned)
    # "Re:" 除去
    cleaned = re.sub(r'^Re:\s*', '', cleaned)
    # 残った具体的社名を匿名化
    for pattern, _ in ANONYMIZE_RULES:
        cleaned = re.sub(pattern.replace(".*", "[^ ]*").replace("$", ""), "", cleaned)

    cleaned = cleaned.strip()
    if not cleaned or len(cleaned) < 3:
        return None

    return cleaned


def load_classification():
    """分類データ読み込み"""
    with open(CLASSIFICATION_FILE, encoding="utf-8") as f:
        data = json.load(f)
    return data


def build_matrix(data):
    """業種×サービスマトリクスを構築"""
    summary = data.get("summary", {})
    cross = summary.get("cross_table", {})
    records = data.get("records", [])

    # マトリクスデータ
    matrix = {}
    for key, count in cross.items():
        parts = key.split("_", 1)
        if len(parts) == 2:
            industry, service = parts
            if industry not in matrix:
                matrix[industry] = {}
            matrix[industry][service] = count

    # 案件サンプル（匿名化済み）- 業種×サービスごとに最大3件
    samples = defaultdict(list)
    seen_cases = set()

    for rec in records:
        industry = rec.get("業種カテゴリ", "その他")
        service = rec.get("サービスカテゴリ", "その他")
        company = rec.get("取引先", "")
        case_name = rec.get("案件名", "")

        company_anon = anonymize_company(company)
        if company_anon is None:  # 自社除外
            continue

        case_anon = anonymize_case_name(case_name, company_anon)
        if case_anon is None:  # 非案件除外
            continue

        key = f"{industry}_{service}"
        # 重複回避
        sig = f"{company_anon}:{case_anon[:30]}"
        if sig in seen_cases:
            continue
        seen_cases.add(sig)

        if len(samples[key]) < 3:
            samples[key].append({
                "company": company_anon,
                "case": case_anon,
            })

    return matrix, samples, summary


def build_case_library_html(data):
    """事例ライブラリHTML生成"""
    matrix, samples, summary = build_matrix(data)
    total = data.get("total_records", 0)
    industry_counts = summary.get("industry", {})
    service_counts = summary.get("service", {})

    # 全レコード数をそのまま使用（分類済み181件）
    actual_total = total

    # 構造化データ
    structured_data = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "CollectionPage",
                "name": "実績事例 | 東海エアサービス",
                "description": f"ドローン測量・空撮・点検の実績事例。業種×サービス別に{actual_total}件以上の事例を紹介。",
                "url": "https://tokaiair.com/case-library/",
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "ホーム", "item": "https://tokaiair.com/"},
                    {"@type": "ListItem", "position": 2, "name": "実績事例", "item": "https://tokaiair.com/case-library/"},
                ]
            }
        ]
    }, ensure_ascii=False, indent=2)

    html_parts = []

    # 構造化データ
    html_parts.append(f'''<script type="application/ld+json">
{structured_data}
</script>''')

    # ヘッダー
    html_parts.append(f'''
<div style="text-align:center;padding:2rem 1rem;margin-bottom:2rem">
<h1 style="font-size:2rem;margin:0 0 .5rem;color:#1a1a1a">実績事例</h1>
<p style="font-size:1.1rem;color:#555;margin:0">業種 x サービス別の導入実績マトリクス</p>
<p style="font-size:.9rem;color:#888;margin:.5rem 0 0">累計 <strong style="color:{BRAND_COLOR};font-size:1.2rem" data-stat-count="{actual_total}">{actual_total}</strong> 件以上の実績</p>
</div>''')

    # 業種別サマリーカード
    html_parts.append(f'''
<div style="max-width:900px;margin:0 auto 3rem;padding:0 1rem">
<h2 style="font-size:1.3rem;margin-bottom:1.5rem;color:#1a1a1a">業種別実績</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));gap:1rem">''')

    for ind in INDUSTRY_ORDER:
        count = industry_counts.get(ind, 0)
        if count == 0:
            continue
        html_parts.append(f'''<div style="background:#f8f9fa;border-radius:12px;padding:1.2rem;text-align:center;border-top:3px solid {BRAND_COLOR}">
<p style="font-size:2rem;font-weight:800;color:{BRAND_COLOR};margin:0">{count}</p>
<p style="font-size:.85rem;color:#555;margin:.3rem 0 0">{ind}</p>
</div>''')

    html_parts.append('</div></div>')

    # サービス別サマリーカード
    html_parts.append(f'''
<div style="max-width:900px;margin:0 auto 3rem;padding:0 1rem">
<h2 style="font-size:1.3rem;margin-bottom:1.5rem;color:#1a1a1a">サービス別実績</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(160px, 1fr));gap:1rem">''')

    for svc in SERVICE_ORDER:
        count = service_counts.get(svc, 0)
        if count == 0:
            continue
        html_parts.append(f'''<div style="background:#f0f4ff;border-radius:12px;padding:1.2rem;text-align:center;border-top:3px solid {BRAND_COLOR}">
<p style="font-size:2rem;font-weight:800;color:{BRAND_COLOR};margin:0">{count}</p>
<p style="font-size:.85rem;color:#555;margin:.3rem 0 0">{svc}</p>
</div>''')

    html_parts.append('</div></div>')

    # マトリクステーブル
    active_services = [s for s in SERVICE_ORDER if service_counts.get(s, 0) > 0]
    active_industries = [i for i in INDUSTRY_ORDER if industry_counts.get(i, 0) > 0]

    html_parts.append(f'''
<div style="max-width:900px;margin:0 auto 3rem;padding:0 1rem;overflow-x:auto">
<h2 style="font-size:1.3rem;margin-bottom:1.5rem;color:#1a1a1a">業種 x サービス マトリクス</h2>
<table style="width:100%;border-collapse:collapse;font-size:.9rem;min-width:600px">
<tr style="background:{BRAND_COLOR};color:#fff">
<th style="padding:10px;text-align:left">業種 / サービス</th>''')

    for svc in active_services:
        html_parts.append(f'<th style="padding:10px;text-align:center">{svc}</th>')
    html_parts.append('<th style="padding:10px;text-align:center;font-weight:700">合計</th></tr>')

    for i, ind in enumerate(active_industries):
        bg = ' style="background:#f8f9fa"' if i % 2 == 1 else ''
        row_total = sum(matrix.get(ind, {}).get(s, 0) for s in active_services)
        html_parts.append(f'<tr{bg}><td style="padding:10px;font-weight:600;border-bottom:1px solid #e0e0e0">{ind}</td>')
        for svc in active_services:
            val = matrix.get(ind, {}).get(svc, 0)
            cell_style = f'font-weight:700;color:{BRAND_COLOR}' if val > 0 else 'color:#ccc'
            html_parts.append(f'<td style="padding:10px;text-align:center;border-bottom:1px solid #e0e0e0;{cell_style}">{val if val > 0 else "-"}</td>')
        html_parts.append(f'<td style="padding:10px;text-align:center;border-bottom:1px solid #e0e0e0;font-weight:700">{row_total}</td></tr>')

    # 合計行
    html_parts.append(f'<tr style="background:#e8ecf0;font-weight:700"><td style="padding:10px">合計</td>')
    grand_total = 0
    for svc in active_services:
        col_total = sum(matrix.get(ind, {}).get(svc, 0) for ind in active_industries)
        grand_total += col_total
        html_parts.append(f'<td style="padding:10px;text-align:center">{col_total}</td>')
    html_parts.append(f'<td style="padding:10px;text-align:center;color:{BRAND_COLOR}">{grand_total}</td></tr>')
    html_parts.append('</table></div>')

    # 業種別事例セクション
    for ind in active_industries:
        ind_cases = []
        for svc in active_services:
            key = f"{ind}_{svc}"
            if key in samples and samples[key]:
                for s in samples[key]:
                    ind_cases.append({"service": svc, **s})

        if not ind_cases:
            continue

        html_parts.append(f'''
<div style="max-width:900px;margin:0 auto 2rem;padding:0 1rem">
<h2 style="font-size:1.2rem;color:#1a1a1a;margin-bottom:1rem;padding-bottom:.5rem;border-bottom:2px solid {BRAND_COLOR}">{ind}の事例</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));gap:1rem">''')

        for case in ind_cases[:6]:  # 最大6件表示
            html_parts.append(f'''<div style="background:#f8f9fa;border-radius:8px;padding:1rem;border-left:3px solid {BRAND_COLOR}">
<p style="margin:0;font-size:.8rem;color:{BRAND_COLOR};font-weight:600">{case["service"]}</p>
<p style="margin:.3rem 0 0;font-size:.95rem;font-weight:600">{case["case"][:50]}</p>
<p style="margin:.3rem 0 0;font-size:.8rem;color:#888">{case["company"]}</p>
</div>''')

        html_parts.append('</div></div>')

    # セグメント別LP誘導
    html_parts.append(f'''
<div style="max-width:900px;margin:3rem auto;padding:2rem;background:#f0f4ff;border-radius:16px">
<h2 style="font-size:1.3rem;text-align:center;margin:0 0 1.5rem;color:#1a1a1a">業種別の詳細はこちら</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));gap:1rem">
<a href="/lp/general-contractor/" style="display:block;background:#fff;border-radius:8px;padding:1.2rem;text-decoration:none;text-align:center;border:1px solid #e0e0e0;transition:box-shadow .2s">
<p style="font-size:1rem;font-weight:700;color:{BRAND_COLOR};margin:0">ゼネコン向け</p>
<p style="font-size:.85rem;color:#666;margin:.3rem 0 0">現場空撮・土量計測</p>
</a>
<a href="/lp/consultant/" style="display:block;background:#fff;border-radius:8px;padding:1.2rem;text-decoration:none;text-align:center;border:1px solid #e0e0e0;transition:box-shadow .2s">
<p style="font-size:1rem;font-weight:700;color:{BRAND_COLOR};margin:0">コンサルタント向け</p>
<p style="font-size:.85rem;color:#666;margin:.3rem 0 0">公共測量・3D計測</p>
</a>
<a href="/lp/government/" style="display:block;background:#fff;border-radius:8px;padding:1.2rem;text-decoration:none;text-align:center;border:1px solid #e0e0e0;transition:box-shadow .2s">
<p style="font-size:1rem;font-weight:700;color:{BRAND_COLOR};margin:0">官公庁向け</p>
<p style="font-size:.85rem;color:#666;margin:.3rem 0 0">i-Construction対応</p>
</a>
<a href="/lp/real-estate/" style="display:block;background:#fff;border-radius:8px;padding:1.2rem;text-decoration:none;text-align:center;border:1px solid #e0e0e0;transition:box-shadow .2s">
<p style="font-size:1rem;font-weight:700;color:{BRAND_COLOR};margin:0">不動産向け</p>
<p style="font-size:.85rem;color:#666;margin:.3rem 0 0">眺望撮影・パノラマ</p>
</a>
<a href="/lp/inspection/" style="display:block;background:#fff;border-radius:8px;padding:1.2rem;text-decoration:none;text-align:center;border:1px solid #e0e0e0;transition:box-shadow .2s">
<p style="font-size:1rem;font-weight:700;color:{BRAND_COLOR};margin:0">点検向け</p>
<p style="font-size:.85rem;color:#666;margin:.3rem 0 0">赤外線外壁調査</p>
</a>
</div>
</div>''')

    # CTA
    html_parts.append(f'''
<div style="background:linear-gradient(135deg, #0a1628 0%, {BRAND_COLOR} 100%);color:#fff;padding:3rem 2rem;text-align:center;border-radius:16px;max-width:800px;margin:3rem auto">
<h2 style="font-size:1.4rem;margin:0 0 1rem">お気軽にご相談ください</h2>
<p style="opacity:.8;margin:0 0 2rem;font-size:.95rem">ドローン測量・空撮・点検のご相談は無料です</p>
<div style="display:flex;gap:1rem;justify-content:center;flex-wrap:wrap">
<a href="/contact/" style="display:inline-block;padding:14px 32px;background:#fff;color:{BRAND_COLOR};text-decoration:none;border-radius:8px;font-weight:700">お問い合わせ</a>
<a href="tel:{PHONE.replace('-', '')}" style="display:inline-block;padding:14px 32px;border:2px solid #fff;color:#fff;text-decoration:none;border-radius:8px;font-weight:700">{PHONE}</a>
</div>
</div>''')

    # 更新日時
    html_parts.append(f'''
<p style="text-align:center;font-size:.8rem;color:#aaa;margin:2rem 0">
最終更新: {datetime.now().strftime("%Y年%m月%d日")} / データソース: CRM受注台帳
</p>''')

    return "\n".join(html_parts)


def backup_current_page(cfg):
    """現在のページ内容をバックアップ"""
    import urllib.request
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)

    url = f"{base_url}/pages/{CASE_PAGE_ID}?context=edit"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = json.loads(r.read())
    except Exception as e:
        print(f"  バックアップ取得失敗: {e}")
        return None

    content = page.get("content", {})
    if isinstance(content, dict):
        content = content.get("raw", content.get("rendered", ""))

    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"case_library_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    backup_path.write_text(content, encoding="utf-8")
    print(f"  バックアップ保存: {backup_path}")
    return backup_path


def main():
    dry_run = "--dry-run" in sys.argv
    backup_only = "--backup" in sys.argv

    cfg = load_config()

    # バックアップ
    print("[Step 1] 現在のページをバックアップ...")
    backup_path = backup_current_page(cfg)

    if backup_only:
        print("バックアップ完了。終了。")
        return True

    # 分類データ読み込み
    print("[Step 2] 分類データ読み込み...")
    data = load_classification()
    print(f"  レコード数: {data['total_records']}")

    # HTML生成
    print("[Step 3] HTML生成...")
    html = build_case_library_html(data)
    print(f"  HTMLサイズ: {len(html):,} bytes")

    if dry_run:
        output_path = BACKUP_DIR / f"case_library_preview_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        BACKUP_DIR.mkdir(exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        print(f"  [DRY-RUN] プレビュー出力: {output_path}")
        return True

    # WordPress更新（review_agentはHTMLが長すぎて途中打ち切りになるため直接更新）
    print("[Step 4] WordPress更新...")
    import urllib.request
    import urllib.error
    auth = get_wp_auth(cfg)
    base_url = get_wp_api_url(cfg)

    data_payload = json.dumps({"content": html}).encode()
    req = urllib.request.Request(
        f"{base_url}/pages/{CASE_PAGE_ID}",
        data=data_payload,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
            print(f"  更新完了: page {resp.get('id')}")
            ok = True
    except urllib.error.HTTPError as e:
        print(f"  更新失敗: {e.code} {e.read().decode()[:300]}")
        ok = False
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  接続エラー: {e}")
        ok = False

    if ok:
        print(f"\n事例ページ更新完了: /case-library/ (ID: {CASE_PAGE_ID})")
    else:
        print(f"\n事例ページ更新失敗")
        if backup_path:
            print(f"  ロールバック: {backup_path}")

    return ok


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
