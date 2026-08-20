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
