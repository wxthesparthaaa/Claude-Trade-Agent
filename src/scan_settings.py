"""
User-adjustable knobs for the growth portfolio's confidence-gated scan
pipeline -- persisted separately from PortfolioProfile (which stays a
static, code-defined singleton) so these can change at runtime via the
dashboard's settings panel without a redeploy.

Same "create with defaults if missing" pattern as strategy_ledger.
load_or_init_ledger. Saving is a plain local write; callers (app.py)
push to GitHub afterward, same convention as pending_approvals.py.
"""
import json
import os
from dataclasses import asdict, dataclass


@dataclass
class ScanSettings:
    autopilot: bool = False
    execute_threshold_pct: float = 70.0
    shortlist_threshold_pct: float = 50.0
    max_concurrent_trades: int = 10
    capital: float = 1000.0


def load_scan_settings(path: str) -> ScanSettings:
    if not os.path.exists(path):
        return ScanSettings()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    defaults = ScanSettings()
    return ScanSettings(
        autopilot=data.get("autopilot", defaults.autopilot),
        execute_threshold_pct=data.get("execute_threshold_pct", defaults.execute_threshold_pct),
        shortlist_threshold_pct=data.get("shortlist_threshold_pct", defaults.shortlist_threshold_pct),
        max_concurrent_trades=data.get("max_concurrent_trades", defaults.max_concurrent_trades),
        capital=data.get("capital", defaults.capital),
    )


def save_scan_settings(path: str, settings: ScanSettings) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)


def validate_scan_settings(settings: ScanSettings) -> None:
    """Raises ValueError with a human-readable message on the first
    violation -- callers (the /settings route) turn this into a
    dashboard message rather than a 500."""
    if not (0 < settings.shortlist_threshold_pct < settings.execute_threshold_pct < 100):
        raise ValueError(
            "Shortlist threshold must be less than execute threshold, and both must be between 0 and 100."
        )
    if settings.capital <= 0:
        raise ValueError("Capital must be greater than 0.")
    if settings.max_concurrent_trades <= 0:
        raise ValueError("Max concurrent trades must be greater than 0.")
