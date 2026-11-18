"""2026-11-18 part 4: index core without the momentum-exit/re-entry churn (core_hold), so only the core changes.
Same bar and END as exp_1118. Output: research/data/exp_1118d.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1118
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

r = replace
H = dict(core_hold=True)
IDEAS = {
    'd1_core_qqq_hold': ([('', r(T, core_fixed=('QQQ',), **H))], 0),
    'd2_core_voo_qqq_hold': ([('', r(T, core_fixed=('VOO', 'QQQ'), **H))], 0),
    'd3_core_switch_agg_hold': ([('', r(T, core_switch=('QQQ', 'AGG', n), **H)) for n in (160, 200, 240)], 1),
    'd4_core_switch_schd_hold': ([('', r(T, core_switch=('QQQ', 'SCHD', n), **H)) for n in (160, 200, 240)], 1),
}

def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center)

if __name__ == '__main__':
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, sys.argv[1:] or list(IDEAS)):
            print(line, flush=True)
