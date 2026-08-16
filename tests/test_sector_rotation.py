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
    rank_us_sectors, rank_hk_sectors_by_gics, sg_unavailable_signal,
    refresh_sector_rotation, load_sector_rotation, save_sector_rotation,
    get_sector_tilt, SectorRotationSignal, SectorRankEntry,
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

    monkeypatch.setattr(sector_rotation, "fetch_stock_bars", fake_fetch_stock_bars)
    monkeypatch.setattr(sector_rotation, "parse_stock_bars_df", lambda token: price_series_by_symbol.get(token, []))
    monkeypatch.setattr(sector_rotation, "get_gics_sector_id_cached", lambda qc, symbol, market, cache: "50")

    result = refresh_sector_rotation(_FakeQuoteClient(), hk_symbols=["00700"], sector_tags_path=str(tmp_path / "sector_tags.json"))

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
    refresh_sector_rotation(_FakeQuoteClient(), hk_symbols=["00700", "00005"], sector_tags_path=tags_path)

    assert calls == ["00700", "00005"]
    assert os.path.exists(tags_path)


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
