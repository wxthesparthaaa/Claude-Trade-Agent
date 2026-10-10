"""2026-10-10 research run: H12 halt modes, H3/H5 group & correlation caps, H14 vol-adjusted ranking,
band-0.5 re-test with more starts, and a universe jackknife (random 70% satellite subsets) to check that
any win is not an artefact of which symbols happen to be in the universe.
Usage: python research/exp_1010.py <group> [NOHALT=1 env to run base without the halt]"""
import os, sys, random
sys.path.insert(0, 'research')
from harness import *
import pandas as pd

END = '2026-10-10'
STARTS = [str(d.date()) for d in pd.date_range('2020-03-01', '2023-09-01', freq='3MS')][:12]
STARTS24 = [str(d.date()) for d in pd.date_range('2020-03-01', '2024-01-01', freq='2MS')][:24]


def jack_unis(un, k=20, frac=0.7, seed=7):
    U = universe(un)
    sats = [s for s, v in U.items() if v == 'satellite']
    rng = random.Random(seed)
    out = []
    for _ in range(k):
        keep = set(rng.sample(sats, int(len(sats) * frac)))
        out.append({s: v for s, v in U.items() if v == 'core' or s in keep})
    return out


def compare(name, cand, base, un, starts=STARTS, jack=True):
    U = universe(un)
    wb, wc = windows(U, base), windows(U, cand)
    better = sum(c['ret'] > b['ret'] for c, b in zip(wc, wb))
    dmdd = [round((c['mdd'] - b['mdd']) * 100, 1) for c, b in zip(wc, wb)]
    dret = [round((c['ret'] - b['ret']) * 100, 1) for c, b in zip(wc, wb)]
    fb, fc = simulate(U, base, '2020-03-01', END), simulate(U, cand, '2020-03-01', END)
    stw = sum(simulate(U, cand, s, END)['ret'] > simulate(U, base, s, END)['ret'] for s in starts)
    jw = '-'
    if jack:
        js = jack_unis(un)
        jw = f"{sum(simulate(u, cand, '2020-03-01', END)['ret'] > simulate(u, base, '2020-03-01', END)['ret'] for u in js)}/{len(js)}"
    print(f"{name:22s} {un:6s} full {fc['ret']*100:7.1f}% vs {fb['ret']*100:7.1f}% mdd {fc['mdd']*100:4.1f} vs {fb['mdd']*100:4.1f} "
          f"ord {fc['orders']} vs {fb['orders']} | win {better}/4 dRet {dret} dMDD {dmdd} | stag {stw}/{len(starts)} | jack {jw}", flush=True)


def run(group, base):
    G = {
        'halt': [('exits_ok', replace(base, halt_mode='exits_ok')),
                 ('exits_ok+reset60', replace(base, halt_mode='exits_ok', halt_reset=60)),
                 ('all+reset60', replace(base, halt_reset=60)),
                 ('all+reset20', replace(base, halt_reset=20)),
                 ('nohalt', replace(base, dd_halt=None))],
        'grp': [(f'grpcap{g}', replace(base, group_cap=g)) for g in (1, 2)],
        'corr': [(f'corr{c}', replace(base, corr_cap=c)) for c in (0.6, 0.7, 0.8, 0.9)],
        'mv': [('mom_vol', replace(base, score_mode='mom_vol')),
               ('mom_vol+band0.5', replace(base, score_mode='mom_vol', band=0.5))],
        'band': [(f'band{b}', replace(base, band=b)) for b in (0.4, 0.5, 0.6)],
    }
    for un in ('static', 'full'):
        for name, c in G[group]:
            compare(name, c, base, un, starts=STARTS24 if group == 'band' else STARTS)


if __name__ == '__main__':
    base = Params(dd_halt=None) if os.environ.get('NOHALT') else Params()
    print(f"## base halt={base.dd_halt}")
    for g in sys.argv[1:]:
        print(f"\n### {g}")
        run(g, base)
