# Claude Trading Agent — Development Log

Chronological record of every notable change since this project started,
newest first is NOT the order here -- entries run oldest to newest so the
story reads start to finish. Linked from the dashboard's collapsed
"Developer Notes" panel, which shows only the 5 most recent single-line
entries; this file is the full history.

---

## 2026-07-26 — Initial build: an options-strategy backtester

**Problem**: No system existed yet. The original goal was an automated
options-income strategy for a Tiger Brokers account.

**Solution**: Built the first working pipeline in one session -- a risk
engine with hard position/drawdown limits and an income-target
calculation, a strategy layer for candidate generation and portfolio
selection, and a backtest engine driven by free historical stock data
plus a Black-Scholes pricer for the options leg. Confirmed real Tiger
API connectivity end to end before building anything further on top of
assumptions.

---

## 2026-07-31 — Pivot to stocks/ETFs, add the Telegram/execution pipeline

**Problem**: Options pricing/margin mechanics added complexity that
wasn't paying for itself relative to a simpler equity strategy, and
there was no way yet to actually place or report on trades.

**Solution**: Pivoted the whole strategy layer from options to a
multi-market stock/ETF approach. Added the order execution module
(paper account, dry-run by default -- no live order without an explicit
flag) and the daily/weekly Telegram notification pipeline with its own
scheduling.

---

## 2026-08-01 — Real news signal, ledger accuracy

**Problem**: The strategy had no sentiment input, and the tracked ledger
didn't distinguish cash reserve from invested capital, making real P&L
hard to reason about after a trade.

**Solution**: Added a real news-tilt signal (documented the accepted
automation-risk tradeoff explicitly rather than leaving it implicit).
Added order-placement Telegram notifications and proper cash-reserve
ledger tracking.

---

## 2026-08-04 — Deployed to the cloud

**Problem**: Everything ran locally only -- no always-on dashboard, no
scheduled Telegram sends independent of a laptop being on.

**Solution**: Deployed to Render.com with a read-only dashboard and
cloud-side Telegram scheduling. Since Render's free tier wipes local
disk on every redeploy, added a periodic GitHub state re-pull so the
dashboard reflects trades placed locally, and untracked the generated
state files from normal git history (they're synced through the GitHub
Contents API instead, not committed like source code).

---

## 2026-08-06 — Automated scan/approval workflow

**Problem**: Trade candidates existed only as backtest output -- there
was no live daily scan or a human-approval step before a real order.

**Solution**: Added COT positioning signals, the automated scan +
pending-approval workflow (score today's candidates, log the rationale,
require a click before any real order), and renamed the project to
"Claude Trading Agent" to match what it had become.

---

## 2026-08-08 — Live dashboard accuracy, shorting, the dividend portfolio

**Problem**: A cluster of real-usage bugs: the dashboard wasn't showing
live data correctly, cash_reserve had drifted out of sync with Tiger's
actual order history, and the strategy had no way to express a bearish
view or a second, income-focused portfolio.

**Solution**: Fixed the live dashboard data path, added tactical
shorting (gated on an actual macro signal, not just any price
weakness) and a market-breadth signal to inform it. Reconciled
cash_reserve against Tiger's real order history to correct the drift,
and activated the dividend portfolio for paper trading with its own
on-demand news and trade-implications summary. Made missing GitHub
credentials a loud failure before any real trade, rather than a silent
one. Added a market trading-hours footer (US/HK/SG, converted to
Singapore time) so the dashboard shows at a glance whether markets are
actually open.

---

## 2026-08-10 — Confidence gating, the trading journal, Finnhub news

**Problem**: Every scored candidate was treated the same regardless of
how confident the score actually was, and there was no durable record
of real fills (price, quantity, realized P&L) separate from the
day-by-day scoring rationale.

**Solution**: Added confidence-gated trading (a sigmoid score-to-
confidence mapping, execute/shortlist/reject thresholds), a shortlist
watchlist for candidates re-scored on every scan, a settings panel, and
a real trading journal. Fixed a real bug where the confidence gate was
force-selling an already-held position that dipped below the execute
threshold, instead of just leaving it to compete normally. Added
Finnhub as the primary news source with keyword-based polarity tagging
(replacing a weaker earlier signal), per-position Close/Reduce-by-N
dashboard actions, and expanded the growth universe from 15 to 27
candidates. Also removed a `trade_journal.xlsx` that had been
accidentally pushed here by a misconfigured local environment variable
from a different project.

---

## 2026-08-11 to 2026-08-13 — Universe growth, Asia-hours coverage, data fixes

**Problem**: The dividend universe was too thin (7 symbols) for real
diversification, SG/HK-hours opportunities were invisible to a scan
that only ran after those markets closed, and the growth universe
crossing 20 US symbols broke Tiger's dividend-data batch request
entirely (a single oversized request fails for the whole market, not
just the extra symbols).

**Solution**: Expanded the dividend universe from 7 to 16 candidates.
Added a second daily scan timed for SG/HK trading hours with its own
Telegram alert, and commodity ETFs to the growth universe as a
retail-accessible alternative to real futures (which this account isn't
permissioned for). Fixed the dividend-data fetch by chunking requests
to stay under Tiger's per-request symbol cap. Iterated on the
dashboard's shortlist display (tried a name+ticker dropdown, reverted
to the original ticker/sleeve/confidence format per feedback, kept a
separate name+ticker digest for Telegram only).

---

## 2026-08-15 — Dividend feature parity, self-improvement, weekend-notification fixes

**Problem**: A full day of connected work. The dividend portfolio's
dashboard was missing most of the growth portfolio's own feature set
(settings, autopilot, shortlist, weekly review, a monthly-gain card);
neither portfolio had any mechanism to actually act on a losing
streak; the two scan jobs and the daily Telegram digest were firing on
weekends when no market was open; a real bug had been miscounting a
deliberate capital reset as a huge trading gain; the "Scan Now" button
had no guard against firing while every relevant market was closed; and
the landing page defaulted to the growth portfolio with no way to see
both portfolios' health at a glance.

**Solution**:
- Fixed capital resets being miscounted as trading gains (tagged reset
  entries, added a reset-aware trailing-window baseline used by both
  the dashboard's monthly-gain card and the weekly review).
- Added the monthly-gain-vs-target card itself, then ported the entire
  confidence-gated pipeline (settings, autopilot default-off, shortlist,
  weekly review, its own 10%/year target vs. growth's 10%/month) to the
  dividend portfolio, using dividend's own per-profile state files
  throughout so growth and dividend never cross-contaminate.
- Restricted the two scan jobs to weekdays only, then found and fixed
  the same gap in the daily Telegram digest -- both the in-app
  scheduler AND the function itself now check whether any relevant
  market actually trades today, since an external OS-level scheduler on
  this machine was calling the underlying function directly and
  bypassing the in-app scheduler's own day-of-week restriction entirely.
- Added a mechanical, downside-only self-improvement loop mirroring the
  sibling Forex Agent project: a symbol that closes net-negative for 3
  traded weeks running is auto-paused from new entries for 2 weeks, then
  resumes with a fresh history -- computed weekly per profile from real
  trade-journal closed trades, never blocks exiting a position already
  held.
- Added a real market-hours guard to the "Scan Now" button, so it
  refuses (with an explanatory message) rather than running uselessly
  when every relevant market is closed.
- Made the combined portfolio overview (both portfolios' capital, gain
  vs. target, pending/paused counts, and a one-line summary per open
  position) the default landing page instead of implicitly favoring
  growth.

---

## 2026-08-16 — Sector rotation, US Investment Clock, opportunistic universe expansion

**Problem**: The growth universe was stuck narrow -- 9 of 10 US satellite
single-stocks were tech/tech-adjacent, so the algo structurally couldn't
find an opportunity outside tech even when one existed elsewhere. There
was also no way to see, at a glance, which sector or region money was
actually rotating into.

**Solution**:
- Added `sector_rotation.py`: ranks US sectors by relative strength via
  the 11 SPDR sector ETFs vs. SPY (reusing `market_breadth.py`'s own
  ratio/ROC pipeline), and HK sectors via GICS-tag-aggregated momentum
  across whatever HK stocks get scanned that week -- coarser, and
  labeled as such on the dashboard. SG gets no sector ranking: live
  testing confirmed Tiger's API doesn't support GICS classification for
  SG symbols at all, so the dashboard says so plainly instead of
  fabricating a number.
- Added `fred_adapter.py` + `investment_clock.py`: a real, unauthenticated
  FRED feed (Industrial Production for growth, 10-Year Breakeven
  Inflation for a fresher-than-CPI inflation read) driving a classic
  Recovery/Overheat/Stagflation/Reflation Investment Clock, US-only --
  HK/SG explicitly have no free macro data of usable quality for this.
- Added `tiger_industry_adapter.py` + `sector_suggestions.py`: turns the
  top-ranked sector into real, liquid, sector-matched trade candidates
  via Tiger's screener intersected with GICS sector membership --
  deliberately never mixes Tiger's own scanner sector tags with GICS
  ids after confirming live that they're incompatible taxonomies.
- Added `universe_extra.py` and `effective_universe()`: a human clicks
  "Add to universe" on a suggestion, it's validated against both
  profiles' universes for overlap, persisted, and picked up by the
  very next scan with no restart -- the original static universe list
  stays untouched so the one-time import disjointness check still
  means what it says.
- Added a small, bounded sector-heat tilt to composite scoring (same
  shape as the existing news tilt) and a daily scheduled job that
  refreshes all of the above every weekday morning, each stage
  independent so a FRED timeout never blocks the sector ranking or
  suggestions from updating.
- Live-verified end to end against real Tiger + FRED data: real US/HK
  rankings, 18 real liquid Technology/Financials suggestions, and a full
  add-to-universe-then-remove round trip confirmed the addition reaches
  `effective_universe()` immediately, with no scan or restart triggered
  as part of verification to avoid touching the live paper account.

---

## 2026-08-17 — Fixed autopilot/approve submitting orders outside a symbol's own market hours

**Problem**: A scan run during HK/SG hours (US closed) found a US
candidate; autopilot tried to place a market order for it anyway, and
Tiger rejected it with "Market order is only available during regular
trading hours (09:30-16:00 ET)" -- confirmed directly from Render's
access logs. That single rejection propagated out of the execution
loop and aborted the *entire* scan, losing the pending-approval record
for every candidate in that run, not just the US one. The existing
"any market open" guard on Scan Now was actually working correctly
(it only ever promised that SOME relevant market was open, by
design) -- the real gap was one level deeper: nothing checked whether
each INDIVIDUAL instruction's own market was open before submitting it.

**Solution**:
- `_run_and_persist_scan` now filters `approved_instructions`
  per-symbol before autopilot execution -- only what's tradeable right
  now gets submitted to Tiger; anything else stays a pending approval
  (not executed, not lost) for a later scan to pick up once its market
  opens.
- `/approve/<id>` (the manual approval click) gets the same per-symbol
  check, returning a clear message instead of letting the same Tiger
  exception surface as an unhandled 500.
- `order_execution.execute_instructions`'s placement loop no longer
  lets one instruction's rejection abort the batch -- orders already
  placed before it still get their ledger/journal update, closing a
  real risk where a genuine broker-side order could have gone
  unrecorded locally.
- Root-caused from a real Render access-log screenshot rather than
  guessing -- the first hypothesis (the market-hours pre-check only
  considers the US) was checked against the actual code and disproven
  live before the real cause was found further downstream.

---

## 2026-08-18 — Fixed silent universe-add data loss, added a 2-hourly scan

**Problem**: reported live: adding a suggested symbol via "Add to
universe" appeared to work but "didn't seem to track." Root cause:
Render's disk is ephemeral, and the route wrote the addition locally
then reported success regardless of whether the GitHub sync actually
succeeded -- if GITHUB_TOKEN/GITHUB_REPO weren't set, or the push
itself failed, the addition would silently vanish on the next restart
or get overwritten by the next scheduled_pull_state pull. Also asked
for scanning to happen more often than the two fixed daily times, with
explicit log confirmation that it's actually running.

**Solution**:
- `/universe/add` now refuses up front when GitHub isn't configured
  (same refusal `/approve` already uses for the identical reason,
  instead of a misleading "Added X" message), and reports clearly if a
  configured push still fails -- `/universe/remove` gets the same
  treatment.
- Added `scheduled_interval_scan`, every 2 hours on weekdays (same
  weekend-skip reasoning as the two existing daily scans), printing
  exactly one `[interval-scan]`-tagged line per active profile every
  run -- success or failure -- so it's confirmable from the logs alone.

---

## 2026-08-19 — Tiger movers data + growth-only auto-add to universe

**Problem**: wanted a way to identify likely-shooting-up companies for
growth using real Tiger data (not a manual click), and for "Add to
universe" to actually self-serve when a sector/mover match is found
instead of requiring a human click every time.

**Solution**:
- New `movers.py`: wraps `QuoteClient.get_trade_rank`, Tiger's own
  real-time "most active" ranking per market -- confirmed live it's a
  real signal (semiconductor names dominated the top of the US list,
  matching sector_rotation.py's independent finding that Semiconductors
  was the day's hottest industry). US/HK only, SG confirmed unsupported
  (same gap as GICS classification). New "Today's movers" panel on
  growth's dashboard.
- `scheduled_sector_rotation_update` now also builds mover-matched
  suggestions for growth: the top sector/industry's membership
  intersected with today's REAL movers instead of a generic liquidity-
  floor screener -- "hot AND actually moving," not just "hot AND
  liquid" -- combined with the existing sector-based suggestions.
- For growth only, up to 3 of those combined suggestions per run get
  added to the universe automatically, no click -- still runs through
  the same disjointness validation a manual add uses. Bounded two ways
  so the universe can't grow unbounded: a per-run cap, and auto-adding
  stops entirely once the extra universe hits 15 entries. Dividend
  keeps the existing manual-approval-only flow untouched.
- Live-verified end to end: real US/HK movers lists, 3 real
  semiconductor names (AXTI, ASX, CRDO) auto-added respecting the cap,
  tagged "auto-added" in the dashboard's Approved additions panel.

---

## 2026-08-20 — Real dividend tracking + a weekly gain progress chart

**Problem**: the dividend portfolio's stated key objective is earning
dividends, but nothing tracked that directly -- only overall capital
gain. Also wanted a quick line-chart view of the current week's
progress, day by day, without digging into the full equity curve.

**Solution**:
- New `dividend_tracker.py` cross-references Tiger's own corporate-
  dividend schedule against the portfolio's trade journal (shares held
  x amount/share, for every dividend event that fell inside a
  position's held window) -- exact for buy-and-hold, approximate if a
  position was partially traded mid-holding (trade_journal.py only
  keeps one aggregated entry per symbol, no multi-lot fill history;
  stated plainly in the module docstring). New daily
  `scheduled_dividends_update` job, dividend-only. Dashboard shows a
  running year-to-date total by currency plus a per-payment detail
  list.
- New `_weekly_gain_chart_data`: reset-aware day-by-day % gain for the
  current week (Monday through today), reusing the ledger's existing
  daily history and the same reset-skip logic the monthly gain card
  already uses. Shown above the Scan Now button on both dashboards.
- Live-verified: a real $15.80 USD dividend payment (HDV, 151 shares,
  matching the actual position) and a real Mon-Thu weekly progress
  chart both rendered correctly.

---

## 2026-08-21 — Fixed overbuying past the capital cap, reverted to 3 market-open scans

**Problem**: reported live -- a negative cash balance ($-1,042) with
$5,917 invested against a $5,000 cap, and "too much" trading churn.
Also asked whether fees were counted in gain, and why the dividend
portfolio's weekly review had nothing to learn from.

**Solution**:
- Confirmed fees already flow into total capital correctly (commission
  is subtracted from cash_delta on every real fill) -- no change
  needed, just verified against the code rather than guessed.
- Root-caused and fixed the overbuying: `run_scan`'s risk-check loop
  built a `state` snapshot of committed capital ONCE before approving
  any instructions, then never updated it as instructions got approved
  WITHIN that same loop -- several candidates in one scan could each
  individually pass `check_capital_cap` against the identical stale
  figure while their SUM blew straight through it. Fixed by updating
  `state.open_positions` after each approval so later checks in the
  same batch see the cumulative effect of everything already approved.
  Same fix covers `check_concurrent_positions` and
  `check_short_exposure` too, identical root cause.
- Reverted the 2-hourly interval scan (added days earlier) back to
  exactly three scans a day, one at each market's own open -- SG
  (9:05 SGT), HK (9:35 SGT), US (9:35am ET, America/New_York timezone
  so DST is handled automatically). The interval scan's frequent
  re-ranking was forcing exits on positions that hadn't actually hit
  stop-loss or momentum-reversal, just because a different candidate
  scored higher that cycle.
- Found and fixed a related gap while investigating the "no lessons"
  question: the weekly review always called `compute_week_stats` with
  a hardcoded empty `position_returns`, so "Best"/"worst" always read
  "n/a" even in a week with real closed trades -- the per-symbol P&L
  needed for it was already computed a few lines later in the same
  function for self-improvement pausing, just never reused for this.
  Also reworded the "no scan decisions" placeholder text, which read
  like leftover pipeline-testing language rather than a genuine
  explanation.

## 2026-10-02

- **Removed the weekly "review"** (lessons / proposed strategy changes / changelog) for both
  portfolios: deleted `src/weekly_review.py`, `format_weekly_update`, the dashboard "Weekly
  reviews" panel and its tests. In its Saturday 9:00 SGT slot, `reporting.run_weekly_summary`
  now sends a short Telegram P&L summary (net weekly P&L after commissions, realized P&L per
  trade closed that week). The mechanical self-improvement pause (a live trading rule, not
  review text) keeps running inside that job and is reported on one line.
- The review had a **second trigger**: the local Windows task `OptionsAgent-WeeklyReview`
  (ran `scripts/send_weekly_review.py`). Disabled it (reversible) -- the Render scheduler
  already sends the summary, so re-enabling it would send it twice. Script renamed to
  `scripts/send_weekly_summary.py`.
- Verified the app does NOT close all trades at week end (nothing flattens positions); that
  behaviour belongs to the Forex Agent project.
- Added a growth-only **Claude research routine** (scheduled task
  `options-agent-stock-weekly-research`, Saturdays 9:00 local): reviews the week, reflects
  against the hypotheses, backtests/refines autonomously, alerts only past a strict bar.
  Spec in `research/README.md`, living log in `research/stock_hypotheses.md`; `research/**`
  added to `render.yaml`'s `ignoredPaths`. Separate from the Forex routine
  (`weekly-strategy-research`).

## 2026-10-28

- **Telegram cleanup (both portfolios).** Removed the "Claude Stock Trading Shortlist" digest and the
  "pending approval(s) ready to review" alert (and the dedupe cache that existed only for them): under autopilot,
  pending items just wait for the next market open, and the shortlist is below-threshold names nobody acts on.
  Both still appear on the dashboard.
- **Daily summary rewritten** (`format_daily_update`): total capital, change since the last update, holdings
  (invested/cash and, for growth, core/satellite vs the 40/60 target), trades since the last update from real
  Tiger fills (with commissions), and only if present an FOMC flag and notable per-symbol news. The macro regime
  paragraph (futures positioning / breadth / short-selling gate) and the "no notable news" filler are gone from
  Telegram (still on the dashboard).
- **"Orders placed" alert**: labelled `[Growth Portfolio]` / `[Dividend Portfolio]`, a plain-English reason per
  order (stop-loss, no longer a top pick, buying/trimming to target size), and "Invested ... | cash ..." instead of
  the misleading "margin used" (the account doesn't trade on margin). The weekly summary is labelled too.

- **Dividend rebalance band (user-directed, "if it works for dividend").** Tested first with
  `research/dividend_band_test.py` (fixed holdings, equal-weight to the live target, daily scan, real
  `reconcile_positions`, $2.98/order, 2020-06 -> 2026-10, three holding sets). No band: ~560-630 orders/yr, 5.3-6.1%
  of capital/yr in fees, net return +9% / +33% / +13%. 20% band: 3-7 orders/yr, ~0.05%/yr, +53% / +76% / +61%, with
  equal-or-lower max drawdown. Live dividend had been paying $232 in commissions in 30 days (78 orders, 69 under $300).
  Applied `rebalance_band_pct=0.20` to the dividend profile. Known tradeoff: a held position can now drift to ~16.8% of
  capital (14% target x 1.2), slightly past `max_single_position_pct` (15%); a 0.10 band holds it to ~15.4% at nearly
  the same fee saving -- a one-line change if preferred. New entries and full exits bypass the band by design.

## 2026-11-01

- **R-multiple expectancy in the weekly summary** (idea from reviewing the `day-trader-skill` pack). New
  `src/trade_stats.py`: R = realized P&L / (entry x quantity x the profile's stop%), average R, hit rate, and the
  break-even hit rate 1/(1+payoff). The Saturday message adds "Expectancy this week" and "Expectancy since inception"
  lines (flagged "small sample" under 10 trades). Approximation: the journal keeps one aggregated entry per symbol, so
  staged trims overstate R a little. First readings: growth -0.21R over 15 closed trades, 53% hit rate vs 80% needed
  (since 1 Oct: -0.60R over 3, which includes AEHR's late -39.5% stop from the outage); dividend +0.29R over 4.
- Also reviewed the pack itself: execution timing (our 09:35 ET fills vs the 10:00-10:30 VWAP) shows no opening
  penalty on paper fills; five new ideas queued in `research/idea_backlog.md` (#13-#17).

---

## 2026-11-21

- **Growth: a drawdown halt now lets protective exits through** (the user's call). New `RiskConfig.halt_allows_exits`
  (default False; True for growth only). While halted, `scan_workflow` approves an order only if the scan flagged it as
  a stop-loss / momentum-reversal / short-stop exit; buys, "no longer a target" rotation sells and band trims stay
  blocked. Before, a halt blocked every order, so a position past its stop sat there for the whole halt. Backtest was
  mixed (static +273% vs +244%, full universe +866% vs +1413%, see `research/stock_hypotheses.md`); a one-line revert.
  The growth book is ~23% below its peak, close to the 25% line, so this could matter soon.
- Research: S&P dip-buying study (`research/dip_buy_study.py`): no fixed -20% rule; idea #18 queued.
- **Growth: index core** (weekly research routine, passed the auto-ship bar; 039bc977). `PortfolioProfile.core_switch`
  (`src/core_switch.py`): the core sleeve holds QQQ while QQQ is above its 200-day SMA (2% hysteresis band) and stays in cash
  otherwise; QQQ skips the momentum exit. Dividend unchanged. Harness +971% vs +712% full, +281% vs +219% static. QQQ is
  risk-off now, so Monday's scan should sell IWM.

- **Growth went into big-bet mode** (the user's call: "as aggressive as possible", cash is stored elsewhere). No index core; two satellites at 50% each; the momentum-reversal exit is off; per-trade risk check raised to 100% so a 50% position can pass it. The 20% stop, 25% halt (60-day restart, exits allowed) are unchanged; dividend is untouched. Backtest $5k since 3/2020: static +707% vs +298%, full +4621% vs +1004%, with maximum drawdown 54-58% (was 32-41%); the worst of 7 start-date/capital variants is +117% / +1152% vs +44% / +269%. A stop-out now costs about 10% of equity. Rollback values are in the comment in `src/portfolio_profiles.py`. Research: `research/exp_1124b-d.py`.

- **Growth's drawdown halt removed** (the user's call). `RiskConfig.max_drawdown_pct` is now Optional and growth sets it to None, so growth keeps scanning and buying through any drawdown; the 60-day restart and exits-through-halt settings stay in the profile but do nothing. Dividend keeps its 25% halt. Backtest on the big-bet config: full universe +12,969% vs +4,621%, static +658% vs +707%, worst start +58% vs +117% (static): the outcome depends on when the halt would have tripped. Revert: `max_drawdown_pct=0.25` in `src/portfolio_profiles.py`.

## 2026-11-26

- **Pre-open check + SEC 8-K event guard for growth** (the user's call, after asking whether news can complement trading).
  New `src/event_guard.py` (EDGAR submissions feed through the existing `sec_edgar_adapter`; blocking items 1.03 / 2.04 /
  3.01 / 4.02, informational 5.02), `src/preopen_check.py` (orchestrator, dependencies injected) and a 09:00 New York weekday
  job `scheduled_preopen_check`: refreshes the news signal, writes `config/event_flags.json`, and sends ONE Telegram heads-up
  only when a held name has a fresh SEC filing or severe headline or a universe name was newly blocked. The scan rejects
  new entries in a blocked name (held names exempt; the guard never sells). Alert-only by design. Smoke-tested against the
  live SEC feed: NVDA's 11/12 and 11/23 8-Ks (Item 5.02, the CEO change) come through; nothing in the universe is blocked today.
- **Found:** the existing news pipeline had never produced data (`news_signal.json` has always been `{}`): `FINNHUB_API_KEY` is
  declared in `render.yaml` but was never given a value. Setting it (free) activates headlines in the alert and the news tilt.
- Not backtestable (no historical headline/filing archive in our data), so none of this went through the ship bar; the guard
  only ever removes entries in names that disclosed a bankruptcy / delisting / non-reliance / debt-acceleration event.

## 2026-11-27

- **Inchworm study (research only, nothing shipped).** The user asked whether "cut the C+ setups, keep base hits, then chase A+" applies to the
  growth bot. `research/inchworm_study.py` + `exp_1127.py`: the live trip distribution is extremely right-skewed (best 5 trips = 76-88% of
  log-return), the base hits alone earn a fraction of it, and the losing tail (stop-outs) cannot be separated from the winners by any
  entry feature; top-rank conviction weighting fails its reversed-order control. Details in `research/stock_hypotheses.md` (2026-11-27).

## 2026-11-28

- **Weekly growth research routine (nothing shipped).** Health OK (decisions every day, 7 growth fills, 808 tests). 14 ideas + 3 variants vs
  big-bet LIVE (`research/exp_1128*.py`); none pass the auto-ship bar. Best: no USO/UNG as growth satellites (21/21 capital paths on both
  universes, jack 16/20) but walk-forward fails. New harness options (off by default): `sat_exclude`, `no_add_below`, `riskoff_confirm`,
  `near_high`, `stage`.
- **Bug flagged, not fixed (off-limits file):** `order_execution.py` debits the sizing estimate when an order is not FILLED within 2 s,
  even if Tiger later rejects it. Two rejected dividend XOM buys (11/23, 11/24) removed ~$8.6k of phantom cash from the dividend ledger.
