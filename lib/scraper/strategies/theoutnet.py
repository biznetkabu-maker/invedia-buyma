"""THE OUTNET (theoutnet.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class THEOUTNETStrategy(SelectorBasedStrategy):
    _domain = "theoutnet.com"
    _price_selectors = (
        "[data-testid='product-price']",
        "[class*='price-current']",
        "[class*='priceContainer']",
        "[class*='ProductPrice']",
        "[class*='product-price']",
        "[itemprop='price']",
        ".price",
    )
    _price_wait_selector = "[data-testid='product-price'], [class*='priceContainer'], [itemprop='price']"
    _add_to_bag_selectors = (
        "[data-testid='add-to-bag']",
        "[class*='AddToBag']",
        "[class*='add-to-bag']",
        "button[aria-label*='Add to bag']",
    )
    _out_of_stock_selectors = (
        "[data-testid='add-to-wishlist-only']",
        "[class*='wishlistOnly']",
        "[class*='sold-out']",
        "[class*='soldOut']",
        "[class*='outOfStock']",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "out of stock", "this item is no longer available",
    })
    _in_stock_texts = frozenset({"add to bag", "add to basket"})
