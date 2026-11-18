"""2026-11-18 part 3: try to break the near-misses. Paired capital sweep ($4,000-$6,000, step 100, halt on) on full and
static, and the jackknife under 4 more seeds. Data to 2026-11-17. Output: research/data/exp_1118c.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1118  # sets shipbar.END
import shipbar
from shipbar import LIVE_PARAMS as T, START, jack_pairs
from harness import *

END = shipbar.END
r = replace
CFG = {'LIVE': T, 'drop_tilt': r(T, sector_tilt_w=0.0), 'tilt_roc63': r(T, tilt_roc=63),
       'tilt_roc50': r(T, tilt_roc=50), 'conv_nearest': r(T, conv_w=(0.40, 0.35, 0.25), share_round='nearest'),
       'core_qqq_mx10': r(T, core_fixed=('QQQ',), mom_exit=-0.10), 'two_sats': r(T, max_sat=2)}
CAPS = [4000.0 + 100 * i for i in range(21)]


def one(a):
    n, c, un = a
    x = simulate(universe(un), r(CFG[n], capital=c), START, END)
    return n, c, un, x['ret'], x['mdd'], x['halted_days']


def jk(a):
    n, seed = a
    w = 0
    for b, c in jack_pairs('', seed=seed):
        w += simulate(c, CFG[n], START, END)['ret'] > simulate(b, T, START, END)['ret']
    return n, seed, w


if __name__ == '__main__':
    with Pool(15) as pool:
        res = pool.map(one, [(n, c, un) for n in CFG for c in CAPS for un in ('full', 'static')], chunksize=4)
        jr = pool.map(jk, [(n, s) for n in CFG if n != 'LIVE' for s in (11, 23, 42, 99)])
    D = {(n, c, un): (ret, mdd, h) for n, c, un, ret, mdd, h in res}
    for un in ('full', 'static'):
        print(f'--- {un}, capital sweep 4000..6000, halt on, to {END}')
        for n in CFG:
            v = [D[(n, c, un)] for c in CAPS]
            rets = sorted(x[0] * 100 for x in v)
            wins = sum(D[(n, c, un)][0] > D[('LIVE', c, un)][0] for c in CAPS)
            frz = sum(x[2] > 300 for x in v)
            print(f"{n:16s} median {rets[10]:7.1f} min {rets[0]:7.1f} max {rets[-1]:7.1f} | median MDD {sorted(x[1]*100 for x in v)[10]:4.1f} | halted>300d {frz:2d}/21 | beats LIVE {wins:2d}/21", flush=True)
    print('--- jackknife wins /20 by seed (11, 23, 42, 99)')
    for n in CFG:
        if n != 'LIVE':
            print(f"{n:16s}", [w for m, s, w in jr if m == n])
