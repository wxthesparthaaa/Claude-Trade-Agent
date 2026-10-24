"""2026-10-24 run 2: trend-quality ranking (score_mode='trendq') follow-up -- window nudges, per-window detail on
static, and variants aimed at the static-universe drawdown (the only failed check in exp_1024b)."""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import evaluate, WINS, START, END
from harness import *

B = Params()
TQ = lambda **k: replace(B, score_mode='trendq', **k)
IDEAS = {
    'trendq 126 (101/126/151)': ([('', TQ(trend_win=w)) for w in (101, 126, 151)], 1),
    'trendq 63 (50/63/76)': ([('', TQ(trend_win=w)) for w in (50, 63, 76)], 1),
    'trendq 189 (151/189/227)': ([('', TQ(trend_win=w)) for w in (151, 189, 227)], 1),
    'trendq + stop 15%': ([('', TQ(stop=s)) for s in (0.12, 0.15, 0.18)], 1),
    'trendq + band 0.5': ([('', TQ(band=b)) for b in (0.4, 0.5, 0.6)], 1),
    'trendq + core 50%': ([('', TQ(core_pct=c, sat_pct=round(1 - c, 2))) for c in (0.4, 0.5, 0.6)], 1),
    'trendq + broad': ([('+broad', TQ())], 0),
}


def run(name):
    grid, c = IDEAS[name]
    return evaluate(name, grid, c)[1]


def detail():
    for un in ('static', 'full'):
        U = universe(un)
        for nm, p in (('LIVE', B), ('trendq', TQ())):
            rs = [simulate(U, p, a, b) for a, b in WINS]
            f = simulate(U, p, START, END, record=True)
            c = f['curve']; dd = (c.cummax() - c) / c.cummax()
            print(f"{un:6s} {nm:7s} windows ret {[round(r['ret']*100,1) for r in rs]} mdd {[round(r['mdd']*100,1) for r in rs]} "
                  f"| full {f['ret']*100:.0f}% mdd {f['mdd']*100:.1f} at {dd.idxmax().date()} halt {f['halted_days']}d trips {f['trips']} win {f['win']*100:.0f}% payoff {f['payoff']:.2f}", flush=True)


if __name__ == '__main__':
    if not sys.argv[1:]: detail()
    names = sys.argv[1:] or list(IDEAS)
    with Pool(len(names)) as pool:
        for line in pool.imap(run, names):
            print(line, flush=True)
