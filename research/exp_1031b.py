"""2026-10-31 run, part 2: try to break the leaders. Each candidate vs LIVE (trendq + sector tilt) on full/static x halt
on/off: full-period return/MDD, windows won, 12 staggered starts won, jackknife wins and median dRet.
The first batch showed full-period results flip by 1000+ points on halt path alone, so the medians are the honest read.
Usage: python research/exp_1031b.py   -> research/data/exp_1031b.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1010 as X
from shipbar import LIVE_PARAMS as T, START, END, WINS
from harness import *

r = replace
CONV = (0.40, 0.35, 0.25)
CANDS = {
    'drop_tilt': r(T, sector_tilt_w=0.0),
    'round_nearest': r(T, share_round='nearest'),
    'conviction': r(T, conv_w=CONV),
    'two_sats': r(T, max_sat=2),
    'group_cap2': r(T, group_cap=2),
    'core_floor0': r(T, min_rank_core=0.0),
    'chase_skip10': r(T, chase_skip=0.10),
    'drop_tilt+nearest': r(T, sector_tilt_w=0.0, share_round='nearest'),
    'drop_tilt+conviction': r(T, sector_tilt_w=0.0, conv_w=CONV),
    'nearest+conviction': r(T, share_round='nearest', conv_w=CONV),
    'drop_tilt+nearest+conv': r(T, sector_tilt_w=0.0, share_round='nearest', conv_w=CONV),
}
STARTS = X.STARTS


def job(a):
    name, un, halt = a
    h = {} if halt else {'dd_halt': None}
    cand, base = r(CANDS[name], **h), r(T, **h)
    U = universe(un)
    fc, fb = simulate(U, cand, START, END), simulate(U, base, START, END)
    wr = [(simulate(U, cand, x, y), simulate(U, base, x, y)) for x, y in WINS]
    win = sum(c['ret'] > b['ret'] for c, b in wr)
    dmdd = max((c['mdd'] - b['mdd']) * 100 for c, b in wr)
    st = [simulate(U, cand, s, END)['ret'] - simulate(U, base, s, END)['ret'] for s in STARTS]
    js = [simulate(u, cand, START, END)['ret'] - simulate(u, base, START, END)['ret'] for u in X.jack_unis(un)]
    med = lambda v: sorted(v)[len(v) // 2] * 100
    return (f"{name:24s} {un:6s} halt={'on ' if halt else 'off'} full {fc['ret']*100:7.1f} vs {fb['ret']*100:7.1f} mdd {fc['mdd']*100:4.1f} vs {fb['mdd']*100:4.1f} "
            f"ord {fc['orders']:4d} vs {fb['orders']:4d} haltd {fc['halted_days']:4d} vs {fb['halted_days']:4d} | win {win}/4 dMDDmax {dmdd:5.1f} | "
            f"starts {sum(d > 0 for d in st):2d}/12 med {med(st):7.1f} | jack {sum(d > 0 for d in js):2d}/20 med {med(js):7.1f}")


if __name__ == '__main__':
    jobs = [(n, un, h) for n in CANDS for un in ('full', 'static') for h in (True, False)]
    with Pool(15) as pool:
        for line in pool.imap(job, jobs):
            print(line, flush=True)
