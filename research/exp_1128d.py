"""2026-11-28: four more ideas re-tested under big-bet mode (2 slots changes how churn and ranking noise bite).
Output: research/data/exp_1128d.txt"""
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
    'n1_drop_sector_tilt': ([('', r(T, sector_tilt_w=0.0)), ('', r(T, sector_tilt_w=0.05))], 0),
    'n2_rank_buffer_1': ([('', r(T, hold_rank_buffer=1))], 0),
    'n3_swap_margin': ([('', r(T, swap_margin=x)) for x in (0.04, 0.05, 0.06)], 1),
    'n4_stop_15': ([('', r(T, stop=x)) for x in (0.12, 0.15, 0.18)], 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center, live=T)


if __name__ == '__main__':
    with Pool(len(IDEAS)) as pool:
        for ok, line in pool.imap(run, list(IDEAS)):
            print(line, flush=True)
