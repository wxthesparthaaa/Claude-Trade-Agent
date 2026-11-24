"""2026-11-24 (user request: "be very aggressive"): the aggression frontier. Each lever is moved one at a time (and a few stacked)
against the CURRENT live config; reports return AND the cost (max drawdown, worst rolling window, halted days) on the static and full
universes, from $5k. Not a ship-bar run: the user asked for more risk, so the question is what each lever BUYS and what it COSTS.
Usage: python research/exp_1124b.py   Output: research/data/exp_1124b.txt"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, 'research')
from multiprocessing import Pool
import shipbar
from shipbar import LIVE_PARAMS as T
from harness import *

END = '2026-11-20'
WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], END)]
r = replace
LEV = {'TQQQ': 'core'}
CFG = {
    'LIVE (core 40 QQQ / sat 60 x3, stop 20, halt 25)': (T, {}),
    # --- allocation ---
    'core 20 / sat 80': (r(T, core_pct=0.2, sat_pct=0.8), {}),
    'core 0 / sat 100': (r(T, core_pct=0.0, sat_pct=1.0), {}),
    # --- concentration ---
    '2 satellites, max single 50%': (r(T, max_sat=2, max_single=0.5), {}),
    '2 satellites, sat 100%, max 50%': (r(T, core_pct=0.0, sat_pct=1.0, max_sat=2, max_single=0.5), {}),
    '4 satellites': (r(T, max_sat=4), {}),
    '5 satellites, sat 80%': (r(T, max_sat=5, core_pct=0.2, sat_pct=0.8), {}),
    # --- entry looseness ---
    'confidence gate 60': (r(T, conf_thresh=60.0), {}),
    'confidence gate 50': (r(T, conf_thresh=50.0), {}),
    # --- exits ---
    'stop 25%': (r(T, stop=0.25), {}),
    'stop 30%': (r(T, stop=0.30), {}),
    'no momentum exit': (r(T, mom_exit=None), {}),
    'stop 25% + no momentum exit': (r(T, stop=0.25, mom_exit=None), {}),
    # --- halt ---
    'halt 35%': (r(T, dd_halt=0.35), {}),
    'halt 50%': (r(T, dd_halt=0.50), {}),
    'no halt': (r(T, dd_halt=None), {}),
    # --- idle cash ---
    'sweep idle cash >5% into targets': (r(T, cash_sweep=0.05), {}),
    # --- leveraged ETFs (3x) ---
    'core = TQQQ above its 200d (else cash)': (r(T, core_switch=('TQQQ', 'CASH', 200)), LEV),
    'core 20 TQQQ / sat 80': (r(T, core_switch=('TQQQ', 'CASH', 200), core_pct=0.2, sat_pct=0.8), LEV),
    # --- stacks ---
    'STACK A: core 20/sat 80, conf 60, sweep': (r(T, core_pct=0.2, sat_pct=0.8, conf_thresh=60.0, cash_sweep=0.05), {}),
    'STACK B: A + 2 sats? no: 4 sats, max 40%': (r(T, core_pct=0.2, sat_pct=0.8, conf_thresh=60.0, cash_sweep=0.05, max_sat=4, max_single=0.40), {}),
    'STACK C: sat 100, 3 sats, conf 60, sweep, stop 25': (r(T, core_pct=0.0, sat_pct=1.0, conf_thresh=60.0, cash_sweep=0.05, stop=0.25, max_single=0.40), {}),
    'STACK D: C + no halt': (r(T, core_pct=0.0, sat_pct=1.0, conf_thresh=60.0, cash_sweep=0.05, stop=0.25, max_single=0.40, dd_halt=None), {}),
}


def one(name):
    p, extra = CFG[name]
    out = []
    for uname in ('static', 'full'):
        u = universe(uname); u.update(extra)
        full = simulate(u, p, shipbar.START, END)
        wins = [simulate(u, p, a, b) for a, b in WINS]
        out.append((uname, full, wins))
    return name, out


if __name__ == '__main__':
    with Pool(max(os.cpu_count() - 1, 1)) as pool:
        res = pool.map(one, list(CFG))
    for uname_i, uname in enumerate(('static', 'full')):
        print(f'\n=== {uname} universe, $5,000 start, {shipbar.START}..{END} (win = 4 rolling windows) ===')
        print(f"{'config':52s} {'return':>8} {'CAGR':>6} {'MDD':>5} | {'win returns':>26} | {'worst win MDD':>13} {'halt d':>6} {'ord':>4}")
        for name, out in res:
            _, f, w = out[uname_i]
            print(f"{name:52s} {f['ret']*100:7.0f}% {f['cagr']*100:5.0f}% {f['mdd']*100:5.1f} | {' '.join(f'{x['ret']*100:6.0f}' for x in w):>26} | {max(x['mdd'] for x in w)*100:13.1f} {f.get('halted_days', 0):6} {f.get('orders', 0):4}")
