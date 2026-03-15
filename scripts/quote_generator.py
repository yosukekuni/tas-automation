#!/usr/bin/env python3
"""
見積書PDF自動生成スクリプト
東海エアサービス株式会社 正式見積書フォーマット

Usage:
  python3 quote_generator.py --json input.json              # JSONファイルから生成
  python3 quote_generator.py --json input.json --preview    # 出力先パス表示のみ
  python3 quote_generator.py \\
    --client "株式会社サンプル" \\
    --project "ドローン測量業務" \\
    --item "ドローン撮影,1,80000" \\
    --item "データ処理,1,50000" \\
    --note "現場：名古屋市港区"                              # CLIから直接指定

JSON format:
  {
    "client_name": "株式会社サンプル",
    "client_department": "工事部",
    "client_contact": "田中太郎 様",
    "project_name": "ドローン測量業務",
    "items": [
      {"name": "ドローン撮影（写真測量）", "quantity": 1, "unit": "式", "unit_price": 80000},
      {"name": "データ処理・成果品作成", "quantity": 1, "unit": "式", "unit_price": 50000}
    ],
    "notes": "現場：名古屋市港区\\n納期：撮影後2週間",
    "quote_number": null,
    "issue_date": null,
    "validity_days": 30,
    "output_dir": null
  }
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
except ImportError:
    print("ERROR: reportlab が未インストールです。")
    print("  pip install reportlab")
    sys.exit(1)

# ── 定数 ──────────────────────────────────────────
COMPANY = {
    "name": "東海エアサービス株式会社",
    "rep": "代表取締役 國本 洋輔",
    "zip": "〒465-0077",
    "addr": "愛知県名古屋市名東区植園町1-9-3 LM1205",
    "invoice_no": "T5180001140533",
    "tel": "",
    "email": "info@tokaiair.com",
    "url": "https://www.tokaiair.com",
}

FONT_REGULAR_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicR.ttc"
FONT_BOLD_PATH = "/mnt/c/Windows/Fonts/BIZ-UDGothicB.ttc"
FONT_REGULAR = "BIZUDGothic"
FONT_BOLD = "BIZUDGothicBold"

DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "quotes"
QUOTE_SEQ_FILE = DEFAULT_OUTPUT_DIR / ".quote_seq.json"

TAX_RATE = 0.10

PAGE_W, PAGE_H = A4  # 595.27 x 841.89 pt
MARGIN_L = 20 * mm
MARGIN_R = 20 * mm
MARGIN_T = 20 * mm
MARGIN_B = 20 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


# ── フォント登録 ──────────────────────────────────
def register_fonts():
    if not os.path.exists(FONT_REGULAR_PATH):
        print(f"WARNING: フォント未検出: {FONT_REGULAR_PATH}")
        print("  Windows日本語フォント(BIZ UDゴシック)が必要です。")
        print("  パスを環境に合わせて修正してください。")
        sys.exit(1)
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, FONT_REGULAR_PATH, subfontIndex=0))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, FONT_BOLD_PATH, subfontIndex=0))


# ── 見積番号の自動採番 ────────────────────────────
def next_quote_number(output_dir: Path, issue_date: str) -> str:
    """TAS-YYMMDD-NNN 形式で採番"""
    seq_file = output_dir / ".quote_seq.json"
    ymd = issue_date.replace("-", "")[2:]  # YYMMDD

    seq_data = {}
    if seq_file.exists():
        try:
            seq_data = json.loads(seq_file.read_text())
        except Exception:
            seq_data = {}

    key = ymd
    seq = seq_data.get(key, 0) + 1
    seq_data[key] = seq
    seq_file.write_text(json.dumps(seq_data, indent=2))

    return f"TAS-{ymd}-{seq:03d}"


# ── 金額フォーマット ──────────────────────────────
def fmt_yen(amount: int) -> str:
    return f"¥{amount:,}"


# ── PDF描画 ───────────────────────────────────────
def draw_quote_pdf(c: canvas.Canvas, data: dict):
    """1ページの見積書を描画"""
    y = PAGE_H - MARGIN_T

    # ── タイトル ──
    c.setFont(FONT_BOLD, 22)
    title = "御 見 積 書"
    tw = c.stringWidth(title, FONT_BOLD, 22)
    c.drawString((PAGE_W - tw) / 2, y, title)
    y -= 8 * mm
    # タイトル下線
    c.setStrokeColor(colors.HexColor("#1a3c6e"))
    c.setLineWidth(2)
    c.line(MARGIN_L, y, PAGE_W - MARGIN_R, y)
    y -= 10 * mm

    # ── 左側: 宛先 / 右側: 見積情報 ──
    left_x = MARGIN_L
    right_x = PAGE_W / 2 + 10 * mm
    info_y = y

    # 宛先
    c.setFont(FONT_BOLD, 14)
    client_name = data.get("client_name", "")
    c.drawString(left_x, y, client_name)
    # 宛先下線
    name_w = c.stringWidth(client_name + "  御中", FONT_BOLD, 14)
    c.setFont(FONT_REGULAR, 14)
    c.drawString(left_x + c.stringWidth(client_name, FONT_BOLD, 14), y, "  御中")
    y -= 2 * mm
    c.setLineWidth(0.8)
    c.setStrokeColor(colors.black)
    c.line(left_x, y, left_x + max(name_w, 80 * mm), y)
    y -= 6 * mm

    if data.get("client_department"):
        c.setFont(FONT_REGULAR, 10)
        c.drawString(left_x + 2 * mm, y, data["client_department"])
        y -= 5 * mm
    if data.get("client_contact"):
        c.setFont(FONT_REGULAR, 10)
        c.drawString(left_x + 2 * mm, y, data["client_contact"])
        y -= 5 * mm

    # 右側: 見積番号・発行日・有効期限
    ry = info_y
    c.setFont(FONT_REGULAR, 9)
    labels = [
        ("見積番号", data["quote_number"]),
        ("発行日", data["issue_date"]),
        ("有効期限", data["valid_until"]),
    ]
    for label, val in labels:
        c.drawString(right_x, ry, f"{label}: {val}")
        ry -= 5 * mm

    # 自社情報（右寄せ）
    ry -= 3 * mm
    c.setFont(FONT_BOLD, 10)
    c.drawString(right_x, ry, COMPANY["name"])
    ry -= 5 * mm
    c.setFont(FONT_REGULAR, 8)
    for line in [
        COMPANY["rep"],
        f"{COMPANY['zip']} {COMPANY['addr']}",
        f"登録番号: {COMPANY['invoice_no']}",
        COMPANY["email"],
        COMPANY["url"],
    ]:
        c.drawString(right_x, ry, line)
        ry -= 4 * mm

    # ── 案件名 ──
    y = min(y, ry) - 8 * mm
    c.setFont(FONT_REGULAR, 10)
    c.drawString(left_x, y, f"件名: {data.get('project_name', '')}")
    y -= 8 * mm

    # ── 合計金額ボックス ──
    total = data["total_with_tax"]
    box_h = 12 * mm
    c.setFillColor(colors.HexColor("#f0f4fa"))
    c.setStrokeColor(colors.HexColor("#1a3c6e"))
    c.setLineWidth(1.5)
    c.roundRect(left_x, y - box_h, CONTENT_W, box_h, 3, stroke=1, fill=1)
    c.setFillColor(colors.black)
    c.setFont(FONT_BOLD, 13)
    c.drawString(left_x + 5 * mm, y - box_h + 3.5 * mm, f"お見積金額（税込）: {fmt_yen(total)}")
    y -= box_h + 8 * mm

    # ── 明細テーブル ──
    items = data.get("items", [])
    col_widths = [8 * mm, 75 * mm, 18 * mm, 14 * mm, 25 * mm, 25 * mm]  # No,品名,数量,単位,単価,金額
    # 残り幅を品名に割り当て
    used = sum(col_widths) - col_widths[1]
    col_widths[1] = CONTENT_W - used

    headers = ["No.", "品名・摘要", "数量", "単位", "単価", "金額"]
    header_h = 8 * mm
    row_h = 7 * mm

    # ヘッダ背景
    c.setFillColor(colors.HexColor("#1a3c6e"))
    c.rect(left_x, y - header_h, CONTENT_W, header_h, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont(FONT_BOLD, 9)

    cx = left_x
    for i, (hdr, w) in enumerate(zip(headers, col_widths)):
        if i in (0, 2, 3):  # center
            c.drawCentredString(cx + w / 2, y - header_h + 2.5 * mm, hdr)
        elif i in (4, 5):  # right
            c.drawRightString(cx + w - 2 * mm, y - header_h + 2.5 * mm, hdr)
        else:
            c.drawString(cx + 2 * mm, y - header_h + 2.5 * mm, hdr)
        cx += w

    y -= header_h
    c.setFillColor(colors.black)
    c.setFont(FONT_REGULAR, 9)

    for idx, item in enumerate(items, 1):
        row_top = y
        row_bot = y - row_h

        # 偶数行に薄い背景
        if idx % 2 == 0:
            c.setFillColor(colors.HexColor("#f7f9fc"))
            c.rect(left_x, row_bot, CONTENT_W, row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)

        # 行の下線
        c.setStrokeColor(colors.HexColor("#dddddd"))
        c.setLineWidth(0.3)
        c.line(left_x, row_bot, left_x + CONTENT_W, row_bot)

        cx = left_x
        name = item.get("name", "")
        qty = item.get("quantity", 1)
        unit = item.get("unit", "式")
        unit_price = int(item.get("unit_price", 0))
        amount = qty * unit_price

        vals = [
            str(idx),
            name,
            str(qty),
            unit,
            fmt_yen(unit_price),
            fmt_yen(amount),
        ]
        for i, (val, w) in enumerate(zip(vals, col_widths)):
            ty = row_bot + 2 * mm
            if i in (0, 2, 3):
                c.drawCentredString(cx + w / 2, ty, val)
            elif i in (4, 5):
                c.drawRightString(cx + w - 2 * mm, ty, val)
            else:
                # 品名：長い場合は切り詰め
                max_chars = int(w / (9 * 0.6))
                if len(val) > max_chars:
                    val = val[:max_chars - 1] + "..."
                c.drawString(cx + 2 * mm, ty, val)
            cx += w

        y -= row_h

    # ── 小計・消費税・合計 ──
    y -= 3 * mm
    summary_x = left_x + CONTENT_W - 55 * mm
    summary_w = 55 * mm
    label_x = summary_x + 2 * mm
    val_x = summary_x + summary_w - 2 * mm

    subtotal = data["subtotal"]
    tax = data["tax"]

    c.setStrokeColor(colors.HexColor("#cccccc"))
    c.setLineWidth(0.5)

    for label, amount, bold in [
        ("小計", subtotal, False),
        (f"消費税（{int(TAX_RATE*100)}%）", tax, False),
        ("合計（税込）", total, True),
    ]:
        font = FONT_BOLD if bold else FONT_REGULAR
        size = 11 if bold else 9
        h = 7 * mm if not bold else 8 * mm

        if bold:
            c.setFillColor(colors.HexColor("#f0f4fa"))
            c.rect(summary_x, y - h, summary_w, h, stroke=1, fill=1)
            c.setFillColor(colors.black)
        else:
            c.line(summary_x, y - h, summary_x + summary_w, y - h)

        c.setFont(font, size)
        c.drawString(label_x, y - h + 2.5 * mm, label)
        c.drawRightString(val_x, y - h + 2.5 * mm, fmt_yen(amount))
        y -= h

    # ── 備考 ──
    notes = data.get("notes", "")
    if notes:
        y -= 10 * mm
        c.setFont(FONT_BOLD, 10)
        c.drawString(left_x, y, "備考")
        y -= 2 * mm
        c.setStrokeColor(colors.HexColor("#cccccc"))
        c.setLineWidth(0.5)
        c.line(left_x, y, left_x + CONTENT_W, y)
        y -= 5 * mm

        c.setFont(FONT_REGULAR, 9)
        for line in notes.split("\n"):
            c.drawString(left_x + 2 * mm, y, line)
            y -= 4.5 * mm

    # ── フッタ ──
    c.setFont(FONT_REGULAR, 7)
    c.setFillColor(colors.HexColor("#888888"))
    c.drawCentredString(PAGE_W / 2, MARGIN_B - 5 * mm,
                        f"{COMPANY['name']} | {COMPANY['email']} | {COMPANY['url']}")
    c.setFillColor(colors.black)


def build_data(raw: dict, output_dir: Path) -> dict:
    """入力データを正規化し計算値を付加"""
    issue_date = raw.get("issue_date") or datetime.now().strftime("%Y-%m-%d")
    validity_days = int(raw.get("validity_days", 30))
    valid_until = (datetime.strptime(issue_date, "%Y-%m-%d") + timedelta(days=validity_days)).strftime("%Y-%m-%d")

    quote_number = raw.get("quote_number")
    if not quote_number:
        quote_number = next_quote_number(output_dir, issue_date)

    items = raw.get("items", [])
    subtotal = sum(int(it.get("quantity", 1)) * int(it.get("unit_price", 0)) for it in items)
    tax = int(subtotal * TAX_RATE)
    total = subtotal + tax

    return {
        "client_name": raw.get("client_name", ""),
        "client_department": raw.get("client_department", ""),
        "client_contact": raw.get("client_contact", ""),
        "project_name": raw.get("project_name", ""),
        "quote_number": quote_number,
        "issue_date": issue_date,
        "valid_until": valid_until,
        "items": items,
        "subtotal": subtotal,
        "tax": tax,
        "total_with_tax": total,
        "notes": raw.get("notes", ""),
    }


def generate_pdf(data: dict, output_path: Path):
    """PDF生成"""
    register_fonts()
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle(f"見積書_{data['quote_number']}")
    c.setAuthor(COMPANY["name"])
    draw_quote_pdf(c, data)
    c.save()


def parse_cli_items(item_args: list) -> list:
    """'品名,数量,単価' 形式のCLI引数をパース"""
    items = []
    for raw in item_args:
        parts = raw.split(",")
        if len(parts) < 3:
            print(f"WARNING: --item の形式が不正です（品名,数量,単価）: {raw}")
            continue
        items.append({
            "name": parts[0].strip(),
            "quantity": int(parts[1].strip()),
            "unit": parts[3].strip() if len(parts) > 3 else "式",
            "unit_price": int(parts[2].strip()),
        })
    return items


def main():
    parser = argparse.ArgumentParser(description="見積書PDF自動生成")
    parser.add_argument("--json", help="入力JSONファイルパス")
    parser.add_argument("--client", help="取引先名")
    parser.add_argument("--department", help="部署名", default="")
    parser.add_argument("--contact", help="担当者名（様付き）", default="")
    parser.add_argument("--project", help="案件名")
    parser.add_argument("--item", action="append", help="明細行: '品名,数量,単価[,単位]'（複数指定可）")
    parser.add_argument("--note", help="備考")
    parser.add_argument("--quote-number", help="見積番号（省略で自動採番）")
    parser.add_argument("--date", help="発行日 YYYY-MM-DD（省略で今日）")
    parser.add_argument("--validity", type=int, default=30, help="有効期限日数（デフォルト30日）")
    parser.add_argument("--output-dir", help="出力ディレクトリ")
    parser.add_argument("--output", help="出力ファイルパス（指定時はoutput-dirを無視）")
    parser.add_argument("--preview", action="store_true", help="出力先パスのみ表示（PDF生成しない）")
    args = parser.parse_args()

    # 入力データ構築
    if args.json:
        json_path = Path(args.json)
        if not json_path.exists():
            print(f"ERROR: JSONファイルが見つかりません: {json_path}")
            sys.exit(1)
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)
    elif args.client and args.item:
        raw = {
            "client_name": args.client,
            "client_department": args.department,
            "client_contact": args.contact,
            "project_name": args.project or "",
            "items": parse_cli_items(args.item),
            "notes": args.note or "",
            "quote_number": args.quote_number,
            "issue_date": args.date,
            "validity_days": args.validity,
        }
    else:
        parser.print_help()
        print("\nERROR: --json または --client + --item を指定してください。")
        sys.exit(1)

    # 出力先決定
    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    data = build_data(raw, output_dir)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        safe_client = data["client_name"].replace("/", "_").replace(" ", "").replace("　", "") or "NoName"
        filename = f"{data['quote_number']}_{safe_client}.pdf"
        output_path = output_dir / filename

    if args.preview:
        print(f"見積番号: {data['quote_number']}")
        print(f"取引先: {data['client_name']}")
        print(f"件名: {data['project_name']}")
        print(f"発行日: {data['issue_date']}")
        print(f"有効期限: {data['valid_until']}")
        print(f"小計: {fmt_yen(data['subtotal'])}")
        print(f"消費税: {fmt_yen(data['tax'])}")
        print(f"合計（税込）: {fmt_yen(data['total_with_tax'])}")
        print(f"出力先: {output_path}")
        return

    generate_pdf(data, output_path)
    print(f"見積書を生成しました: {output_path}")
    print(f"  見積番号: {data['quote_number']}")
    print(f"  合計（税込）: {fmt_yen(data['total_with_tax'])}")


if __name__ == "__main__":
    main()
