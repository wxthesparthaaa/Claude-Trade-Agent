# options-agent

AI-assisted options trading agent for Tiger Brokers (Singapore), deployed
on Render.com, monitored by UptimeRobot.

## Status
- [x] Tiger developer account registered (Tiger ID 20160815, license TBSG)
- [x] Live (Prime) account and Paper account identified
- [x] Local connectivity test passing (paper account, auth + trade + quote)
- [ ] Options trading permission confirmed on live account
- [ ] API market data subscription confirmed active (only needed before live real-time trading)
- [x] Risk/rules engine (src/risk_engine.py) with unit tests
- [x] Strategy layer (src/strategy.py) -- candidate generation + portfolio selection, unit tested
- [x] Tiger option chain adapter (src/tiger_option_adapter.py) -- parsing logic unit tested
- [x] Live chain fetch confirmed against paper account -- blocked on paid US OPT data permission (expected, not a bug)
- [x] Backtest engine (src/options_pricing.py, src/backtest.py) using free historical stock data + Black-Scholes model, unit tested
- [ ] LLM sentiment scorer
- [ ] Order execution module (wires strategy + risk engine to real Tiger orders)
- [ ] Render deployment
- [ ] UptimeRobot monitoring

## Backtest sanity check (simulated, not yet run on real AAPL data)
A single 20-delta weekly cash-secured put on a realistic-ish simulated
price series averaged ~0.4% weekly yield -- well below the ~2-2.5% weekly
needed for the $500/week target on $20k-25k. This is a model estimate, not
final -- scripts/run_backtest.py runs the same engine on real historical
AAPL prices. Expect the real target to require either more aggressive
strike selection (higher risk) or accepting a lower/more variable average,
consistent with the earlier income-target math.

## Weekly income target
Target: $500/week, capital range $20,000-$25,000. See scripts/income_target_check.py
for the required yield math -- at this range it's ~2-2.5% weekly (~104-130%
annualized), which is aggressive relative to a conservative premium-selling
approach. The risk engine's hard limits always take precedence over this
target; a week that can't safely hit $500 should produce less than $500,
not a riskier trade. Diversifying across ~5 positions (20% of capital cap
each) is the current default rather than concentrating in one underlying.

## Local setup
1. `python3 -m venv venv && source venv/bin/activate`
2. `pip install -r requirements.txt`
3. Copy your **paper account** properties file to `config/tiger_openapi_config.properties`
   (see config/README.md)
4. `python scripts/test_connection.py`

## Security notes
- `config/*.properties`, `*.pem`, `.env` are git-ignored — never commit credentials.
- Regenerate RSA keys via the Tiger Developer Info page if they've ever been
  shared outside this local environment.
- The live account file is only ever used once TIGER_ENV is explicitly set
  to "live" after a validated paper-trading run.
