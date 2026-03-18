"""
Lark (Feishu) API 共通モジュール

トークン取得・Bitable レコード操作・DM送信・Webhook通知を提供する。
lark_crm_monitor.py / deal_thankyou_email.py から抽出した最も成熟した実装。

Usage:
    from lib.config import load_config
    from lib.lark_api import lark_get_token, lark_list_records, send_lark_dm, send_lark_webhook

    cfg = load_config()
    token = lark_get_token(cfg)
    records = lark_list_records(token, table_id="tbl1rM86nAw9l3bP")
    send_lark_dm(token, open_id="ou_xxx", text="Hello")
    send_lark_webhook(cfg, "通知テスト")

注意:
    - CRM_BASE_TOKEN はデフォルトで cfg["lark"]["crm_base_token"] を使う。
      別の Base を操作する場合は base_token 引数で明示する。
    - lark_list_records はページネーション・リトライ・空レスポンス対策済み。
"""

import json
import time
import urllib.request
import urllib.error

from lib.retry import urlopen_with_retry

# デフォルトの Lark API ベースURL
LARK_API_BASE = "https://open.larksuite.com/open-apis"


# ── Token ──

def lark_get_token(cfg):
    """テナントアクセストークンを取得する。

    Args:
        cfg: load_config() の戻り値。cfg["lark"]["app_id"] と cfg["lark"]["app_secret"] を使用。

    Returns:
        str: tenant_access_token
    """
    app_id = cfg["lark"]["app_id"]
    app_secret = cfg["lark"]["app_secret"]

    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        f"{LARK_API_BASE}/auth/v3/tenant_access_token/internal",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen_with_retry(req, timeout=15) as r:
        return json.loads(r.read())["tenant_access_token"]


# ── Bitable Records ──

def lark_list_records(token, table_id, base_token=None, cfg=None,
                      filter_expr=None, page_size=500, fields=None,
                      max_retries=3):
    """Bitable テーブルの全レコードをページネーションで取得する。

    deal_thankyou_email.py の get_all_records() 相当。リトライ・空レスポンス対策付き。

    Args:
        token: lark_get_token() の戻り値
        table_id: テーブルID（例: "tbl1rM86nAw9l3bP"）
        base_token: Base トークン。省略時は cfg["lark"]["crm_base_token"]
        cfg: load_config() の戻り値。base_token 省略時に必要
        filter_expr: フィルター式（Lark Bitable filter 構文）
        page_size: 1ページあたりのレコード数（最大500）
        fields: 取得するフィールド名リスト（省略時は全フィールド）
        max_retries: API呼び出し失敗時のリトライ回数

    Returns:
        list[dict]: レコードのリスト。各要素は {"record_id": ..., "fields": {...}} 形式。
    """
    if base_token is None:
        if cfg is None:
            raise ValueError("base_token か cfg のどちらかを指定してください")
        base_token = cfg["lark"]["crm_base_token"]

    records = []
    page_token = None

    while True:
        url = (f"{LARK_API_BASE}/bitable/v1/apps/{base_token}"
               f"/tables/{table_id}/records?page_size={page_size}")
        if page_token:
            url += f"&page_token={page_token}"
        if filter_expr:
            url += f"&filter={urllib.request.quote(filter_expr)}"

        headers = {"Authorization": f"Bearer {token}"}

        # フィールド指定
        if fields:
            # Lark API は field_names パラメータで指定
            for fname in fields:
                url += f"&field_names={urllib.request.quote(fname)}"

        req = urllib.request.Request(url, headers=headers)
        result = None

        for attempt in range(max_retries):
            try:
                with urlopen_with_retry(req, timeout=30, max_retries=2) as r:
                    body = r.read()
                    if not body:
                        print(f"[WARN] Empty response (attempt {attempt + 1}/{max_retries}), retrying...")
                        time.sleep(5 * (attempt + 1))
                        continue
                    result = json.loads(body)
                    break
            except (urllib.error.URLError, json.JSONDecodeError, ValueError) as e:
                print(f"[WARN] Lark API error (attempt {attempt + 1}/{max_retries}): {e}")
                time.sleep(5 * (attempt + 1))

        if result is None:
            print(f"[ERROR] Failed to fetch records after {max_retries} attempts for table {table_id}")
            break

        data = result.get("data", {})
        records.extend(data.get("items", []))

        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        time.sleep(0.3)

    return records


def lark_get_record_count(token, table_id, base_token=None, cfg=None):
    """テーブルの総レコード数を返す。

    Args:
        token: lark_get_token() の戻り値
        table_id: テーブルID
        base_token: Base トークン。省略時は cfg から取得
        cfg: load_config() の戻り値

    Returns:
        int: レコード数
    """
    if base_token is None:
        if cfg is None:
            raise ValueError("base_token か cfg のどちらかを指定してください")
        base_token = cfg["lark"]["crm_base_token"]

    url = (f"{LARK_API_BASE}/bitable/v1/apps/{base_token}"
           f"/tables/{table_id}/records?page_size=1")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urlopen_with_retry(req, timeout=15) as r:
        result = json.loads(r.read())
        return result.get("data", {}).get("total", 0)


def lark_update_record(token, table_id, record_id, fields,
                       base_token=None, cfg=None):
    """Bitable レコードを更新する。

    Args:
        token: lark_get_token() の戻り値
        table_id: テーブルID
        record_id: 更新対象のレコードID
        fields: 更新するフィールドの辞書
        base_token: Base トークン
        cfg: load_config() の戻り値

    Returns:
        dict: API レスポンス
    """
    if base_token is None:
        if cfg is None:
            raise ValueError("base_token か cfg のどちらかを指定してください")
        base_token = cfg["lark"]["crm_base_token"]

    url = (f"{LARK_API_BASE}/bitable/v1/apps/{base_token}"
           f"/tables/{table_id}/records/{record_id}")
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    with urlopen_with_retry(req, timeout=15) as r:
        return json.loads(r.read())


def lark_create_record(token, table_id, fields, base_token=None, cfg=None):
    """Bitable レコードを新規作成する。

    Args:
        token: lark_get_token() の戻り値
        table_id: テーブルID
        fields: フィールドの辞書
        base_token: Base トークン
        cfg: load_config() の戻り値

    Returns:
        dict: API レスポンス
    """
    if base_token is None:
        if cfg is None:
            raise ValueError("base_token か cfg のどちらかを指定してください")
        base_token = cfg["lark"]["crm_base_token"]

    url = (f"{LARK_API_BASE}/bitable/v1/apps/{base_token}"
           f"/tables/{table_id}/records")
    data = json.dumps({"fields": fields}).encode()
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen_with_retry(req, timeout=15) as r:
        return json.loads(r.read())


# ── Messaging ──

def send_lark_dm(token, open_id, text, max_chunk_size=1900):
    """Lark Bot 経由で個人メッセージ（DM）を送信する。

    長いメッセージは自動的に分割して送信する（Lark の文字数制限対策）。

    Args:
        token: lark_get_token() の戻り値
        open_id: 送信先の open_id。None の場合は何もしない。
        text: 送信テキスト
        max_chunk_size: 1メッセージあたりの最大文字数（デフォルト1900）
    """
    if not open_id:
        return

    chunks = [text[i:i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]

    for chunk in chunks:
        data = json.dumps({
            "receive_id": open_id,
            "msg_type": "text",
            "content": json.dumps({"text": chunk}),
        }).encode()

        req = urllib.request.Request(
            f"{LARK_API_BASE}/im/v1/messages?receive_id_type=open_id",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen_with_retry(req, timeout=15) as r:
                result = json.loads(r.read())
                if result.get("code") != 0:
                    print(f"  Lark DM error: {result.get('msg', 'unknown')}")
        except urllib.error.HTTPError as e:
            print(f"  Lark DM error: {e.code} {e.read().decode()[:200]}")
        time.sleep(0.3)


def send_lark_bot_message(token, user_identifier, text, id_type="email"):
    """Lark Bot で個人メッセージを送信する（email / user_id / open_id 指定可）。

    send_lark_dm は open_id 専用だが、こちらは id_type を選べる。
    外部委託（政木）など open_id を持たないユーザーへは email で送信可能。

    Args:
        token: lark_get_token() の戻り値
        user_identifier: 送信先（email, user_id, or open_id）
        text: 送信テキスト
        id_type: "email", "user_id", or "open_id"

    Returns:
        bool: 送信成功なら True
    """
    if not user_identifier:
        return False

    data = json.dumps({
        "receive_id": user_identifier,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }).encode()

    req = urllib.request.Request(
        f"{LARK_API_BASE}/im/v1/messages?receive_id_type={id_type}",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen_with_retry(req, timeout=15) as r:
            result = json.loads(r.read())
            if result.get("code") == 0:
                return True
            else:
                print(f"  Lark Bot message error: {result.get('msg', 'unknown')}")
                return False
    except Exception as e:
        print(f"  Lark Bot message failed: {e}")
        return False


def send_lark_webhook(cfg, text):
    """Lark Webhook でグループチャットに通知を送信する。

    Args:
        cfg: load_config() の戻り値。cfg["notifications"]["lark_webhook_url"] を使用。
        text: 通知テキスト

    Returns:
        bool: 送信成功なら True
    """
    webhook = cfg.get("notifications", {}).get("lark_webhook_url", "")
    if not webhook:
        print("  [WARN] lark_webhook_url not configured")
        return False

    data = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
    req = urllib.request.Request(
        webhook, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        urlopen_with_retry(req, timeout=15).close()
        return True
    except Exception as e:
        print(f"  Lark Webhook error: {e}")
        return False
