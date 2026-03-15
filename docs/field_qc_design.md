# 撮影データ品質チェックスクリプト 設計書

## 概要

撮影直後に現場でCLI一発実行し、データ品質を合否判定するスクリプト。
再撮影・再計測の要否をその場で判断し、手戻りコストを排除する。

```
python field_qc.py /path/to/flight_data/ [--design design.csv] [--plan plan.geojson]
```

---

## 1. 入力データ構成

```
flight_data/
  images/          # ドローン撮影画像（JPEG/TIFF）
  gcp/             # GCP計測値（CSV: point_id, x, y, z）
  design.csv       # 設計座標値（CSV: point_id, x, y, z）  ※任意
  plan.geojson     # 撮影計画エリア（GeoJSON polygon）      ※任意
```

---

## 2. チェック項目・判定基準・出力

### 2.1 GPS整合性確認

| 項目 | 内容 |
|------|------|
| 処理 | 全画像のEXIF GPSタグを抽出。緯度・経度・高度を取得 |
| 異常検出 | (1) GPS未記録の画像 (2) 外れ値（中央値から3σ超） (3) 高度の急変（前後画像比で±50m超） |
| 判定 | GPS欠損0件 かつ 外れ値0件 → PASS |
| ライブラリ | `exifread` |

**抽出ロジック:**
```python
def extract_gps(image_path):
    """EXIF GPSInfo → (lat, lon, alt)。未記録ならNone返却"""
    tags = exifread.process_file(open(image_path, 'rb'), details=False)
    if 'GPS GPSLatitude' not in tags:
        return None
    lat = dms_to_decimal(tags['GPS GPSLatitude'], tags['GPS GPSLatitudeRef'])
    lon = dms_to_decimal(tags['GPS GPSLongitude'], tags['GPS GPSLongitudeRef'])
    alt = float(tags.get('GPS GPSAltitude', Fraction(0)))
    return (lat, lon, alt)
```

**外れ値検出:**
- 全座標の中央値・標準偏差を算出
- |座標 - 中央値| > 3σ の画像をフラグ
- 高度: ソート済み連続画像間で±50m以上の急変を検出

### 2.2 オーバーラップ率確認

| 項目 | 内容 |
|------|------|
| 処理 | GPS座標＋画角（EXIF FocalLength, SensorWidth）＋高度から地上投影範囲を算出。隣接画像の重複面積を計算 |
| 判定基準 | 進行方向（OL）≥ 80%、横方向（SL）≥ 60% → PASS |
| 補足 | 画角不明時はDJI標準値（Phantom4RTK: 84°）をデフォルト使用 |

**算出ロジック:**
```python
def calc_ground_footprint(lat, lon, alt_agl, focal_mm, sensor_w_mm, sensor_h_mm, img_w, img_h):
    """地上投影サイズ（m）を返す"""
    gsd_w = (alt_agl * sensor_w_mm) / (focal_mm * img_w)  # m/px
    gsd_h = (alt_agl * sensor_h_mm) / (focal_mm * img_h)
    footprint_w = gsd_w * img_w  # m
    footprint_h = gsd_h * img_h
    return footprint_w, footprint_h

def calc_overlap(img1, img2):
    """2枚の画像間オーバーラップ率（%）"""
    dist = haversine(img1.lat, img1.lon, img2.lat, img2.lon)
    # 進行方向の重なり
    overlap = max(0, img1.footprint_h - dist) / img1.footprint_h * 100
    return overlap
```

**隣接画像の特定:**
- 撮影タイムスタンプ順にソート
- 同一ストリップ内で連続する画像ペアを抽出
- ストリップ間（横方向）は最近傍画像をペアリング

### 2.3 GCP座標と設計値の突合

| 項目 | 内容 |
|------|------|
| 処理 | GCP計測CSVと設計CSV（point_id照合）の座標差分を算出 |
| 判定基準 | 水平誤差 ≤ 50mm、垂直誤差 ≤ 50mm → PASS |
| 補足 | 設計CSVが未指定の場合はスキップ（WARNINGのみ） |

```python
def check_gcp_accuracy(measured_csv, design_csv):
    """GCP精度チェック。point_idで突合し差分算出"""
    results = []
    for pid in measured:
        dh = sqrt((m.x - d.x)**2 + (m.y - d.y)**2)  # 水平誤差
        dv = abs(m.z - d.z)                            # 垂直誤差
        results.append({
            'point_id': pid,
            'dh_mm': dh * 1000,
            'dv_mm': dv * 1000,
            'pass': dh * 1000 <= 50 and dv * 1000 <= 50
        })
    return results
```

### 2.4 画像品質チェック

| 項目 | 判定基準 | 手法 |
|------|---------|------|
| ブレ検出 | Laplacian分散 < 100 → NG | `cv2.Laplacian(gray, cv2.CV_64F).var()` |
| 白飛び | 輝度255のピクセル > 5% → NG | ヒストグラム上位ビン比率 |
| 暗すぎ | 平均輝度 < 40 → NG | `np.mean(gray)` |
| 霧・もや | コントラスト（std） < 30 → WARNING | `np.std(gray)` |

```python
def check_image_quality(image_path):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ブレ検出
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    is_blurry = blur_score < 100

    # 白飛び
    overexposed_ratio = np.sum(gray >= 250) / gray.size
    is_overexposed = overexposed_ratio > 0.05

    # 暗すぎ
    mean_brightness = np.mean(gray)
    is_dark = mean_brightness < 40

    # 低コントラスト（霧）
    contrast = np.std(gray)
    is_hazy = contrast < 30

    return {
        'blur_score': blur_score,
        'is_blurry': is_blurry,
        'overexposed_ratio': overexposed_ratio,
        'is_overexposed': is_overexposed,
        'mean_brightness': mean_brightness,
        'is_dark': is_dark,
        'contrast': contrast,
        'is_hazy': is_hazy,
        'pass': not (is_blurry or is_overexposed or is_dark)
    }
```

### 2.5 撮影漏れチェック（カバレッジ確認）

| 項目 | 内容 |
|------|------|
| 処理 | 計画エリア（GeoJSON）を10mグリッドに分割。各グリッドが1枚以上の画像投影範囲に含まれるか判定 |
| 判定基準 | カバレッジ率 ≥ 95% → PASS |
| 補足 | plan.geojson未指定時はスキップ。GPS座標のConvex Hullのみ出力 |

```python
def check_coverage(images, plan_geojson, grid_size=10):
    """計画エリアのカバレッジ率を算出"""
    plan_poly = shape(plan_geojson['features'][0]['geometry'])
    # UTM変換してグリッド生成
    grid_points = generate_grid(plan_poly, grid_size)
    covered = 0
    for pt in grid_points:
        for img in images:
            if img.footprint_polygon.contains(pt):
                covered += 1
                break
    return covered / len(grid_points) * 100
```

---

## 3. CLI インターフェース

```
usage: field_qc.py [-h] data_dir [--design DESIGN_CSV] [--plan PLAN_GEOJSON]
                   [--sensor {phantom4rtk,mavic3e,matrice350}]
                   [--output {console,json,html}] [--strict]

positional arguments:
  data_dir              撮影データディレクトリ

optional arguments:
  --design              設計座標CSV（GCP突合用）
  --plan                撮影計画エリアGeoJSON
  --sensor              機体プリセット（デフォルト: phantom4rtk）
  --output              出力形式（デフォルト: console）
  --strict              WARNING項目もFAIL扱いにする
```

---

## 4. 出力フォーマット

### 4.1 コンソール出力（デフォルト）

```
========================================
  TAS Field QC Report
  2026-03-14 15:32:00
  Data: /path/to/flight_data/
  Images: 342 files
========================================

[1/5] GPS整合性 ........................ PASS
  - GPS記録: 342/342 (100%)
  - 外れ値: 0件
  - 高度急変: 0件

[2/5] オーバーラップ率 .................. PASS
  - 進行方向(OL): 平均 83.2% (最小 80.1%)
  - 横方向(SL): 平均 67.5% (最小 61.3%)

[3/5] GCP精度 .......................... PASS
  - 検査点: 5/5
  - 水平誤差: 最大 32mm (許容 50mm)
  - 垂直誤差: 最大 28mm (許容 50mm)

[4/5] 画像品質 ......................... WARNING
  - ブレ画像: 0件
  - 白飛び: 2件 → DJI_0142.JPG, DJI_0143.JPG
  - 暗すぎ: 0件
  - 霧/もや: 1件 → DJI_0201.JPG

[5/5] カバレッジ ....................... PASS
  - カバレッジ率: 98.3% (基準 95%)
  - 未カバーグリッド: 3/180

========================================
  総合判定: PASS (WARNING: 1件)
========================================
  ※ WARNING画像の目視確認を推奨
```

### 4.2 JSON出力（`--output json`）

後続処理・Lark Base連携用。上記と同等の構造をJSONで出力。
ファイル名: `qc_report_YYYYMMDD_HHMMSS.json`

### 4.3 HTML出力（`--output html`）

問題画像のサムネイル付きレポート。現場でブラウザ確認用。

---

## 5. 機体プリセット

| 機体 | センサーサイズ(mm) | 焦点距離(mm) | 画角(°) | 解像度 |
|------|-------------------|-------------|---------|--------|
| Phantom 4 RTK | 13.2 x 8.8 | 8.8 | 84 | 5472x3648 |
| Mavic 3 Enterprise | 17.3 x 13.0 | 12.3 | 84 | 5280x3956 |
| Matrice 350 + P1 | 35.9 x 24.0 | 35 | 63.5 | 8192x5460 |

---

## 6. 判定ロジックまとめ

| チェック | PASS条件 | FAIL条件 | WARNING条件 |
|---------|---------|---------|-------------|
| GPS整合性 | 欠損0 & 外れ値0 | 欠損>0 or 外れ値>0 | - |
| オーバーラップ | OL≥80% & SL≥60% | OL<80% or SL<60% | OL<85% |
| GCP精度 | 全点 dh≤50mm & dv≤50mm | いずれか超過 | dh>30mm or dv>30mm |
| 画像品質 | 全画像PASS | ブレ or 暗すぎ >0 | 白飛び or 霧 >0 |
| カバレッジ | ≥95% | <90% | 90-95% |

**総合判定:**
- **PASS**: 全項目PASS（WARNING含む）
- **FAIL**: 1項目でもFAIL
- `--strict`: WARNING も FAIL扱い

---

## 7. 依存ライブラリ

```
pillow>=10.0
opencv-python-headless>=4.8
exifread>=3.0
numpy>=1.24
shapely>=2.0       # カバレッジ計算
pyproj>=3.6        # 座標変換（WGS84↔UTM）
```

---

## 8. ファイル構成

```
scripts/
  field_qc.py            # メインCLI
  field_qc/
    __init__.py
    gps_check.py         # 2.1 GPS整合性
    overlap_check.py     # 2.2 オーバーラップ率
    gcp_check.py         # 2.3 GCP精度
    image_quality.py     # 2.4 画像品質
    coverage_check.py    # 2.5 カバレッジ
    sensor_presets.py    # 機体プリセット
    report.py            # 出力生成（console/json/html）
    utils.py             # 座標変換・haversine等
```

---

## 9. 実行時間目安

| 画像枚数 | 想定時間 | ボトルネック |
|---------|---------|------------|
| 100枚 | ~30秒 | 画像品質チェック（OpenCV読み込み） |
| 500枚 | ~2分 | 同上 |
| 1000枚 | ~4分 | 同上 |

画像品質チェックは `multiprocessing.Pool` で並列化（CPU コア数分）。

---

## 10. 運用フロー

```
撮影完了
  ↓
SDカード → ノートPC にコピー
  ↓
python field_qc.py ./flight_data/ --design design.csv --plan plan.geojson
  ↓
┌─ PASS → 撤収OK
└─ FAIL → 問題箇所確認 → 再撮影/再計測 → 再チェック
```

---

## 11. 今後の拡張候補

- Lark Base連携: QC結果を受注台帳に自動記録
- 点群前処理: SfM前のタイポイント密度予測
- 熱画像対応: サーマルカメラのEXIF解析
- RTK Fix率チェック: PPKログからFix/Float比率確認
