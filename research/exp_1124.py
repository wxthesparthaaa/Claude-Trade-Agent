"""2026-11-24: the "scan -> trend stack -> relative strength" checklist (liquid growth names, ADR > 4%, EMA9 > EMA21 > SMA50 > SMA200,
stock out-structures QQQ) through the auto-ship bar against the CURRENT live config (shipbar.LIVE_PARAMS incl. the 11/21 index core).
Usage: python research/exp_1124.py [name ...]   Output: research/data/exp_1124.txt"""
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
P3 = lambda field, vals, **kw: [('', r(T, **{field: v}, **kw)) for v in vals]
IDEAS = {
    'g1_stack_full': ([('', r(T, ma_stack='full'))], 0),                      # step 2 as stated: price > EMA9 > EMA21 > SMA50 > SMA200
    'g2_stack_half': ([('', r(T, ma_stack='half'))], 0),                      # without the EMA9 leg
    'g3_above_200': ([('', r(T, ma_stack='200'))], 0),                        # "the deal breaker": only the 200d leg
    'g4_adr_min': (P3('adr_min', (0.03, 0.04, 0.05)), 1),                     # step 1: average daily range >= 3/4/5%
    'g5_dvol_1b': (P3('min_dvol', (3e8, 1e9, 2e9)), 1),                       # step 1: 20d average dollar volume >= $0.3/1/2 billion
    'g6_full_adr4_dvol1b': ([('', r(T, ma_stack='full', adr_min=0.04, min_dvol=1e9))], 0),   # the whole checklist, steps 1+2
    'g7_stack_exit_200': ([('', r(T, stack_exit='200'))], 0),                 # "below the 200d: take it off your charts" as an exit
    'g8_stack_exit_2150': ([('', r(T, stack_exit='2150'))], 0),
    'g9_sat_rs_qqq': (P3('sat_rs', (0.02, 0.05, 0.10)), 1),                   # step 3 proxy: 126/21 momentum beats QQQ's (also tested 11/21 e7)
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center, live=T)


if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, names):
            print(line, flush=True)
