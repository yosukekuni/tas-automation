#!/usr/bin/env python3
"""
survey_field_qc.py - 撮影データ現場QCチェック

撮影直後にデータ品質を自動検査し、現場で再撮影判断を支援。

機能:
  1. GPSログとExif情報の整合性チェック
  2. 撮影カバレッジ確認（設計範囲に対する充足率）
  3. 画像品質チェック（ブレ・露出・ピント）
  4. 座標系変換・設計値との差分チェック
  5. 合否判定レポート生成

使用方法:
  python survey_field_qc.py --image-dir ./photos --gps-log flight.csv
  python survey_field_qc.py --image-dir ./photos --boundary design_area.geojson
  python survey_field_qc.py --image-dir ./photos --gcp gcp_coords.csv --output qc_report/

依存: Pillow, piexif, numpy, pyproj, shapely, matplotlib
"""

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# ---- 遅延インポート ----
def _import_pil():
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 300_000_000  # ドローン高解像度画像対応
    return Image

def _import_cv2():
    import cv2
    return cv2

def _import_matplotlib():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt

# ---- ローカル設定 ----
sys.path.insert(0, os.path.dirname(__file__))
from survey_config import QC, DEFAULT_EPSG, WGS84_EPSG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("survey_field_qc")


# =========================================================================
# データ構造
# =========================================================================

@dataclass
class ImageQCResult:
    """1画像のQC結果"""
    filename: str
    # GPS
    exif_lat: Optional[float] = None
    exif_lon: Optional[float] = None
    exif_alt: Optional[float] = None
    gps_match: Optional[bool] = None       # GPSログとの整合
    gps_deviation_m: Optional[float] = None
    # 画像品質
    blur_score: Optional[float] = None     # Laplacian分散（低い=ブレ大）
    brightness: Optional[float] = None     # 平均輝度
    contrast: Optional[float] = None       # 輝度の標準偏差
    is_blurry: bool = False
    is_overexposed: bool = False
    is_underexposed: bool = False
    is_low_contrast: bool = False
    # 判定
    pass_qc: bool = True
    issues: List[str] = field(default_factory=list)


@dataclass
class QCSummary:
    """全体QCサマリー"""
    total_images: int = 0
    passed_images: int = 0
    failed_images: int = 0
    # GPS
    gps_checked: int = 0
    gps_passed: int = 0
    avg_gps_deviation_m: float = 0.0
    # 画像品質
    blurry_count: int = 0
    overexposed_count: int = 0
    underexposed_count: int = 0
    low_contrast_count: int = 0
    # カバレッジ
    coverage_ratio: Optional[float] = None
    coverage_pass: Optional[bool] = None
    # GCP
    gcp_residuals: Optional[List[float]] = None
    gcp_pass: Optional[bool] = None
    # 総合判定
    overall_pass: bool = True
    failure_reasons: List[str] = field(default_factory=list)


# =========================================================================
# 1. Exif GPS抽出
# =========================================================================

def extract_exif_gps(image_path: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """画像のExifからGPS座標を抽出 (lat, lon, alt)"""
    try:
        Image = _import_pil()
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data:
            return None, None, None

        # GPSInfo tag = 34853
        gps_info = exif_data.get(34853)
        if not gps_info:
            return None, None, None

        def _dms_to_decimal(dms, ref):
            """度分秒 → 10進数"""
            if isinstance(dms[0], tuple):
                degrees = dms[0][0] / dms[0][1]
                minutes = dms[1][0] / dms[1][1]
                seconds = dms[2][0] / dms[2][1]
            else:
                degrees, minutes, seconds = float(dms[0]), float(dms[1]), float(dms[2])
            decimal = degrees + minutes / 60 + seconds / 3600
            if ref in ("S", "W"):
                decimal = -decimal
            return decimal

        lat = _dms_to_decimal(gps_info[2], gps_info[1]) if 2 in gps_info else None
        lon = _dms_to_decimal(gps_info[4], gps_info[3]) if 4 in gps_info else None
        alt = None
        if 6 in gps_info:
            alt_val = gps_info[6]
            alt = float(alt_val[0] / alt_val[1]) if isinstance(alt_val, tuple) else float(alt_val)

        return lat, lon, alt

    except Exception as e:
        log.warning(f"Exif GPS抽出エラー ({Path(image_path).name}): {e}")
        return None, None, None


# =========================================================================
# 2. GPSログとの整合性チェック
# =========================================================================

def load_gps_log(log_path: str) -> List[dict]:
    """
    GPSログCSVを読み込み。

    想定フォーマット:
      timestamp, latitude, longitude, altitude, filename(optional)
    or DJI形式:
      datetime, latitude, longitude, altitude(m), ...
    """
    records = []
    path = Path(log_path)

    if path.suffix.lower() == ".csv":
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rec = {}
                # 柔軟にカラム名をマッピング
                for lat_key in ("latitude", "lat", "Latitude", "GPSLatitude"):
                    if lat_key in row:
                        rec["lat"] = float(row[lat_key])
                        break
                for lon_key in ("longitude", "lon", "Longitude", "GPSLongitude"):
                    if lon_key in row:
                        rec["lon"] = float(row[lon_key])
                        break
                for alt_key in ("altitude", "alt", "Altitude", "GPSAltitude", "altitude(m)"):
                    if alt_key in row:
                        rec["alt"] = float(row[alt_key])
                        break
                for fn_key in ("filename", "file", "FileName", "photo"):
                    if fn_key in row:
                        rec["filename"] = row[fn_key]
                        break
                if "lat" in rec and "lon" in rec:
                    records.append(rec)

    log.info(f"GPSログ読み込み: {len(records)}件 ({path.name})")
    return records


def check_gps_consistency(
    image_results: List[ImageQCResult],
    gps_log: List[dict],
) -> List[ImageQCResult]:
    """ExifのGPSとフライトログの整合性を検証"""
    from pyproj import Geod
    geod = Geod(ellps="WGS84")

    # ファイル名でマッチングを試みる
    log_by_name = {}
    for rec in gps_log:
        if "filename" in rec:
            log_by_name[Path(rec["filename"]).stem] = rec

    # ファイル名マッチがない場合、最近傍マッチ（タイムスタンプor位置）
    log_positions = np.array([[r["lat"], r["lon"]] for r in gps_log]) if gps_log else None

    for result in image_results:
        if result.exif_lat is None or result.exif_lon is None:
            continue

        stem = Path(result.filename).stem
        matched = log_by_name.get(stem)

        if matched:
            # 直接マッチ
            _, _, dist = geod.inv(
                result.exif_lon, result.exif_lat,
                matched["lon"], matched["lat"],
            )
            result.gps_deviation_m = round(float(dist), 3)
        elif log_positions is not None:
            # 最近傍マッチ
            img_pos = np.array([result.exif_lat, result.exif_lon])
            dists = np.sqrt(np.sum((log_positions - img_pos) ** 2, axis=1))
            nearest_idx = np.argmin(dists)
            nearest = gps_log[nearest_idx]
            _, _, dist = geod.inv(
                result.exif_lon, result.exif_lat,
                nearest["lon"], nearest["lat"],
            )
            result.gps_deviation_m = round(float(dist), 3)

        if result.gps_deviation_m is not None:
            result.gps_match = result.gps_deviation_m <= QC.gps_position_tolerance_m
            if not result.gps_match:
                result.pass_qc = False
                result.issues.append(
                    f"GPS偏差 {result.gps_deviation_m:.1f}m > 許容値{QC.gps_position_tolerance_m}m"
                )

    return image_results


# =========================================================================
# 3. 画像品質チェック
# =========================================================================

def check_image_quality(image_path: str) -> dict:
    """
    画像品質を検査（ブレ・露出・コントラスト）。

    OpenCV利用。なければPillow/numpyフォールバック。
    """
    try:
        cv2 = _import_cv2()
        img = cv2.imread(image_path)
        if img is None:
            return {"error": "画像読み込み失敗"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # ブレ検出（Laplacian分散）
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        blur_score = float(laplacian.var())

        # 明るさ・コントラスト
        brightness = float(gray.mean())
        contrast = float(gray.std())

        return {
            "blur_score": round(blur_score, 2),
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
        }

    except ImportError:
        # Pillow/numpyフォールバック
        Image = _import_pil()
        img = Image.open(image_path).convert("L")
        arr = np.array(img, dtype=float)

        # 簡易ブレ検出（Laplacianカーネル）
        kernel = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=float)
        from scipy.signal import convolve2d
        lap = convolve2d(arr, kernel, mode="valid")
        blur_score = float(lap.var())

        brightness = float(arr.mean())
        contrast = float(arr.std())

        return {
            "blur_score": round(blur_score, 2),
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 2),
        }


def evaluate_image_quality(result: ImageQCResult, quality: dict) -> ImageQCResult:
    """品質数値を閾値と比較して合否判定"""
    if "error" in quality:
        result.pass_qc = False
        result.issues.append(quality["error"])
        return result

    result.blur_score = quality["blur_score"]
    result.brightness = quality["brightness"]
    result.contrast = quality["contrast"]

    # ブレ判定（スコアが低い = ブレが大きい）
    if result.blur_score < QC.max_blur_score:
        result.is_blurry = True
        result.pass_qc = False
        result.issues.append(f"ブレ検出 (score={result.blur_score:.0f} < {QC.max_blur_score})")

    # 露出
    if result.brightness < QC.min_brightness:
        result.is_underexposed = True
        result.pass_qc = False
        result.issues.append(f"露出不足 (brightness={result.brightness:.0f})")
    elif result.brightness > QC.max_brightness:
        result.is_overexposed = True
        result.pass_qc = False
        result.issues.append(f"露出過多 (brightness={result.brightness:.0f})")

    # コントラスト
    if result.contrast < QC.min_contrast:
        result.is_low_contrast = True
        result.pass_qc = False
        result.issues.append(f"低コントラスト (contrast={result.contrast:.0f})")

    return result


# =========================================================================
# 4. 撮影カバレッジチェック
# =========================================================================

def check_coverage(
    image_results: List[ImageQCResult],
    boundary_path: str = None,
    boundary_wkt: str = None,
) -> Optional[float]:
    """
    撮影カバレッジ（設計範囲に対する充足率）を算出。

    設計範囲をGeoJSON/WKTで指定。撮影点の凸包が設計範囲をカバーしている割合を算出。
    """
    try:
        from shapely.geometry import Point, MultiPoint, shape
        from shapely import wkt as shapely_wkt
    except ImportError:
        log.warning("shapely未インストール。カバレッジチェックをスキップ")
        return None

    # 撮影点の座標を取得
    photo_coords = []
    for r in image_results:
        if r.exif_lat is not None and r.exif_lon is not None:
            photo_coords.append((r.exif_lon, r.exif_lat))

    if len(photo_coords) < 3:
        log.warning("GPS付き画像が3枚未満。カバレッジ計算不可")
        return None

    # 撮影範囲（凸包）
    photo_hull = MultiPoint(photo_coords).convex_hull

    # 設計範囲の取得
    design_area = None
    if boundary_path:
        path = Path(boundary_path)
        if path.suffix.lower() == ".geojson":
            with open(path, "r", encoding="utf-8") as f:
                geojson = json.load(f)
            if geojson["type"] == "FeatureCollection":
                design_area = shape(geojson["features"][0]["geometry"])
            else:
                design_area = shape(geojson["geometry"] if "geometry" in geojson else geojson)
        elif path.suffix.lower() == ".wkt":
            design_area = shapely_wkt.loads(path.read_text())
    elif boundary_wkt:
        design_area = shapely_wkt.loads(boundary_wkt)

    if design_area is None:
        log.warning("設計範囲未指定。カバレッジ比率のみ計算不可")
        return None

    # カバレッジ = 交差面積 / 設計面積
    intersection = photo_hull.intersection(design_area)
    coverage = intersection.area / design_area.area if design_area.area > 0 else 0
    coverage = min(coverage, 1.0)  # 100%上限

    log.info(f"撮影カバレッジ: {coverage:.1%}")
    return round(coverage, 4)


# =========================================================================
# 5. GCPチェック
# =========================================================================

def check_gcp_accuracy(
    gcp_file: str,
    measured_file: str = None,
) -> Optional[dict]:
    """
    GCP（地上基準点）の精度チェック。

    gcp_file: 設計GCP座標CSV (id, x, y, z)
    measured_file: 計測GCP座標CSV (id, x, y, z) ※Metashape出力等
    """
    if not measured_file or not os.path.exists(measured_file):
        return None

    design_gcps = {}
    with open(gcp_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = row.get("id", row.get("ID", row.get("name", "")))
            design_gcps[gid] = {
                "x": float(row.get("x", row.get("X", row.get("easting", 0)))),
                "y": float(row.get("y", row.get("Y", row.get("northing", 0)))),
                "z": float(row.get("z", row.get("Z", row.get("elevation", 0)))),
            }

    measured_gcps = {}
    with open(measured_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            gid = row.get("id", row.get("ID", row.get("name", "")))
            measured_gcps[gid] = {
                "x": float(row.get("x", row.get("X", row.get("easting", 0)))),
                "y": float(row.get("y", row.get("Y", row.get("northing", 0)))),
                "z": float(row.get("z", row.get("Z", row.get("elevation", 0)))),
            }

    residuals = []
    details = []
    for gid in design_gcps:
        if gid in measured_gcps:
            d = design_gcps[gid]
            m = measured_gcps[gid]
            dx = m["x"] - d["x"]
            dy = m["y"] - d["y"]
            dz = m["z"] - d["z"]
            residual_3d = np.sqrt(dx**2 + dy**2 + dz**2)
            residuals.append(residual_3d)
            details.append({
                "id": gid,
                "dx": round(dx, 4),
                "dy": round(dy, 4),
                "dz": round(dz, 4),
                "residual_3d": round(residual_3d, 4),
                "pass": residual_3d <= QC.max_gcp_residual_m,
            })

    if not residuals:
        return None

    return {
        "gcp_count": len(residuals),
        "mean_residual": round(float(np.mean(residuals)), 4),
        "max_residual": round(float(np.max(residuals)), 4),
        "rms_residual": round(float(np.sqrt(np.mean(np.array(residuals)**2))), 4),
        "all_pass": all(d["pass"] for d in details),
        "details": details,
    }


# =========================================================================
# 6. QC実行 & レポート生成
# =========================================================================

def run_qc(
    image_dir: str,
    gps_log: str = None,
    boundary: str = None,
    gcp_file: str = None,
    gcp_measured: str = None,
    output_dir: str = None,
) -> QCSummary:
    """
    全QCチェックを実行し、サマリーを返す。
    """
    img_dir = Path(image_dir)
    if not img_dir.exists():
        raise FileNotFoundError(f"画像ディレクトリが見つかりません: {image_dir}")

    # 対象画像一覧
    image_extensions = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".dng"}
    image_files = sorted([
        f for f in img_dir.iterdir()
        if f.suffix.lower() in image_extensions
    ])

    if not image_files:
        raise ValueError(f"画像が見つかりません: {image_dir}")

    log.info(f"QC対象: {len(image_files)}枚 ({img_dir})")

    # --- 各画像のQC ---
    results: List[ImageQCResult] = []
    for img_file in image_files:
        result = ImageQCResult(filename=img_file.name)

        # GPS抽出
        lat, lon, alt = extract_exif_gps(str(img_file))
        result.exif_lat = lat
        result.exif_lon = lon
        result.exif_alt = alt

        # 画像品質
        quality = check_image_quality(str(img_file))
        result = evaluate_image_quality(result, quality)

        results.append(result)

    # --- GPSログ整合性 ---
    if gps_log:
        log_data = load_gps_log(gps_log)
        results = check_gps_consistency(results, log_data)

    # --- カバレッジ ---
    coverage = check_coverage(results, boundary_path=boundary) if boundary else None

    # --- GCPチェック ---
    gcp_result = check_gcp_accuracy(gcp_file, gcp_measured) if gcp_file else None

    # --- サマリー集計 ---
    summary = QCSummary(
        total_images=len(results),
        passed_images=sum(1 for r in results if r.pass_qc),
        failed_images=sum(1 for r in results if not r.pass_qc),
        gps_checked=sum(1 for r in results if r.gps_deviation_m is not None),
        gps_passed=sum(1 for r in results if r.gps_match is True),
        blurry_count=sum(1 for r in results if r.is_blurry),
        overexposed_count=sum(1 for r in results if r.is_overexposed),
        underexposed_count=sum(1 for r in results if r.is_underexposed),
        low_contrast_count=sum(1 for r in results if r.is_low_contrast),
    )

    # GPS偏差平均
    gps_devs = [r.gps_deviation_m for r in results if r.gps_deviation_m is not None]
    if gps_devs:
        summary.avg_gps_deviation_m = round(float(np.mean(gps_devs)), 3)

    # カバレッジ
    if coverage is not None:
        summary.coverage_ratio = coverage
        summary.coverage_pass = coverage >= QC.min_coverage_ratio
        if not summary.coverage_pass:
            summary.failure_reasons.append(
                f"カバレッジ不足: {coverage:.1%} < {QC.min_coverage_ratio:.0%}"
            )

    # GCP
    if gcp_result:
        summary.gcp_residuals = [d["residual_3d"] for d in gcp_result["details"]]
        summary.gcp_pass = gcp_result["all_pass"]
        if not summary.gcp_pass:
            summary.failure_reasons.append(
                f"GCP残差超過: max={gcp_result['max_residual']}m > {QC.max_gcp_residual_m}m"
            )

    # 総合判定
    if summary.failed_images > 0:
        fail_pct = summary.failed_images / summary.total_images * 100
        summary.failure_reasons.append(
            f"品質不合格: {summary.failed_images}/{summary.total_images}枚 ({fail_pct:.0f}%)"
        )
    if summary.coverage_pass is False:
        summary.overall_pass = False
    if summary.gcp_pass is False:
        summary.overall_pass = False
    # 10%以上の画像が不合格なら全体不合格
    if summary.total_images > 0 and summary.failed_images / summary.total_images > 0.10:
        summary.overall_pass = False

    if not summary.failure_reasons:
        summary.overall_pass = True

    # --- レポート出力 ---
    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        _save_qc_report(out, results, summary, gcp_result)

    return summary


def _save_qc_report(
    output_dir: Path,
    results: List[ImageQCResult],
    summary: QCSummary,
    gcp_result: dict = None,
):
    """QCレポートをJSON + テキストで保存"""

    # JSON詳細レポート
    json_path = output_dir / "qc_detail.json"
    report_data = {
        "generated": datetime.now().isoformat(),
        "summary": {
            "total_images": summary.total_images,
            "passed": summary.passed_images,
            "failed": summary.failed_images,
            "overall_pass": summary.overall_pass,
            "coverage_ratio": summary.coverage_ratio,
            "avg_gps_deviation_m": summary.avg_gps_deviation_m,
            "failure_reasons": summary.failure_reasons,
        },
        "quality_issues": {
            "blurry": summary.blurry_count,
            "overexposed": summary.overexposed_count,
            "underexposed": summary.underexposed_count,
            "low_contrast": summary.low_contrast_count,
        },
        "failed_images": [
            {
                "filename": r.filename,
                "issues": r.issues,
                "blur_score": r.blur_score,
                "brightness": r.brightness,
                "gps_deviation_m": r.gps_deviation_m,
            }
            for r in results if not r.pass_qc
        ],
    }
    if gcp_result:
        report_data["gcp"] = gcp_result

    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"QC詳細レポート: {json_path}")

    # テキストサマリー（現場確認用）
    txt_path = output_dir / "qc_summary.txt"
    verdict = "PASS" if summary.overall_pass else "FAIL"
    lines = [
        "=" * 50,
        f"  撮影データ QCチェック結果: [{verdict}]",
        "=" * 50,
        f"検査日時:     {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"対象枚数:     {summary.total_images}",
        f"合格:         {summary.passed_images}",
        f"不合格:       {summary.failed_images}",
        "",
        "--- 品質内訳 ---",
        f"ブレ検出:     {summary.blurry_count}枚",
        f"露出過多:     {summary.overexposed_count}枚",
        f"露出不足:     {summary.underexposed_count}枚",
        f"低コントラスト: {summary.low_contrast_count}枚",
        "",
    ]

    if summary.gps_checked > 0:
        lines += [
            "--- GPS整合性 ---",
            f"チェック済み: {summary.gps_checked}枚",
            f"合格:         {summary.gps_passed}枚",
            f"平均偏差:     {summary.avg_gps_deviation_m:.3f}m",
            "",
        ]

    if summary.coverage_ratio is not None:
        cov_verdict = "OK" if summary.coverage_pass else "NG"
        lines += [
            "--- カバレッジ ---",
            f"充足率:       {summary.coverage_ratio:.1%} [{cov_verdict}]",
            f"基準:         {QC.min_coverage_ratio:.0%}以上",
            "",
        ]

    if summary.failure_reasons:
        lines += ["--- 不合格理由 ---"]
        for reason in summary.failure_reasons:
            lines.append(f"  - {reason}")
        lines.append("")

    # 不合格画像一覧（現場で再撮影対象を特定するため）
    failed = [r for r in results if not r.pass_qc]
    if failed:
        lines += ["--- 再撮影対象 ---"]
        for r in failed[:20]:  # 最大20枚表示
            lines.append(f"  {r.filename}: {', '.join(r.issues)}")
        if len(failed) > 20:
            lines.append(f"  ... 他{len(failed) - 20}枚")

    lines += [
        "",
        "=" * 50,
        f"  総合判定: [{verdict}]",
        "=" * 50,
    ]

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"QCサマリー: {txt_path}")

    # 可視化（GPS分布図）
    _plot_photo_positions(results, output_dir / "photo_positions.png")


def _plot_photo_positions(results: List[ImageQCResult], output_path: Path):
    """撮影位置マップを生成"""
    coords_pass = [(r.exif_lon, r.exif_lat) for r in results if r.pass_qc and r.exif_lat]
    coords_fail = [(r.exif_lon, r.exif_lat) for r in results if not r.pass_qc and r.exif_lat]

    if not coords_pass and not coords_fail:
        return

    try:
        plt = _import_matplotlib()
        fig, ax = plt.subplots(1, 1, figsize=(10, 8))

        if coords_pass:
            px, py = zip(*coords_pass)
            ax.scatter(px, py, c="green", s=20, alpha=0.6, label=f"PASS ({len(coords_pass)})")
        if coords_fail:
            fx, fy = zip(*coords_fail)
            ax.scatter(fx, fy, c="red", s=40, marker="x", alpha=0.8, label=f"FAIL ({len(coords_fail)})")

        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title("Photo Positions & QC Results")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_aspect("equal")

        fig.tight_layout()
        fig.savefig(str(output_path), dpi=100, bbox_inches="tight")
        plt.close(fig)
        log.info(f"撮影位置マップ: {output_path}")
    except Exception as e:
        log.warning(f"位置マップ生成エラー: {e}")


# =========================================================================
# メイン
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ドローン撮影データ 現場QCチェック",
    )
    parser.add_argument(
        "--image-dir", "-d", required=True,
        help="撮影画像のディレクトリパス",
    )
    parser.add_argument(
        "--gps-log", "-g",
        help="フライトGPSログCSV",
    )
    parser.add_argument(
        "--boundary", "-b",
        help="設計範囲ファイル (GeoJSON/WKT)",
    )
    parser.add_argument(
        "--gcp",
        help="GCP設計座標CSV (id,x,y,z)",
    )
    parser.add_argument(
        "--gcp-measured",
        help="GCP計測値CSV（Metashape出力等）",
    )
    parser.add_argument(
        "--output", "-o",
        help="レポート出力ディレクトリ",
    )

    args = parser.parse_args()

    summary = run_qc(
        image_dir=args.image_dir,
        gps_log=args.gps_log,
        boundary=args.boundary,
        gcp_file=args.gcp,
        gcp_measured=args.gcp_measured,
        output_dir=args.output or f"./qc_report_{datetime.now().strftime('%Y%m%d_%H%M')}",
    )

    # 結果表示
    verdict = "PASS" if summary.overall_pass else "FAIL"
    log.info(f"=== QC結果: [{verdict}] ===")
    log.info(f"合格: {summary.passed_images}/{summary.total_images}枚")
    if summary.failure_reasons:
        for reason in summary.failure_reasons:
            log.warning(f"  {reason}")

    # 終了コード（CI/CD連携用）
    sys.exit(0 if summary.overall_pass else 1)


if __name__ == "__main__":
    main()
