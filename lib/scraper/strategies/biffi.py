"""Biffi (biffi.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class BIFFIStrategy(SelectorBasedStrategy):
    _domain = "biffi.com"
    _price_selectors = (
        "[class*='price-final']",
        "[class*='price-sales']",
        "[class*='product-price']",
        "[class*='ProductPrice']",
        "[data-testid='price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='price'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[class*='add-to-cart']",
        "[class*='AddToCart']",
        "button[title*='Add to cart']",
        "button[title*='Aggiungi al carrello']",
        "button[data-action='add-to-cart']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='soldOut']",
        "[class*='out-of-stock']",
        "[class*='not-available']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "esaurito", "non disponibile",
        "out of stock", "not available",
    })
    _in_stock_texts = frozenset({"add to cart", "add to bag", "aggiungi al carrello"})
