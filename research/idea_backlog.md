# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | Universe | Rebuild the satellite pool beyond semis: add non-semi growth leaders (e.g. software, internet, industrial/defense, healthcare growth names) and let momentum choose | 15/16 auto-adds were semis, and all 3 satellites fell together in Oct 2026. A broader pool gives momentum real choices | untested |
| 2 | Signals | 12-1 month momentum blended with 6-1 (252/21 + 126/21) | 12-1 is the best-documented momentum horizon; the blend may cut whipsaw vs 126 alone | untested (189/252 alone were worse in 2022) |
| 3 | Signals | 52-week-high proximity as a ranking term | George-Hwang anomaly: names near their 52w high keep drifting up, with less crash risk than raw momentum | untested |
| 4 | Signals | Trend quality: rank by slope × R² of 126d log price | Smooth trends persist more than jumpy ones; it penalizes one-spike names like AEHR | untested |
| 5 | Construction | Core sleeve = QQQ only, vs a 2-ETF core | Concentrating the core in the highest-momentum broad ETF; the dividend benchmark is beating growth's core | untested |
| 6 | Learn from dividend | Compare dividend's turnover, holdings count and fee drag vs growth; test growth with 4–5 smaller satellites | Dividend holds more names with lower turnover and is performing better | untested |
| 7 | Execution | Skip new entries on a gap-up > X% at the open | Buying at the open after a big gap fills at the worst price | untested |
| 8 | Signals | Short-term reversal filter: don't enter a name up >15% in the last 5 days | Avoids buying blow-off tops | untested |
| 9 | Regime | Satellite sleeve to core when breadth (regime.json) or SPY 50<200 | Momentum crashes cluster in bear rebounds; SPY200 alone didn't help, so test breadth | untested |
| 10 | Construction | Rank buffer only within the same GICS group (swap semis for semis only when clearly better) | buf1 cut orders 50% and won on full, but failed on static | follow-up of H18 |
| 11 | Signals | Earnings-drift tilt: post-earnings-surprise names get a score bonus for 60 days | PEAD is a well-documented anomaly; finnhub data exists | needs data |
| 12 | Universe | Liquidity / history filter for auto-adds (min 2y bars, min $ volume) | Short-history names (SKHY, ALAB) can't be scored properly | untested |

## Done
- See `stock_hypotheses.md` for H1–H21 (band, stop, sector cap, cooldown, momentum windows, SPY200 gate,
  satellite count, min order, ATR/trailing stops, confidence, cadence, halt variants, group/corr caps,
  vol-adjusted ranking, faster exits, inverse-vol sizing, core/sat split, rank buffer, min-hold).
