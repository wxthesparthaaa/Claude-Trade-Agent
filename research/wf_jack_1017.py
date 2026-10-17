"""Walk-forward x universe jackknife for the rebalance band (H1 follow-up, 2026-10-17).
For each of 20 random 70%-satellite universes: pick the band (0.2..0.6) with best IS CAGR/MDD on 2020-03..2023-03,
then compare its OOS (2023-03..2026-10-17) return/MDD against LIVE band 0.2. Full universe, halt on and off."""
import sys; sys.path.insert(0, 'research')
from harness import *
from exp_1010 import jack_unis
IS, OOS = ('2020-03-01', '2023-03-01'), ('2023-03-01', '2026-10-17')
BANDS = (0.2, 0.3, 0.4, 0.5, 0.6)
for halt in (0.25, None):
    for un in ('full', 'static'):
        wins, dd_ok, picks, rows = 0, 0, [], []
        for U in jack_unis(un):
            isr = {b: simulate(U, Params(band=b, dd_halt=halt), *IS) for b in BANDS}
            best = max(BANDS, key=lambda b: isr[b]['cagr'] / max(isr[b]['mdd'], 0.05))
            o_best = simulate(U, Params(band=best, dd_halt=halt), *OOS)
            o_live = simulate(U, Params(dd_halt=halt), *OOS)
            picks.append(best)
            wins += o_best['ret'] > o_live['ret']
            dd_ok += o_best['mdd'] - o_live['mdd'] <= 0.05
            rows.append((o_best['ret'] - o_live['ret']) * 100)
        print(f"halt={halt} {un}: IS pick beats LIVE OOS in {wins}/20 universes, MDD ok {dd_ok}/20, "
              f"median dRet {sorted(rows)[10]:.1f} pts, picks {dict((b, picks.count(b)) for b in BANDS)}", flush=True)
