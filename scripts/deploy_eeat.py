#!/usr/bin/env python3
"""
E-E-A-T強化デプロイスクリプト
1. 用語集ページ作成（WP REST API）
2. トップページに構造化データ追加
3. テンプレートにBreadcrumbList追加 → 全ページ再デプロイ
"""
import json, sys, os, base64, urllib.request, urllib.parse, urllib.error
from pathlib import Path

CONFIG_PATH = "/mnt/c/Users/USER/Documents/_data/automation_config.json"
TOP_PAGE_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/templates/top_page_final.html"
TEMPLATE_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/templates/page_template.html"
PAGES_DIR = "/mnt/c/Users/USER/Documents/_data/tas-automation/templates/pages"

with open(CONFIG_PATH) as f:
    config = json.load(f)

wp = config["wordpress"]
BASE_URL = wp["base_url"]
CREDS = base64.b64encode(f"{wp['user']}:{wp['app_password']}".encode()).decode()

# All subpages with their WP page IDs and content files
SUBPAGES = [
    {"slug": "company",              "page_id": 16,   "file": "company.html"},
    {"slug": "contact",              "page_id": 19,   "file": "contact.html"},
    {"slug": "recruit",              "page_id": 4537, "file": "recruit.html"},
    {"slug": "services",             "page_id": 4837, "file": "services.html"},
    {"slug": "uav-survey",           "page_id": 4831, "file": "uav-survey.html"},
    {"slug": "infrared-inspection",  "page_id": 4834, "file": "infrared-inspection.html"},
    {"slug": "3d-measurement",       "page_id": 4843, "file": "3d-measurement.html"},
    {"slug": "faq",                  "page_id": 4850, "file": "faq.html"},
    {"slug": "case-library",         "page_id": 5098, "file": "case-library.html"},
    {"slug": "column",               "page_id": 4895, "file": "column.html"},
]

def wp_request(url, data=None, method="GET"):
    """Make WP REST API request."""
    if data:
        encoded = urllib.parse.urlencode(data).encode()
    else:
        encoded = None
    req = urllib.request.Request(url, data=encoded, method=method if not data else "POST")
    req.add_header("Authorization", f"Basic {CREDS}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("User-Agent", "TAS-Automation/1.0")
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"  HTTP {e.code}: {body}")
        raise


def wp_update_page(page_id, content):
    """Update existing WP page content."""
    url = f"{BASE_URL}/pages/{page_id}"
    data = {"content": content}
    return wp_request(url, data)


# ══════════════════════════════════════════════
# 1. 用語集ページ作成
# ══════════════════════════════════════════════
def build_glossary_html():
    """Build glossary page HTML content with structured data."""
    terms = [
        {"id": "bim-cim", "term": "BIM/CIM", "yomi": "ビム・シム", "en": "Building/Construction Information Modeling/Management",
         "desc": "建築・土木分野における3次元モデルを活用した情報管理手法。設計から施工、維持管理まで一貫したデータ活用を実現します。国土交通省が推進するi-Constructionの中核技術です。",
         "link": "/services/3d-measurement/", "link_text": "3次元モデル作成"},
        {"id": "dsm", "term": "DSM", "yomi": "ディーエスエム", "en": "Digital Surface Model（数値表層モデル）",
         "desc": "地表面の建物・樹木などを含む表面の標高データモデル。ドローン測量やレーザー測量で取得した点群データから生成されます。地形の全体像把握や景観シミュレーションに活用されます。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量"},
        {"id": "dtm", "term": "DTM", "yomi": "ディーティーエム", "en": "Digital Terrain Model（数値地形モデル）",
         "desc": "建物や樹木を除去した地表面（裸地面）の標高データモデル。DSMからフィルタリング処理を行って生成されます。土量計算や造成設計の基礎データとして不可欠です。",
         "link": "/tools/earthwork/", "link_text": "土量計算ツール"},
        {"id": "drone-survey", "term": "ドローン測量", "yomi": "ドローンそくりょう", "en": "Drone Survey / UAV Survey",
         "desc": "無人航空機（ドローン）を用いた測量技術。広範囲を短時間で高精度に計測でき、従来のトータルステーション測量と比較して作業時間を大幅に短縮します。i-Construction対応の出来形管理に広く活用されています。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "photogrammetry", "term": "フォトグラメトリ", "yomi": "フォトグラメトリ", "en": "Photogrammetry",
         "desc": "複数の写真から3次元形状を復元する技術。ドローンで撮影した空中写真や地上写真から点群データ・3Dモデルを生成します。SfM技術の実用的応用として建設測量で広く使われています。",
         "link": "/services/3d-measurement/", "link_text": "3次元計測サービス"},
        {"id": "gcp", "term": "GCP", "yomi": "ジーシーピー", "en": "Ground Control Point（対空標識・地上基準点）",
         "desc": "ドローン測量において位置精度を確保するために地上に設置する基準点。GNSSで正確な座標を取得し、SfM処理時の幾何補正に使用します。通常、撮影範囲に対して5点以上を配置します。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "gnss", "term": "GNSS", "yomi": "ジーエヌエスエス", "en": "Global Navigation Satellite System（全球測位衛星システム）",
         "desc": "GPS（米国）、GLONASS（ロシア）、Galileo（EU）、みちびき（日本）など複数の衛星測位システムの総称。RTKやPPK方式と組み合わせることで、センチメートル級の高精度測位を実現します。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "i-construction", "term": "i-Construction", "yomi": "アイ・コンストラクション", "en": "i-Construction",
         "desc": "国土交通省が推進する建設現場のICT活用・生産性向上施策。3次元データの活用、ICT建機の導入、検査の省力化を3本柱とします。2016年度より本格運用が開始され、公共工事での導入が進んでいます。",
         "link": "/services/uav-survey/", "link_text": "i-Construction対応測量"},
        {"id": "ifc", "term": "IFC", "yomi": "アイエフシー", "en": "Industry Foundation Classes",
         "desc": "建築・建設分野のBIMデータ交換のための国際標準フォーマット（ISO 16739）。異なるBIMソフトウェア間でのデータ互換性を確保するオープンな規格です。3次元モデルの属性情報も含めて交換できます。",
         "link": "/services/3d-measurement/", "link_text": "3次元モデル作成"},
        {"id": "infrared-survey", "term": "赤外線調査（サーモグラフィ）", "yomi": "せきがいせんちょうさ", "en": "Infrared Thermography Inspection",
         "desc": "赤外線カメラで対象物の表面温度分布を可視化する非破壊検査技術。外壁タイルの浮き・剥離、コンクリートの内部欠陥、防水層の劣化などを効率的に検出します。建築基準法12条に基づく定期報告にも活用されます。",
         "link": "/services/infrared-inspection/", "link_text": "赤外線調査サービス"},
        {"id": "inspection-12", "term": "12条点検", "yomi": "じゅうにじょうてんけん", "en": "Article 12 Building Inspection",
         "desc": "建築基準法第12条に基づく特定建築物等の定期調査報告制度。外壁タイル等の劣化診断では、従来の打診調査に代わりドローンによる赤外線調査が認められており、安全性・効率性が大幅に向上します。",
         "link": "/services/infrared-inspection/", "link_text": "赤外線調査サービス"},
        {"id": "dekigata", "term": "出来形管理", "yomi": "できがたかんり", "en": "As-built Management",
         "desc": "施工した構造物が設計図書通りに完成しているかを管理する品質管理手法。3次元データを活用した面的な出来形管理では、従来の断面管理と比較してより詳細な品質確認が可能です。",
         "link": "/services/uav-survey/", "link_text": "出来形管理用測量"},
        {"id": "earthwork", "term": "土量計算", "yomi": "どりょうけいさん", "en": "Earthwork Volume Calculation",
         "desc": "切土・盛土の体積を算出する計算。3次元点群データを用いることで、面的な計測が可能となり、従来の断面法と比較して高精度な数量算出を実現します。造成工事や残土処理の計画に不可欠です。",
         "link": "/tools/earthwork/", "link_text": "土量計算ツール"},
        {"id": "kirimori", "term": "切盛土量", "yomi": "きりもりどりょう", "en": "Cut and Fill Volume",
         "desc": "地形の切土（掘削）量と盛土（盛り上げ）量のこと。設計面と現況面の差分から算出し、土工事の施工計画・残土処理計画の基礎となります。3次元データを用いた面的比較により高精度な算出が可能です。",
         "link": "/tools/earthwork/", "link_text": "土量計算ツール"},
        {"id": "landxml", "term": "LandXML", "yomi": "ランドエックスエムエル", "en": "LandXML",
         "desc": "土木・測量分野の3次元設計データ交換用XMLフォーマット。i-Constructionにおける3次元設計データの標準交換形式として採用されています。TIN（三角網）や線形データの記述に対応しています。",
         "link": "/services/3d-measurement/", "link_text": "3次元モデル作成"},
        {"id": "laser-survey", "term": "レーザー測量（LiDAR）", "yomi": "レーザーそくりょう", "en": "LiDAR Survey（Light Detection and Ranging）",
         "desc": "レーザー光を照射し、反射光の到達時間から対象物までの距離を計測する技術。地上型・航空型・ドローン搭載型があり、樹木下の地形も計測可能です。高密度な点群データの取得に優れています。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "norimensurvey", "term": "法面測量", "yomi": "のりめんそくりょう", "en": "Slope Survey",
         "desc": "法面（のり面）の形状・勾配・変位を計測する測量。切土・盛土の斜面管理や災害復旧に不可欠です。ドローン測量により、人が立ち入りにくい急斜面でも安全かつ効率的に面的計測が行えます。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "ortho", "term": "オルソ画像", "yomi": "オルソがぞう", "en": "Orthophoto / Orthoimage",
         "desc": "航空写真やドローン写真の歪みを除去し、地図と同じ正射投影に変換した画像。位置精度が高く、GIS上に重ねて面積計測や現況把握に利用できます。施工前後の比較記録としても重要です。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "pdop", "term": "PDOP", "yomi": "ピーディーオーピー", "en": "Position Dilution of Precision（位置精度低下率）",
         "desc": "GNSS測位における衛星配置に起因する精度低下の指標。値が小さいほど衛星の配置が良好で高精度な測位が可能です。一般にPDOP 3以下が理想的とされ、ドローン測量の飛行計画時に確認する重要な指標です。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "pointcloud", "term": "点群データ（3次元点群）", "yomi": "てんぐんデータ", "en": "Point Cloud Data",
         "desc": "3次元空間上の座標値（X, Y, Z）と属性情報（色、反射強度等）を持つ大量の点の集合。ドローン測量やレーザー測量で取得され、地形モデル・土量計算・出来形管理の基礎データとなります。",
         "link": "/services/3d-measurement/", "link_text": "3次元計測サービス"},
        {"id": "ppk", "term": "PPK", "yomi": "ピーピーケー", "en": "Post-Processing Kinematic（後処理キネマティック測位）",
         "desc": "飛行後にGNSS観測データを後処理して高精度な位置を算出する測位方式。RTKと同等の精度をリアルタイム通信なしで実現できます。通信環境が悪い山間部でも安定した精度を確保できる利点があります。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "public-survey", "term": "公共測量", "yomi": "こうきょうそくりょう", "en": "Public Survey",
         "desc": "測量法に基づき、国・地方公共団体等が実施または費用負担する測量。作業規程の準則に従って実施する必要があり、成果は国土地理院に提出されます。登録測量業者のみが実施可能です。",
         "link": "/company/", "link_text": "資格・認定情報"},
        {"id": "rtk", "term": "RTK", "yomi": "アールティーケー", "en": "Real Time Kinematic（リアルタイムキネマティック測位）",
         "desc": "基準局からの補正データをリアルタイムに受信し、センチメートル級の測位精度を実現する技術。ドローンに搭載することでGCP（対空標識）の設置数を削減でき、測量作業の大幅な効率化が可能です。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "sagyokitei", "term": "作業規程の準則", "yomi": "さぎょうきていのじゅんそく", "en": "Standards for Public Survey Operations",
         "desc": "公共測量の作業方法・精度基準を定めた国土交通省の技術基準。UAV測量についても規定があり、写真測量やレーザー測量の要求精度・作業手順が詳細に定められています。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "seido-kanri", "term": "精度管理表", "yomi": "せいどかんりひょう", "en": "Accuracy Control Sheet",
         "desc": "測量成果の精度を体系的に記録・管理するための帳票。GCPの座標値、検証点の残差、点群データの点密度など、品質を定量的に示します。i-Construction対応工事では電子納品の必須書類です。",
         "link": "/services/uav-survey/", "link_text": "高精度測量サービス"},
        {"id": "sfm", "term": "SfM", "yomi": "エスエフエム", "en": "Structure from Motion",
         "desc": "複数のカメラ位置から撮影された画像群から、カメラの位置姿勢と3次元形状を同時に推定する技術。ドローン測量における点群生成の基盤技術であり、専用ソフトウェア（Metashape等）で処理されます。",
         "link": "/services/3d-measurement/", "link_text": "3次元計測サービス"},
        {"id": "tin", "term": "TIN", "yomi": "ティン", "en": "Triangulated Irregular Network（不整三角網）",
         "desc": "不規則に分布する点群データを三角形のネットワークで結び、連続的な地表面モデルを構築するデータ構造。地形の凹凸を効率的に表現でき、土量計算やLandXMLデータの基盤として使用されます。",
         "link": "/tools/earthwork/", "link_text": "土量計算ツール"},
        {"id": "cross-section", "term": "縦横断測量", "yomi": "じゅうおうだんそくりょう", "en": "Longitudinal and Cross-Section Survey",
         "desc": "道路・河川等の路線に沿った縦断面と、路線に直交する横断面の地形データを取得する測量。土工事の数量算出や施工計画の基礎となります。3次元点群データからの自動生成により、作業効率が飛躍的に向上しています。",
         "link": "/services/uav-survey/", "link_text": "ドローン測量サービス"},
        {"id": "uav-survey", "term": "UAV測量", "yomi": "ユーエーブイそくりょう", "en": "UAV Survey（Unmanned Aerial Vehicle Survey）",
         "desc": "無人航空機（UAV）を使用した測量の正式名称。国土交通省のi-Construction要領では「UAVを用いた公共測量」として技術基準が定められています。ドローン測量と同義で使われます。",
         "link": "/services/uav-survey/", "link_text": "UAV測量サービス"},
        {"id": "voxel", "term": "ボクセル", "yomi": "ボクセル", "en": "Voxel（Volume Pixel / Volumetric Pixel）",
         "desc": "3次元空間を立方体のグリッドで分割したデータ構造。点群データの効率的な管理・可視化に使用されます。大規模な点群を扱う際の間引き処理（ボクセルダウンサンプリング）にも活用されます。",
         "link": "/services/3d-measurement/", "link_text": "3次元計測サービス"},
    ]

    # Sort: alphabetical (A-Z) then Japanese (あ-ん)
    alpha_terms = [t for t in terms if t["term"][0].isascii()]
    jp_terms = [t for t in terms if not t["term"][0].isascii()]
    alpha_terms.sort(key=lambda t: t["term"].upper())
    jp_terms.sort(key=lambda t: t["yomi"])
    sorted_terms = alpha_terms + jp_terms

    # Build index
    alpha_index = sorted(set(t["term"][0].upper() for t in alpha_terms))
    jp_yomi_groups = {"あ": [], "か": [], "さ": [], "た": [], "な": [], "は": [], "ま": [], "や": [], "ら": [], "わ": []}
    yomi_map = {"あ": "あ", "い": "あ", "う": "あ", "え": "あ", "お": "あ",
                "か": "か", "き": "か", "く": "か", "け": "か", "こ": "か",
                "さ": "さ", "し": "さ", "す": "さ", "せ": "さ", "そ": "さ",
                "た": "た", "ち": "た", "つ": "た", "て": "た", "と": "た",
                "な": "な", "に": "な", "ぬ": "な", "ね": "な", "の": "な",
                "は": "は", "ひ": "は", "ふ": "は", "へ": "は", "ほ": "は",
                "ま": "ま", "み": "ま", "む": "ま", "め": "ま", "も": "ま",
                "や": "や", "ゆ": "や", "よ": "や",
                "ら": "ら", "り": "ら", "る": "ら", "れ": "ら", "ろ": "ら",
                "わ": "わ", "を": "わ", "ん": "わ"}

    for t in jp_terms:
        first_char = t["yomi"][0]
        # Convert katakana to hiragana
        if '\u30A0' <= first_char <= '\u30FF':
            first_char = chr(ord(first_char) - 0x60)
        group = yomi_map.get(first_char, "あ")
        jp_yomi_groups[group].append(t)

    jp_index_used = [k for k in jp_yomi_groups if jp_yomi_groups[k]]

    # Build structured data
    defined_terms_json = []
    for t in sorted_terms:
        defined_terms_json.append({
            "@type": "DefinedTerm",
            "name": t["term"],
            "description": t["desc"],
            "inDefinedTermSet": {"@id": "https://tokaiair.com/glossary/#termset"}
        })

    schema = {
        "@context": "https://schema.org",
        "@type": "DefinedTermSet",
        "@id": "https://tokaiair.com/glossary/#termset",
        "name": "建設測量・ドローン用語集",
        "description": "ドローン測量・3次元計測・i-Constructionに関する専門用語を解説。東海エアサービスの技術者が実務経験に基づいて説明します。",
        "hasDefinedTerm": defined_terms_json
    }

    schema_json = json.dumps(schema, ensure_ascii=False)

    # Build term cards HTML
    term_cards = []
    for t in sorted_terms:
        term_cards.append(f'''<div class="glossary-term" id="{t['id']}">
  <div class="glossary-term-header">
    <h3>{t['term']}</h3>
    <div class="glossary-meta">
      <span class="glossary-yomi">{t['yomi']}</span>
      <span class="glossary-en">{t['en']}</span>
    </div>
  </div>
  <p class="glossary-desc">{t['desc']}</p>
  <a href="https://tokaiair.com{t['link']}" class="glossary-link">{t['link_text']}について詳しく見る &rarr;</a>
</div>''')

    # Build index links
    alpha_links = ' '.join(f'<a href="#idx-{c}">{c}</a>' for c in alpha_index)
    jp_links = ' '.join(f'<a href="#idx-{k}">{k}行</a>' for k in jp_index_used)

    # Build grouped sections
    # Alpha section
    alpha_sections = []
    current_letter = None
    for t in alpha_terms:
        letter = t["term"][0].upper()
        if letter != current_letter:
            if current_letter:
                alpha_sections.append('</div>')
            alpha_sections.append(f'<div class="glossary-group" id="idx-{letter}"><h2 class="glossary-group-title">{letter}</h2>')
            current_letter = letter
        alpha_sections.append(f'''<div class="glossary-term" id="{t['id']}">
  <div class="glossary-term-header">
    <h3>{t['term']}</h3>
    <div class="glossary-meta">
      <span class="glossary-yomi">{t['yomi']}</span>
      <span class="glossary-en">{t['en']}</span>
    </div>
  </div>
  <p class="glossary-desc">{t['desc']}</p>
  <a href="https://tokaiair.com{t['link']}" class="glossary-link">{t['link_text']}について詳しく見る &rarr;</a>
</div>''')
    if current_letter:
        alpha_sections.append('</div>')

    # JP section
    jp_sections = []
    for group_name in jp_index_used:
        group_terms = jp_yomi_groups[group_name]
        jp_sections.append(f'<div class="glossary-group" id="idx-{group_name}"><h2 class="glossary-group-title">{group_name}行</h2>')
        for t in group_terms:
            jp_sections.append(f'''<div class="glossary-term" id="{t['id']}">
  <div class="glossary-term-header">
    <h3>{t['term']}</h3>
    <div class="glossary-meta">
      <span class="glossary-yomi">{t['yomi']}</span>
      <span class="glossary-en">{t['en']}</span>
    </div>
  </div>
  <p class="glossary-desc">{t['desc']}</p>
  <a href="https://tokaiair.com{t['link']}" class="glossary-link">{t['link_text']}について詳しく見る &rarr;</a>
</div>''')
        jp_sections.append('</div>')

    html = f'''<script type="application/ld+json">{schema_json}</script>

<div class="page-hero">
  <h1>建設測量・ドローン用語集</h1>
  <p>ドローン測量・3次元計測・i-Constructionに関する専門用語を、実務経験に基づいてわかりやすく解説します。</p>
</div>

<section class="page-content">
  <div class="container">

    <div class="glossary-index">
      <div class="glossary-index-label">索引</div>
      <div class="glossary-index-row">
        <span class="glossary-index-section">アルファベット:</span>
        {alpha_links}
      </div>
      <div class="glossary-index-row">
        <span class="glossary-index-section">五十音:</span>
        {jp_links}
      </div>
    </div>

    {''.join(alpha_sections)}
    {''.join(jp_sections)}

    <div class="cta-banner">
      <h2>測量のお悩み、専門家に相談しませんか？</h2>
      <p>ドローン測量・3次元計測について、お気軽にお問い合わせください。</p>
      <a href="https://tokaiair.com/contact/" class="btn-primary">無料相談はこちら &rarr;</a>
    </div>
  </div>
</section>

<style>
.glossary-index {{
  background: var(--gray-bg);
  border-radius: 12px;
  padding: 24px 28px;
  margin-bottom: 48px;
  border: 1px solid var(--gray-light);
}}
.glossary-index-label {{
  font-size: 14px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 12px;
}}
.glossary-index-row {{
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}}
.glossary-index-row:last-child {{ margin-bottom: 0; }}
.glossary-index-section {{
  font-size: 12px;
  font-weight: 600;
  color: var(--gray-mid);
  min-width: 100px;
}}
.glossary-index a {{
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--white);
  border: 1px solid var(--gray-light);
  color: var(--brand);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
  transition: background 0.2s, color 0.2s;
}}
.glossary-index a:hover {{
  background: var(--brand);
  color: var(--white);
}}
.glossary-group {{
  margin-bottom: 40px;
}}
.glossary-group-title {{
  font-size: 22px;
  font-weight: 900;
  color: var(--brand);
  padding-bottom: 12px;
  border-bottom: 2px solid var(--brand);
  margin-bottom: 20px;
}}
.glossary-term {{
  background: var(--white);
  border: 1px solid var(--gray-light);
  border-left: 4px solid var(--brand);
  border-radius: 10px;
  padding: 24px 28px;
  margin-bottom: 12px;
  transition: box-shadow 0.25s, transform 0.2s;
}}
.glossary-term:hover {{
  box-shadow: 0 8px 30px rgba(22,71,251,0.08);
  transform: translateY(-2px);
}}
.glossary-term-header {{
  margin-bottom: 12px;
}}
.glossary-term-header h3 {{
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin-bottom: 6px;
}}
.glossary-meta {{
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}}
.glossary-yomi {{
  font-size: 13px;
  color: var(--gray-mid);
}}
.glossary-en {{
  font-size: 13px;
  color: var(--gray-mid);
  font-style: italic;
}}
.glossary-desc {{
  font-size: 15px;
  line-height: 1.8;
  color: var(--text);
  margin-bottom: 12px;
}}
.glossary-link {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--brand);
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}}
.glossary-link:hover {{ text-decoration: underline; }}
@media (max-width: 768px) {{
  .glossary-index-row {{ flex-direction: column; align-items: flex-start; }}
  .glossary-index-section {{ min-width: auto; }}
  .glossary-term {{ padding: 20px; }}
}}
</style>'''

    return html


def create_glossary_page():
    """Create glossary page in WP."""
    print("\n=== 1. 用語集ページ作成 ===")
    content = build_glossary_html()

    # Check if glossary page already exists
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/pages?slug=glossary&status=publish,draft",
            headers={"Authorization": f"Basic {CREDS}", "User-Agent": "TAS-Automation/1.0"}
        )
        resp = urllib.request.urlopen(req)
        existing = json.loads(resp.read())
        if existing:
            page_id = existing[0]["id"]
            print(f"  既存ページ発見 (ID={page_id})。更新します。")
            result = wp_update_page(page_id, content)
            print(f"  更新完了: {result.get('link')}")
            return page_id
    except Exception as e:
        print(f"  既存チェックエラー（新規作成に進みます）: {e}")

    # Create new page
    url = f"{BASE_URL}/pages"
    data = {
        "title": "用語集",
        "slug": "glossary",
        "content": content,
        "status": "publish"
    }
    result = wp_request(url, data)
    page_id = result.get("id")
    link = result.get("link")
    print(f"  作成完了: ID={page_id}, URL={link}")
    return page_id


# ══════════════════════════════════════════════
# 2. トップページ構造化データ強化
# ══════════════════════════════════════════════
def update_top_page_schema():
    """Add ProfessionalService + Person schema to top page."""
    print("\n=== 2. トップページ構造化データ強化 ===")

    with open(TOP_PAGE_PATH, encoding="utf-8") as f:
        html = f.read()

    # Build enhanced schema
    new_schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": "https://tokaiair.com/#organization",
                "name": "東海エアサービス株式会社",
                "url": "https://tokaiair.com/",
                "telephone": "+81-50-7117-7141",
                "email": "info@tokaiair.com",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "植園町1-9-3",
                    "addressLocality": "名古屋市名東区",
                    "addressRegion": "愛知県",
                    "postalCode": "465-0077",
                    "addressCountry": "JP"
                }
            },
            {
                "@type": "ProfessionalService",
                "@id": "https://tokaiair.com/#service",
                "name": "東海エアサービス株式会社",
                "url": "https://tokaiair.com/",
                "telephone": "+81-50-7117-7141",
                "email": "info@tokaiair.com",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": "植園町1-9-3",
                    "addressLocality": "名古屋市名東区",
                    "addressRegion": "愛知県",
                    "postalCode": "465-0077",
                    "addressCountry": "JP"
                },
                "priceRange": "¥150,000〜",
                "areaServed": "JP",
                "knowsAbout": ["ドローン測量", "3次元計測", "赤外線調査", "土量計算", "BIM/CIM"],
                "hasCredential": [
                    "測量業者登録 第(1)-37730号",
                    "全省庁統一資格",
                    "国交省航空局包括飛行許可"
                ]
            },
            {
                "@type": "Person",
                "@id": "https://tokaiair.com/#kunimoto",
                "name": "國本 洋輔",
                "jobTitle": "代表取締役",
                "worksFor": {"@id": "https://tokaiair.com/#organization"},
                "knowsAbout": ["ドローン測量", "建設DX", "3次元計測", "事業承継"]
            }
        ]
    }

    new_schema_str = json.dumps(new_schema, ensure_ascii=False)

    # Replace existing schema in top_page_final.html
    old_schema_tag = '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","@id":"https://tokaiair.com/#organization","name":"東海エアサービス株式会社","url":"https://tokaiair.com/","telephone":"+81-50-7117-7141","email":"info@tokaiair.com","address":{"@type":"PostalAddress","addressLocality":"名古屋市名東区","addressRegion":"愛知県","postalCode":"465-0077","addressCountry":"JP"}}]}</script>'
    new_schema_tag = f'<script type="application/ld+json">{new_schema_str}</script>'

    if old_schema_tag in html:
        html = html.replace(old_schema_tag, new_schema_tag)
        print("  構造化データ置換完了（Organization → Organization + ProfessionalService + Person）")
    else:
        print("  WARNING: 既存のschemaタグが見つかりません。手動確認が必要です。")
        # Try to insert before </head>
        html = html.replace('</head>', f'{new_schema_tag}\n</head>')
        print("  </head>の前に挿入しました。")

    with open(TOP_PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ファイル更新完了: {TOP_PAGE_PATH}")

    # Deploy to WP (page ID 212 = front page)
    print("  WPフロントページにデプロイ中...")
    result = wp_update_page(212, html)
    print(f"  デプロイ完了: {result.get('link')}")
    return True


# ══════════════════════════════════════════════
# 3. テンプレートにBreadcrumbList追加 → 全ページ再デプロイ
# ══════════════════════════════════════════════
def update_template_breadcrumb():
    """Add BreadcrumbList JS to page_template.html."""
    print("\n=== 3. テンプレートBreadcrumbList追加 ===")

    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()

    breadcrumb_js = '''
    // Breadcrumb structured data (dynamic)
    (function(){
      var path = location.pathname;
      var crumbs = [{"@type":"ListItem","position":1,"name":"ホーム","item":"https://tokaiair.com/"}];
      if(path !== '/'){
        var title = document.title.split('｜')[0].trim();
        crumbs.push({"@type":"ListItem","position":2,"name":title,"item":"https://tokaiair.com"+path});
      }
      var bcSchema = {"@context":"https://schema.org","@type":"BreadcrumbList","itemListElement":crumbs};
      var s = document.createElement('script');
      s.type = 'application/ld+json';
      s.textContent = JSON.stringify(bcSchema);
      document.head.appendChild(s);
    })();'''

    # Check if already added
    if 'BreadcrumbList' in template:
        print("  BreadcrumbListは既に追加済みです。スキップします。")
    else:
        # Insert before </script> at end of template
        # Find the last </script> before </body>
        insert_marker = '  </script>\n</body>'
        if insert_marker in template:
            template = template.replace(insert_marker, f'{breadcrumb_js}\n  </script>\n</body>')
            print("  BreadcrumbList JS追加完了")
        else:
            # Try alternate approach
            template = template.replace('</script>\n</body>', f'{breadcrumb_js}\n</script>\n</body>')
            print("  BreadcrumbList JS追加完了（代替パターン）")

        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            f.write(template)
        print(f"  テンプレート更新完了: {TEMPLATE_PATH}")

    # Also update page_template.html schema (same as top page Organization schema)
    old_schema_in_template = '<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization","@id":"https://tokaiair.com/#organization","name":"東海エアサービス株式会社","url":"https://tokaiair.com/","telephone":"+81-50-7117-7141","email":"info@tokaiair.com","address":{"@type":"PostalAddress","addressLocality":"名古屋市名東区","addressRegion":"愛知県","postalCode":"465-0077","addressCountry":"JP"}}]}</script>'

    if old_schema_in_template in template:
        new_org_schema = {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": "https://tokaiair.com/#organization",
                    "name": "東海エアサービス株式会社",
                    "url": "https://tokaiair.com/",
                    "telephone": "+81-50-7117-7141",
                    "email": "info@tokaiair.com",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "植園町1-9-3",
                        "addressLocality": "名古屋市名東区",
                        "addressRegion": "愛知県",
                        "postalCode": "465-0077",
                        "addressCountry": "JP"
                    }
                },
                {
                    "@type": "ProfessionalService",
                    "@id": "https://tokaiair.com/#service",
                    "name": "東海エアサービス株式会社",
                    "url": "https://tokaiair.com/",
                    "telephone": "+81-50-7117-7141",
                    "email": "info@tokaiair.com",
                    "address": {
                        "@type": "PostalAddress",
                        "streetAddress": "植園町1-9-3",
                        "addressLocality": "名古屋市名東区",
                        "addressRegion": "愛知県",
                        "postalCode": "465-0077",
                        "addressCountry": "JP"
                    },
                    "priceRange": "¥150,000〜",
                    "areaServed": "JP",
                    "knowsAbout": ["ドローン測量", "3次元計測", "赤外線調査", "土量計算", "BIM/CIM"],
                    "hasCredential": [
                        "測量業者登録 第(1)-37730号",
                        "全省庁統一資格",
                        "国交省航空局包括飛行許可"
                    ]
                }
            ]
        }
        template = template.replace(old_schema_in_template, f'<script type="application/ld+json">{json.dumps(new_org_schema, ensure_ascii=False)}</script>')
        with open(TEMPLATE_PATH, "w", encoding="utf-8") as f:
            f.write(template)
        print("  テンプレートの構造化データも強化しました")

    # Re-read updated template
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = f.read()

    # Deploy all subpages
    print("\n  全サブページ再デプロイ中...")
    for page in SUBPAGES:
        page_file = os.path.join(PAGES_DIR, page["file"])
        if not os.path.exists(page_file):
            print(f"  SKIP: {page['slug']} (ファイル {page['file']} が見つかりません)")
            continue

        with open(page_file, encoding="utf-8") as f:
            page_content = f.read()

        full_html = template.replace("__PAGE_CONTENT__", page_content)

        try:
            result = wp_update_page(page["page_id"], full_html)
            print(f"  OK: {page['slug']} (ID={page['page_id']}) -> {result.get('link', 'N/A')}")
        except Exception as e:
            print(f"  FAIL: {page['slug']} (ID={page['page_id']}) -> {e}")

    return True


# ══════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════
if __name__ == "__main__":
    print("E-E-A-T強化デプロイ開始")
    print("=" * 60)

    # 1. Glossary page
    glossary_id = create_glossary_page()

    # 2. Top page structured data
    update_top_page_schema()

    # 3. Template breadcrumb + redeploy all
    update_template_breadcrumb()

    print("\n" + "=" * 60)
    print("E-E-A-T強化デプロイ完了")
    print(f"  用語集ページID: {glossary_id}")
    print(f"  用語集URL: https://tokaiair.com/glossary/")
