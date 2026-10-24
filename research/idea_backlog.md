# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | Signals | Trend quality (slope×R²) for the **satellite sleeve only**; core keeps live momentum | trendq's static-universe drawdown may come from it re-ranking the core ETFs | untested (follow-up of 10/24 #1) |
| 2 | Signals | trendq + GICS group cap 2 | trendq's full-universe win is real; cap the semis clustering that hurts static W4 | untested |
| 3 | Signals | trendq + rank-hold buffer 1 | both cut churn; check they stack | untested |
| 4 | Signals | mom×R² with a larger satellite pool (fix jackknife 6/20 dependence) | passed every check except the jackknife | untested |
| 5 | Ops / design (user) | **Shadow-mode tracking**: log what trendq would hold each live scan, next to live | gets real out-of-sample evidence without risking capital; needs a small src change | propose to user |
| 6 | Design (user) | Halt path-dependence dominates full-universe results (tq151: 1,081 halted days → −922 pts) | every verdict on the live setup is noisy because of it; any halt change is the user's call | propose to user |
| 7 | Regime | Satellite sleeve to core when breadth (regime.json) is weak or SPY 50<200 | momentum crashes cluster in bear rebounds | needs breadth history in the harness |
| 8 | Signals | Earnings-drift tilt (post-earnings-surprise bonus for 60 days) | PEAD is well documented | needs finnhub earnings history |
| 9 | Universe | Liquidity / history filter for auto-adds (min 2y bars) | short-history names can't be scored properly | untested |
| 10 | Execution | Gap-up skip at 5% only (the 3% nudge collapsed via the halt) | WF ok, 3/4 windows; jackknife 11/20 | weak, low priority |
| 11 | Learn from dividend | Dividend's edge since 9/21 is low beta in a tech pullback (QQQ −5%), not mechanism; test a defensive core (SCHD/VYM) when QQQ < 50d | turn the dividend observation into a regime rule for the core | untested |
| 12 | Construction | Satellite count 2 (concentration) on the live setup | 4–5 satellites failed badly; test the other direction | untested |

## Done
- **2026-10-24 run 2** (`exp_1024b/c/d/e`, see log): broad 2020-top-cap pool ✗; sector-ETF pool ✗; broad+ETF ✗;
  126+252 momentum blend ✗ (jack 11/20); 52w-high ✗✗; **trend quality slope×R² — top candidate, fails static
  MDD and 151-day nudge (halt artefact)**; trendq 63/189 ✗; trendq+stop15/band0.5/core50/broad ✗ (static MDD);
  core = 1 ETF ✗; 4–5 satellites ✗✗; gap-up skip ✗ (nudge); 5-day blow-off skip ✗; mom×R² 126 — passes all
  but jackknife (6/20); mom×R² 252 ✗; R² gate 0.3/0.5 ✗.
- See `stock_hypotheses.md` for H1–H21 (band, stop, sector cap, cooldown, momentum windows, SPY200 gate,
  satellite count, min order, ATR/trailing stops, confidence, cadence, halt variants, group/corr caps,
  vol-adjusted ranking, faster exits, inverse-vol sizing, core/sat split, rank buffer, min-hold).
