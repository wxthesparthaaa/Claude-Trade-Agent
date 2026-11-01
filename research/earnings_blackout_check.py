"""Is an earnings blackout for NEW entries worth testing properly?  (backlog #13, 2026-11-01)

Part 1  data coverage of research/data/earnings.csv for the satellites
Part 2  event study: how big are earnings-reaction gaps vs the live 20% stop and vs a normal day
Part 3  tag the LIVE config's own round trips (full + static universes): did trips that spanned an earnings
        reaction day do worse, and how much of the pain do they explain
Part 4  (--filter) the filter itself through the auto-ship bar: shipbar.evaluate with earn_blackout = 3/5/8 days
Usage: python research/earnings_blackout_check.py [--filter]
"""
import os, sys, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
from dataclasses import replace
from harness import universe, load_panel, simulate, earnings_reaction_days
from shipbar import LIVE_PARAMS as LIVE, START, END, evaluate

earn = pd.read_csv(os.path.join(os.path.dirname(__file__), 'data', 'earnings.csv'), parse_dates=['report_date'])
print('earnings rows:', len(earn), '| symbols:', earn['symbol'].nunique(), '| labeled before/after:', int(earn['report_time'].notna().sum()))

for uname in ('static', 'full'):
    uni = universe(uname)
    sats = [s for s, v in uni.items() if v == 'satellite']
    idx, op, hi, lo, cl = load_panel(sats)
    sats = [s for s in sats if s in cl.columns]
    rd = earnings_reaction_days(sats, idx)
    print(f'\n=== {uname} universe: {len(sats)} satellites; with earnings dates: {len(rd)} (missing: {[s for s in sats if s not in rd]})')

    # Part 2: event study
    gaps, moves, normal = [], [], []
    for s in sats:
        o, c = op[s].values, cl[s].values
        r = rd.get(s, np.array([], dtype=int))
        for k in r:
            if 1 <= k < len(c) and not np.isnan(c[k - 1]) and not np.isnan(o[k]):
                gaps.append(o[k] / c[k - 1] - 1)
                moves.append(c[k] / c[k - 1] - 1)
        ng = o[1:] / c[:-1] - 1
        mask = np.ones(len(ng), bool); mask[[k - 1 for k in r if 1 <= k <= len(ng)]] = False
        normal.extend(ng[mask & ~np.isnan(ng)])
    g, m, nm = np.array(gaps), np.array(moves), np.array(normal)
    print(f'Part 2 event study, {len(g)} earnings reactions:')
    print(f'  median |open gap|  earnings {np.median(abs(g))*100:5.2f}%   normal day {np.median(abs(nm))*100:5.2f}%')
    for th in (0.05, 0.10, 0.20):
        print(f'  |gap| > {th:.0%}: earnings {np.mean(abs(g) > th)*100:5.1f}%   normal {np.mean(abs(nm) > th)*100:5.2f}%   | gap < -{th:.0%}: earnings {np.mean(g < -th)*100:4.1f}%')
    print(f'  worst earnings gap {g.min()*100:.1f}%, worst day-close move {m.min()*100:.1f}%; 1 in {len(g)/max(1, np.sum(g < -0.10)):.0f} earnings gaps down >10%')

    # Part 3: tag the live config's round trips
    res = simulate(uni, LIVE, START, END, record=True)
    rdall = earnings_reaction_days(list(uni), idx)
    rt = {}
    for sym, pnl, reason, ed, xd, closed in res['trades']:
        key = (sym, ed)
        d = rt.setdefault(key, dict(pnl=0.0, reasons=[], exit=xd, closed=False))
        d['pnl'] += pnl; d['reasons'].append(reason); d['exit'] = xd; d['closed'] = d['closed'] or closed
    rows = []
    for (sym, ed), d in rt.items():
        if not d['closed']:
            continue
        e_pos, x_pos = idx.get_loc(pd.Timestamp(ed)), idx.get_loc(pd.Timestamp(d['exit']))
        r = rdall.get(sym, np.array([], dtype=int))
        span = bool(((r > e_pos) & (r <= x_pos)).any())
        near = bool(((r > e_pos) & (r <= e_pos + 5)).any())   # entered 1..5 sessions before a reaction day = what the filter blocks
        rows.append((sym, d['pnl'], span, any(x.startswith('stop') for x in d['reasons']), ed, d['exit'], near))
    df = pd.DataFrame(rows, columns=['sym', 'pnl', 'span', 'stop', 'entry', 'exit', 'near'])
    sat = df[~df['sym'].isin([s for s, v in uni.items() if v == 'core'])]
    print(f'Part 3 LIVE round trips ({len(df)} closed; satellites {len(sat)}), full period {START}..{END}, final ret {res["ret"]*100:.0f}%:')
    for label, g2 in (('satellite spanned earnings', sat[sat['span']]), ('satellite did not', sat[~sat['span']])):
        if len(g2):
            print(f'  {label:28s} n={len(g2):3d}  mean ${g2["pnl"].mean():7.2f}  median ${g2["pnl"].median():7.2f}  win {np.mean(g2["pnl"] > 0)*100:4.0f}%  total ${g2["pnl"].sum():9.0f}  worst ${g2["pnl"].min():8.0f}')
    for label, g2 in (('entered <=5d before earnings', sat[sat['near']]), ('entered otherwise', sat[~sat['near']])):
        if len(g2):
            print(f'  {label:28s} n={len(g2):3d}  mean ${g2["pnl"].mean():7.2f}  median ${g2["pnl"].median():7.2f}  win {np.mean(g2["pnl"] > 0)*100:4.0f}%  total ${g2["pnl"].sum():9.0f}  worst ${g2["pnl"].min():8.0f}')
    losers = sat.sort_values('pnl').head(10)
    print(f'  10 worst satellite trips: {int(losers["span"].sum())}/10 spanned earnings; stop-outs overall {int(sat["stop"].sum())}, of which spanned {int((sat["stop"] & sat["span"]).sum())}')
    held_days = (pd.to_datetime(sat['exit']) - pd.to_datetime(sat['entry'])).dt.days
    print(f'  share of satellite trips spanning earnings: {sat["span"].mean()*100:.0f}% (mean hold {held_days.mean():.0f} days)')

if '--filter' in sys.argv:
    print('\n=== Part 4: filter through the ship bar (center = 5 days)')
    for n_center in ((3, 5, 8),):
        grid = [('', replace(LIVE, earn_blackout=n)) for n in n_center]
        ok, line = evaluate('earn_blackout_3/5/8', grid, center=1)
        print(line)
