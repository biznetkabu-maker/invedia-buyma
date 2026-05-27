"""Saks Fifth Avenue (saksfifthavenue.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class SAKSStrategy(SelectorBasedStrategy):
    _domain = "saksfifthavenue.com"
    _price_selectors = (
        "[data-testid='product-price']",
        "[class*='price-main']",
        "[class*='Price_main']",
        "[class*='saks-price']",
        "[class*='ProductPrice']",
        "[class*='product-card__price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[data-testid='product-price'], [class*='price-main'], [itemprop='price']"
    _price_wait_timeout_ms = 30_000
    _add_to_bag_selectors = (
        "[data-testid='add-to-bag']",
        "button[class*='AddToBag']",
        "button[aria-label*='Add to Bag']",
        "#add-to-cart-btn",
    )
    _out_of_stock_selectors = (
        "[class*='soldOut']",
        "[class*='sold-out']",
        "[class*='outOfStock']",
        "[data-testid='out-of-stock']",
    )
    _out_of_stock_texts = frozenset({"sold out", "out of stock", "temporarily unavailable", "notify me"})
    _in_stock_texts = frozenset({"add to bag", "add to cart"})
