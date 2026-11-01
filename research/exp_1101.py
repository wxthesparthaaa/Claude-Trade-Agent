"""2026-11-01 run: earnings-surprise drift (backlog #10) through the auto-ship bar, against LIVE = trendq + sector tilt.
Usage: python research/exp_1101.py [name ...]   (no args = all)"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(__file__))
from dataclasses import replace as r
from shipbar import LIVE_PARAMS as T, evaluate, START, END
from harness import universe, simulate

IDEAS = {
    # S = clip(surprise/0.5, -1, 1); bonus is in trend-quality score units (typical scores 0.07-0.6)
    'eps_tilt_mag': ([('', r(T, score_mode='tq_eps', eps_bonus=b)) for b in (0.10, 0.20, 0.30)], 1),
    'eps_tilt_sign': ([('', r(T, score_mode='tq_eps', eps_mode='sign', eps_bonus=b)) for b in (0.05, 0.10, 0.15)], 1),
    'eps_veto': ([('', r(T, eps_veto=v)) for v in (0.05, 0.10, 0.20)], 1),
}
if __name__ == '__main__':
    if '--sanity' in sys.argv:
        a = simulate(universe('full'), T, START, END)
        b = simulate(universe('full'), r(T, score_mode='tq_eps', eps_bonus=0.0), START, END)
        print('LIVE', round(a['ret'] * 100, 2), a['orders'], '| tq_eps bonus 0', round(b['ret'] * 100, 2), b['orders'])
        sys.exit()
    for name in (sys.argv[1:] or IDEAS):
        grid, center = IDEAS[name]
        print(evaluate(name, grid, center)[1], flush=True)
