"""Neiman Marcus (neimanmarcus.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class NEIMANMARCUSStrategy(SelectorBasedStrategy):
    _domain = "neimanmarcus.com"
    _price_selectors = (
        "[data-testid='product-price']",
        "[class*='product-price']",
        "[class*='ProductPrice']",
        "[class*='ItemPrice']",
        "[class*='price-now']",
        "[class*='price__sale']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='product-price'], [class*='ItemPrice'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[class*='add-to-bag']",
        "[class*='AddToBag']",
        "button[id*='addToCart']",
        "button[data-id='addToBag']",
        "button[aria-label*='Add to Bag']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='SoldOut']",
        "[class*='out-of-stock']",
        "[class*='notifyMe']",
        "[class*='notify-me']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "notify me when available",
        "this item is not available", "temporarily out of stock",
    })
    _in_stock_texts = frozenset({"add to bag", "add to cart"})
