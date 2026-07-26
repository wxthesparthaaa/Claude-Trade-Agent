"""
Run with:
    python scripts/income_target_check.py

Purely informational -- shows what weekly premium yield is required to hit
the configured weekly income target at different capital levels, and flags
where that yield would require breaking the max_risk_per_trade_pct limit
if attempted on a single position. This does not place any trades.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from risk_engine import RiskConfig, RiskEngine


def main():
    config = RiskConfig(
        max_capital_at_risk=10000,
        max_risk_per_trade_pct=0.10,
        weekly_income_target=100,
    )
    engine = RiskEngine(config)

    print(f"Weekly income target: ${config.weekly_income_target:.2f}")
    print(f"Max risk per trade: {config.max_risk_per_trade_pct:.0%} of capital cap "
          f"(${config.max_capital_at_risk * config.max_risk_per_trade_pct:.2f} on a "
          f"${config.max_capital_at_risk:.0f} cap)\n")

    for capital in (2000, 3000, 5000, 7500, 10000):
        yield_needed = engine.required_weekly_yield(capital)
        annualized = yield_needed * 52
        flag = "  <-- aggressive / high risk for a single position" if yield_needed > 0.02 else ""
        print(f"${capital:>6.0f} capital -> {yield_needed:6.2%} weekly needed "
              f"(~{annualized:6.0%} annualized){flag}")


if __name__ == "__main__":
    main()
