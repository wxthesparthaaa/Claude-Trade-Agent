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

### 2026-10-02 (Fri, week of 9/28–10/2) — first routine run

**State pull.** `pull_state_from_github()` returned `config/decision_log.json` empty (Contents API >1MB drop;
`src/github_state_sync.py` does NOT handle this). Fetched it via raw.githubusercontent.com (1,054,339 bytes).

**Week review — growth placed ZERO orders this week.** Tiger `get_filled_orders` 9/28–10/2: 12 fills, all
dividend symbols (ABBV/JEPI/MO/KO/SPYD). Last growth fill: 2026-09-21. So no closed trades, win rate/payoff
n/a, $0 commissions, no stop-outs or re-entries. For context, 9/14–9/21 (6 sessions): 27 growth orders
≈ $80 commission (pre-H1).
Live growth positions (Tiger, 10/2): AEHR 6, ALAB 1, MRVL 2, XLK 2, IWM 1. Market value ≈ $2,250, unrealized
≈ +$277. Satellite = 100% semis (AEHR/ALAB/MRVL).

**Operational faults found (NOT strategy; outside research scope — src/ not touched, flagged to the user):**
1. `config/decision_log.json` passed 1 MiB on 9/21 (its last GitHub commit is 9/21 21:35 SGT). From then on,
   `pull_state_from_github` writes it as a 0-byte file and `decision_log.write_decision_log` would `json.load`
   an empty file. That is consistent with every growth scan since 9/22 failing: no growth decisions, no growth
   fills, while dividend (383 KB log) kept trading daily. Strongly suspected, not confirmed from Render logs.
2. `reporting.py` daily mark-to-market calls `refresh_snapshot(..., profile.universe, ...)`, the STATIC
   universe. It therefore omits the auto-added satellites (AEHR/ALAB/MRVL ≈ $1,560). The ledger reads $3,627,
   but cash $2,948 + live positions ≈ $5,195, which is above the $5,135 peak. The "29.5% drawdown" in the
   baseline above is an artifact. `scan_workflow` also sizes targets off `latest_capital(ledger)`, i.e. off
   the understated figure.
   → Drawdown halt: the scan itself appends live capital (≈$5.2k) to the curve, so it would NOT be halted.
   But the scan isn't running (item 1).

**Hypotheses vs this week:** H1, H2, H3 — **no evidence** (no growth scans or orders ran). H3: no new
auto-adds since 9/06; the existing satellite pool is still semis-only.

**Harness built (closes all three "Known harness gaps"):** `research/harness.py`
- $2.98/order, daily scan-at-open with fills at the open, integer shares
- live reconcile + band rule, confidence gate on new entries only
- 20% stop from average cost, momentum-reversal exit
- optional 25% halt that blocks ALL orders (as live)

Bars come from `research/fetch_bars.py`: Tiger, 2019-08 → 2026-10, 41 US symbols, cached and gitignored.
Universes:
- "static" = code universe, US only. Less biased; this is the primary universe.
- "full" = static + extra_universe semis. Hindsight-picked, so biased.

Simplifications: no dividends, news, sector or regime tilts, shorts, or HK/SG names.
Rolling windows: W1 20/03–21/09, W2 21/09–23/03, W3 23/03–24/09, W4 24/09–26/10.
Scripts: `experiments.py` (sweeps), `robust.py` (escalation-bar check), `walkforward.py`.

**Results (live config, 2020-03→2026-10, $5k):**

| Config | Static universe | Full universe |
|---|---|---|
| Live (band 0.2, stop 0.2) | +305%, MDD 28.9%, 815 orders, $2.4k commissions | +1318%, MDD 51% |
| Old (band 0, stop 0.15) | +23%, MDD 30.6%, 1,094 orders | +510% |

The old config's +23% includes 1,002 days frozen by the halt.

- **H1 band** — supported. Band 0: +118% vs +310% (halt off), $6.6k vs $2.5k commissions. Bands
  0.1–0.6 are all similar to each other.
- **H2 20% stop** — supported vs 10–15%. 15%: +275%, W4 +22% vs +29%. 25–30% and no stop are about equal
  to 20%. The stop rarely binds (14 stop-outs in 6.5 yrs).
- **H4 cooldown** — inconclusive. Static: 5/10/20d ≤ base. Full: 5d/20d helped. Mixed, drop priority.
- **H6 momentum windows** — 126/21 is fine. 189/21 and 252/21 are much worse in 2022 on static. 126/5 has
  higher return but a higher MDD. No change.
- **H7 SPY>200d entry gate** — no help: static +296% vs +310%, full +520% vs +701%.
- **H8 satellite count** — 3 is best on static. 2 wins on full, but that is semis-hindsight. No change.
- **H9 min order size** — irrelevant once the band exists: $100/$200 change nothing, $400 is noise.
- **H10 ATR/trailing stops** — trailing 15–25% hurts (more whipsaw). ATR×4 slightly better on static
  (+367%), ATR×2–3 worse. Not robust.
- **H11 confidence** — conf 80 alone: +386% vs +310% static, half the orders, 3/4 windows on both
  universes. **But knife-edge:** a ±20% score nudge (conf 75 / 84) fails, and with the halt on it wins only
  2–3 of 12 staggered starts.
- **Cadence** — weekly scan with weekly exits (cad5x): +358% static, +1,020% full (halt off). Fails the
  drawdown leg on static: W2 MDD +5.5 pts, and cad4x/cad6x +6–7 pts.
- **Momentum-reversal exit off** — +468% static, but W2 −18% vs −12.5% and MDD +4.8 pts. That is a 2022
  bear-market tradeoff, not a free lunch.

**Best candidate: band 0.5 + conf 80.**
- Halt off: passes on both universes — 3–4/4 windows, MDD better, 12/12 staggered starts, band 0.4/0.6
  nudges pass.
- Halt on, full universe: only 5/12 staggered starts.
- Conf nudge fails: conf 75 + band 0.5 wins 2/4 windows.
- Walk-forward (tune 2020–23, test 2023–26, band×conf grid): the in-sample pick beat LIVE out-of-sample in
  all 4 settings (static/full × halt on/off), e.g. static/halt: +157% vs +129%, MDD 25.9% vs 29.7%.
  With the halt off on static, LIVE ranked 20/20 out-of-sample.

**Verdict:** wider band (0.4–0.6) is the most consistent improvement found. It is robust on the static
universe but mixed on the semis-heavy full universe. The conf 80 gain is not robust to nudges.
**Nothing meets the escalation bar → no Telegram.**

**New hypotheses:**
- H12: the 25% halt blocks exits too, so a halted portfolio is frozen and path-dependent. Variants swung by
  up to −250 pts per window purely from halt timing. Consider letting stop/exit orders through a halt.
  Needs the user's design call.
- H13: decision-log growth >1 MiB silently breaks state sync (ops, see above).

**Next step:**
- Re-test band 0.5 alone on the full universe with more start offsets and halt-on.
- Add a dividend-yield term and sector tilt to the harness.
- Re-measure H1/H2 live once growth scans actually run again.

### 2026-10-10 (Sat, week of 10/5–10/9) — second routine run

**State pull.** Same as last week: `pull_state_from_github()` wrote `config/decision_log.json` as 0 bytes, so
I fetched it via raw.githubusercontent.com (1,054,339 bytes). It is **unchanged since 2026-09-21**. The last
GitHub commits of `decision_log.json` and `trade_journal.json` are both 9/21. Only `strategy_ledger.json`
updates; that is the daily 18:00 SGT mark-to-market.

**Week review — growth placed ZERO orders for the 3rd straight week.** Tiger fills 10/5–10/9:
- 13 fills, all dividend symbols (MO, ABBV, SPYD, VZ, JEPI, KO). Out of scope here.
- Growth: no closed trades, win rate and payoff n/a, $0 commissions, no stop-outs, no re-entries.

Live growth positions (Tiger, 10/10):

| Symbol | Shares | Avg cost | Price |
|---|---|---|---|
| AEHR | 6 | 88.94 | 84.71 (−4.8%) |
| ALAB | 1 | 296.81 | 339.81 |
| MRVL | 2 | 234.72 | 274.71 |
| XLK | 2 | 191.24 | 198.80 |
| IWM | 1 | 287.06 | 278.81 |

- Market value ≈ $2,074. Unrealized P&L ≈ +$104, down from ≈ +$277 on 10/2.
- Satellite is still 100% semis.
- These positions are **unmanaged**: no stop, momentum-exit, or rebalance check has run on them since
  9/21.
- Ledger capital is $3,626 (understated, see the 10/02 item 2), which reads as ~29% below the $5,135 peak.
  Whether the halt would be "active" is moot while the scan isn't running.

The operational faults from 10/02 (H13 decision-log >1 MiB; static-universe mark-to-market) look
unresolved. **This is the most important finding for the user**, and it is still outside research scope
(src/ not touched).

**Hypotheses vs this week:**
- H1, H2, H3: **no evidence**. No growth scans ran.
- H3: no new auto-adds.

**Harness changes** (`research/harness.py`, all off by default; LIVE results unchanged):
- `halt_mode='exits_ok'`: a halt blocks buys only.
- `halt_reset=N`: re-base the peak after N halted days.
- `group_cap`: max satellites per GICS industry group, from `config/sector_tags.json`.
- `corr_cap`: skip a satellite whose 63d return correlation with an already-picked one is above the cap.
- `score_mode='mom_vol'`: rank by momentum ÷ 63d volatility.

New robustness test: **universe jackknife**, i.e. 20 random universes that keep 70% of the satellites.
It checks that a win doesn't depend on which symbols happen to be in the universe.

Bars refreshed through 2026-10-09. Script: `research/exp_1010.py`. Outputs: `research/data/exp_1010_*.txt`.
Each test reports:
- the 4 rolling windows vs LIVE;
- staggered starts (12, or 24 every 2 months for band);
- the jackknife;
- halt on and off.

LIVE, 2020-03 → 2026-10-09:

| Universe | Halt on | Halt off |
|---|---|---|
| Static | +300%, MDD 28.9% | +305% |
| Full | +1275%, MDD 51.4% | +677% |

**Results (candidate vs LIVE):**

| Candidate | Universe / halt | Windows | Staggered starts | Jackknife | Full-period return vs LIVE (MDD) |
|---|---|---|---|---|---|
| band 0.4 | static / on | 3/4 | 14/24 | 13/20 | 349% vs 300% |
| **band 0.5** | static / on | 3/4 | **22/24** | **15/20** | 405% vs 300% (MDD 26.4 vs 28.9) |
| band 0.6 | static / on | 4/4 | 15/24 | 11/20 | 375% vs 300% |
| band 0.4 / 0.5 / 0.6 | static / off | 3/4, 3/4, 4/4 | 23/24, 24/24, 23/24 | 15/20, 16/20, 17/20 | 355%, 390%, 392% vs 305% |
| band 0.4 | full / on | 1/4 | 8/24 | 10/20 | 191% vs 1275% (halt froze it) |
| band 0.5 | full / on | **2/4** | 14/24 | 11/20 | 1247% vs 1275% |
| band 0.6 | full / on | 4/4 | 19/24 | 13/20 | 1664% vs 1275% |
| band 0.5 | full / off | 3/4 | 14/24 | 11/20 | 684% vs 677% |
| grpcap1 (1 semi max) | full / off | 3/4 | 12/12 | 5/20 | 958% vs 677%, MDD 38.3 vs 45.8 |
| grpcap1 | full / on | 3/4 | 2/12 | 6/20 | |
| grpcap1 | static / on | 1/4 | | 3/20 | |
| grpcap2 | full / off | 3/4 | 12/12 | 10/20 | |
| grpcap2 | static | 2–3/4 | | 3/20 | |
| corr 0.6–0.9 | all | 0–3/4 | 0–10/12 | 2–12/20 | **worse** |
| mom_vol (± band 0.5) | all | 0–2/4 | 0–1/12 | 1–11/20 | **clearly worse** (static +184% vs +300%) |
| exits_ok (halt) | all | 0/4 | 0/12 | | **far worse**: once it is in cash below the peak it never re-arms (static +194%, full +70%) |
| exits_ok + reset60 | all | 0/4 | 1–4/12 | | worse |
| all + reset60 | all | 0/4 | 1–2/12 | | worse |
| all + reset20 | all | 0–1/4 | 1–6/12 | | worse |

**Verdict:**
- **H1 (band):** the wider-band result replicates on refreshed data with 2× the starts and the new jackknife.
  On the static universe, band 0.4–0.6 beats LIVE in every halt mode: 3–4/4 windows, 22–24/24 starts,
  13–17/20 jackknife, and MDD never worse by more than 1.6 points. On the semis-heavy full universe (what
  live actually trades) it is still mixed: band 0.5 with the halt on wins 2/4 windows, and nudges 0.4 vs 0.6
  swing from −1085 to +389 points. That swing is halt path-dependence, not the band itself. The per-window
  gains are also small (+1.5–2.3 points in W2/W3, −0.3 in W4); most of the edge is W1 compounding. So it
  does **not** meet "≥3/4 windows on the live setup". No escalation.
- **H5 diversification:** a GICS group cap of 1 sharply cuts drawdown on the full universe (MDD −8 to −10
  points per window with the halt off). But it fails the jackknife (5/20) and the static universe (1/4). A
  correlation cap is worse at every threshold. Reject a correlation cap. A group cap is a risk-control
  choice, not a return improvement, so it stays open as a design question for the user.
- **H12 halt redesign:** "let exits through" is worse unless the halt can re-arm. With no re-arm, a stopped-out
  portfolio sits in cash forever, because cash can't recover to the peak. Every variant tried lost to LIVE.
  If the user ever redesigns the halt, it needs a re-arm rule. None of the ones tried (20/60-day re-base)
  helped. Drop H12 as a return lever.
- **H14 (new: vol-adjusted momentum ranking):** rejected, worse everywhere.
- **Nothing meets the escalation bar → no Telegram.**

**Next step:**
- Re-measure H1–H3 live once growth scans resume. The ops fault (H13) is blocking all live evidence.
- If band is revisited: rerun the walk-forward with the jackknife on the full universe with the halt on.
  Also try a halt that measures drawdown on a trailing 1-year peak instead of the all-time peak. The halt
  path-dependence is what makes every full-universe verdict noisy.
