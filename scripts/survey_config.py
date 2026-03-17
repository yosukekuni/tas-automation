"""
survey_config.py - ドローン測量自動化の共通設定

NASパス・座標系・品質基準をconfig化。
ハードコード禁止（CLAUDE.md準拠）。
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# NAS / ファイルパス設定（環境変数 or デフォルト）
# ---------------------------------------------------------------------------
NAS_BASE = os.environ.get("SURVEY_NAS_BASE", "/mnt/nas1")  # 1_projects
NAS_INBOX = os.environ.get("SURVEY_NAS_INBOX", "/mnt/nas")  # 0_inbox
NAS_ARCHIVE = os.environ.get("SURVEY_NAS_ARCHIVE", "/mnt/nas4")  # 4_archive

# プロジェクトルート（NAS上のドローン測量フォルダ）
SURVEY_PROJECT_ROOT = os.path.join(NAS_BASE, "drone_survey")
SURVEY_INBOX = os.path.join(NAS_INBOX, "drone_survey")

# ---------------------------------------------------------------------------
# 座標系設定
# ---------------------------------------------------------------------------
# 日本の平面直角座標系（JGD2011）- 地域別EPSGコード
PLANE_RECT_EPSG = {
    # 中部地方（東海エアサービス主要エリア）
    "VII": 6675,   # 第VII系: 愛知・三重・岐阜（東海メイン）
    "VIII": 6676,  # 第VIII系: 新潟・長野・山梨・静岡
    # 他の系が必要な場合はここに追加
}
DEFAULT_COORD_SYSTEM = "VII"  # 愛知・三重・岐阜
DEFAULT_EPSG = PLANE_RECT_EPSG[DEFAULT_COORD_SYSTEM]

# WGS84（GPS/ドローン生データ）
WGS84_EPSG = 4326
# JGD2011 地理座標
JGD2011_EPSG = 6668


# ---------------------------------------------------------------------------
# 品質基準（QC閾値）
# ---------------------------------------------------------------------------
@dataclass
class QCThresholds:
    """現場QCチェックの合否判定基準"""
    # GPS整合性
    gps_position_tolerance_m: float = 2.0       # GPS座標とExifの許容差（メートル）
    gps_altitude_tolerance_m: float = 5.0       # 高度の許容差（メートル）

    # 撮影カバレッジ
    min_coverage_ratio: float = 0.85            # 設計範囲に対する最小充足率（85%）
    min_overlap_ratio: float = 0.70             # 最小オーバーラップ率（70%）
    min_sidelap_ratio: float = 0.60             # 最小サイドラップ率（60%）

    # 画像品質
    max_blur_score: float = 100.0               # ブレスコア上限（Laplacian分散）
    min_brightness: int = 40                    # 最小輝度（0-255）
    max_brightness: int = 230                   # 最大輝度（0-255）
    min_contrast: float = 20.0                  # 最小コントラスト（標準偏差）

    # 座標精度
    max_design_deviation_m: float = 0.10        # 設計値との最大許容差（メートル）
    max_gcp_residual_m: float = 0.05            # GCP残差の最大許容値

    # 点群品質
    min_point_density: float = 50.0             # 最小点密度（点/m2）
    max_noise_ratio: float = 0.05               # 最大ノイズ率（5%）


@dataclass
class VolumeCalcConfig:
    """土量計算設定"""
    grid_resolution_m: float = 0.1              # グリッド解像度（メートル）
    mesh_method: str = "delaunay"               # メッシュ生成方式
    volume_method: str = "grid"                 # 体積計算方式: grid / mesh
    reference_plane: str = "lowest"             # 基準面: lowest / average / custom
    custom_reference_z: Optional[float] = None  # カスタム基準面の高さ


@dataclass
class CrossSectionConfig:
    """断面図設定"""
    interval_m: float = 1.0                     # 断面線上のサンプリング間隔（メートル）
    buffer_width_m: float = 0.5                 # 断面線からのバッファ幅
    output_dpi: int = 150                       # 出力画像のDPI
    figure_width_inch: float = 12.0
    figure_height_inch: float = 6.0


@dataclass
class DeliveryConfig:
    """納品フォルダ構成"""
    # 納品フォルダテンプレート: {project_root}/{site_name}/{date}/
    folder_structure: dict = field(default_factory=lambda: {
        "01_raw": "生データ（写真・GPSログ）",
        "02_pointcloud": "点群データ（LAS/PLY/LAZ）",
        "03_mesh": "メッシュ・DSM・オルソ",
        "04_volume": "土量計算結果",
        "05_crosssection": "断面図",
        "06_report": "レポート・QC結果",
        "07_reference": "参考資料（設計図・GCP座標等）",
    })


# ---------------------------------------------------------------------------
# グローバル設定インスタンス
# ---------------------------------------------------------------------------
QC = QCThresholds()
VOLUME = VolumeCalcConfig()
CROSS_SECTION = CrossSectionConfig()
DELIVERY = DeliveryConfig()


def load_project_config(config_path: str) -> dict:
    """
    プロジェクト固有設定をJSONから読み込み。

    config例:
    {
        "site_name": "名古屋港_残土",
        "coord_system": "VII",
        "design_boundary_wkt": "POLYGON((...  ...))",
        "gcp_file": "gcp_coords.csv",
        "reference_surface": "2026-01-15_baseline.las"
    }
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"プロジェクト設定ファイルが見つかりません: {config_path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_delivery_path(site_name: str, date_str: str, subfolder: str = "") -> Path:
    """納品フォルダパスを生成"""
    base = Path(SURVEY_PROJECT_ROOT) / site_name / date_str
    if subfolder:
        return base / subfolder
    return base
