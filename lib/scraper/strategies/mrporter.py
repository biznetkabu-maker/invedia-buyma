"""MR PORTER (mrporter.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class MRPORTERStrategy(SelectorBasedStrategy):
    _domain = "mrporter.com"
    _price_selectors = (
        "[data-testid='product-price']",
        "[class*='ProductPrice']",
        "[class*='price__value']",
        "[class*='product-price']",
        "[class*='pdp-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[data-testid='product-price'], [class*='ProductPrice'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[data-testid='add-to-bag']",
        "[class*='add-to-bag']",
        "[class*='AddToBag']",
        "button[aria-label*='Add to bag']",
        "button[aria-label*='add to bag']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='SoldOut']",
        "[class*='out-of-stock']",
        "[class*='OutOfStock']",
        "[data-testid='notify-me']",
        "[class*='notify-me']",
        "[class*='NotifyMe']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "notify me",
        "email me when available", "this item is currently out of stock",
    })
    _in_stock_texts = frozenset({"add to bag", "add to basket"})
