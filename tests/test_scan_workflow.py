"""
Run with:
    pytest tests/test_scan_workflow.py -v

scan_workflow.run_scan touches five different Tiger-facing fetch
functions; rather than fake pandas DataFrames all the way through, these
tests monkeypatch the fetch_*/parse_* pairs scan_workflow imports by
name (same pattern test_app.py already uses for its own dependencies),
so a fake "df" can just be the symbol string itself and parse_* looks up
a synthetic price series from a plain dict.
"""
import sys
import os
import json
from dataclasses import dataclass
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import scan_workflow
from scan_workflow import run_scan
from universe import UniverseEntry
from portfolio_construction import PortfolioConfig
from risk_engine import RiskConfig
from strategy_ledger import record_snapshot


def make_price_series(start_price, daily_changes, start_date=date(2025, 1, 5)):
    prices = []
    price = start_price
    d = start_date
    for change in daily_changes:
        prices.append((d, price))
        price *= change
        d += timedelta(days=1)
    return prices


UPTREND = make_price_series(100.0, [1.003] * 160)      # clear long candidate
DOWNTREND = make_price_series(100.0, [0.997] * 160)     # clear short/breakdown candidate
FLAT = make_price_series(100.0, [1.0001] * 160)


@dataclass
class FakeContract:
    symbol: str


@dataclass
class FakePosition:
    contract: FakeContract
    quantity: float
    average_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_percent: float


class FakeQuoteClient:
    pass


class FakeTradeClient:
    def __init__(self, positions=None):
        self._positions = positions or []

    def get_positions(self):
        return self._positions


def make_profile(tmp_path, universe, allow_short=False, initial_capital=1000.0, name="growth",
                  max_short_positions=1, max_short_exposure_pct=0.15, max_satellite_positions=3):
    return scan_workflow.PortfolioProfile(
        name=name,
        initial_capital=initial_capital,
        universe=universe,
        portfolio_config=PortfolioConfig(core_pct=0.4, satellite_pct=0.6, max_core_positions=2,
                                          max_satellite_positions=max_satellite_positions),
        risk_config=RiskConfig(
            max_capital_at_risk=initial_capital, max_risk_per_trade_pct=1.0,
            allowed_strategies=("core_hold", "satellite_momentum", "satellite_short"),
            max_short_positions=max_short_positions, max_short_exposure_pct=max_short_exposure_pct,
        ),
        allow_short=allow_short,
        active=True,
        ledger_path=str(tmp_path / f"ledger_{name}.json"),
        decision_log_path=str(tmp_path / f"decision_log_{name}.json"),
        snapshot_path=str(tmp_path / f"snapshot_{name}.json"),
        pending_approvals_path=str(tmp_path / f"pending_{name}.json"),
    )


def patch_fetches(monkeypatch, price_series_by_symbol):
    monkeypatch.setattr(scan_workflow, "fetch_stock_bars", lambda qc, symbol, limit: symbol)
    monkeypatch.setattr(scan_workflow, "parse_stock_bars_df", lambda df: price_series_by_symbol.get(df, []))
    monkeypatch.setattr(scan_workflow, "fetch_corporate_dividends", lambda qc, symbols, market, b, e: None)
    monkeypatch.setattr(scan_workflow, "parse_dividend_df", lambda df: {})
    monkeypatch.setattr(scan_workflow, "fetch_trade_metas", lambda qc, symbols: None)
    monkeypatch.setattr(scan_workflow, "parse_trade_metas_df", lambda df: {})


def write_regime(path, positioning_tilt=1.0, breadth_trend="flat", breadth_at_edge=False):
    data = {
        "as_of": "2026-08-08", "regime": "recovery", "sleeve_tilts": {"core": 1.0, "satellite": 1.0},
        "sources": [], "notes": "",
        "positioning_tilt": positioning_tilt, "positioning_as_of": "2026-08-08", "positioning_notes": "",
        "breadth_trend": breadth_trend, "breadth_as_of": "2026-08-08", "breadth_notes": "",
        "breadth_tilt": 1.0, "breadth_at_edge": breadth_at_edge,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def no_regime(monkeypatch, tmp_path):
    regime_path = str(tmp_path / "regime.json")  # never written -- os.path.exists is False
    monkeypatch.setattr(scan_workflow, "REGIME_PATH", regime_path)
    monkeypatch.setattr(scan_workflow, "NEWS_PATH", str(tmp_path / "news.json"))
    return regime_path


def test_run_scan_uses_profile_capital_and_name(tmp_path, monkeypatch):
    universe = [UniverseEntry("UP", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"UP": UPTREND})
    no_regime(monkeypatch, tmp_path)
    profile = make_profile(tmp_path, universe, initial_capital=5000.0, name="dividend")

    result = run_scan(FakeQuoteClient(), FakeTradeClient(), profile)

    assert result.profile_name == "dividend"
    assert result.capital == 5000.0


def test_run_scan_dividend_profile_never_shorts_even_when_market_favors_it(tmp_path, monkeypatch):
    universe = [UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=0.85)  # crowded long -- market favors shorting
    monkeypatch.setattr(os.path, "exists", os.path.exists)  # sanity no-op, keep default behavior
    # regime file now exists at regime_path
    profile = make_profile(tmp_path, universe, allow_short=False, name="dividend")

    result = run_scan(FakeQuoteClient(), FakeTradeClient(), profile)

    assert all(p.target_notional >= 0 for p in result.planned)


def test_run_scan_growth_profile_no_short_when_market_does_not_favor_it(tmp_path, monkeypatch):
    universe = [UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=1.0, breadth_trend="flat", breadth_at_edge=False)  # not crowded
    profile = make_profile(tmp_path, universe, allow_short=True, name="growth")

    result = run_scan(FakeQuoteClient(), FakeTradeClient(), profile)

    assert all(p.target_notional >= 0 for p in result.planned)


def test_run_scan_growth_profile_opens_short_when_cot_crowded(tmp_path, monkeypatch):
    # UP is a strictly better long candidate so allocate_portfolio's
    # default-fill-the-sleeve behavior (no minimum-score floor) doesn't
    # sweep DOWN into a long target purely for lack of an alternative --
    # that would exclude it from short eligibility via the "already a
    # long target" guard, masking what this test is actually checking.
    universe = [UniverseEntry("UP", "US", "USD", "", "satellite"), UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"UP": UPTREND, "DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=0.85)  # crowded long -- market favors shorting
    profile = make_profile(tmp_path, universe, allow_short=True, name="growth", max_satellite_positions=1)

    result = run_scan(FakeQuoteClient(), FakeTradeClient(), profile)

    short_targets = [p for p in result.planned if p.target_notional < 0]
    assert len(short_targets) == 1
    assert short_targets[0].symbol == "DOWN"
    short_instr = next(i for i in result.instructions if i.symbol == "DOWN")
    assert short_instr.action == "SELL"


def test_run_scan_growth_profile_opens_short_via_breadth_narrowing_at_edge(tmp_path, monkeypatch):
    universe = [UniverseEntry("UP", "US", "USD", "", "satellite"), UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"UP": UPTREND, "DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=1.0, breadth_trend="narrowing", breadth_at_edge=True)
    profile = make_profile(tmp_path, universe, allow_short=True, name="growth", max_satellite_positions=1)

    result = run_scan(FakeQuoteClient(), FakeTradeClient(), profile)

    short_targets = [p for p in result.planned if p.target_notional < 0]
    assert len(short_targets) == 1


def test_run_scan_does_not_short_a_symbol_currently_held_long(tmp_path, monkeypatch):
    universe = [UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=0.85)
    profile = make_profile(tmp_path, universe, allow_short=True, name="growth")
    record_snapshot(profile.ledger_path, 1000.0, as_of="2026-08-01")

    held_long = FakeTradeClient([
        FakePosition(FakeContract("DOWN"), 2, 100.0, 90.0, 180.0, -20.0, -0.1),
    ])
    result = run_scan(FakeQuoteClient(), held_long, profile)

    short_targets = [p for p in result.planned if p.target_notional < 0]
    assert short_targets == []


def test_run_scan_existing_short_hitting_stop_loss_produces_cover_instruction(tmp_path, monkeypatch):
    universe = [UniverseEntry("DOWN", "US", "USD", "", "satellite")]
    patch_fetches(monkeypatch, {"DOWN": DOWNTREND})
    regime_path = no_regime(monkeypatch, tmp_path)
    write_regime(regime_path, positioning_tilt=1.0)  # not crowded -- irrelevant, position already open
    profile = make_profile(tmp_path, universe, allow_short=True, name="growth")

    # DOWNTREND's most recent close is well below the entry -- but this
    # short was entered at a much LOWER price than current, so it's a
    # loser: price has RISEN against the short beyond the 15% stop.
    entry_price = DOWNTREND[-1][1] * 0.5
    current_price = DOWNTREND[-1][1]
    short_position = FakeTradeClient([
        FakePosition(FakeContract("DOWN"), -3, entry_price, current_price, -3 * current_price, -100.0, -1.0),
    ])

    result = run_scan(FakeQuoteClient(), short_position, profile)

    assert "DOWN" in result.exit_reasons
    assert "stop_loss_short" in result.exit_reasons["DOWN"]
    cover_instr = next(i for i in result.instructions if i.symbol == "DOWN")
    assert cover_instr.action == "BUY"
