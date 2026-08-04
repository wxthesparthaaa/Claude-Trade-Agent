"""
Run with:
    python scripts/send_weekly_review.py
Intended to run every Saturday.

Thin CLI wrapper around src/reporting.py::run_weekly_review() -- the same
function the Flask app's scheduler calls on Render, so local and cloud
runs behave identically.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reporting import run_weekly_review

if __name__ == "__main__":
    run_weekly_review()
