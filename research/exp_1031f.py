"""2026-10-31, user request: concrete options for the 25% halt, each vs LIVE (today's halt).
Paired capital sweep $4,000-$6,000, 4 windows and 12 staggered starts at $5,000, 20-universe jackknife; full and static.
Part 2 re-tests the three shortlisted candidates under each serious option. Output: research/data/exp_1031f.txt"""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import exp_1010 as X
from shipbar import LIVE_PARAMS as T, START, END, WINS
from harness import *

r = replace
OPTS = {
    'A keep as is': {},
    'B no halt': dict(dd_halt=None),
    'C 30% threshold': dict(dd_halt=0.30),
    'C 35% threshold': dict(dd_halt=0.35),
    'C 40% threshold': dict(dd_halt=0.40),
    'D freeze, restart after 20d': dict(halt_reset=20),
    'D freeze, restart after 60d': dict(halt_reset=60),
    'D freeze, restart after 120d': dict(halt_reset=120),
    'E exits only, restart 60d': dict(halt_mode='exits_ok', halt_reset=60),
    'E exits only, restart 120d': dict(halt_mode='exits_ok', halt_reset=120),
    'F freeze until SPY>200d': dict(halt_release='spy200'),
    'F exits only until SPY>200d': dict(halt_mode='exits_ok', halt_release='spy200'),
    'G core only, restart 60d': dict(halt_mode='derisk', halt_reset=60),
    'G core only until SPY>200d': dict(halt_mode='derisk', halt_release='spy200'),
    'H half sats, restart 60d': dict(halt_mode='derisk', halt_sat_scale=0.5, halt_reset=60),
    'H half sats until SPY>200d': dict(halt_mode='derisk', halt_sat_scale=0.5, halt_release='spy200'),
}
CAPS = [4000.0 + 100 * i for i in range(21)]
SERIOUS = ['A keep as is', 'B no halt', 'C 35% threshold', 'D freeze, restart after 60d', 'F exits only until SPY>200d',
           'G core only until SPY>200d', 'H half sats until SPY>200d']
CANDS = {'drop tilt': dict(sector_tilt_w=0.0), 'conviction+nearest': dict(conv_w=(0.40, 0.35, 0.25), share_round='nearest'),
         'two sats': dict(max_sat=2)}


def sweep(a):
    n, un, cand, c = a
    x = simulate(universe(un), r(T, **OPTS[n], **(CANDS[cand] if cand else {}), capital=c), START, END)
    return (n, un, cand, c), (x['ret'], x['mdd'], x['halted_days'], x['orders'])


def detail(a):
    n, un = a
    p, b = r(T, **OPTS[n]), T
    U = universe(un)
    wr = [(simulate(U, p, x, y), simulate(U, b, x, y)) for x, y in WINS]
    st = [simulate(U, p, s, END)['ret'] - simulate(U, b, s, END)['ret'] for s in X.STARTS]
    js = [simulate(u, p, START, END)['ret'] - simulate(u, b, START, END)['ret'] for u in X.jack_unis(un)]
    oos = simulate(U, p, '2023-03-01', END)
    return (n, un), (sum(c['ret'] > d['ret'] for c, d in wr), max(c['mdd'] for c, _ in wr) * 100, sum(d > 0 for d in st), sorted(st)[6] * 100,
                     sum(d > 0 for d in js), sorted(js)[10] * 100, oos['ret'] * 100, oos['mdd'] * 100)


if __name__ == '__main__':
    with Pool(15) as pool:
        S = dict(pool.map(sweep, [(n, un, None, c) for n in OPTS for un in ('full', 'static') for c in CAPS], chunksize=4))
        Dt = dict(pool.map(detail, [(n, un) for n in OPTS for un in ('full', 'static')]))
        Sc = dict(pool.map(sweep, [(n, un, k, c) for n in SERIOUS for k in CANDS for un in ('full', 'static') for c in CAPS], chunksize=4))
    for un in ('full', 'static'):
        print(f'--- {un}: capital sweep medians, then $5,000 detail vs LIVE')
        for n in OPTS:
            v = [S[(n, un, None, c)] for c in CAPS]
            rt = sorted(x[0] * 100 for x in v)
            md = sorted(x[1] * 100 for x in v)
            beat = sum(S[(n, un, None, c)][0] > S[('A keep as is', un, None, c)][0] for c in CAPS)
            d = Dt[(n, un)]
            print(f"{n:30s} ret med {rt[10]:7.1f} min {rt[0]:7.1f} max {rt[-1]:7.1f} | MDD med {md[10]:4.1f} max {md[-1]:4.1f} | halted med {sorted(x[2] for x in v)[10]:4d}d >300d {sum(x[2] > 300 for x in v):2d}/21 | "
                  f"orders {sorted(x[3] for x in v)[10]:4d} | beats A {beat:2d}/21 | win {d[0]}/4 worstWinMDD {d[1]:4.1f} | starts {d[2]:2d}/12 med {d[3]:7.1f} | jack {d[4]:2d}/20 med {d[5]:7.1f} | 2023+ {d[6]:6.1f} mdd {d[7]:4.1f}", flush=True)
    print('--- candidates under each serious option: median return / median MDD / frozen>300d, sweep (A = today)')
    for k in CANDS:
        for n in SERIOUS:
            row = []
            for un in ('full', 'static'):
                v = [Sc[(n, un, k, c)] for c in CAPS]
                base = sum(Sc[(n, un, k, c)][0] > S[(n, un, None, c)][0] for c in CAPS)
                row.append(f"{un} {sorted(x[0]*100 for x in v)[10]:7.1f} min {min(x[0]*100 for x in v):7.1f} mdd {sorted(x[1]*100 for x in v)[10]:4.1f} frozen {sum(x[2] > 300 for x in v):2d}/21 beats same-option LIVE {base:2d}/21")
            print(f"{k:20s} {n:30s} " + ' | '.join(row), flush=True)
