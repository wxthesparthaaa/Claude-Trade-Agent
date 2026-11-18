"""2026-11-18 research run: every idea through the auto-ship bar (shipbar.evaluate), against LIVE = shipbar.LIVE_PARAMS
(trendq + sector tilt + 60-day halt restart). Data now runs to 2026-11-17, so END and W4 are extended.
Usage: python research/exp_1118.py [name ...]   (no args = all); one output line per idea."""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import shipbar
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

shipbar.END = '2026-11-18'
shipbar.OOS = ('2023-03-01', shipbar.END)
shipbar.WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], shipbar.END)]

r = replace
P3 = lambda field, vals, **kw: [('', r(T, **{field: v}, **kw)) for v in vals]   # (low, center, high), center=1
IDEAS = {
    # backlog #1: the 10/31 shortlist through the full bar against the current LIVE (60-day restart)
    'b1a_drop_tilt': (P3('sector_tilt_w', (0.02, 0.0)), 1),
    'b1b_conviction_nearest': ([('', r(T, conv_w=w, share_round='nearest')) for w in
                                ((0.36, 0.34, 0.30), (0.40, 0.35, 0.25), (0.44, 0.36, 0.20))], 1),
    'b1c_two_sats': ([('', r(T, max_sat=m)) for m in (2, 3)], 0),
    # backlog #5: gate new entries on trend quality instead of composite-score confidence
    'b5_gate_tq': (P3('gate_tq', (0.04, 0.05, 0.06)), 1),
    # backlog #7: sector tilt only on the extreme ranks (top 2 / bottom 2 of 11)
    'b7_tilt_tail': (P3('tilt_tail', (0.6, 0.8, 1.0)), 1),
    # backlog #12: gap-up skip at 5% re-tested on the new baseline
    'b12_gap_skip': (P3('gap_skip', (0.04, 0.05, 0.06)), 1),
    # NEW construction / learn-from-dividend: a plain index core instead of trend-ranked IWM/XLK
    'n1_core_voo_qqq': ([('', r(T, core_fixed=('VOO', 'QQQ')))], 0),
    'n2_core_voo': ([('', r(T, core_fixed=('VOO',)))], 0),
    'n3_core_qqq': ([('', r(T, core_fixed=('QQQ',)))], 0),
    # NEW regime: trend-switched core, QQQ above its n-day SMA else a defensive ETF
    'n4_core_switch_agg': ([('', r(T, core_switch=('QQQ', 'AGG', n))) for n in (160, 200, 240)], 1),
    'n5_core_switch_schd': ([('', r(T, core_switch=('QQQ', 'SCHD', n))) for n in (160, 200, 240)], 1),
    # NEW universe: sector ETFs as core candidates (dividend led on defensive rotation)
    'n6_core_sector_etfs': ([('+coreetf', T)], 0),
    # NEW entry timing: no new entry after a 5-day fall (MRVL bought 11/9 after a -30% month)
    'n7_knife_skip': (P3('knife_skip', (0.08, 0.10, 0.12)), 1),
    # NEW signals: slower sector-tilt rotation (63d instead of 20d), less gate noise
    'n8_tilt_slow': (P3('tilt_roc', (50, 63, 76)), 1),
    # NEW universe: liquidity floor on satellite entries (AEHR/AXTI-type small caps)
    'n9_min_dvol': (P3('min_dvol', (40e6, 50e6, 60e6)), 1),
    # NEW risk/selection: after a stop-out, block that GICS group for N days (11/6: MU stop, AMD/ASX near it)
    'n10_grp_cooldown': (P3('grp_cooldown', (8, 10, 12)), 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center)


if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, names):
            print(line, flush=True)
