# ドローン測量 後工程自動化 設計書

**作成日**: 2026-03-17
**ステータス**: プロトタイプ完了
**対象タスク**: Metashape出力後の後工程自動化 + 撮影データ現場QCチェック

---

## 1. 概要

Metashapeで処理した点群データの後工程（土量計算・断面図・レポート）と、撮影現場でのデータ品質チェックを自動化するスクリプト群。

### 解決する課題
- 土量計算の手作業（Excel手入力）を自動化
- 断面図生成の外注コスト削減
- 現場での撮影やり直し判断の迅速化（帰社後に品質不足発覚→再訪問を防止）
- 納品フォルダの整理ルール統一

### スコープ
| 機能 | スクリプト | 状態 |
|------|-----------|------|
| 土量計算（差分解析） | survey_postprocess.py | プロトタイプ |
| 断面図生成 | survey_postprocess.py | プロトタイプ |
| 定期比較レポート | survey_postprocess.py | プロトタイプ |
| 納品データ整理 | survey_postprocess.py | プロトタイプ |
| GPS整合性チェック | survey_field_qc.py | プロトタイプ |
| 撮影カバレッジ確認 | survey_field_qc.py | プロトタイプ |
| 画像品質チェック | survey_field_qc.py | プロトタイプ |
| GCP精度チェック | survey_field_qc.py | プロトタイプ |

---

## 2. アーキテクチャ

```
NAS (1_projects/drone_survey/)
  └── {site_name}/
       └── {date}/
            ├── 01_raw/          ← 撮影生データ
            ├── 02_pointcloud/   ← LAS/PLY点群
            ├── 03_mesh/         ← DSM/オルソ
            ├── 04_volume/       ← 土量計算結果
            ├── 05_crosssection/ ← 断面図
            ├── 06_report/       ← PDF/QCレポート
            └── 07_reference/    ← 設計図/GCP座標

scripts/
  ├── survey_config.py        ← 共通設定（NASパス・座標系・閾値）
  ├── survey_postprocess.py   ← 後工程自動化
  └── survey_field_qc.py      ← 現場QCチェック
```

### 設定のconfig化
- NASパスは環境変数 `SURVEY_NAS_BASE` で上書き可能
- 座標系は平面直角座標系VII系（愛知・三重・岐阜）がデフォルト
- QC閾値は `survey_config.py` の `QCThresholds` で一元管理
- プロジェクト固有設定はJSONファイルで指定

---

## 3. 後工程自動化 (survey_postprocess.py)

### 3.1 土量計算

**方式**: グリッドベースの差分体積算出
1. 基準時点(before)と比較時点(after)の点群を読み込み
2. 共通XY範囲にグリッドを生成（デフォルト0.1m解像度）
3. 各セルの平均Z値を算出
4. 差分（after - before）から切土/盛土量を計算

**出力**:
- 切土量・盛土量・差引（m3）
- 差分ヒートマップ画像（赤=盛土 / 青=切土）

**使用例**:
```bash
python survey_postprocess.py \
  --baseline 2026-01-15_baseline.las \
  --current 2026-03-15_survey.las \
  --site "名古屋港_残土置場" \
  --resolution 0.1 \
  --organize
```

### 3.2 断面図

**方式**: 指定ライン沿いの点群スライス
1. 断面線（始点-終点）を指定
2. バッファ幅内の点を抽出
3. 断面線上の等間隔ビンで平均Z値を算出
4. 複数時点の断面を重ね描き可能

**使用例**:
```bash
python survey_postprocess.py \
  --input survey.las \
  --cross-section "1000,2000,1100,2000;1000,2050,1100,2050" \
  --site "河川堤防"
```

### 3.3 納品フォルダ整理

`--organize` フラグで自動的に標準フォルダ構成を作成し、生成物を配置。

### 3.4 レポートPDF

reportlabでA4 PDFを生成。日本語フォントが利用可能なら使用。
reportlab未インストール時はテキストレポートにフォールバック。

---

## 4. 現場QCチェック (survey_field_qc.py)

### 4.1 GPSログ整合性

- 各画像のExif GPS座標をフライトログCSVと照合
- ファイル名マッチ → 最近傍マッチのフォールバック
- 許容差: 水平2.0m / 高度5.0m（設定変更可能）

### 4.2 撮影カバレッジ

- Exif GPS座標の凸包と設計範囲（GeoJSON/WKT）の交差面積比
- 基準: 85%以上で合格

### 4.3 画像品質

| チェック項目 | 手法 | 閾値 |
|------------|------|------|
| ブレ | Laplacian分散 | 100以上で合格 |
| 露出不足 | 平均輝度 | 40以上 |
| 露出過多 | 平均輝度 | 230以下 |
| コントラスト | 輝度の標準偏差 | 20以上 |

OpenCV優先、なければPillow+scipyフォールバック。

### 4.4 GCP精度

- 設計GCP座標と計測GCP座標のCSVを比較
- 3D残差を算出、RMSEで評価
- 閾値: 1点あたり0.05m以下

### 4.5 判定ロジック

- 個別画像: 全チェック合格で PASS
- 全体: 10%以上の画像が不合格、またはカバレッジ/GCP不合格で FAIL
- 終了コード: PASS=0 / FAIL=1（CI連携可能）

**使用例**:
```bash
python survey_field_qc.py \
  --image-dir /mnt/nas/drone_survey/photos/ \
  --gps-log flight_log.csv \
  --boundary design_area.geojson \
  --gcp gcp_design.csv \
  --gcp-measured gcp_metashape.csv \
  --output qc_report/
```

**出力**:
- `qc_detail.json` - 全画像の詳細結果
- `qc_summary.txt` - 現場確認用テキスト（再撮影対象一覧）
- `photo_positions.png` - 撮影位置マップ（PASS/FAIL色分け）

---

## 5. 依存パッケージ

```
pip install -r requirements-survey.txt
```

主要パッケージ:
- **laspy** + lazrs: LAS/LAZ点群I/O
- **Open3D**: 点群・メッシュ処理
- **numpy** + scipy: 数値計算・グリッド統計
- **pyproj**: 座標系変換（WGS84 → JGD2011平面直角）
- **shapely**: 空間解析（カバレッジ）
- **Pillow** + opencv-python-headless: 画像処理・Exif・品質検査
- **matplotlib**: 可視化
- **reportlab**: PDF生成

PDAL（点群パイプライン）はオプション。conda経由推奨。

---

## 6. 座標系

| 用途 | 座標系 | EPSG |
|------|--------|------|
| GPS/ドローン生データ | WGS84 | 4326 |
| JGD2011地理座標 | JGD2011 | 6668 |
| 平面直角VII系（愛知・三重・岐阜） | JGD2011 CS VII | 6675 |
| 平面直角VIII系（静岡） | JGD2011 CS VIII | 6676 |

pyproj Transformerで変換。デフォルトはVII系（東海エリア）。

---

## 7. 今後の拡張計画

### Phase 2（実データで検証後）
- [ ] PDAL統合（ノイズ除去・地表分類フィルタ）
- [ ] メッシュベースの土量計算（Delaunay三角形メッシュ）
- [ ] オーバーラップ/サイドラップ率の実計算（カメラFOVベース）
- [ ] Metashape Python APIとの直接連携
- [ ] Lark通知（QC結果をLark Webhookで現場チームに即時共有）

### Phase 3（運用安定後）
- [ ] 定期比較の自動スケジュール（月次/週次の土量変化トラッキング）
- [ ] GitHub Actions連携（NASに新データ投入→自動処理→レポート生成）
- [ ] ダッシュボード統合（既存dashboard.htmlに測量KPIを追加）
- [ ] 全天球画像の合成品質チェック

---

## 8. ファイル一覧

| ファイル | 説明 |
|---------|------|
| `scripts/survey_config.py` | 共通設定（NASパス・座標系・QC閾値） |
| `scripts/survey_postprocess.py` | 後工程自動化（土量・断面・レポート・納品整理） |
| `scripts/survey_field_qc.py` | 現場QCチェック（GPS・画像品質・カバレッジ・GCP） |
| `requirements-survey.txt` | 依存パッケージ一覧 |
| `content/survey_automation_design.md` | 本設計書 |
