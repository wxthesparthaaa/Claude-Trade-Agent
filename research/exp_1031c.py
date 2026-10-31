"""2026-10-31 run, part 3: full auto-ship bar + attempts to break 'conviction + nearest-share rounding'.
Output: research/data/exp_1031c.txt"""
import os, sys, random, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1010 as X
from shipbar import LIVE_PARAMS as T, START, END, WINS, evaluate
from harness import *

r = replace
C = (0.40, 0.35, 0.25)
N = dict(share_round='nearest')
BAR = {
    'wide nudges': ([('', r(T, conv_w=w, **N)) for w in ((0.36, 0.34, 0.30), C, (0.44, 0.36, 0.20))], 1),
    'spread +/-20%': ([('', r(T, conv_w=w, **N)) for w in ((0.385, 0.35, 0.265), C, (0.415, 0.35, 0.235))], 1),
    'top wt +/-20%': ([('', r(T, conv_w=w, **N)) for w in ((0.32, 0.38, 0.30), C, (0.48, 0.32, 0.20))], 1),
}


def bar(n):
    g, c = BAR[n]
    return evaluate(n, g, c)[1]


def jack(a):
    un, seed, k, label, cand, base = a
    d = []
    for u in X.jack_unis(un, seed=seed):
        d.append(simulate(u, cand, START, END)['ret'] - simulate(u, base, START, END)['ret'])
    return f"{label} {un} seed {seed}: {sum(x > 0 for x in d)}/20 med {sorted(d)[10]*100:.1f}"


def stress(a):
    label, kw_c, kw_b, un = a
    U = universe(un)
    cand, base = r(T, conv_w=C, **N, **kw_c), r(T, **kw_b)
    fc, fb = simulate(U, cand, START, END), simulate(U, base, START, END)
    wr = [(simulate(U, cand, x, y), simulate(U, base, x, y)) for x, y in WINS]
    return (f"{label:18s} {un:6s} full {fc['ret']*100:7.1f} vs {fb['ret']*100:7.1f} mdd {fc['mdd']*100:4.1f} vs {fb['mdd']*100:4.1f} ord {fc['orders']} vs {fb['orders']} "
            f"haltd {fc['halted_days']} vs {fb['halted_days']} | win {sum(c['ret'] > b['ret'] for c, b in wr)}/4 d {[round(float(c['ret']-b['ret'])*100,1) for c, b in wr]}")


if __name__ == '__main__':
    cand, base = r(T, conv_w=C, **N), T
    with Pool(15) as pool:
        for l in pool.imap(bar, list(BAR)):
            print(l, flush=True)
        for l in pool.imap(jack, [(un, s, 0, 'jack', cand, base) for un in ('full', 'static') for s in (7, 11, 23, 42, 99)]):
            print(l, flush=True)
        S = [('capital 3000', dict(capital=3000.0), dict(capital=3000.0)), ('capital 4600', dict(capital=4600.0), dict(capital=4600.0)),
             ('capital 7500', dict(capital=7500.0), dict(capital=7500.0)), ('capital 15000', dict(capital=15000.0), dict(capital=15000.0)),
             ('commission 5', dict(commission=5.0), dict(commission=5.0)), ('commission 2.5', dict(commission=2.5), dict(commission=2.5)),
             ('stop 15', dict(stop=0.15), dict(stop=0.15)), ('band 0.3', dict(band=0.3), dict(band=0.3)),
             ('momentum rank', dict(score_mode='mom'), dict(score_mode='mom')), ('no regime tilt', {}, {})]
        for l in pool.imap(stress, [(a, b, c, un) for a, b, c in S for un in ('full', 'static')]):
            print(l, flush=True)
