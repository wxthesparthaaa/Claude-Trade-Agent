"""2026-11-27 inchworm follow-up. Part A: trip-level counterfactual "skip the worst tercile of each entry feature" (no slot
replacement, so it is an UPPER bound on what an entry filter could add). Part B: the "obsess about A+" half -- weight the top-ranked
satellite more (rank-1 gets w1, rank-2 gets 1-w1); rank-reversed as a control (if rank carried information, 40/60 should lose).
Each config runs on static + full, from $4k/$5k/$6k and four start dates. Output: research/data/exp_1127.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import numpy as np
import pandas as pd
import shipbar
from shipbar import LIVE_PARAMS as T
from harness import *

END = '2026-11-20'
STARTS = ['2020-03-01', '2021-01-04', '2022-01-03', '2023-01-03']
r = replace
CFG = {
    'LIVE (50/50)': T,
    'conv 60/40': r(T, conv_w=(0.6, 0.4), max_single=0.6),
    'conv 70/30': r(T, conv_w=(0.7, 0.3), max_single=0.7),
    'conv 80/20': r(T, conv_w=(0.8, 0.2), max_single=0.8),
    'CONTROL reversed 40/60': r(T, conv_w=(0.4, 0.6), max_single=0.6),
    '1 satellite x 100%': r(T, max_sat=1, max_single=1.0),
    '3 sats 50/30/20': r(T, max_sat=3, conv_w=(0.5, 0.3, 0.2)),
}


def one(name):
    p = CFG[name]
    res = {}
    for uname in ('static', 'full'):
        u = universe(uname)
        res[uname] = {'caps': [simulate(u, r(p, capital=c), STARTS[0], END) for c in (4000.0, 5000.0, 6000.0)],
                      'starts': [simulate(u, p, s, END) for s in STARTS]}
    return name, res


def part_a(out):
    out.append('=== Part A: trip-level "skip the worst tercile" counterfactual (sum of log trip returns; no slot replacement) ===')
    feats = [('vol63', 'high vol', 'high'), ('adr', 'high ADR', 'high'), ('ext20', 'extended above 20d', 'high'),
             ('r2', 'low R2 (jagged)', 'low'), ('tq', 'low trend quality', 'low'), ('off_hi', 'far below 52w high', 'low'),
             ('mom21', 'weak 21d', 'low'), ('gap', 'gap-up', 'high'), ('above200', 'stretched over 200d', 'high')]
    for uname in ('static', 'full'):
        df = pd.read_csv(f'research/data/inchworm_trips_{uname}.csv')
        base = np.log1p(df['ret']).sum()
        out.append(f'\n[{uname}] {len(df)} trips, total log {base:.2f}')
        out.append(f"{'drop worst tercile by':32s} {'dropped':>8s} {'their log sum':>14s} {'their stops':>12s} {'their A+':>9s} {'result':>8s}")
        for col, label, side in feats:
            rk = df[col].rank(method='first')
            cut = rk > rk.quantile(2 / 3) if side == 'high' else rk <= rk.quantile(1 / 3)
            d = df[cut]
            out.append(f"{label:32s} {len(d):8d} {np.log1p(d['ret']).sum():+14.2f} {int((d['ret'] <= -0.20).sum()):12d} {int((d['ret'] > 0.60).sum()):9d} {base - np.log1p(d['ret']).sum():8.2f}")
        for col, label in [('qqq_on', 'QQQ below 200d at entry')]:
            d = df[df[col] == False]
            out.append(f"{label:32s} {len(d):8d} {np.log1p(d['ret']).sum():+14.2f} {int((d['ret'] <= -0.20).sum()):12d} {int((d['ret'] > 0.60).sum()):9d} {base - np.log1p(d['ret']).sum():8.2f}")


if __name__ == '__main__':
    out = []
    part_a(out)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        res = pool.map(one, list(CFG))
    for uname in ('static', 'full'):
        out.append(f'\n=== Part B [{uname}] to {END} ===')
        out.append(f"{'config':26s} | {'$5k return':>10} {'MDD':>5} | {'$4k/$5k/$6k':>22} | {'starts 2020/21/22/23':>32} | {'min':>6}")
        for name, rs in res:
            c, s = rs[uname]['caps'], rs[uname]['starts']
            allr = [x['ret'] * 100 for x in c + s]
            out.append(f"{name:26s} | {c[1]['ret']*100:9.0f}% {c[1]['mdd']*100:5.1f} | {' '.join(f'{x['ret']*100:6.0f}' for x in c):>22} | {' '.join(f'{x['ret']*100:7.0f}' for x in s):>32} | {min(allr):6.0f}")
    text = '\n'.join(out)
    open('research/data/exp_1127.txt', 'w', encoding='utf-8').write(text)
    print(text)
