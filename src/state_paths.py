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
}
