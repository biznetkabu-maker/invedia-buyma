"""scraper パッケージ。

使い方::

    from lib.scraper import PriceScraper

    scraper = PriceScraper()
    result = scraper.scrape("https://www.ssense.com/en-us/women/product/...")
    print(result)
"""

from .base import ScraperStrategy
from .engine import PriceScraper
from .models import ScrapedResult
from .strategies import (
    BIFFIStrategy,
    FARFETCHStrategy,
    GenericStrategy,
    GIGLIOStrategy,
    HARRODSStrategy,
    LUISAVIAROMAStrategy,
    MATCHESFASHIONStrategy,
    MYTHERESAStrategy,
    SAKSStrategy,
    SELFRIDGESStrategy,
    SSENSEStrategy,
    TESSABITStrategy,
    THEOUTNETStrategy,
    YOOXStrategy,
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
