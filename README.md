# Claude Trading Agent (formerly options-agent)

Trading agent for Tiger Brokers (Singapore), pivoted from an options
income strategy to a multi-market stock/ETF strategy. Deployed on
Render.com (free tier) and monitored by UptimeRobot for the dashboard
and Telegram reporting. The dashboard now includes a **Scan Now** button
and an approval workflow (see "Automated scan + approval workflow"
below) -- but the hard boundary is unchanged in spirit: nothing runs
autonomously on a schedule ever places a real order. The one exception
is a human clicking **Approve** on a specific proposed trade, which is
that human's own HTTP request, not autonomous code -- see that section
for the exact reasoning.

## Pivot (2026-07-31)

This repo started as an options premium-selling agent. It has since fully
pivoted to stock/ETF trading -- all options-specific code (Black-Scholes
backtest, credit spread engine, option chain adapter, cash-secured-put
strategy layer) was removed; git history preserves it if ever needed.

**Goal:** start with $1,000, target 10% return per month, trading a
core-satellite mix (broad ETFs + dividend names for stability, momentum
stocks for growth) across US, Hong Kong, and Singapore markets. The 10%/month
target is extremely aggressive (~213%/year) -- after being told this
directly, the user explicitly chose concentrated, higher-risk position
sizing ("chase the target harder") over a conservative target. One hard
floor stays regardless: `RiskConfig.max_drawdown_pct` (25% by default) halts
trading if the account gives back more than that from its peak, and
`max_single_position_pct` (35%) means no single position ever reaches 100%
of capital.

## Status
- [x] Tiger developer account, paper account, local connectivity all confirmed (unchanged from the options era)
- [x] Risk/rules engine (`src/risk_engine.py`) -- reused almost as-is from the options track (the mechanics are asset-agnostic), with a new `max_drawdown_pct` circuit breaker and $1,000/10%-monthly-target defaults
- [x] Multi-market universe (`src/universe.py`) -- US/HK/SG, core + satellite sleeves, with currency/exchange metadata for future order placement
- [x] Tiger data adapters for dividends (`src/tiger_dividend_adapter.py`) and board-lot metadata (`src/tiger_trade_metas_adapter.py`)
- [x] Selection signal (`src/stock_signal.py`) -- momentum + trailing dividend yield + an optional news tilt, blended into one composite score
- [x] Macro "investment clock" regime signal (`src/macro_regime.py`, `config/regime.json`) -- refreshed manually via web search of public JPMorgan/Goldman Sachs/DBS/OCBC commentary (their full research is paywalled)
- [x] Daily news-tilt signal (`src/news_scanner.py`, `config/news_signal.json`) -- same manual-research pattern, **deliberately kept manual, not automated.** An unattended scheduled agent doing live web research and writing files needs permission-bypass to run at all (no human present to approve mid-run) -- explored this and decided against it: the security exposure (a prompt-injection risk from web content, feeding directly into position sizing for a real trading strategy, with no one reviewing that day's specific findings) isn't worth trading for convenience. Refreshed on request instead -- e.g. 2026-08-01's real synthesis, sourced per-symbol, is in `config/news_signal.json` right now
- [x] Core-satellite portfolio construction (`src/portfolio_construction.py`) -- board-lot affordability filtering runs before allocation, so HK/SG names that don't fit $1,000 are excluded upstream
- [x] Exit rules (`src/exit_rules.py`) -- a real "when to sell" mechanism: a hard stop-loss and a momentum-reversal exit, checked daily within each holding period, not just "didn't get re-picked at the next rebalance"
- [x] Decision log (`src/decision_log.py`) -- a deterministic buy/hold/sell/reject rationale trail for every candidate at every rebalance, built from the actual scores/exit triggers used, not a per-period LLM narration
- [x] Weekly self-learning review (`src/weekly_review.py`) -- computes realized-vs-target stats and proposes *bounded* tactical adjustments (signal weights only, never the hard risk limits above)
- [x] Telegram notifier (`src/telegram_notifier.py`) -- configured and verified sending real messages
- [x] Daily/weekly notification pipeline (`scripts/send_daily_update.py`, `scripts/send_weekly_review.py`) -- registered as Windows Scheduled Tasks (`OptionsAgent-DailyUpdate` 6pm SGT daily, `OptionsAgent-WeeklyReview` Saturdays 9am SGT), verified running. Tracks the strategy's own $1,000 in `strategy_ledger.py`, separate from Tiger's default $1,000,000 paper-account balance. Honestly reports flat/no-activity until real trades exist.
- [x] Stock backtest engine (`src/stock_backtest.py`, `scripts/run_stock_backtest.py`) -- see findings below
- [x] Order execution module (`src/execution.py`, `src/tiger_order_adapter.py`, `scripts/execute_trades.py`) -- see below. Every computed order passes through `risk_engine.validate_trade()`; the only module that ever calls Tiger's order API is `tiger_order_adapter.py`, and it's only ever invoked from `execute_trades.py --live` with a human explicitly triggering that specific run
- [x] Cloud deployment (`app.py`, `render.yaml`) -- see below. Dashboard + the daily/weekly Telegram jobs now run independently of any local machine being on
- [x] Daily mark-to-market (`strategy_ledger.mark_to_market_snapshot`) -- fixed a real bug where reported capital only ever moved on trade days; `run_daily_update()` now re-fetches live Tiger positions and re-anchors capital every day, verified live: stale $990.86 -> real $1,018.46 -> $1,017.33 on subsequent runs
- [x] CFTC Commitment of Traders positioning signal (`src/cot_adapter.py`) -- free, public, weekly (Socrata Open Data API, no auth). Computes a z-score of net non-commercial futures positioning against its own trailing history for S&P 500 / Nasdaq-100 e-minis, translated into a bounded (0.9-1.1) tilt applied to the satellite sleeve via `macro_regime.effective_sleeve_tilts`. Refreshed by a Friday 4:30pm ET scheduled job, matching the CFTC's real publication time. Verified against the real API: sp500 z=+2.20, nasdaq100 z=-1.24, tilt=0.976
- [x] Automated daily news-sentiment scan (`src/alpha_vantage_news_adapter.py`) -- free Alpha Vantage `NEWS_SENTIMENT` API, structured pre-scored data, deliberately **no LLM/agent in this loop** so there's no prompt-injection surface in the unattended path (unlike a web-search agent would have). Includes economy/fiscal/monetary/financial-markets topics so policy coverage (tariffs, Fed commentary, how outlets report presidential statements) surfaces by construction. Needs a free `ALPHA_VANTAGE_API_KEY` (see `render.yaml`)
- [x] FOMC calendar awareness (`src/fomc_calendar.py`) -- all 8 real 2026 FOMC meeting dates; the daily Telegram update now flags when today is an announcement day or one is coming up within 3 days
- [x] Automated daily scan + approval workflow (`src/scan_workflow.py`, `src/pending_approvals.py`, `src/order_execution.py`) -- see below
- [x] Renamed the dashboard from "options-agent" to "Claude Trading Agent" (`templates/base.html`, brand + nav)
- [x] Dashboard live-data fix -- the dashboard used to only reflect a 30-minute-old position snapshot and a once-a-day capital mark-to-market, so reloading the page never showed anything new between those. `dashboard()` now fetches live from Tiger on every request (falling back to the cached snapshot with a visible "live data unavailable" banner if Tiger's unreachable), without persisting a new ledger-history entry per page view
- [x] A second portfolio: dividend/income investing alongside the existing $1,000 growth/momentum one -- see "Two portfolios" below
- [x] Tactical short-selling in the growth portfolio, gated on an actual macro signal -- see "Shorting" below
- [x] Market-breadth signal (RSP/SPY equal-weight vs. cap-weight ratio) -- see "Market breadth" below

## Cloud deployment (Render.com, free tier)

Local Windows Task Scheduler jobs only fire when the laptop is on and
active -- confirmed directly: a job scheduled for 6pm ran at 10:09pm
instead because the laptop wasn't active at 6pm. Moved the daily/weekly
Telegram reports and a read-only portfolio dashboard to an always-on (free
tier -- UptimeRobot pings `/health` every 5 min to prevent spin-down)
Render web service.

**Live** at `https://options-agent-dashboard-xab8.onrender.com/` --
verified: real capital ($990.86), real positions (NVDA/SCHD/VYM), and the
full decision rationale trail all render correctly from GitHub-synced
state, independent of any local machine being on. UptimeRobot pings
`/health` every 5 minutes.

**Hard boundary, updated for the approval workflow below:** no
*scheduled* job here ever calls `tiger_order_adapter.place_market_order`.
The cloud service's autonomous jobs (a) send the daily/weekly Telegram
reports (per active portfolio), (b) run a daily scan per active
portfolio that scores candidates and writes proposals for review -- but
places nothing, (c) refresh a read-only position snapshot every 30
minutes, (d) refresh the weekly COT positioning tilt, (e) refresh the
daily market-breadth (RSP/SPY) signal, (f) refresh the daily
news-sentiment signal, and (g) re-pull state from GitHub every 10
minutes so a locally-placed trade shows up on the dashboard without a
manual restart. The **one** path
that places a real order is `POST /approve/<id>`, and it only ever runs
as a direct result of a human clicking Approve on a specific proposed
trade on the dashboard -- never triggered by the scheduler or any other
autonomous code path (see `order_execution.py`'s and `app.py`'s
docstrings, which state this same boundary from both sides). It
re-validates risk with freshly-fetched positions (not the stale
scan-time snapshot) before placing anything, since state may have moved
since the scan that proposed it. `execute_trades.py --live` remains the
separate local, human-triggered CLI path, unchanged. Route inventory
(`app.app.url_map`): `/health`, `/` (dashboard), `/scan` (POST, runs a
scan), `/review` (full rationale), `/approve/<id>` (GET renders a
confirmation page and executes nothing; POST re-validates and places the
order).

The dashboard intentionally has **no login** -- an explicit, informed
choice made even after the Approve button was added (flagged twice,
confirmed both times). Anyone with the URL can trigger a scan or approve
a proposed trade; this is an accepted tradeoff for a personal $1,000
account, not an oversight.

**State persistence without paying for a disk:** Render's free tier wipes
its filesystem on every redeploy, so `src/github_state_sync.py` uses
GitHub's Contents API as a free, durable store for the small JSON state
files (`strategy_ledger.json`, `decision_log.json`,
`strategy_changelog.json`, `news_signal.json`, `regime.json`,
`pending_approvals.json`, plus the dividend portfolio's own
`strategy_ledger_dividend.json`/`decision_log_dividend.json`/
`portfolio_snapshot_dividend.json`/`pending_approvals_dividend.json` --
see `src/state_paths.py::STATE_FILES`) -- pulled
on startup and every 10 minutes thereafter, pushed after every local
write (`execute_trades.py`, `scripts/send_daily_update.py`,
`scripts/send_weekly_review.py` all call this now; `GITHUB_TOKEN`/
`GITHUB_REPO` are set as persistent local env vars, same names as on
Render). Both the local machine (where trades actually get placed) and
the cloud dashboard share this as one source of truth.
`src/state_paths.py` centralizes where these files live locally vs. in
the cloud (`STATE_DIR` env var).

**Credentials as env vars:** `tiger_client.py` and `telegram_notifier.py`
check `TIGER_*`/`TELEGRAM_*` env vars first, falling back to the local
properties files unchanged for local dev. See `render.yaml` for the full
env var list -- all `sync: false`, entered directly in Render's
dashboard, never in the repo.

## Backtest findings (2026-07-31, `python scripts/run_stock_backtest.py`)

Real Tiger paper-account data, Dec 2023 - Jun 2026, 38 monthly-ish rebalance
periods, **with the stop-loss/momentum-reversal exit rules active (43 early
exits fired over the run):** 113.2% total return, 2.1% average per period
against the 10%/month target -- an 8% hit rate. Worst single period -6.0%,
max drawdown 12.3% (breaker threshold is 25%, never tripped in this run; it
does trip on a synthetic crash, see
`tests/test_stock_backtest.py::test_backtest_halts_on_severe_drawdown`, and
the stop-loss firing correctly is its own test,
`test_stop_loss_exits_crashing_position_early_and_caps_the_loss`).

**This is a real, honest tradeoff, not free money:** the same backtest
*without* exit rules produced a higher total return (183.4%) but a worse
worst-period (-9.9%) and worse max drawdown (19.1%) -- the sell discipline
gives up some upside (it occasionally exits a name that goes on to recover,
e.g. one META exit locked in +24.7% rather than letting it run further)
in exchange for meaningfully less tail risk. Every rebalance's full
buy/hold/sell/reject rationale, with the score or exit trigger behind each
decision, is written to `config/decision_log.json` and the most recent
period's is printed at the end of the script's output.

**Read the total return with real caveats, not at face value:**
- The satellite sleeve was almost always filled by NVDA/AMD/AVGO/META --
  names that were hand-picked into the universe as "momentum candidates"
  precisely because they've performed well. That's a selection-bias risk:
  the backtest is partly measuring "did I successfully guess in advance
  which stocks would rally," not "does the momentum signal generalize."
  A less flattering, unbiased satellite universe (or true forward/
  out-of-sample testing) is the natural next check before trusting this.
- The window (Dec 2023-Jun 2026) covers an unusually strong AI-stock bull
  run. A 2.5-year backtest is one historical path, not a distribution.
- HK candidates (Tencent, HSBC) were correctly excluded the entire time --
  their board lots cost ~$6,000-$8,600 USD, far past what $1,000 can
  afford. This is the affordability filter working as designed, confirming
  the concern raised before this was built.
- SG needed a symbol-format fix (`D05` -> `D05.SI`) to fetch any bars at
  all; Singtel (`Z74.SI`) shows up regularly in the core sleeve, DBS/OCBC
  never won the ranking against it or the US ETFs.

## Order execution (`scripts/execute_trades.py`)

Scores today's candidates identically to the backtest (shared via
`stock_signal.score_symbol`), checks the exit rules against whatever's
*currently held* (not just the rebalance ranking -- a real sell check, live),
reconciles against actual Tiger positions, and gates every resulting order
through `risk_engine.validate_trade()`.

- `python scripts/execute_trades.py` -- dry run, computes and prints only,
  places nothing. Safe to run anytime.
- `python scripts/execute_trades.py --live` -- actually submits orders to
  whichever account `tiger_client.get_client_config()` currently points at.
  **Verify that's still the paper account before ever using this flag.**

One real bug this surfaced and fixed: lot-size rounding was rounding
share quantities to the *nearest* lot, which could push a position's
notional slightly **above** its target and trip the risk engine's
per-trade cap, rejecting the whole order rather than sizing it down.
`execution.round_to_lot` now floors instead -- undershooting a target by
less than one lot is far more benign than breaching a hard cap.

**First live (paper) trade placed 2026-08-01:** `BUY 5 SCHD, BUY 1 VYM,
BUY 1 NVDA` -- $525.18 deployed, 52.5% of the $1,000. Placing the order is
always a human-triggered `--live` run, never something this project
executes on its own initiative.

On order placement, `format_order_placed_update` (in `telegram_notifier.py`)
sends a Telegram message with each order's $ size and % of the $1,000,
plus overall margin utilization and cash remaining. Every trade also calls
`strategy_ledger.apply_trade_and_snapshot`, which pulls the *actual* fill
price and commission per order (not the sizing-time estimate) to update a
persisted `cash_reserve` -- total tracked capital is `cash_reserve +`
current position market value, so a buy converts cash into stock value
without silently changing total equity, and only the real commission cost
(plus subsequent price moves) shows up as a genuine gain/loss. First
trade: $1,000.00 -> $990.86 (-$9.14: $8.94 in commissions across 3 orders,
plus a few cents of price drift since fill).

## Automated scan + approval workflow

`src/scan_workflow.py::run_scan()` extracts everything `execute_trades.py`
already did before its `--live` block (scoring, exit checks, allocation,
reconciliation against real positions, risk-gating) into one function --
now shared by three callers: the CLI (dry-run and `--live`), a daily
17:30 SGT scheduled job on the cloud service, and the dashboard's **Scan
Now** button (`POST /scan`). Every scan writes the full rationale to
`config/decision_log.json` (viewable on `/review`, grouped by
buy/hold/sell/reject) and, separately, a `config/pending_approvals.json`
of just the approved-but-not-yet-executed instructions -- each carrying
its rationale, score, and projected impact (resulting position % of
capital, projected total portfolio utilization) for the dashboard's
Pending Approvals panel. **The whole pending list is replaced by each
scan**, not merged -- a stale unapproved proposal from an earlier scan is
superseded, since prices and targets have moved.

Clicking **Review & Approve** on a pending item shows a confirmation
page (`/approve/<id>` GET, which renders and executes nothing) with the
same rationale/impact plus a warning that risk will be re-checked with
fresh data. Confirming (`/approve/<id>` POST) re-fetches live positions,
re-runs `risk_engine.check_max_drawdown` and `validate_trade` against
that fresh state, and only then calls `order_execution.execute_instructions`
-- the same function `execute_trades.py --live` uses, extracted in this
pass into `src/order_execution.py` as the one shared place (besides
`tiger_order_adapter.py` itself) that ever calls `place_market_order`.

**One real bug this extraction surfaced and fixed:** commission was
being *added* to sell proceeds instead of subtracted (`cash_amount =
filled_cash_amount + commission` applied to both buys and sells), which
would have overstated `cash_reserve` on every future sell. Never
exercised before since every real trade so far had been a BUY; caught
while writing `tests/test_order_execution.py` and fixed in
`order_execution.py`.

## Two portfolios: growth and dividend

`src/portfolio_profiles.py` bundles everything that used to be hardcoded
to the one strategy (universe, risk config, allocation config, state file
paths) into a `PortfolioProfile`. `GROWTH_PROFILE` is the existing $1,000
momentum/core-satellite strategy, unchanged file paths and behavior --
zero migration risk to the real state history already live on Render/
GitHub. `DIVIDEND_PROFILE` is a new $30,000-target income portfolio
(`src/universe.py::DIVIDEND_UNIVERSE`, yield-first scoring weights),
tracked as a **separate ledger in the same Tiger account** (the user's
explicit choice over a second brokerage account) via new `_dividend`-
suffixed state files. It's inactive (`initial_capital=0`) until a real
`DIVIDEND_PORTFOLIO_CAPITAL` env var is set, locally and in Render --
once set, the daily scan and dashboard pick it up automatically, no code
change needed.

**Hard constraint this creates:** Tiger reports one combined position
per symbol for the whole account -- it has no concept of "these shares
are the dividend ledger's, those are growth's." So the two portfolios'
universes must stay **symbol-disjoint**, enforced by an assertion at
import time (`portfolio_profiles.assert_universes_disjoint`, unit
tested) rather than solved via cross-attribution.

Every dashboard/scan/review/approve route takes an optional
`?portfolio=growth|dividend` query param (default `growth`, so existing
bookmarks/UptimeRobot/Telegram links are unaffected); `templates/base.html`
has a Growth/Dividend switcher in the header. The scheduled daily scan
loops over `portfolio_profiles.ACTIVE_PROFILES`. Weekly review stays
growth-only for now (`reporting.run_weekly_review`'s docstring) --
its proposed weight adjustments are specific to growth's momentum-first
scoring, not dividend's yield-first one; revisit once dividend has real
trading history.

## Shorting

Tactical, gated on an actual macro signal -- "if the opportunity
arises," not a standing sleeve. Growth portfolio only
(`RiskConfig.max_short_positions`, default 1; `max_short_exposure_pct`,
default 15% of capital).

**How it fits the existing BUY/SELL pipeline, verified against the
installed SDK, not assumed:** `tigeropen`'s `market_order()` only takes
`action="BUY"|"SELL"` and `Position` has no separate long/short flag,
just a `quantity` field -- so opening a short is just a `SELL` when you
don't (fully) own the shares, and covering is a `BUY`. **No changes
were needed to `tiger_order_adapter.py` or `order_execution.py`** --
shorting is entirely a strategy/risk/UI-layer concept layered on the
existing order-placement primitives. `src/scan_workflow.py` expresses a
short target as a **negative** `target_notional`, and
`execution.reconcile_positions`'s existing delta math (`target_qty -
current_qty`) already produces the mechanically correct BUY/SELL calls
for opening, adding to, partially covering, and fully covering a short
(`execution.round_to_lot` was made sign-aware to support this -- it used
to collapse any negative input to zero).

**Gate:** `src/short_signal.py::market_favors_shorting()` only opens the
short-candidate pass when either the COT positioning signal shows
crowded-long conditions, or the market-breadth signal (below) is
narrowing at an edge -- both are "the tide may be turning" reads from
independent data. A per-symbol candidate additionally needs a real
momentum breakdown (`score_short_candidate`, default threshold -15%).
Symbols already held long are excluded (can't be long and short the
same symbol at once).

**Risk:** symmetric 15% stop-loss (`exit_rules.check_stop_loss_short`),
plus a dedicated aggregate short-exposure cap
(`RiskEngine.check_short_exposure`, only triggered for `direction=
"short"` trades -- a cover, which reduces exposure, is never gated by
it). `pending_approvals.py` derives a `position_type` ("short"/"cover"/
"long") purely for dashboard/review labeling ("SHORT 10 AMD" instead of
a bare, confusing "SELL 10 AMD" for a symbol you don't currently hold) --
the underlying order stays a plain BUY/SELL, no new order type.

**Not yet verified against real data and deliberately not enabled with
real capital yet:** whether Tiger's paper account actually represents an
open short as `quantity < 0` with correspondingly signed `market_value`
(the assumed, standard convention this design's P&L math depends on).
Placing one small real short and inspecting `get_positions()` is the
next step before trusting `/approve/<id>` on a short with real money.

## Market breadth (RSP/SPY)

`src/market_breadth.py`: the equal-weight S&P 500 (RSP) divided by the
cap-weight S&P 500 (SPY) -- rising means the average stock is starting
to beat the mega-caps ("broadening"), falling means the opposite
("narrowing"). Reuses the existing `tiger_stock_bars_adapter` unchanged
(RSP/SPY are just two more symbols to a function already used for every
other ticker). Two deliberately quantitative signals, not visual/
candlestick pattern-recognition (consistent with every other signal in
this codebase):
- **Trend** ("stick with the wave"): the ratio's position relative to a
  20-day and 100-day moving average.
- **At-edge** ("get ready to turn"): a z-score of the ratio's 20-day
  rate of change against its own trailing history -- the same
  statistical technique `cot_adapter.py` already uses for COT z-scores.
  Flagged honestly as a "this move is stretched, be cautious" risk flag,
  not a reversal-timing prediction.

Feeds `macro_regime.effective_sleeve_tilts` (multiplied into the
satellite tilt alongside the existing COT-derived tilt), scales down new
capital deployment for the scan when at an edge (a separate light-touch
caution knob from sleeve tilting or the hard drawdown halt), and is one
of the two independent inputs to the shorting gate above. Refreshed
daily (`scheduled_breadth_update`, 08:30 SGT). Verified against real
Tiger data: RSP/SPY ratio 0.2846, trend "flat", not at an edge.

**Deliberately deferred:** true sector/industry-level granularity (a
dedicated sector-ETF universe with per-sector breadth scoring) -- this
pass feeds the existing core/satellite tilt and the short gate across
the existing universe, not a new sector-rotation layer.

## Local setup
1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copy your **paper account** properties file to `config/tiger_openapi_config.properties`
   (see `config/README.md`)
4. `python scripts/test_connection.py`
5. `pytest tests/ -q` -- should show all tests passing
6. `python scripts/run_stock_backtest.py` -- runs the real backtest above

## Security notes
- `config/*.properties`, `*.pem`, `.env` are git-ignored — never commit credentials.
- Regenerate RSA keys via the Tiger Developer Info page if they've ever been
  shared outside this local environment.
- The live account file is only ever used once TIGER_ENV is explicitly set
  to "live" after a validated paper-trading run.
