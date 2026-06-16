"""_sheets_retry デコレータのユニットテスト。"""

import unittest
from unittest.mock import MagicMock, patch

from gspread.exceptions import APIError

from lib.sheet_manager import _sheets_retry


class TestSheetsRetry(unittest.TestCase):
    """_sheets_retry のテスト。"""

    def _make_api_error(self, status_code: int) -> APIError:
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = f"Error {status_code}"
        return APIError(resp)

    @patch("lib.sheet_manager.time.sleep")
    def test_retries_on_429(self, mock_sleep):
        fn = MagicMock(side_effect=[self._make_api_error(429), "ok"])
        wrapped = _sheets_retry(max_retries=3, base_wait=1.0)(fn)
        result = wrapped()
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("lib.sheet_manager.time.sleep")
    def test_retries_on_500(self, mock_sleep):
        fn = MagicMock(side_effect=[self._make_api_error(500), "ok"])
        wrapped = _sheets_retry(max_retries=3, base_wait=1.0)(fn)
        result = wrapped()
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)

    @patch("lib.sheet_manager.time.sleep")
    def test_retries_on_503(self, mock_sleep):
        fn = MagicMock(side_effect=[self._make_api_error(503), "ok"])
        wrapped = _sheets_retry(max_retries=3, base_wait=1.0)(fn)
        result = wrapped()
        self.assertEqual(result, "ok")

    @patch("lib.sheet_manager.time.sleep")
    def test_does_not_retry_on_400(self, mock_sleep):
        fn = MagicMock(side_effect=self._make_api_error(400))
        wrapped = _sheets_retry(max_retries=3, base_wait=1.0)(fn)
        with self.assertRaises(APIError):
            wrapped()
        self.assertEqual(fn.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("lib.sheet_manager.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep):
        fn = MagicMock(side_effect=self._make_api_error(429))
        wrapped = _sheets_retry(max_retries=2, base_wait=1.0)(fn)
        with self.assertRaises(APIError):
            wrapped()
        self.assertEqual(fn.call_count, 3)  # 1 initial + 2 retries

    def test_no_error_passes_through(self):
        fn = MagicMock(return_value="ok")
        wrapped = _sheets_retry()(fn)
        self.assertEqual(wrapped(), "ok")
        self.assertEqual(fn.call_count, 1)

    @patch("lib.sheet_manager.time.sleep")
    def test_exponential_backoff(self, mock_sleep):
        fn = MagicMock(side_effect=[
            self._make_api_error(429),
            self._make_api_error(429),
            "ok",
        ])
        wrapped = _sheets_retry(max_retries=3, base_wait=10.0)(fn)
        result = wrapped()
        self.assertEqual(result, "ok")
        calls = mock_sleep.call_args_list
        self.assertEqual(calls[0][0][0], 10.0)  # base_wait * 1
        self.assertEqual(calls[1][0][0], 20.0)  # base_wait * 2


if __name__ == "__main__":
    unittest.main()
