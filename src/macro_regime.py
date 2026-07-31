"""
Macro "investment clock" regime signal. The actual research (searching
public JPMorgan/Goldman Sachs/DBS/OCBC outlook content and synthesizing a
regime read) is a judgment call done by Claude when refreshing
config/regime.json -- there is no scheduled/automated fetch pipeline yet,
per the pivot plan. This module only handles loading that file and applying
its sleeve tilts; it is pure logic so it can be unit tested with a synthetic
signal, independent of whatever the current real regime read says.
"""
import json
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class RegimeSignal:
    as_of: str                      # "YYYY-MM-DD"
    regime: str                      # e.g. "recovery" | "overheat" | "stagflation" | "reflation"
    sleeve_tilts: Dict[str, float]    # e.g. {"core": 0.9, "satellite": 1.1}
    sources: List[str]
    notes: str = ""


def load_regime_signal(path: str) -> RegimeSignal:
    """Pure parse -- no network. Raises if the file is missing/malformed."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return RegimeSignal(
        as_of=data["as_of"],
        regime=data["regime"],
        sleeve_tilts=data["sleeve_tilts"],
        sources=data.get("sources", []),
        notes=data.get("notes", ""),
    )


def apply_regime_tilt(base_weights: Dict[str, float], tilts: Dict[str, float]) -> Dict[str, float]:
    """
    Multiplies each base weight by its matching tilt (defaulting to 1.0 for
    any key not present in tilts), then renormalizes so the result still
    sums to the same total as base_weights -- a tilt shifts the mix between
    sleeves, it doesn't change how much capital is deployed overall.
    """
    if not base_weights:
        return {}

    total_before = sum(base_weights.values())
    tilted = {k: v * tilts.get(k, 1.0) for k, v in base_weights.items()}
    total_after = sum(tilted.values())

    if total_after <= 0:
        raise ValueError("Tilted weights sum to zero or less -- check the tilts config")

    scale = total_before / total_after
    return {k: v * scale for k, v in tilted.items()}
