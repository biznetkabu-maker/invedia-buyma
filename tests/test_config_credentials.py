"""config._resolve_credentials の一時ファイル処理テスト。"""

from __future__ import annotations

import json
import os
import stat
import unittest
from unittest.mock import patch

from lib.config import Config


_FAKE_JSON = json.dumps({"type": "service_account", "project_id": "x"})


class TestResolveCredentials(unittest.TestCase):
    def test_local_path_when_no_json(self):
        with patch.dict("os.environ", {"CREDENTIALS_PATH": "my_creds.json"}, clear=False):
            os.environ.pop("GOOGLE_CREDENTIALS_JSON", None)
            path, tmp = Config._resolve_credentials()
        self.assertEqual(path, "my_creds.json")
        self.assertIsNone(tmp)

    def test_json_written_to_secure_tempfile(self):
        with patch.dict("os.environ", {"GOOGLE_CREDENTIALS_JSON": _FAKE_JSON}):
            path, tmp = Config._resolve_credentials()
        try:
            self.assertEqual(path, tmp)
            self.assertTrue(os.path.exists(tmp))
            # 所有者のみ読み書き可能（0o600）
            mode = stat.S_IMODE(os.stat(tmp).st_mode)
            self.assertEqual(mode, 0o600)
            with open(tmp) as f:
                self.assertEqual(json.load(f)["project_id"], "x")
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)

    def test_cleanup_removes_tempfile(self):
        with patch.dict("os.environ", {"GOOGLE_CREDENTIALS_JSON": _FAKE_JSON}):
            cfg = Config.from_env()
        tmp = cfg._tmp_credentials
        self.assertIsNotNone(tmp)
        self.assertTrue(os.path.exists(tmp))
        cfg.cleanup()
        self.assertFalse(os.path.exists(tmp))
        # 二重呼び出しでも例外を出さない
        cfg.cleanup()


if __name__ == "__main__":
    unittest.main()
