"""2026-11-18 batch 2: the index-core idea with the live gate kept (batch 1 waived it: 2022 W2 MDD +9..12 and a
momentum-exit/re-entry churn), plus attempts to rescue the batch-1 near-misses. Same bar and END as exp_1118."""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1118  # sets shipbar.END / OOS / WINS
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

r = replace
G = dict(core_fixed_gate=True)
IDEAS = {
    'c1_core_qqq_gated': ([('', r(T, core_fixed=('QQQ',), **G))], 0),
    'c2_core_voo_qqq_gated': ([('', r(T, core_fixed=('VOO', 'QQQ'), **G))], 0),
    'c3_core_voo_gated': ([('', r(T, core_fixed=('VOO',), **G))], 0),
    # QQQ above its n-day SMA else AGG, gate kept
    'c5_core_switch_agg_gated': ([('', r(T, core_switch=('QQQ', 'AGG', n), **G)) for n in (160, 200, 240)], 1),
    # QQQ core, gate waived, but the momentum exit loosened to stop the exit/re-entry churn
    'c6_core_qqq_momexit10': ([('', r(T, core_fixed=('QQQ',), mom_exit=m)) for m in (-0.08, -0.10, -0.12)], 1),
    'c7_tilt_slow_wide': ([('', r(T, tilt_roc=v)) for v in (42, 52, 63, 76, 90)], 2),
}

def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center)

if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, names):
            print(line, flush=True)
