"""P3 価格マルチソース投票のテスト。"""

from __future__ import annotations

import pytest

from lib.multi_source import (
    PriceConsensus,
    PriceVote,
    SourceCandidate,
    compute_price_consensus,
    _extract_site_name,
)


def _make_candidate(
    url: str = "https://www.ssense.com/product/1",
    price: float = 800.0,
    currency: str = "USD",
    stock: str = "in_stock",
    **kwargs,
) -> SourceCandidate:
    return SourceCandidate(
        url=url,
        price=price,
        currency=currency,
        stock_status=stock,
        jpy_cost=price * 155.0 if price is not None else None,
        profit=10000.0,
        profit_rate=0.10,
        breakdown=None,
        **kwargs,
    )


class TestComputePriceConsensus:

    def test_no_candidates(self):
        assert compute_price_consensus([]) is None

    def test_no_in_stock(self):
        c = _make_candidate(stock="out_of_stock")
        assert compute_price_consensus([c]) is None

    def test_no_price(self):
        c = _make_candidate(price=None)
        assert compute_price_consensus([c]) is None

    def test_single_vote(self):
        c = _make_candidate(price=800.0, currency="USD")
        result = compute_price_consensus([c])
        assert result is not None
        assert result.consensus_price == 800.0
        assert result.currency == "USD"
        assert result.method == "single"
        assert result.confidence == 0.5
        assert result.vote_count == 1
        assert result.outlier_count == 0

    def test_unanimous_votes(self):
        candidates = [
            _make_candidate(url=f"https://site{i}.com/p", price=800.0, currency="USD")
            for i in range(3)
        ]
        result = compute_price_consensus(candidates)
        assert result is not None
        assert result.consensus_price == 800.0
        assert result.method == "unanimous"
        assert result.confidence == 1.0
        assert result.outlier_count == 0

    def test_close_prices_median(self):
        candidates = [
            _make_candidate(url="https://ssense.com/p/1", price=795.0),
            _make_candidate(url="https://farfetch.com/p/2", price=800.0),
            _make_candidate(url="https://mytheresa.com/p/3", price=805.0),
        ]
        result = compute_price_consensus(candidates)
        assert result is not None
        assert result.consensus_price == 800.0
        assert result.method == "median"
        assert result.confidence > 0.9
        assert result.outlier_count == 0

    def test_outlier_detected(self):
        candidates = [
            _make_candidate(url="https://ssense.com/p/1", price=800.0),
            _make_candidate(url="https://farfetch.com/p/2", price=810.0),
            _make_candidate(url="https://mytheresa.com/p/3", price=1200.0),  # outlier
        ]
        result = compute_price_consensus(candidates)
        assert result is not None
        assert result.outlier_count == 1
        assert result.consensus_price < 900
        assert result.confidence < 1.0

    def test_mixed_currencies_uses_majority(self):
        candidates = [
            _make_candidate(url="https://ssense.com/p/1", price=800.0, currency="USD"),
            _make_candidate(url="https://farfetch.com/p/2", price=810.0, currency="USD"),
            _make_candidate(url="https://24s.com/p/3", price=720.0, currency="EUR"),
        ]
        result = compute_price_consensus(candidates)
        assert result is not None
        assert result.currency == "USD"

    def test_custom_threshold(self):
        candidates = [
            _make_candidate(url="https://ssense.com/p/1", price=800.0),
            _make_candidate(url="https://farfetch.com/p/2", price=850.0),
        ]
        result_strict = compute_price_consensus(candidates, outlier_threshold=0.03)
        result_loose = compute_price_consensus(candidates, outlier_threshold=0.10)
        assert result_strict is not None
        assert result_loose is not None
        assert result_strict.outlier_count >= result_loose.outlier_count

    def test_summary_format(self):
        c = _make_candidate(price=800.0)
        result = compute_price_consensus([c])
        assert result is not None
        s = result.summary()
        assert "P3:" in s
        assert "USD" in s
        assert "800" in s

    def test_out_of_stock_excluded(self):
        candidates = [
            _make_candidate(url="https://ssense.com/p/1", price=800.0, stock="in_stock"),
            _make_candidate(url="https://farfetch.com/p/2", price=900.0, stock="out_of_stock"),
        ]
        result = compute_price_consensus(candidates)
        assert result is not None
        assert result.vote_count == 1
        assert result.consensus_price == 800.0


class TestExtractSiteName:

    def test_known_sites(self):
        assert _extract_site_name("https://www.ssense.com/en-us/p/1") == "ssense"
        assert _extract_site_name("https://www.farfetch.com/shopping/p/1") == "farfetch"
        assert _extract_site_name("https://www.mytheresa.com/en-us/p.html") == "mytheresa"
        assert _extract_site_name("https://www.net-a-porter.com/en-us/shop/p/1") == "net-a-porter"
        assert _extract_site_name("https://www.24s.com/en-us/p/1") == "24s"

    def test_unknown_site(self):
        result = _extract_site_name("https://www.unknownshop.com/product/1")
        assert "unknownshop" in result


class TestPriceVoteDomain:

    def test_domain_from_url(self):
        v = PriceVote(url="https://www.ssense.com/p/1", price=800, currency="USD", source_site="ssense")
        assert v.domain == "www.ssense.com"
