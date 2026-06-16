"""Selfridges (selfridges.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class SELFRIDGESStrategy(SelectorBasedStrategy):
    _domain = "selfridges.com"
    _price_selectors = (
        "[class*='ProductPrice']",
        "[class*='product-price']",
        "[class*='price-block']",
        "#productPrice",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='ProductPrice'], [class*='product-price'], [itemprop='price']"
    _price_wait_timeout_ms = 30_000
    _add_to_bag_selectors = (
        "[class*='addToBag']",
        "[class*='add-to-bag']",
        "button[aria-label*='Add to bag']",
        "button[data-testid='add-to-bag']",
    )
    _out_of_stock_selectors = (
        "[class*='outOfStock']",
        "[class*='out-of-stock']",
        "[class*='sold-out']",
    )
    _out_of_stock_texts = frozenset({"sold out", "out of stock", "notify me", "unavailable"})
    _in_stock_texts = frozenset({"add to bag", "add to basket"})
    _use_ogp_price = True
