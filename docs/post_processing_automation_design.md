# Metashape後工程自動化 設計書

## 1. 概要

Metashape出力後の手動作業4工程をPythonスクリプトで自動化する。

| 工程 | 入力 | 出力 | スクリプト名 |
|------|------|------|-------------|
| 土量計算 | 2時点のLAS/LAZ | CSV + ヒートマップPNG | `volume_calc.py` |
| 断面図生成 | LAS/LAZ + 断面定義JSON | 断面図PNG + CSV | `cross_section.py` |
| 定期比較レポート | 2時点のLAS/LAZ + 前回レポート | PDF | `comparison_report.py` |
| 納品データ整理 | 各出力ファイル群 | 整理済みフォルダ + ZIP | `delivery_organizer.py` |

**技術スタック**: Python 3.10+ / Open3D / PDAL / laspy / matplotlib / reportlab(PDF)

---

## 2. 共通設計

### 2.1 設定ファイル (`config/survey_config.json`)

```json
{
  "project_name": "現場名",
  "client_name": "取引先名",
  "coordinate_system": "EPSG:6677",
  "input_dir": "./input",
  "output_dir": "./output",
  "previous_data": null,
  "cross_sections": [],
  "grid_resolution": 0.5,
  "delivery_format": {
    "naming_pattern": "{project}_{date}_{type}",
    "zip_compression": true
  }
}
```

### 2.2 ディレクトリ構成

```
survey_project/
├── config/
│   └── survey_config.json
├── input/
│   ├── before.las          # 前回時点（土量計算・比較用）
│   └── after.las           # 今回時点
├── output/
│   ├── volume/
│   │   ├── volume_summary.csv
│   │   └── heatmap.png
│   ├── sections/
│   │   ├── section_001.png
│   │   └── section_data.csv
│   ├── report/
│   │   └── comparison_report.pdf
│   └── delivery/
│       └── {project}_{date}_納品.zip
└── logs/
    └── processing.log
```

### 2.3 共通モジュール (`survey_utils.py`)

| 関数 | 役割 |
|------|------|
| `load_point_cloud(path)` | LAS/LAZ読み込み。laspy→numpy配列変換 |
| `create_dem(points, resolution)` | 点群→DEM（グリッド補間）。scipy.interpolate.griddata使用 |
| `align_grids(dem1, dem2)` | 2つのDEMのグリッド範囲・解像度を統一 |
| `setup_logger(name)` | ログ設定。ファイル+コンソール出力 |
| `validate_crs(las_file, expected_epsg)` | 座標系の一致確認 |

---

## 3. 工程別設計

### 3.1 土量計算 (`volume_calc.py`)

**処理フロー**:

```
before.las → DEM化 → グリッド統一 → 差分DEM算出 → 切土/盛土分離 → 体積算出 → CSV + ヒートマップ
after.las  → DEM化 ↗
```

**アルゴリズム**:
1. 両時点の点群を読み込み、地表面DEMを生成（グリッド解像度: 設定値、デフォルト0.5m）
2. グリッド範囲の共通領域を算出し、両DEMを統一
3. 差分DEM = after_dem - before_dem
4. 正値 = 盛土（土砂堆積）、負値 = 切土（土砂除去）
5. 各セルの体積 = 高さ差 × セル面積（resolution^2）
6. 合計体積を算出

**出力 (`volume_summary.csv`)**:
```
項目,値,単位
切土量,1234.56,m³
盛土量,789.01,m³
差引(切-盛),445.55,m³
対象面積,5000.00,m²
グリッド解像度,0.50,m
計測日(前),2026-01-15,
計測日(後),2026-03-14,
```

**ヒートマップ**: matplotlibでカラーマップ（赤=切土 / 青=盛土）を生成。カラーバーに高さ差(m)を表示。

**精度管理**:
- グリッド解像度と点群密度の比率チェック（密度不足で警告）
- 外れ値フィルタリング（標準偏差3σ超の点を除外）
- 処理範囲のバウンディングボックスをログに記録

### 3.2 断面図生成 (`cross_section.py`)

**処理フロー**:

```
LAS + 断面定義JSON → 断面線バッファ内の点を抽出 → 断面線上に投影 → ソート → プロット → PNG + CSV
```

**断面定義JSON**:
```json
{
  "sections": [
    {
      "id": "A-A'",
      "start": [x1, y1],
      "end": [x2, y2],
      "buffer_width": 1.0
    }
  ]
}
```

**アルゴリズム**:
1. 断面線の始点→終点を結ぶベクトルを算出
2. バッファ幅（デフォルト1.0m）内の点群を抽出
3. 各点を断面線上に直交投影し、始点からの距離と標高(Z)を取得
4. 距離でソートし、断面プロファイルを生成
5. 2時点ある場合は同一断面に重ねて描画（実線=今回 / 破線=前回）

**出力**:
- PNG: X軸=距離(m)、Y軸=標高(m)。アスペクト比は縦強調（実測スケールだと平坦に見えるため）
- CSV: 距離, 標高(今回), 標高(前回)

**パラメータ**:
| パラメータ | デフォルト | 説明 |
|-----------|-----------|------|
| buffer_width | 1.0m | 断面線からの抽出幅 |
| vertical_exaggeration | 5.0 | 縦倍率（表示用） |
| point_interval | 0.1m | 断面上の補間間隔 |

### 3.3 定期比較レポート (`comparison_report.py`)

**処理フロー**:

```
volume_calc結果 + cross_section結果 + 前回レポート(任意) → PDF統合
```

**PDFレポート構成**:

| ページ | 内容 |
|--------|------|
| 表紙 | 現場名・取引先名・計測日・作成日 |
| 概要 | 土量サマリ表 + 前回比増減 |
| ヒートマップ | 差分DEMカラーマップ（全体図） |
| 断面図 | 各断面図（1断面/ページ、2時点重ね描画） |
| 数値データ | 土量計算詳細表 |
| 付記 | 座標系・精度情報・使用ソフトウェア |

**レポート生成**: reportlab + matplotlib図埋め込み。テンプレートはPython内で定義（外部テンプレート不要）。

**前回比較ロジック**:
- `previous_data`が設定されている場合、前回CSVを読み込み差分を算出
- 「前回比 切土量 +15.3%」のような増減率を表示

### 3.4 納品データ整理 (`delivery_organizer.py`)

**処理フロー**:

```
output各フォルダ → 命名規則適用 → フォルダ構成作成 → ZIP圧縮
```

**命名規則**:
```
{現場名}_{計測日YYYYMMDD}_{種別}.{拡張子}

例:
  名古屋港埋立地_20260314_土量計算.csv
  名古屋港埋立地_20260314_ヒートマップ.png
  名古屋港埋立地_20260314_断面図_A-A.png
  名古屋港埋立地_20260314_比較レポート.pdf
```

**納品フォルダ構成**:
```
{現場名}_{計測日}_納品/
├── 01_土量計算/
│   ├── 土量サマリ.csv
│   └── 差分ヒートマップ.png
├── 02_断面図/
│   ├── 断面図_A-A.png
│   ├── 断面図_B-B.png
│   └── 断面データ.csv
├── 03_比較レポート/
│   └── 定期比較レポート.pdf
└── 04_点群データ/
    └── (オプション: LAS/LAZの納品が必要な場合コピー)
```

**ZIP圧縮**: shutil.make_archive使用。文字化け防止のためUTF-8設定。

---

## 4. CLI設計

全スクリプトを統合するエントリーポイント `survey_pipeline.py` を用意。

```
# 全工程一括実行
python survey_pipeline.py --config config/survey_config.json

# 個別実行
python survey_pipeline.py --config config/survey_config.json --step volume
python survey_pipeline.py --config config/survey_config.json --step section
python survey_pipeline.py --config config/survey_config.json --step report
python survey_pipeline.py --config config/survey_config.json --step delivery

# 断面定義のみ追加して再実行
python survey_pipeline.py --config config/survey_config.json --step section --sections sections.json
```

**引数**:
| フラグ | 必須 | 説明 |
|--------|------|------|
| `--config` | Yes | 設定ファイルパス |
| `--step` | No | 実行工程（省略時は全工程） |
| `--sections` | No | 断面定義JSONパス（section工程用） |
| `--no-zip` | No | ZIP圧縮をスキップ |
| `--verbose` | No | 詳細ログ出力 |

---

## 5. 依存パッケージ

```
laspy[lazrs]>=2.5      # LAS/LAZ読み書き
open3d>=0.18           # 点群処理・フィルタリング
pdal>=3.2              # パイプライン処理（CRS変換等）
numpy>=1.24
scipy>=1.11            # DEM補間（griddata）
matplotlib>=3.8        # 断面図・ヒートマップ描画
reportlab>=4.0         # PDF生成
```

---

## 6. エラーハンドリング

| エラー条件 | 対応 |
|-----------|------|
| LASファイルが空 / 読み込み失敗 | 即時終了 + エラーログ |
| 2時点のCRS不一致 | 警告表示 + PDAL経由で自動変換を試行 |
| 点群の重複領域が全体の50%未満 | 警告ログ（比較精度低下の可能性） |
| 断面線が点群範囲外 | 該当断面をスキップ + 警告 |
| メモリ不足（大規模点群） | PDALパイプラインでタイル分割読み込み |

---

## 7. 実装優先度

| 順位 | スクリプト | 理由 |
|------|-----------|------|
| 1 | `survey_utils.py` | 全工程の基盤 |
| 2 | `volume_calc.py` | 最も頻繁に依頼される作業 |
| 3 | `delivery_organizer.py` | 毎回発生する定型作業 |
| 4 | `cross_section.py` | 案件により必要 |
| 5 | `comparison_report.py` | 定期案件で必要 |
| 6 | `survey_pipeline.py` | 統合CLI |

---

## 8. 将来拡張

- **Metashape API連携**: Metashape Python APIで処理→後工程を完全パイプライン化
- **GeoTIFF出力**: DEMをGeoTIFF形式でも出力（GIS連携用）
- **Lark CRM連携**: 受注台帳から現場名・取引先を自動取得し設定ファイル生成
- **Web閲覧**: Potree等で3D点群をブラウザ表示（顧客向けプレビュー）
