# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

Baseline changed on 2026-10-31: LIVE is now trendq **plus the sector tilt**. Verdicts from before that date were
measured against a baseline that overstated live.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | Construction / regime | **Index core with a FAST risk-off**: core = QQQ (or VOO+QQQ) held through momentum dips, switching to SCHD/AGG on QQQ < 100d SMA, or on 6-month QQQ-vs-AGG dual momentum | d4 (200d switch to SCHD) gets jackknife 20/20, static 340% vs 224% with lower MDD, nudges ok, but W2 (2022) MDD +8.2 and WF picks LIVE. Needs ≥3.2 pts less W2 drawdown | **next run, first job**; new 11/18 |
| 2 | Construction (user) | **Index core, 200d switch to SCHD (d4), accepting the bear-market cost** | See 11/18 log: +116 pts static, 20/20 jackknife, but W2 −10.8 pts and MDD +8.2 | top candidate, **propose to user** |
| 3 | Signals | **Drop the sector tilt from growth's score** | 11/18 vs current LIVE: WF ok, 3/4 windows, static 291% vs 224%, nudge ok, sweep 21/21 on both. Jackknife 9/20 (7/8/15/11 on other seeds) | candidate, **propose to user** |
| 4 | Construction | **Conviction sizing** 40/35/25 by rank + nearest-share rounding | 11/18: WF ok, 4/4, jackknife 15/20 (14–18 on other seeds), static ok; nudges −420 / +449; static sweep only 10/21 | candidate |
| 4b | Signals | Slow sector tilt (63d ROC) + walk-forward re-tune of the lookback | 11/18: 3/4, jack 15/20, static 281%, but 50d −109 and WF picks LIVE | weak; re-test with a wider grid |
| 4c | Construction | Two satellites | 11/18: 4/4 but W1 MDD +6.0, jack 17/20, static 298%; 5/21 sweep paths halted >300 days | parked |
| 5 | Signals | ~~Gate new entries on trend quality~~ | **Tested 11/18: ✗** (2/4, W2 MDD +10.9, jack 9/20) | ✗ dropped |
| 6 | Signals | Sector tilt by GICS group, not sector (semis vs software) | One "Technology" rank moves every tech name together | untested, new 10/31 |
| 7 | Regime | ~~Sector tilt on the tail ranks only~~ | **Tested 11/18: ✗** (1/4, jack 7/20) | ✗ dropped |
| 8 | Harness | Add the 0.3 × dividend yield score term, the breadth caution factor and regime tilts to the harness | Each remaining difference from live is a chance of another false baseline like the tilt | untested, new 10/31 |
| 9 | Ops / design (user) | Shadow-mode tracking: log what each candidate would hold each live scan, next to live | Real out-of-sample evidence without risking capital; needs a small src change | propose to user |
| 10 | Signals | ~~Earnings-drift tilt from real earnings surprises~~ | **Tested 11/01, no drift, fails the bar** (`earnings_surprise_study.py`, `exp_1101.py`): see Done | ✗ dropped |
| 11 | Universe | Satellite pool rebuilt by rule each quarter, from size and liquidity rather than recent winners | Reduces the full universe's hindsight | untested |
| 12 | Execution | ~~Gap-up skip at 5%~~ | **Re-tested 11/18: ✗** (1/4, jack 11/20, nudges fail) | ✗ dropped |
| 13 | Signals | ~~Real earnings-date blackout for NEW satellite entries~~ | **Tested 11/01, fails the bar and the premise** (`earnings_blackout_check.py`): see Done | ✗ dropped |
| 14 | Signals | **Fundamental quality screen on satellites**: positive TTM EPS, YoY revenue growth > 0, operating margin not falling, using SEC XBRL facts with their `filed` dates (point-in-time) | Small caps like AEHR/ALAB are the stop-out source; trader-analyst's TTM/YoY/margin table is the template. Point-in-time is possible because XBRL gives filing dates | untested, new 11/01; heavy build |
| 15 | Reporting | **R-multiple expectancy** in the weekly review: R = realized P&L / (entry x qty x stop%), avg R, hit rate vs break-even hit rate 1/(1+payoff) | day-trader-skill's "honest odds" framing; shows at a glance whether the edge is real (baseline: 58% hit rate vs ~71% break-even = negative) | **built 11/01** (`trade_stats.py`, weekly summary) -- baseline: growth -0.21R over 15 trades, 53% hit rate vs 80% needed |
| 16 | Ops / risk (user) | **Event guard**: block new entries / flag held names with a fresh SEC 8-K of Item 1.03 (bankruptcy), 2.04 (debt acceleration), 3.01 (delisting), 4.02 (non-reliance on financials) | Rare, protective, free data, SEC adapter already exists. Not backtestable (too rare) | propose to user |
| 17 | Ops / design (user) | **Resting protective stops** (broker-side stop per position) to cover the ~24 h between US scans | Stops are only checked at scan times. Low expected value: the 20% stop binds ~14 times in 6.5 yrs. Touches order mechanics | propose to user, low priority |
| 18 | Signals | Semis exposure cap by sleeve weight (≤ 1 semi among satellites while the semis group's 20d return is below SPY's) | 11/6: MU stop, AMD/ASX at −23% on the close, then MRVL bought 3 days later. Group cap 2 and group cooldown both failed, so this is a regime-conditioned version | untested, new 11/18 |
| 19 | Learn from dividend | Core sleeve 50/50 QQQ + SCHD, fixed and held, annual-ish rebalance via the 20% band | Dividend's broad, low-turnover book beat growth by 11 pts over 11/2–11/17; d2 (VOO+QQQ) got 20/20 jackknife | untested, new 11/18 |
| 20 | Execution | Stop check on the 09:35 price only after a 15-minute confirmation (skip a stop when the open recovers >5% off the prior close) | 11/6: early scans would have stopped AMD at −23% at the low; the open was −15%. Exits are exhausted, so low priority | untested, new 11/18 |

## Done
- **2026-11-18** (`exp_1118.py`, `exp_1118b–d.py`, see log). 26 configurations from 16 ideas, against LIVE with the
  60-day restart, END 11/18. None pass. Index core: QQQ held (d1) ✗ W2; VOO+QQQ held (d2) ✗ W2; QQQ/SCHD 200d switch (d4)
  ✗ W2 MDD +8.2 and WF, otherwise strong → queue #1/#2; QQQ/AGG switch (d3) ✗; gated index cores (c1–c3, c5) ✗; QQQ core
  + mom exit −10% (c6) ✗ confounded; sector ETFs as core ✗ (0/20); falling-knife skip ✗ (0/4); liquidity floor $50M ✗
  (0/20); group cooldown ✗ (0/4); trend-quality gate ✗; tilt tail ✗; gap-up 5% ✗; slow tilt 63d ✗ (fragile nudge, WF);
  drop tilt ✗ jackknife only; conviction ✗ nudge only; two satellites ✗.
- **2026-11-01 earnings-surprise drift (#10)** -- real EPS from Tiger's calendar (`fetch_earnings.py` now keeps `expected_eps`/
  `actual_eps`; 1,127 usable reports, 51 symbols), harness `score_mode='tq_eps'` / `eps_veto` (off by default; `tq_eps` with a
  zero bonus reproduces LIVE exactly: 1413.19%, 392 orders). **Event study: no drift.** Beat-minus-miss excess spread vs SPY:
  20d +1.6% (t 1.15) static / -0.5% full; 60d -0.7% static / -7.5% full (t -1.47); Spearman(surprise, 60d excess) = -0.02
  (n=507). The biggest misses did best afterwards (full: +17.4% xs60, n=54). All groups beat SPY (+5-7% xs60): that is the
  satellites' trend, not the surprise. **Ship bar:** tilt magnitude 0.10/0.20/0.30 -> jackknife 7/20, nudges -17/-49 pts,
  walk-forward OOS 302% vs 351% FAIL; tilt sign -> jack 9/20, nudges -150/-195 pts, WF FAIL; miss veto 5/10/20% -> full
  1019% vs 1413%, windows 1/4, jack 2/20 (blocking entries after a miss HURTS). Static looks better (319%/287% vs 244%) but
  not robust. Caveats: ~24 hindsight-picked large caps with a 73% beat rate (PEAD is a cross-sectional effect over thousands
  of stocks, so this has little power and does not refute it in general); Tiger's EPS basis (GAAP vs adjusted) is unverified;
  report dates cluster in seasons so t-stats are optimistic. Verdict: drop; do not test the inverse (contrarian) tilt, that
  would be mining the event study (t -1.5).
- **2026-11-01 earnings blackout (#13)** -- `fetch_earnings.py`, `earnings_blackout_check.py`, harness `Params.earn_blackout`
  (off by default). Earnings gaps are real: median |gap| 4.4% vs 0.6% on a normal day, 14-18% of reactions exceed 10%.
  But (a) a down-gap past the 20% stop is rare: 0.4% of reactions (static) / 1.0% (full); (b) stop-outs are not an
  earnings story: 0 of 8 (static), 3 of 13 (full) spanned one, and 2-3 of the 10 worst trips; (c) trips that HELD THROUGH
  earnings are the profit engine (static n=35 +$13.1k, win 69%; the rest n=67 -$3.7k), so de-risking before earnings would
  cut winners; (d) the filter as specified only touches entries within 5 sessions before a report: 7 (static) / 10 (full)
  trips in 6.6 years. Ship bar: windows 2/4, jackknife 9/20, nudges FAIL, walk-forward no pick; static neutral
  (245% vs 244%). Verdict: noise, drop. Caveats: 237 of 1,422 report dates have no before/after label (treated as after
  close); reaction-day timing is daily-bar based; the near-earnings sample is tiny.
- **2026-11-01** (user-requested review of the `day-trader-skill` pack, 11 intraday skills; `fill_timing_check.py`).
  Its signal ideas were already tested here and failed (breakout / 52w-high ✗✗, volume ratio ✗, ATR + trailing stops ✗,
  gap-up and chase skips ✗, faster exits ✗, inverse-vol sizing ✗). **Execution timing** (it avoids the first 15 min; we
  scan at 09:35 ET): 93 real open-window fills vs the 10:00-10:30 VWAP = -0.18% (s.e. 0.06%), i.e. no opening penalty.
  CAVEAT: Tiger PAPER fills are simulated, so real spread cost can't be measured here; revisit if/when live. The open's
  5-min range is 2x mid-morning (0.58% vs 0.27%). Not assimilable: intraday ORB scanning, Monte-Carlo day replay,
  3-trades/day sizing, Alpaca broker gating, congressional-trade feed. New ideas #13-#17 above.
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
