# options-agent

AI-assisted options trading agent for Tiger Brokers (Singapore), deployed
on Render.com, monitored by UptimeRobot.

## Status
- [x] Tiger developer account registered (Tiger ID 20160815, license TBSG)
- [x] Live (Prime) account and Paper account identified
- [ ] Options trading permission confirmed on live account
- [ ] API market data subscription confirmed active
- [ ] Local connectivity test passing (paper account)
- [ ] Risk/rules engine
- [ ] LLM sentiment scorer
- [ ] Order execution module
- [ ] Render deployment
- [ ] UptimeRobot monitoring

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
