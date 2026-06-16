"""lib.http_client のテスト。"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from lib import http_client


def _resp(status: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    return r


class TestHttpClientRetry:
    def test_get_success_no_retry(self):
        resp = _resp(200)
        with patch("requests.get", return_value=resp) as m:
            out = http_client.get("https://example.com")
        assert out is resp
        assert m.call_count == 1

    def test_default_timeout_applied(self):
        resp = _resp(200)
        with patch("requests.get", return_value=resp) as m:
            http_client.get("https://example.com")
        assert m.call_args.kwargs["timeout"] == http_client.DEFAULT_TIMEOUT

    def test_explicit_timeout_preserved(self):
        resp = _resp(200)
        with patch("requests.post", return_value=resp) as m:
            http_client.post("https://example.com", timeout=5)
        assert m.call_args.kwargs["timeout"] == 5

    def test_retries_on_retryable_status_then_succeeds(self):
        resp = [_resp(503), _resp(503), _resp(200)]
        with patch("requests.get", side_effect=resp) as m, \
                patch("time.sleep"):
            out = http_client.get("https://example.com")
        assert out.status_code == 200
        assert m.call_count == 3

    def test_returns_last_response_when_all_retries_fail(self):
        with patch("requests.get", side_effect=[_resp(500)] * 4) as m, \
                patch("time.sleep"):
            out = http_client.get("https://example.com")
        assert out.status_code == 500
        assert m.call_count == 4  # 初回 + 3 リトライ

    def test_retries_on_connection_error_then_raises(self):
        with patch(
            "requests.get",
            side_effect=requests.ConnectionError("boom"),
        ) as m, patch("time.sleep"), pytest.raises(requests.ConnectionError):
            http_client.get("https://example.com")
        assert m.call_count == 4

    def test_connection_error_then_success(self):
        ok = _resp(200)
        with patch(
            "requests.post",
            side_effect=[requests.ConnectionError("x"), ok],
        ) as m, patch("time.sleep"):
            out = http_client.post("https://example.com")
        assert out is ok
        assert m.call_count == 2

    def test_non_retryable_4xx_returned_immediately(self):
        resp = _resp(404)
        with patch("requests.get", return_value=resp) as m:
            out = http_client.get("https://example.com")
        assert out.status_code == 404
        assert m.call_count == 1
