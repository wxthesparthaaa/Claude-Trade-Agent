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
}
