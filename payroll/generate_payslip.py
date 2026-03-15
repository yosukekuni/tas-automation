#!/usr/bin/env python3
"""
業務委託 支払明細書 PDF生成スクリプト
東海エアサービス株式会社
"""

import os
import sys
from datetime import datetime
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
COMPANY = {
    "name": "東海エアサービス株式会社",
    "rep": "代表取締役 國本 洋輔",
    "zip": "〒465-0077",
    "addr": "愛知県名古屋市名東区植園町1-9-3 LM1205",
    "invoice_no": "T5180001140533",
    "email": "info@tokaiair.com",
    "url": "https://www.tokaiair.com",
}

FONT_REGULAR_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicR.ttc"
FONT_BOLD_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicB.ttc"
FONT_REGULAR = "BIZUDGothic"
FONT_BOLD = "BIZUDGothicBold"

PAGE_W, PAGE_H = A4
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
MARGIN_T = 20 * mm
MARGIN_B = 20 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


def register_fonts():
    if not os.path.exists(FONT_REGULAR_PATH):
        print(f"WARNING: フォント未検出: {FONT_REGULAR_PATH}")
        sys.exit(1)
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_BOLD_PATH, subfontIndex=0))


def fmt_yen(amount: int) -> str:
    return f"¥{amount:,}"


def draw_payslip(c: canvas.Canvas, data: dict):
    y = PAGE_H - MARGIN_T
    left_x = MARGIN_L
    right_x = PAGE_W / 2 + 10 * mm

    # ── タイトル ──
    c.setFont(FONT_BOLD, 20)
    title = "支 払 明 細 書"
    tw = c.stringWidth(title, FONT_BOLD, 20)
    c.drawString((PAGE_W - tw) / 2, y, title)
    y -= 7 * mm
    c.setStrokeColor(colors.HexColor("#1a3c6e"))
    c.setLineWidth(2)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 12 * mm

    # ── 左: 受取人 / 右: 発行情報 ──
    info_y = y

    # 受取人
    c.setFont(FONT_BOLD, 14)
    name = data["payee_name"]
    c.drawString(left_x, y, f"{name}  殿")
    y -= 3 * mm
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.8)
    c.line(left_x, y, left_x + 80 * mm, y)
    y -= 8 * mm

    c.setFont(FONT_REGULAR, 10)
    c.drawString(left_x, y, f"対象期間: {data['period']}")
    y -= 6 * mm
    c.drawString(left_x, y, f"支払日: {data['payment_date']}")
    y -= 6 * mm

    # 右: 発行者情報
    ry = info_y
    c.setFont(FONT_BOLD, 10)
    c.drawString(right_x, ry, COMPANY["name"])
    ry -= 5 * mm
    c.setFont(FONT_REGULAR, 8)
    for line in [
        COMPANY["rep"],
        f"{COMPANY['zip']} {COMPANY['addr']}",
        f"登録番号: {COMPANY['invoice_no']}",
        COMPANY["email"],
    ]:
        c.drawString(right_x, ry, line)
        ry -= 4 * mm

    # ── 明細テーブル ──
    y = min(y, ry) - 10 * mm

    col_widths = [8 * mm, 0, 18 * mm, 14 * mm, 28 * mm, 28 * mm]
    used = sum(col_widths)
    col_widths[1] = CONTENT_W - used  # 品名列

    headers = ["No.", "業務内容", "数量", "単位", "単価", "金額"]
    header_h = 8 * mm
    row_h = 7 * mm

    # ヘッダ
    c.setFillColor(colors.HexColor("#1a3c6e"))
    c.rect(left_x, y - header_h, CONTENT_W, header_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 9)
    cx = left_x
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        if i in (0, 2, 3):
            c.drawCentredString(cx + w / 2, y - header_h + 2.5 * mm, hdr)
        elif i in (4, 5):
            c.drawRightString(cx + w - 2 * mm, y - header_h + 2.5 * mm, hdr)
        else:
            c.drawString(cx + 2 * mm, y - header_h + 2.5 * mm, hdr)
        cx += w
    y -= header_h
    c.setFillColor(colors.black)
    c.setFont(FONT_REGULAR, 9)

    items = data["items"]
    for idx, item in enumerate(items, 1):
        row_bot = y - row_h
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#f7f9fc"))
            c.rect(left_x, row_bot, CONTENT_W, row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.setLineWidth(0.3)
        c.line(left_x, row_bot, left_x + CONTENT_W, row_bot)

        name_val = item["name"]
        qty = item["quantity"]
        unit = item.get("unit", "日")
        unit_price = item["unit_price"]
        amount = qty * unit_price

        vals = [str(idx), name_val, str(qty), unit, fmt_yen(unit_price), fmt_yen(amount)]
        cx = left_x
        for i, (val, w) in enumerate(zip(vals, col_widths)):
            ty = row_bot + 2 * mm
            if i in (0, 2, 3):
                c.drawCentredString(cx + w / 2, ty, val)
            elif i in (4, 5):
                c.drawRightString(cx + w - 2 * mm, ty, val)
            else:
                max_chars = int(w / (9 * 0.55))
                if len(val) > max_chars:
                    val = val[:max_chars - 1] + "..."
                c.drawString(cx + 2 * mm, ty, val)
            cx += w
        y -= row_h

    # ── 小計・源泉・差引支払額 ──
    y -= 5 * mm
    summary_w = 65 * mm
    summary_x = left_x + CONTENT_W - summary_w
    label_x = summary_x + 2 * mm
    val_x = summary_x + summary_w - 2 * mm

    gross = data["gross_total"]
    withholding = data["withholding_tax"]
    net = data["net_payment"]

    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)

    rows = [
        ("報酬合計", gross, False),
        ("源泉徴収税額", -withholding, False),
        ("差引支払額", net, True),
    ]

    for label, amount, bold in rows:
        font = FONT_BOLD if bold else FONT_REGULAR
        size = 12 if bold else 9
        h = 9 * mm if bold else 7 * mm

        if bold:
            c.setFillColor(colors.HexColor("#f0f4fa"))
            c.setStrokeColor(colors.HexColor("#1a3c6e"))
            c.setLineWidth(1.5)
            c.roundRect(summary_x, y - h, summary_w, h, 3, stroke=1, fill=1)
            c.setFillColor(colors.black)
        else:
            c.line(summary_x, y - h, summary_x + summary_w, y - h)

        c.setFont(font, size)
        c.drawString(label_x, y - h + 3 * mm, label)
        if amount < 0:
            c.drawRightString(val_x, y - h + 3 * mm, f"-{fmt_yen(abs(amount))}")
        else:
            c.drawRightString(val_x, y - h + 3 * mm, fmt_yen(amount))
        y -= h

    # ── 計算根拠 ──
    y -= 12 * mm
    c.setFont(FONT_BOLD, 10)
    c.drawString(left_x, y, "源泉徴収の計算根拠")
    y -= 2 * mm
    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)
    c.line(left_x, y, left_x + CONTENT_W, y)
    y -= 6 * mm

    c.setFont(FONT_REGULAR, 9)
    for line in data.get("tax_notes", []):
        c.drawString(left_x + 2 * mm, y, line)
        y -= 4.5 * mm

    # ── 備考 ──
    if data.get("notes"):
        y -= 8 * mm
        c.setFont(FONT_BOLD, 10)
        c.drawString(left_x, y, "備考")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#cccccc"))
        c.setLineWidth(0.5)
        c.line(left_x, y, left_x + CONTENT_W, y)
        y -= 5 * mm
        c.setFont(FONT_REGULAR, 9)
        for line in data["notes"].split("\n"):
            c.drawString(left_x + 2 * mm, y, line)
            y -= 4.5 * mm

    # ── フッタ ──
    c.setFont(FONT_REGULAR, 7)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(PAGE_W / 2, MARGIN_B - 5 * mm,
                        f"{COMPANY['name']} | {COMPANY['email']} | {COMPANY['url']}")
    c.drawCentredString(PAGE_W / 2, MARGIN_B - 9 * mm,
                        "本書類は社外秘です。第三者への開示を禁じます。")
    c.setFillColor(colors.black)


def calculate_withholding_tax_business(gross: int) -> int:
    """
    業務委託報酬の源泉徴収税額
    報酬が100万円以下: 10.21%
    報酬が100万円超: (報酬-100万)×20.42% + 102,100
    """
    if gross <= 1_000_000:
        return int(gross * 0.1021)
    else:
        return int((gross - 1_000_000) * 0.2042 + 102_100)


def main():
    # ── 新美光 2026年3月前半（3/1-3/15）稼働実績 ──
    #
    # データソース:
    #   - Googleカレンダー: 3/9 昭和区マンション眺望撮影（静止画）10:00-14:30
    #   - 週2稼働パターン（火曜最多36.7%）から推定
    #   - Lark CRM / Sparkメールはアクセス不可のため推定値を含む
    #
    # 3/1-3/15の平日火曜: 3/3, 3/10（2日）
    # 3/9（月）撮影現場あり → カレンダー確認済み（参加者要確認）
    #
    # 【要確認】以下は推定値を含みます。新美さん本人の稼働報告で確定してください。

    items = [
        {
            "name": "フル出勤（営業・現場対応）3/3",
            "quantity": 1,
            "unit": "日",
            "unit_price": 16_000,
        },
        {
            "name": "フル出勤（営業・現場対応）3/10",
            "quantity": 1,
            "unit": "日",
            "unit_price": 16_000,
        },
        {
            "name": "現場撮影（昭和区マンション眺望）3/9",
            "quantity": 1,
            "unit": "日",
            "unit_price": 15_000,
        },
        {
            "name": "点群データ処理（昭和区案件）",
            "quantity": 1,
            "unit": "式",
            "unit_price": 10_560,
        },
    ]

    gross = sum(it["quantity"] * it["unit_price"] for it in items)
    withholding = calculate_withholding_tax_business(gross)
    net = gross - withholding

    data = {
        "payee_name": "新美 光",
        "period": "2026年3月1日 〜 2026年3月15日",
        "payment_date": "2026年3月16日（月）",
        "items": items,
        "gross_total": gross,
        "withholding_tax": withholding,
        "net_payment": net,
        "tax_notes": [
            "・業務委託報酬に対する源泉徴収（所得税法第204条）",
            f"・税率: 10.21%（報酬100万円以下）",
            f"・計算: {fmt_yen(gross)} × 10.21% = {fmt_yen(withholding)}",
            "・甲欄適用・扶養親族1名",
        ],
        "notes": (
            "【要確認】本明細の稼働実績は、Googleカレンダーおよび\n"
            "週2稼働パターンからの推定値を含みます。\n"
            "新美さん本人の稼働報告で確定後、修正版を発行してください。\n"
            "\n"
            "振込先: 新美さん指定口座\n"
            "支払方法: 銀行振込"
        ),
    }

    output_path = Path(__file__).parent / "niimi_202503.pdf"

    register_fonts()
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle("支払明細書_新美光_202503前半")
    c.setAuthor(COMPANY["name"])
    draw_payslip(c, data)
    c.save()

    print(f"支払明細書を生成しました: {output_path}")
    print()
    print("=== 計算内訳 ===")
    print(f"対象期間: {data['period']}")
    print(f"支払日: {data['payment_date']}")
    print()
    for i, item in enumerate(items, 1):
        amt = item['quantity'] * item['unit_price']
        print(f"  {i}. {item['name']}: {item['quantity']}{item['unit']} × {fmt_yen(item['unit_price'])} = {fmt_yen(amt)}")
    print(f"  ────────────────────────────────")
    print(f"  報酬合計:       {fmt_yen(gross)}")
    print(f"  源泉徴収税額:   -{fmt_yen(withholding)}")
    print(f"  差引支払額:     {fmt_yen(net)}")
    print()
    print("【注意】稼働実績は推定値を含みます。新美さんの稼働報告で確定してください。")


if __name__ == "__main__":
    main()
