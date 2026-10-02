"""
Run with:
    python scripts/send_weekly_summary.py
Intended to run every Saturday.

Thin CLI wrapper around src/reporting.py::run_weekly_summary() -- the same
function the Flask app's scheduler calls on Render, so local and cloud
runs behave identically. NOTE: the Render scheduler already sends this
every Saturday, so don't ALSO register this as an OS-level scheduled task
-- it would just send the summary twice.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reporting import run_weekly_summary

if __name__ == "__main__":
    run_weekly_summary()
