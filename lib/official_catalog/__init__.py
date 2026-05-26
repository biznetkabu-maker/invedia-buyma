"""ブランド公式サイトを基準カタログとして型番照合する。"""

from lib.official_catalog.prada import PradaOfficialMatch, lookup_prada_official_sync

__all__ = ["PradaOfficialMatch", "lookup_prada_official_sync"]
