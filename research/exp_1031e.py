"""2026-10-31 run, part 5: paired capital sweep for the other leaders and the halt itself, plus this week's
counterfactual with the corrected baseline. Output: research/data/exp_1031e.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import LIVE_PARAMS as T, START, END
from harness import *

r = replace
CFG = {'LIVE': T, 'LIVE halt off': r(T, dd_halt=None), 'LIVE halt exits_ok': r(T, halt_mode='exits_ok'), 'drop_tilt': r(T, sector_tilt_w=0.0),
       'two_sats': r(T, max_sat=2), 'two_sats halt off': r(T, max_sat=2, dd_halt=None), 'group_cap2': r(T, group_cap=2),
       'chase_skip10': r(T, chase_skip=0.10), 'conv.40 floor': r(T, conv_w=(0.40, 0.35, 0.25)),
       'conv.40 floor halt off': r(T, conv_w=(0.40, 0.35, 0.25), dd_halt=None),
       'conv.40 nearest': r(T, conv_w=(0.40, 0.35, 0.25), share_round='nearest'),
       'conv.40 nearest halt off': r(T, conv_w=(0.40, 0.35, 0.25), share_round='nearest', dd_halt=None),
       'drop_tilt+conv.40': r(T, sector_tilt_w=0.0, conv_w=(0.40, 0.35, 0.25))}
CAPS = [4000.0 + 100 * i for i in range(21)]


def one(a):
    n, c, un = a
    x = simulate(universe(un), r(CFG[n], capital=c), START, END)
    return n, c, un, x['ret'], x['mdd'], x['halted_days']


if __name__ == '__main__':
    with Pool(15) as pool:
        res = pool.map(one, [(n, c, un) for n in CFG for c in CAPS for un in ('full', 'static')], chunksize=4)
    D = {(n, c, un): (ret, mdd, h) for n, c, un, ret, mdd, h in res}
    for un in ('full', 'static'):
        print(f'--- {un}, capital sweep 4000..6000')
        for n in CFG:
            v = [D[(n, c, un)] for c in CAPS]
            rets = sorted(x[0] * 100 for x in v)
            wins = sum(D[(n, c, un)][0] > D[('LIVE', c, un)][0] for c in CAPS)
            print(f"{n:28s} median {rets[10]:7.1f} min {rets[0]:7.1f} max {rets[-1]:7.1f} | median MDD {sorted(x[1]*100 for x in v)[10]:4.1f} | halted>300d {sum(x[2] > 300 for x in v):2d}/21 | beats LIVE {wins:2d}/21", flush=True)
    print('--- week 10/26-10/30 counterfactual, full universe, $4,634')
    for nm, p in (('LIVE trendq+tilt', T), ('momentum+tilt (pre-10/24 live)', Params(sector_tilt_w=0.1))):
        f = simulate(universe('full'), r(p, capital=4634.0), '2026-10-26', '2026-10-31', record=True)
        print(f"{nm:32s} fresh {f['ret']*100:+.2f}% holdings {f['holdings']} cash {f['cash']:.0f} orders {f['orders']}")
        cv = simulate(universe('full'), p, '2026-03-01', END, record=True)
        print(f"{'':32s} from 2026-03: week {(cv['curve'].iloc[-1]/cv['curve'][cv['curve'].index <= '2026-10-23'].iloc[-1]-1)*100:+.2f}% holdings {cv['holdings']}")
