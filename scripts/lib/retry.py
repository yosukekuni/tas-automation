"""
Exponential Backoff リトライモジュール

全API呼び出しに指数バックオフ付きリトライを提供する。
デコレータ・関数ラッパーの2パターンで使用可能。

Usage (デコレータ):
    from lib.retry import retry

    @retry(max_retries=5, backoff_base=1, backoff_max=60)
    def call_api():
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read())

Usage (関数ラッパー):
    from lib.retry import urlopen_with_retry

    # urllib.request.urlopen の代替として使用
    with urlopen_with_retry(req, timeout=15) as r:
        data = json.loads(r.read())

リトライ対象:
    - HTTP 429 (Rate Limit), 500, 502, 503, 504
    - ConnectionError, Timeout, URLError

リトライ非対象:
    - HTTP 400, 401, 403, 404（クライアントエラー）
    - その他の明示的なクライアントエラー

注意:
    - ジッター（ランダム遅延）を含むため、同時リクエストの集中を防止
    - ログは print で出力（GitHub Actions / 標準ログ互換）
"""

import functools
import random
import time
import urllib.error
import urllib.request

# リトライ対象のHTTPステータスコード
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# リトライ非対象（即座に失敗させる）
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}


def _is_retryable_exception(exc):
    """例外がリトライ対象かどうかを判定する。

    Args:
        exc: 発生した例外

    Returns:
        bool: リトライすべきなら True
    """
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in NON_RETRYABLE_STATUS_CODES:
            return False
        if exc.code in RETRYABLE_STATUS_CODES:
            return True
        # 未知のサーバーエラー (5xx) もリトライ
        if exc.code >= 500:
            return True
        return False

    if isinstance(exc, urllib.error.URLError):
        # ネットワークエラー（DNS解決失敗、接続拒否等）
        return True

    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True

    # socket.timeout は TimeoutError のサブクラス（Python 3.3+）
    return False


def _calculate_delay(attempt, backoff_base, backoff_max):
    """指数バックオフ + ジッターで待機時間を計算する。

    Args:
        attempt: 現在の試行回数（0始まり）
        backoff_base: 基本待機時間（秒）
        backoff_max: 最大待機時間（秒）

    Returns:
        float: 待機秒数
    """
    # 指数バックオフ: base * 2^attempt
    delay = backoff_base * (2 ** attempt)
    # 最大値でキャップ
    delay = min(delay, backoff_max)
    # ジッター: 0.5 ~ 1.0 倍のランダム
    jitter = random.uniform(0.5, 1.0)
    return delay * jitter


def retry(max_retries=5, backoff_base=1, backoff_max=60,
          retryable_check=None, on_retry=None):
    """API呼び出し関数にExponential Backoffリトライを追加するデコレータ。

    Args:
        max_retries: 最大リトライ回数（初回を含まない）。デフォルト5。
        backoff_base: 初回リトライの基本待機秒数。デフォルト1。
        backoff_max: 最大待機秒数。デフォルト60。
        retryable_check: カスタムのリトライ判定関数。Noneならデフォルト判定。
        on_retry: リトライ時のコールバック(attempt, delay, exception)。

    Returns:
        デコレータ関数

    Example:
        @retry(max_retries=3)
        def fetch_data():
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
    """
    check_fn = retryable_check or _is_retryable_exception

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e

                    if attempt >= max_retries:
                        break

                    if not check_fn(e):
                        # リトライ非対象 → 即座にraise
                        raise

                    delay = _calculate_delay(attempt, backoff_base, backoff_max)

                    # ログ出力
                    error_desc = _format_error(e)
                    print(f"  [Retry] {func.__name__} "
                          f"attempt {attempt + 1}/{max_retries} failed: {error_desc} "
                          f"- retrying in {delay:.1f}s")

                    if on_retry:
                        on_retry(attempt, delay, e)

                    time.sleep(delay)

            # 全リトライ失敗
            error_desc = _format_error(last_exception)
            print(f"  [Retry] {func.__name__} "
                  f"ALL {max_retries + 1} attempts failed: {error_desc}")
            raise last_exception

        return wrapper
    return decorator


def urlopen_with_retry(req, timeout=30, max_retries=5,
                       backoff_base=1, backoff_max=60):
    """urllib.request.urlopen のリトライ付きラッパー。

    urllib.request.urlopen と同じインターフェースで使用可能。
    コンテキストマネージャとして使う場合は戻り値をそのまま使う。

    Args:
        req: urllib.request.Request オブジェクトまたはURL文字列
        timeout: タイムアウト秒数
        max_retries: 最大リトライ回数
        backoff_base: 初回リトライの基本待機秒数
        backoff_max: 最大待機秒数

    Returns:
        http.client.HTTPResponse: レスポンスオブジェクト

    Raises:
        urllib.error.HTTPError: リトライ非対象のHTTPエラー or 全リトライ失敗
        urllib.error.URLError: 全リトライ失敗後のネットワークエラー

    Example:
        # 既存コードの urlopen を置き換え:
        # before: with urllib.request.urlopen(req, timeout=15) as r:
        # after:  with urlopen_with_retry(req, timeout=15) as r:
        with urlopen_with_retry(req, timeout=15) as r:
            data = json.loads(r.read())
    """
    req_desc = _get_request_desc(req)
    last_exception = None

    for attempt in range(max_retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            last_exception = e

            if attempt >= max_retries:
                break

            if not _is_retryable_exception(e):
                raise

            delay = _calculate_delay(attempt, backoff_base, backoff_max)

            error_desc = _format_error(e)
            print(f"  [Retry] urlopen {req_desc} "
                  f"attempt {attempt + 1}/{max_retries} failed: {error_desc} "
                  f"- retrying in {delay:.1f}s")

            time.sleep(delay)

    error_desc = _format_error(last_exception)
    print(f"  [Retry] urlopen {req_desc} "
          f"ALL {max_retries + 1} attempts failed: {error_desc}")
    raise last_exception


def patch_urlopen(max_retries=5, backoff_base=1, backoff_max=60):
    """urllib.request.urlopen をモンキーパッチしてリトライ機能を追加する。

    各スクリプトの先頭で1回呼ぶだけで、そのプロセス内の全urlopen呼び出しに
    Exponential Backoffが適用される。既にパッチ済みの場合は何もしない。

    Args:
        max_retries: 最大リトライ回数。デフォルト5。
        backoff_base: 初回リトライの基本待機秒数。デフォルト1。
        backoff_max: 最大待機秒数。デフォルト60。

    Usage:
        # スクリプトの先頭で1回だけ呼ぶ
        import sys; sys.path.insert(0, str(Path(__file__).parent))
        from lib.retry import patch_urlopen; patch_urlopen()

    注意:
        - lolipop_waf.py のセッション管理のような opener.open() 呼び出しは
          urlopen 経由ではないため、パッチの影響を受けない（意図通り）。
        - 再帰防止フラグ付き。パッチ内部の urlopen は元の関数を呼ぶ。
    """
    if getattr(urllib.request, '_retry_patched', False):
        return  # 既にパッチ済み

    _original_urlopen = urllib.request.urlopen

    def _patched_urlopen(url, data=None, timeout=None, **kwargs):
        # timeout 引数の処理
        open_kwargs = {}
        if timeout is not None:
            open_kwargs['timeout'] = timeout
        if data is not None:
            open_kwargs['data'] = data

        req_desc = _get_request_desc(url)
        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                return _original_urlopen(url, **open_kwargs, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt >= max_retries:
                    break

                if not _is_retryable_exception(e):
                    raise

                delay = _calculate_delay(attempt, backoff_base, backoff_max)

                error_desc = _format_error(e)
                print(f"  [Retry] urlopen {req_desc} "
                      f"attempt {attempt + 1}/{max_retries} failed: "
                      f"{error_desc} - retrying in {delay:.1f}s")

                time.sleep(delay)

        error_desc = _format_error(last_exception)
        print(f"  [Retry] urlopen {req_desc} "
              f"ALL {max_retries + 1} attempts failed: {error_desc}")
        raise last_exception

    urllib.request.urlopen = _patched_urlopen
    urllib.request._retry_patched = True
    print("[Retry] urllib.request.urlopen patched with exponential backoff "
          f"(max_retries={max_retries}, base={backoff_base}s, max={backoff_max}s)")


def _format_error(exc):
    """例外を短い説明文字列にフォーマットする。"""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        return f"URLError: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def _get_request_desc(req):
    """リクエストオブジェクトから説明文字列を生成する。"""
    if isinstance(req, urllib.request.Request):
        method = req.get_method()
        url = req.full_url
        # URLが長い場合は末尾を省略
        if len(url) > 80:
            url = url[:77] + "..."
        return f"{method} {url}"
    if isinstance(req, str):
        return req[:80]
    return str(req)[:80]
