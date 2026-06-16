"""24S (24s.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class TWENTYFOURSStrategy(SelectorBasedStrategy):
    _domain = "24s.com"
    _price_selectors = (
        "[class*='ProductPrice']",
        "[class*='product-price']",
        "[class*='price-current']",
        "[class*='price__amount']",
        "[data-testid='price']",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='ProductPrice'], [class*='price-current'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[class*='AddToCart']",
        "[class*='add-to-cart']",
        "button[data-testid='add-to-cart']",
        "button[class*='addToCart']",
        "button[aria-label*='Add to cart']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='SoldOut']",
        "[class*='out-of-stock']",
        "[class*='OutOfStock']",
        "[class*='notify-me']",
        "[class*='NotifyMe']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "notify me", "currently unavailable",
        "email me when available",
    })
    _in_stock_texts = frozenset({"add to cart", "add to bag", "add to basket"})
