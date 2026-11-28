"""2026-11-28: the futures-roll exclusion variants of k1 through the full ship bar vs current LIVE. Rule = no single-commodity
FUTURES ETFs as growth satellites (roll decay: USO crude, UNG natural gas, CPER copper); physically backed GLD/SLV and the
diversified DBC stay. Also: per-window split of the UNG/USO trade P&L (is the exclusion knowable from 2020-03..2023-03 alone?).
Output: research/data/exp_1128c.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import shipbar
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

shipbar.END = '2026-11-28'
shipbar.OOS = ('2023-03-01', shipbar.END)
shipbar.WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], shipbar.END)]
r = replace
IDEAS = {
    'm1_no_UNG': ([('', r(T, sat_exclude=('UNG',))), ('', r(T, sat_exclude=('USO', 'UNG')))], 0),
    'm2_no_USO_UNG': ([('', r(T, sat_exclude=('UNG',))), ('', r(T, sat_exclude=('USO', 'UNG'))),
                       ('', r(T, sat_exclude=('USO', 'UNG', 'CPER')))], 1),
    'm3_no_futures_single': ([('', r(T, sat_exclude=('USO', 'UNG'))), ('', r(T, sat_exclude=('USO', 'UNG', 'CPER'))),
                              ('', r(T, sat_exclude=('USO', 'UNG', 'CPER', 'DBC')))], 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center, live=T)


if __name__ == '__main__':
    for u in ('static', 'full'):
        res = simulate(universe(u), T, '2020-03-01', shipbar.END, record=True)
        by = {}
        for sym, pnl, why, ed, xd, closed in res['trades']:
            if sym in ('USO', 'UNG', 'CPER'):
                k = (sym, 'IS' if str(ed) < '2023-03-01' else 'OOS')
                by.setdefault(k, []).append(round(pnl))
        print(u, 'LIVE single-commodity futures ETF trade legs by entry period:', {k: (len(v), sum(v)) for k, v in sorted(by.items())})
    with Pool(len(IDEAS)) as pool:
        for ok, line in pool.imap(run, list(IDEAS)):
            print(line, flush=True)
