"""
Shared "what would the strategy do today" computation: scoring, exit
checks, target allocation, reconciliation against real Tiger positions,
and risk-gating -- everything execute_trades.py did inline before, now
reusable by the CLI (dry-run and --live), the automated daily scan, and
the "Scan Now" dashboard button. One implementation, three callers,
parametrized by which PortfolioProfile (growth or dividend -- see
portfolio_profiles.py) is being scanned.

This module never places an order -- see order_execution.py for that,
which every caller must invoke as an explicit separate step.

Shorting (growth profile only, gated on an actual macro signal -- see
short_signal.py): a short target is expressed as a NEGATIVE
target_notional/target_pct on a PlannedPosition, merged into the same
list passed to execution.reconcile_positions as the long side. That
function's existing delta math (target_qty - current_qty) already
produces the mechanically correct BUY/SELL calls for opening, adding to,
partially covering, or fully covering a short -- no new order type or
separate code path, see execution.py and tiger_order_adapter.py's
docstrings for the same point made from the execution side.
"""
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from tigeropen.common.consts import Market

from tiger_stock_bars_adapter import fetch_stock_bars, parse_stock_bars_df
from tiger_dividend_adapter import fetch_corporate_dividends, parse_dividend_df
from tiger_trade_metas_adapter import fetch_trade_metas, parse_trade_metas_df
from universe import UniverseEntry
from stock_signal import score_symbol, momentum_score
from portfolio_construction import (
    ScoredCandidate, PlannedPosition, allocate_portfolio, filter_affordable_by_lot,
)
from exit_rules import ExitConfig, check_stop_loss, check_stop_loss_short, check_momentum_reversal
from risk_engine import RiskEngine, RiskViolation, DailyState, Position as RiskPosition
from execution import reconcile_positions, CurrentPosition, OrderInstruction
from decision_log import DecisionRecord
from macro_regime import load_regime_signal, effective_sleeve_tilts
from news_scanner import load_news_signal, get_tilt
from short_signal import score_short_candidate, market_favors_shorting
from strategy_ledger import load_or_init_ledger, latest_capital
from state_paths import REGIME_PATH, NEWS_PATH
from portfolio_profiles import PortfolioProfile
from confidence import score_to_confidence

MOMENTUM_LOOKBACK_DAYS = 126
MOMENTUM_SKIP_DAYS = 21
BREADTH_EDGE_CAUTION_FACTOR = 0.85  # scale down new-capital deployment when market_breadth flags at_edge

_MARKET_ENUM = {"US": Market.US, "HK": Market.HK, "SG": Market.SG}
_SLEEVE_TO_STRATEGY = {"core": "core_hold", "satellite": "satellite_momentum"}
_SHORT_STRATEGY_KEY = "satellite_short"


@dataclass
class ScanResult:
    profile_name: str
    as_of: str
    universe: List[UniverseEntry]
    sleeve_by_symbol: Dict[str, str]
    all_candidates: List[ScoredCandidate]
    affordable_candidates: List[ScoredCandidate]
    planned: List[PlannedPosition]
    current_positions: Dict[str, CurrentPosition]
    price_by_symbol: Dict[str, float]
    exit_reasons: Dict[str, str]
    instructions: List[OrderInstruction]
    instruction_outcomes: Dict[str, Tuple[str, str]]
    approved_instructions: List[OrderInstruction]
    decisions: List[DecisionRecord]
    capital: float
    halted: bool
    halt_reason: Optional[str] = None
    confidence_by_symbol: Dict[str, float] = field(default_factory=dict)  # empty when profile.confidence_scale is None


def run_scan(
    quote_client, trade_client, profile: PortfolioProfile,
    execute_threshold_pct: float = 70.0, shortlist_threshold_pct: float = 50.0,
) -> ScanResult:
    universe = profile.universe
    sleeve_by_symbol = {e.symbol: e.sleeve for e in universe}
    today = date.today()

    prices_by_symbol = {}
    for entry in universe:
        try:
            df = fetch_stock_bars(quote_client, entry.symbol, limit=MOMENTUM_LOOKBACK_DAYS + 30)
            prices = parse_stock_bars_df(df)
            if len(prices) >= MOMENTUM_LOOKBACK_DAYS + 1:
                prices_by_symbol[entry.symbol] = prices
        except Exception as e:
            print(f"  {entry.symbol}: bars fetch failed ({type(e).__name__}: {e}), skipping")

    dividends_by_symbol = {}
    by_market = {}
    for entry in universe:
        by_market.setdefault(entry.market, []).append(entry.symbol)
    begin_date = (today - timedelta(days=365 * 2)).isoformat()
    end_date = today.isoformat()
    for market, symbols in by_market.items():
        try:
            df = fetch_corporate_dividends(quote_client, symbols, _MARKET_ENUM[market], begin_date, end_date)
            dividends_by_symbol.update(parse_dividend_df(df))
        except Exception as e:
            print(f"  Dividend fetch failed for {market} symbols ({type(e).__name__}: {e})")

    news_signals = {}
    if os.path.exists(NEWS_PATH):
        try:
            news_signals = load_news_signal(NEWS_PATH)
        except Exception as e:
            print(f"  Failed to load news signal ({type(e).__name__}: {e})")

    regime = None
    regime_tilts = None
    if os.path.exists(REGIME_PATH):
        try:
            regime = load_regime_signal(REGIME_PATH)
            regime_tilts = effective_sleeve_tilts(regime)
        except Exception as e:
            print(f"  Failed to load regime signal ({type(e).__name__}: {e})")

    all_candidates = []
    for symbol, prices in prices_by_symbol.items():
        tilt = get_tilt(news_signals, symbol) if news_signals else 0.0
        scored = score_symbol(
            prices, dividends_by_symbol.get(symbol, []),
            lookback_days=MOMENTUM_LOOKBACK_DAYS, skip_recent_days=MOMENTUM_SKIP_DAYS, news_tilt=tilt,
            weights=profile.scoring_weights,
        )
        if scored is not None:
            all_candidates.append(ScoredCandidate(symbol=symbol, sleeve=sleeve_by_symbol[symbol],
                                                   score=scored.score, price=scored.price))

    # Fetched here (earlier than the rest of the current-position
    # handling below) purely so the confidence gate right below can tell
    # a held symbol apart from a prospective new one -- see that gate's
    # comment for why this order matters.
    raw_positions = trade_client.get_positions() or []
    current_positions = {}
    for p in raw_positions:
        symbol = p.contract.symbol
        # quantity != 0 keeps open shorts (negative quantity) visible and
        # exit-checked, not just long positions.
        if symbol in sleeve_by_symbol and p.quantity and p.quantity != 0:
            current_positions[symbol] = CurrentPosition(
                symbol=symbol, quantity=int(p.quantity), average_cost=float(p.average_cost or 0.0)
            )

    # Confidence gating (growth only, profile.confidence_scale is not
    # None): candidates below execute_threshold_pct never reach
    # affordability/allocation at all -- they're either shortlisted or
    # rejected by the caller (app.py) using confidence_by_symbol below,
    # not ranked/sized here. Dividend (confidence_scale=None) is
    # completely unaffected: execute_eligible_candidates == all_candidates.
    #
    # Currently-held symbols are ALWAYS execute-eligible regardless of
    # confidence -- this gate is meant to decide whether something is
    # confident enough to buy NEW, not to force-liquidate something
    # already held. A held position that dips below the threshold still
    # competes normally in allocate_portfolio's per-sleeve ranking below
    # (it can still lose its slot to a better candidate, or trip an
    # actual exit rule -- stop-loss/momentum-reversal, checked further
    # down); it just isn't excluded by an absolute confidence floor
    # before ranking even happens. Without this, every held position
    # that dips under the threshold would get an immediate full-exit
    # sell from execution.reconcile_positions's "no longer a target"
    # rule, which is not what this gate is for.
    confidence_by_symbol: Dict[str, float] = {}
    execute_eligible_candidates = all_candidates
    if profile.confidence_scale is not None:
        confidence_by_symbol = {
            c.symbol: score_to_confidence(c.score, profile.confidence_scale) for c in all_candidates
        }
        execute_eligible_candidates = [
            c for c in all_candidates
            if confidence_by_symbol[c.symbol] >= execute_threshold_pct or c.symbol in current_positions
        ]

    try:
        lot_infos = parse_trade_metas_df(fetch_trade_metas(quote_client, [e.symbol for e in universe]))
    except Exception as e:
        print(f"  Trade metas fetch failed ({type(e).__name__}: {e}), proceeding without lot-size filtering")
        lot_infos = {}

    ledger = load_or_init_ledger(profile.ledger_path, profile.initial_capital)
    capital = latest_capital(ledger)

    config = profile.portfolio_config
    affordable_candidates = execute_eligible_candidates
    if lot_infos and execute_eligible_candidates:
        affordable_symbols = set(filter_affordable_by_lot(
            symbol_prices={c.symbol: c.price for c in execute_eligible_candidates},
            lot_infos=lot_infos, available_capital=capital, max_position_pct=config.max_single_position_pct,
        ))
        affordable_candidates = [c for c in execute_eligible_candidates if c.symbol in affordable_symbols]

    # market_breadth "get ready to turn at the edges" caution: deploy less
    # NEW capital this scan when the breadth signal is stretched -- a
    # separate light-touch knob from sleeve tilting (which rebalances
    # between sleeves at constant total spend) and from the hard
    # max_drawdown halt below (which this does not replace).
    allocation_capital = capital
    if regime is not None and regime.breadth_at_edge:
        allocation_capital = capital * BREADTH_EDGE_CAUTION_FACTOR

    planned = allocate_portfolio(affordable_candidates, config, capital=allocation_capital, regime_tilts=regime_tilts)

    # current_positions was already fetched above (needed earlier by the
    # confidence gate) -- reused here rather than calling
    # trade_client.get_positions() a second time.

    # Exit-rule check on whatever's currently held -- independent of this
    # period's rebalance ranking, this is the real "when to sell" check.
    # Shorts get the symmetric stop-loss only (no momentum-reversal cover
    # rule yet -- see exit_rules.check_stop_loss_short's docstring).
    exit_config = ExitConfig()
    exit_reasons = {}
    price_by_symbol = {c.symbol: c.price for c in all_candidates}
    for symbol, position in current_positions.items():
        current_price = price_by_symbol.get(symbol)
        if current_price is None:
            continue
        if position.quantity > 0:
            stop_decision = check_stop_loss(position.average_cost, current_price, exit_config)
            if stop_decision.should_exit:
                exit_reasons[symbol] = stop_decision.reason
                continue
            prices = prices_by_symbol.get(symbol)
            if prices:
                try:
                    rolling_momentum = momentum_score(
                        prices, lookback_days=MOMENTUM_LOOKBACK_DAYS, skip_recent_days=MOMENTUM_SKIP_DAYS
                    )
                    mom_decision = check_momentum_reversal(rolling_momentum, exit_config)
                    if mom_decision.should_exit:
                        exit_reasons[symbol] = mom_decision.reason
                except ValueError:
                    pass
        else:
            stop_decision = check_stop_loss_short(position.average_cost, current_price, exit_config)
            if stop_decision.should_exit:
                exit_reasons[symbol] = stop_decision.reason

    planned = [p for p in planned if p.symbol not in exit_reasons]

    # Short-candidate pass: tactical, gated on an actual macro signal (COT
    # crowding or a narrowing/at-edge breadth trend -- see
    # short_signal.market_favors_shorting), not any breakdown regardless
    # of context. Growth profile only (profile.allow_short).
    short_planned: List[PlannedPosition] = []
    if profile.allow_short and market_favors_shorting(regime):
        long_held_symbols = {sym for sym, pos in current_positions.items() if pos.quantity > 0}
        long_target_symbols = {p.symbol for p in planned}
        short_candidates = []
        for entry in universe:
            symbol = entry.symbol
            if symbol in long_held_symbols or symbol in long_target_symbols:
                continue  # can't be long and short the same symbol at once
            prices = prices_by_symbol.get(symbol)
            if not prices:
                continue
            score = score_short_candidate(prices, lookback_days=MOMENTUM_LOOKBACK_DAYS, skip_recent_days=MOMENTUM_SKIP_DAYS)
            if score is not None:
                short_candidates.append((symbol, score, entry.sleeve))
        short_candidates.sort(key=lambda t: t[1])  # deepest breakdown first

        max_short_positions = max(profile.risk_config.max_short_positions, 0)
        chosen = short_candidates[:max_short_positions]
        if chosen and capital > 0:
            per_short_notional = (profile.risk_config.max_short_exposure_pct * capital) / max(len(chosen), 1)
            for symbol, score, sleeve in chosen:
                short_planned.append(PlannedPosition(
                    symbol=symbol, sleeve=sleeve,
                    target_notional=-per_short_notional, target_pct=-(per_short_notional / capital),
                ))
        short_planned = [p for p in short_planned if p.symbol not in exit_reasons]

    planned_symbols = {p.symbol for p in planned} | {p.symbol for p in short_planned}
    short_target_symbols = {p.symbol for p in short_planned}
    existing_short_symbols = {sym for sym, pos in current_positions.items() if pos.quantity < 0}

    merged_planned = planned + short_planned
    lot_size_by_symbol = {sym: info.lot_size for sym, info in lot_infos.items()}
    instructions = reconcile_positions(merged_planned, current_positions, price_by_symbol, lot_size_by_symbol)

    risk_engine = RiskEngine(profile.risk_config)
    equity_curve = [h["capital"] for h in ledger["history"]]
    halted = False
    halt_reason = None
    try:
        risk_engine.check_max_drawdown(equity_curve)
    except RiskViolation as e:
        halted = True
        halt_reason = str(e)

    state = DailyState(
        date=today,
        realized_pnl_today=0.0,
        open_positions=[
            RiskPosition(
                symbol=sym,
                strategy=(_SHORT_STRATEGY_KEY if pos.quantity < 0
                          else _SLEEVE_TO_STRATEGY.get(sleeve_by_symbol.get(sym), "core_hold")),
                notional=abs(pos.quantity * price_by_symbol.get(sym, pos.average_cost)),
                premium_collected=0.0, opened_on=today,
                direction="short" if pos.quantity < 0 else "long",
            )
            for sym, pos in current_positions.items()
        ],
    )

    # First: gate the actual order instructions through the risk engine --
    # this determines which orders get placed, independent of the fuller
    # rationale trail built below.
    instruction_outcomes: Dict[str, Tuple[str, str]] = {}
    approved_instructions = []
    for instr in instructions:
        if halted:
            instruction_outcomes[instr.symbol] = ("reject", "risk engine drawdown halt is active -- no new orders")
            continue

        short_related = instr.symbol in short_target_symbols or instr.symbol in existing_short_symbols
        if short_related:
            strategy_key = _SHORT_STRATEGY_KEY
            # Only opening/adding to a short (a SELL) increases short
            # exposure -- a BUY here is a cover, which reduces it, so it
            # must not be gated by the short-exposure cap.
            direction = "short" if instr.action == "SELL" else "long"
        else:
            sleeve = sleeve_by_symbol.get(instr.symbol, "unknown")
            strategy_key = _SLEEVE_TO_STRATEGY.get(sleeve, "core_hold")
            direction = "long"

        try:
            risk_engine.validate_trade(state, strategy_key, instr.notional, direction=direction)
            approved_instructions.append(instr)
            action = "buy" if instr.action == "BUY" else "sell"
            instruction_outcomes[instr.symbol] = (action, exit_reasons.get(instr.symbol, instr.reason))
        except RiskViolation as e:
            instruction_outcomes[instr.symbol] = ("reject", f"risk engine blocked: {e}")

    # Then: a full rationale trail for every scored candidate today (buy/
    # hold/reject), not just the ones that needed a new order -- mirrors
    # stock_backtest.py's decision log so "why" is answered for a no-change
    # day too, not just when something actually moves.
    execute_eligible_symbols = {c.symbol for c in execute_eligible_candidates}
    decisions: List[DecisionRecord] = []
    affordable_symbols_set = {c.symbol for c in affordable_candidates}
    for c in all_candidates:
        if c.symbol in instruction_outcomes:
            action, reason = instruction_outcomes[c.symbol]
            decisions.append(DecisionRecord(date=str(today), action=action, symbol=c.symbol,
                                             sleeve=c.sleeve, reason=reason, score=c.score))
        elif profile.confidence_scale is not None and c.symbol not in execute_eligible_symbols:
            confidence = confidence_by_symbol[c.symbol]
            if confidence >= shortlist_threshold_pct:
                decisions.append(DecisionRecord(
                    date=str(today), action="shortlist", symbol=c.symbol, sleeve=c.sleeve,
                    reason=f"confidence {confidence:.1f}% -- below the {execute_threshold_pct:.0f}% "
                           "execute threshold, shortlisted for re-scoring",
                    score=c.score,
                ))
            else:
                decisions.append(DecisionRecord(
                    date=str(today), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                    reason=f"confidence {confidence:.1f}% -- below the {shortlist_threshold_pct:.0f}% "
                           "shortlist threshold",
                    score=c.score,
                ))
        elif c.symbol not in affordable_symbols_set:
            decisions.append(DecisionRecord(
                date=str(today), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                reason=f"board lot unaffordable at current equity ${capital:,.0f}", score=c.score,
            ))
        elif c.symbol in planned_symbols:
            action = "hold" if c.symbol in current_positions else "buy"
            decisions.append(DecisionRecord(date=str(today), action=action, symbol=c.symbol,
                                             sleeve=c.sleeve, reason=f"top {c.sleeve} pick this period", score=c.score))
        else:
            decisions.append(DecisionRecord(
                date=str(today), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                reason=f"ranked below the {c.sleeve} sleeve's position cap", score=c.score,
            ))

    for symbol, reason in exit_reasons.items():
        if symbol not in instruction_outcomes:
            decisions.append(DecisionRecord(date=str(today), action="sell", symbol=symbol,
                                             sleeve=sleeve_by_symbol.get(symbol, "unknown"), reason=reason))

    candidate_symbols = {c.symbol for c in all_candidates}
    for symbol in current_positions:
        if symbol in instruction_outcomes or symbol in exit_reasons or symbol in candidate_symbols:
            continue
        decisions.append(DecisionRecord(
            date=str(today), action="sell", symbol=symbol, sleeve=sleeve_by_symbol.get(symbol, "unknown"),
            reason="dropped -- no longer eligible (insufficient history/momentum data today)",
        ))

    return ScanResult(
        profile_name=profile.name,
        as_of=str(today),
        universe=universe,
        sleeve_by_symbol=sleeve_by_symbol,
        all_candidates=all_candidates,
        affordable_candidates=affordable_candidates,
        planned=merged_planned,
        current_positions=current_positions,
        price_by_symbol=price_by_symbol,
        exit_reasons=exit_reasons,
        instructions=instructions,
        instruction_outcomes=instruction_outcomes,
        approved_instructions=approved_instructions,
        decisions=decisions,
        capital=capital,
        halted=halted,
        halt_reason=halt_reason,
        confidence_by_symbol=confidence_by_symbol,
    )
