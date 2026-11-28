"""2026-11-28: try to break k1 (no commodity ETFs as growth satellites). (a) what the commodity ETFs' round trips earned in
LIVE; (b) paired capital sweep $4k..$6k (21 paths) and 4 start dates on static + full, for several exclusion sets;
(c) static rolling windows. Output: research/data/exp_1128b.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import numpy as np
from shipbar import LIVE_PARAMS as T
from harness import *

END = '2026-11-28'
STARTS = ['2020-03-01', '2021-01-04', '2022-01-03', '2023-01-03']
CAPS = [4000.0 + 100 * k for k in range(21)]
r = replace
COMMOD = ('CPER', 'DBC', 'GLD', 'SLV', 'UNG', 'USO')
CFG = {
    'LIVE': T,
    'no commodities (all 6)': r(T, sat_exclude=COMMOD),
    'no energy (USO, UNG, DBC)': r(T, sat_exclude=('USO', 'UNG', 'DBC')),
    'no metals (GLD, SLV, CPER)': r(T, sat_exclude=('GLD', 'SLV', 'CPER')),
    'no UNG': r(T, sat_exclude=('UNG',)),
    'no USO+UNG': r(T, sat_exclude=('USO', 'UNG')),
}


def one(name):
    p = CFG[name]
    out = {}
    for u in ('static', 'full'):
        U = universe(u)
        out[u] = dict(caps=[simulate(U, r(p, capital=c), STARTS[0], END)['ret'] for c in CAPS],
                      starts=[simulate(U, p, s, END)['ret'] for s in STARTS],
                      wins=[simulate(U, p, a, b) for a, b in WINDOWS[:-1] + [(WINDOWS[-1][0], END)]],
                      mdd=simulate(U, p, STARTS[0], END)['mdd'])
    return name, out


if __name__ == '__main__':
    for u in ('static', 'full'):
        res = simulate(universe(u), T, STARTS[0], END, record=True)
        trips = {}
        for sym, pnl, why, ed, xd, closed in res['trades']:
            trips.setdefault(sym, []).append(pnl)
        com = {s: (len(v), round(sum(v))) for s, v in trips.items() if s in COMMOD}
        print(f'{u}: LIVE commodity-ETF trade legs (n, $pnl):', com, '| total $', sum(v[1] for v in com.values()),
              'of final $', round(res['final']))
    with Pool(min(len(CFG), os.cpu_count() - 1)) as pool:
        out = dict(pool.map(one, list(CFG)))
    base = out['LIVE']
    for u in ('static', 'full'):
        print(f'\n=== {u}, to {END} ===')
        for name, o in out.items():
            b = base[u]
            wc = sum(c > l for c, l in zip(o[u]['caps'], b['caps']))
            ws = sum(c > l for c, l in zip(o[u]['starts'], b['starts']))
            wn = sum(c['ret'] > l['ret'] for c, l in zip(o[u]['wins'], b['wins']))
            print(f"{name:28s} $5k {o[u]['caps'][10]*100:8.0f}% mdd {o[u]['mdd']*100:4.1f} | caps beat LIVE {wc}/21 median {np.median(o[u]['caps'])*100:7.0f}% "
                  f"min {min(o[u]['caps'])*100:6.0f}% | starts {ws}/4 {[round(x*100) for x in o[u]['starts']]} | windows {wn}/4 "
                  f"{[round(w['ret']*100,1) for w in o[u]['wins']]} mdd {[round(w['mdd']*100,1) for w in o[u]['wins']]}")
