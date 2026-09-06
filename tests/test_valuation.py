"""
Run with:
    pytest tests/test_valuation.py -v
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from valuation import compute_pe_ratio, classify_batch, fetch_pe_assessments


def test_compute_pe_ratio_divides_price_by_eps():
    assert compute_pe_ratio(100.0, 5.0) == 20.0


def test_compute_pe_ratio_none_when_price_or_eps_missing():
    assert compute_pe_ratio(None, 5.0) is None
    assert compute_pe_ratio(100.0, None) is None


def test_compute_pe_ratio_none_when_eps_not_positive():
    assert compute_pe_ratio(100.0, 0.0) is None
    assert compute_pe_ratio(100.0, -2.0) is None


def test_classify_batch_flags_relative_to_median():
    # Median of the three known PEs (10, 20, 30) is 20.
    pe_by_symbol = {"CHEAP": 10.0, "MID": 20.0, "PRICEY": 30.0}
    verdicts = classify_batch(pe_by_symbol)
    assert verdicts["CHEAP"] == "undervalued"
    assert verdicts["MID"] == "fair"
    assert verdicts["PRICEY"] == "overvalued"


def test_classify_batch_unknown_stays_unknown_and_does_not_skew_median():
    pe_by_symbol = {"CHEAP": 10.0, "MID": 20.0, "PRICEY": 30.0, "NODATA": None}
    verdicts = classify_batch(pe_by_symbol)
    assert verdicts["NODATA"] == "unknown"
    assert verdicts["MID"] == "fair"  # median of the 3 known values is still 20


def test_classify_batch_everything_unknown_with_fewer_than_two_known_pes():
    assert classify_batch({"ONLY": 20.0, "NODATA": None}) == {"ONLY": "unknown", "NODATA": "unknown"}
    assert classify_batch({"NODATA": None}) == {"NODATA": "unknown"}


def test_fetch_pe_assessments_orchestrates_price_and_eps_lookups(monkeypatch):
    import valuation

    monkeypatch.setattr(valuation, "fetch_ticker_cik_map", lambda: {"0": {"cik_str": 1, "ticker": "AAA"}})
    monkeypatch.setattr(valuation, "get_annual_eps", lambda symbol, cik_map: {"AAA": 5.0, "BBB": 5.0}.get(symbol))
    monkeypatch.setattr(valuation, "fetch_stock_bars", lambda quote_client, symbol, limit=5: "raw")
    monkeypatch.setattr(valuation, "parse_stock_bars_df", lambda raw: [(None, 100.0)])

    assessments = fetch_pe_assessments(quote_client=object(), symbols=["AAA", "BBB"])

    assert assessments["AAA"].pe_ratio == 20.0
    assert assessments["BBB"].pe_ratio == 20.0
    # Equal PEs -> both "fair" relative to their shared median.
    assert assessments["AAA"].verdict == "fair"


def test_fetch_pe_assessments_survives_a_price_fetch_failure_for_one_symbol(monkeypatch):
    import valuation

    monkeypatch.setattr(valuation, "fetch_ticker_cik_map", lambda: {})
    monkeypatch.setattr(valuation, "get_annual_eps", lambda symbol, cik_map: 5.0)

    def flaky_bars(quote_client, symbol, limit=5):
        if symbol == "BROKEN":
            raise RuntimeError("tiger api down")
        return "raw"

    monkeypatch.setattr(valuation, "fetch_stock_bars", flaky_bars)
    monkeypatch.setattr(valuation, "parse_stock_bars_df", lambda raw: [(None, 100.0)])

    assessments = fetch_pe_assessments(quote_client=object(), symbols=["OK", "BROKEN"])

    assert assessments["BROKEN"].price is None
    assert assessments["BROKEN"].pe_ratio is None
    assert assessments["OK"].pe_ratio == 20.0
