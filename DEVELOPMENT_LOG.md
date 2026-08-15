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
