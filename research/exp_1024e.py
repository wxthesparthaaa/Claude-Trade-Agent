"""2026-10-24 run 2: smoothness variants that keep live momentum (mom x R^2, R^2 gate) -- aimed at keeping trendq's
turnover cut without its static-universe drawdown."""
import sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
from shipbar import evaluate
from harness import Params, replace

B = Params()
IDEAS = {
    'mom x R2 126 (101/126/151)': ([('', replace(B, score_mode='mom_r2', trend_win=w)) for w in (101, 126, 151)], 1),
    'mom x R2 252 (202/252)': ([('', replace(B, score_mode='mom_r2', trend_win=w)) for w in (202, 252)], 1),
    'R2 gate 0.5 (0.4/0.5/0.6)': ([('', replace(B, score_mode='r2_gate', r2_min=r)) for r in (0.4, 0.5, 0.6)], 1),
    'R2 gate 0.3 (0.24/0.3/0.36)': ([('', replace(B, score_mode='r2_gate', r2_min=r)) for r in (0.24, 0.3, 0.36)], 1),
    'mom x R2 + band 0.5': ([('', replace(B, score_mode='mom_r2', band=b)) for b in (0.4, 0.5, 0.6)], 1),
}


def run(name):
    grid, c = IDEAS[name]
    return evaluate(name, grid, c)[1]


if __name__ == '__main__':
    with Pool(len(IDEAS)) as pool:
        for line in pool.imap(run, list(IDEAS)):
            print(line.replace('np.float64(', '').replace(')', ''), flush=True)
