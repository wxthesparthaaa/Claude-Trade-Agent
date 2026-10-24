"""2026-10-24 run 2: trend-quality window sensitivity, halt on/off, full/static (is the 151d nudge failure a halt artefact?)."""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import START, END
from harness import *

CASES = [(un, h, w) for un in ('full', 'static') for h in (0.25, None) for w in (0, 101, 113, 126, 139, 151)]


def run(c):
    un, h, w = c
    p = Params(dd_halt=h) if w == 0 else Params(dd_halt=h, score_mode='trendq', trend_win=w)
    r = simulate(universe(un), p, START, END)
    return c, r


if __name__ == '__main__':
    with Pool(16) as pool:
        for (un, h, w), r in pool.imap(run, CASES):
            print(f"{un:6s} halt={h} {'LIVE' if w == 0 else f'tq{w}':6s} ret {r['ret']*100:7.1f}% mdd {r['mdd']*100:4.1f} orders {r['orders']} halted {r['halted_days']}d", flush=True)
