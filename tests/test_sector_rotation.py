"""
Run with:
    pytest tests/test_sector_rotation.py -v
"""
import sys
import os
import json
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
import sector_rotation
from tiger_industry_adapter import SectorTag
from sector_rotation import (
    US_SECTOR_ETFS, GICS_SECTOR_NAMES, SPY_SYMBOL,
    rank_us_sectors, rank_hk_sectors_by_gics, rank_industries_by_gics, distinct_industries, sg_unavailable_signal,
    refresh_sector_rotation, load_sector_rotation, save_sector_rotation,
    get_sector_tilt, SectorRotationSignal, SectorRankEntry, IndustryRankEntry,
)


def make_series(start_price, daily_changes, start_date=date(2026, 1, 1)):
    series = []
    price = start_price
    d = start_date
    for change in daily_changes:
        series.append((d, price))
        price *= change
        d += timedelta(days=1)
    return series


# ---- rank_us_sectors -------------------------------------------------

def test_rank_us_sectors_ranks_strongest_relative_mover_first():
    prices = {SPY_SYMBOL: make_series(500.0, [1.0005] * 200)}
    # XLK rallies hard relative to SPY; XLU lags relative to SPY.
    prices["XLK"] = make_series(100.0, [1.003] * 200)
    prices["XLU"] = make_series(60.0, [0.999] * 200)

    signal = rank_us_sectors(prices)

    assert signal.region == "US"
    assert signal.method == "sector_etf"
    symbols_in_order = [e.etf_symbol for e in signal.entries]
    assert symbols_in_order[0] == "XLK"
    assert symbols_in_order[-1] == "XLU"
    assert signal.entries[0].rank == 1
    assert signal.note == ""


def test_rank_us_sectors_skips_etfs_without_enough_history():
    prices = {SPY_SYMBOL: make_series(500.0, [1.0005] * 200), "XLK": make_series(100.0, [1.003] * 200)}
    # every other SPDR ETF has no data at all

    signal = rank_us_sectors(prices)

    assert [e.etf_symbol for e in signal.entries] == ["XLK"]


def test_rank_us_sectors_empty_when_no_data():
    signal = rank_us_sectors({})
    assert signal.entries == []
    assert signal.note != ""


def test_rank_us_sectors_covers_all_eleven_gics_sectors_when_data_exists():
    prices = {SPY_SYMBOL: make_series(500.0, [1.0002] * 200)}
    for etf in US_SECTOR_ETFS:
        prices[etf] = make_series(100.0, [1.0003] * 200)
    signal = rank_us_sectors(prices)
    assert len(signal.entries) == 11
    assert {e.gics_sector_id for e in signal.entries} == set(GICS_SECTOR_NAMES.keys())


# ---- rank_hk_sectors_by_gics -------------------------------------------------

def test_rank_hk_sectors_by_gics_groups_and_averages_by_sector():
    momentum = {"00700": 0.20, "09988": 0.10, "00005": -0.05}
    gics = {"00700": "50", "09988": "50", "00005": "40"}  # both tech-ish -> comm services (50), HSBC -> financials (40)

    signal = rank_hk_sectors_by_gics(momentum, gics)

    assert signal.region == "HK"
    assert signal.method == "gics_aggregate"
    by_id = {e.gics_sector_id: e for e in signal.entries}
    assert by_id["50"].roc == pytest.approx(0.15)  # (0.20 + 0.10) / 2
    assert by_id["40"].roc == pytest.approx(-0.05)
    assert signal.entries[0].gics_sector_id == "50"  # ranked first (higher avg momentum)
    assert signal.entries[0].sector_name == GICS_SECTOR_NAMES["50"]


def test_rank_hk_sectors_by_gics_excludes_untagged_symbols():
    momentum = {"XXXX": 0.5}
    gics = {"XXXX": None}
    signal = rank_hk_sectors_by_gics(momentum, gics)
    assert signal.entries == []
    assert "No GICS-tagged" in signal.note


def test_rank_hk_sectors_by_gics_note_mentions_coarser_proxy_when_populated():
    signal = rank_hk_sectors_by_gics({"00700": 0.1}, {"00700": "50"})
    assert "Coarser proxy" in signal.note


# ---- rank_industries_by_gics -------------------------------------------------

def test_rank_industries_by_gics_groups_and_averages_by_industry_group():
    momentum = {"NVDA": 0.20, "AMD": 0.10, "MSFT": 0.05}
    tags = {
        "NVDA": SectorTag(symbol="NVDA", gics_sector_id="45", looked_up_at="2026-08-16",
                           gics_group_id="4530", gics_group_name="Semiconductors & Semiconductor Equipment"),
        "AMD": SectorTag(symbol="AMD", gics_sector_id="45", looked_up_at="2026-08-16",
                          gics_group_id="4530", gics_group_name="Semiconductors & Semiconductor Equipment"),
        "MSFT": SectorTag(symbol="MSFT", gics_sector_id="45", looked_up_at="2026-08-16",
                           gics_group_id="4510", gics_group_name="Software & Services"),
    }

    entries = rank_industries_by_gics(momentum, tags)

    by_id = {e.gics_group_id: e for e in entries}
    assert by_id["4530"].roc == pytest.approx(0.15)  # (0.20 + 0.10) / 2
    assert by_id["4530"].industry_name == "Semiconductors & Semiconductor Equipment"
    assert by_id["4530"].parent_sector_name == "Technology"
    assert by_id["4510"].roc == pytest.approx(0.05)
    assert entries[0].gics_group_id == "4530"  # ranked first (higher avg momentum)
    assert entries[0].rank == 1


def test_rank_industries_by_gics_excludes_untagged_and_ungrouped_symbols():
    momentum = {"XXXX": 0.5, "YYYY": 0.3}
    tags = {
        "XXXX": SectorTag(symbol="XXXX", gics_sector_id=None, looked_up_at="2026-08-16"),
        # YYYY has no tag at all (never looked up)
    }
    entries = rank_industries_by_gics(momentum, tags)
    assert entries == []


def test_rank_industries_by_gics_falls_back_to_group_id_when_name_missing():
    momentum = {"NVDA": 0.1}
    tags = {"NVDA": SectorTag(symbol="NVDA", gics_sector_id="45", looked_up_at="2026-08-16", gics_group_id="4530")}
    entries = rank_industries_by_gics(momentum, tags)
    assert entries[0].industry_name == "4530"


# ---- distinct_industries -------------------------------------------------

def test_distinct_industries_drops_sectors_with_only_one_group():
    entries = [
        IndustryRankEntry("Banks", "4010", "Financials", 0.17, 1),           # only group under Financials
        IndustryRankEntry("Utilities", "5510", "Utilities", 0.002, 2),       # only group under Utilities
        IndustryRankEntry("Consumer Services", "2530", "Consumer Discretionary", -0.06, 3),
        IndustryRankEntry("Consumer Discretionary Distribution & Retail", "2550", "Consumer Discretionary", -0.26, 4),
    ]
    result = distinct_industries(entries)
    assert [e.industry_name for e in result] == ["Consumer Services", "Consumer Discretionary Distribution & Retail"]


def test_distinct_industries_renumbers_survivors():
    entries = [
        IndustryRankEntry("Banks", "4010", "Financials", 0.17, 1),
        IndustryRankEntry("Consumer Services", "2530", "Consumer Discretionary", -0.06, 2),
        IndustryRankEntry("Consumer Discretionary Distribution & Retail", "2550", "Consumer Discretionary", -0.26, 3),
    ]
    result = distinct_industries(entries)
    assert [e.rank for e in result] == [1, 2]


def test_distinct_industries_keeps_everything_when_all_sectors_have_multiple_groups():
    entries = [
        IndustryRankEntry("Semiconductors & Semiconductor Equipment", "4530", "Technology", 0.55, 1),
        IndustryRankEntry("Software & Services", "4510", "Technology", -0.03, 2),
        IndustryRankEntry("Pharmaceuticals, Biotechnology & Life Sciences", "3520", "Health Care", 0.07, 3),
        IndustryRankEntry("Health Care Equipment & Supplies", "3510", "Health Care", 0.02, 4),
    ]
    result = distinct_industries(entries)
    assert len(result) == 4


def test_distinct_industries_empty_when_no_sector_has_multiple_groups():
    entries = [IndustryRankEntry("Banks", "4010", "Financials", 0.17, 1)]
    assert distinct_industries(entries) == []


def test_distinct_industries_empty_input():
    assert distinct_industries([]) == []


# ---- sg_unavailable_signal -------------------------------------------------

def test_sg_unavailable_signal_shape():
    signal = sg_unavailable_signal()
    assert signal.region == "SG"
    assert signal.method == "unavailable"
    assert signal.entries == []
    assert signal.note != ""
    assert signal.as_of == date.today().isoformat()


# ---- load/save round trip -------------------------------------------------

def test_save_then_load_sector_rotation_round_trips(tmp_path):
    path = str(tmp_path / "sector_rotation.json")
    original = {
        "US": SectorRotationSignal(
            as_of="2026-08-16", region="US", method="sector_etf",
            entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
        ),
        "SG": sg_unavailable_signal(),
    }
    save_sector_rotation(path, original)
    loaded = load_sector_rotation(path)
    assert loaded == original


def test_load_sector_rotation_empty_when_file_missing(tmp_path):
    assert load_sector_rotation(str(tmp_path / "does_not_exist.json")) == {}


def test_save_then_load_sector_rotation_round_trips_industries(tmp_path):
    path = str(tmp_path / "sector_rotation.json")
    original = {
        "US": SectorRotationSignal(
            as_of="2026-08-16", region="US", method="sector_etf",
            entries=[SectorRankEntry("Technology", "45", "XLK", "broadening", 0.05, 1.2, 1)],
            industries=[IndustryRankEntry("Semiconductors & Semiconductor Equipment", "4530", "Technology", 0.08, 1)],
        ),
    }
    save_sector_rotation(path, original)
    assert load_sector_rotation(path) == original


def test_load_sector_rotation_defaults_industries_when_field_missing_from_old_file(tmp_path):
    """Backward compat: files written before the industries field existed."""
    path = str(tmp_path / "sector_rotation.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "US": {
                "as_of": "2026-08-16", "region": "US", "method": "sector_etf",
                "entries": [], "note": "",
            },
        }, f)
    loaded = load_sector_rotation(path)
    assert loaded["US"].industries == []


# ---- refresh_sector_rotation (orchestration) -------------------------------------------------

class _FakeQuoteClient:
    pass


def test_refresh_sector_rotation_returns_all_three_regions(tmp_path, monkeypatch):
    def fake_fetch_stock_bars(qc, symbol, limit):
        return symbol  # opaque token, decoded by fake parse below

    price_series_by_symbol = {SPY_SYMBOL: make_series(500.0, [1.0003] * 200)}
    for etf in US_SECTOR_ETFS:
        price_series_by_symbol[etf] = make_series(100.0, [1.0004] * 200)
    price_series_by_symbol["00700"] = make_series(300.0, [1.002] * 130)

    def fake_get_gics_sector_id_cached(qc, symbol, market, cache):
        cache[symbol] = SectorTag(symbol=symbol, gics_sector_id="50", looked_up_at=date.today().isoformat())
        return "50"

    monkeypatch.setattr(sector_rotation, "fetch_stock_bars", fake_fetch_stock_bars)
    monkeypatch.setattr(sector_rotation, "parse_stock_bars_df", lambda token: price_series_by_symbol.get(token, []))
    monkeypatch.setattr(sector_rotation, "get_gics_sector_id_cached", fake_get_gics_sector_id_cached)

    result = refresh_sector_rotation(
        _FakeQuoteClient(), us_symbols=[], hk_symbols=["00700"], sector_tags_path=str(tmp_path / "sector_tags.json"),
    )

    assert set(result.keys()) == {"US", "HK", "SG"}
    assert result["US"].method == "sector_etf"
    assert len(result["US"].entries) == 11
    assert result["HK"].method == "gics_aggregate"
    assert result["HK"].entries[0].gics_sector_id == "50"
    assert result["SG"].method == "unavailable"


def test_refresh_sector_rotation_persists_sector_tag_cache(tmp_path, monkeypatch):
    valid_prices = make_series(300.0, [1.002] * 130)
    monkeypatch.setattr(sector_rotation, "fetch_stock_bars", lambda qc, symbol, limit: None)
    monkeypatch.setattr(sector_rotation, "parse_stock_bars_df", lambda token: valid_prices)

    calls = []

    def fake_get_gics_sector_id_cached(qc, symbol, market, cache):
        calls.append(symbol)
        cache[symbol] = SectorTag(symbol=symbol, gics_sector_id="45", looked_up_at=date.today().isoformat())
        return "45"
    monkeypatch.setattr(sector_rotation, "get_gics_sector_id_cached", fake_get_gics_sector_id_cached)

    tags_path = str(tmp_path / "sector_tags.json")
    refresh_sector_rotation(
        _FakeQuoteClient(), us_symbols=["AAPL"], hk_symbols=["00700", "00005"], sector_tags_path=tags_path,
    )

    assert calls == ["AAPL", "00700", "00005"]
    assert os.path.exists(tags_path)


def test_refresh_sector_rotation_populates_industries_for_us_and_hk(tmp_path, monkeypatch):
    price_series_by_symbol = {SPY_SYMBOL: make_series(500.0, [1.0003] * 200)}
    for etf in US_SECTOR_ETFS:
        price_series_by_symbol[etf] = make_series(100.0, [1.0004] * 200)
    price_series_by_symbol["NVDA"] = make_series(100.0, [1.002] * 130)
    price_series_by_symbol["00700"] = make_series(300.0, [1.002] * 130)

    monkeypatch.setattr(sector_rotation, "fetch_stock_bars", lambda qc, symbol, limit: symbol)
    monkeypatch.setattr(sector_rotation, "parse_stock_bars_df", lambda token: price_series_by_symbol.get(token, []))

    def fake_get_gics_sector_id_cached(qc, symbol, market, cache):
        cache[symbol] = SectorTag(
            symbol=symbol, gics_sector_id="45", looked_up_at=date.today().isoformat(),
            gics_group_id="4530", gics_group_name="Semiconductors & Semiconductor Equipment",
        )
        return "45"
    monkeypatch.setattr(sector_rotation, "get_gics_sector_id_cached", fake_get_gics_sector_id_cached)

    result = refresh_sector_rotation(
        _FakeQuoteClient(), us_symbols=["NVDA"], hk_symbols=["00700"], sector_tags_path=str(tmp_path / "sector_tags.json"),
    )

    assert result["US"].industries[0].industry_name == "Semiconductors & Semiconductor Equipment"
    assert result["HK"].industries[0].industry_name == "Semiconductors & Semiconductor Equipment"
    assert result["SG"].industries == []


# ---- get_sector_tilt -------------------------------------------------

def _signal_with_ranks(*gics_ids):
    entries = [
        SectorRankEntry(sector_name=GICS_SECTOR_NAMES.get(gid, gid), gics_sector_id=gid, etf_symbol=None,
                         trend="", roc=0.0, roc_zscore=0.0, rank=i + 1)
        for i, gid in enumerate(gics_ids)
    ]
    return SectorRotationSignal(as_of="2026-08-16", region="US", method="sector_etf", entries=entries)


def test_get_sector_tilt_top_ranked_sector_is_plus_one():
    signal = _signal_with_ranks("45", "40", "10")
    assert get_sector_tilt(signal, "45") == pytest.approx(1.0)


def test_get_sector_tilt_bottom_ranked_sector_is_minus_one():
    signal = _signal_with_ranks("45", "40", "10")
    assert get_sector_tilt(signal, "10") == pytest.approx(-1.0)


def test_get_sector_tilt_middle_ranked_sector_is_zero():
    signal = _signal_with_ranks("45", "40", "10")
    assert get_sector_tilt(signal, "40") == pytest.approx(0.0)


def test_get_sector_tilt_single_entry_signal_is_plus_one():
    signal = _signal_with_ranks("45")
    assert get_sector_tilt(signal, "45") == pytest.approx(1.0)


def test_get_sector_tilt_neutral_when_sector_unranked():
    signal = _signal_with_ranks("45", "40")
    assert get_sector_tilt(signal, "99") == 0.0


def test_get_sector_tilt_neutral_when_gics_id_is_none():
    signal = _signal_with_ranks("45", "40")
    assert get_sector_tilt(signal, None) == 0.0


def test_get_sector_tilt_neutral_when_signal_is_none():
    assert get_sector_tilt(None, "45") == 0.0


def test_get_sector_tilt_neutral_for_sg_unavailable_signal():
    assert get_sector_tilt(sg_unavailable_signal(), "45") == 0.0
