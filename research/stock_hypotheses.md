# Stock strategy hypotheses — living log (Options Agent, growth portfolio)

Append new dated entries at the bottom. Keep verdicts honest: say "inconclusive" when it is.

## Baseline (measured 2026-10-01, before the changes below)

- 12 closed round-trips, win rate 58.3%, avg win +$23.56 vs avg loss -$58.26 (payoff 0.40).
- Total realized P&L -$126.39. Commissions paid on growth: **$146.08 over 49 orders (~90 days)**,
  ~$2.98 flat per order — fees alone exceeded the entire realized loss.
- Cause (decision log): every held position re-targeted to its exact dollar weight on every
  scan (3x/day); AEHR logged ~38 buy/sell decisions in 6 weeks, mostly 1–4 share
  "reduce/increase toward target" trims. Also stop-out → re-buy → stop-out whipsaws (AEHR 9/8
  then 9/14; ALAB).
- 15 of 16 auto-added satellite symbols were in "Semiconductors & Semiconductor Equipment".
- Account peak $5,135 → $3,619 on 2026-10-01 (29.5% drawdown). Drawdown circuit breaker
  (25%) is live: while it is active **nothing trades**, so check it before judging a week.

## Active hypotheses (shipped 2026-10-01/02 — measure them weekly)

| # | Change | Prediction to check each week |
|---|---|---|
| H1 | `rebalance_band_pct=0.20` for growth (no trim/top-up within ±20% of target) | Orders/week and commissions/week fall sharply vs baseline; winners are no longer trimmed while still top-ranked |
| H2 | Stop-loss 15% → 20% for growth | Fewer stop-outs; fewer stop-out→re-entry pairs within 10 days |
| H3 | Max 3 auto-added symbols per sector | New auto-adds are diversified; satellite picks no longer all semis |

## Backtest evidence so far (3 yrs of daily bars, 18 symbols — single window, in-sample, treat as hints)

- Rebalance every N trading days, gross total return: 3d 117%, 5d 146%, 10d 133%, 21d 6.5%, 42d 66%,
  63d 88%. Net of $2.98/order: 3d 101%, 5d 133%, 10d 122%, 21d -1.5%, 42d 62%, 63d 84%.
  No clean "faster = worse" pattern; the module default (21d) was the worst.
- Stop-loss (rebalance 5d, cooldown 10d): 8% 157%, 10% 109%, 15% 166%, **20% 190%**, 25% 129%, 30% 143%;
  exits at 20%: 40 vs 54 at 15%.
- Stop-out cooldown: helped at 5d rebalance (10d cooldown 166% vs 146%), hurt at 3d. Inconclusive.

## Open hypotheses (not yet tested properly)

- H4: cooldown after a stop-out (inconclusive above).
- H5: true diversification — cap by theme/correlation, not just GICS label; prune existing semi pool.
- H6: momentum lookback/skip window tuning (currently 126/21).
- H7: regime/breadth gating of new entries (regime.json breadth + COT already exist).
- H8: fewer, higher-conviction satellite positions vs 3.
- H9: commission-aware minimum order size (skip orders whose notional is small vs the ~$3 fee).
- H10: volatility-scaled (ATR) stop instead of a fixed % stop.
- H11: confidence threshold (execute ≥70%) vs realized outcome — is confidence predictive at all?

## Log
