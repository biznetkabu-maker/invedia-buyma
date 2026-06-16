"""buyma_item_parser.py のユニットテスト。"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from lib.buyma_item_parser import (
    _extract_jpy_price,
    _extract_title,
    fetch_buyma_item_info,
    fetch_buyma_item_info_sync,
    parse_buyma_item_from_html,
)


class TestParseBuymaItem(unittest.TestCase):

    def test_og_title_and_brand_json(self) -> None:
        html = """
        <html>
        <meta property="og:title" content="CELINE トリオバッグ スモール ブラック" />
        <script>{"brand": {"name": "CELINE"}, "name": "トリオバッグ スモール"}</script>
        <div>この商品の型番：ARC58-BLK</div>
        <span>¥210,000</span>
        </html>
        """
        info = parse_buyma_item_from_html(html, buyma_url="https://www.buyma.com/items/123/")
        self.assertEqual(info.brand, "CELINE")
        self.assertIn("トリオ", info.product_name)
        self.assertEqual(info.style_id, "ARC58-BLK")
        self.assertEqual(info.price_jpy, 210000)

    def test_title_split_without_json_brand(self) -> None:
        html = """
        <title>PRADA サフィアーノ 財布 | BUYMA</title>
        """
        info = parse_buyma_item_from_html(html)
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("財布", info.product_name)

    def test_outlet_prefix_title_brand(self) -> None:
        html = """
        <title>♪直営アウトレット♪PRADA Tシャツ UJN880 1UIR | BUYMA</title>
        """
        info = parse_buyma_item_from_html(html)
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("Tシャツ", info.product_name)

    def test_japanese_decorated_title_brand(self) -> None:
        html = """
        <title>【セール】プラダ☆キルティング ドックキャリーバッグ☆2VC039 | BUYMA</title>
        """
        info = parse_buyma_item_from_html(html)
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("ドックキャリーバッグ", info.product_name)

    def test_sale_crochet_tote_brand(self) -> None:
        html = """
        <title>【セール】プラダ☆ロゴ刺繍 クロシェトートバッグ☆1BG493 2M2T | BUYMA</title>
        """
        info = parse_buyma_item_from_html(html)
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("クロシェ", info.product_name)

    def test_bracket_prada_with_model_code_prefix(self) -> None:
        html = """
        <title>【PRADA】2X3119 3LKK トライアングルロゴ レザーサンダル | BUYMA</title>
        <meta property="og:title" content="【PRADA】2X3119 3LKK トライアングルロゴ レザーサンダル" />
        <script>{"productID": "129042477"}</script>
        """
        info = parse_buyma_item_from_html(html)
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("2X3119", info.product_name)
        self.assertEqual(info.style_id, "2X3119")

        from lib.product_identity import VariantKey

        variant = VariantKey.resolve(
            brand=info.brand,
            product_name=info.product_name,
            buyma_style_id="129042477",
            raw_product_name=info.product_name,
            raw_title=info.raw_title,
        )
        self.assertEqual(variant.match_ref, "2X3119")

    def test_kids_sneaker_rejects_json_buyma_brand(self) -> None:
        """JSON-LD brand=BUYMA でもタイトル先頭のプラダ → PRADA。"""
        html = """
        <title>プラダ キッズスニーカー 0P0211 ベルクロ アイボリー 17433486 | BUYMA</title>
        <meta property="og:title" content="プラダ キッズスニーカー 0P0211 ベルクロ アイボリー 17433486" />
        <script>{"brand": {"name": "BUYMA"}, "name": "プラダ キッズスニーカー"}</script>
        """
        info = parse_buyma_item_from_html(html, buyma_url="https://www.buyma.com/item/130198840/")
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("キッズ", info.product_name)
        self.assertEqual(info.style_id, "0P0211")

    def test_pouch_og_without_prada_prefix_uses_json_name(self) -> None:
        """og:title に PRADA が無くても JSON name から PRADA を復元。"""
        html = """
        <meta property="og:title" content="ポーチ SPEEDROCK 2NE067 2HE1 リナイロン" />
        <script>{"brand":{"name":"BUYMA"},"name":"PRADA ポーチ SPEEDROCK 2NE067 2HE1 リナイロン"}</script>
        """
        info = parse_buyma_item_from_html(html, buyma_url="https://www.buyma.com/item/131116731/")
        self.assertEqual(info.brand, "PRADA")
        self.assertIn("SPEEDROCK", info.product_name)
        self.assertEqual(info.style_id, "2NE067")

    def test_empty_html_uses_fallback_name(self) -> None:
        info = parse_buyma_item_from_html("", buyma_url="https://www.buyma.com/items/1/")
        self.assertEqual(info.product_name, "（商品名未取得）")
        self.assertIsNone(info.price_jpy)


class TestExtractHelpers(unittest.TestCase):
    def test_extract_title_empty(self):
        self.assertEqual(_extract_title("<html></html>"), "")

    def test_extract_title_tag_strips_buyma_suffix(self):
        self.assertEqual(_extract_title("<title>FOO BAR | BUYMA</title>"), "FOO BAR")

    def test_extract_jpy_price_yen_suffix(self):
        self.assertEqual(_extract_jpy_price("価格 198,000 円"), 198000)

    def test_extract_jpy_price_jpy_prefix(self):
        self.assertEqual(_extract_jpy_price("JPY 250,000"), 250000)

    def test_extract_jpy_price_none(self):
        self.assertIsNone(_extract_jpy_price("価格未定"))


class TestFetchItemInfo(unittest.TestCase):
    def test_fetch_rejects_non_item_url(self):
        result = asyncio.run(fetch_buyma_item_info("https://example.com/x"))
        self.assertIsNone(result)

    def test_sync_wrapper_returns_async_result(self):
        sentinel = object()

        async def _fake(url, **kwargs):
            return sentinel

        with patch("lib.buyma_item_parser.fetch_buyma_item_info", side_effect=_fake):
            result = fetch_buyma_item_info_sync("https://www.buyma.com/items/1/")
        self.assertIs(result, sentinel)


if __name__ == "__main__":
    unittest.main()
