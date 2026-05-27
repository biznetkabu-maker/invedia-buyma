"""MYTHERESA (mytheresa.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class MYTHERESAStrategy(SelectorBasedStrategy):
    _domain = "mytheresa.com"
    _price_selectors = (
        "[class*='pricing__prices']",
        "[class*='priceValue']",
        "[class*='ProductDetails__price']",
        "[class*='pdp-product__price']",
        "[class*='price-value']",
        "[data-testid='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='pricing'], [class*='priceValue'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[class*='addtocart__button']",
        "[class*='AddToCart']",
        "button[data-testid='add-to-cart']",
        "button[class*='add-to-bag']",
    )
    _out_of_stock_selectors = (
        "[class*='notify-me']",
        "[class*='NotifyMe']",
        "[class*='sold-out']",
    )
    _out_of_stock_texts = frozenset({"sold out", "notify me", "out of stock", "currently unavailable"})
    _in_stock_texts = frozenset({"add to bag", "add to cart", "in den warenkorb"})
