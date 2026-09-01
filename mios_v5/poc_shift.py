"""Detect when a chart's dynamic POC steps to a new level, and word the alert.

Pure by design. It compares two readings — this cycle's dynamic POC per chart
against the last one seen — decides whether a genuine step happened and in which
direction, and formats the message. It sends nothing, reads no `session_state`
and imports no app module: `vob_minimal` owns the notification channels and the
per-cycle memory, exactly as every other alert in this app does (see
`docs/ARCHITECTURE_PRINCIPLES.md` §1, §4). The dynamic POC itself has one owner,
`compute_dynamic_poc`; this never computes one.

The dynamic POC is bin-quantised, so a real move clears one bin width at least —
`TOL_FRAC` only rejects the sub-tick wobble a redraw can introduce, never a true
step. A value that is `None` (a panel without enough bars to place a POC) is not
a level, so a shift is reported only when BOTH the old and new readings exist:
`MISSING → 24,000` is a warm-up, not a move (§9, fail-fast, never invent).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: the three terminal charts, in the order the alert should read them.
CHARTS: Sequence[str] = ("NIFTY", "CALL", "PUT")

#: below this fractional move, a change is float/bin jitter rather than a step.
#: 0.01% of the level — well under one bin width on any of the three panels.
TOL_FRAC = 1e-4


def _f(v: Any) -> Optional[float]:
    """A finite float, or None. NaN is not a level."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def detect(current: Mapping[str, Any], previous: Mapping[str, Any],
           charts: Sequence[str] = CHARTS,
           tol_frac: float = TOL_FRAC) -> List[Dict[str, Any]]:
    """The shifts between two readings, one dict per chart that moved.

    Each shift is `{chart, prev, cur, direction, delta}` where `direction` is
    `"UP"` or `"DOWN"`. A chart is skipped when either reading is missing (a
    warm-up is not a move) or when the move is within `tol_frac` of the old
    level (jitter, not a step).
    """
    out: List[Dict[str, Any]] = []
    for chart in charts:
        cur = _f(current.get(chart))
        prev = _f(previous.get(chart))
        if cur is None or prev is None:
            continue
        if abs(cur - prev) <= max(abs(prev) * tol_frac, 1e-6):
            continue
        out.append({
            "chart": chart, "prev": prev, "cur": cur,
            "direction": "UP" if cur > prev else "DOWN",
            "delta": cur - prev,
        })
    return out


def _decimals(chart: str, decimals: Optional[int]) -> int:
    # 0 for the index, 2 for a premium leg: ₹0.05 on a ₹120 option is a move,
    # and rounding it to the rupee would hide it.
    if decimals is not None:
        return decimals
    return 0 if chart == "NIFTY" else 2


def headline(shift: Mapping[str, Any], label: Optional[str] = None,
             decimals: Optional[int] = None) -> str:
    """One shift → the one-line headline the market-event feed carries.

    Plain text (no HTML): it is routed through `capture_market_event`, whose
    Discord relay wraps the headline itself. `label` names the chart — the leg's
    own tag ("ATM CE 24450") rather than "CALL" — and defaults to the chart key.
    """
    chart = str(shift.get("chart") or "")
    label = label or chart
    dp = _decimals(chart, decimals)
    direction = str(shift.get("direction") or "")
    arrow = "⬆️" if direction == "UP" else "⬇️"
    prev = f"{float(shift['prev']):,.{dp}f}"
    cur = f"{float(shift['cur']):,.{dp}f}"
    delta = f"{float(shift['delta']):+,.{dp}f}"
    return f"Dynamic POC {arrow} {direction} — {label}: ₹{prev} → ₹{cur} ({delta})"


def detail(shift: Mapping[str, Any], label: Optional[str] = None) -> str:
    """The 'why it matters' line under the headline."""
    label = label or str(shift.get("chart") or "")
    up = str(shift.get("direction") or "") == "UP"
    return (f"{label}'s high-volume node stepped {'up' if up else 'down'} — "
            f"volume is now concentrating at a "
            f"{'higher' if up else 'lower'} level.")
