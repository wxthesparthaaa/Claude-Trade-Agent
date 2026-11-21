"""2026-11-21 part 2: try to break f1 (core = QQQ held while QQQ > its 200d SMA with 2% hysteresis, else cash).
(a) ship bar with the SMA LENGTH as the nudged key parameter (160/200/240, band 0.02), both baselines;
(b) paired capital sweep $4,000-$6,000 (21 starts) on full and static, both baselines;
(c) jackknife under 4 more seeds; (d) static-universe rolling windows. Output: research/data/exp_1121b.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1121  # sets shipbar.END / OOS / WINS
import shipbar
from shipbar import LIVE_PARAMS as NEW, START, jack_pairs, evaluate
from harness import *

END = shipbar.END
r = replace
OLD = r(NEW, halt_mode='all')
F1 = lambda base, n=200, b=0.02: r(base, core_switch=('QQQ', 'CASH', n), csw_band=b, core_hold=True)
CAPS = [4000.0 + 100 * i for i in range(21)]


def bar(a):
    tag, base = a
    grid = [('', F1(base, n)) for n in (160, 200, 240)]
    return evaluate(f'f1_smalen_{tag}', grid, 1, live=base)[1]


def one(a):
    tag, which, c, un = a
    base = NEW if tag == 'new' else OLD
    p = F1(base) if which == 'f1' else base
    x = simulate(universe(un), r(p, capital=c), START, END)
    return tag, which, c, un, x['ret'], x['mdd'], x['halted_days']


def jk(a):
    tag, seed = a
    base = NEW if tag == 'new' else OLD
    return tag, seed, sum(simulate(c, F1(base), START, END)['ret'] > simulate(b, base, START, END)['ret']
                          for b, c in jack_pairs('', seed=seed))


def sw(a):
    tag, w = a
    base = NEW if tag == 'new' else OLD
    S = universe('static')
    x, y = simulate(S, F1(base), *w), simulate(S, base, *w)
    return tag, w, x['ret'], y['ret'], x['mdd'], y['mdd']


if __name__ == '__main__':
    with Pool(15) as pool:
        bars = pool.map(bar, [('new', NEW), ('old', OLD)])
        res = pool.map(one, [(t, w, c, un) for t in ('new', 'old') for w in ('f1', 'live') for c in CAPS for un in ('full', 'static')], chunksize=4)
        jr = pool.map(jk, [(t, s) for t in ('new', 'old') for s in (11, 23, 42, 99)])
        swr = pool.map(sw, [(t, w) for t in ('new', 'old') for w in shipbar.WINS])
    for l in bars:
        print(l.replace('np.float64(', '').replace(')', ''))
    D = {(t, w, c, un): (ret, mdd, h) for t, w, c, un, ret, mdd, h in res}
    for t in ('new', 'old'):
        for un in ('full', 'static'):
            f = sorted(D[(t, 'f1', c, un)][0] * 100 for c in CAPS); l = sorted(D[(t, 'live', c, un)][0] * 100 for c in CAPS)
            fm = sorted(D[(t, 'f1', c, un)][1] * 100 for c in CAPS); lm = sorted(D[(t, 'live', c, un)][1] * 100 for c in CAPS)
            wins = sum(D[(t, 'f1', c, un)][0] > D[(t, 'live', c, un)][0] for c in CAPS)
            print(f"sweep base={t} {un:6s} f1 median {f[10]:7.1f} min {f[0]:7.1f} | LIVE median {l[10]:7.1f} min {l[0]:7.1f} | "
                  f"median MDD {fm[10]:.1f} vs {lm[10]:.1f} | f1 beats LIVE {wins}/21", flush=True)
    for t in ('new', 'old'):
        print(f'jackknife base={t} seeds 11/23/42/99:', [w for tt, s, w in jr if tt == t])
    for t, w, a, b, ma, mb in swr:
        print(f'static window base={t} {w}: f1 {a*100:.1f}% vs {b*100:.1f}% mdd {ma*100:.1f} vs {mb*100:.1f}')
