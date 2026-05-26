"""supply_url_cache.py のユニットテスト。"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import lib.supply_url_cache as cache_mod


class TestSupplyUrlCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self._orig_file = cache_mod._DEFAULT_CACHE_FILE
        cache_mod._DEFAULT_CACHE_FILE = Path(self.tmp.name)
        self._env_patch = patch.dict(
            os.environ,
            {
                "SUPPLY_URL_CACHE": "1",
                "SUPPLY_URL_CACHE_TTL_DAYS": "90",
                "SUPPLY_URL_CACHE_MIN_GRADE": "A",
            },
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()
        cache_mod._DEFAULT_CACHE_FILE = self._orig_file
        os.unlink(self.tmp.name)

    def test_cache_key_normalizes_brand_and_mpn(self):
        self.assertEqual(cache_mod.cache_key("prada", "1ml506"), "PRADA|1ML506")
        self.assertEqual(cache_mod.cache_key("", "1ML506"), "")

    def test_store_and_lookup(self):
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        cache_mod.store_supply_urls("PRADA", "1ML506", [url], match_grade="A")
        hits = cache_mod.lookup_supply_urls("PRADA", "1ML506")
        self.assertEqual(hits, [url])

    def test_rejects_low_match_grade(self):
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        cache_mod.store_supply_urls("PRADA", "1ML506", [url], match_grade="B")
        self.assertEqual(cache_mod.lookup_supply_urls("PRADA", "1ML506"), [])

    def test_ttl_expiry(self):
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        with patch.dict(os.environ, {"SUPPLY_URL_CACHE_TTL_DAYS": "1"}, clear=False):
            cache_mod.store_supply_urls("PRADA", "1ML506", [url], match_grade="S")
            data = json.loads(Path(self.tmp.name).read_text(encoding="utf-8"))
            data["PRADA|1ML506"]["updated_at"] = time.time() - 86400 * 2
            Path(self.tmp.name).write_text(
                json.dumps(data), encoding="utf-8"
            )
            self.assertEqual(cache_mod.lookup_supply_urls("PRADA", "1ML506"), [])

    def test_lookup_skips_invalid_url_on_read(self):
        bad = "https://www.farfetch.com/jp/shopping/women/search/items.aspx?q=x"
        good = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        Path(self.tmp.name).write_text(
            json.dumps(
                {
                    "PRADA|1ML506": {
                        "brand": "PRADA",
                        "mpn": "1ML506",
                        "urls": [{"url": bad}, {"url": good}],
                        "updated_at": time.time(),
                    }
                }
            ),
            encoding="utf-8",
        )
        hits = cache_mod.lookup_supply_urls("PRADA", "1ML506")
        self.assertEqual(hits, [good])

    def test_disabled_by_env(self):
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-small-saffiano-leather-wallet-item-36404881.aspx"
        )
        with patch.dict(os.environ, {"SUPPLY_URL_CACHE": "0"}, clear=False):
            cache_mod.store_supply_urls("PRADA", "1ML506", [url], match_grade="A")
            self.assertEqual(cache_mod.lookup_supply_urls("PRADA", "1ML506"), [])


if __name__ == "__main__":
    unittest.main()
