#!/usr/bin/env python3
"""
給与明細書 最終確定版 - 新美光 2026年2月度
経費精算全10件反映・差引支払額¥150,765

出力:
  1. CSV上書き
  2. PDF上書き（reportlab + BIZ UDゴシック）
  3. Google Sheets「給与明細：新美光」2602シート上書き
"""

import csv
import json
import os
import sys
from pathlib import Path

CSV_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/payroll/給与明細_新美光_2602_final.csv"
PDF_PATH = "/mnt/c/Users/USER/Documents/_data/tas-automation/payroll/給与明細_新美光_202602.pdf"
SA_JSON = "/mnt/c/Users/USER/Documents/_data/drive-organizer-489313-9230cf87e259.json"
SHEETS_ID = "1dJ2Yx2heeRU9gUnrAv3jrO00zrjxmt6Fo2CaaKnwI_w"


def generate_csv():
    rows = [
        ["新美 光様 2026年2月度 給与明細（最終確定版）", "", "", ""],
        ["", "", "", ""],
        ["支払予定日： 2026年3月16日 扶養親族等： 1名（配偶者）", "", "", ""],
        ["", "", "", ""],
        ["項目", "詳細・内訳", "金額（円）", "根拠・備考"],
        ["I. 基本報酬（現場）", "", "111,000", ""],
        ["フル日給", "16,000円 × 6日", "96,000", "2/5, 2/12, 2/17, 2/20, 2/24, 2/26（Lark打刻確認済み）"],
        ["単独撮影（特約）", "15,000円 × 1日", "15,000", "2/2 尾鷲港新田線（本人機体・出張申請ベース）"],
        ["II. 基本報酬（内業）", "1箇所分", "10,560", ""],
        ["点群処理（Lv2）", "10,560円 × 1箇所", "10,560", "尾鷲港新田線（成果レポート2/20提出・K6修正2/21）個人1.1×複数0.8適用"],
        ["III. 諸手当（課税）", "", "7,000", ""],
        ["車両手当（フル）", "1,000円 × 7日", "7,000", "2/2, 2/5, 2/12, 2/17, 2/20, 2/24, 2/26"],
        ["IV. 経費精算（非課税）", "", "22,205", "Lark承認管理エクスポート全10件"],
        ["", "", "", ""],
        ["【ガソリン代精算】", "809km × 15円/km", "12,135", ""],
        ["(1) 202602020001 2/2 尾鷲港測量 交通費", "421km", "6,315", ""],
        ["(2) 202602050001 2/5 昭和区ロケハン+営業", "78km", "1,170", ""],
        ["(3) 202602120001 2/12 営業", "70km", "1,050", ""],
        ["(4) 202602170001 2/17 営業", "89km", "1,335", ""],
        ["(5) 202602200001 2/20 営業", "79km", "1,185", ""],
        ["(6) 202602240001 2/24 営業", "8km", "120", ""],
        ["(7) 202602260001 2/26 三河エリア営業", "64km", "960", ""],
        ["", "", "", ""],
        ["【実費精算】", "", "10,070", ""],
        ["(8) 202602030001 2/2 尾鷲港 高速道路", "実費", "8,000", ""],
        ["(9) 202602050002 2/5 昭和区 駐車場", "実費", "600", ""],
        ["(10) 202602250001 2/24 公共交通機関", "実費", "1,470", ""],
        ["", "", "", ""],
        ["総支給額 (I〜IV)", "", "150,765", ""],
        ["課税対象額合計（I+II+III）", "", "128,560", ""],
        ["V. 源泉徴収税（控除）", "甲欄・扶養1人", "0", "課税対象額128,560円→127,000〜129,000円の行・扶養1人＝0円"],
        ["差引支払額（振込額）", "", "150,765", ""],
        ["", "", "", ""],
        ["=== 勤怠実績（Lark Attendance API打刻記録・確定済み） ===", "", "", ""],
        ["日付", "出勤→退勤", "実働時間（休憩1h控除）", "区分"],
        ["2026-02-02", "出張申請ベース（打刻なし）", "—", "単独撮影（特約）"],
        ["2026-02-05", "09:23→17:39", "7.3h", "フル日給"],
        ["2026-02-12", "08:19→16:23", "7.1h", "フル日給"],
        ["2026-02-17", "09:16→16:59", "6.7h", "フル日給"],
        ["2026-02-20", "08:46→16:55", "7.2h", "フル日給"],
        ["2026-02-24", "08:58→16:55", "7.0h", "フル日給"],
        ["2026-02-26", "09:00→16:47", "6.8h", "フル日給"],
        ["", "", "", ""],
        ["=== 経費精算実績（Lark承認管理エクスポート全10件・確定済み） ===", "", "", ""],
        ["申請ID", "日付・内容", "距離/種別", "金額"],
        ["202602020001", "2/2 尾鷲港測量 交通費（ガソリン）", "421km", "6,315"],
        ["202602030001", "2/2 尾鷲港 高速道路（実費）", "—", "8,000"],
        ["202602050001", "2/5 昭和区ロケハン+営業（ガソリン）", "78km", "1,170"],
        ["202602050002", "2/5 昭和区 駐車場（実費）", "—", "600"],
        ["202602120001", "2/12 営業（ガソリン）", "70km", "1,050"],
        ["202602170001", "2/17 営業（ガソリン）", "89km", "1,335"],
        ["202602200001", "2/20 営業（ガソリン）", "79km", "1,185"],
        ["202602240001", "2/24 営業（ガソリン）", "8km", "120"],
        ["202602250001", "2/24 公共交通機関（実費）", "—", "1,470"],
        ["202602260001", "2/26 三河エリア営業（ガソリン）", "64km", "960"],
        ["合計", "ガソリン¥12,135 + 実費¥10,070", "", "22,205"],
        ["", "", "", ""],
        ["=== 内業（点群処理）計上根拠 ===", "", "", ""],
        ["尾鷲港新田線: 新美氏が2/20に成果レポート提出→2/21にK6修正版提出（Sparkメール確認済み）", "", "", ""],
        ["和合案件7箇所で複数係数0.8適用（12,000×1.1×0.8=10,560円/箇所）", "", "", ""],
        ["1月分で計上済みの6箇所（尾呂志川・在ノ上・木梶川・市木川ほか）は2月に重複計上しない", "", "", ""],
        ["", "", "", ""],
        ["=== 源泉徴収税の計算過程 ===", "", "", ""],
        ["課税対象額合計: 111,000（現場）+ 10,560（内業）+ 7,000（手当）= 128,560円", "", "", ""],
        ["経費精算22,205円は非課税のため課税対象に含まない", "", "", ""],
        ["税額判定: 令和8年分源泉徴収税額表（甲欄）を参照。", "", "", ""],
        ["「社会保険料等控除後の給与」の127,000円以上 129,000円未満の行、扶養親族1人の欄を適用し、税額は 0円。", "", "", ""],
        ["", "", "", ""],
        ["新美光様の2026年2月度（3月16日支払）の最終お振込金額は、150,765円となります。", "", "", ""],
    ]

    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    print(f"CSV生成完了: {CSV_PATH}")
    return rows


def generate_pdf():
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    PAGE_W, PAGE_H = A4
    MARGIN_L = 18 * mm
    MARGIN_R = 18 * mm
    MARGIN_T = 18 * mm
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

    pdfmetrics.registerFont(TTFont(FONT_R, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_B, FONT_BOLD_PATH, subfontIndex=0))

    def draw_table_header(c, x, y, widths, headers, height=7*mm):
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
        if aligns is None:
            aligns = ['c'] * len(widths)
        if idx % 2 == 1:
            c.setFillColor(COLOR_LIGHT_BG)
            c.rect(x, y - height, sum(widths), height, stroke=0, fill=1)
            c.setFillColor(colors.black)
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
        h = 7 * mm
        c.setFillColor(COLOR_LIGHT_BG)
        c.rect(x, y - h, CONTENT_W, h, stroke=0, fill=1)
        c.setStrokeColor(COLOR_ACCENT)
        c.setLineWidth(1.2)
        c.line(x, y, x, y - h)
        c.setFillColor(COLOR_NAVY)
        c.setFont(FONT_B, 10)
        c.drawString(x + 3 * mm, y - h + 2.2 * mm, title)
        if amount_str:
            c.setFont(FONT_B, 10)
            c.drawRightString(x + CONTENT_W - 3 * mm, y - h + 2.2 * mm, amount_str)
        c.setFillColor(colors.black)
        return y - h

    c = canvas.Canvas(PDF_PATH, pagesize=A4)
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
    c.drawRightString(lx + CONTENT_W - 8 * mm, y - box_h + 4.5 * mm, "\u00a5150,765")
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
    y = draw_section_title(c, lx, y, "IV. 経費精算（非課税）", "\u00a522,205")
    y -= 1 * mm

    w4 = [14*mm, CONTENT_W - 14*mm - 18*mm - 22*mm, 18*mm, 22*mm]
    y = draw_table_header(c, lx, y, w4, ["日付", "内容", "距離", "金額"])

    expense_items = [
        ("2/2", "尾鷲港測量 交通費（ガソリン）", "421km", "\u00a56,315"),
        ("2/2", "尾鷲港 高速道路（実費）", "\u2014", "\u00a58,000"),
        ("2/5", "昭和区ロケハン+営業（ガソリン）", "78km", "\u00a51,170"),
        ("2/5", "昭和区 駐車場（実費）", "\u2014", "\u00a5600"),
        ("2/12", "営業（ガソリン）", "70km", "\u00a51,050"),
        ("2/17", "営業（ガソリン）", "89km", "\u00a51,335"),
        ("2/20", "営業（ガソリン）", "79km", "\u00a51,185"),
        ("2/24", "営業（ガソリン）", "8km", "\u00a5120"),
        ("2/24", "公共交通機関（実費）", "\u2014", "\u00a51,470"),
        ("2/26", "三河エリア営業（ガソリン）", "64km", "\u00a5960"),
    ]
    for idx, (dt, desc, dist, amt) in enumerate(expense_items):
        y = draw_table_row(c, lx, y, w4, [dt, desc, dist, amt], idx=idx,
                           aligns=['c', 'l', 'c', 'r'], font_size=7)

    # 経費小計行
    y -= 1 * mm
    c.setFont(FONT_B, 7.5)
    c.drawString(lx + 2 * mm, y, "ガソリン代 7件: \u00a512,135（809km）")
    y -= 3.5 * mm
    c.drawString(lx + 2 * mm, y, "実費精算 3件: \u00a510,070（高速\u00a58,000 + 駐車場\u00a5600 + 公共交通機関\u00a51,470）")
    y -= 5 * mm

    # ═══ 集計 ═══
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
    c.drawRightString(val_x, y - row_h + 2.5 * mm, "\u00a5150,765")
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
    c.drawRightString(val_x, y - big_h + 3 * mm, "\u00a5150,765")
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
    c.drawString(lx + 2 * mm, y, "\u30fb Lark承認管理エクスポートにより経費精算全10件を確認・反映済み。")
    y -= 3.5 * mm
    c.drawString(lx + 2 * mm, y, "\u30fb 勤怠データはLark Attendance API打刻記録に基づく。")

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
    print(f"PDF生成完了: {PDF_PATH}")


def write_to_sheets(csv_rows):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SA_JSON, scopes=scopes)
    gc = gspread.authorize(creds)

    spreadsheet = gc.open_by_key(SHEETS_ID)
    print(f"スプレッドシート発見: {spreadsheet.url}")

    sheet_title = "2602"
    try:
        ws = spreadsheet.worksheet(sheet_title)
        ws.clear()
        print(f"既存シート「{sheet_title}」をクリア")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=sheet_title, rows=len(csv_rows) + 5, cols=4)
        print(f"新規シート「{sheet_title}」を作成")

    ws.update(range_name="A1", values=csv_rows)
    print(f"Google Sheets書き込み完了: {spreadsheet.url}")
    return spreadsheet.url


if __name__ == "__main__":
    print("=== 1. CSV生成 ===")
    csv_rows = generate_csv()

    print("\n=== 2. PDF生成 ===")
    generate_pdf()

    print("\n=== 3. Google Sheets書き込み ===")
    try:
        url = write_to_sheets(csv_rows)
    except Exception as e:
        print(f"Google Sheets エラー: {e}")
        raise
