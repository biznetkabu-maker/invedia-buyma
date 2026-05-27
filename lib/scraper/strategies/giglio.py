"""GIGLIO (giglio.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class GIGLIOStrategy(SelectorBasedStrategy):
    _domain = "giglio.com"
    _price_selectors = (
        "[class*='PriceBox-module__price']",
        "[class*='PriceBox__price']",
        "[class*='PriceBox']",
        "[class*='product-price']",
        "[data-testid='price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[class*='PriceBox'], [class*='product-price'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[class*='AddToCart']",
        "[class*='add-to-cart']",
        "button[class*='addtocart']",
        "button[aria-label*='Aggiungi al carrello']",
        "button[title*='Add to cart']",
    )
    _out_of_stock_selectors = (
        "[class*='soldOut']",
        "[class*='sold-out']",
        "[class*='outOfStock']",
        "[class*='esaurito']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "esaurito", "non disponibile", "out of stock", "not available",
    })
    _in_stock_texts = frozenset({"add to cart", "aggiungi al carrello", "add to bag"})
    _use_ogp_price = True
