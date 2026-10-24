"""2026-10-24 run 2 (first run of the reworked routine). Every idea goes through shipbar.evaluate (the README
auto-ship bar) on the live-like setup (full universe, halt on) with the static universe as guardrail.
Usage: python research/exp_1024b.py [names...]   (no args = all)"""
import sys
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import evaluate
from harness import Params, replace

B = Params()
IDEAS = {
    # universe / selection
    'broad (2020 top caps)': ([('+broad', B)], 0),
    'sector ETFs': ([('+etf', B)], 0),
    'broad + sector ETFs': ([('+broad+etf', B)], 0),
    # signals
    'blend 126+252 mom': ([('', replace(B, score_mode='blend'))], 0),
    '52w-high proximity': ([('', replace(B, score_mode='hi52'))], 0),
    'trend quality slope*R2': ([('', replace(B, score_mode='trendq'))], 0),
    # construction
    'core = 1 ETF': ([('', replace(B, max_core=1))], 0),
    'satellites 4 (3/4/5)': ([('', replace(B, max_sat=n)) for n in (3, 4, 5)], 1),
    'satellites 5 (4/5/6)': ([('', replace(B, max_sat=n)) for n in (4, 5, 6)], 1),
    # execution
    'gap-up skip 4% (3/4/5)': ([('', replace(B, gap_skip=g)) for g in (0.03, 0.04, 0.05)], 1),
    '5d blow-off skip 15%': ([('', replace(B, rev_skip=g)) for g in (0.12, 0.15, 0.18)], 1),
}


def run(name):
    grid, c = IDEAS[name]
    return evaluate(name, grid, c)[1]


if __name__ == '__main__':
    names = sys.argv[1:] or list(IDEAS)
    with Pool(min(len(names), 11)) as pool:
        for line in pool.imap(run, names):
            print(line, flush=True)
