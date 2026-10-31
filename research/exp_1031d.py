"""2026-10-31 run, part 4: how much of the full-period result is halt-path luck?
Paired sweep: starting capital 4000..6000 (step 100), same rules otherwise, halt on, full universe. A config 'freezes'
when it ends the period under +400% (the 25% halt never releases). Also the auto-ship bar on the top-heavy centre the walk-forward picked.
Output: research/data/exp_1031d.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import LIVE_PARAMS as T, START, END, evaluate
from harness import *

r = replace
N = dict(share_round='nearest')
CFG = {'LIVE': T, 'LIVE+nearest': r(T, **N)}
for w in ((0.36, 0.34, 0.30), (0.385, 0.35, 0.265), (0.40, 0.35, 0.25), (0.415, 0.35, 0.235), (0.42, 0.36, 0.22), (0.44, 0.36, 0.20),
          (0.46, 0.36, 0.18), (0.48, 0.32, 0.20)):
    CFG[f'near+{w}'] = r(T, conv_w=w, **N)
    CFG[f'floor+{w}'] = r(T, conv_w=w)
CAPS = [4000.0 + 100 * i for i in range(21)]
TOP = [(0.42, 0.36, 0.22), (0.44, 0.36, 0.20), (0.46, 0.36, 0.18)]


def one(a):
    n, c, un = a
    x = simulate(universe(un), r(CFG[n], capital=c), START, END)
    return n, c, un, x['ret'], x['mdd'], x['halted_days']


def bar(_):
    return evaluate('top-heavy .44/.36/.20', [('', r(T, conv_w=w, **N)) for w in TOP], 1)[1]


if __name__ == '__main__':
    with Pool(15) as pool:
        print(pool.map(bar, [0])[0], flush=True)
        res = pool.map(one, [(n, c, un) for n in CFG for c in CAPS for un in ('full', 'static')], chunksize=4)
    D = {(n, c, un): (ret, mdd, h) for n, c, un, ret, mdd, h in res}
    for un in ('full', 'static'):
        print(f'--- {un}, capital sweep 4000..6000, halt on')
        for n in CFG:
            v = [D[(n, c, un)] for c in CAPS]
            rets = sorted(x[0] * 100 for x in v)
            wins = sum(D[(n, c, un)][0] > D[('LIVE', c, un)][0] for c in CAPS)
            frz = sum(x[0] < 4.0 for x in v) if un == 'full' else sum(x[2] > 300 for x in v)
            print(f"{n:32s} median {rets[10]:7.1f} min {rets[0]:7.1f} max {rets[-1]:7.1f} | median MDD {sorted(x[1]*100 for x in v)[10]:4.1f} | frozen {frz:2d}/21 | beats LIVE {wins:2d}/21", flush=True)
