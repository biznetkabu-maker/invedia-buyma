"""TESSABIT (tessabit.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class TESSABITStrategy(SelectorBasedStrategy):
    _domain = "tessabit.com"
    _price_selectors = (
        "[data-price-type='finalPrice'] .price",
        "[data-price-type='finalPrice']",
        ".product-info-price .price",
        ".price-box .price",
        ".special-price .price",
        ".regular-price .price",
        "[class*='product-price'] .price",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[data-price-type='finalPrice'], .price-box, [itemprop='price']"
    _add_to_bag_selectors = (
        "#product-addtocart-button",
        "[class*='add-to-cart']",
        "button[title*='Add to Cart']",
        "button[title*='カートに追加']",
        ".btn-cart",
        "button[type='submit'][class*='cart']",
    )
    _out_of_stock_selectors = (
        ".unavailable",
        ".out-of-stock",
        "[class*='out-of-stock']",
        "[class*='outOfStock']",
        ".stock.unavailable",
    )
    _out_of_stock_texts = frozenset({
        "out of stock", "sold out", "unavailable",
        "non disponibile", "esaurito", "ausverkauft", "épuisé",
    })
    _in_stock_texts = frozenset({"add to cart", "add to bag", "カートに追加"})
    _use_ogp_price = True
