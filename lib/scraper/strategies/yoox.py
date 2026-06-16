"""YOOX (yoox.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class YOOXStrategy(SelectorBasedStrategy):
    _domain = "yoox.com"
    _price_selectors = (
        "[class*='d-price']",
        "[class*='activatedPrice']",
        "[class*='fullPrice']",
        "[class*='product-price']",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='d-price'], [class*='activatedPrice'], [itemprop='price']"
    _price_wait_timeout_ms = 12_000
    _add_to_bag_selectors = (
        "[class*='d-addtobag']",
        "[class*='addtobag']",
        "[class*='AddToBag']",
        "button[aria-label*='Add to bag']",
        "#addtobag",
    )
    _out_of_stock_selectors = (
        "[class*='d-soldout']",
        "[class*='soldout']",
        "[class*='sold-out']",
        "[class*='outOfStock']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "not available", "esaurito",
        "out of stock", "this item is no longer available",
    })
    _in_stock_texts = frozenset({"add to bag", "add to cart"})
