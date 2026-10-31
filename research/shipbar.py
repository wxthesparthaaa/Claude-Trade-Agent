"""Auto-ship bar evaluator (research/README.md section 4), 2026-10-24.

A candidate is (universe_suffix, Params). Primary setup = 'full'+suffix with the live 25% halt; guardrail =
'static'+suffix. LIVE = Params() on 'full' / 'static'. Every check is reported, and PASS needs all of them:
  wf     walk-forward: choose among {LIVE} + grid on IS (2020-03..2023-03, CAGR/MDD); the choice must be a candidate
         and beat LIVE OOS (2023-03..END), with OOS MDD no worse than LIVE by more than 3 points
  win    >= 3/4 rolling windows beat LIVE on primary, with no window MDD worse by more than 5 points
  jack   >= 13/20 jackknife universes (70% of base satellites + 70% of any added satellites) beat LIVE
  static full-period return >= 0.9x LIVE's (as a growth multiple) and MDD no worse by more than 5 points
  nudge  every grid neighbour (+/-20% of the key parameter) beats LIVE full-period on primary
Usage: from shipbar import evaluate; evaluate(name, grid=[(suffix, Params), ...], center=index)."""
import random
import sys
sys.path.insert(0, 'research')
from harness import *

END = '2026-10-31'
START = '2020-03-01'
IS, OOS = (START, '2023-03-01'), ('2023-03-01', END)
WINS = WINDOWS[:-1] + [(WINDOWS[-1][0], END)]
# The CURRENT live growth config. Since 2026-10-24 live ranks by trend quality (commit in
# research/shipped_changes.md); Params() alone is the pre-2026-10-24 momentum-ranked config.
# sector_tilt_w=0.1 added 2026-10-31: live's composite score (which drives the confidence gate) has always carried
# it, and with it the harness reproduces live's 10/26 picks; without it every earlier 'LIVE' number overstated live.
LIVE_PARAMS = Params(score_mode='trendq', sector_tilt_w=0.1)
LIVE = ('', LIVE_PARAMS)


def _score(r):
    return r['cagr'] / max(r['mdd'], 0.05)


def jack_pairs(suffix, k=20, frac=0.7, seed=7):
    """(base_universe, candidate_universe) pairs sharing the same random 70% of the full-universe satellites."""
    B, Cn = universe('full'), universe('full' + suffix)
    bs = [s for s, v in B.items() if v == 'satellite']
    added = [s for s, v in Cn.items() if v == 'satellite' and s not in B]
    rng = random.Random(seed)
    out = []
    for _ in range(k):
        keep = set(rng.sample(bs, int(len(bs) * frac)))
        add = set(rng.sample(added, int(len(added) * frac))) if added else set()
        b = {s: v for s, v in B.items() if v == 'core' or s in keep}
        c = dict(b)
        c.update({s: Cn[s] for s in add})
        # a candidate may also redefine core membership only via Params, never via universe
        out.append((b, c))
    return out


def evaluate(name, grid, center=0, live=None):
    suffix, cp = grid[center]
    Pu, Lu = universe('full' + suffix), universe('full')
    Su, LSu = universe('static' + suffix), universe('static')
    live = live or LIVE_PARAMS
    # rolling windows
    rc = [simulate(Pu, cp, a, b) for a, b in WINS]
    rb = [simulate(Lu, live, a, b) for a, b in WINS]
    w = sum(c['ret'] > b['ret'] for c, b in zip(rc, rb))
    wdd = [round((c['mdd'] - b['mdd']) * 100, 1) for c, b in zip(rc, rb)]
    wd = [round((c['ret'] - b['ret']) * 100, 1) for c, b in zip(rc, rb)]
    ok_win = w >= 3 and max(wdd) <= 5
    # full period
    fc, fb = simulate(Pu, cp, START, END), simulate(Lu, live, START, END)
    # jackknife
    jw = 0
    for b, c in jack_pairs(suffix):
        jw += simulate(c, cp, START, END)['ret'] > simulate(b, live, START, END)['ret']  # same universes for both
    ok_jack = jw >= 13
    # static guardrail
    sc, sb = simulate(Su, cp, START, END), simulate(LSu, live, START, END)
    ok_static = (1 + sc['ret']) >= 0.9 * (1 + sb['ret']) and sc['mdd'] - sb['mdd'] <= 0.05
    # nudges
    nb = [i for i in (center - 1, center + 1) if 0 <= i < len(grid)]
    nres = [(simulate(universe('full' + grid[i][0]), grid[i][1], START, END)['ret'] - fb['ret']) * 100 for i in nb]
    ok_nudge = all(d > 0 for d in nres) if nres else True
    # walk-forward
    opts = [('', live)] + list(grid)
    isr = [_score(simulate(universe('full' + s), p, *IS)) for s, p in opts]
    pick = max(range(len(opts)), key=lambda i: isr[i])
    oc = simulate(universe('full' + opts[pick][0]), opts[pick][1], *OOS)
    ob = simulate(Lu, live, *OOS)
    ok_wf = pick != 0 and oc['ret'] > ob['ret'] and oc['mdd'] - ob['mdd'] <= 0.03
    ok = ok_wf and ok_win and ok_jack and ok_static and ok_nudge
    flag = lambda b: 'ok' if b else 'FAIL'
    line = (f"{'PASS' if ok else '    '} {name:26s} full {fc['ret']*100:7.1f}% vs {fb['ret']*100:7.1f}% mdd {fc['mdd']*100:4.1f} vs {fb['mdd']*100:4.1f} "
            f"ord {fc['orders']} vs {fb['orders']} | win {w}/4 {wd} dMDD {wdd} [{flag(ok_win)}] | jack {jw}/20 [{flag(ok_jack)}] | "
            f"static {sc['ret']*100:.0f}% vs {sb['ret']*100:.0f}% mdd {sc['mdd']*100:.1f} vs {sb['mdd']*100:.1f} [{flag(ok_static)}] | "
            f"nudge {[round(d, 1) for d in nres]} [{flag(ok_nudge)}] | wf pick {pick} OOS {oc['ret']*100:.1f}% vs {ob['ret']*100:.1f}% "
            f"mdd {oc['mdd']*100:.1f} vs {ob['mdd']*100:.1f} [{flag(ok_wf)}]")
    return ok, line
