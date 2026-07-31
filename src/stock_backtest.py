"""
Total-return backtest for the core-satellite stock/ETF strategy: rescoring
and reallocating on a monthly-ish cadence (rebalance_days, default 21
trading days), using real historical closes + dividends, tracking an
equity curve that feeds risk_engine.check_max_drawdown so the backtest
actually halts (rather than keeps compounding losses) if the drawdown
circuit breaker would have fired.

Selling is a real, distinct decision here, not just "didn't get re-picked
next month": within each holding period, every day is checked against
exit_rules (a hard stop-loss and a momentum-reversal exit) so a position
can be sold before the next scheduled rebalance if it craters or its trend
turns. Positions that survive to the rebalance boundary without triggering
either are sold there if they lose the re-ranking, or held if they keep it.

Every rebalance also produces a decision_log.DecisionRecord per candidate
(buy/hold/sell/reject, with the score or exit trigger that explains it) --
a deterministic rationale trail, not a per-period LLM narration (that
wouldn't scale to dozens of periods; the qualitative "lessons observed"
text stays a Claude judgment call in weekly_review.py, kept separate).

Caveats, stated up front rather than left implicit:
  - Multiple markets (US/HK/SG) don't share a trading calendar. Symbols are
    aligned onto the UNION of all their trading dates, forward-filling each
    symbol's last known close on days its own market was closed. This is a
    modeling simplification, not a replay of exact cross-market timing.
  - The news tilt (see news_scanner.py) has no historical archive to replay,
    so backtests always score with news_tilt=0.0 -- the live/paper system
    would include it, the backtest structurally can't.
  - Momentum needs momentum_lookback_days of history before a symbol is
    eligible; symbols listed partway through the backtest window are simply
    not candidates until they clear that bar.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from stock_signal import momentum_score, score_symbol
from portfolio_construction import (
    PortfolioConfig, ScoredCandidate, PlannedPosition, allocate_portfolio, filter_affordable_by_lot,
)
from exit_rules import ExitConfig, check_stop_loss, check_momentum_reversal
from decision_log import DecisionRecord
from risk_engine import RiskEngine, RiskViolation
from tiger_trade_metas_adapter import LotInfo
from universe import UniverseEntry


@dataclass
class ExitEvent:
    symbol: str
    reason: str
    exit_date: date
    return_at_exit: float


@dataclass
class BacktestPeriodResult:
    period_start: date
    equity_before: float
    positions: List[PlannedPosition]
    period_return_pct: float
    equity_after: float
    exits: List[ExitEvent] = field(default_factory=list)
    decisions: List[DecisionRecord] = field(default_factory=list)
    halted: bool = False
    halt_reason: Optional[str] = None


def _forward_fill_grid(
    prices_by_symbol: Dict[str, List[Tuple[date, float]]]
) -> Tuple[List[date], Dict[str, List[Optional[float]]]]:
    """
    Aligns every symbol's price series onto the union of all trading dates
    present across the whole universe, forward-filling each symbol's last
    known close on dates its own market was closed. A symbol has None for
    any date before its own series starts (not listed / no data yet).
    """
    all_dates = sorted({d for series in prices_by_symbol.values() for d, _ in series})

    aligned: Dict[str, List[Optional[float]]] = {}
    for symbol, series in prices_by_symbol.items():
        lookup = dict(series)
        closes: List[Optional[float]] = []
        last_known = None
        for d in all_dates:
            if d in lookup:
                last_known = lookup[d]
            closes.append(last_known)
        aligned[symbol] = closes

    return all_dates, aligned


def run_stock_backtest(
    prices_by_symbol: Dict[str, List[Tuple[date, float]]],
    dividends_by_symbol: Dict[str, List[Tuple[date, float]]],
    universe: List[UniverseEntry],
    config: PortfolioConfig,
    risk_engine: RiskEngine,
    initial_capital: float = 1000.0,
    rebalance_days: int = 21,
    momentum_lookback_days: int = 126,
    momentum_skip_days: int = 21,
    regime_tilts: Optional[Dict[str, float]] = None,
    lot_infos: Optional[Dict[str, LotInfo]] = None,
    exit_config: Optional[ExitConfig] = None,
) -> List[BacktestPeriodResult]:
    exit_config = exit_config or ExitConfig()
    sleeve_by_symbol = {e.symbol: e.sleeve for e in universe}
    all_dates, aligned = _forward_fill_grid(prices_by_symbol)

    min_history = momentum_lookback_days + 1
    if len(all_dates) < min_history + rebalance_days:
        raise ValueError(
            f"Need at least {min_history + rebalance_days} aligned trading days, "
            f"got {len(all_dates)}"
        )

    results: List[BacktestPeriodResult] = []
    equity_curve = [initial_capital]
    equity = initial_capital
    previously_held: set = set()

    i = min_history
    while i + rebalance_days < len(all_dates):
        period_start = all_dates[i]
        all_candidates: List[ScoredCandidate] = []

        for symbol, closes in aligned.items():
            if symbol not in sleeve_by_symbol:
                continue
            window = closes[i - min_history + 1 : i + 1]
            if any(c is None for c in window):
                continue  # not enough history for this symbol yet

            price_series = list(zip(all_dates[i - min_history + 1 : i + 1], window))
            # news_tilt=0.0: no historical news archive to replay (see module docstring)
            scored = score_symbol(
                price_series, dividends_by_symbol.get(symbol, []),
                lookback_days=momentum_lookback_days, skip_recent_days=momentum_skip_days, news_tilt=0.0,
            )
            if scored is None:
                continue
            all_candidates.append(
                ScoredCandidate(symbol=symbol, sleeve=sleeve_by_symbol[symbol], score=scored.score, price=closes[i])
            )

        affordable_candidates = all_candidates
        if lot_infos is not None and all_candidates:
            affordable_symbols = set(filter_affordable_by_lot(
                symbol_prices={c.symbol: c.price for c in all_candidates},
                lot_infos=lot_infos,
                available_capital=equity,
                max_position_pct=config.max_single_position_pct,
            ))
            affordable_candidates = [c for c in all_candidates if c.symbol in affordable_symbols]

        planned = allocate_portfolio(affordable_candidates, config, capital=equity, regime_tilts=regime_tilts)
        planned_symbols = {p.symbol for p in planned}

        period_return_pct = 0.0
        exits: List[ExitEvent] = []
        for position in planned:
            symbol = position.symbol
            start_price = aligned[symbol][i]
            if start_price is None or start_price <= 0:
                continue

            exit_idx = i + rebalance_days
            exit_reason = None
            for j in range(i + 1, i + rebalance_days + 1):
                price_j = aligned[symbol][j]
                if price_j is None:
                    continue

                stop_decision = check_stop_loss(start_price, price_j, exit_config)
                if stop_decision.should_exit:
                    exit_idx, exit_reason = j, stop_decision.reason
                    break

                window_start = j - min_history + 1
                if window_start >= 0:
                    window = aligned[symbol][window_start : j + 1]
                    if all(c is not None for c in window):
                        rolling_series = list(zip(all_dates[window_start : j + 1], window))
                        try:
                            rolling_momentum = momentum_score(
                                rolling_series, lookback_days=momentum_lookback_days,
                                skip_recent_days=momentum_skip_days,
                            )
                            mom_decision = check_momentum_reversal(rolling_momentum, exit_config)
                            if mom_decision.should_exit:
                                exit_idx, exit_reason = j, mom_decision.reason
                                break
                        except ValueError:
                            pass

            exit_price = aligned[symbol][exit_idx]
            price_return = (exit_price - start_price) / start_price
            period_dividends = sum(
                amount
                for d, amount in dividends_by_symbol.get(symbol, [])
                if period_start <= d <= all_dates[exit_idx]
            )
            position_return = price_return + period_dividends / start_price
            period_return_pct += position.target_pct * position_return

            if exit_reason is not None:
                exits.append(ExitEvent(
                    symbol=symbol, reason=exit_reason, exit_date=all_dates[exit_idx], return_at_exit=position_return
                ))

        equity_before = equity
        equity = equity_before * (1 + period_return_pct)
        equity_curve.append(equity)

        # Decision log: buy/hold/reject for every scored candidate, plus sell
        # for anything that dropped out (early exit or lost the rebalance).
        decisions: List[DecisionRecord] = []
        early_exit_symbols = {e.symbol for e in exits}
        for c in all_candidates:
            if c.symbol not in {ac.symbol for ac in affordable_candidates}:
                decisions.append(DecisionRecord(
                    date=str(period_start), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                    reason=f"board lot unaffordable at current equity ${equity_before:,.0f}", score=c.score,
                ))
            elif c.symbol in planned_symbols:
                action = "hold" if c.symbol in previously_held else "buy"
                decisions.append(DecisionRecord(
                    date=str(period_start), action=action, symbol=c.symbol, sleeve=c.sleeve,
                    reason=f"top {c.sleeve} pick this period", score=c.score,
                ))
            else:
                decisions.append(DecisionRecord(
                    date=str(period_start), action="reject", symbol=c.symbol, sleeve=c.sleeve,
                    reason=f"ranked below the {c.sleeve} sleeve's position cap", score=c.score,
                ))

        for e in exits:
            decisions.append(DecisionRecord(
                date=str(e.exit_date), action="sell", symbol=e.symbol,
                sleeve=sleeve_by_symbol.get(e.symbol, "unknown"), reason=e.reason,
            ))
        # Symbols still scored this period but not re-selected already have a
        # "reject" record above explaining why -- only symbols that fell out
        # of eligibility entirely (e.g. missing history/momentum this period)
        # need a separate "sell" record here, to avoid listing the same drop
        # twice under two different labels.
        candidates_this_period = {c.symbol for c in all_candidates}
        for symbol in (previously_held - planned_symbols - early_exit_symbols):
            if symbol in candidates_this_period:
                continue
            decisions.append(DecisionRecord(
                date=str(period_start), action="sell", symbol=symbol,
                sleeve=sleeve_by_symbol.get(symbol, "unknown"),
                reason="dropped at scheduled rebalance -- no longer eligible (insufficient history/momentum data this period)",
            ))

        result = BacktestPeriodResult(
            period_start=period_start,
            equity_before=equity_before,
            positions=planned,
            period_return_pct=period_return_pct,
            equity_after=equity,
            exits=exits,
            decisions=decisions,
        )

        previously_held = planned_symbols - early_exit_symbols

        try:
            risk_engine.check_max_drawdown(equity_curve)
        except RiskViolation as e:
            result.halted = True
            result.halt_reason = str(e)
            results.append(result)
            break

        results.append(result)
        i += rebalance_days

    return results


def summarize(results: List[BacktestPeriodResult], target_monthly_pct: float = 0.10) -> dict:
    if not results:
        return {"periods": 0}

    period_returns = [r.period_return_pct for r in results]
    total_return_pct = (results[-1].equity_after / results[0].equity_before) - 1
    hits = sum(1 for r in period_returns if r >= target_monthly_pct)

    peak = results[0].equity_before
    max_drawdown = 0.0
    for r in results:
        peak = max(peak, r.equity_after)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - r.equity_after) / peak)

    total_early_exits = sum(len(r.exits) for r in results)

    return {
        "periods": len(results),
        "total_return_pct": round(total_return_pct, 4),
        "avg_period_return_pct": round(sum(period_returns) / len(period_returns), 4),
        "worst_period_pct": round(min(period_returns), 4),
        "best_period_pct": round(max(period_returns), 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "hit_rate_vs_target": round(hits / len(results), 4),
        "final_equity": round(results[-1].equity_after, 2),
        "early_exits": total_early_exits,
        "halted": results[-1].halted,
        "halt_reason": results[-1].halt_reason,
    }
