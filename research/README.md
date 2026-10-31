# Growth strategy improvement routine (Options Agent / growth portfolio ONLY)

**Scope.** Options Agent repo (`options-agent`, Tiger Brokers), **growth** portfolio only. It is not the Forex
Agent project: never read, edit, or message about that. The dividend portfolio is not something to change, but
use it as a **benchmark** and as a **source of ideas**.

## Mission (reworked 2026-10-24 at the user's request)

The first four runs (10/02–10/17) produced careful research, no live improvement, and silence. The growth scan
had actually been crashing since 9/22, so nothing could have improved. That must not happen again.

**Every Saturday run must leave the live growth system measurably better, or prove it tried hard.** Each run
ends with at least one of these:
1. a **shipped** improvement, within the auto-ship guardrails below;
2. a **fixed ops fault** that was stopping or distorting growth trading (shipped, with tests);
3. a ranked shortlist of the 3 best candidates, each with numbers and what it still needs to pass. This is only
   acceptable after the minimum research volume below has been met.

"Nothing passed the bar" is not a result on its own.

## Weekly routine

### 0. Health check (do this first, every run)
- Is growth actually trading?
  - `config/decision_log.json` should have an entry for every US trading day of the week.
  - Growth fills from `TradeClient.get_filled_orders` should be > 0, unless the halt is active or the book is
    unchanged by design.
- Is `strategy_ledger.json` capital close to cash + all growth positions in Tiger?
- Are state files syncing? No 0-byte files after `pull_state_from_github()`.
- Was the 25% drawdown halt active?
- Any failing tests (`python -m pytest -q`)?

**If growth is not trading, or its state is wrong, fixing that is this week's #1 job.** Diagnose it, fix it in
`src/` with a regression test, run the full suite, and ship it (see Shipping). Ops fixes don't count against
the one-strategy-change-per-week limit.

### 1. Review the week (growth vs dividend vs market)
- Growth: trades closed, win rate, payoff ratio, realized P&L, unrealized change, commissions, orders,
  stop-out→re-entry within 10 days, and satellite sector concentration.
- **Benchmarks:** the same week, and since inception, for the dividend portfolio, SPY and QQQ. (Dividend got the same 20% rebalance band on 2026-10-28 at the user's direction, so its turnover and fees drop from that date -- account for it when comparing.) If dividend is
  beating growth, explain why in numbers (beta, concentration, turnover, fees) and turn it into ideas.
- **Counterfactual:** run the harness's LIVE config over the same week. Live doing worse than the harness means
  execution or ops drift.
- Check every change in `research/shipped_changes.md` against its live measurement plan (see Rollback).

### 2. Generate ideas — minimum volume every run
- Keep `research/idea_backlog.md` as a ranked queue. Every run, add **at least 8 new ideas**. Draw them from at
  least 3 of the families below, and from this week's trades and the dividend comparison.
- **Actually test at least 6 ideas** per run, through the full test protocol.
- Don't restart from scratch each week: pick up the backlog's top untested ideas.

Idea families. The heavily tested ones are de-prioritized, because exits, band, stop and halt variants have
been tried to death (see `stock_hypotheses.md`).
- **Signals:** multi-horizon momentum blends (21/63/126/252), 52-week-high proximity, trend quality (R² of the
  log-price slope), residual / sector-relative momentum, volume-confirmed breakouts, earnings-surprise drift,
  short-term reversal filters on entry, analyst/fundamental quality screens (`valuation.py`,
  `finnhub_adapter.py`).
- **Universe / selection:** quality of the satellite auto-add pipeline (it picked 15/16 semis), adding
  non-semi growth leaders, ETF-only satellites, a liquidity filter, dropping symbols with a short history.
- **Portfolio construction:** number of satellites, core/satellite split, conviction-weighted sizing, cash
  floor, a core-sleeve choice of QQQ vs VOO vs a trend-switched pick.
- **Entry timing / execution:** scan time of day, staged entries, limit vs market, skipping entries after gap-ups,
  cost-aware turnover (expected edge vs a $2.98 fee).
- **Regime:** breadth, VIX or credit-spread gating of the satellite sleeve only. The existing regime and COT
  data is in `config/regime.json`.
- **Learn from dividend:** what does it do that growth doesn't (lower turnover, broader holdings, a different
  rebalance rule)?
- **Wild cards:** anything new from the week's data, or from reading published, documented anomalies on the web.

### 3. Test protocol
- Harness: `research/harness.py`, commission-aware at $2.98 per order, daily scan-at-open cadence, live
  reconcile/band/stop rules. Extend it as needed. New features are off by default, so LIVE results never move.
- **Primary setup = live-like:** full/effective universe (static + `config/extra_universe.json` US names),
  25% halt on, $5k, from 2020-03.
- **Guardrail setup:** static universe. This guards against the semis hindsight in the full universe.
- Run every idea through: the 4 rolling windows, walk-forward (tune 2020-03→2023-03, test 2023-03→now), the
  20-universe jackknife (`exp_1010.jack_unis`), and ±20% nudges on its key parameter(s).
- Bars: `python research/fetch_bars.py --refresh`, which respects Tiger's limit of 60 kline calls per minute.
- Try hard to break any winner before shipping it.

### 4. Shipping — auto-ship bar (the user authorised this on 2026-10-24)

A strategy change ships **without asking** only when it meets **all** of these:
1. **Walk-forward:** with parameters chosen on 2020-03→2023-03 only, it beats LIVE on 2023-03→now on the primary
   setup after commissions. Its OOS max drawdown is no worse than LIVE by more than 3 points.
2. **Rolling windows:** it beats LIVE in at least 3 of 4 windows on the primary setup, and no window's MDD is
   worse by more than 5 points.
3. **Jackknife:** it beats LIVE in at least 13 of 20 universes on the primary setup.
4. **Static guardrail:** full-period return is at least 0.9× LIVE's, and MDD is worse by no more than 5 points.
5. **Robustness:** ±20% nudges of each key parameter still beat LIVE full-period on the primary setup.
6. **Mechanism:** a plain-language reason it should work, and a small, reviewable code change.

**May change:**
- growth's strategy logic and parameters: `GROWTH_PROFILE`'s PortfolioConfig/ExitConfig fields;
- growth scoring in `stock_signal.py` / `scan_workflow.py`;
- satellite selection in `portfolio_construction.py`;
- growth universe auto-add rules;
- growth scan cadence;
- any ops bug that stops or distorts growth trading or its state.

Keep new behaviour profile-scoped, so the dividend profile's behaviour is byte-for-byte unchanged.

**Must never change without the user:**
- the dividend profile, or anything that changes dividend behaviour;
- `risk_engine.py` limits: max capital at risk, the 25% drawdown halt, short permissions;
- the autopilot setting;
- position caps above 35% of capital;
- a stop wider than 25%, or removing the stop;
- capital amounts;
- `order_execution.py` / `tiger_order_adapter.py` / `tiger_client.py` order mechanics or credentials;
- `render.yaml`;
- pushing `config/*.json`;
- placing or cancelling orders by hand.

**Process for every ship:**
- At most **one strategy change per week**, so its live effect can be attributed.
- Implement it with unit tests and run the **full** `pytest` suite (all must pass).
- Commit with the evidence table in the message, then push `master:main`. Render auto-deploys. Retry on
  non-fast-forward; the state bot pushes config often.
- Append an entry to `research/shipped_changes.md`: date, commit hash, change, evidence, a live measurement
  plan, and a rollback trigger.

**Rollback:**
- Revert immediately, without asking, if a shipped change breaks scans, produces zero growth orders when the
  harness would trade, or fails tests.
- After 4+ live trading weeks, revert if live growth trails the harness's pre-change LIVE counterfactual over the
  same period by more than 3% of capital. Revert with `git revert <hash>`, tests, and a push.

### 5. Record and report — always, every week
- Append a dated entry to `research/stock_hypotheses.md` and update `research/idea_backlog.md`.
- Commit `research/**` together with any shipped `src/`/`tests/` change. Never commit `config/*.json`: run
  `git checkout -- config/` before merging.
- **Send ONE Telegram every week** (`telegram_notifier.get_telegram_config` + `send_message`), with the
  prefix `[OPTIONS AGENT - STOCK STRATEGY RESEARCH]`. It contains:
  - health status;
  - the week's growth P&L vs dividend vs SPY;
  - what shipped or was fixed, with commit and evidence;
  - the top 3 candidates and what each still needs;
  - anything that needs the user's decision.

  Keep it short and plain.

## Known harness facts
- **Current live config in harness terms: `Params(score_mode='trendq', sector_tilt_w=0.1)`**
  (`shipbar.LIVE_PARAMS`). The sector tilt was added on 2026-10-31: live's confidence gate has always carried it,
  and with it the harness reproduces live's 10/26 satellite picks. Every "LIVE" number logged before 10/31
  leaves it out, so those overstate live. `Params()` alone is the old momentum-ranked config, kept so the earlier
  logs reproduce. Compare every new idea against `LIVE_PARAMS`.
- `research/harness.py` covers commissions, the daily scan cadence, the 20% stop, the live band, the sector tilt,
  and an optional halt. It ignores dividends and the 0.3 × yield score term, news and regime tilts, the breadth
  caution factor, shorts, and HK/SG names.
- **Full-period results on the halt-on setup are chaotic.** Starting LIVE at $4,600 instead of $5,000 moves it from
  +1413% to +74%, because the halt blocks every order and can freeze a path for years. Before believing a
  full-period number, run the paired capital sweep in `exp_1031d.py` / `exp_1031e.py`.
- The full universe is hindsight-biased; the static universe is the honest guardrail.
- The live system has run on the full/effective universe since 2026-08.
- `exp_1010.compare` uses `harness.windows`, whose default argument binds `WINDOWS` at import time (W4 ends
  2026-10-03). To extend W4, override `X.windows` at module level, as `exp_1024.py` does.
- History: see `stock_hypotheses.md`. Already rejected or weak: faster exits (SMA, crash, peak, trailing), ATR
  stops, rolling-peak halt, exits-through-halt, correlation caps, vol-adjusted ranking, inverse-vol sizing,
  min-hold, a SPY200 entry gate, cooldowns. Band 0.4–0.6 and rank-buffer are borderline.
