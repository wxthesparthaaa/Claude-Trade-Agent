"""Is there post-earnings-announcement drift in OUR universe?  (backlog #10, 2026-11-01)

For every earnings report with both consensus and reported EPS (research/data/earnings.csv, Tiger calendar), enter at
the open of the first session AFTER the reaction day and measure the forward return over 20/40/60 sessions, raw and
net of SPY, split by surprise = (actual - expected) / max(|expected|, 0.10).
Caveat on the t-stats: reports cluster in earnings seasons, so events are not independent -- read them as optimistic.
Usage: python research/earnings_surprise_study.py
"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
from harness import universe, load_panel

earn = pd.read_csv(os.path.join(os.path.dirname(__file__), 'data', 'earnings.csv'), parse_dates=['report_date'])
earn = earn.dropna(subset=['expected_eps', 'actual_eps'])
print(f'reports with EPS: {len(earn)} ({earn.symbol.nunique()} symbols), {earn.report_date.min().date()} -> {earn.report_date.max().date()}')

for uname in ('static', 'full'):
    uni = universe(uname)
    stocks = [s for s, v in uni.items() if v == 'satellite' and s in set(earn.symbol)]
    idx, op, hi, lo, cl = load_panel(stocks + ['SPY'])
    vals, spy_c, spy_o = idx.values, cl['SPY'].values, op['SPY'].values
    rows = []
    for _, r in earn[earn.symbol.isin(stocks)].iterrows():
        o, c = op[r.symbol].values, cl[r.symbol].values
        pos = int(np.searchsorted(vals, np.datetime64(r.report_date), side='left' if r.report_time == '盘前' else 'right'))
        e = pos + 1                                    # first session we could act on the news
        if e >= len(vals) - 61 or np.isnan(o[e]) or np.isnan(spy_o[e]):
            continue
        sp = (r.actual_eps - r.expected_eps) / max(abs(r.expected_eps), 0.10)
        rec = dict(sym=r.symbol, date=r.report_date, surp=sp, ear=c[pos] / c[pos - 1] - 1 if pos > 0 else np.nan)
        for h in (20, 40, 60):
            raw = c[e + h - 1] / o[e] - 1
            rec[f'r{h}'] = raw
            rec[f'x{h}'] = raw - (spy_c[e + h - 1] / spy_o[e] - 1)
        rows.append(rec)
    df = pd.DataFrame(rows).dropna(subset=['surp', 'r60'])
    df['grp'] = pd.cut(df.surp, [-9, -0.10, -0.02, 0.02, 0.10, 9], labels=['miss>10%', 'miss 2-10%', 'inline', 'beat 2-10%', 'beat>10%'])
    print(f'\n=== {uname} satellites: {len(df)} events, {df.sym.nunique()} symbols; surprise median {df.surp.median()*100:.1f}%, beats {np.mean(df.surp > 0.02)*100:.0f}% / misses {np.mean(df.surp < -0.02)*100:.0f}%')
    print('mean forward return from the open after the reaction day (excess = minus SPY):')
    print(f"{'group':>11} {'n':>4} | {'raw20':>6} {'raw60':>6} | {'xs20':>6} {'xs40':>6} {'xs60':>6} | {'t(xs60)':>7} {'hit60':>5}")
    for g, d in list(df.groupby('grp')) + [('ALL', df)]:
        if len(d) < 3: continue
        t = d.x60.mean() / (d.x60.std() / np.sqrt(len(d)))
        print(f"{g:>11} {len(d):>4} | {d.r20.mean()*100:6.1f} {d.r60.mean()*100:6.1f} | {d.x20.mean()*100:6.1f} {d.x40.mean()*100:6.1f} {d.x60.mean()*100:6.1f} | {t:7.2f} {np.mean(d.x60 > 0)*100:5.0f}")
    top, bot = df[df.surp > 0.02], df[df.surp < -0.02]
    for h in (20, 40, 60):
        spread = top[f'x{h}'].mean() - bot[f'x{h}'].mean()
        se = np.sqrt(top[f'x{h}'].var() / len(top) + bot[f'x{h}'].var() / len(bot))
        print(f'  beat-minus-miss excess spread {h}d: {spread*100:+.2f}%  (t {spread/se:+.2f})')
    rho = df[['surp', 'x60']].corr(method='spearman').iloc[0, 1]
    print(f'  Spearman(surprise, 60d excess) = {rho:+.3f} (n={len(df)}, rough t {rho*np.sqrt((len(df)-2)/(1-rho**2)):+.2f})')
    # does the reaction-day move already contain it? (drift conditional on a same-sign first reaction)
    agree = df[(np.sign(df.surp) == np.sign(df.ear)) & (abs(df.surp) > 0.02)]
    print(f'  surprise and day-1 reaction agree: {len(agree)}/{len(df)} events')
