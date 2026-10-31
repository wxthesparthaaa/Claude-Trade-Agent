# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

Baseline changed on 2026-10-31: LIVE is now trendq **plus the sector tilt**. Verdicts from before that date were
measured against a baseline that overstated live.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | Design (user) | **The halt decision.** It blocks every order and can freeze a path for years. LIVE halt on vs off, $4–6k capital sweep: full +1253% (as low as +74%), MDD 40.6 vs +968%, MDD 47.2; static +141%, MDD 37.6 vs +273%, MDD 39.2 | Most candidates fail only because a nudge lands on a frozen path; risk limits are the user's call | **propose to user** (10/31) |
| 2 | Signals | **Drop the sector tilt from growth's score** (`scoring_weights` without `sector_tilt`, a one-line change) | Capital sweep beats LIVE 21/21 on full and 20/21 on static, and never freezes on full. A 20-day ETF rotation shifts the entry gate by ±0.1, which is the same as moving the momentum bar by ±17 points. Fails jackknife 8/20 (median −2.9 pts), and halt off it is a wash | top candidate, **propose to user** |
| 3 | Construction | **Conviction sizing** of satellites, 40/35/25 by rank, with nearest-share rounding | Passes walk-forward, 4/4 windows, jackknife 14/20, static. Halt off it is +1355% vs +968% with lower MDD. Fails nudges: 5 of the 6 neighbouring weights land on a frozen path | candidate; re-test if the halt changes |
| 4 | Construction | Two satellites | 4/4 windows, jackknife 17/20, halt off +2908% vs +968%. Halt on: freezes 19/21 in the capital sweep, W1 MDD +6.0 | candidate; re-test if the halt changes |
| 5 | Signals | Align the gate with the ranking: gate new entries on trend quality instead of composite momentum (MU: confidence 98%, trend quality 0.07; CRM: confidence below gate, trend quality 0.57) | Ranking and gate currently measure different things | untested, new 10/31 |
| 6 | Signals | Sector tilt by GICS group, not sector (semis vs software) | One "Technology" rank moves every tech name together | untested, new 10/31 |
| 7 | Regime | Cap the sector tilt's effect on held-vs-new asymmetry: apply it only to the tail ranks (top 2 / bottom 2 of 11) | Keeps the rotation signal, removes most of the gate noise | untested, new 10/31 |
| 8 | Harness | Add the 0.3 × dividend yield score term, the breadth caution factor and regime tilts to the harness | Each remaining difference from live is a chance of another false baseline like the tilt | untested, new 10/31 |
| 9 | Ops / design (user) | Shadow-mode tracking: log what each candidate would hold each live scan, next to live | Real out-of-sample evidence without risking capital; needs a small src change | propose to user |
| 10 | Signals | Earnings-drift tilt from real earnings surprises (Finnhub), not the gap proxy tested 10/31 | PEAD is well documented; the proxy was too crude to count | needs finnhub earnings history |
| 11 | Universe | Satellite pool rebuilt by rule each quarter, from size and liquidity rather than recent winners | Reduces the full universe's hindsight | untested |
| 12 | Execution | Gap-up skip at 5% only | Old baseline: WF ok, 3/4 windows, jackknife 11/20 | weak, re-test on new baseline |

## Done
- **2026-10-31** (`exp_1031.py`, `exp_1031b–e.py`, see log). 31 ideas against corrected LIVE, none pass.
  Backlog: trendq satellites + momentum core ✗ (0/4); group cap 2 ✗ (jack 9/20); rank buffer ✗; mom×R² + broad ✗;
  min 2y history ✗ (jack 7/20); defensive core below QQQ 50d ✗ (1/4). New: nearest-share rounding ✗ (no edge halt
  off); cash sweep ✗ (orders ×1.5, W2 MDD +12); core trend floor ✗ (jack 4/20); satellite trend floor ✗; t-stat ✗;
  trendq 63/126/252 blend ✗; beta-residual trendq ✗; group-relative trendq ✗; 21-day confirm ✗ (orders ×3); volume
  ratio ✗; earnings-gap proxy ✗; satellite off on SPY cross / breadth / vol / QQQ 50d ✗ (0–1/4); chase skip 10% ✗
  (0/4); swap margin ✗; weekly scan ✗; half tilt ✗; confidence gate 60 ✗.
- **2026-10-24 run 2** (`exp_1024b/c/d/e`, see log): broad 2020-top-cap pool ✗; sector-ETF pool ✗; broad+ETF ✗;
  126+252 momentum blend ✗ (jack 11/20); 52w-high ✗✗; **trend quality slope×R² — shipped 10/24 by the user's
  decision**; trendq 63/189 ✗; trendq+stop15/band0.5/core50/broad ✗ (static MDD); core = 1 ETF ✗; 4–5 satellites
  ✗✗; gap-up skip ✗ (nudge); 5-day blow-off skip ✗; mom×R² 126 — passes all but jackknife (6/20); mom×R² 252 ✗;
  R² gate 0.3/0.5 ✗.
- See `stock_hypotheses.md` for H1–H21 (band, stop, sector cap, cooldown, momentum windows, SPY200 gate,
  satellite count, min order, ATR/trailing stops, confidence, cadence, halt variants, group/corr caps,
  vol-adjusted ranking, faster exits, inverse-vol sizing, core/sat split, rank buffer, min-hold).
