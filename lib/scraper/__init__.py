"""scraper パッケージ。

使い方::

    from lib.scraper import PriceScraper

    scraper = PriceScraper()
    result = scraper.scrape("https://www.ssense.com/en-us/women/product/...")
    print(result)
"""

from .engine import PriceScraper
from .models import ScrapedResult
from .base import ScraperStrategy
from .strategies import (
    SSENSEStrategy, TESSABITStrategy, GenericStrategy,
    FARFETCHStrategy, MATCHESFASHIONStrategy, MYTHERESAStrategy,
    SELFRIDGESStrategy, SAKSStrategy, HARRODSStrategy,
    LUISAVIAROMAStrategy, GIGLIOStrategy, BIFFIStrategy,
    YOOXStrategy, THEOUTNETStrategy,
)

__all__ = [
    "PriceScraper",
    "ScrapedResult",
    "ScraperStrategy",
    # 既存
    "SSENSEStrategy",
    "TESSABITStrategy",
    "GenericStrategy",
    # 定番
    "FARFETCHStrategy",
    "MATCHESFASHIONStrategy",
    "MYTHERESAStrategy",
    # デパート
    "SELFRIDGESStrategy",
    "SAKSStrategy",
    "HARRODSStrategy",
    # 欧州セレクト
    "LUISAVIAROMAStrategy",
    "GIGLIOStrategy",
    "BIFFIStrategy",
    # アウトレット
    "YOOXStrategy",
    "THEOUTNETStrategy",
]
