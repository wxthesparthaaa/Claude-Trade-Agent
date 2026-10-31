"""2026-10-31 research run: every idea through the auto-ship bar (shipbar.evaluate), against LIVE = trendq.
Usage: python research/exp_1031.py [name ...]   (no args = all); output lines go to stdout, one per idea."""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import LIVE_PARAMS as T, evaluate
from harness import *

r = replace
P3 = lambda field, vals, **kw: [('', r(T, **{field: v}, **kw)) for v in vals]   # (low, center, high), center=1
IDEAS = {
    # backlog queue
    'b1_sat_tq_core_mom': (P3('trend_win', (101, 126, 151), core_score_mode='mom'), 1),
    'b2_groupcap': (P3('group_cap', (1, 2, 3)), 1),
    'b3_buffer': (P3('hold_rank_buffer', (1, 2)), 0),
    'b4_momr2_broad': ([('+broad', r(T, score_mode='mom_r2', trend_win=w)) for w in (101, 126, 151)], 1),
    'b9_min_bars': (P3('min_bars', (403, 504, 605)), 1),
    'b11_core_defensive': ([('', r(T, core_defensive=True))], 0),
    'b12_two_sats': ([('', r(T, max_sat=2))], 0),
    # construction: small-account whole-share cash drag (AMD this week: target 21%, 1 share = 11%; 15% cash idle)
    'n1_round_nearest': ([('', r(T, share_round='nearest'))], 0),
    'n2_cash_sweep': (P3('cash_sweep', (0.04, 0.05, 0.06)), 1),
    'n3_nearest+sweep': (P3('cash_sweep', (0.04, 0.05, 0.06), share_round='nearest'), 1),
    'n4_conviction': ([('', r(T, conv_w=w)) for w in ((0.36, 0.34, 0.30), (0.40, 0.35, 0.25), (0.44, 0.36, 0.20))], 1),
    # absolute trend floors (IWM is held in core this week with trend quality -0.004)
    'n5_core_floor': (P3('min_rank_core', (-0.02, 0.0, 0.02)), 1),
    'n6_sat_floor': (P3('min_rank_sat', (0.08, 0.10, 0.12)), 1),
    # signals
    'n7_tstat': (P3('trend_win', (101, 126, 151), score_mode='tstat'), 1),
    'n8_tq_blend': ([('', r(T, score_mode='tq_blend'))], 0),
    'n9_tq_resid': (P3('trend_win', (101, 126, 151), score_mode='tq_resid'), 1),
    'n10_tq_group_rel': ([('', r(T, score_mode='tq_grp'))], 0),
    'n11_tq_confirm': ([('', r(T, score_mode='tq_confirm'))], 0),
    'n12_tq_volume': ([('', r(T, score_mode='tq_vol'))], 0),
    'n13_tq_ead_gap': (P3('ead_bonus', (0.08, 0.10, 0.12), score_mode='tq_ead'), 1),
    # regime, satellite sleeve only
    'n14_off_spycross': ([('', r(T, sat_off='spy_cross'))], 0),
    'n15_off_breadth': (P3('breadth_min', (0.32, 0.40, 0.48), sat_off='breadth'), 1),
    'n16_off_vol_half': (P3('vol_max', (0.20, 0.25, 0.30), sat_off='vol', sat_off_scale=0.5), 1),
    'n17_off_qqq50_half': ([('', r(T, sat_off='qqq50', sat_off_scale=0.5))], 0),
    # execution
    'n18_chase_skip': (P3('chase_skip', (0.08, 0.10, 0.12)), 1),
    'n19_swap_margin': (P3('swap_margin', (0.04, 0.05, 0.06)), 1),
    'n20_weekly_scan': (P3('cadence', (4, 5, 6)), 1),
    # the sector tilt in the confidence gate (found this week: harness had never modelled it)
    'n21_drop_sector_tilt': (P3('sector_tilt_w', (0.02, 0.0)), 1),
    'n22_half_sector_tilt': (P3('sector_tilt_w', (0.04, 0.05, 0.06)), 1),
    'n23_conf_gate_60': (P3('conf_thresh', (55.0, 60.0, 65.0)), 1),
    'n24_conf_gate_60_no_tilt': (P3('conf_thresh', (55.0, 60.0, 65.0), sector_tilt_w=0.0), 1),
}


def run(name):
    grid, center = IDEAS[name]
    return evaluate(name, grid, center)


if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        for ok, line in pool.imap(run, names):
            print(line, flush=True)
