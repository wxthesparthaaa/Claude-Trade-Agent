# Growth idea backlog (ranked queue)

Every run must add ≥8 ideas and test ≥6 (see README §2). Move tested ideas to "Done" with a one-line verdict
and a pointer to the log entry. Rank = expected impact × testability.

Baseline changed on 2026-10-31: LIVE is now trendq **plus the sector tilt**. Verdicts from before that date were
measured against a baseline that overstated live.

## Queue

| # | Family | Idea | Why it might work | Status |
|---|---|---|---|---|
| 1 | Construction / regime | ~~Index core with a FAST risk-off~~ → **SHIPPED 11/21 as f1** (039bc977): QQQ held above its 200d SMA with a 2% hysteresis band, else cash | Faster SMA (100d) and dual momentum did not fix W2; the hysteresis band did (whipsaw was the cost). Passes every bar check vs current LIVE | **shipped**, see shipped_changes.md |
| 2 | Construction (user) | ~~Index core, 200d switch to SCHD (d4)~~ | Superseded by f1. With the band, SCHD instead of cash (f2) passes vs the new LIVE but fails WF vs the old one | superseded 11/21 |
| 3 | Signals | **Drop the sector tilt from growth's score** | 11/18 vs current LIVE: WF ok, 3/4 windows, static 291% vs 224%, nudge ok, sweep 21/21 on both. Jackknife 9/20 (7/8/15/11 on other seeds) | **re-tested 11/28 under big-bet: ✗** (2/4, jack 8/20, static 591% vs 681%, WF ✗) | ✗ dropped |
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
| 18 | Regime / construction | **Dip-deploy overlay**: when SPY is >=10% below its high AND has reclaimed its 200-day average (or VIX has fallen back from >35), lift the satellite budget / cash cap above normal | 21-Nov study (`dip_buy_study.py`): the 200-day reclaim while -10% down was the best-behaved entry signal (93% positive 1y, n=15, median further fall -4%). Our earlier regime tests were all DE-risking (SPY200, QQQ50, breadth, vol: all fail); this is the mirror image and untested. Needs the 25% halt to let buys through | untested, new 11/21 |
| 18b | Signals | ~~Semis exposure cap while semis trail SPY (20d)~~ | **Tested 11/21 (e5): ✗** 0–1/4 windows, jack 4–6/20, orders ×2 | ✗ dropped |
| 19 | Learn from dividend | ~~Core 50/50 QQQ + SCHD, fixed and held~~ | **Tested 11/21 (e4): ✗** 2/4, W2 MDD +4.2/+9.1, WF picks LIVE/fails; jack 19/20, static 297–319% | ✗ dropped (f1 does it better) |
| 20 | Execution | Stop check on the 09:35 price only after a 15-minute confirmation (skip a stop when the open recovers >5% off the prior close) | 11/6: early scans would have stopped AMD at −23% at the low; the open was −15%. Exits are exhausted, so low priority | untested, new 11/18 |
| 21 | Regime / breadth | **Breadth washout as a dip-deploy / halt-release trigger** (TradingView McClellan osc < -80, High-Low Index 10d SMA < 5) | 11/21 proxy study (`breadth_study.py`): osc < -80 has no edge (3m +3.2% vs +3.3% baseline, n=33); HiLo < 5 is better (3m +8.2%, 75% up, n=12) but not better than VIX>=30 / 200d reclaim and only 12 clusters. Parked: needs real NYSE/Nasdaq breadth data to trust, which is paywalled |
| 22 | Regime (new 11/21) | ~~Core switch, QQQ vs AGG 6-month dual momentum, else SCHD~~ | **Tested 11/21 (e2): ✗** 2/4, W2 MDD +6.4/+11.5; jack 19–20/20 | ✗ dropped |
| 23 | Regime (new 11/21) | ~~Core switch at 100d SMA (to SCHD, e1; to cash, e3b)~~ | **Tested 11/21:** passes vs the new LIVE, fails vs the old (1–2/4, nudges −128/−194); static 206% vs 219% for e3b | ✗ fragile |
| 24 | Selection (new 11/21) | ~~No new satellite with 63d vol > 70%~~ | **Tested 11/21 (e6): ✗✗** full 269% vs 712%, jack 1/20: the volatile names are the return | ✗ dropped |
| 25 | Signals (new 11/21) | ~~Satellites must beat QQQ 126/21 momentum by 5%~~ | **Tested 11/21 (e7): ✗** almost never binds (0/4, identical windows) | ✗ dropped |
| 26 | Construction (new 11/21) | ~~d4 with core 50% / sat 50%~~ | **Tested 11/21 (e8): ✗** 2/4, nudges fail, jack 4–16/20 | ✗ dropped |
| 27 | Construction (new 11/21) | **Park risk-off core cash in a T-bill ETF** (BIL/SGOV) instead of idle cash | f1 leaves 40% in cash for months (2022: ~10 months); ~4–5%/yr on $1.5k ≈ $60/yr vs 2 orders × $2.98 per switch. Needs BIL bars | moot since 11/24 big-bet (no core, ~no idle cash) | parked |
| 28 | Construction (new 11/21) | **f1 with VOO+QQQ or VOO as the risk-on core** (broader, dividend-like) | d2 (VOO+QQQ held) had 20/20 jackknife and +407% static; the band may fix its W2 cost too | moot since 11/24 (core off) | parked |
| 29 | Execution (new 11/21) | **Staged satellite entries**: half the target now, the rest after 5 sessions if still a target | 11/9 MRVL and 11/13 ASX top-ups were bought into a falling tape; halves the cost of a fresh pick that fails fast. Costs one extra order | **Tested 11/28 (k9): ✗** 0/4, jack 2/20 | ✗ dropped |
| 30 | Signals / regime (new 11/21) | **While f1 is risk-off, new satellites need a positive 21d return** | Satellites still enter in a bear (MRVL 11/9, ASX top-up 11/13); a short-term confirmation only when the index is below trend | **Tested 11/28 (k3): ✗** 1/4, jack 2/20 | ✗ dropped |
| 31 | Ops (new 11/21) | **Shadow-log f1 vs pre-f1 core each scan** (what the trend-ranked core would hold) | Gives the 4-week rollback check real numbers instead of a harness replay | untested, small src change |
| 32 | Universe (new 11/28) | **No single-commodity futures ETFs (USO, UNG) as growth satellites** (m2) | Roll decay in contango: their trends are supply-shock spikes that mean-revert; LIVE's own UNG/USO trades lost ~$9.6k static / ~$15.7k full. 11/28: static 1034% vs 681%, 21/21 capital paths + 4/4 starts on BOTH universes, jack 16/20, nudges ok; **fails WF** (IS trades flat) and windows 2/4 (W2 MDD +5.9) | **candidate #1, propose to user** |
| 33 | Universe (new 11/28) | No UNG only (m1) | Smaller version of #32. 11/28: full 15,941% vs 13,322%, static 940%, jack 14/20, nudge ok; windows 1/4 (W3 tie), WF ✗ | candidate #2 |
| 34 | Ops / design (new 11/28) | **Shadow-log #32**: each scan, record what growth would hold without USO/UNG | Live out-of-sample evidence for the walk-forward gap, no capital at risk | untested, small src change, propose |
| 35 | Universe (new 11/28) | Swap commodity futures ETFs for equity sector ETFs (XLE for energy, XME/COPX for metals) | Keeps commodity-cycle exposure without the roll; equities trend more smoothly | untested; needs bars |
| 36 | Signals (new 11/28) | Roll-cost-adjusted trend quality for futures ETFs (trendq minus the trailing 12m ETF-vs-spot gap) | Same mechanism as #32, as a penalty instead of a ban | untested; needs spot data |
| 37 | Ops (new 11/28, user) | **order_execution: book only confirmed fills**; re-check non-FILLED orders on the next scan instead of debiting the sizing estimate | Dividend lost ~$8.6k of phantom cash to two rejected XOM buys (11/23, 11/24); growth uses the same code | **needs the user** (order_execution is off-limits) |
| 38 | Ops (new 11/28, user) | Drop a symbol from the universe after Tiger rejects it with "can only be closed" | XOM retried on two days and failed both | needs the user (dividend) |
| 39 | Execution (new 11/28) | ~~No top-up into a held name >10% below cost~~ (k2) | 11/23 AMD top-up decision 1 day before its stop | **Tested 11/28: ✗** 1/4, jack 4/20 |
| 40 | Signals (new 11/28) | ~~Entry only within 15% of the 63d high~~ (k8) | Avoid buying a broken trend that still ranks on 126d | **Tested 11/28: ✗✗** 0/4, jack 2/20 |
| 41 | Construction (new 11/28) | ~~Three satellites / group cap 1 / corr cap 0.7 under big-bet~~ (k10, k4, k5) | Diversify the 2 big bets | **Tested 11/28: ✗✗** 0–1/4, jack 2–5/20 |
| 42 | Regime (new 11/28) | ~~Half the satellites to cash below SPY 200d~~ (k6) | Big-bet has no halt now | **Tested 11/28: ✗** 0/4, jack 4/20 |
| 43 | Signals (new 11/28) | ~~Trend window 189d~~ (k7), ~~rank buffer 1~~ (n2), ~~swap margin~~ (n3) | Less churn between ranks 2 and 3 | **Tested 11/28: ✗✗** 0/4 each |
| 44 | Exits (new 11/28) | Stop 15% under big-bet (n4) | Each stop costs ~10% of equity now. 11/28: MDD 59 vs 62 full, 51 vs 58 static, return flat; jack 8/20, windows 1/4 | candidate #3, weak |

## Done
- **2026-11-28** (`exp_1128*.py`, see log). 14 ideas + 3 variants against LIVE big-bet (halt off). None pass. Best: no USO/UNG
  satellites (#32) -- 21/21 capital paths and 4/4 starts on both universes, jack 16/20, static 1034% vs 681%, but walk-forward picks LIVE
  (the losses are all after 2023) and windows 2/4. ✗: commodity ban (all 6), no-add-to-losers, risk-off 21d confirm, group cap 1, corr cap,
  half sats below SPY200, trendq 189d, near-63d-high entry, staged entry, three sats, drop tilt, rank buffer, swap margin, stop 15%.
- **2026-11-21** (`exp_1121.py`, `exp_1121b.py`, see log). 12 configurations from 11 ideas, each against BOTH the new LIVE
  (`halt_mode='exits_ok'`, the user's 11/21 change) and the old one. **f1 shipped** (QQQ above 200d SMA ±2% band, else cash):
  passes every check vs the new LIVE (and all but the 240d nudge vs the old); capital sweep 21/21 both universes; jack 20/20 on
  5 seeds. f2 (band, SCHD) passes vs new, fails WF vs old; f3 (4% band) passes vs new, fails nudges vs old. ✗: e1/e3b 100d
  switch (fragile), e2 dual momentum (W2), e3 cash-200d no band (W2 +6.7 vs old), e4 QQQ+SCHD fixed (W2), e5 semis cap, e6 vol
  cap, e7 RS vs QQQ, e8 core 50%.
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
