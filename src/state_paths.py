"""
Centralizes where the strategy's state files live. Defaults to the local
config/ directory (today's behavior, unchanged for local dev/tests);
overridden via STATE_DIR when deployed, since Render's free-tier
filesystem doesn't persist across redeploys and github_state_sync.py
syncs whatever's in this directory to/from GitHub instead.
"""
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_DIR = os.environ.get("STATE_DIR", os.path.join(REPO_ROOT, "config"))

LEDGER_PATH = os.path.join(STATE_DIR, "strategy_ledger.json")
DECISION_LOG_PATH = os.path.join(STATE_DIR, "decision_log.json")
CHANGELOG_PATH = os.path.join(STATE_DIR, "strategy_changelog.json")
NEWS_PATH = os.path.join(STATE_DIR, "news_signal.json")
REGIME_PATH = os.path.join(STATE_DIR, "regime.json")
SNAPSHOT_PATH = os.path.join(STATE_DIR, "portfolio_snapshot.json")
PENDING_APPROVALS_PATH = os.path.join(STATE_DIR, "pending_approvals.json")

# The confidence-gated scan pipeline's settings and watchlist (see
# scan_settings.py / shortlist.py / portfolio_profiles.py's
# confidence_scale) -- one file pair per profile, so growth and
# dividend never share a single settings/watchlist (they have very
# different capital/score scales and must not cross-contaminate).
SCAN_SETTINGS_PATH = os.path.join(STATE_DIR, "scan_settings.json")
SHORTLIST_PATH = os.path.join(STATE_DIR, "shortlist.json")
SCAN_SETTINGS_PATH_DIVIDEND = os.path.join(STATE_DIR, "scan_settings_dividend.json")
SHORTLIST_PATH_DIVIDEND = os.path.join(STATE_DIR, "shortlist_dividend.json")

# Trading journal -- both portfolios (pure record-keeping, no execution/
# risk implications, unlike the confidence system above).
JOURNAL_PATH = os.path.join(STATE_DIR, "trade_journal.json")
JOURNAL_PATH_DIVIDEND = os.path.join(STATE_DIR, "trade_journal_dividend.json")

# Dividends actually earned (see dividend_tracker.py) -- dividend
# portfolio only, computed from its own journal.
DIVIDENDS_EARNED_PATH = os.path.join(STATE_DIR, "dividends_earned.json")

# Self-improvement pause/resume state (see self_improvement.py) -- one
# file per profile, mirroring the Forex Agent sibling project's
# DashboardState.paused_instruments, but never shared between growth and
# dividend since a losing streak in one has nothing to do with the other.
PAUSED_SYMBOLS_PATH = os.path.join(STATE_DIR, "paused_symbols.json")
PAUSED_SYMBOLS_PATH_DIVIDEND = os.path.join(STATE_DIR, "paused_symbols_dividend.json")

# Sector rotation / Investment Clock (see sector_rotation.py,
# investment_clock.py, tiger_industry_adapter.py) -- shared across both
# profiles, since sector heat and the macro clock are market-wide facts,
# not portfolio-specific.
SECTOR_ROTATION_PATH = os.path.join(STATE_DIR, "sector_rotation.json")
INVESTMENT_CLOCK_PATH = os.path.join(STATE_DIR, "investment_clock.json")
SECTOR_TAGS_PATH = os.path.join(STATE_DIR, "sector_tags.json")

# Screener-sourced "add to universe" suggestions and user-approved
# additions (see sector_suggestions.py, universe_extra.py) -- one pair
# per profile, since each portfolio's universe is its own.
SECTOR_SUGGESTIONS_PATH = os.path.join(STATE_DIR, "sector_suggestions.json")
SECTOR_SUGGESTIONS_PATH_DIVIDEND = os.path.join(STATE_DIR, "sector_suggestions_dividend.json")
EXTRA_UNIVERSE_PATH = os.path.join(STATE_DIR, "extra_universe.json")
EXTRA_UNIVERSE_PATH_DIVIDEND = os.path.join(STATE_DIR, "extra_universe_dividend.json")

# Today's most-active/moving stocks per market (see movers.py) -- market-
# wide, like sector rotation, not portfolio-specific.
MOVERS_PATH = os.path.join(STATE_DIR, "movers.json")

# Dividend portfolio's own parallel state files (see portfolio_profiles.py)
# -- deliberately new, suffixed filenames rather than renaming the growth
# portfolio's existing paths above, so there's zero migration risk to the
# real state history already live on Render/GitHub for the growth account.
LEDGER_PATH_DIVIDEND = os.path.join(STATE_DIR, "strategy_ledger_dividend.json")
DECISION_LOG_PATH_DIVIDEND = os.path.join(STATE_DIR, "decision_log_dividend.json")
CHANGELOG_PATH_DIVIDEND = os.path.join(STATE_DIR, "strategy_changelog_dividend.json")
SNAPSHOT_PATH_DIVIDEND = os.path.join(STATE_DIR, "portfolio_snapshot_dividend.json")
PENDING_APPROVALS_PATH_DIVIDEND = os.path.join(STATE_DIR, "pending_approvals_dividend.json")

# Every path above, keyed by its repo-relative name -- used by
# github_state_sync.py to know what to pull/push without hardcoding the
# list twice.
STATE_FILES = {
    "config/strategy_ledger.json": LEDGER_PATH,
    "config/decision_log.json": DECISION_LOG_PATH,
    "config/strategy_changelog.json": CHANGELOG_PATH,
    "config/news_signal.json": NEWS_PATH,
    "config/regime.json": REGIME_PATH,
    "config/portfolio_snapshot.json": SNAPSHOT_PATH,
    "config/pending_approvals.json": PENDING_APPROVALS_PATH,
    "config/scan_settings.json": SCAN_SETTINGS_PATH,
    "config/shortlist.json": SHORTLIST_PATH,
    "config/scan_settings_dividend.json": SCAN_SETTINGS_PATH_DIVIDEND,
    "config/shortlist_dividend.json": SHORTLIST_PATH_DIVIDEND,
    "config/trade_journal.json": JOURNAL_PATH,
    "config/trade_journal_dividend.json": JOURNAL_PATH_DIVIDEND,
    "config/strategy_ledger_dividend.json": LEDGER_PATH_DIVIDEND,
    "config/decision_log_dividend.json": DECISION_LOG_PATH_DIVIDEND,
    "config/strategy_changelog_dividend.json": CHANGELOG_PATH_DIVIDEND,
    "config/portfolio_snapshot_dividend.json": SNAPSHOT_PATH_DIVIDEND,
    "config/pending_approvals_dividend.json": PENDING_APPROVALS_PATH_DIVIDEND,
    "config/paused_symbols.json": PAUSED_SYMBOLS_PATH,
    "config/paused_symbols_dividend.json": PAUSED_SYMBOLS_PATH_DIVIDEND,
    "config/sector_rotation.json": SECTOR_ROTATION_PATH,
    "config/investment_clock.json": INVESTMENT_CLOCK_PATH,
    "config/sector_tags.json": SECTOR_TAGS_PATH,
    "config/sector_suggestions.json": SECTOR_SUGGESTIONS_PATH,
    "config/sector_suggestions_dividend.json": SECTOR_SUGGESTIONS_PATH_DIVIDEND,
    "config/extra_universe.json": EXTRA_UNIVERSE_PATH,
    "config/extra_universe_dividend.json": EXTRA_UNIVERSE_PATH_DIVIDEND,
    "config/movers.json": MOVERS_PATH,
    "config/dividends_earned.json": DIVIDENDS_EARNED_PATH,
}
