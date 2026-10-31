"""2026-10-31: break-test the leading halt option (freeze, restart after 60 days): +/-20% nudges, and when the halts happen.
Output: research/data/exp_1031g.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import LIVE_PARAMS as T, START, END
from harness import *

r = replace
CAPS = [4000.0 + 100 * i for i in range(21)]
NS = (None, 48, 60, 72)


def one(a):
    n, un, c = a
    x = simulate(universe(un), r(T, halt_reset=n, capital=c), START, END)
    return (n, un, c), (x['ret'] * 100, x['mdd'] * 100, x['halted_days'])


def episodes(curve, th=0.25):
    """Spells at >=25% below the running peak, on closes, against the all-time peak."""
    dd = 1 - curve / curve.cummax()
    on = dd >= th
    out, start = [], None
    for d, v in on.items():
        if v and start is None:
            start = d
        if not v and start is not None:
            out.append(f"{start.date()}..{d.date()}")
            start = None
    if start is not None:
        out.append(f"{start.date()}..open")
    return out


if __name__ == '__main__':
    with Pool(15) as pool:
        S = dict(pool.map(one, [(n, un, c) for n in NS for un in ('full', 'static') for c in CAPS], chunksize=4))
    for un in ('full', 'static'):
        for n in NS:
            v = [S[(n, un, c)] for c in CAPS]
            print(f"{un:6s} restart {str(n):4s} ret med {sorted(x[0] for x in v)[10]:7.1f} min {min(x[0] for x in v):7.1f} max {max(x[0] for x in v):7.1f} | "
                  f"MDD med {sorted(x[1] for x in v)[10]:4.1f} max {max(x[1] for x in v):4.1f} | halted>300d {sum(x[2] > 300 for x in v):2d}/21", flush=True)
        for n in (None, 60):
            c = simulate(universe(un), r(T, halt_reset=n), START, END, record=True)
            print(f"  $5,000 restart {n}: >=25% below peak on closes: {episodes(c['curve'])}; halted {c['halted_days']}d; ret {c['ret']*100:.1f}", flush=True)
