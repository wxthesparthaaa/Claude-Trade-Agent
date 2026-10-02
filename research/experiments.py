"""Variant sweep: full period + 4 rolling windows, static (less biased) and full universes.
Usage: python research/experiments.py [group]"""
import sys, json; sys.path.insert(0, 'research')
from harness import *
import pandas as pd

import os
B = Params(dd_halt=None) if os.environ.get('NOHALT') else Params()
VARIANTS = {
 'base': [('LIVE', B)],
 'bench': [],
 'H1band': [(f'band{b}', replace(B, band=b)) for b in (0.0, 0.1, 0.2, 0.3, 0.5)],
 'H2stop': [(f'stop{s}', replace(B, stop=s)) for s in (None, 0.10, 0.15, 0.20, 0.25, 0.30)],
 'H4cool': [(f'cool{c}', replace(B, cooldown=c)) for c in (0, 5, 10, 20)],
 'H6mom': [(f'lb{l}/sk{k}', replace(B, lookback=l, skip=k)) for l, k in ((126, 21), (126, 5), (63, 5), (189, 21), (252, 21), (126, 0))],
 'H8sat': [(f'sat{n}', replace(B, max_sat=n)) for n in (1, 2, 3, 4, 5)],
 'H9minord': [(f'min{m}', replace(B, min_order=m)) for m in (0, 100, 200, 400)],
 'H10atr': [(f'atr{m}', replace(B, atr_mult=m)) for m in (2.0, 3.0, 4.0, 5.0)] + [(f'trail{x}', replace(B, trail=x)) for x in (0.15, 0.2, 0.25)],
 'H11conf': [(f'conf{c}', replace(B, conf_thresh=c)) for c in (50, 60, 70, 80, 90)],
 'H7regime': [('spy200', replace(B, regime_gate='spy200'))],
 'cadence': [(f'cad{c}', replace(B, cadence=c)) for c in (1, 2, 5, 10, 21)] + [(f'cad{c}x', replace(B, cadence=c, exits_on_cadence=True)) for c in (5, 10)],
 'momexit': [(f'mx{m}', replace(B, mom_exit=m)) for m in (None, -0.10, -0.05, 0.0)],
 'buffer': [(f'buf{b}', replace(B, hold_rank_buffer=b)) for b in (0, 1, 2, 3)],
 'halt': [('halt25', B), ('nohalt', replace(B, dd_halt=None))],
}

def row(name, uni, p):
    full = simulate(uni, p, '2020-03-01', '2026-10-03')
    ws = windows(uni, p)
    return dict(name=name, ret=full['ret'], mdd=full['mdd'], orders=full['orders'], comm=full['comm'], win=full['win'],
                payoff=full['payoff'], stops=full['stopouts'], re10=full['reentry10'], halt=full['halted_days'],
                **{f'w{k+1}': w['ret'] for k, w in enumerate(ws)}, **{f'dd{k+1}': w['mdd'] for k, w in enumerate(ws)})

def show(rows):
    df = pd.DataFrame(rows).set_index('name')
    pct = ['ret', 'mdd', 'win', 'w1', 'w2', 'w3', 'w4', 'dd1', 'dd2', 'dd3', 'dd4']
    for c in pct: df[c] = (df[c] * 100).round(1)
    df['comm'] = df['comm'].round(0); df['payoff'] = df['payoff'].round(2)
    print(df.to_string())

if __name__ == '__main__':
    groups = sys.argv[1:] or list(VARIANTS)
    for g in groups:
        for un in ('static', 'full'):
            print(f'\n### {g} / {un}')
            show([row(n, universe(un), p) for n, p in VARIANTS[g]])
