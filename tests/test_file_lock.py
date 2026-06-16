"""file_lock のユニットテスト。"""

import json
import tempfile
import unittest
from pathlib import Path

from lib.file_lock import atomic_json_read, atomic_json_write


class TestAtomicJsonRead(unittest.TestCase):
    def test_read_valid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"key": "value"}, f)
            path = Path(f.name)
        try:
            data = atomic_json_read(path)
            self.assertEqual(data, {"key": "value"})
        finally:
            path.unlink()

    def test_file_not_found(self):
        data = atomic_json_read(Path("/tmp/nonexistent_test_file_12345.json"))
        self.assertEqual(data, {})

    def test_custom_default(self):
        data = atomic_json_read(Path("/tmp/nonexistent_test_file_12345.json"), default=[])
        self.assertEqual(data, [])

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            path = Path(f.name)
        try:
            data = atomic_json_read(path, default={"fallback": True})
            self.assertEqual(data, {"fallback": True})
        finally:
            path.unlink()


class TestAtomicJsonWrite(unittest.TestCase):
    def test_write_and_read(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            result = atomic_json_write(path, {"hello": "world"})
            self.assertTrue(result)
            with open(path) as f:
                data = json.load(f)
            self.assertEqual(data, {"hello": "world"})
        finally:
            path.unlink(missing_ok=True)

    def test_write_creates_parent_dirs(self):
        parent = Path(tempfile.mkdtemp()) / "sub" / "dir"
        path = parent / "test.json"
        try:
            result = atomic_json_write(path, {"nested": True})
            self.assertTrue(result)
            self.assertTrue(path.exists())
        finally:
            import shutil
            shutil.rmtree(parent.parent, ignore_errors=True)

    def test_roundtrip_unicode(self):
        path = Path(tempfile.mktemp(suffix=".json"))
        try:
            data = {"商品名": "プラダ バッグ", "価格": 80000}
            atomic_json_write(path, data)
            loaded = atomic_json_read(path)
            self.assertEqual(loaded, data)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
