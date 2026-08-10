"""
One-time backfill: seeds a portfolio's trade journal from Tiger's real
historical fill data (TradeClient.get_filled_orders -- verified live
against the real paper account before writing this: returns real
Order objects with .contract.symbol, .action, .quantity,
.avg_fill_price, .status, .trade_time in epoch milliseconds), replayed
in chronological order through the same open/close-per-symbol logic
live trading already uses (trade_journal.apply_fill). This is how
"trades so far" get into the journal -- decision_log.json never
recorded price/quantity, so it can't reconstruct real trades, but
Tiger's own fill history can.

Confidence isn't backfilled (confidence_pct=None) -- the confidence
system didn't exist for these historical trades, so there's nothing
real to report; fabricating a number would misrepresent history.

Run with:
    python scripts/backfill_trade_journal.py                       (growth, last 365 days, dry run preview)
    python scripts/backfill_trade_journal.py --days 730
    python scripts/backfill_trade_journal.py --portfolio dividend
    python scripts/backfill_trade_journal.py --write               (actually save + push)

Intended as a true one-time seed, not a periodic job: re-running with
--write REPLACES the journal file with a fresh replay from Tiger's fill
history, so running it again after live trading has already added real
entries would overwrite those too -- only run --write once, before any
real trading happens through the new journal-writing code path.
"""
import argparse
import io
import os
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tiger_client import get_client_config
from tigeropen.trade.trade_client import TradeClient

from portfolio_profiles import get_profile
from trade_journal import apply_fill, save_journal
from journal_export import build_journal_workbook
from github_state_sync import push_state_to_github, push_binary_file, get_github_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--portfolio", default="growth", choices=["growth", "dividend"])
    parser.add_argument("--days", type=int, default=365, help="How many days of fill history to backfill (default: 365).")
    parser.add_argument("--write", action="store_true", help="Actually save (and push) the journal. Without this, only previews.")
    args = parser.parse_args()

    profile = get_profile(args.portfolio)
    sleeve_by_symbol = {e.symbol: e.sleeve for e in profile.universe}

    client_config = get_client_config()
    trade_client = TradeClient(client_config)

    # Tiger's get_filled_orders caps the start/end window at 90 days
    # (verified live -- a >90-day request raises ApiException code 1010),
    # so a longer --days lookback is fetched in successive 90-day chunks.
    orders = []
    window_end = date.today()
    remaining_days = args.days
    while remaining_days > 0:
        window_days = min(remaining_days, 90)
        window_start = window_end - timedelta(days=window_days)
        chunk = trade_client.get_filled_orders(
            account=client_config.account,
            start_time=window_start.strftime("%Y-%m-%d"), end_time=window_end.strftime("%Y-%m-%d"),
        ) or []
        orders.extend(chunk)
        window_end = window_start
        remaining_days -= window_days

    relevant = [o for o in orders if o.contract.symbol in sleeve_by_symbol and str(o.status).endswith("FILLED")]
    relevant.sort(key=lambda o: o.trade_time)  # chronological replay order -- required for correct open/close math

    print(f"Found {len(relevant)} filled order(s) for '{profile.name}' in the last {args.days} day(s).")

    entries = []
    for o in relevant:
        opened_at = datetime.fromtimestamp(o.trade_time / 1000, tz=timezone.utc).isoformat()
        entries = apply_fill(
            entries, symbol=o.contract.symbol, sleeve=sleeve_by_symbol.get(o.contract.symbol, "unknown"),
            action=o.action, quantity=int(o.quantity), fill_price=float(o.avg_fill_price),
            opened_at=opened_at, confidence_pct=None, reason="backfilled from Tiger fill history",
        )

    for e in entries:
        line = f"  {e.status}: {e.position_type} {e.quantity} {e.symbol} @ ${e.entry_price:.2f}"
        if e.status == "CLOSED":
            line += f" -> closed @ ${e.exit_price:.2f}, realized P&L ${e.realized_pnl:+.2f}"
        print(line)

    if not args.write:
        print("\nPREVIEW ONLY -- re-run with --write to actually save (and push) this journal.")
        return

    save_journal(profile.journal_path, entries)
    print(f"\nWrote {len(entries)} journal entrie(s) to {profile.journal_path}.")

    if get_github_config() is None:
        print("GITHUB_TOKEN/GITHUB_REPO not set -- journal saved locally only, not pushed.")
        return

    if push_state_to_github(profile.journal_path):
        print(f"Pushed {os.path.basename(profile.journal_path)} to GitHub.")

    from dataclasses import asdict
    workbook = build_journal_workbook([asdict(e) for e in entries])
    buffer = io.BytesIO()
    workbook.save(buffer)
    xlsx_repo_path = os.path.basename(profile.journal_path).replace(".json", ".xlsx")
    if push_binary_file(buffer.getvalue(), xlsx_repo_path):
        print(f"Pushed {xlsx_repo_path} to GitHub.")


if __name__ == "__main__":
    main()
