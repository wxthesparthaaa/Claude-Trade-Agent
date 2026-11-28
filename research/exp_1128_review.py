"""2026-11-28 weekly review counterfactual: harness LIVE (big-bet, halt off) over the live week, fresh start at live equity,
plus what the long-path harness holds now. Output: research/data/exp_1128_review.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from harness import *
from shipbar import LIVE_PARAMS as T, PRE_1124_PARAMS as P0
F = universe('full')
for name, p in [('LIVE (big-bet)', T), ('pre-11/24 (index core)', P0)]:
    for a, cap in [('2026-11-20', 3854.0), ('2026-11-23', 3854.0), ('2026-08-12', 5000.0)]:
        r = simulate(F, replace(p, capital=cap), a, '2026-11-28', record=True)
        print(f"{name:24s} from {a} ${cap:.0f}: ret {r['ret']*100:6.2f}% final ${r['final']:.0f} holds {r['holdings']} orders {r['orders']}")
r = simulate(F, T, '2020-03-01', '2026-11-28', record=True)
print('long path (2020-03, $5k) holds', r['holdings'], 'cash', round(r['cash']), 'last trades', [(t[0], t[2], str(t[4])[:10]) for t in r['trades'][-6:]])
