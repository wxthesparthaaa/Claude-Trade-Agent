"""
Commission-aware, scan-cadence-faithful backtest harness for the GROWTH portfolio.
Research-only (never imported by src/). Closes the "Known harness gaps" in research/README.md:

  * $2.98 flat commission per order (Tiger's real fills: 2.98-3.01).
  * Daily scan cadence: every trading day t the system "scans at the open" -- the price series it
    sees is closes[..t-1] + open[t] (live scans run ~9:35 ET with today's partial bar) -- and every
    order fills at open[t]. `cadence=N` scans only every N-th day (exit checks still run daily unless
    exits_on_cadence=True).
  * Positions are integer shares, re-targeted with the live reconcile rule (execution.reconcile_positions):
    new entries always go through, already-held targets are skipped while inside +/-band, anything
    held that is no longer a target is fully exited.
  * Live gates: confidence sigmoid(score/0.15) >= execute threshold for NEW entries only (held names
    exempt), 20% stop from AVERAGE COST (live uses Tiger's average_cost, which moves on top-ups),
    momentum-reversal exit (momentum < -5%), allocate_portfolio's 40/60 split, 2 core / 3 satellite,
    35% max / 10% min position, sized on mark-to-market equity.
  * Optional 25% drawdown halt that blocks ALL orders (live behaviour) while equity is >=25% below peak.

Simplifications (stated, not hidden): US symbols only (HK/SG names skipped); dividend yield, news tilt,
sector tilt, regime tilts, breadth caution and shorts are all 0/off; dividends are not credited.
Universe membership is today's -- the auto-added semis were picked in Aug 2026 with hindsight, so
results on the "full" universe are survivorship/selection-biased; prefer the "static" universe.
"""
import math
import os
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HERE = os.path.dirname(__file__)
BARS = os.path.join(HERE, 'data', 'bars')

STATIC_CORE = ['VOO', 'QQQ', 'SCHD', 'VYM', 'AGG', 'TLT', 'IWM', 'XLK', 'DIA']
STATIC_SAT = ['NVDA', 'AMD', 'META', 'AVGO', 'MSFT', 'AAPL', 'GOOGL', 'AMZN', 'TSLA', 'CRM',
              'GLD', 'SLV', 'USO', 'DBC', 'CPER', 'UNG']
EXTRA_SAT = ['AXTI', 'ASX', 'CRDO', 'AEHR', 'ADI', 'ACMR', 'INTC', 'MRVL', 'MU', 'ALAB', 'SKHY',
             'TSM', 'ASML', 'ALGM', 'ARM']


def universe(name: str) -> Dict[str, str]:
    u = {s: 'core' for s in STATIC_CORE}
    u.update({s: 'satellite' for s in STATIC_SAT})
    if name == 'full':
        u.update({s: 'satellite' for s in EXTRA_SAT})
    return u


_cache = {}


def load_panel(symbols: List[str]):
    key = tuple(sorted(symbols))
    if key in _cache:
        return _cache[key]
    frames = {}
    for s in list(symbols) + ['SPY']:
        p = os.path.join(BARS, f'{s}.csv')
        if os.path.exists(p):
            frames[s] = pd.read_csv(p, parse_dates=['date']).set_index('date')
    dates = sorted(set().union(*[f.index for f in frames.values()]))
    idx = pd.DatetimeIndex(dates)
    op = pd.DataFrame({s: f['open'].reindex(idx) for s, f in frames.items()})
    cl = pd.DataFrame({s: f['close'].reindex(idx) for s, f in frames.items()})
    hi = pd.DataFrame({s: f['high'].reindex(idx) for s, f in frames.items()})
    lo = pd.DataFrame({s: f['low'].reindex(idx) for s, f in frames.items()})
    out = (idx, op, hi, lo, cl)
    _cache[key] = out
    return out


@dataclass
class Params:
    capital: float = 5000.0
    core_pct: float = 0.40
    sat_pct: float = 0.60
    max_core: int = 2
    max_sat: int = 3
    max_single: float = 0.35
    min_pos: float = 0.10
    band: float = 0.20
    stop: Optional[float] = 0.20
    mom_exit: Optional[float] = -0.05
    lookback: int = 126
    skip: int = 21
    conf_thresh: float = 70.0
    conf_scale: float = 0.15
    commission: float = 2.98
    cadence: int = 1                 # scan every N trading days
    exits_on_cadence: bool = False   # if True, stop/momentum exits only checked on scan days
    cooldown: int = 0                # days a stopped-out symbol can't be re-entered
    min_order: float = 0.0           # skip non-exit orders whose notional < this
    dd_halt: Optional[float] = 0.25
    regime_gate: Optional[str] = None  # 'spy200': no NEW entries while SPY close < 200d SMA
    atr_mult: Optional[float] = None   # if set, stop = entry - atr_mult*ATR20 at entry (replaces % stop)
    trail: Optional[float] = None      # trailing stop from highest close since entry
    hold_rank_buffer: int = 0          # held name keeps its slot unless it falls below cap+buffer
    sat_weight_scheme: str = 'equal'


def _conf(score, scale):
    return 100.0 / (1.0 + math.exp(-score / scale))


def simulate(uni: Dict[str, str], p: Params, start: str, end: str, record=False):
    syms = list(uni)
    idx, op, hi, lo, cl = load_panel(syms)
    syms = [s for s in syms if s in cl.columns]
    O, C, H, L = op[syms].values, cl[syms].values, hi[syms].values, lo[syms].values
    spy = cl['SPY'].values if 'SPY' in cl.columns else None
    spy_sma = pd.Series(spy).rolling(200).mean().values if spy is not None else None
    tr = np.maximum(H - L, np.maximum(np.abs(H - np.roll(C, 1, 0)), np.abs(L - np.roll(C, 1, 0))))
    atr = pd.DataFrame(tr).rolling(20).mean().values
    n = len(syms)
    sleeve = np.array([uni[s] for s in syms])
    t0 = int(np.searchsorted(idx.values, np.datetime64(start)))
    t1 = int(np.searchsorted(idx.values, np.datetime64(end)))
    t0 = max(t0, p.lookback + 2)

    cash = p.capital
    qty = np.zeros(n, dtype=int)
    avg = np.zeros(n)
    peak_px = np.zeros(n)
    atr_stop = np.zeros(n)
    entry_t = np.zeros(n, dtype=int)
    cooldown_until = np.full(n, -1)
    last_stop_t = np.full(n, -10**9)
    peak_eq = p.capital
    orders = 0
    comm = 0.0
    trades = []      # closed round trips: (sym, pnl_incl_comm, reason, entry_date, exit_date)
    reentries = 0
    stopouts = 0
    open_cost = np.zeros(n)  # cost basis incl. commissions for round-trip P&L
    eq_curve = []
    halted_days = 0
    invested_days = 0

    def fill(i, dq, px, t, reason):
        nonlocal cash, orders, comm, stopouts, reentries
        cash -= dq * px + p.commission
        orders += 1
        comm += p.commission
        if dq > 0:
            if qty[i] == 0:
                entry_t[i] = t
                peak_px[i] = px
                atr_stop[i] = px - (p.atr_mult * atr[t - 1, i] if p.atr_mult and not np.isnan(atr[t - 1, i]) else 0)
                if t - last_stop_t[i] <= 10:
                    reentries += 1
            avg[i] = (avg[i] * qty[i] + dq * px) / (qty[i] + dq)
            open_cost[i] += dq * px + p.commission
            qty[i] += dq
        else:
            sold = -dq
            frac = sold / qty[i]
            cost_part = open_cost[i] * frac
            pnl = sold * px - p.commission - cost_part
            open_cost[i] -= cost_part
            qty[i] -= sold
            if qty[i] == 0:
                avg[i] = 0
                open_cost[i] = 0
            # a partial trim is folded into the round trip it belongs to
            trades.append((syms[i], pnl, reason, idx[entry_t[i]].date(), idx[t].date(), qty[i] == 0))
            if reason.startswith('stop'):
                stopouts += 1
                last_stop_t[i] = t
                if p.cooldown:
                    cooldown_until[i] = t + p.cooldown

    for t in range(t0, t1):
        px_now = O[t]
        valid_now = ~np.isnan(px_now)
        mark = np.where(valid_now, px_now, C[t - 1])
        equity = cash + np.nansum(qty * mark)
        peak_eq = max(peak_eq, equity)
        halted = p.dd_halt is not None and (peak_eq - equity) / peak_eq >= p.dd_halt
        if halted:
            halted_days += 1
        scan_day = ((t - t0) % p.cadence == 0)
        held = qty > 0
        # update trailing peaks on prior close
        peak_px = np.where(held, np.maximum(peak_px, np.nan_to_num(C[t - 1])), peak_px)

        # ---- exits (daily, or only on scan days) ----
        exits = {}
        if not halted and (scan_day or not p.exits_on_cadence):
            for i in np.where(held & valid_now)[0]:
                px = px_now[i]
                if p.atr_mult:
                    if px <= atr_stop[i]:
                        exits[i] = 'stop_atr'
                        continue
                elif p.stop is not None and (px - avg[i]) / avg[i] <= -p.stop:
                    exits[i] = 'stop_loss'
                    continue
                if p.trail is not None and px <= peak_px[i] * (1 - p.trail):
                    exits[i] = 'stop_trail'
                    continue
                if p.mom_exit is not None:
                    # series = closes[..t-1] + open[t]; len k; start=k-1-lookback, end=k-1-skip
                    s_px = C[t - p.lookback, i]
                    e_px = C[t - p.skip, i] if p.skip > 0 else px
                    if s_px > 0 and not np.isnan(e_px) and (e_px - s_px) / s_px < p.mom_exit:
                        exits[i] = 'momentum_reversal'
        if not halted and scan_day:
            # ---- scoring ----
            s_px = C[t - p.lookback]
            e_px = C[t - p.skip] if p.skip > 0 else px_now
            mom = (e_px - s_px) / s_px
            score = 0.6 * mom
            ok = valid_now & ~np.isnan(score)
            conf_ok = np.array([ok[i] and _conf(score[i], p.conf_scale) >= p.conf_thresh for i in range(n)])
            eligible = ok & (conf_ok | held)
            eligible &= ~((cooldown_until > t) & ~held)
            if p.regime_gate == 'spy200' and spy is not None and spy[t - 1] < spy_sma[t - 1]:
                eligible &= held
            for i in exits:
                eligible[i] = False
            targets = {}
            for sl, budget_pct, cap in (('core', p.core_pct, p.max_core), ('satellite', p.sat_pct, p.max_sat)):
                cand = [i for i in np.where(eligible & (sleeve == sl))[0]]
                cand.sort(key=lambda i: -score[i])
                if p.hold_rank_buffer:
                    top = cand[:cap]
                    keep = [i for i in cand[:cap + p.hold_rank_buffer] if held[i] and i not in top]
                    chosen = [i for i in top]
                    # held names inside the buffer displace the weakest non-held top names
                    for k in keep:
                        nonheld = [c for c in chosen if not held[c]]
                        if nonheld:
                            chosen.remove(nonheld[-1]); chosen.append(k)
                    cand = chosen
                else:
                    cand = cand[:cap]
                if not cand:
                    continue
                budget = equity * budget_pct
                k = len(cand)
                while k > 1 and budget / k < equity * p.min_pos:
                    k -= 1
                cand = cand[:k]
                if budget / k < equity * p.min_pos:
                    continue
                per = min(budget / k, equity * p.max_single)
                for i in cand:
                    targets[i] = per
            # ---- reconcile ----
            # sells first (frees cash), then buys
            instr = []
            for i in np.where(held)[0]:
                if not valid_now[i]:
                    continue
                if i in exits:
                    instr.append((i, -qty[i], exits[i]))
                elif i not in targets:
                    instr.append((i, -qty[i], 'not_target'))
            for i, tgt in targets.items():
                tq = int(tgt / px_now[i])
                d = tq - qty[i]
                if d == 0:
                    continue
                if qty[i] != 0 and p.band > 0 and abs(qty[i] * px_now[i] - tgt) <= tgt * p.band:
                    continue
                if qty[i] != 0 and p.min_order and abs(d) * px_now[i] < p.min_order:
                    continue
                instr.append((i, d, 'rebalance'))
            for i, d, why in sorted(instr, key=lambda x: x[1]):
                if d > 0:
                    d = min(d, int(max(cash - p.commission, 0) / px_now[i]))
                    if d <= 0:
                        continue
                fill(i, d, px_now[i], t, why)
        elif not halted and exits:
            for i, why in exits.items():
                fill(i, -qty[i], px_now[i], t, why)
        eq_close = cash + np.nansum(qty * np.where(np.isnan(C[t]), mark, C[t]))
        eq_curve.append(eq_close)
        if qty.any():
            invested_days += 1

    eq = np.array(eq_curve)
    pk = np.maximum.accumulate(eq)
    mdd = float(np.max((pk - eq) / pk)) if len(eq) else 0.0
    years = (t1 - t0) / 252
    # round trips: aggregate partial trims by (sym, entry_date)
    rt = {}
    for sym, pnl, why, ed, xd, closed in trades:
        k = (sym, ed)
        r = rt.setdefault(k, [0.0, why, False])
        r[0] += pnl
        if closed:
            r[1], r[2] = why, True
    closed = [v for v in rt.values() if v[2]]
    wins = [v[0] for v in closed if v[0] > 0]
    losses = [v[0] for v in closed if v[0] <= 0]
    res = dict(
        ret=eq[-1] / p.capital - 1, cagr=(eq[-1] / p.capital) ** (1 / max(years, 1e-9)) - 1, mdd=mdd,
        orders=orders, comm=comm, orders_per_wk=orders / max((t1 - t0) / 5, 1),
        trips=len(closed), win=len(wins) / len(closed) if closed else float('nan'),
        payoff=(np.mean(wins) / -np.mean(losses)) if wins and losses and np.mean(losses) < 0 else float('nan'),
        stopouts=stopouts, reentry10=reentries, halted_days=halted_days, final=eq[-1],
    )
    if record:
        res['curve'] = pd.Series(eq, index=idx[t0:t1])
        res['trades'] = trades
    return res


WINDOWS = [('2020-03-01', '2021-09-01'), ('2021-09-01', '2023-03-01'),
           ('2023-03-01', '2024-09-01'), ('2024-09-01', '2026-10-03')]


def fmt(r):
    return (f"ret {r['ret']*100:7.1f}%  cagr {r['cagr']*100:6.1f}%  mdd {r['mdd']*100:5.1f}%  "
            f"orders {r['orders']:4d} ({r['orders_per_wk']:.2f}/wk) comm ${r['comm']:6.0f}  trips {r['trips']:3d} "
            f"win {r['win']*100:4.0f}% payoff {r['payoff']:.2f}  stops {r['stopouts']:3d} re10 {r['reentry10']:2d} halt {r['halted_days']}")


def windows(uni, p, wins=WINDOWS):
    return [simulate(uni, p, a, b) for a, b in wins]
