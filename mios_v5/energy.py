"""MIOS V6 — Stage 37 Market Energy (promoted to a first-class read).

The calculation already existed, buried inside Stage 4's context blob as three
loose numbers. Later engines — Stage 48 Market State, Stage 51 Signal Validity —
need it as a standardized engine output, so this **promotes** it rather than
recomputing it. No new maths, no duplicate logic: Stage 4 stays the owner of the
gamma/pin physics, this turns its output into a first-class contract.

    energy 82 · compression 74 · breakout_risk 66
                        ↓
    state COMPRESSION · strength 82% · expansion-readiness 88% ·
    release-probability 84% · duration 24min · confidence 91%

The reading that matters: **quiet is not one thing.** Quiet-because-damped (long
gamma pinning price) is dead — nothing is coming. Quiet-because-coiled (short
gamma, price contained) is loaded — a release is building. Both look like "low
movement" on a chart and mean opposite things, which is why compression and
energy are tracked separately rather than collapsed into one "volatility" number.

Duration is part of the read: compression that has persisted 24 minutes is far
closer to releasing than compression that started a minute ago.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

STATES = ("DEAD", "COMPRESSION", "BUILDING", "EXPANSION", "RELEASED")

_LABEL = {
    "DEAD": "💤 Dead — damped, nothing coming",
    "COMPRESSION": "🪤 Compression — coiling, loaded",
    "BUILDING": "⚡ Building — energy accumulating",
    "EXPANSION": "💥 Expansion — releasing now",
    "RELEASED": "🌊 Released — energy spent",
}

_RISK_LABEL = {0: "Low", 1: "Moderate", 2: "High", 3: "Very High"}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def risk_label(breakout_risk: Optional[float]) -> str:
    b = _f(breakout_risk)
    if b is None:
        return "Unknown"
    return _RISK_LABEL[0 if b < 35 else 1 if b < 60 else 2 if b < 80 else 3]


def classify(energy: Optional[float], compression: Optional[float],
             breakout_risk: Optional[float],
             prev_state: Optional[str] = None,
             prev_compression: Optional[float] = None,
             duration_cycles: int = 0) -> Dict[str, Any]:
    """Standardize Stage 4's three numbers into the Stage 37 contract."""
    e, c, b = _f(energy), _f(compression), _f(breakout_risk)
    if e is None:
        return {"state": None, "label": "—", "strength": 0, "compression": 0,
                "expansion_readiness": 0, "release_probability": 0,
                "breakout_risk": 0, "risk_label": "Unknown", "confidence": 0,
                "duration_cycles": 0, "ready": False}
    c = c if c is not None else 0.0
    b = b if b is not None else 0.0
    pc = _f(prev_compression)

    # a sharp drop in compression while energy is high = the coil just let go
    released = (pc is not None and pc >= 55 and c <= pc - 20
                and prev_state in ("COMPRESSION", "BUILDING"))

    if released:
        state = "RELEASED"
    elif e < 25:
        state = "DEAD"
    elif b >= 70 or (e >= 65 and c < 35):
        state = "EXPANSION"
    elif c >= 55:
        state = "COMPRESSION"
    elif e >= 45:
        state = "BUILDING"
    else:
        state = "DEAD" if e < 35 else "BUILDING"

    # how ready is a move? coiled AND energetic AND primed to break
    expansion_readiness = _clamp(0.45 * c + 0.35 * b + 0.20 * e)

    # release probability grows the longer a coil holds — a 24-minute
    # compression is far closer to letting go than a 1-minute one
    dwell = min(1.0, duration_cycles / 12.0)
    if state == "COMPRESSION":
        release = _clamp(35 + 0.35 * c + 0.25 * b + 25 * dwell)
    elif state == "BUILDING":
        release = _clamp(25 + 0.30 * b + 0.20 * e + 15 * dwell)
    elif state == "EXPANSION":
        release = _clamp(75 + 0.20 * b)
    elif state == "RELEASED":
        release = 20.0
    else:
        release = _clamp(10 + 0.15 * b)

    # confidence: we trust this more once the state has persisted a little
    confidence = int(_clamp(45 + min(35, duration_cycles * 5)
                            + (10 if b or c else 0)))

    return {"state": state, "label": _LABEL[state], "strength": round(e),
            "compression": round(c), "breakout_risk": round(b),
            "risk_label": risk_label(b),
            "expansion_readiness": round(expansion_readiness),
            "release_probability": round(release),
            "confidence": confidence, "duration_cycles": duration_cycles,
            "ready": True,
            "tradeable": state not in ("DEAD",),
            "stars": _stars(e)}


def _stars(pct: float) -> str:
    n = max(1, min(5, int(round(pct / 20.0))))
    return "★" * n + "☆" * (5 - n)


def advise(read: Optional[Dict[str, Any]]) -> str:
    """The one line a trader acts on."""
    r = read or {}
    st = r.get("state")
    if not st:
        return "Energy unknown."
    if st == "DEAD":
        return "Energy dead — damped market, breakout entries will fail."
    if st == "COMPRESSION":
        return (f"Market coiling ({r.get('compression')}% compressed) — "
                f"release probability {r.get('release_probability')}%. "
                f"Wait for the break, don't pre-position.")
    if st == "BUILDING":
        return "Energy accumulating — a directional move is being prepared."
    if st == "EXPANSION":
        return "Expansion underway — trade WITH the move, do not fade it."
    return "Energy spent after a release — expect consolidation."
