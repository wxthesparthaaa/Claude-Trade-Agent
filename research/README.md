# Stock strategy research routine (Options Agent / growth portfolio ONLY)

**Scope — read this first.** This routine belongs to the **Options Agent repo**
(`options-agent`, Tiger Brokers, the *growth/stock* portfolio). It is **not** the
Forex Agent project's routine and must never read, edit, or message about that
project. The **dividend** portfolio is out of scope: its weekly review was simply
removed, with no research routine.

## What replaced the weekly review

| Before | Now |
|---|---|
| Saturday 9:00 SGT Telegram "review" (lessons + proposed changes), both portfolios | Saturday 9:00 SGT Telegram **P&L summary** (both portfolios, `reporting.run_weekly_summary`) |
| — | Saturday Claude research routine, **growth only** (this file) |

## Routine (runs every Saturday, after the week's trading has closed)

1. **Pull the data.** Sync state (`github_state_sync.pull_state_from_github`). If
   `config/decision_log.json` comes back empty, GitHub's Contents API dropped it for
   being >1MB — fetch it from the file's `download_url` instead.
2. **Review the week's trades** (`config/trade_journal.json`, `config/decision_log.json`,
   `config/strategy_ledger.json`, real fills/commissions via `TradeClient.get_filled_orders`):
   trades, win rate, payoff ratio, commissions paid vs realized P&L, order count,
   stop-outs followed by re-entry, sector concentration. Note whether the drawdown
   halt was active — a halted week says nothing about any hypothesis.
3. **Reflect against the hypotheses** in `research/stock_hypotheses.md`: did this
   week's evidence support, contradict, or say nothing about each active hypothesis?
4. **Self-backtest aggressively and keep iterating** — new hypotheses, refinements,
   parameter sweeps, walk-forward tests — until a credible idea emerges or the
   session's budget is spent. No approval needed for any of this.
5. **Record everything** by appending a dated entry to `research/stock_hypotheses.md`
   (what was tested, numbers, verdict, next step). Put scripts/outputs under
   `research/` too.
6. **Escalate only if warranted** (below). Otherwise stay quiet — no Telegram.

## Autonomy boundary

Free to do without asking: run backtests, write research scripts, fetch historical
bars/dividends/fundamentals, update `research/**`, commit and push `research/**` only
(Render ignores that path).

**Never without the user's explicit approval:** edit anything under `src/`, `app.py`,
`templates/`, or profile config; change live strategy parameters; push anything under
`config/`; place/cancel orders; deploy. A winning idea is *proposed*, not shipped.

## Escalation bar — "significantly improves"

Message the user (Telegram, prefixed `[OPTIONS AGENT - STOCK STRATEGY RESEARCH]`, plus an
`ESCALATE` entry in the log) only when a candidate beats the **current live config**:

- out-of-sample / walk-forward, not just in-sample;
- **after real commissions** (~$2.98 flat per order) and the live scan cadence;
- better in at least 3 of 4 rolling windows, and max drawdown no worse by >5 points;
- still better when its key parameters are nudged ±20% (not a knife-edge fit);
- with a plain-language mechanism for *why* it should work.

The message must include the proposed change, the evidence table, and the caveats.

## Known harness gaps (fix these first)

`src/stock_backtest.py` (a) models **no commissions**, (b) holds each pick at a fixed
weight for the whole rebalance period, so it never exercises the live system's
per-scan drift re-targeting, and (c) uses the 15% default stop unless told otherwise
(live growth uses 20%). Build a commission-aware, scan-cadence-faithful harness under
`research/` before trusting any new backtest verdict.
