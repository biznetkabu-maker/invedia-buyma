"""MATCHESFASHION (matchesfashion.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class MATCHESFASHIONStrategy(SelectorBasedStrategy):
    _domain = "matchesfashion.com"
    _price_selectors = (
        "[data-testid='product-price']",
        "[data-testid='price']",
        "[class*='price__value']",
        "[class*='ProductPrice']",
        "[class*='product-info__price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[data-testid='product-price'], [class*='price']"
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='SoldOut']",
        "[data-testid='sold-out']",
    )
    _out_of_stock_texts = frozenset({"sold out", "out of stock", "notify me when available"})
    _in_stock_texts = frozenset({"add to bag", "add to cart", "add to basket"})
    _use_ogp_price = True
