#!/usr/bin/env python3
"""
コラム記事から専門用語を自動抽出し、用語集ページに追加するスクリプト

Usage:
    python3 glossary_extractor.py --scan        # 記事をスキャンして候補用語を抽出
    python3 glossary_extractor.py --add         # 抽出した用語を用語集に追加
    python3 glossary_extractor.py --dry-run     # プレビューのみ
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
import base64
import argparse
from pathlib import Path
from collections import Counter, defaultdict

SCRIPT_DIR = Path(__file__).parent
CONFIG_PATH = Path("/mnt/c/Users/USER/Documents/_data/automation_config.json")
GLOSSARY_CACHE = SCRIPT_DIR / "data" / "glossary_candidates.json"

# 既知の専門用語パターン（カテゴリ別）
TERM_PATTERNS = {
    "測量技術": [
        r"SfM", r"Structure from Motion", r"フォトグラメトリ", r"写真測量",
        r"RTK", r"PPK", r"GNSS", r"GCP", r"対空標識",
        r"PDOP", r"基線解析", r"後処理キネマティック",
        r"トータルステーション", r"TS", r"水準測量", r"基準点測量",
        r"地理座標系", r"投影座標系", r"ジオイド", r"楕円体高",
    ],
    "点群・3D": [
        r"点群", r"点群データ", r"ポイントクラウド",
        r"LAS", r"LAZ", r"E57",
        r"TIN", r"Triangulated Irregular Network",
        r"DSM", r"DTM", r"DEM", r"数値標高モデル", r"数値地形モデル",
        r"オルソ画像", r"オルソモザイク", r"正射投影",
        r"ボクセル", r"メッシュ", r"テクスチャマッピング",
        r"ノイズ除去", r"フィルタリング", r"間引き処理",
    ],
    "BIM/CIM": [
        r"BIM", r"CIM", r"BIM/CIM", r"IFC", r"LandXML",
        r"3Dモデル", r"LOD", r"属性情報",
        r"Revit", r"Civil ?3D", r"InfraWorks",
    ],
    "土量・施工": [
        r"土量計算", r"切土", r"盛土", r"切盛", r"残土",
        r"出来形", r"出来形管理", r"出来高",
        r"法面", r"のり面", r"横断図", r"縦断図",
        r"土質", r"地山", r"ほぐし率", r"締固め",
        r"転圧", r"CBR", r"含水比",
        r"ダンプ", r"積載量", r"運搬距離",
    ],
    "i-Construction": [
        r"i-Construction", r"ICT施工", r"ICT活用工事",
        r"マシンコントロール", r"マシンガイダンス",
        r"TS出来形", r"3次元設計データ",
        r"精度管理", r"精度管理表",
    ],
    "赤外線・点検": [
        r"赤外線", r"サーモグラフィ", r"熱画像",
        r"外壁調査", r"12条点検", r"打診調査",
        r"クラック", r"ひび割れ", r"浮き", r"剥離",
        r"鉄筋探査", r"かぶり厚",
    ],
    "ドローン": [
        r"UAV", r"無人航空機", r"マルチコプター",
        r"飛行申請", r"包括許可", r"航空法",
        r"DID", r"人口集中地区",
        r"DIPS", r"飛行計画",
        r"ペイロード", r"飛行時間", r"バッテリー",
        r"センサー", r"ジンバル",
    ],
    "データ処理": [
        r"Metashape", r"Pix4D", r"DJI Terra",
        r"CloudCompare", r"QGIS",
        r"GeoTIFF", r"Shapefile", r"KML", r"GeoJSON",
        r"座標変換", r"測地系", r"JGD2011",
    ],
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_wp_auth(cfg):
    user = cfg["wordpress"]["user"]
    pwd = cfg["wordpress"]["app_password"]
    return base64.b64encode((user + ":" + pwd).encode()).decode()


def get_all_posts(cfg):
    """全公開記事を取得"""
    auth = get_wp_auth(cfg)
    base = cfg["wordpress"]["base_url"]
    all_posts = []
    page = 1
    while True:
        url = f"{base}/posts?per_page=50&page={page}&status=publish&_fields=id,slug,title,content"
        req = urllib.request.Request(url, headers={
            "Authorization": "Basic " + auth,
            "User-Agent": "TAS-Automation/1.0"
        })
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            posts = json.loads(resp.read())
            if not posts:
                break
            all_posts.extend(posts)
            page += 1
        except urllib.error.HTTPError:
            break
    return all_posts


def get_existing_glossary(cfg):
    """既存の用語集ページから登録済み用語を取得"""
    auth = get_wp_auth(cfg)
    base = cfg["wordpress"]["base_url"]
    url = f"{base}/pages?slug=glossary&_fields=id,content"
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        pages = json.loads(resp.read())
        if pages:
            content = pages[0].get("content", {}).get("rendered", "")
            # 用語名を抽出（h3タグ内）
            terms = re.findall(r"<h3[^>]*>(.*?)</h3>", content)
            clean = [re.sub(r"<[^>]+>", "", t).strip() for t in terms]
            return clean
    except:
        pass
    return []


def extract_terms_from_content(content):
    """記事本文から専門用語を抽出"""
    # HTMLタグ除去
    text = re.sub(r"<[^>]+>", " ", content)
    text = re.sub(r"\s+", " ", text)

    found = defaultdict(lambda: {"count": 0, "categories": set()})

    for category, patterns in TERM_PATTERNS.items():
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                # 正規化（大文字小文字統一）
                term = matches[0]
                found[term]["count"] += len(matches)
                found[term]["categories"].add(category)

    return found


def generate_definition(term, category):
    """用語の定義を生成（テンプレートベース）"""
    definitions = {
        "SfM": "Structure from Motionの略。複数の写真から3次元モデルを生成する写真測量技術。ドローンで撮影した空撮画像から点群データや3Dモデルを作成する際の基盤技術。",
        "フォトグラメトリ": "写真測量法。複数の写真から対象物の3次元形状を復元する技術。SfM技術の応用として、建設現場の地表面モデル作成に広く用いられる。",
        "対空標識": "航空写真測量において、地上の基準点位置を上空から識別するために設置する標識。GCPと組み合わせて測量精度を向上させる。",
        "基線解析": "GNSS測量において、2つの受信機間の相対位置を高精度に求める解析手法。RTK測量やPPK測量の基礎技術。",
        "E57": "3次元点群データの標準ファイル形式。ASTM規格に基づき、異なるスキャナー間でのデータ交換に使用される。",
        "数値標高モデル": "Digital Elevation Model (DEM)。地表面の標高を格子状に記録した数値データ。DSM（建物含む）とDTM（地表面のみ）の総称。",
        "正射投影": "航空写真の歪みを補正し、真上から見た正確な地図画像を生成する処理。オルソ画像の作成に使用される。",
        "ノイズ除去": "点群データから不要な点（植生、車両、反射ノイズ等）を自動または手動で除去する処理。精度の高い地表面モデル作成に必須。",
        "間引き処理": "大量の点群データから一定の規則で点を削減し、データサイズを最適化する処理。計算速度とデータ品質のバランスを取る。",
        "LOD": "Level of Detailの略。BIM/CIMモデルの詳細度を表す指標。LOD100（概念設計）からLOD500（竣工モデル）まで段階がある。",
        "属性情報": "3DモデルやGISデータに付与される非幾何学的な情報。材質、施工日、管理者等のメタデータ。BIM/CIMの核心的要素。",
        "ほぐし率": "地山の土を掘削した際に体積が増加する割合。土量計算において切土量から運搬量を算出する際に必要な係数。一般的に1.2〜1.3程度。",
        "締固め": "盛土材料を機械的に圧縮し、所定の密度に達するまで転圧する施工作業。品質管理にはCBR試験や現場密度試験を用いる。",
        "転圧": "ローラーやタンパーを用いて地盤や盛土を締め固める作業。適切な含水比で施工することが重要。",
        "CBR": "California Bearing Ratioの略。路床や路盤の支持力を評価する指標。道路設計における舗装厚決定の基礎データ。",
        "含水比": "土中の水分量を乾燥重量に対する百分率で表した値。締固めの最適含水比を把握することで施工品質を管理する。",
        "マシンコントロール": "GNSS位置情報と3次元設計データを連動させ、建設機械の刃先を自動制御する技術。丁張りが不要になり、施工効率が大幅に向上する。",
        "マシンガイダンス": "建設機械のオペレーターに対して、3次元設計データに基づいた施工ガイドをリアルタイムで表示する技術。マシンコントロールの前段階として導入されることが多い。",
        "TS出来形": "トータルステーションを用いた出来形管理。i-Constructionにおける出来形管理要領に基づき、設計値との差異を3次元で管理する。",
        "かぶり厚": "コンクリート表面から鉄筋表面までの距離。建築基準法で最小かぶり厚が規定されており、構造物の耐久性に直結する。",
        "DID": "Densely Inhabited District（人口集中地区）の略。航空法により、DID上空でのドローン飛行には国土交通大臣の許可が必要。",
        "DIPS": "ドローン情報基盤システム。国土交通省が運用する無人航空機の飛行許可・承認申請のオンラインシステム。",
        "ペイロード": "ドローンが搭載できる機器の最大重量。カメラ、LiDAR、赤外線センサー等の搭載可否を決定する重要なスペック。",
        "ジンバル": "カメラの振動を吸収し、安定した映像・画像を撮影するための機械式スタビライザー。3軸ジンバルが一般的。",
        "測地系": "地球上の位置を表現するための座標系の基準。日本ではJGD2011（日本測地系2011）が標準。旧測地系との座標変換が必要な場合がある。",
        "JGD2011": "Japanese Geodetic Datum 2011。2011年の東日本大震災後に改定された日本の測地基準系。GNSSによる測位はこの測地系に基づく。",
        "Shapefile": "GIS（地理情報システム）で広く使用されるベクターデータ形式。点・線・面の空間情報と属性データを格納する。ESRI社が開発。",
        "KML": "Keyhole Markup Language。Google Earthなどで使用される地理空間データの記述形式。XMLベースで、地物の位置・形状・属性を表現する。",
        "GeoJSON": "地理空間データをJSON形式で表現するオープン標準。Webアプリケーションでの地図データ交換に広く用いられる。",
    }

    if term in definitions:
        return definitions[term]

    # カテゴリに基づくテンプレート定義
    templates = {
        "測量技術": f"{term}は、建設測量で使用される技術・手法の一つ。現場の位置情報や形状データの取得に用いられる。",
        "点群・3D": f"{term}は、3次元計測・点群データ処理に関連する技術・形式。ドローン測量や3Dスキャンの成果物の処理・活用に使用される。",
        "BIM/CIM": f"{term}は、BIM/CIM（建設情報モデリング）に関連する技術・規格。建設プロジェクトの3次元情報管理に使用される。",
        "土量・施工": f"{term}は、土工事・施工管理に関連する用語。土量計算や出来形管理において重要な概念。",
        "i-Construction": f"{term}は、国土交通省が推進するi-Construction（ICT施工）に関連する技術・基準。",
        "赤外線・点検": f"{term}は、建築物の点検・調査に関連する技術・手法。非破壊検査として広く活用されている。",
        "ドローン": f"{term}は、ドローン（無人航空機）の運用・規制に関連する用語。",
        "データ処理": f"{term}は、測量データの処理・変換に関連するソフトウェアまたはデータ形式。",
    }

    cat = list(category)[0] if category else "測量技術"
    return templates.get(cat, f"{term}は、建設測量・データ計測に関連する専門用語。")


def scan_articles(cfg):
    """全記事をスキャンして用語候補を抽出"""
    print("記事を取得中...")
    posts = get_all_posts(cfg)
    print(f"  {len(posts)}件取得")

    print("既存用語集を取得中...")
    existing = get_existing_glossary(cfg)
    print(f"  {len(existing)}語登録済み")

    print("用語を抽出中...")
    all_terms = defaultdict(lambda: {"count": 0, "categories": set(), "articles": []})

    for post in posts:
        content = post.get("content", {}).get("rendered", "")
        title = post.get("title", {}).get("rendered", "")
        slug = post.get("slug", "")

        terms = extract_terms_from_content(content)
        for term, info in terms.items():
            all_terms[term]["count"] += info["count"]
            all_terms[term]["categories"].update(info["categories"])
            all_terms[term]["articles"].append(slug)

    # 既存用語を除外
    existing_lower = [e.lower() for e in existing]
    new_terms = {
        t: info for t, info in all_terms.items()
        if t.lower() not in existing_lower and t not in existing
    }

    # 出現回数順にソート
    sorted_terms = sorted(new_terms.items(), key=lambda x: -x[1]["count"])

    print(f"\n新規用語候補: {len(sorted_terms)}語（既存{len(existing)}語を除外）\n")
    for term, info in sorted_terms[:50]:
        cats = ", ".join(info["categories"])
        articles = len(set(info["articles"]))
        print(f"  {info['count']:4d}回 | {articles:2d}記事 | {term:25s} | {cats}")

    # キャッシュに保存
    os.makedirs(SCRIPT_DIR / "data", exist_ok=True)
    cache = {
        t: {
            "count": info["count"],
            "categories": list(info["categories"]),
            "articles": list(set(info["articles"]))[:5],
        }
        for t, info in sorted_terms
    }
    with open(GLOSSARY_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    print(f"\n候補をキャッシュに保存: {GLOSSARY_CACHE}")

    return sorted_terms


def add_terms_to_glossary(cfg, dry_run=False):
    """抽出した用語を用語集ページに追加"""
    if not GLOSSARY_CACHE.exists():
        print("キャッシュがありません。先に --scan を実行してください。")
        return

    with open(GLOSSARY_CACHE, "r", encoding="utf-8") as f:
        candidates = json.load(f)

    # 2記事以上に出現する用語のみ追加
    terms_to_add = {
        t: info for t, info in candidates.items()
        if len(info.get("articles", [])) >= 2 or info.get("count", 0) >= 5
    }

    print(f"追加候補: {len(terms_to_add)}語")

    if not terms_to_add:
        print("追加する用語がありません。")
        return

    # 用語のHTML生成
    html_parts = []
    schema_terms = []

    for term, info in sorted(terms_to_add.items()):
        categories = set(info.get("categories", []))
        definition = generate_definition(term, categories)
        cat_label = ", ".join(categories) if categories else "一般"
        term_id = re.sub(r"[^a-zA-Z0-9]", "-", term.lower()).strip("-")

        html_parts.append(f"""
<div id="{term_id}" style="padding:16px 0;border-bottom:1px solid var(--gray-light,#e2e8f0);">
  <h3 style="font-size:16px;font-weight:700;color:#1e293b;margin-bottom:4px;">{term}</h3>
  <p style="font-size:11px;color:#64748b;margin-bottom:8px;">{cat_label}</p>
  <p style="font-size:14px;color:#475569;line-height:1.75;">{definition}</p>
</div>""")

        schema_terms.append({
            "@type": "DefinedTerm",
            "name": term,
            "description": definition,
        })

    new_html = "\n".join(html_parts)

    if dry_run:
        print(f"\n=== プレビュー（{len(terms_to_add)}語）===")
        for term in sorted(terms_to_add.keys()):
            print(f"  + {term}")
        print(f"\nHTML: {len(new_html):,} chars")
        return

    # 既存の用語集ページに追記
    auth = get_wp_auth(cfg)
    base = cfg["wordpress"]["base_url"]

    url = f"{base}/pages?slug=glossary&_fields=id,content"
    req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
    resp = urllib.request.urlopen(req)
    pages = json.loads(resp.read())

    if not pages:
        print("用語集ページが見つかりません。")
        return

    page_id = pages[0]["id"]
    current_content = pages[0].get("content", {}).get("rendered", "")

    # CTAバナーの前に用語を追加
    cta_marker = "<!-- CTA -->"
    if cta_marker in current_content:
        updated = current_content.replace(cta_marker, new_html + "\n" + cta_marker)
    else:
        updated = current_content + new_html

    # 更新
    data = urllib.parse.urlencode({"content": updated}).encode("utf-8")
    req2 = urllib.request.Request(
        f"{base}/pages/{page_id}",
        data=data, method="POST",
        headers={
            "Authorization": "Basic " + auth,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TAS-Automation/1.0",
        })
    resp2 = urllib.request.urlopen(req2, timeout=60)
    print(f"OK: {len(terms_to_add)}語を用語集に追加（page {page_id}）")


def main():
    parser = argparse.ArgumentParser(description="コラム記事から専門用語を自動抽出")
    parser.add_argument("--scan", action="store_true", help="記事をスキャンして候補を抽出")
    parser.add_argument("--add", action="store_true", help="候補を用語集に追加")
    parser.add_argument("--dry-run", action="store_true", help="プレビューのみ")

    args = parser.parse_args()
    cfg = load_config()

    if args.scan:
        scan_articles(cfg)
    elif args.add:
        add_terms_to_glossary(cfg, dry_run=args.dry_run)
    elif args.dry_run:
        scan_articles(cfg)
        add_terms_to_glossary(cfg, dry_run=True)
    else:
        scan_articles(cfg)


if __name__ == "__main__":
    main()
