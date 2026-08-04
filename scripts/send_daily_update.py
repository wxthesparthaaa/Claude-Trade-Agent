"""
Run with:
    python scripts/send_daily_update.py

Thin CLI wrapper around src/reporting.py::run_daily_update() -- the same
function the Flask app's scheduler calls on Render, so local and cloud
runs behave identically.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from reporting import run_daily_update

if __name__ == "__main__":
    run_daily_update()
