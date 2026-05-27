"""Harvey Nichols (harveynichols.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class HARVEYNICHOLSStrategy(SelectorBasedStrategy):
    _domain = "harveynichols.com"
    _price_selectors = (
        "[class*='product__price']",
        "[class*='ProductPrice']",
        "[class*='price-item']",
        "[class*='price__current']",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='product__price'], [class*='price-item'], [itemprop='price']"
    _add_to_bag_selectors = (
        "button[class*='add-to-cart']",
        "button[data-add-to-cart]",
        "[class*='AddToCart']",
        "[class*='add-to-bag']",
        "button[aria-label*='Add to bag']",
        "button[aria-label*='Add to Bag']",
    )
    _out_of_stock_selectors = (
        "[class*='sold-out']",
        "[class*='SoldOut']",
        "[class*='out-of-stock']",
        "[class*='OutOfStock']",
        "[class*='notify-me']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "notify me", "currently unavailable",
        "email when available",
    })
    _in_stock_texts = frozenset({"add to bag", "add to basket", "add to cart"})
