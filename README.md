# options-agent

Trading agent for Tiger Brokers (Singapore), pivoted from an options
income strategy to a multi-market stock/ETF strategy. Deployed on
Render.com (free tier) and monitored by UptimeRobot for the read-only
dashboard and Telegram reporting; order placement remains a local,
human-triggered action against the paper account (see "Cloud deployment"
below for the hard boundary between the two).

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
- [x] Cloud deployment (`app.py`, `render.yaml`) -- see below. Read-only dashboard + the daily/weekly Telegram jobs now run independently of any local machine being on; order placement stays local-only regardless (see the hard boundary below)

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

**Hard boundary, unchanged from the local setup:** nothing deployed here
ever calls `tiger_order_adapter.place_market_order`. `execute_trades.py
--live` stays a local, human-triggered action only -- `app.py` never
imports it. The cloud service only (a) sends the existing daily/weekly
reports, which read already-computed state and decide nothing, (b)
refreshes a read-only position snapshot every 30 minutes
(`src/portfolio_snapshot.py`, which deliberately never imports the
order-placement path either -- verify this if anything is ever added to
that file), and (c) re-pulls state from GitHub every 10 minutes so a
locally-placed trade shows up on the dashboard without a manual restart.
The dashboard (`templates/dashboard.html`) has no order-entry route --
confirmed via `app.app.url_map`: only `/health` and `/` exist.

**State persistence without paying for a disk:** Render's free tier wipes
its filesystem on every redeploy, so `src/github_state_sync.py` uses
GitHub's Contents API as a free, durable store for the small JSON state
files (`strategy_ledger.json`, `decision_log.json`,
`strategy_changelog.json`, `news_signal.json`, `regime.json`) -- pulled
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
