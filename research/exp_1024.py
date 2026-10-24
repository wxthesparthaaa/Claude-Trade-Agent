"""2026-10-24 research run.
  wf     H1 band, rolling walk-forward re-tune: every 6 months (Mar/Sep, from 2021-09) pick the band in BANDS with the
         best CAGR/MDD on the EXPANDING history 2020-03..tune date, then trade with that band (Params.band_sched).
         Scored on W2/W3/W4 (W1 has no prior data to tune on) and on 2021-09..END, vs LIVE band 0.2; + jackknife.
  buf    H18 hold_rank_buffer 1/2: a held satellite keeps its slot until it drops below rank cap+buffer.
         Motivation: a fresh LIVE-config run on the full universe made 1-2 day not_target round trips in Oct 2026
         (ALAB 10/19-10/20, ARM 10/20-10/21, INTC 10/21-10/23), i.e. pure top-of-ranking churn.
  invvol H19 satellite budget split by 1/63d vol instead of equally (AEHR, the most volatile name, was the biggest loser).
  split  H20 core/satellite split 30/70, 50/50, 60/40 vs live 40/60 (risk control after an all-semis satellite drawdown).
Usage: python research/exp_1024.py <group...>   (NOHALT=1 env -> base without the halt)"""
import os, sys
sys.path.insert(0, 'research')
import exp_1010 as X
from harness import *
from multiprocessing import Pool

END = '2026-10-24'
X.END = END
W4 = WINDOWS[:-1] + [(WINDOWS[-1][0], END)]   # extend W4 to this week (module level so spawned workers see it)
X.windows = lambda uni, p: [simulate(uni, p, a, b) for a, b in W4]
BANDS = (0.2, 0.3, 0.4, 0.5, 0.6)
TUNE = [f'{y}-{m}-01' for y in range(2021, 2027) for m in ('03', '09')][1:]  # 2021-09 .. 2026-09
TUNE = [d for d in TUNE if d < END]


def sched_for(U, halt):
    out = []
    for d in TUNE:
        isr = {b: simulate(U, Params(band=b, dd_halt=halt), '2020-03-01', d) for b in BANDS}
        out.append((d, max(BANDS, key=lambda b: isr[b]['cagr'] / max(isr[b]['mdd'], 0.05))))
    return tuple(out)


def wf_one(args):
    U, halt = args
    sch = sched_for(U, halt)
    cand, base = Params(band_sched=sch, dd_halt=halt), Params(dd_halt=halt)
    wins = W4[1:]
    rc = [simulate(U, cand, a, b) for a, b in wins]
    rb = [simulate(U, base, a, b) for a, b in wins]
    fc, fb = simulate(U, cand, '2021-09-01', END), simulate(U, base, '2021-09-01', END)
    return sch, rc, rb, fc, fb


def wf():
    for halt in (0.25, None):
        for un in ('static', 'full'):
            sch, rc, rb, fc, fb = wf_one((universe(un), halt))
            w = sum(c['ret'] > b['ret'] for c, b in zip(rc, rb))
            print(f"halt={halt} {un}: sched {[b for _, b in sch]}\n   W2-W4 win {w}/3 dRet {[round((c['ret']-b['ret'])*100,1) for c,b in zip(rc,rb)]} "
                  f"dMDD {[round((c['mdd']-b['mdd'])*100,1) for c,b in zip(rc,rb)]} | 2021-09..end {fc['ret']*100:.1f}% vs {fb['ret']*100:.1f}% "
                  f"mdd {fc['mdd']*100:.1f} vs {fb['mdd']*100:.1f}", flush=True)
            with Pool(8) as pool:
                js = pool.map(wf_one, [(u, halt) for u in X.jack_unis(un)])
            jw = sum(f['ret'] > b['ret'] for _, _, _, f, b in js)
            jwin = sum(sum(c['ret'] > b['ret'] for c, b in zip(rc_, rb_)) >= 2 for _, rc_, rb_, _, _ in js)
            jdd = sum(f['mdd'] - b['mdd'] <= 0.05 for _, _, _, f, b in js)
            d = sorted((f['ret'] - b['ret']) * 100 for _, _, _, f, b in js)
            print(f"   jackknife: beats LIVE 2021-09..end {jw}/20, >=2/3 windows {jwin}/20, MDD ok {jdd}/20, median dRet {d[10]:.1f} pts", flush=True)


def _cmp(a):
    name, c, base, un = a
    import io, contextlib
    f = io.StringIO()
    with contextlib.redirect_stdout(f):
        X.compare(name, c, base, un)
    return f.getvalue()


def grid(base):
    return {
        'buf': [(f'buf{b}', replace(base, hold_rank_buffer=b)) for b in (1, 2)],
        'hold': [(f'hold{h}', replace(base, min_hold=h)) for h in (5, 8, 10, 12, 21)],
        'bufband': [('buf1+band0.5', replace(base, hold_rank_buffer=1, band=0.5))],
        'invvol': [('invvol', replace(base, sat_weight_scheme='invvol')),
                   ('invvol+band0.5', replace(base, sat_weight_scheme='invvol', band=0.5))],
        'split': [(f'split{int(c*100)}', replace(base, core_pct=c, sat_pct=round(1 - c, 2))) for c in (0.3, 0.5, 0.6)],
    }


if __name__ == '__main__':
    base = Params(dd_halt=None) if os.environ.get('NOHALT') else Params()
    print(f"## base halt={base.dd_halt}  end={END}", flush=True)
    G = grid(base)
    for g in sys.argv[1:]:
        print(f"\n### {g}", flush=True)
        if g == 'wf':
            wf()
            continue
        jobs = [(n, c, base, un) for un in ('static', 'full') for n, c in G[g]]
        with Pool(8) as pool:
            for out in pool.map(_cmp, jobs):
                print(out, end='', flush=True)
