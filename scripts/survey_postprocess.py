#!/usr/bin/env python3
"""
survey_postprocess.py - Metashape出力後の後工程自動化

機能:
  1. PLY/LAS点群ファイルの読み込み・前処理
  2. 土量計算（2時点の差分メッシュ → 体積算出）
  3. 断面図生成（指定ラインでの断面プロファイル）
  4. 納品フォルダ自動整理（日付/現場名/データ種別）
  5. レポートPDF生成

使用方法:
  python survey_postprocess.py --config project_config.json
  python survey_postprocess.py --baseline before.las --current after.las --site "名古屋港"
  python survey_postprocess.py --input point_cloud.las --cross-section "0,0,100,0" --site "現場名"

依存: Open3D, laspy, numpy, scipy, matplotlib, reportlab, pyproj
"""

import argparse
import json
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np

# ---- 遅延インポート（重いライブラリは必要時のみ） ----
def _import_laspy():
    import laspy
    return laspy

def _import_open3d():
    import open3d as o3d
    return o3d

def _import_matplotlib():
    import matplotlib
    matplotlib.use("Agg")  # GUI不要
    import matplotlib.pyplot as plt
    return plt

# ---- ローカル設定 ----
sys.path.insert(0, os.path.dirname(__file__))
from survey_config import (
    VOLUME, CROSS_SECTION, DELIVERY, DEFAULT_EPSG, WGS84_EPSG,
    get_delivery_path, load_project_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("survey_postprocess")


# =========================================================================
# 1. 点群I/O
# =========================================================================

def load_point_cloud(filepath: str) -> np.ndarray:
    """
    LAS/LAZ/PLY点群を読み込み、Nx3 numpy配列（X,Y,Z）を返す。
    """
    path = Path(filepath)
    ext = path.suffix.lower()

    if ext in (".las", ".laz"):
        laspy = _import_laspy()
        with laspy.open(str(path)) as f:
            las = f.read()
        points = np.vstack([las.x, las.y, las.z]).T
        log.info(f"LAS読み込み完了: {len(points):,}点 ({path.name})")
        return points

    elif ext == ".ply":
        o3d = _import_open3d()
        pcd = o3d.io.read_point_cloud(str(path))
        points = np.asarray(pcd.points)
        log.info(f"PLY読み込み完了: {len(points):,}点 ({path.name})")
        return points

    else:
        raise ValueError(f"未対応のファイル形式: {ext} (LAS/LAZ/PLYのみ対応)")


def save_point_cloud_las(points: np.ndarray, filepath: str, epsg: int = DEFAULT_EPSG):
    """Nx3配列をLASファイルとして保存"""
    laspy = _import_laspy()
    header = laspy.LasHeader(point_format=0, version="1.4")
    # CRSをVLRに記録
    header.offsets = np.min(points, axis=0)
    header.scales = np.array([0.001, 0.001, 0.001])

    las = laspy.LasData(header)
    las.x = points[:, 0]
    las.y = points[:, 1]
    las.z = points[:, 2]
    las.write(filepath)
    log.info(f"LAS保存完了: {filepath}")


# =========================================================================
# 2. 土量計算（差分解析）
# =========================================================================

def compute_volume_grid(
    baseline_points: np.ndarray,
    current_points: np.ndarray,
    resolution: float = None,
) -> dict:
    """
    グリッドベースの土量計算。

    2時点の点群をグリッドに投影し、各セルのZ平均の差分から体積を算出。

    Args:
        baseline_points: 基準時点のNx3点群
        current_points:  比較時点のNx3点群
        resolution:      グリッド解像度（m）。Noneならconfig値を使用

    Returns:
        {
            "cut_volume_m3": float,    # 切土量
            "fill_volume_m3": float,   # 盛土量
            "net_volume_m3": float,    # 差引（正=盛土超過）
            "grid_resolution_m": float,
            "grid_shape": (rows, cols),
            "diff_grid": np.ndarray,   # 差分グリッド（可視化用）
            "extent": (xmin, xmax, ymin, ymax),
        }
    """
    from scipy.stats import binned_statistic_2d

    res = resolution or VOLUME.grid_resolution_m
    log.info(f"土量計算開始 (グリッド解像度: {res}m)")

    # 共通の範囲を決定
    all_points = np.vstack([baseline_points[:, :2], current_points[:, :2]])
    xmin, ymin = all_points.min(axis=0) - res
    xmax, ymax = all_points.max(axis=0) + res

    # グリッドビン定義
    x_bins = np.arange(xmin, xmax + res, res)
    y_bins = np.arange(ymin, ymax + res, res)

    # 各時点の高さグリッド（平均Z）
    baseline_grid, _, _, _ = binned_statistic_2d(
        baseline_points[:, 0], baseline_points[:, 1], baseline_points[:, 2],
        statistic="mean", bins=[x_bins, y_bins],
    )
    current_grid, _, _, _ = binned_statistic_2d(
        current_points[:, 0], current_points[:, 1], current_points[:, 2],
        statistic="mean", bins=[x_bins, y_bins],
    )

    # NaN（データなし）を除外して差分計算
    valid = ~(np.isnan(baseline_grid) | np.isnan(current_grid))
    diff = np.full_like(baseline_grid, np.nan)
    diff[valid] = current_grid[valid] - baseline_grid[valid]

    cell_area = res * res
    cut_cells = diff[valid & (diff < 0)]
    fill_cells = diff[valid & (diff > 0)]

    cut_volume = float(np.abs(cut_cells).sum() * cell_area)
    fill_volume = float(fill_cells.sum() * cell_area)
    net_volume = fill_volume - cut_volume

    result = {
        "cut_volume_m3": round(cut_volume, 3),
        "fill_volume_m3": round(fill_volume, 3),
        "net_volume_m3": round(net_volume, 3),
        "grid_resolution_m": res,
        "grid_shape": baseline_grid.shape,
        "diff_grid": diff,
        "extent": (xmin, xmax, ymin, ymax),
        "valid_cell_count": int(valid.sum()),
        "total_cell_count": int(valid.size),
    }

    log.info(
        f"土量計算完了: 切土={cut_volume:.1f}m3, "
        f"盛土={fill_volume:.1f}m3, 差引={net_volume:.1f}m3"
    )
    return result


def plot_volume_diff(volume_result: dict, output_path: str, title: str = "土量差分マップ"):
    """差分グリッドをヒートマップとして可視化"""
    plt = _import_matplotlib()

    diff = volume_result["diff_grid"]
    extent = volume_result["extent"]

    fig, ax = plt.subplots(1, 1, figsize=(12, 10))
    # 差分値の最大絶対値で対称カラースケール
    vmax = np.nanmax(np.abs(diff))
    if vmax == 0:
        vmax = 1.0

    im = ax.imshow(
        diff.T, origin="lower",
        extent=[extent[0], extent[1], extent[2], extent[3]],
        cmap="RdBu_r", vmin=-vmax, vmax=vmax,
        aspect="equal",
    )
    cbar = plt.colorbar(im, ax=ax, label="高さ変化 (m)")
    ax.set_title(title, fontsize=14)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")

    # 凡例テキスト
    info_text = (
        f"切土: {volume_result['cut_volume_m3']:.1f} m³\n"
        f"盛土: {volume_result['fill_volume_m3']:.1f} m³\n"
        f"差引: {volume_result['net_volume_m3']:.1f} m³\n"
        f"解像度: {volume_result['grid_resolution_m']}m"
    )
    ax.text(
        0.02, 0.98, info_text, transform=ax.transAxes,
        fontsize=10, verticalalignment="top",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info(f"差分マップ保存: {output_path}")


# =========================================================================
# 3. 断面図生成
# =========================================================================

def extract_cross_section(
    points: np.ndarray,
    line_start: Tuple[float, float],
    line_end: Tuple[float, float],
    buffer_width: float = None,
    interval: float = None,
) -> dict:
    """
    指定ライン沿いの断面プロファイルを抽出。

    Args:
        points:       Nx3点群
        line_start:   断面線の始点 (x, y)
        line_end:     断面線の終点 (x, y)
        buffer_width: 断面線からの採用幅（m）
        interval:     サンプリング間隔（m）

    Returns:
        {
            "distances": np.ndarray,  # 始点からの距離
            "elevations": np.ndarray, # 各位置の高さ
            "line_start": (x, y),
            "line_end": (x, y),
            "line_length_m": float,
        }
    """
    buf = buffer_width or CROSS_SECTION.buffer_width_m
    intv = interval or CROSS_SECTION.interval_m

    start = np.array(line_start, dtype=float)
    end = np.array(line_end, dtype=float)
    line_vec = end - start
    line_length = np.linalg.norm(line_vec)
    line_unit = line_vec / line_length

    # 各点の断面線への射影
    pts_2d = points[:, :2]
    rel = pts_2d - start
    proj_dist = rel @ line_unit                         # 断面線上の位置
    perp_dist = np.abs(rel @ np.array([-line_unit[1], line_unit[0]]))  # 断面線からの距離

    # バッファ内かつ断面線の範囲内の点を抽出
    mask = (perp_dist <= buf) & (proj_dist >= 0) & (proj_dist <= line_length)
    selected_dist = proj_dist[mask]
    selected_z = points[mask, 2]

    if len(selected_z) == 0:
        log.warning("断面線のバッファ内に点がありません")
        return {
            "distances": np.array([]),
            "elevations": np.array([]),
            "line_start": tuple(start),
            "line_end": tuple(end),
            "line_length_m": float(line_length),
        }

    # 等間隔ビンで平均高さを算出
    bins = np.arange(0, line_length + intv, intv)
    bin_indices = np.digitize(selected_dist, bins) - 1
    distances = []
    elevations = []
    for i in range(len(bins) - 1):
        in_bin = selected_z[bin_indices == i]
        if len(in_bin) > 0:
            distances.append((bins[i] + bins[i + 1]) / 2)
            elevations.append(float(np.mean(in_bin)))

    log.info(f"断面抽出完了: {len(distances)}サンプル / 全長{line_length:.1f}m")
    return {
        "distances": np.array(distances),
        "elevations": np.array(elevations),
        "line_start": tuple(start),
        "line_end": tuple(end),
        "line_length_m": float(line_length),
    }


def plot_cross_section(
    sections: List[dict],
    labels: List[str],
    output_path: str,
    title: str = "断面図",
):
    """1本以上の断面プロファイルを重ねて描画"""
    plt = _import_matplotlib()

    fig, ax = plt.subplots(
        1, 1,
        figsize=(CROSS_SECTION.figure_width_inch, CROSS_SECTION.figure_height_inch),
    )

    colors = plt.cm.tab10.colors
    for i, (sec, label) in enumerate(zip(sections, labels)):
        if len(sec["distances"]) == 0:
            continue
        ax.plot(
            sec["distances"], sec["elevations"],
            label=label, color=colors[i % len(colors)], linewidth=1.5,
        )

    ax.set_xlabel("距離 (m)", fontsize=12)
    ax.set_ylabel("標高 (m)", fontsize=12)
    ax.set_title(title, fontsize=14)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=CROSS_SECTION.output_dpi, bbox_inches="tight")
    plt.close(fig)
    log.info(f"断面図保存: {output_path}")


# =========================================================================
# 4. 納品フォルダ自動整理
# =========================================================================

def organize_delivery_folder(
    site_name: str,
    date_str: str = None,
    source_files: dict = None,
) -> Path:
    """
    納品フォルダを作成し、ファイルを配置。

    Args:
        site_name:     現場名
        date_str:      日付文字列（YYYY-MM-DD）。Noneなら今日
        source_files:  {"subfolder_key": [filepath, ...]} の辞書
                       例: {"02_pointcloud": ["output.las"], "06_report": ["report.pdf"]}

    Returns:
        納品フォルダのルートPath
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    delivery_root = get_delivery_path(site_name, date_str)

    # サブフォルダ作成
    for folder_key, description in DELIVERY.folder_structure.items():
        folder_path = delivery_root / folder_key
        folder_path.mkdir(parents=True, exist_ok=True)
        # READMEで内容を記載
        readme = folder_path / "README.txt"
        if not readme.exists():
            readme.write_text(f"{folder_key}: {description}\n", encoding="utf-8")

    # ファイルコピー
    if source_files:
        for subfolder, files in source_files.items():
            dest_dir = delivery_root / subfolder
            if not dest_dir.exists():
                log.warning(f"未定義のサブフォルダ: {subfolder}")
                dest_dir.mkdir(parents=True, exist_ok=True)
            for src in files:
                src_path = Path(src)
                if src_path.exists():
                    dest = dest_dir / src_path.name
                    shutil.copy2(str(src_path), str(dest))
                    log.info(f"コピー: {src_path.name} → {subfolder}/")
                else:
                    log.warning(f"ファイルが見つかりません: {src}")

    log.info(f"納品フォルダ作成完了: {delivery_root}")
    return delivery_root


# =========================================================================
# 5. レポートPDF生成
# =========================================================================

def generate_report_pdf(
    output_path: str,
    site_name: str,
    date_str: str,
    volume_result: dict = None,
    section_images: List[str] = None,
    diff_map_image: str = None,
    qc_summary: dict = None,
):
    """
    測量後処理レポートをPDFで生成。

    reportlabが無い場合はテキストレポートにフォールバック。
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
            Table, TableStyle,
        )
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        _generate_pdf_reportlab(
            output_path, site_name, date_str,
            volume_result, section_images, diff_map_image, qc_summary,
        )
    except ImportError:
        log.warning("reportlab未インストール。テキストレポートにフォールバック")
        txt_path = output_path.replace(".pdf", ".txt")
        _generate_text_report(
            txt_path, site_name, date_str,
            volume_result, section_images, diff_map_image, qc_summary,
        )


def _generate_pdf_reportlab(
    output_path, site_name, date_str,
    volume_result, section_images, diff_map_image, qc_summary,
):
    """reportlabによるPDF生成"""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
        Table, TableStyle,
    )
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 日本語フォント登録（利用可能な場合）
    jp_font = None
    for font_path in [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
    ]:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("JPFont", font_path))
                jp_font = "JPFont"
                break
            except Exception:
                continue

    doc = SimpleDocTemplate(output_path, pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # タイトル
    story.append(Paragraph(
        f"Drone Survey Post-Processing Report",
        styles["Title"],
    ))
    story.append(Paragraph(
        f"Site: {site_name} / Date: {date_str}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 10 * mm))

    # 土量計算結果
    if volume_result:
        story.append(Paragraph("Volume Calculation Results", styles["Heading2"]))
        vol_data = [
            ["Item", "Value"],
            ["Cut Volume", f"{volume_result['cut_volume_m3']:.3f} m3"],
            ["Fill Volume", f"{volume_result['fill_volume_m3']:.3f} m3"],
            ["Net Volume", f"{volume_result['net_volume_m3']:.3f} m3"],
            ["Grid Resolution", f"{volume_result['grid_resolution_m']} m"],
            ["Valid Cells", f"{volume_result.get('valid_cell_count', 'N/A'):,}"],
        ]
        t = Table(vol_data, colWidths=[60 * mm, 80 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("FONTSIZE", (0, 0), (-1, -1), 10),
        ]))
        story.append(t)
        story.append(Spacer(1, 5 * mm))

    # 差分マップ画像
    if diff_map_image and os.path.exists(diff_map_image):
        story.append(Paragraph("Volume Difference Map", styles["Heading2"]))
        story.append(RLImage(diff_map_image, width=160 * mm, height=130 * mm))
        story.append(Spacer(1, 5 * mm))

    # 断面図
    if section_images:
        story.append(Paragraph("Cross Sections", styles["Heading2"]))
        for img_path in section_images:
            if os.path.exists(img_path):
                story.append(RLImage(img_path, width=160 * mm, height=80 * mm))
                story.append(Spacer(1, 3 * mm))

    # QCサマリー
    if qc_summary:
        story.append(Paragraph("QC Summary", styles["Heading2"]))
        for key, val in qc_summary.items():
            story.append(Paragraph(f"{key}: {val}", styles["Normal"]))

    # 生成情報
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} by TAS Survey Automation",
        styles["Normal"],
    ))

    doc.build(story)
    log.info(f"PDFレポート生成完了: {output_path}")


def _generate_text_report(
    output_path, site_name, date_str,
    volume_result, section_images, diff_map_image, qc_summary,
):
    """テキストフォールバックレポート"""
    lines = [
        "=" * 60,
        "ドローン測量 後処理レポート",
        "=" * 60,
        f"現場名: {site_name}",
        f"日付:   {date_str}",
        f"生成:   {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    if volume_result:
        lines += [
            "--- 土量計算結果 ---",
            f"切土量:     {volume_result['cut_volume_m3']:.3f} m3",
            f"盛土量:     {volume_result['fill_volume_m3']:.3f} m3",
            f"差引:       {volume_result['net_volume_m3']:.3f} m3",
            f"グリッド:   {volume_result['grid_resolution_m']}m",
            f"有効セル:   {volume_result.get('valid_cell_count', 'N/A')}",
            "",
        ]

    if section_images:
        lines += ["--- 断面図 ---"]
        for img in section_images:
            lines.append(f"  {img}")
        lines.append("")

    if qc_summary:
        lines += ["--- QCサマリー ---"]
        for k, v in qc_summary.items():
            lines.append(f"  {k}: {v}")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    log.info(f"テキストレポート生成: {output_path}")


# =========================================================================
# メインパイプライン
# =========================================================================

def run_pipeline(args):
    """後工程パイプラインを実行"""
    site_name = args.site or "unnamed_site"
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    output_dir = Path(args.output or f"./output/{site_name}_{date_str}")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # ---------- 土量計算 ----------
    if args.baseline and args.current:
        log.info("=== 土量計算 ===")
        baseline = load_point_cloud(args.baseline)
        current = load_point_cloud(args.current)

        vol = compute_volume_grid(
            baseline, current,
            resolution=args.resolution,
        )
        results["volume"] = vol

        # 差分マップ
        diff_map_path = str(output_dir / "volume_diff_map.png")
        plot_volume_diff(vol, diff_map_path, title=f"{site_name} 土量差分")
        results["diff_map_image"] = diff_map_path

    # ---------- 断面図 ----------
    section_images = []
    if args.cross_section and (args.input or args.current):
        log.info("=== 断面図生成 ===")
        pc_path = args.input or args.current
        points = load_point_cloud(pc_path) if "current" not in results.get("volume", {}) else current

        # 断面線パース: "x1,y1,x2,y2" or 複数 "x1,y1,x2,y2;x3,y3,x4,y4"
        for i, line_str in enumerate(args.cross_section.split(";")):
            coords = [float(c) for c in line_str.strip().split(",")]
            if len(coords) != 4:
                log.error(f"断面線の座標が不正: {line_str} (x1,y1,x2,y2が必要)")
                continue

            section = extract_cross_section(
                points,
                line_start=(coords[0], coords[1]),
                line_end=(coords[2], coords[3]),
            )

            sec_path = str(output_dir / f"cross_section_{i + 1}.png")
            plot_cross_section(
                [section], [f"断面{i + 1}"],
                sec_path,
                title=f"{site_name} 断面図 {i + 1}",
            )
            section_images.append(sec_path)

    # ---------- 単体入力の点群処理（断面のみ） ----------
    if args.input and not args.cross_section:
        log.info("=== 点群統計 ===")
        points = load_point_cloud(args.input)
        log.info(f"点数: {len(points):,}")
        log.info(f"XYZ範囲: X[{points[:,0].min():.3f}, {points[:,0].max():.3f}] "
                 f"Y[{points[:,1].min():.3f}, {points[:,1].max():.3f}] "
                 f"Z[{points[:,2].min():.3f}, {points[:,2].max():.3f}]")

    # ---------- レポート生成 ----------
    report_path = str(output_dir / "report.pdf")
    generate_report_pdf(
        report_path, site_name, date_str,
        volume_result=results.get("volume"),
        section_images=section_images,
        diff_map_image=results.get("diff_map_image"),
    )

    # ---------- 納品フォルダ整理 ----------
    if args.organize:
        log.info("=== 納品フォルダ整理 ===")
        source_files = {}
        if args.input:
            source_files["02_pointcloud"] = [args.input]
        if args.baseline:
            source_files["02_pointcloud"] = source_files.get("02_pointcloud", []) + [args.baseline]
        if args.current:
            source_files.setdefault("02_pointcloud", []).append(args.current)

        # 生成物を配置
        source_files["06_report"] = [report_path]
        if results.get("diff_map_image"):
            source_files["04_volume"] = [results["diff_map_image"]]
        if section_images:
            source_files["05_crosssection"] = section_images

        delivery_root = organize_delivery_folder(site_name, date_str, source_files)
        log.info(f"納品フォルダ: {delivery_root}")

    log.info("=== パイプライン完了 ===")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="ドローン測量 後工程自動化（土量計算・断面図・レポート）",
    )
    parser.add_argument("--config", help="プロジェクト設定JSON")
    parser.add_argument("--baseline", help="基準時点の点群ファイル (LAS/PLY)")
    parser.add_argument("--current", help="比較時点の点群ファイル (LAS/PLY)")
    parser.add_argument("--input", "-i", help="単体点群ファイル（断面図用）")
    parser.add_argument("--site", "-s", help="現場名")
    parser.add_argument("--date", "-d", help="日付 (YYYY-MM-DD)")
    parser.add_argument("--output", "-o", help="出力ディレクトリ")
    parser.add_argument("--resolution", type=float, help="グリッド解像度 (m)")
    parser.add_argument(
        "--cross-section",
        help="断面線座標 'x1,y1,x2,y2' (複数は ';' 区切り)",
    )
    parser.add_argument(
        "--organize", action="store_true",
        help="納品フォルダ自動整理を実行",
    )

    args = parser.parse_args()

    # 設定ファイルからの読み込み
    if args.config:
        cfg = load_project_config(args.config)
        if not args.site:
            args.site = cfg.get("site_name")
        if not args.baseline:
            args.baseline = cfg.get("baseline_file")
        if not args.current:
            args.current = cfg.get("current_file")

    if not (args.baseline or args.current or args.input):
        parser.error("--baseline/--current または --input が必要です")

    run_pipeline(args)


if __name__ == "__main__":
    main()
