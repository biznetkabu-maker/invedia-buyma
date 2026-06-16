"""リトライ付き共通 HTTP クライアント。

一時的なネットワーク障害や 429/5xx を指数バックオフで自動リトライする
共通ヘルパを提供する。各モジュールが個別に `requests.get/post` を呼ぶ代わりに
このモジュール経由で呼ぶことで、障害耐性を統一する。

実装は `requests.<method>` を呼び出し時に解決するため、`requests.post` を
パッチするテストとも互換性がある。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

# リトライ対象のステータスコード（レート制限・一時的なサーバエラー）
DEFAULT_RETRY_STATUSES = (429, 500, 502, 503, 504)
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5
DEFAULT_TIMEOUT = 15


def request(
    method: str,
    url: str,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    retry_statuses: tuple[int, ...] = DEFAULT_RETRY_STATUSES,
    **kwargs: Any,
) -> requests.Response:
    """指数バックオフ付きでリクエストを送る。

    接続エラー・タイムアウト・リトライ対象ステータスを最大 `retries` 回まで
    再試行する。timeout 未指定なら既定値を付与する。
    """
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    func = getattr(requests, method.lower())
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = func(url, **kwargs)
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            logger.debug(
                "HTTP %s %s 失敗（%s）リトライ %d/%d",
                method, url, exc, attempt + 1, retries,
            )
        else:
            status = getattr(resp, "status_code", None)
            if attempt < retries and isinstance(status, int) and status in retry_statuses:
                logger.debug(
                    "HTTP %s %s status=%s リトライ %d/%d",
                    method, url, resp.status_code, attempt + 1, retries,
                )
            else:
                return resp
        time.sleep(backoff_factor * (2 ** attempt))
    if last_exc is not None:
        raise last_exc
    return resp


def get(url: str, **kwargs: Any) -> requests.Response:
    """リトライ付き GET。"""
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> requests.Response:
    """リトライ付き POST。"""
    return request("POST", url, **kwargs)
