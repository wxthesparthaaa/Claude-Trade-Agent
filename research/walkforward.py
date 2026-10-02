"""Walk-forward: tune (band x conf) on 2020-03..2023-03 (in-sample), evaluate the IS winner on 2023-03..2026-10."""
import sys; sys.path.insert(0, 'research')
from harness import *
IS, OOS = ('2020-03-01', '2023-03-01'), ('2023-03-01', '2026-10-03')
for halt in (0.25, None):
    for un in ('static', 'full'):
        U = universe(un); rows = []
        for band in (0.2, 0.3, 0.4, 0.5, 0.6):
            for conf in (70.0, 75.0, 80.0, 85.0):
                p = Params(band=band, conf_thresh=conf, dd_halt=halt)
                a, b = simulate(U, p, *IS), simulate(U, p, *OOS)
                rows.append((a['cagr'] / max(a['mdd'], 0.05), band, conf, a['ret'], b['ret'], b['mdd']))
        rows.sort(reverse=True)
        live = [r for r in rows if r[1] == 0.2 and r[2] == 70.0][0]
        oos_rank = sorted(rows, key=lambda r: -r[4])
        print(f'halt={halt} {un}: IS-best band={rows[0][1]} conf={rows[0][2]} IS {rows[0][3]*100:.1f}% -> OOS {rows[0][4]*100:.1f}% (mdd {rows[0][5]*100:.1f}%), '
              f'OOS rank {oos_rank.index(rows[0])+1}/20 | LIVE IS {live[3]*100:.1f}% OOS {live[4]*100:.1f}% (mdd {live[5]*100:.1f}%), OOS rank {oos_rank.index(live)+1}/20')
