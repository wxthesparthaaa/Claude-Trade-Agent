"""Escalation-bar checker: candidate vs LIVE on (a) 4 rolling windows, (b) 12 staggered start dates
(paired, each run to 2026-10-02), (c) +/-20% parameter nudges, with the 25% halt both ON and OFF."""
import sys; sys.path.insert(0, 'research')
from harness import *
import pandas as pd

STARTS = [str(d.date()) for d in pd.date_range('2020-03-01', '2023-09-01', freq='3MS')][:12]

def bar(cand, base, uni):
    wb = windows(uni, base); wc = windows(uni, cand)
    better = sum(c['ret'] > b['ret'] for c, b in zip(wc, wb))
    ddok = all(c['mdd'] - b['mdd'] <= 0.05 for c, b in zip(wc, wb))
    st = [(simulate(uni, cand, s, '2026-10-03')['ret'], simulate(uni, base, s, '2026-10-03')['ret']) for s in STARTS]
    stw = sum(c > b for c, b in st)
    return better, ddok, stw, [round((c['ret'] - b['ret']) * 100, 1) for c, b in zip(wc, wb)], [round((c['mdd'] - b['mdd']) * 100, 1) for c, b in zip(wc, wb)]

def report(label, cands, uni_names=('static', 'full')):
    for halt in (0.25, None):
        base = Params(dd_halt=halt)
        for un in uni_names:
            U = universe(un)
            for name, mk in cands:
                c = mk(base)
                b, ok, stw, dret, ddd = bar(c, base, U)
                print(f'{label:10s} halt={halt} {un:6s} {name:14s} windows {b}/4 ddOK={ok!s:5s} staggered {stw:2d}/12  dRet/w {dret}  dMDD/w {ddd}')

if __name__ == '__main__':
    which = sys.argv[1]
    if which == 'band':
        report('band', [(f'band{x}', (lambda x: lambda b: replace(b, band=x))(x)) for x in (0.4, 0.5, 0.6)])
    if which == 'cad':
        report('cadx', [(f'cad{x}x', (lambda x: lambda b: replace(b, cadence=x, exits_on_cadence=True))(x)) for x in (4, 5, 6, 10)])
    if which == 'stop':
        report('stop', [(f'stop{x}', (lambda x: lambda b: replace(b, stop=x))(x)) for x in (0.25, 0.30, None)])
    if which == 'conf':
        report('conf', [(f'conf{x}', (lambda x: lambda b: replace(b, conf_thresh=x))(x)) for x in (75.0, 80.0, 84.0)])
    if which == 'combo':
        report('combo', [('conf80+band0.5', lambda b: replace(b, conf_thresh=80.0, band=0.5)),
                         ('conf80+band0.4', lambda b: replace(b, conf_thresh=80.0, band=0.4)),
                         ('conf80+band0.6', lambda b: replace(b, conf_thresh=80.0, band=0.6))])
    if which == 'combo2':
        report('combo2', [('conf75+band0.5', lambda b: replace(b, conf_thresh=75.0, band=0.5)),
                          ('conf84+band0.5', lambda b: replace(b, conf_thresh=84.0, band=0.5))])
