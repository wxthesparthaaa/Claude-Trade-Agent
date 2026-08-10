"""
Human-readable rationale trail for each buy/hold/sell/reject decision the
strategy makes, built deterministically from the same numeric inputs the
strategy actually used (composite scores, board-lot affordability, exit
triggers). This is NOT a per-period LLM narration -- it has to run for
every rebalance period in a backtest (dozens of them), not just the much
rarer live daily/weekly agent-driven research passes (the news tilt and the
weekly "lessons observed" text stay qualitative, written by Claude, and
stay separate from this).
"""
import json
import os
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class DecisionRecord:
    date: str
    action: str    # "buy" | "hold" | "sell" | "reject" | "shortlist" (growth's confidence-gated pipeline only)
    symbol: str
    sleeve: str
    reason: str
    score: Optional[float] = None


def format_decision_summary(date: str, records: List[DecisionRecord]) -> str:
    lines = [f"Decisions for {date}:"]
    for action in ("buy", "hold", "sell", "shortlist", "reject"):
        matches = [r for r in records if r.action == action]
        if not matches:
            continue
        lines.append(f"  {action.upper()}:")
        for r in matches:
            score_str = f" (score={r.score:.3f})" if r.score is not None else ""
            lines.append(f"    - {r.symbol} [{r.sleeve}]{score_str}: {r.reason}")
    return "\n".join(lines)


def write_decision_log(path: str, date: str, records: List[DecisionRecord]):
    """Appends one date's decisions to a JSON list at `path`, creating it if needed."""
    entries = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    entries.append({"date": date, "decisions": [asdict(r) for r in records]})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
