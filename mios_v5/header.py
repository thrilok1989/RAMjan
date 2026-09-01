"""MIOS V6 — the persistent market header.

Nine facts that must never leave the screen, whichever dashboard is open:

    NIFTY · Decision · Confidence · Quality · Market State · Flow · Dealer ·
    Acceptance · Memory · Controller

The reason to make this persistent rather than putting it on the Decision tab
is specific: a trader digging through the engine room on Dashboard 3, or
reading a post-trade review on Dashboard 4, is exactly the trader most likely
to have stopped watching the tape. The header is what stops a flow shift or a
dealer flip from happening off-screen while they are reading about a trade from
an hour ago.

**Every tile degrades to "—" rather than to a stale value.** A header that keeps
showing the last known dealer bias after the engine stops reporting is worse
than one that shows nothing, because it looks live. Tiles carry `stale` so the
panel can dim them.

Pure module: a final read in, tiles out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .final_read import section

#: tile order, left to right. Spot first — it is the only number that is not
#: an opinion.
ORDER = ("spot", "decision", "confidence", "quality", "market_state", "flow",
         "dealer", "acceptance", "memory", "controller")

_BULL = ("BULL", "STRONG_BULL", "BULLISH")
_BEAR = ("BEAR", "STRONG_BEAR", "BEARISH")

_GOOD, _WARN, _BAD, _DIM = "#00ff88", "#ffd000", "#ff4444", "#cfd9e6"

#: decision state → colour. WAIT is deliberately dim, not red: not trading is
#: the correct default, and colouring it as a problem trains impatience.
_DECISION_COLOUR = {
    "ENTER": _GOOD, "SCALE_IN": _GOOD, "HOLD": "#4da6ff", "TRAIL": "#a78bfa",
    "ENTRY_READY": _WARN, "FLOOR_CONFIRMED": _GOOD, "CEILING_CONFIRMED": _BAD,
    "SCALE_OUT": _WARN, "EXIT": "#ff9500", "ABORT": "#ff2d55",
    "COMPLETE": _DIM, "WAIT": _DIM,
}

_FLOW_COLOUR = {"STABLE": _GOOD, "UNSTABLE": _WARN, "SHOCK": _BAD,
                "RECOVERY": _WARN}

_QUALITY_COLOUR = {"A+": _GOOD, "A": "#17c98b", "B": _WARN, "C": _BAD}


def _s(v) -> str:
    return str(v or "").upper()


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _bias_colour(bias: Any) -> str:
    b = _s(bias)
    if b in _BULL:
        return _GOOD
    if b in _BEAR:
        return _BAD
    return _DIM


def _tile(key: str, label: str, value: Optional[str],
          colour: str = "#ffffff", sub: str = "") -> Dict[str, Any]:
    ok = bool(value) and value not in ("—", "NONE", "None")
    return {"key": key, "label": label,
            "value": value if ok else "—",
            "colour": colour if ok else _DIM,
            "sub": sub if ok else "",
            "stale": not ok}


def build(final_read: Optional[Dict[str, Any]],
          spot: Any = None) -> List[Dict[str, Any]]:
    """The header tiles, in display order."""
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    ms = fr.get("market_state") or {}
    mem = fr.get("memory_read") or {}
    rc = fr.get("reaction") or {}
    d = section(fr, "dealer")

    sp = _f(spot) if spot is not None else _f(fr.get("spot"))
    state = _s(dec.get("state"))
    conf = _f(dec.get("confidence"))
    # fall back to the arbitrated read when no trade is proposed — the trader
    # still needs a conviction number, it just isn't a trade's conviction
    conf_sub = ""
    if conf is None or (not conf and state in ("", "WAIT")):
        conf = _f(fr.get("confidence_tempered", fr.get("confidence")))
        conf_sub = "market read"

    dur = _f(mem.get("state_duration_min"))
    trisk = _f(mem.get("state_transition_risk")) or 0.0

    dealer_bias = d.get("bias") or (fr.get("families") or {}).get(
        "dealer", {}).get("direction")

    from .thesis import market_controller
    ctl = market_controller(fr.get("families"))

    return [
        _tile("spot", "NIFTY", f"{sp:,.1f}" if sp is not None else None,
              "#ffffff"),
        _tile("decision", "Decision",
              str(dec.get("label") or state or "").replace("_", " ") or None,
              _DECISION_COLOUR.get(state, _DIM)),
        _tile("confidence", "Confidence",
              f"{conf:.0f}%" if conf is not None else None,
              _GOOD if (conf or 0) >= 70 else _WARN if (conf or 0) >= 50
              else _DIM, conf_sub),
        _tile("quality", "Quality", dec.get("quality"),
              _QUALITY_COLOUR.get(_s(dec.get("quality")), _DIM)),
        _tile("market_state", "Market State",
              str(ms.get("label") or ms.get("state") or "") or None, "#c9b6ec"),
        _tile("flow", "Flow", fr.get("stability"),
              _FLOW_COLOUR.get(_s(fr.get("stability")), _DIM)),
        _tile("dealer", "Dealer",
              str(dealer_bias or "") or None, _bias_colour(dealer_bias)),
        _tile("acceptance", "Acceptance",
              (str(rc.get("state")).replace("_", " ").title()
               if rc.get("state") and _s(rc.get("state")) != "IDLE" else None),
              _bias_colour("BULL" if rc.get("winner") == "Buyers"
                           else "BEAR" if rc.get("winner") == "Sellers"
                           else None)),
        _tile("memory", "Memory",
              f"{dur:.0f} min" if dur is not None else None,
              _WARN if trisk >= 60 else "#edf3f9",
              f"risk {trisk:.0f}%" if trisk >= 30 else ""),
        _tile("controller", "Controller", ctl.get("label"), "#9fd3ff"),
    ]


def alerts(final_read: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The two conditions that must interrupt whatever the trader is reading.

    Kept to two on purpose. A header that can raise five alerts raises one
    every cycle and is then ignored — which is how the flow shift you actually
    needed gets missed.
    """
    fr = dict(final_read or {})
    out = []
    fs = fr.get("flow_shift") or {}
    if fs.get("freeze_entries"):
        out.append({"key": "flow_shift", "colour": "#ff9500",
                    "text": f"⚠️ INSTITUTIONAL FLOW SHIFT "
                            f"{_f(fs.get('score')) or 0:.0f}% — "
                            f"{fs.get('reason', 'tape repricing')}"})
    ev = fr.get("event") or {}
    if ev.get("event_detected"):
        out.append({"key": "event", "colour": "#ff2d2d",
                    "text": f"🚨 BREAKING EVENT "
                            f"{_f(ev.get('event_score')) or 0:.0f}% — "
                            f"reaction {ev.get('reaction', '')}"})
    return out[:2]
