"""LUISAVIAROMA (luisaviaroma.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class LUISAVIAROMAStrategy(SelectorBasedStrategy):
    _domain = "luisaviaroma.com"
    _price_selectors = (
        "[class*='ProductPrice__listPrice']",
        "[class*='ProductPrice']",
        "[class*='product-price']",
        "[class*='pdp-price']",
        "[data-testid='price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='ProductPrice'], [itemprop='price']"
    _price_wait_timeout_ms = 30_000
    _add_to_bag_selectors = (
        "#btnAddToCart",
        "[class*='AddToCart']",
        "[class*='add-to-cart']",
        "button[aria-label*='Add to cart']",
    )
    _out_of_stock_selectors = (
        "[class*='soldOut']",
        "[class*='sold-out']",
        "[class*='notifyMe']",
    )
    _out_of_stock_texts = frozenset({"sold out", "notify me", "out of stock", "not available"})
    _in_stock_texts = frozenset({"add to cart", "add to bag"})
