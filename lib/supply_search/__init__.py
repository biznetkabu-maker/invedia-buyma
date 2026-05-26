"""仕入先サイトの検索（Step3）用 Strategy。"""

from .farfetch import (
    FarfetchSearchDiagnostics,
    lookup_farfetch_search_diagnose,
    lookup_farfetch_search_sync,
    parse_farfetch_search_html,
    search_farfetch_product_urls,
)
from .mytheresa import (
    MytheresaSearchDiagnostics,
    lookup_mytheresa_search_diagnose,
    parse_mytheresa_search_html,
    search_mytheresa_product_urls,
)
from .ssense import (
    SsenseSearchDiagnostics,
    lookup_ssense_search_diagnose,
    parse_ssense_search_html,
    search_ssense_product_urls,
)
from .netaporter import (
    NetaporterSearchDiagnostics,
    lookup_netaporter_search_diagnose,
    parse_netaporter_search_html,
    search_netaporter_product_urls,
)
from .twentyfoursevens import (
    TwentyFourSSearchDiagnostics,
    lookup_24s_search_diagnose,
    parse_24s_search_html,
    search_24s_product_urls,
)

__all__ = [
    "FarfetchSearchDiagnostics",
    "lookup_farfetch_search_diagnose",
    "lookup_farfetch_search_sync",
    "parse_farfetch_search_html",
    "search_farfetch_product_urls",
    "MytheresaSearchDiagnostics",
    "lookup_mytheresa_search_diagnose",
    "parse_mytheresa_search_html",
    "search_mytheresa_product_urls",
    "SsenseSearchDiagnostics",
    "lookup_ssense_search_diagnose",
    "parse_ssense_search_html",
    "search_ssense_product_urls",
    "NetaporterSearchDiagnostics",
    "lookup_netaporter_search_diagnose",
    "parse_netaporter_search_html",
    "search_netaporter_product_urls",
    "TwentyFourSSearchDiagnostics",
    "lookup_24s_search_diagnose",
    "parse_24s_search_html",
    "search_24s_product_urls",
]
