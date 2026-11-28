"""2026-11-27 (user: apply Jared Tadler's "inchworm" idea -- cut the C+ trades, keep the base hits, then chase A+).
Step 1 of 2: does the live system HAVE a bad left tail that is identifiable BEFORE entry?
Runs the CURRENT live growth config (shipbar.LIVE_PARAMS: two satellites, no halt) with record=True, rebuilds every closed
round trip's return from the bars (entry/exit fill at the day's open, as the harness does), attaches entry-time features
(only information known at the entry scan: closes[..t-1] + open[t]), then reports
  (a) the outcome distribution (is it a bell curve? where does the money come from?),
  (b) "remove the C+ and A+ and keep the base hits" arithmetic,
  (c) for each feature, outcome by tercile: does the worst tercile of the feature carry the losers?
Output: research/data/inchworm_study.txt
"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
import numpy as np
import pandas as pd
import shipbar
from harness import *

END = '2026-11-20'
START = '2020-03-01'
P = shipbar.LIVE_PARAMS


def trips_for(uname):
    uni = universe(uname)
    res = simulate(uni, P, START, END, record=True)
    syms = [s for s in uni if s in load_panel(list(uni))[4].columns]
    idx, op, hi, lo, cl = load_panel(list(uni))
    O, C, H, L = op[syms].values, cl[syms].values, hi[syms].values, lo[syms].values
    spy = cl['SPY'].values
    spy200 = pd.Series(spy).rolling(200).mean().values
    qqq = C[:, syms.index('QQQ')]
    qqq200 = pd.Series(qqq).rolling(200).mean().values
    Cd = pd.DataFrame(C)
    e9, e21 = Cd.ewm(span=9, adjust=False).mean().values, Cd.ewm(span=21, adjust=False).mean().values
    m20, m50, m200 = Cd.rolling(20).mean().values, Cd.rolling(50).mean().values, Cd.rolling(200).mean().values
    adr = pd.DataFrame(H / L - 1).rolling(20).mean().values
    R = np.vstack([np.full((1, len(syms)), np.nan), C[1:] / C[:-1] - 1])
    pos = {d: k for k, d in enumerate(idx.date)}

    # round trips: aggregate partial trims by (sym, entry_date); keep closed ones
    rt = {}
    for sym, pnl, why, ed, xd, closed in res['trades']:
        r = rt.setdefault((sym, ed), {'pnl': 0.0, 'why': why, 'exit': xd, 'closed': False})
        r['pnl'] += pnl
        if closed:
            r.update(why=why, exit=xd, closed=True)
    rows = []
    last_stop = {}
    for (sym, ed), r in sorted(rt.items(), key=lambda kv: kv[0][1]):
        if not r['closed']:
            continue
        i, t, tx = syms.index(sym), pos[ed], pos[r['exit']]
        if t < 260 or O[t, i] <= 0 or np.isnan(O[tx, i]):
            continue
        y = np.log(C[t - 126:t, i]); x = np.arange(126.0); xm = x - x.mean(); ym = y - y.mean()
        slope = (xm * ym).sum() / (xm ** 2).sum()
        r2 = 1 - ((ym - slope * xm) ** 2).sum() / (ym ** 2).sum()
        # trend-quality percentile among satellites on that day
        tqs = []
        for j, s in enumerate(syms):
            if uni[s] != 'satellite' or np.isnan(C[t - 126:t, j]).any():
                continue
            yy = np.log(C[t - 126:t, j]); yym = yy - yy.mean(); sl = (xm * yym).sum() / (xm ** 2).sum()
            rr = 1 - ((yym - sl * xm) ** 2).sum() / (yym ** 2).sum()
            tqs.append(sl * 252 * rr)
        tq = slope * 252 * r2
        ret = O[tx, i] / O[t, i] - 1
        rows.append(dict(
            sym=sym, entry=ed, exit=r['exit'], why=r['why'], days=tx - t, ret=ret, pnl=r['pnl'],
            tq=tq, tq_pct=float(np.mean(np.array(tqs) <= tq)), r2=r2,
            mom21=C[t - 1, i] / C[t - 22, i] - 1, run5=C[t - 1, i] / C[t - 6, i] - 1,
            ext20=O[t, i] / m20[t - 1, i] - 1, gap=O[t, i] / C[t - 1, i] - 1,
            vol63=np.nanstd(R[t - 63:t, i]) * np.sqrt(252), adr=adr[t - 1, i],
            off_hi=C[t - 1, i] / np.nanmax(C[t - 252:t, i]), above200=C[t - 1, i] / m200[t - 1, i] - 1,
            stack=bool((C[t - 1, i] > e9[t - 1, i] > e21[t - 1, i] > m50[t - 1, i] > m200[t - 1, i])),
            qqq_on=bool(qqq[t - 1] > qqq200[t - 1]), spy_on=bool(spy[t - 1] > spy200[t - 1]),
            reentry=bool(sym in last_stop and (ed - last_stop[sym]).days <= 14)))
        if r['why'].startswith('stop'):
            last_stop[sym] = r['exit']
    return pd.DataFrame(rows), res


def dist(df, label, out):
    out.append(f'\n--- {label}: {len(df)} closed round trips ---')
    rr = df['ret']
    out.append(f"win rate {np.mean(rr > 0)*100:.0f}%  mean {rr.mean()*100:+.1f}%  median {rr.median()*100:+.1f}%  "
               f"avg win {rr[rr > 0].mean()*100:+.1f}%  avg loss {rr[rr <= 0].mean()*100:+.1f}%  skew {rr.skew():+.2f}")
    qs = rr.quantile([.05, .1, .25, .5, .75, .9, .95])
    out.append('quantiles  ' + '  '.join(f'p{int(q*100)} {v*100:+.0f}%' for q, v in qs.items()))
    bins = [(-9, -0.20, 'stopped (<= -20%)'), (-0.20, -0.05, 'C+ loser -20..-5%'), (-0.05, 0.05, 'scratch -5..+5%'),
            (0.05, 0.25, 'base hit +5..+25%'), (0.25, 0.60, 'good +25..+60%'), (0.60, 99, 'A+ (> +60%)')]
    tot_log = np.log1p(rr).sum()
    out.append(f"{'bucket':24s} {'n':>4s} {'share':>6s} {'avg':>8s} {'sum of log-returns':>20s} {'% of total':>11s}")
    for lo_, hi_, name in bins:
        m = (rr > lo_) & (rr <= hi_) if lo_ > -9 else (rr <= hi_)
        s = np.log1p(rr[m]).sum()
        out.append(f"{name:24s} {m.sum():4d} {m.mean()*100:5.0f}% {rr[m].mean()*100 if m.any() else 0:+7.1f}% {s:20.2f} {s/tot_log*100:10.0f}%")
    # the video's thought experiment
    mid = (rr > -0.05) & (rr <= 0.25)
    out.append(f"'keep only the middle' (-5%..+25%): n={mid.sum()}  mean {rr[mid].mean()*100:+.1f}%  sum of log-returns {np.log1p(rr[mid]).sum():.2f} vs all {tot_log:.2f}")
    nol = rr > -0.05
    out.append(f"'remove every loser worse than -5%' (hindsight): sum log {np.log1p(rr[nol]).sum():.2f} vs all {tot_log:.2f}")
    nos = rr <= 0.60
    out.append(f"'remove every A+ (> +60%)' (hindsight): sum log {np.log1p(rr[nos]).sum():.2f} vs all {tot_log:.2f}")
    top5 = np.sort(np.log1p(rr))[::-1][:5].sum()
    out.append(f"best 5 trips = {top5:.2f} of {tot_log:.2f} total log-return ({top5/tot_log*100:.0f}%)")


FEATURES = [('tq', 'trend quality score'), ('tq_pct', 'trend-quality percentile in universe'), ('r2', 'R^2 of the 126d trend'),
            ('mom21', '21d return (extension)'), ('run5', '5d run-up'), ('ext20', 'open vs 20d SMA'), ('gap', 'open gap vs prior close'),
            ('vol63', '63d annualised vol'), ('adr', '20d avg daily range'), ('off_hi', 'close / 252d high'), ('above200', 'close vs 200d SMA')]


def tercile_table(df, out):
    out.append(f"\n{'feature':38s} {'tercile':>8s} {'range':>20s} {'n':>4s} {'mean':>7s} {'median':>7s} {'win%':>5s} {'<=-20%':>7s} {'>+60%':>6s}")
    for col, label in FEATURES:
        q = pd.qcut(df[col].rank(method='first'), 3, labels=['low', 'mid', 'high'])
        for k in q.cat.categories:
            s = df[q == k]
            rr = s['ret']
            out.append(f"{label:38s} {k:>8s} {s[col].min():9.2f}..{s[col].max():8.2f} {len(s):4d} {rr.mean()*100:+6.1f}% {rr.median()*100:+6.1f}% "
                       f"{np.mean(rr > 0)*100:4.0f}% {np.mean(rr <= -0.20)*100:6.0f}% {np.mean(rr > 0.60)*100:5.0f}%")
    for col, label in [('stack', 'full MA stack at entry'), ('qqq_on', 'QQQ above 200d'), ('spy_on', 'SPY above 200d'), ('reentry', 're-entry <=14d after a stop')]:
        for val in (True, False):
            s = df[df[col] == val]
            if len(s):
                rr = s['ret']
                out.append(f"{label:38s} {str(val):>8s} {'':20s} {len(s):4d} {rr.mean()*100:+6.1f}% {rr.median()*100:+6.1f}% "
                           f"{np.mean(rr > 0)*100:4.0f}% {np.mean(rr <= -0.20)*100:6.0f}% {np.mean(rr > 0.60)*100:5.0f}%")


def exits(df, out):
    out.append(f"\n{'exit reason':22s} {'n':>4s} {'mean':>8s} {'median':>8s} {'avg days':>9s}")
    for why, s in df.groupby(df['why'].str.replace(r'_.*', '', regex=True) if False else 'why'):
        out.append(f"{why:22s} {len(s):4d} {s['ret'].mean()*100:+7.1f}% {s['ret'].median()*100:+7.1f}% {s['days'].mean():9.0f}")


if __name__ == '__main__':
    out = []
    for uname in ('static', 'full'):
        df, res = trips_for(uname)
        df.to_csv(f'research/data/inchworm_trips_{uname}.csv', index=False)
        out.append(f"\n================ {uname} universe, {START}..{END}, LIVE (big-bet) config: final return {res['ret']*100:.0f}%, mdd {res['mdd']*100:.0f}% ================")
        dist(df, uname, out)
        exits(df, out)
        tercile_table(df, out)
    text = '\n'.join(out)
    open('research/data/inchworm_study.txt', 'w', encoding='utf-8').write(text)
    print(text)
