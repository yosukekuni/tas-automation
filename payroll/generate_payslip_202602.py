#!/usr/bin/env python3
"""
給与明細書 PDF生成 - 新美光 2026年2月度（最終版）
東海エアサービス株式会社
"""

import os
import sys
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError:
    print("ERROR: reportlab が未インストールです。 pip install reportlab")
    sys.exit(1)

# ── 定数 ──
PAGE_W, PAGE_H = A4
MARGIN_L = 18 * mm
MARGIN_R = 18 * mm
MARGIN_T = 18 * mm
MARGIN_B = 15 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

FONT_REGULAR_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicR.ttc"
FONT_BOLD_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicB.ttc"
FONT_R = "BIZUDGothic"
FONT_B = "BIZUDGothicBold"

COLOR_NAVY = colors.HexColor("#1a365d")
COLOR_LIGHT_BG = colors.HexColor("#f7fafc")
COLOR_ACCENT = colors.HexColor("#2b6cb0")
COLOR_BORDER = colors.HexColor("#cbd5e0")
COLOR_SUBTLE = colors.HexColor("#718096")


def register_fonts():
    pdfmetrics.registerFont(TTFont(FONT_R, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_B, FONT_BOLD_PATH, subfontIndex=0))


def fmt_yen(amount) -> str:
    if isinstance(amount, int):
        return f"\u00a5{amount:,}"
    return str(amount)


def draw_table_header(c, x, y, widths, headers, height=7*mm):
    """Draw a table header row with navy background."""
    c.setFillColor(COLOR_NAVY)
    c.rect(x, y - height, sum(widths), height, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_B, 8)
    cx = x
    for hdr, w in zip(headers, widths):
        c.drawCentredString(cx + w / 2, y - height + 2.2 * mm, hdr)
        cx += w
    c.setFillColor(colors.black)
    return y - height


def draw_table_row(c, x, y, widths, values, height=6.5*mm, idx=0, aligns=None, font_size=8):
    """Draw a table data row. aligns: list of 'l','c','r'."""
    if aligns is None:
        aligns = ['c'] * len(widths)
    if idx % 2 == 1:
        c.setFillColor(COLOR_LIGHT_BG)
        c.rect(x, y - height, sum(widths), height, stroke=0, fill=1)
        c.setFillColor(colors.black)
    # bottom border
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.3)
    c.line(x, y - height, x + sum(widths), y - height)

    c.setFont(FONT_R, font_size)
    cx = x
    for val, w, align in zip(values, widths, aligns):
        ty = y - height + 2 * mm
        if align == 'r':
            c.drawRightString(cx + w - 2 * mm, ty, str(val))
        elif align == 'c':
            c.drawCentredString(cx + w / 2, ty, str(val))
        else:
            c.drawString(cx + 2 * mm, ty, str(val))
        cx += w
    return y - height


def draw_section_title(c, x, y, title, amount_str=None):
    """Draw a section title with light background."""
    h = 7 * mm
    c.setFillColor(COLOR_LIGHT_BG)
    c.rect(x, y - h, CONTENT_W, h, stroke=0, fill=1)
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.2)
    c.line(x, y, x, y - h)  # left accent bar
    c.setFillColor(COLOR_NAVY)
    c.setFont(FONT_B, 10)
    c.drawString(x + 3 * mm, y - h + 2.2 * mm, title)
    if amount_str:
        c.setFont(FONT_B, 10)
        c.drawRightString(x + CONTENT_W - 3 * mm, y - h + 2.2 * mm, amount_str)
    c.setFillColor(colors.black)
    return y - h


def generate_pdf(output_path: str):
    register_fonts()
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle("給与明細書_新美光_202602")
    c.setAuthor("東海エアサービス株式会社")

    y = PAGE_H - MARGIN_T
    lx = MARGIN_L

    # ═══ ヘッダー ═══
    header_h = 22 * mm
    c.setFillColor(COLOR_NAVY)
    c.rect(0, y - header_h + 8 * mm, PAGE_W, header_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_B, 22)
    c.drawCentredString(PAGE_W / 2, y - 5 * mm, "給 与 明 細 書")
    c.setFont(FONT_R, 9)
    c.drawCentredString(PAGE_W / 2, y - 12 * mm, "東海エアサービス株式会社")
    c.setFont(FONT_R, 7.5)
    c.drawCentredString(PAGE_W / 2, y - 16.5 * mm, "\u3012465-0077 愛知県名古屋市名東区植園町1-9-3 LM1205")
    c.setFillColor(colors.black)
    y -= header_h + 4 * mm

    # ═══ 受取人情報 ═══
    c.setFont(FONT_B, 13)
    c.drawString(lx, y, "新美 光 様")
    y -= 2.5 * mm
    c.setStrokeColor(COLOR_NAVY)
    c.setLineWidth(1)
    c.line(lx, y, lx + 55 * mm, y)
    y -= 6 * mm

    c.setFont(FONT_R, 9)
    c.drawString(lx, y, "対象期間: 2026年2月1日 〜 2月28日")
    c.drawString(lx + 90 * mm, y, "支払日: 2026年3月16日")
    y -= 10 * mm

    # ═══ 差引支払額（大きく表示）═══
    box_h = 16 * mm
    c.setFillColor(colors.HexColor("#ebf4ff"))
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(2)
    c.roundRect(lx, y - box_h, CONTENT_W, box_h, 3, stroke=1, fill=1)

    c.setFillColor(COLOR_NAVY)
    c.setFont(FONT_B, 11)
    c.drawString(lx + 5 * mm, y - box_h + 5.5 * mm, "差引支払額")
    c.setFillColor(COLOR_ACCENT)
    c.setFont(FONT_B, 20)
    c.drawRightString(lx + CONTENT_W - 8 * mm, y - box_h + 4.5 * mm, "\u00a5132,160")
    c.setFillColor(COLOR_SUBTLE)
    c.setFont(FONT_R, 7)
    c.drawRightString(lx + CONTENT_W - 8 * mm, y - box_h + 12 * mm, "\u203b2/25公共交通機関費は確認後に追加精算")
    c.setFillColor(colors.black)
    y -= box_h + 6 * mm

    # ═══ I. 基本報酬（現場）═══
    y = draw_section_title(c, lx, y, "I. 基本報酬（現場）", "\u00a5111,000")
    y -= 1 * mm

    w1 = [14*mm, CONTENT_W - 14*mm - 22*mm - 22*mm, 22*mm, 22*mm]
    y = draw_table_header(c, lx, y, w1, ["日付", "業務内容", "区分", "金額"])

    field_items = [
        ("2/2", "尾鷲港新田線 公共測量", "単独撮影", "\u00a515,000"),
        ("2/5", "営業訪問  09:23-17:39", "フル日給", "\u00a516,000"),
        ("2/12", "営業訪問  08:19-16:23", "フル日給", "\u00a516,000"),
        ("2/17", "営業訪問  09:16-16:59", "フル日給", "\u00a516,000"),
        ("2/20", "営業訪問  08:46-16:55", "フル日給", "\u00a516,000"),
        ("2/24", "営業訪問  08:58-16:55", "フル日給", "\u00a516,000"),
        ("2/26", "営業訪問  09:00-16:47", "フル日給", "\u00a516,000"),
    ]
    for idx, (dt, desc, cat, amt) in enumerate(field_items):
        y = draw_table_row(c, lx, y, w1, [dt, desc, cat, amt], idx=idx,
                           aligns=['c', 'l', 'c', 'r'])
    y -= 4 * mm

    # ═══ II. 基本報酬（内業）═══
    y = draw_section_title(c, lx, y, "II. 基本報酬（内業）", "\u00a510,560")
    y -= 1 * mm

    w2 = [CONTENT_W - 18*mm - 20*mm - 22*mm, 18*mm, 20*mm, 22*mm]
    y = draw_table_header(c, lx, y, w2, ["内容", "箇所数", "単価", "金額"])
    y = draw_table_row(c, lx, y, w2,
                       ["点群処理Lv2（尾鷲港新田線）", "1", "\u00a510,560", "\u00a510,560"],
                       idx=0, aligns=['l', 'c', 'r', 'r'])
    y -= 4 * mm

    # ═══ III. 諸手当 ═══
    y = draw_section_title(c, lx, y, "III. 諸手当（課税）", "\u00a57,000")
    y -= 1 * mm

    w3 = [CONTENT_W - 18*mm - 20*mm - 22*mm, 18*mm, 20*mm, 22*mm]
    y = draw_table_header(c, lx, y, w3, ["内容", "日数", "単価", "金額"])
    y = draw_table_row(c, lx, y, w3,
                       ["車両手当（フル）", "7日", "\u00a51,000", "\u00a57,000"],
                       idx=0, aligns=['l', 'c', 'r', 'r'])
    y -= 4 * mm

    # ═══ IV. 経費精算（非課税）═══
    y = draw_section_title(c, lx, y, "IV. 経費精算（非課税）", "\u00a53,600")
    y -= 1 * mm

    w4 = [14*mm, CONTENT_W - 14*mm - 18*mm - 22*mm, 18*mm, 22*mm]
    y = draw_table_header(c, lx, y, w4, ["日付", "内容", "距離", "金額"])

    expense_items = [
        ("2/17", "営業（ガソリン代）", "89km", "\u00a51,335"),
        ("2/20", "営業（ガソリン代）", "79km", "\u00a51,185"),
        ("2/24", "営業（ガソリン代）", "8km", "\u00a5120"),
        ("2/26", "三河エリア営業（ガソリン代）", "64km", "\u00a5960"),
        ("2/25", "名古屋市内営業（公共交通機関）", "\u2014", "要確認"),
    ]
    for idx, (dt, desc, dist, amt) in enumerate(expense_items):
        y = draw_table_row(c, lx, y, w4, [dt, desc, dist, amt], idx=idx,
                           aligns=['c', 'l', 'c', 'r'], font_size=7.5)
    y -= 3 * mm

    # ═══ 集計 ═══
    y -= 1 * mm
    summary_w = 72 * mm
    sx = lx + CONTENT_W - summary_w
    label_x = sx + 4 * mm
    val_x = sx + summary_w - 4 * mm
    row_h = 7.5 * mm

    # 総支給額
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.5)
    c.line(sx, y - row_h, sx + summary_w, y - row_h)
    c.setFont(FONT_R, 9)
    c.drawString(label_x, y - row_h + 2.5 * mm, "総支給額")
    c.drawRightString(val_x, y - row_h + 2.5 * mm, "\u00a5132,160")
    y -= row_h

    # 課税対象額
    c.line(sx, y - row_h, sx + summary_w, y - row_h)
    c.setFont(FONT_R, 8)
    c.setFillColor(COLOR_SUBTLE)
    c.drawString(label_x, y - row_h + 2.5 * mm, "課税対象額（I+II+III）")
    c.drawRightString(val_x, y - row_h + 2.5 * mm, "\u00a5128,560")
    c.setFillColor(colors.black)
    y -= row_h

    # 源泉徴収
    c.line(sx, y - row_h, sx + summary_w, y - row_h)
    c.setFont(FONT_R, 9)
    c.drawString(label_x, y - row_h + 2.5 * mm, "源泉徴収税（甲欄・扶養1名）")
    c.drawRightString(val_x, y - row_h + 2.5 * mm, "\u00a50")
    y -= row_h

    # 差引支払額
    big_h = 9 * mm
    c.setFillColor(colors.HexColor("#ebf4ff"))
    c.setStrokeColor(COLOR_ACCENT)
    c.setLineWidth(1.5)
    c.roundRect(sx, y - big_h, summary_w, big_h, 3, stroke=1, fill=1)
    c.setFillColor(COLOR_NAVY)
    c.setFont(FONT_B, 11)
    c.drawString(label_x, y - big_h + 3 * mm, "差引支払額")
    c.setFillColor(COLOR_ACCENT)
    c.setFont(FONT_B, 13)
    c.drawRightString(val_x, y - big_h + 3 * mm, "\u00a5132,160")
    c.setFillColor(colors.black)
    y -= big_h

    # ═══ 備考 ═══
    y -= 4 * mm
    c.setFont(FONT_B, 8)
    c.setFillColor(COLOR_NAVY)
    c.drawString(lx, y, "備考")
    c.setFillColor(colors.black)
    y -= 1.5 * mm
    c.setStrokeColor(COLOR_BORDER)
    c.setLineWidth(0.5)
    c.line(lx, y, lx + CONTENT_W, y)
    y -= 4 * mm
    c.setFont(FONT_R, 7)
    c.drawString(lx + 2 * mm, y, "\u30fb 2/25公共交通機関費は領収書確認後に追加精算。2/5・2/12は経費申請なし（提出漏れの場合は追加対応）。")
    y -= 3.5 * mm
    c.drawString(lx + 2 * mm, y, "\u30fb 2/25分の高速代・駐車場代は3月経費精算で申請済みのため3月計上。")

    # ═══ フッター ═══
    footer_y = 8 * mm
    c.setFont(FONT_R, 6.5)
    c.setFillColor(COLOR_SUBTLE)
    c.drawCentredString(PAGE_W / 2, footer_y + 3 * mm,
                        "東海エアサービス株式会社 | info@tokaiair.com | https://www.tokaiair.com")
    c.drawCentredString(PAGE_W / 2, footer_y,
                        "本書類は社外秘です。第三者への開示を禁じます。")
    c.setFillColor(colors.black)

    c.save()
    print(f"PDF生成完了: {output_path}")


if __name__ == "__main__":
    output = "/mnt/c/Users/USER/Documents/_data/tas-automation/payroll/給与明細_新美光_202602.pdf"
    generate_pdf(output)
