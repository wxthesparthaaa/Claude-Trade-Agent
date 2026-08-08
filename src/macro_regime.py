"""
Macro "investment clock" regime signal. The qualitative research
(searching public JPMorgan/Goldman Sachs/DBS/OCBC outlook content and
synthesizing a regime read) is a judgment call done by Claude when
refreshing config/regime.json -- no automated pipeline for that part.

positioning_tilt is different: it's mechanically derived from CFTC COT
data (see cot_adapter.py) on a weekly schedule, no judgment call involved,
so it's updated automatically and kept as its own field rather than
folded into the manually-curated sleeve_tilts.

breadth_tilt/breadth_trend/breadth_at_edge follow the same pattern,
mechanically derived from the RSP/SPY market-breadth signal (see
market_breadth.py) on a daily schedule.
"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class RegimeSignal:
    as_of: str                          # "YYYY-MM-DD"
    regime: str                          # e.g. "recovery" | "overheat" | "stagflation" | "reflation"
    sleeve_tilts: Dict[str, float]        # e.g. {"core": 0.9, "satellite": 1.1} -- manually curated
    sources: List[str]
    notes: str = ""
    positioning_tilt: Optional[float] = None       # from cot_adapter.positioning_to_tilt, auto-updated weekly
    positioning_as_of: Optional[str] = None
    positioning_notes: str = ""
    breadth_trend: Optional[str] = None            # "broadening" | "narrowing" | "flat", auto-updated daily
    breadth_as_of: Optional[str] = None
    breadth_notes: str = ""
    breadth_tilt: Optional[float] = None           # from market_breadth.compute_breadth_signal
    breadth_at_edge: bool = False


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
        positioning_tilt=data.get("positioning_tilt"),
        positioning_as_of=data.get("positioning_as_of"),
        positioning_notes=data.get("positioning_notes", ""),
        breadth_trend=data.get("breadth_trend"),
        breadth_as_of=data.get("breadth_as_of"),
        breadth_notes=data.get("breadth_notes", ""),
        breadth_tilt=data.get("breadth_tilt"),
        breadth_at_edge=data.get("breadth_at_edge", False),
    )


def update_positioning_tilt(path: str, positioning_tilt: float, as_of: str, notes: str = "") -> None:
    """
    Updates just the COT-derived positioning fields in regime.json,
    leaving the manually-curated regime/sleeve_tilts/sources/notes
    untouched. Creates a minimal file if one doesn't exist yet (the
    qualitative fields default to a neutral placeholder in that case --
    a real regime refresh should still happen separately).
    """
    data = {
        "as_of": as_of, "regime": "unknown", "sleeve_tilts": {}, "sources": [], "notes": "",
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    data["positioning_tilt"] = positioning_tilt
    data["positioning_as_of"] = as_of
    data["positioning_notes"] = notes

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_breadth_signal(
    path: str, breadth_tilt: float, trend: str, at_edge: bool, as_of: str, notes: str = ""
) -> None:
    """
    Updates just the RSP/SPY-derived breadth fields in regime.json, same
    shape and same "leave the manually-curated fields alone, create a
    minimal file if needed" behavior as update_positioning_tilt.
    """
    data = {
        "as_of": as_of, "regime": "unknown", "sleeve_tilts": {}, "sources": [], "notes": "",
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

    data["breadth_tilt"] = breadth_tilt
    data["breadth_trend"] = trend
    data["breadth_at_edge"] = at_edge
    data["breadth_as_of"] = as_of
    data["breadth_notes"] = notes

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def effective_sleeve_tilts(regime: RegimeSignal) -> Dict[str, float]:
    """
    Combines the manually-curated sleeve_tilts with the COT-derived
    positioning_tilt and the RSP/SPY-derived breadth_tilt -- both are
    momentum/satellite-relevant signals (defensive core holdings aren't
    what either is measuring), so both only adjust "satellite", multiplied
    together rather than either overriding the other.
    """
    tilts = dict(regime.sleeve_tilts)
    combined = 1.0
    any_present = False
    if regime.positioning_tilt is not None:
        combined *= regime.positioning_tilt
        any_present = True
    if regime.breadth_tilt is not None:
        combined *= regime.breadth_tilt
        any_present = True
    if any_present:
        tilts["satellite"] = tilts.get("satellite", 1.0) * combined
    return tilts


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
