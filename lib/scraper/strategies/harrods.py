"""Harrods (harrods.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class HARRODSStrategy(SelectorBasedStrategy):
    _domain = "harrods.com"
    _price_selectors = (
        "[class*='product__price']",
        "[class*='ProductPrice']",
        "[class*='price-wrapper']",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='product__price'], [class*='ProductPrice'], [itemprop='price']"
    _price_wait_timeout_ms = 30_000
    _add_to_bag_selectors = (
        "[class*='product__add-to-bag']",
        "[class*='AddToBag']",
        "button[aria-label*='Add to bag']",
        "button[data-testid='add-to-bag']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='soldOut']",
        "[class*='out-of-stock']",
        "[class*='unavailable']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "unavailable",
        "notify me", "sign up to be notified",
    })
    _in_stock_texts = frozenset({"add to bag", "add to basket"})
