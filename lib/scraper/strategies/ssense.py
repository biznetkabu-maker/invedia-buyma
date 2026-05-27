"""SSENSE (ssense.com) 向けスクレイピングStrategy。"""

from .selector_based import SelectorBasedStrategy


class SSENSEStrategy(SelectorBasedStrategy):
    _domain = "ssense.com"
    _price_selectors = (
        "[data-testid='price']",
        "[data-testid='product-price']",
        "[class*='Price__priceItem']",
        "[class*='Price__price']",
        "[class*='ProductPrice']",
        "[itemprop='price']",
        ".price",
        "[class*='price']",
    )
    _out_of_stock_selectors = (
        "[class*='SoldOut']",
        "[class*='sold-out']",
        "[class*='soldOut']",
        "[data-testid='sold-out']",
        ".sold-out",
    )
    _out_of_stock_texts = frozenset({
        "sold out", "épuisé", "ausverkauft", "agotado", "なし", "sold-out",
    })
    _in_stock_texts = frozenset({
        "add to bag", "add to cart", "ajouter au panier",
        "in den warenkorb", "añadir al carrito", "カートに追加",
    })
    _use_json_ld_style_id = True
