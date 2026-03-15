#!/usr/bin/env python3
"""
Lark Mail Reader - info@tokaiair.com メール検索・閲覧ツール

SparkデスクトップのSQLiteデータベースをコピーして検索し、
IMAP経由で全文取得する。

Usage:
    python3 lark_mail_reader.py --recent 20
    python3 lark_mail_reader.py --search "見積" --to "kobayashi"
    python3 lark_mail_reader.py --search "昭和区" --sent
    python3 lark_mail_reader.py --read <message_id or pk>
    python3 lark_mail_reader.py --search "見積" --from "niimi" --days 30
"""

import argparse
import email
import email.policy
import imaplib
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# ── 定数 ──────────────────────────────────────────────
SPARK_DB = Path(r"/mnt/c/Users/USER/AppData/Local/Spark Desktop/core-data/databases/messages.sqlite")
ACCOUNT_PK = 12  # info@tokaiair.com
SENT_FOLDER_IMAP = "&XfJT0ZAB-"

# .env読み込み
ENV_PATH = Path("/home/user/tokaiair/.env")
load_dotenv(ENV_PATH)

IMAP_HOST = os.getenv("LARK_IMAP_HOST", "imap.larksuite.com")
IMAP_PORT = int(os.getenv("LARK_IMAP_PORT", "993"))
IMAP_USER = os.getenv("LARK_IMAP_USER", "info@tokaiair.com")
IMAP_PASS = os.getenv("LARK_IMAP_PASS", "")


# ── SparkDB操作 ─────────────────────────────────────────
def copy_db() -> str:
    """Spark DBをtmpにコピーしてパスを返す（WALもコピー）"""
    tmp_dir = tempfile.mkdtemp(prefix="spark_mail_")
    for ext in ["", "-shm", "-wal"]:
        src = Path(str(SPARK_DB) + ext)
        if src.exists():
            shutil.copy2(str(src), os.path.join(tmp_dir, src.name))
    return os.path.join(tmp_dir, SPARK_DB.name)


def search_messages(db_path: str, search: str = None, from_addr: str = None,
                    to_addr: str = None, sent_only: bool = False,
                    limit: int = 20, days: int = None) -> list:
    """SparkDBからメール検索"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    conditions = [f"accountPk = {ACCOUNT_PK}"]
    params = []

    if sent_only:
        conditions.append("inSent = 1")

    if search:
        conditions.append("(subject LIKE ? OR shortBody LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])

    if from_addr:
        conditions.append("(messageFrom LIKE ? OR messageFromMailbox LIKE ?)")
        params.extend([f"%{from_addr}%", f"%{from_addr}%"])

    if to_addr:
        conditions.append("(messageTo LIKE ? OR messageCc LIKE ?)")
        params.extend([f"%{to_addr}%", f"%{to_addr}%"])

    if days:
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        conditions.append("receivedDate >= ?")
        params.append(cutoff)

    where = " AND ".join(conditions)
    query = f"""
        SELECT pk, receivedDate, subject, messageFrom, messageTo,
               messageCc, shortBody, messageId, inSent,
               numberOfFileAttachments
        FROM messages
        WHERE {where}
        ORDER BY receivedDate DESC
        LIMIT ?
    """
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def format_date(ts: float) -> str:
    """Unixタイムスタンプを日本時間に変換"""
    from datetime import timedelta
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) + timedelta(hours=9)
    return dt.strftime("%Y-%m-%d %H:%M")


def truncate(text: str, length: int = 80) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ").replace("\r", "")
    return text[:length] + "..." if len(text) > length else text


def extract_name_email(raw: str) -> str:
    """'"Name" <email>' → 'Name <email>' に簡略化"""
    if not raw:
        return ""
    return raw.replace('"', '').strip()


def print_list(rows: list):
    """一覧表示"""
    if not rows:
        print("該当するメールが見つかりません。")
        return

    print(f"\n{'='*90}")
    print(f"  {'PK':>6}  {'日時':^16}  {'方向':^4}  {'件名'}")
    print(f"{'='*90}")

    for row in rows:
        direction = "→送信" if row["inSent"] else "←受信"
        date_str = format_date(row["receivedDate"])
        subj = truncate(row["subject"], 50)
        from_str = extract_name_email(row["messageFrom"])
        to_str = extract_name_email(row["messageTo"])
        attach = f" 📎{row['numberOfFileAttachments']}" if row["numberOfFileAttachments"] else ""

        print(f"  {row['pk']:>6}  {date_str}  {direction}  {subj}{attach}")
        if row["inSent"]:
            print(f"          To: {truncate(to_str, 60)}")
        else:
            print(f"          From: {truncate(from_str, 60)}")
        body_preview = truncate(row["shortBody"], 70)
        if body_preview:
            print(f"          {body_preview}")
        print()

    print(f"  合計: {len(rows)}件")
    print(f"{'='*90}")
    print(f"  全文表示: python3 {Path(__file__).name} --read <PK番号>")
    print()


# ── IMAP全文取得 ─────────────────────────────────────────
def fetch_full_message(db_path: str, pk_or_msgid: str) -> None:
    """PKまたはMessage-IDからIMAPで全文取得して表示"""
    if not IMAP_PASS:
        print("エラー: LARK_IMAP_PASS が .env に設定されていません。")
        print(f"  .env パス: {ENV_PATH}")
        print(f"  必要な変数: LARK_IMAP_PASS=<パスワード>")
        sys.exit(1)

    # PKの場合、DBからmessageIdとinSentを取得
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        pk = int(pk_or_msgid)
        cur.execute("SELECT messageId, inSent, subject, messageFrom, messageTo, receivedDate FROM messages WHERE pk = ?", (pk,))
    except ValueError:
        cur.execute("SELECT messageId, inSent, subject, messageFrom, messageTo, receivedDate FROM messages WHERE messageId = ?", (pk_or_msgid,))

    row = cur.fetchone()
    conn.close()

    if not row:
        print(f"エラー: メッセージが見つかりません (PK/ID: {pk_or_msgid})")
        sys.exit(1)

    message_id = row["messageId"]
    is_sent = row["inSent"]

    print(f"\n{'='*80}")
    print(f"  件名: {row['subject']}")
    print(f"  日時: {format_date(row['receivedDate'])}")
    print(f"  From: {extract_name_email(row['messageFrom'])}")
    print(f"  To:   {extract_name_email(row['messageTo'])}")
    print(f"  Message-ID: {message_id}")
    print(f"{'='*80}")

    # IMAP接続
    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        imap.login(IMAP_USER, IMAP_PASS)
    except Exception as e:
        print(f"\nIMAP接続エラー: {e}")
        print("\n--- SparkDBのプレビューを表示します ---")
        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        cur2 = conn2.cursor()
        try:
            pk_val = int(pk_or_msgid)
            cur2.execute("SELECT shortBody FROM messages WHERE pk = ?", (pk_val,))
        except ValueError:
            cur2.execute("SELECT shortBody FROM messages WHERE messageId = ?", (pk_or_msgid,))
        r = cur2.fetchone()
        conn2.close()
        if r:
            print(r["shortBody"])
        return

    # フォルダ選択
    folder = SENT_FOLDER_IMAP if is_sent else "INBOX"
    try:
        status, _ = imap.select(folder, readonly=True)
        if status != "OK":
            # フォールバック: すべてのフォルダを試す
            imap.select("INBOX", readonly=True)
    except Exception:
        imap.select("INBOX", readonly=True)

    # Message-IDで検索
    search_criteria = f'(HEADER Message-ID "{message_id}")'
    status, data = imap.search(None, search_criteria)

    if status != "OK" or not data[0]:
        # 送信済みフォルダも試す
        if not is_sent:
            try:
                imap.select(SENT_FOLDER_IMAP, readonly=True)
                status, data = imap.search(None, search_criteria)
            except Exception:
                pass

    if status != "OK" or not data[0]:
        print(f"\nIMAPでメッセージが見つかりませんでした。")
        print("--- SparkDBのプレビューを表示します ---\n")
        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        cur2 = conn2.cursor()
        try:
            pk_val = int(pk_or_msgid)
            cur2.execute("SELECT shortBody FROM messages WHERE pk = ?", (pk_val,))
        except ValueError:
            cur2.execute("SELECT shortBody FROM messages WHERE messageId = ?", (pk_or_msgid,))
        r = cur2.fetchone()
        conn2.close()
        if r:
            print(r["shortBody"])
        imap.logout()
        return

    # メッセージ取得
    msg_nums = data[0].split()
    uid = msg_nums[-1]  # 最新のものを使用
    status, msg_data = imap.fetch(uid, "(RFC822)")

    if status != "OK":
        print("メッセージ取得に失敗しました。")
        imap.logout()
        return

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email, policy=email.policy.default)

    # 本文抽出
    body = extract_body(msg)
    print(f"\n{body}")

    # 添付ファイル一覧
    attachments = []
    for part in msg.walk():
        filename = part.get_filename()
        if filename:
            attachments.append(filename)

    if attachments:
        print(f"\n{'─'*40}")
        print(f"添付ファイル ({len(attachments)}件):")
        for i, name in enumerate(attachments, 1):
            print(f"  {i}. {name}")

    print(f"\n{'='*80}\n")
    imap.logout()


def extract_body(msg) -> str:
    """メールの本文をテキストで抽出"""
    # text/plain を優先
    body = msg.get_body(preferencelist=("plain",))
    if body:
        content = body.get_content()
        if content and content.strip():
            return content.strip()

    # text/html をフォールバック
    body = msg.get_body(preferencelist=("html",))
    if body:
        content = body.get_content()
        if content:
            return html_to_text(content)

    return "(本文を取得できませんでした)"


def html_to_text(html: str) -> str:
    """簡易HTML→テキスト変換"""
    import re
    text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&')
    text = text.replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    # 連続空行を整理
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── メイン ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="info@tokaiair.com メール検索・閲覧（Spark DB + IMAP）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  %(prog)s --recent 20                  最新20件表示
  %(prog)s --search "見積"               件名・本文で検索
  %(prog)s --search "見積" --to "小林"    宛先を絞り込み
  %(prog)s --search "昭和区" --sent       送信済みから検索
  %(prog)s --from "niimi" --days 7       直近7日間の受信
  %(prog)s --read 187582                 PK指定で全文表示
  %(prog)s --unread                      未読メール一覧
        """
    )

    # 検索モード
    parser.add_argument("--search", "-s", help="件名・本文で検索")
    parser.add_argument("--from", "-f", dest="from_addr", help="送信者でフィルタ")
    parser.add_argument("--to", "-t", help="宛先でフィルタ")
    parser.add_argument("--sent", action="store_true", help="送信済みメールのみ")
    parser.add_argument("--days", "-d", type=int, help="直近N日間に限定")
    parser.add_argument("--limit", "-n", type=int, default=20, help="表示件数（デフォルト20）")

    # 表示モード
    parser.add_argument("--recent", "-r", type=int, help="最新N件を表示")
    parser.add_argument("--unread", action="store_true", help="未読メールのみ")
    parser.add_argument("--read", metavar="PK", help="全文表示（PK番号またはMessage-ID）")

    args = parser.parse_args()

    # 引数なしの場合はヘルプ表示
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    # DB コピー
    print("Spark DBをコピー中...", end=" ", flush=True)
    db_path = copy_db()
    print("OK")

    try:
        if args.read:
            fetch_full_message(db_path, args.read)
        elif args.recent:
            rows = search_messages(db_path, limit=args.recent, days=args.days)
            print_list(rows)
        elif args.unread:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            conditions = [f"accountPk = {ACCOUNT_PK}", "unseen = 1", "inSent = 0"]
            params = []
            if args.days:
                cutoff = datetime.now(timezone.utc).timestamp() - (args.days * 86400)
                conditions.append("receivedDate >= ?")
                params.append(cutoff)
            where = " AND ".join(conditions)
            params.append(args.limit)
            cur.execute(f"""
                SELECT pk, receivedDate, subject, messageFrom, messageTo,
                       messageCc, shortBody, messageId, inSent,
                       numberOfFileAttachments
                FROM messages WHERE {where}
                ORDER BY receivedDate DESC LIMIT ?
            """, params)
            rows = cur.fetchall()
            conn.close()
            print_list(rows)
        else:
            rows = search_messages(
                db_path,
                search=args.search,
                from_addr=args.from_addr,
                to_addr=args.to,
                sent_only=args.sent,
                limit=args.limit,
                days=args.days,
            )
            print_list(rows)
    finally:
        # tmpファイル削除
        import shutil as _shutil
        _shutil.rmtree(os.path.dirname(db_path), ignore_errors=True)


if __name__ == "__main__":
    main()
