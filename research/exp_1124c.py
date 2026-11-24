"""2026-11-24: robustness of the three most promising aggression levers from exp_1124b, through the ship-bar checks
(walk-forward, rolling windows, jackknife universes, static guardrail, +/-20% nudges) against the current live config.
The MDD tolerances in the bar are expected to bind: these ideas buy return with drawdown. Output: research/data/exp_1124c.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import shipbar
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

shipbar.END = '2026-11-20'
shipbar.OOS = ('2023-03-01', shipbar.END)
shipbar.WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], shipbar.END)]
r = replace
IDEAS = {
    'h1_core_share': ([('', r(T, core_pct=c, sat_pct=round(1 - c, 2))) for c in (0.15, 0.20, 0.25)], 1),
    'h2_two_sats_max50': ([('', r(T, max_sat=2, max_single=m)) for m in (0.40, 0.50, 0.60)], 1),
    'h3_core20_two_sats_max50': ([('', r(T, core_pct=c, sat_pct=round(1 - c, 2), max_sat=2, max_single=0.5)) for c in (0.15, 0.20, 0.25)], 1),
    'h4_core0_two_sats_max50': ([('', r(T, core_pct=0.0, sat_pct=1.0, max_sat=2, max_single=m)) for m in (0.40, 0.50, 0.60)], 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center, live=T)


if __name__ == '__main__':
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, list(IDEAS)):
            print(line, flush=True)
