"""scraper.price_sanity のテスト。"""

from __future__ import annotations

import unittest

from lib.scraper.price_sanity import (
    infer_currency_from_url,
    is_plausible_supply_price,
    normalize_raw_price_string,
    price_matches_url_item_id,
)
from lib.scraper.utils import parse_price_string


class TestPriceSanity(unittest.TestCase):
    def test_infer_jp_farfetch(self) -> None:
        u = "https://www.farfetch.com/jp/shopping/women/prada-item-1.aspx"
        self.assertEqual(infer_currency_from_url(u), "JPY")

    def test_normalize_none_prefix(self) -> None:
        self.assertEqual(normalize_raw_price_string("None 473,000"), "473,000")

    def test_parse_none_prefix_price(self) -> None:
        val, cur = parse_price_string("None473000")
        self.assertEqual(val, 473000.0)
        self.assertIsNone(cur)

    def test_reject_item_id_as_price(self) -> None:
        url = "https://www.farfetch.com/jp/shopping/women/prada-item-16787669.aspx"
        self.assertTrue(price_matches_url_item_id(url, 16_787_669.0))
        self.assertFalse(
            is_plausible_supply_price(
                16_787_669.0, "JPY", url, buyma_price_jpy=93_800, exchange_rate=1.0,
            )
        )
        self.assertTrue(
            is_plausible_supply_price(
                132_000.0, "JPY", url, buyma_price_jpy=93_800, exchange_rate=1.0,
            )
        )

    def test_reject_absurd_jpy_farfetch(self) -> None:
        url = (
            "https://www.farfetch.com/jp/shopping/women/"
            "prada-re-nylon-item-16787669.aspx"
        )
        self.assertFalse(
            is_plausible_supply_price(
                473_000.0, "JPY", url, buyma_price_jpy=93_800, exchange_rate=1.0,
            )
        )
        self.assertFalse(
            is_plausible_supply_price(
                473_000.0, "EUR", url, buyma_price_jpy=93_800, exchange_rate=184.89,
            )
        )
        self.assertFalse(
            is_plausible_supply_price(
                473_000.0,
                "JPY",
                url,
                buyma_price_jpy=93_800,
                exchange_rate=1.0,
                raw_price="None473000",
            )
        )

    def test_accept_reasonable_eur(self) -> None:
        url = "https://www.farfetch.com/shopping/women/x.aspx"
        self.assertTrue(
            is_plausible_supply_price(
                450.0, "EUR", url, buyma_price_jpy=93_800, exchange_rate=184.89,
            )
        )


if __name__ == "__main__":
    unittest.main()
