# options-agent

Trading agent for Tiger Brokers (Singapore), pivoted from an options
income strategy to a multi-market stock/ETF strategy. Eventually deployed
on Render.com and monitored by UptimeRobot; for now it runs locally against
the paper account.

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
- [x] Macro "investment clock" regime signal (`src/macro_regime.py`, `config/regime.json`) -- refreshed manually via web search of public JPMorgan/Goldman Sachs/DBS/OCBC commentary (their full research is paywalled), not a scheduled/automated pipeline yet
- [x] Daily news-tilt signal (`src/news_scanner.py`) -- same manual-research pattern as the regime signal; the search itself is an agent action, this module just persists the result
- [x] Core-satellite portfolio construction (`src/portfolio_construction.py`) -- board-lot affordability filtering runs before allocation, so HK/SG names that don't fit $1,000 are excluded upstream
- [x] Exit rules (`src/exit_rules.py`) -- a real "when to sell" mechanism: a hard stop-loss and a momentum-reversal exit, checked daily within each holding period, not just "didn't get re-picked at the next rebalance"
- [x] Decision log (`src/decision_log.py`) -- a deterministic buy/hold/sell/reject rationale trail for every candidate at every rebalance, built from the actual scores/exit triggers used, not a per-period LLM narration
- [x] Weekly self-learning review (`src/weekly_review.py`) -- computes realized-vs-target stats and proposes *bounded* tactical adjustments (signal weights only, never the hard risk limits above)
- [x] Telegram notifier (`src/telegram_notifier.py`) -- configured and verified sending real messages
- [x] Daily/weekly notification pipeline (`scripts/send_daily_update.py`, `scripts/send_weekly_review.py`) -- registered as Windows Scheduled Tasks (`OptionsAgent-DailyUpdate` 6pm SGT daily, `OptionsAgent-WeeklyReview` Saturdays 9am SGT), verified running. Tracks the strategy's own $1,000 in `strategy_ledger.py`, separate from Tiger's default $1,000,000 paper-account balance. Honestly reports flat/no-activity until real trades exist.
- [x] Stock backtest engine (`src/stock_backtest.py`, `scripts/run_stock_backtest.py`) -- see findings below
- [x] Order execution module (`src/execution.py`, `src/tiger_order_adapter.py`, `scripts/execute_trades.py`) -- see below. Every computed order passes through `risk_engine.validate_trade()`; the only module that ever calls Tiger's order API is `tiger_order_adapter.py`, and it's only ever invoked from `execute_trades.py --live` with a human explicitly triggering that specific run
- [ ] Render deployment / UptimeRobot monitoring

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
less than one lot is far more benign than breaching a hard cap. Verified
against the real paper account in dry-run mode; no orders have been placed
yet since going live is a per-run human decision, not something this
project automates.

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
