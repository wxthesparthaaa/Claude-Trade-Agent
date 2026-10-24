# Shipped changes to the live growth system

One entry per ship (strategy change or ops fix). Each run checks every open entry against its plan.

| Date | Commit | Type | Change | Live measurement plan | Rollback trigger | Status |
|---|---|---|---|---|---|---|
| 2026-10-24 | 0c207a3a | ops fix | `pull_state_from_github` fetches >1 MB files raw; the decision log tolerates empty/corrupt files and is capped at 60 days; the daily mark-to-market uses the effective universe. | Week of 10/26: `decision_log.json` has an entry for every trading day; growth places orders (AEHR is past its 20% stop, so a sell is expected on the first scan); ledger capital ≈ cash + all growth positions (~$4.6k, not ~$3.6k). | Any scan crash, or still zero growth decisions → diagnose and fix immediately. | open |
