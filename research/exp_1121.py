"""2026-11-21 research run: 8 new ideas through the auto-ship bar (shipbar.evaluate) against LIVE = shipbar.LIVE_PARAMS
(trendq + sector tilt + 60-day halt restart). Data to 2026-11-20 (a -8.6% SPY week), so END and W4 are extended.
Usage: python research/exp_1121.py [name ...]   (no args = all). Output: research/data/exp_1121.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import shipbar
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

shipbar.END = '2026-11-21'
shipbar.OOS = ('2023-03-01', shipbar.END)
shipbar.WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], shipbar.END)]

r = replace
H = dict(core_hold=True)
P3 = lambda field, vals, **kw: [('', r(T, **{field: v}, **kw)) for v in vals]
IDEAS = {
    # backlog #1: index core with a FASTER risk-off (d4 used 200d and failed W2 MDD by 3.2 pts)
    'e1_core_switch_schd_100': ([('', r(T, core_switch=('QQQ', 'SCHD', n), **H)) for n in (80, 100, 120)], 1),
    'e2_core_dualmom_agg_schd': ([('', r(T, core_dualmom=('QQQ', 'AGG', 'SCHD', n), **H)) for n in (101, 126, 151)], 1),
    'e3_core_switch_cash_200': ([('', r(T, core_switch=('QQQ', 'CASH', n), **H)) for n in (160, 200, 240)], 1),
    'e3b_core_switch_cash_100': ([('', r(T, core_switch=('QQQ', 'CASH', n), **H)) for n in (80, 100, 120)], 1),
    # backlog #19 learn-from-dividend: fixed 50/50 QQQ + SCHD core, held
    'e4_core_qqq_schd_fixed': ([('', r(T, core_fixed=('QQQ', 'SCHD'), **H))], 0),
    # backlog #18: at most 1 semi among satellites while semis trail SPY over 20d (11/6 and 11/20 stops were semis)
    'e5_semi_cap_regime': ([('', r(T, semi_cap=c)) for c in (0, 1, 2)], 1),
    # NEW selection: no NEW satellite with 63d vol above x (ASX/MU/AEHR stops were the high-vol names)
    'e6_sat_max_vol': (P3('sat_max_vol', (0.56, 0.70, 0.84)), 1),
    # NEW signals: satellites must beat QQQ's 126/21 momentum (relative strength vs the index they replace)
    'e7_sat_rs_qqq': (P3('sat_rs', (0.04, 0.05, 0.06)), 1),
    # NEW construction: d4 with a bigger core share (dividend-like breadth), 50/50
    'e8_d4_core50': ([('', r(T, core_switch=('QQQ', 'SCHD', 200), core_pct=c, sat_pct=round(1 - c, 2), **H))
                      for c in (0.40, 0.50, 0.60)], 1),
    # batch 2: try to rescue e3 / d4 on the 2022 window with hysteresis on the 200d switch (whipsaw was the W2 cost)
    'f1_cash200_band': ([('', r(T, core_switch=('QQQ', 'CASH', 200), csw_band=b, **H)) for b in (0.016, 0.02, 0.024)], 1),
    'f2_schd200_band': ([('', r(T, core_switch=('QQQ', 'SCHD', 200), csw_band=b, **H)) for b in (0.016, 0.02, 0.024)], 1),
    'f3_cash200_band4': ([('', r(T, core_switch=('QQQ', 'CASH', 200), csw_band=b, **H)) for b in (0.032, 0.04, 0.048)], 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center)


if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, names):
            print(line, flush=True)
