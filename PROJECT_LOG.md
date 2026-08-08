# Claude Trading Agent — Project Log

*A running record of what this project is, how it was built, and the engineering
judgment calls behind it. Written to be reusable as a portfolio piece / case
study, not just a changelog.*

## What it is

An automated trading agent for Tiger Brokers (Singapore), running two portfolios:

- **Growth** — $1,000, momentum + dividend-yield stock/ETF strategy across
  US/HK/SG markets, with tactical short-selling gated on macro signals.
- **Dividend** — a $30,000-target income portfolio, dormant until funded,
  tracked as a separate ledger in the same brokerage account.

It scores candidates daily, proposes trades with full rationale, and shows
them on a live dashboard for one-click human approval — nothing places a real
order without that click. Deployed on Render (free tier), state synced
through GitHub's API since the free tier has no persistent disk, notified via
Telegram.

**At a glance (as of this log):**
| | |
|---|---|
| Source modules | 31 files, ~3,460 lines |
| Test files | 31 files, ~3,740 lines, **300 tests, all passing** |
| Commits | 60+ |
| Real capital tracked | $1,000 (growth), $30,000 target (dividend, unfunded) |
| Uptime | Render free tier + UptimeRobot keep-alive, GitHub-synced state survives every redeploy |
| Real trades placed | 4 (paper account), fully reconciled against broker fill data |

## The build, in phases

**Phase 1 — Options income agent (2026-07-26).** Started as a premium-selling
options strategy: Black-Scholes backtest engine, credit spread logic, a risk
engine with hard limits (max drawdown, max daily loss, per-trade caps,
kill switch). Tiger API connectivity confirmed end-to-end against a real
paper account.

**Phase 2 — Pivot to stock/ETF (2026-07-31).** The options approach was
scrapped in favor of a multi-market core-satellite equity strategy — broad
ETFs and dividend names for stability, momentum stocks for growth, across
US/HK/SG. All options-specific code was removed (git history keeps it if
ever needed). The risk engine carried over almost unchanged — the mechanics
turned out to be asset-agnostic. Built a real backtest against 2.5 years of
Tiger's own historical data: **113.2% total return, 38 rebalance periods,
12.3% max drawdown**, with an honest write-up of the backtest's own
limitations (selection bias in the hand-picked momentum universe, a strong
bull-market window, HK board lots too expensive for the account size).

**Phase 3 — Real order execution (2026-08-01).** First live trade placed
against the paper account. Found and fixed a real bug here: lot-size
rounding was rounding *up* to the nearest board lot, which could push a
position's notional above its risk cap and get the whole order rejected —
changed to floor instead, so a slightly undersized fill is preferred over a
hard rejection.

**Phase 4 — Cloud deployment (2026-08-04).** Windows Task Scheduler jobs
were firing hours late whenever the laptop wasn't active (confirmed
directly — a 6pm job once ran at 10:09pm). Moved the dashboard and
Telegram jobs to an always-on Render service. Since Render's free tier
wipes disk on every redeploy, built a small state-sync layer
(`github_state_sync.py`) using GitHub's Contents API as a zero-cost durable
store — no database, no paid disk.

**Phase 5 — Positioning signals and an approval workflow (2026-08-06).**
Added CFTC Commitment of Traders data (free, public, weekly) as a
market-crowding signal, an automated daily news-sentiment scan (deliberately
using a structured API instead of an LLM/web-search agent, to keep zero
prompt-injection surface in the unattended path), and replaced "trades only
happen if you run a local script" with a dashboard workflow: Scan → proposed
trade with rationale and projected impact → human clicks Approve → order
placed. Renamed the project along the way.

**Phase 6 — Shorting, a second portfolio, and market breadth
(2026-08-08).** The biggest single pass: tactical short-selling gated on
macro signals rather than any momentum dip, a second $30,000-target dividend
portfolio sharing the same brokerage account, and an RSP/SPY market-breadth
signal. See "Engineering highlights" below for how these were actually built.

**Phase 7 — Production incident and hardening (2026-08-08, same day).**
A user-reported balance discrepancy turned into a real data-integrity bug
hunt — see "Bugs found and fixed" below. Ended with the ledger corrected
against ground truth and two new hard guardrails against the same failure
recurring.

## Engineering highlights

**Verify assumptions against the actual SDK, not documentation or
inference.** Before building short-selling, the natural assumption is "the
broker API needs a `SELL_SHORT` order type." Instead of assuming, I read
`tigeropen`'s installed source directly and confirmed it only has
`BUY`/`SELL` — a short is just a `SELL` you don't have shares to cover. That
one check meant shorting could be built as a pure strategy/risk-layer
concept with **zero changes to the order-placement code path** — a target
notional just goes negative, and the existing buy/sell reconciliation math
(`target_qty - current_qty`) already produces the mechanically correct
orders for opening, adding to, partially covering, and fully covering a
short. Smaller, safer diff than assuming a new order type was needed.

**A hard architectural constraint, found before it caused a data-corruption
bug, not after.** The two portfolios share one brokerage account, and Tiger
reports one combined position per symbol for the whole account — it has no
concept of "these shares are the dividend ledger's, those are growth's."
Rather than build cross-attribution logic, the two portfolios' universes are
kept **symbol-disjoint by design**, enforced by an assertion at import time
and unit tested, so a future accidental overlap fails loudly at startup
instead of silently corrupting two ledgers.

**Reused statistical machinery instead of inventing new formulas.** The
market-breadth signal (RSP/SPY ratio, trend + "is this move stretched"
z-score) uses the exact same z-score-against-trailing-history technique
already built for the CFTC positioning signal — new data source, same
proven math, consistent behavior.

**Every real trade instruction is derived, not authored per-portfolio.**
`PortfolioProfile` bundles universe, risk config, allocation config, and
state file paths into one object; the entire scan → risk-gate →
approval pipeline is written once and parametrized by profile, so the
dividend portfolio required zero new business logic — only new config
(a different universe, yield-first scoring weights, its own risk cap).

## Safety and risk engineering

This is a real-money-shaped system (currently paper-traded), so the risk
posture was treated as a first-class design concern, not an afterthought:

- **Every proposed trade passes through one risk engine** (`RiskEngine.validate_trade`)
  before it can ever be approved — hard caps on capital at risk, per-trade
  size, concurrent positions, daily loss, and a 25% max-drawdown circuit
  breaker that halts all new trading regardless of how attractive a
  candidate looks.
- **Shorts get an additional, dedicated risk gate** (aggregate short-exposure
  cap, symmetric stop-loss) since a short's downside is theoretically
  unbounded, unlike a long position which floors at zero.
- **The human-approval boundary is enforced architecturally, not just by
  convention.** The scheduler can score candidates and write proposals; it
  can never place an order. The *only* code path that ever calls the
  broker's order-placement API is triggered by a human's own HTTP request
  (clicking Approve), and that route re-validates risk against freshly
  fetched positions before doing anything — the scan-time snapshot is
  never trusted for the actual placement decision.
- **No autonomous escalation.** The end goal discussed for this project is
  eventually running both portfolios "on autopilot" — that has been
  explicitly scoped *out* of every pass so far, with the reasoning written
  down: it's a deliberate future decision that needs a funded track record,
  proven shorting behavior, and safety rails (per-day trade caps, a kill
  switch reachable without a code deploy) this project doesn't have yet.

## Bugs found and fixed

A representative sample — the ones that mattered:

1. **Lot-rounding could breach a risk cap.** Rounding to the *nearest* board
   lot could push a position's notional slightly above its target, tripping
   the risk engine and rejecting the whole order. Fixed to floor instead.

2. **Sell-side commission was doubling its own effect.** Commission was
   being *added* to sell proceeds instead of subtracted, overstating cash
   on every future sell — never exercised before since every prior real
   trade had been a buy. Caught while writing a regression test during a
   later refactor, not in production.

3. **The dashboard never actually refreshed.** Capital and positions only
   reflected a 30-minute-old snapshot and a once-a-day mark-to-market —
   reloading the page never showed anything new in between. Fixed to fetch
   live from the broker on every page load, with a graceful fallback and
   visible "data unavailable" banner if the broker API is briefly
   unreachable.

4. **A real $537 accounting drift, root-caused from first principles.** A
   user report ("the balance still looks wrong") turned into pulling the
   account's actual filled-order history directly from the broker and
   reconstructing what `cash_reserve` *should* be from ground truth — it
   should have been $361.30; the ledger had drifted to $898.59. The
   evidence pointed to a specific mechanism: one trade's recorded cost
   matched the *sizing-time estimate* rather than the real fill+commission,
   meaning it had gone through a fallback code path *and* been applied
   against a ledger that had been silently reset to a fresh baseline at
   some point, losing real prior history. Fixed by recomputing the correct
   value from the broker's own records and pushing the correction through
   the same tested code path every other ledger update uses (not a
   hand-edited JSON patch).

5. **The fix for #4 had its own side effect, caught before it mattered.**
   Correcting the inflated capital figure left three phantom high-water
   entries in the equity history, which made the *honest* number look like
   a 34.5% drawdown from a peak that was never real — silently tripping the
   25% max-drawdown halt and blocking all future trading. Caught by
   re-running the scan after the fix and noticing the halt message, not
   assumed away.

6. **Root cause addressed, not just the symptom.** Bug #4's actual root
   cause was a local script being run in a shell session without the
   GitHub sync credentials set, which failed *silently* rather than
   refusing — meaning a real trade got sized and recorded against a
   possibly-fresh/stale ledger with no error at all. Added a hard,
   loud pre-flight check: the live-trading CLI and the dashboard's
   approval route now both refuse outright, with a clear explanation,
   if those credentials aren't present — instead of trading quietly
   against a state nobody can trust.

## Testing discipline

300 tests across 31 test files (slightly more test code than source code by
line count). The convention held throughout: every module that touches a
network call splits into a `fetch_*` (network, untested) and `parse_*`/pure
function (unit tested with synthetic data, no network in any test run).
Every bug fix above shipped with a regression test that fails on the old
code and passes on the new. New risk-engine behavior includes an explicit
test that *omitting* the new parameter reproduces every pre-existing test
unchanged — a deliberate check that extending shared, safety-critical code
didn't silently change its default behavior.

## What's next

- Verify Tiger's real short-position data shape (`quantity`/`market_value`
  sign convention) with one small real short before trusting the short
  P&L math with actual capital.
- Fund the dividend portfolio and let it accumulate real trading history.
- A visual, sourced "why this trade" rationale card for proposed trades
  (technical indicators + news sourcing), and a proper per-stock/sector
  breadth indicator set — scoped but not yet built.
- Autopilot for both portfolios — explicitly deferred until there's a real
  track record and additional safety tooling to back it.
