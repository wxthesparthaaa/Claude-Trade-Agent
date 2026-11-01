# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

Baseline changed on 2026-10-31: LIVE is now trendq **plus the sector tilt**. Verdicts from before that date were
measured against a baseline that overstated live.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | All | **Re-run the shortlist (#2–#4) through the full bar against the new LIVE** (60-day restart) | In the capital sweep under the restart: drop tilt 21/21 and 21/21, two satellites 21/21 and 21/21, conviction 21/21 and 11/21 (full and static). The sweep isn't the bar | next run, first job |
| 2 | Signals | **Drop the sector tilt from growth's score** (`scoring_weights` without `sector_tilt`, a one-line change) | Capital sweep beats LIVE 21/21 on full and 20/21 on static, and never freezes on full. A 20-day ETF rotation shifts the entry gate by ±0.1, which is the same as moving the momentum bar by ±17 points. Fails jackknife 8/20 (median −2.9 pts), and halt off it is a wash | top candidate, **propose to user** |
| 3 | Construction | **Conviction sizing** of satellites, 40/35/25 by rank, with nearest-share rounding | Passes walk-forward, 4/4 windows, jackknife 14/20, static. Halt off it is +1355% vs +968% with lower MDD. Fails nudges: 5 of the 6 neighbouring weights land on a frozen path | candidate; re-test if the halt changes |
| 4 | Construction | Two satellites | 4/4 windows, jackknife 17/20, halt off +2908% vs +968%. Halt on: freezes 19/21 in the capital sweep, W1 MDD +6.0 | candidate; re-test if the halt changes |
| 5 | Signals | Align the gate with the ranking: gate new entries on trend quality instead of composite momentum (MU: confidence 98%, trend quality 0.07; CRM: confidence below gate, trend quality 0.57) | Ranking and gate currently measure different things | untested, new 10/31 |
| 6 | Signals | Sector tilt by GICS group, not sector (semis vs software) | One "Technology" rank moves every tech name together | untested, new 10/31 |
| 7 | Regime | Cap the sector tilt's effect on held-vs-new asymmetry: apply it only to the tail ranks (top 2 / bottom 2 of 11) | Keeps the rotation signal, removes most of the gate noise | untested, new 10/31 |
| 8 | Harness | Add the 0.3 × dividend yield score term, the breadth caution factor and regime tilts to the harness | Each remaining difference from live is a chance of another false baseline like the tilt | untested, new 10/31 |
| 9 | Ops / design (user) | Shadow-mode tracking: log what each candidate would hold each live scan, next to live | Real out-of-sample evidence without risking capital; needs a small src change | propose to user |
| 10 | Signals | ~~Earnings-drift tilt from real earnings surprises~~ | **Tested 11/01, no drift, fails the bar** (`earnings_surprise_study.py`, `exp_1101.py`): see Done | ✗ dropped |
| 11 | Universe | Satellite pool rebuilt by rule each quarter, from size and liquidity rather than recent winners | Reduces the full universe's hindsight | untested |
| 12 | Execution | Gap-up skip at 5% only | Old baseline: WF ok, 3/4 windows, jackknife 11/20 | weak, re-test on new baseline |
| 13 | Signals | ~~Real earnings-date blackout for NEW satellite entries~~ | **Tested 11/01, fails the bar and the premise** (`earnings_blackout_check.py`): see Done | ✗ dropped |
| 14 | Signals | **Fundamental quality screen on satellites**: positive TTM EPS, YoY revenue growth > 0, operating margin not falling, using SEC XBRL facts with their `filed` dates (point-in-time) | Small caps like AEHR/ALAB are the stop-out source; trader-analyst's TTM/YoY/margin table is the template. Point-in-time is possible because XBRL gives filing dates | untested, new 11/01; heavy build |
| 15 | Reporting | **R-multiple expectancy** in the weekly review: R = realized P&L / (entry x qty x stop%), avg R, hit rate vs break-even hit rate 1/(1+payoff) | day-trader-skill's "honest odds" framing; shows at a glance whether the edge is real (baseline: 58% hit rate vs ~71% break-even = negative) | **built 11/01** (`trade_stats.py`, weekly summary) -- baseline: growth -0.21R over 15 trades, 53% hit rate vs 80% needed |
| 16 | Ops / risk (user) | **Event guard**: block new entries / flag held names with a fresh SEC 8-K of Item 1.03 (bankruptcy), 2.04 (debt acceleration), 3.01 (delisting), 4.02 (non-reliance on financials) | Rare, protective, free data, SEC adapter already exists. Not backtestable (too rare) | propose to user |
| 17 | Ops / design (user) | **Resting protective stops** (broker-side stop per position) to cover the ~24 h between US scans | Stops are only checked at scan times. Low expected value: the 20% stop binds ~14 times in 6.5 yrs. Touches order mechanics | propose to user, low priority |

## Done
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
