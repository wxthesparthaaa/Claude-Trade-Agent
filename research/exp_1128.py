"""2026-11-28 weekly run: 10 ideas through the ship bar against the CURRENT live config (big-bet: no core, 2 satellites
at 50%, no momentum exit, no drawdown halt). New harness features (off by default): sat_exclude, no_add_below,
riskoff_confirm, near_high, stage. Output: research/data/exp_1128.txt"""
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
COMMOD = ('CPER', 'DBC', 'GLD', 'SLV', 'UNG', 'USO')
IDEAS = {
    'k1_no_commodity_sats': ([('', r(T, sat_exclude=('USO', 'UNG', 'DBC'))), ('', r(T, sat_exclude=COMMOD))], 1),
    'k2_no_add_to_losers': ([('', r(T, no_add_below=x)) for x in (0.08, 0.10, 0.12)], 1),
    'k3_riskoff_21d_confirm': ([('', r(T, riskoff_confirm=n)) for n in (17, 21, 25)], 1),
    'k4_group_cap_1': ([('', r(T, group_cap=1))], 0),
    'k5_corr_cap': ([('', r(T, corr_cap=x)) for x in (0.56, 0.70, 0.84)], 1),
    'k6_half_sats_below_spy200': ([('', r(T, sat_off='spy200', sat_off_scale=x, sat_off_to='cash')) for x in (0.4, 0.5, 0.6)], 1),
    'k7_trendq_189d': ([('', r(T, trend_win=w)) for w in (151, 189, 227)], 1),
    'k8_near_63d_high': ([('', r(T, near_high=x)) for x in (0.12, 0.15, 0.18)], 1),
    'k9_staged_entry': ([('', r(T, stage=(0.5, d))) for d in (4, 5, 6)], 1),
    'k10_three_sats': ([('', r(T, max_sat=3))], 0),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center, live=T)


if __name__ == '__main__':
    F, S = universe('full'), universe('static')
    print('LIVE full', fmt(simulate(F, T, shipbar.START, shipbar.END)))
    print('LIVE static', fmt(simulate(S, T, shipbar.START, shipbar.END)), flush=True)
    with Pool(min(len(IDEAS), max(os.cpu_count() - 1, 1))) as pool:
        for ok, line in pool.imap(run, list(IDEAS)):
            print(line, flush=True)
