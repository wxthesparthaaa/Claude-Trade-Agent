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
regime tilts, breadth caution and shorts are all 0/off; dividends are not credited. The sector tilt is modelled
but off by default (Params.sector_tilt_w; shipbar.LIVE_PARAMS turns it on, as live has it).
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


# Rule-based, low-hindsight broadening sets (2026-10-24 run 2):
# BROAD_SAT = the 2020-01 S&P 500 top-30 by market cap not already in the universe, minus dividend-portfolio
#   symbols (KO, VZ, ABBV...) because the two universes must stay disjoint. Picked by 2020 size, not 2026 winners.
# SECTOR_ETF = the SPDR sector ETFs not already held (XLK is core).
BROAD_SAT = ['V', 'JPM', 'UNH', 'MA', 'HD', 'DIS', 'PYPL', 'ADBE', 'NFLX', 'CMCSA', 'PFE', 'MRK',
             'PEP', 'ABT', 'WMT', 'BAC', 'CSCO', 'ORCL']  # JNJ, PG, XOM dropped: dividend universe
SECTOR_ETF = ['XLE', 'XLF', 'XLV', 'XLI', 'XLY', 'XLP', 'XLU', 'XLB', 'XLC']


def universe(name: str) -> Dict[str, str]:
    """'static' | 'full' | any of those plus '+broad' / '+etf' (e.g. 'full+broad+etf')."""
    base, *adds = name.split('+')
    u = {s: 'core' for s in STATIC_CORE}
    u.update({s: 'satellite' for s in STATIC_SAT})
    if base == 'full':
        u.update({s: 'satellite' for s in EXTRA_SAT})
    if 'broad' in adds:
        u.update({s: 'satellite' for s in BROAD_SAT})
    if 'etf' in adds:
        u.update({s: 'satellite' for s in SECTOR_ETF})
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


DEFENSIVE_CORE = ('SCHD', 'VYM', 'AGG', 'TLT')
_vol_cache = {}
# src/sector_rotation.US_SECTOR_ETFS: ETF -> GICS sector id
SECTOR_ETF_IDS = {'XLE': '10', 'XLB': '15', 'XLI': '20', 'XLY': '25', 'XLP': '30', 'XLV': '35', 'XLF': '40',
                  'XLK': '45', 'XLC': '50', 'XLU': '55', 'XLRE': '60'}
_tilt_cache = {}


def _sector_tilts(syms, idx):
    """Live's sector tilt per day/symbol (sector_rotation.rank_us_sectors + get_sector_tilt): sector ETFs ranked by the
    20-day rate of change of ETF/SPY as of that day's close, +1 for the top sector down to -1 for the last. Symbols
    with no GICS sector tag (ETFs, commodities) get 0. Use row t-1 at scan t (the rotation file refreshes daily)."""
    key = (tuple(syms), len(idx))
    if key in _tilt_cache:
        return _tilt_cache[key]
    import json
    read = lambda s: pd.read_csv(os.path.join(BARS, f'{s}.csv'), parse_dates=['date']).set_index('date')['close'].reindex(idx).ffill()
    spy = read('SPY')
    roc = pd.DataFrame({sid: (read(e) / spy).pct_change(20) for e, sid in SECTOR_ETF_IDS.items()}, index=idx)
    rank = roc.rank(axis=1, ascending=False, method='first')
    k = roc.notna().sum(axis=1)
    tilt = (1 - 2 * (rank - 1).div((k - 1).where(k > 1), axis=0)).fillna(0.0)
    tags = json.load(open(os.path.join(HERE, '..', 'config', 'sector_tags.json')))
    out = np.zeros((len(idx), len(syms)))
    for j, s in enumerate(syms):
        sid = (tags.get(s) or {}).get('gics_sector_id')
        if sid in tilt.columns:
            out[:, j] = tilt[sid].values
    _tilt_cache[key] = out
    return out


def _volumes(syms, idx):
    """Daily volume panel aligned to the price panel (research features only)."""
    key = (tuple(syms), len(idx))
    if key not in _vol_cache:
        _vol_cache[key] = np.column_stack([
            pd.read_csv(os.path.join(BARS, f'{s}.csv'), parse_dates=['date']).set_index('date')['volume'].reindex(idx).values
            for s in syms])
    return _vol_cache[key]


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
    # --- added 2026-10-10 ---
    halt_mode: str = 'all'             # 'all' = live (halt blocks every order); 'exits_ok' = halt blocks buys only
    group_cap: Optional[int] = None    # max satellites per GICS industry group (config/sector_tags.json)
    corr_cap: Optional[float] = None   # skip a satellite whose 63d return corr with an already-picked one > this
    halt_reset: Optional[int] = None   # after N consecutive halted days, re-base the peak to current equity
    score_mode: str = 'mom'            # 'mom' = live; 'mom_vol' = rank by momentum / 63d vol (conf gate unchanged)
    # --- added 2026-10-17 ---
    halt_peak_window: Optional[int] = None  # halt measures drawdown from the max of the last N daily closes (None = all-time peak, live)
    sma_exit: Optional[int] = None     # exit a held name when its prior close < its N-day SMA ('stop_sma', so cooldown applies)
    crash_exit: Optional[tuple] = None # (k, thresh): exit when open[t]/close[t-k]-1 < thresh ('stop_crash')
    peak_exit: Optional[float] = None  # exit when open[t] is this far below the 63d high close ('stop_peak'), unlike `trail` independent of entry
    # --- added 2026-10-24 ---
    band_sched: Optional[tuple] = None # ((date_str, band), ...) ascending; band in force = last entry dated <= today (walk-forward re-tune)
    min_hold: int = 0                  # a held name dropped from targets is kept (not sold 'not_target') until held >= N days; stop/momentum exits unaffected
    # --- added 2026-10-24 (run 2) ---
    # score_mode also accepts: 'blend' (mean of 126/21 and 252/21 momentum), 'hi52' (close/252d-high, among
    # names with positive 126/21 momentum), 'trendq' (126d log-price slope x R^2). Conf gate stays on live score.
    trend_win: int = 126               # window for score_mode='trendq' / 'mom_r2' / 'r2_gate'
    r2_min: float = 0.5                # score_mode='r2_gate' threshold
    gap_skip: Optional[float] = None   # no NEW entry when open[t]/close[t-1]-1 > this
    rev_skip: Optional[float] = None   # no NEW entry when close[t-1]/close[t-6]-1 > this (5-day blow-off)
    # sat_weight_scheme: 'equal' (live) | 'invvol' (satellite budget split by 1/63d vol, clipped to [min_pos, max_single])
    # --- added 2026-10-31 ---
    # score_mode also accepts: 'tstat' (slope / its std error), 'tq_blend' (mean trendq over 63/126/252),
    # 'tq_resid' (trendq of the log-price residual after removing beta x SPY), 'tq_grp' (trendq minus the median of
    # its GICS group), 'tq_confirm' (trendq, unrankable while the 21d return is negative), 'tq_vol' (trendq x 63d
    # up/down volume ratio clipped to [0.5, 2]), 'tq_ead' (trendq + ead_bonus if a >=3% gap-up on >=2x volume in the last 60d).
    core_score_mode: Optional[str] = None  # rank the core sleeve by this mode instead of score_mode
    ead_bonus: float = 0.10
    share_round: str = 'floor'         # 'nearest': target shares rounded to nearest (never above max_single); live floors
    cash_sweep: Optional[float] = None # idle cash above this fraction of equity buys whole shares of targets, most underweight first, up to target*(1+band)
    sweep_min: float = 100.0           # smallest sweep order worth a commission
    min_rank_core: Optional[float] = None  # a core name whose rank key is below this can't be a target (even if held)
    min_rank_sat: Optional[float] = None   # same for satellites
    sat_off: Optional[str] = None      # regime that cuts the satellite budget: 'spy_cross' (SMA50<200), 'spy200', 'qqq50', 'breadth', 'vol'
    sat_off_scale: float = 0.0         # satellite budget multiplier while sat_off is active
    sat_off_to: str = 'core'           # the freed budget goes to 'core' (capped by max_single) or 'cash'
    breadth_min: float = 0.40          # sat_off='breadth': fraction of the universe above its 200d SMA
    vol_max: float = 0.25              # sat_off='vol': SPY 20d annualised realised vol
    core_defensive: bool = False       # while QQQ < its 50d SMA the core ranks only SCHD/VYM/AGG/TLT, conf gate waived
    conv_w: Optional[tuple] = None     # satellite budget weights by rank, e.g. (0.4, 0.35, 0.25), clipped to [min_pos, max_single]
    chase_skip: Optional[float] = None # no NEW entry when open[t] is more than this above the 20d SMA
    swap_margin: Optional[float] = None  # a held name outside the top cap stays unless the weakest new pick out-ranks it by this much
    min_bars: int = 0                  # no NEW entry with fewer than this many bars of history
    sector_tilt_w: float = 0.0         # composite score += w * sector tilt (live growth's weight is 0.1, see _sector_tilts); drives the conf gate
    # halt_mode also accepts 'derisk': while halted, keep scanning and exiting, with the satellite budget x halt_sat_scale
    halt_sat_scale: float = 0.0
    halt_release: Optional[str] = None # 'spy200': a halt ends, and the peak re-bases to current equity, once SPY closes above its 200d SMA


_GROUPS = None


def groups():
    global _GROUPS
    if _GROUPS is None:
        import json
        path = os.path.join(HERE, '..', 'config', 'sector_tags.json')
        try:
            d = json.load(open(path))
            _GROUPS = {k: (v.get('gics_group_id') or k) for k, v in d.items()}
        except Exception:
            _GROUPS = {}
    return _GROUPS


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
    sma = pd.DataFrame(C).rolling(p.sma_exit).mean().values if p.sma_exit else None
    hi63 = pd.DataFrame(C).rolling(63, min_periods=20).max().values if p.peak_exit else None
    # 2026-10-31 features: only built when used
    sma20 = pd.DataFrame(C).rolling(20).mean().values if p.chase_skip is not None else None
    sma200 = pd.DataFrame(C).rolling(200).mean().values if p.sat_off == 'breadth' else None
    bars_seen = (~np.isnan(C)).cumsum(axis=0) if p.min_bars else None
    spy50 = pd.Series(spy).rolling(50).mean().values if spy is not None else None
    spy_vol = pd.Series(spy).pct_change().rolling(20).std().values * np.sqrt(252) if spy is not None else None
    qqq50 = pd.Series(C[:, syms.index('QQQ')]).rolling(50).mean().values if 'QQQ' in syms else None
    V = _volumes(syms, idx) if p.score_mode in ('tq_vol', 'tq_ead') else None
    Vavg = pd.DataFrame(V).rolling(20).mean().values if V is not None else None
    STILT = _sector_tilts(syms, idx) if p.sector_tilt_w else None
    n = len(syms)
    G = groups()
    grp = np.array([G.get(s, s) for s in syms])
    R = np.vstack([np.full((1, n), np.nan), C[1:] / C[:-1] - 1])
    sleeve = np.array([uni[s] for s in syms])
    t0 = int(np.searchsorted(idx.values, np.datetime64(start)))
    t1 = int(np.searchsorted(idx.values, np.datetime64(end)))
    t0 = max(t0, p.lookback + 2, p.trend_win + 2 if p.score_mode in ("trendq", "mom_r2", "r2_gate") else 0)

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
    halt_run = 0
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

    sched = [(np.datetime64(d), b) for d, b in p.band_sched] if p.band_sched else None
    band = p.band
    for t in range(t0, t1):
        if sched:
            for d, b in sched:
                if d <= idx.values[t]:
                    band = b
        px_now = O[t]
        valid_now = ~np.isnan(px_now)
        mark = np.where(valid_now, px_now, C[t - 1])
        equity = cash + np.nansum(qty * mark)
        if p.halt_peak_window:
            peak_eq = max([equity] + (eq_curve[-p.halt_peak_window:] if eq_curve else [p.capital]))
        else:
            peak_eq = max(peak_eq, equity)
        halted = p.dd_halt is not None and (peak_eq - equity) / peak_eq >= p.dd_halt
        if halted and p.halt_release == 'spy200' and spy[t - 1] > spy_sma[t - 1]:
            peak_eq = equity
            halted = False
        if halted:
            halted_days += 1
            halt_run += 1
            if p.halt_reset and halt_run >= p.halt_reset:
                peak_eq = equity
                halted = False
                halt_run = 0
        else:
            halt_run = 0
        derisk = halted and p.halt_mode == 'derisk'
        if derisk:
            halted = False   # keeps trading, but the satellite budget is scaled below
        scan_day = ((t - t0) % p.cadence == 0)
        held = qty > 0
        # update trailing peaks on prior close
        peak_px = np.where(held, np.maximum(peak_px, np.nan_to_num(C[t - 1])), peak_px)

        # ---- exits (daily, or only on scan days) ----
        exits = {}
        exits_allowed = (not halted) or p.halt_mode == 'exits_ok'
        if exits_allowed and (scan_day or not p.exits_on_cadence):
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
                if p.sma_exit and not np.isnan(sma[t - 1, i]) and C[t - 1, i] < sma[t - 1, i]:
                    exits[i] = 'stop_sma'
                    continue
                if p.crash_exit:
                    k, th = p.crash_exit
                    ref = C[t - k, i]
                    if ref > 0 and px / ref - 1 < th:
                        exits[i] = 'stop_crash'
                        continue
                if p.peak_exit and not np.isnan(hi63[t - 1, i]) and px <= hi63[t - 1, i] * (1 - p.peak_exit):
                    exits[i] = 'stop_peak'
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
            if p.sector_tilt_w:
                score = score + p.sector_tilt_w * STILT[t - 1]

            def tq_parts(win):
                y = np.log(C[t - win:t])
                x = np.arange(float(win))
                xm = x - x.mean()
                ym = y - np.nanmean(y, axis=0)
                slope = np.nansum(xm[:, None] * ym, axis=0) / (xm ** 2).sum()
                ss_tot = np.nansum(ym ** 2, axis=0)
                ss_res = np.nansum((ym - slope * xm[:, None]) ** 2, axis=0)
                r2 = 1 - ss_res / np.where(ss_tot > 0, ss_tot, np.nan)
                return slope, r2, ~np.isnan(y).any(axis=0), ss_res, (xm ** 2).sum()

            def tq(win):
                slope, r2, full_win, _, _ = tq_parts(win)
                return np.where(full_win, slope * 252 * r2, np.nan)

            def rank_for(mode):
                if mode == 'mom_vol':
                    vol = np.nanstd(R[t - 63:t], axis=0) * np.sqrt(252)
                    return mom / np.where(vol > 0, vol, np.nan)
                if mode == 'blend':
                    s12 = C[t - 252] if t >= 252 else np.full(n, np.nan)
                    m12 = (e_px - s12) / s12
                    return np.where(np.isnan(m12), mom, 0.5 * (mom + m12))
                if mode == 'hi52':
                    h = np.nanmax(C[max(t - 252, 0):t], axis=0)
                    return np.where(mom > 0, C[t - 1] / h, np.nan)
                if mode in ('trendq', 'mom_r2', 'r2_gate'):
                    slope, r2, full_win, _, _ = tq_parts(p.trend_win)
                    if mode == 'trendq':
                        return np.where(full_win, slope * 252 * r2, np.nan)  # needs a full window
                    if mode == 'mom_r2':      # live momentum, scaled by trend smoothness
                        return np.where(full_win, mom * np.clip(r2, 0, 1), np.nan)
                    # 'r2_gate': live momentum, but R^2 < r2_min can't rank
                    return np.where(full_win & (r2 >= p.r2_min), score, np.nan)
                if mode == 'tstat':
                    slope, _, full_win, ss_res, sxx = tq_parts(p.trend_win)
                    se = np.sqrt(ss_res / (p.trend_win - 2) / sxx)
                    return np.where(full_win & (se > 0), slope / np.where(se > 0, se, np.nan), np.nan)
                if mode == 'tq_blend':
                    return np.nanmean(np.vstack([tq(63), tq(126), tq(252) if t >= 252 else np.full(n, np.nan)]), axis=0)
                if mode == 'tq_resid':
                    w = p.trend_win
                    y = np.log(C[t - w:t])
                    m = np.log(spy[t - w:t])
                    my, mm = np.nanmean(y, axis=0), np.nanmean(m)
                    beta = np.nansum((y - my) * (m - mm)[:, None], axis=0) / np.nansum((m - mm) ** 2)
                    res = y - beta * (m - mm)[:, None]
                    x = np.arange(float(w)); xm = x - x.mean()
                    rm = res - np.nanmean(res, axis=0)
                    sl = np.nansum(xm[:, None] * rm, axis=0) / (xm ** 2).sum()
                    st = np.nansum(rm ** 2, axis=0)
                    sr = np.nansum((rm - sl * xm[:, None]) ** 2, axis=0)
                    r2 = 1 - sr / np.where(st > 0, st, np.nan)
                    return np.where(~np.isnan(y).any(axis=0), sl * 252 * r2, np.nan)
                if mode == 'tq_grp':
                    k = tq(p.trend_win)
                    out = k.copy()
                    for g in set(grp):
                        m = grp == g
                        if m.sum() > 1 and (~np.isnan(k[m])).any():
                            out[m] = k[m] - np.nanmedian(k[m])
                    return out
                if mode == 'tq_confirm':
                    return np.where(C[t - 1] >= C[t - 21], tq(p.trend_win), np.nan)
                if mode == 'tq_vol':
                    r, v = R[t - 63:t], V[t - 63:t]
                    up = np.nansum(np.where(r > 0, v, 0.0), axis=0)
                    dn = np.nansum(np.where(r < 0, v, 0.0), axis=0)
                    return tq(p.trend_win) * np.clip(up / np.where(dn > 0, dn, np.nan), 0.5, 2.0)
                if mode == 'tq_ead':
                    gap = O[t - 60:t] / C[t - 61:t - 1] - 1
                    surge = V[t - 60:t] >= 2 * Vavg[t - 61:t - 1]
                    return tq(p.trend_win) + p.ead_bonus * ((gap >= 0.03) & surge).any(axis=0)
                return score

            rank_key = rank_for(p.score_mode)
            if p.core_score_mode:
                rank_key = np.where(sleeve == 'core', rank_for(p.core_score_mode), rank_key)
            ok = valid_now & ~np.isnan(score)
            conf_ok = np.array([ok[i] and _conf(score[i], p.conf_scale) >= p.conf_thresh for i in range(n)])
            eligible = ok & (conf_ok | held)
            eligible &= ~((cooldown_until > t) & ~held)
            if p.gap_skip is not None:
                eligible &= held | ~(px_now / C[t - 1] - 1 > p.gap_skip)
            if p.rev_skip is not None:
                eligible &= held | ~(C[t - 1] / C[t - 6] - 1 > p.rev_skip)
            if p.regime_gate == 'spy200' and spy is not None and spy[t - 1] < spy_sma[t - 1]:
                eligible &= held
            if p.chase_skip is not None:
                eligible &= held | ~(px_now > sma20[t - 1] * (1 + p.chase_skip))
            if p.min_bars:
                eligible &= held | (bars_seen[t - 1] >= p.min_bars)
            if p.min_rank_core is not None:
                eligible &= ~((sleeve == 'core') & ~(np.nan_to_num(rank_key, nan=-1e9) >= p.min_rank_core))
            if p.min_rank_sat is not None:
                eligible &= ~((sleeve == 'satellite') & ~(np.nan_to_num(rank_key, nan=-1e9) >= p.min_rank_sat))
            if p.core_defensive and ('QQQ' not in syms or C[t - 1, syms.index('QQQ')] < qqq50[t - 1]):
                is_def = np.array([s in DEFENSIVE_CORE for s in syms])
                eligible &= (sleeve != 'core') | is_def
                eligible |= (sleeve == 'core') & is_def & ok
            for i in exits:
                eligible[i] = False
            core_pct, sat_pct = p.core_pct, p.sat_pct
            if derisk:
                sat_pct *= p.halt_sat_scale
            if p.sat_off:
                off = {'spy_cross': lambda: spy50[t - 1] < spy_sma[t - 1],
                       'spy200': lambda: spy[t - 1] < spy_sma[t - 1],
                       'qqq50': lambda: C[t - 1, syms.index('QQQ')] < qqq50[t - 1],
                       'breadth': lambda: np.nanmean(C[t - 1] > sma200[t - 1]) < p.breadth_min,
                       'vol': lambda: spy_vol[t - 1] > p.vol_max}[p.sat_off]()
                if off:
                    freed = sat_pct * (1 - p.sat_off_scale)
                    sat_pct -= freed
                    if p.sat_off_to == 'core':
                        core_pct += freed
            targets = {}
            for sl, budget_pct, cap in (('core', core_pct, p.max_core), ('satellite', sat_pct, p.max_sat)):
                if budget_pct <= 0:
                    continue
                cand = [i for i in np.where(eligible & (sleeve == sl))[0]]
                cand.sort(key=lambda i: -(rank_key[i] if not np.isnan(rank_key[i]) else -1e9))
                if sl == 'satellite' and (p.group_cap or p.corr_cap):
                    picked = []
                    for i in cand:
                        if p.group_cap and sum(grp[j] == grp[i] for j in picked) >= p.group_cap:
                            continue
                        if p.corr_cap and picked:
                            win = R[t - 63:t]
                            ok_c = True
                            for j in picked:
                                a, b = win[:, i], win[:, j]
                                m = ~(np.isnan(a) | np.isnan(b))
                                if m.sum() > 30 and np.corrcoef(a[m], b[m])[0, 1] > p.corr_cap:
                                    ok_c = False
                                    break
                            if not ok_c:
                                continue
                        picked.append(i)
                        if len(picked) >= cap + p.hold_rank_buffer:
                            break
                    cand = picked
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
                elif p.swap_margin is not None:
                    chosen = cand[:cap]
                    for k in [i for i in cand[cap:] if held[i]]:
                        new = [c for c in chosen if not held[c]]
                        if new and rank_key[new[-1]] - rank_key[k] < p.swap_margin:
                            chosen.remove(new[-1]); chosen.append(k)
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
                if sl == 'satellite' and p.sat_weight_scheme == 'invvol' and k > 1:
                    vol = np.nanstd(R[t - 63:t][:, cand], axis=0)
                    w = 1.0 / np.where(vol > 0, vol, np.nan)
                    w = np.nan_to_num(w / np.nansum(w), nan=1.0 / k)
                    for i, wi in zip(cand, w):
                        targets[i] = float(np.clip(budget * wi, equity * p.min_pos, equity * p.max_single))
                elif sl == 'satellite' and p.conv_w and k > 1:
                    w = np.array(p.conv_w[:k], dtype=float)
                    for i, wi in zip(cand, w / w.sum()):
                        targets[i] = float(np.clip(budget * wi, equity * p.min_pos, equity * p.max_single))
                else:
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
                    if p.min_hold and t - entry_t[i] < p.min_hold:
                        continue
                    instr.append((i, -qty[i], 'not_target'))
            for i, tgt in targets.items():
                tq_ = int(tgt / px_now[i])
                if p.share_round == 'nearest' and round(tgt / px_now[i]) * px_now[i] <= equity * p.max_single:
                    tq_ = int(round(tgt / px_now[i]))
                d = tq_ - qty[i]
                if d == 0:
                    continue
                if qty[i] != 0 and band > 0 and abs(qty[i] * px_now[i] - tgt) <= tgt * band:
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
            if p.cash_sweep is not None and targets and cash > equity * p.cash_sweep:
                gaps = sorted(targets, key=lambda i: qty[i] * px_now[i] - targets[i])
                for i in gaps:
                    room = min(targets[i] * (1 + band), equity * p.max_single) - qty[i] * px_now[i]
                    d = min(int(room / px_now[i]), int(max(cash - p.commission, 0) / px_now[i]))
                    if d > 0 and d * px_now[i] >= p.sweep_min:
                        fill(i, d, px_now[i], t, 'sweep')
        elif exits:
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
        res['holdings'] = {syms[i]: int(qty[i]) for i in np.where(qty > 0)[0]}
        res['cash'] = cash
    return res


WINDOWS = [('2020-03-01', '2021-09-01'), ('2021-09-01', '2023-03-01'),
           ('2023-03-01', '2024-09-01'), ('2024-09-01', '2026-10-03')]


def fmt(r):
    return (f"ret {r['ret']*100:7.1f}%  cagr {r['cagr']*100:6.1f}%  mdd {r['mdd']*100:5.1f}%  "
            f"orders {r['orders']:4d} ({r['orders_per_wk']:.2f}/wk) comm ${r['comm']:6.0f}  trips {r['trips']:3d} "
            f"win {r['win']*100:4.0f}% payoff {r['payoff']:.2f}  stops {r['stopouts']:3d} re10 {r['reentry10']:2d} halt {r['halted_days']}")


def windows(uni, p, wins=WINDOWS):
    return [simulate(uni, p, a, b) for a, b in wins]
