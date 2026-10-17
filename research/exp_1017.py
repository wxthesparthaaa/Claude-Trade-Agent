"""2026-10-17 research run. Motivated by the week of 10/12-10/16: the 3 semis satellites (unmanaged since the
9/21 scan outage) fell 16-29% in one week together, AEHR -43% from its 10/2 high.
  H15 halt on a rolling peak (halt_peak_window) instead of the all-time peak -> less halt path-dependence?
  H16 faster exits: SMA-cross exit, short-window crash exit, 63d-high drawdown exit (each +/- 10d cooldown).
Uses exp_1010.compare (4 windows, staggered starts, universe jackknife).
Usage: python research/exp_1017.py <group...>   (NOHALT=1 env -> base without the halt)"""
import os, sys
sys.path.insert(0, 'research')
import exp_1010 as X
from harness import *

X.END = '2026-10-17'


def groups(base):
    return {
        'hpw': [(f'hpw{w}', replace(base, halt_peak_window=w)) for w in (126, 252, 504)],
        'sma': [(f'sma{n}{"+cd10" if cd else ""}', replace(base, sma_exit=n, cooldown=cd)) for n in (50, 100, 200) for cd in (0, 10)],
        'crash': [(f'crash{k}/{th}+cd10', replace(base, crash_exit=(k, th), cooldown=10))
                  for k, th in ((5, -0.15), (10, -0.15), (10, -0.20), (21, -0.20), (21, -0.25))],
        'peak': [(f'peak{x}+cd{cd}', replace(base, peak_exit=x, cooldown=cd)) for x in (0.20, 0.25, 0.30) for cd in (0, 10)],
    }


if __name__ == '__main__':
    base = Params(dd_halt=None) if os.environ.get('NOHALT') else Params()
    print(f"## base halt={base.dd_halt}  end={X.END}")
    G = groups(base)
    for g in sys.argv[1:]:
        print(f"\n### {g}")
        for un in ('static', 'full'):
            for name, c in G[g]:
                X.compare(name, c, base, un)
