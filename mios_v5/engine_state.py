"""MIOS V5 — Engine State snapshot (the "derived" half of the two-table
design: `candles_data` / `option_chain_data` / etc. are the immutable raw
layer, already collected every cycle; this is the per-cycle output of the
scoring engines run over that raw data).

One row per pipeline pass. Flattens the most-queried engine outputs into
plain columns (so a similarity search is a normal SQL WHERE clause, not a
JSONB unpack) and keeps the full per-engine detail in `full_state` for
anything not flattened. `engine_version` tags which scoring logic produced
the row, so a later change to how a stage scores doesn't silently mix
incomparable rows together (mirrors the `Database Version` idea from the
spec — this need not exist yet, but rows must self-report the version that
produced them, or a rebuild-vs-mix bug is baked in from day one).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import pytz

from .core.contract import EngineResult, MarketState

IST = pytz.timezone("Asia/Kolkata")

#: bump whenever a stage's scoring formula changes, so old rows can be told
#: apart from rows produced by the new logic (rebuild, don't silently mix)
ENGINE_VERSION = "v5.0"

#: (row column prefix, engine name) for engines flattened into top-level
#: bias/confidence columns — extend as new stages come online
_FLATTENED = [
    ("structure", "stage02_structure"),
    ("regime", "stage05_regime"),
    ("dealer", "stage11_dealer"),
    ("options", "stage12_options"),
    ("institutional", "stage13_institutional"),
    ("orderflow", "stage14_orderflow"),
    ("intent", "stage25_intent"),
    ("probability", "stage31_probability"),
    ("reaction_zone", "stage35_reaction_zone"),
]


def _bias_confidence(state: MarketState, engine_name: str) -> tuple[Optional[str], Optional[float]]:
    r: Optional[EngineResult] = state.get(engine_name)
    if r is None or not r.ok:
        return None, None
    return r.bias.value, round(r.confidence, 2)


def build_engine_state_row(state: MarketState, spot: Optional[float] = None) -> Dict[str, Any]:
    """Pure function: MarketState → one engine_state row. No DB, no
    Streamlit — testable standalone."""
    now = datetime.now(IST)
    row: Dict[str, Any] = {
        "ts": now.isoformat(),
        "trading_day": now.date().isoformat(),
        "spot": spot,
        "engine_version": ENGINE_VERSION,
    }
    for prefix, engine_name in _FLATTENED:
        bias, conf = _bias_confidence(state, engine_name)
        row[f"{prefix}_bias"] = bias
        row[f"{prefix}_confidence"] = conf

    s2 = state.get("stage02_structure")
    row["structure_score"] = round(s2.data.get("structure_score"), 2) if (s2 and s2.ok and s2.data.get("structure_score") is not None) else None
    row["structure_decision"] = s2.data.get("decision") if (s2 and s2.ok) else None

    conflict = state.get("stage27_conflict")
    row["conflict_severity"] = conflict.data.get("severity") if (conflict and conflict.ok) else None
    row["conflict_agreement_pct"] = round(conflict.data.get("agreement_pct"), 2) if (
        conflict and conflict.ok and conflict.data.get("agreement_pct") is not None) else None

    # full per-engine snapshot for anything not flattened above, and for
    # future-proofing when new stages come online
    row["full_state"] = {
        name: {
            "status": r.status.value, "bias": r.bias.value,
            "confidence": r.confidence, "data": r.data,
        }
        for name, r in state.results.items()
    }
    return row
