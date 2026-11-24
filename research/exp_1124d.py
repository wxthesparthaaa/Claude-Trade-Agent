"""2026-11-24 (user: drawdown and cash safety do NOT matter, be as aggressive as possible): maximise growth. Each candidate is run on the
static and full universes from $4k/$5k/$6k and from four start dates, so a config that only wins on one lucky path shows up as a low
minimum. Output: research/data/exp_1124d.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import numpy as np
import shipbar
from shipbar import LIVE_PARAMS as T
from harness import *

END = '2026-11-20'
STARTS = ['2020-03-01', '2021-01-04', '2022-01-03', '2023-01-03']
r = replace
A = r(T, core_pct=0.0, sat_pct=1.0, max_sat=2, max_single=0.5)          # step 4 from the last run
LEVX = {'TQQQ': 'satellite', 'SOXL': 'satellite'}
CFG = {
    'LIVE': (T, {}),
    'step1: 2 sats (core 40 QQQ)': (r(T, max_sat=2), {}),
    'A: core 0, 2 sats x 50%': (A, {}),
    'A, 1 satellite x 100%': (r(A, max_sat=1, max_single=1.0), {}),
    'A, 3 sats x 33%': (r(A, max_sat=3, max_single=0.34), {}),
    'A, no halt': (r(A, dd_halt=None), {}),
    'A, no halt, stop 25%': (r(A, dd_halt=None, stop=0.25), {}),
    'A, no halt, no stop': (r(A, dd_halt=None, stop=None), {}),
    'A, stop 25%': (r(A, stop=0.25), {}),
    'A, stop 15%': (r(A, stop=0.15), {}),
    'A, no momentum exit': (r(A, mom_exit=None), {}),
    'A, momentum ranking (not trendq)': (r(A, score_mode='mom'), {}),
    'A + TQQQ/SOXL as satellites': (A, LEVX),
    'A, no halt + TQQQ/SOXL as satellites': (r(A, dd_halt=None), LEVX),
    'core 0, 2 sats, TQQQ core? n/a: core 25 TQQQ': (r(A, core_pct=0.25, sat_pct=0.75, core_switch=('TQQQ', 'CASH', 200), max_single=0.5), {'TQQQ': 'core'}),
}


def one(name):
    p, extra = CFG[name]
    res = {}
    for uname in ('static', 'full'):
        u = universe(uname); u.update(extra)
        res[uname] = {
            'caps': [simulate(u, r(p, capital=c), STARTS[0], END) for c in (4000.0, 5000.0, 6000.0)],
            'starts': [simulate(u, p, s, END) for s in STARTS],
        }
    return name, res


if __name__ == '__main__':
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        out = pool.map(one, list(CFG))
    for uname in ('static', 'full'):
        print(f'\n=== {uname} universe, to {END} ===')
        print(f"{'config':46s} | {'$5k return':>10} {'MDD':>5} | {'$4k/$5k/$6k returns':>22} | {'4 start dates (2020/21/22/23)':>32} | {'min':>6}")
        for name, res in out:
            c, s = res[uname]['caps'], res[uname]['starts']
            allr = [x['ret'] * 100 for x in c + s]
            print(f"{name:46s} | {c[1]['ret']*100:9.0f}% {c[1]['mdd']*100:5.1f} | {' '.join(f'{x['ret']*100:6.0f}' for x in c):>22} | {' '.join(f'{x['ret']*100:7.0f}' for x in s):>32} | {min(allr):6.0f}")
