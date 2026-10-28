"""Does a rebalance tolerance band suit the dividend strategy?

Isolates the ONE thing the band changes -- how finely already-held positions get re-trimmed -- by holding the
set of names fixed (the band never changes which names are held: new entries and full exits bypass it) and
rebalancing equal-weight to the live target size once per scan day, using the REAL execution.reconcile_positions
(integer shares, never rounds up), $2.98 per order, fills at the day's close. Price-only (dividends are paid on
roughly the same shares either way, so they do not separate the variants).
"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from execution import reconcile_positions, CurrentPosition
from portfolio_construction import PlannedPosition

BARS = os.path.join(os.path.dirname(__file__), 'data', 'bars_div')
FEE, CAPITAL, CAP_PCT = 2.98, 31000.0, 0.15


def load(syms):
    cols = {s: pd.read_csv(os.path.join(BARS, f'{s}.csv'), parse_dates=['date']).set_index('date')['close'] for s in syms}
    return pd.DataFrame(cols).dropna().loc['2020-06-01':]


def run(prices, target_pct, band):
    cash, shares = CAPITAL, {s: 0 for s in prices.columns}
    orders = fees = days_over_cap = 0
    max_w, max_dev, peak, mdd = 0.0, 0.0, CAPITAL, 0.0
    for dt, row in prices.iterrows():
        px = row.to_dict()
        cap = cash + sum(shares[s] * px[s] for s in shares)
        targets = [PlannedPosition(s, 'core', target_pct * cap, target_pct) for s in shares]
        cur = {s: CurrentPosition(s, q, px[s]) for s, q in shares.items() if q}
        for i in reconcile_positions(targets, cur, px, rebalance_band_pct=band):
            q = i.quantity if i.action == 'BUY' else -i.quantity
            shares[i.symbol] += q
            cash -= q * px[i.symbol] + FEE
            orders += 1; fees += FEE
        cap = cash + sum(shares[s] * px[s] for s in shares)
        peak = max(peak, cap); mdd = max(mdd, (peak - cap) / peak)
        if dt > prices.index[0]:
            ws = [shares[s] * px[s] / cap for s in shares]
            max_w = max(max_w, max(ws)); max_dev = max(max_dev, max(abs(w - target_pct) / target_pct for w in ws))
            days_over_cap += any(w > CAP_PCT for w in ws)
    years = (prices.index[-1] - prices.index[0]).days / 365.25
    return dict(final=cap, orders=orders, per_year=orders / years, fees=fees, fee_pct_yr=fees / CAPITAL / years * 100,
                ret=(cap / CAPITAL - 1) * 100, mdd=mdd * 100, max_w=max_w * 100, max_dev=max_dev * 100, over_cap_days=days_over_cap)


SETS = {
    'A current holdings (VZ JEPI SPYD MO KO ABBV @14%)': (['VZ', 'JEPI', 'SPYD', 'MO', 'KO', 'ABBV'], 0.14),
    'B other names (O JNJ PG XOM CVX HDV @14%)': (['O', 'JNJ', 'PG', 'XOM', 'CVX', 'HDV'], 0.14),
    'C all 13 US names @6.5%': (['JEPI', 'SPYD', 'O', 'KO', 'JNJ', 'PG', 'VZ', 'XOM', 'CVX', 'ABBV', 'MO', 'VNQ', 'HDV'], 0.065),
}
if __name__ == '__main__':
    for name, (syms, tgt) in SETS.items():
        px = load(syms)
        print(f'\n== {name}  [{px.index[0].date()} -> {px.index[-1].date()}, {len(px)} days]')
        print(f"{'band':>5} | {'orders':>6} {'/yr':>5} | {'fees$':>7} {'fee %cap/yr':>11} | {'net ret%':>8} | {'maxDD%':>6} | {'max wt%':>7} {'max drift%':>10} {'days>15%':>8}")
        base = None
        for b in (0.0, 0.1, 0.2, 0.3, 0.5):
            r = run(px, tgt, b); base = base or r
            print(f"{b:>5.1f} | {r['orders']:>6} {r['per_year']:>5.0f} | {r['fees']:>7.0f} {r['fee_pct_yr']:>11.2f} | {r['ret']:>8.1f} | {r['mdd']:>6.1f} | {r['max_w']:>7.1f} {r['max_dev']:>10.0f} {r['over_cap_days']:>8}")
