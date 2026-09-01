"""MIOS V6 — Dashboard 2's Top Command Center.

Six cards, answering the three questions a trader asks in the first five
seconds: what is the market doing, where should I trade, and what are the ATM
legs doing.

**This module reads. It does not decide.** Every value is quoted from an engine
that already produced it — Stage 52 for the decision, Stage 48 for market state,
Stage 53 for the controller, the thesis builder for why/expect/invalidation. If
a card cannot be filled, it says so; it never falls back to a plausible value,
because a header tile is exactly where a stale number does the most damage.

Pure module: `final_read` in, dicts out. No pandas, no session, no IO.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: decision state → (label, tone). The eight the spec names, plus the ones the
#: Decision Engine actually emits.
DECISIONS: Dict[str, str] = {
    "ENTER": "bull", "BUY": "bull", "ENTRY_READY": "watch",
    "SCALE_IN": "bull", "SCALE_OUT": "watch", "EXIT": "watch",
    "ABORT": "bear", "SELL": "bear", "WAIT": "neutral",
    "FLOOR_CONFIRMED": "bull", "CEILING_CONFIRMED": "bear",
    "TRAIL": "info",
}

TONE = {"bull": "#00ff88", "bear": "#ff4444", "watch": "#ffcc33",
        "info": "#4da6ff", "dealer": "#a78bfa", "neutral": "#cfd9e6",
        "off": "#6f7d8f"}

#: the POCs the S/R card shows, in the order a trader scans them
POC_ORDER = ("Today", "1H", "4H", "Daily", "Weekly", "Monthly")

_MISSING = "—"


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").strip().upper()


def _pts(v, spot) -> Optional[str]:
    """Distance from LTP, signed. The number a trader actually acts on — an
    absolute level tells you where, this tells you how far."""
    a, b = _f(v), _f(spot)
    if a is None or b is None:
        return None
    return f"{a - b:+,.0f} pts"


# ── card 1 · the decision ───────────────────────────────────────────────
def decision_card(fr: Optional[Dict[str, Any]],
                  quality: Optional[Dict[str, Any]] = None,
                  risk: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stage 52's verdict, quoted. Confidence, quality, risk, dynamic trail."""
    f = fr or {}
    dec = f.get("decision_v2") or {}
    state = _s(dec.get("state")) or "WAIT"
    trail = (dec.get("trail") or {}).get("stop")

    return {
        "title": "MIOS V6",
        "state": state,
        "tone": DECISIONS.get(state, "neutral"),
        "confidence": _f(dec.get("confidence")),
        "quality": (quality or {}).get("grade") or _MISSING,
        "quality_tone": _quality_tone((quality or {}).get("grade")),
        "risk": (risk or {}).get("level") or _MISSING,
        "risk_tone": _risk_tone((risk or {}).get("level")),
        "trail": _f(trail),
        "trail_state": (dec.get("trail") or {}).get("state"),
        "side": dec.get("side"),
        # a trail that is not armed is not a number — saying "—" is the honest
        # rendering, and stops a stale level looking live
        "armed": bool(dec.get("entry")),
    }


def _quality_tone(grade) -> str:
    g = _s(grade)
    if g.startswith("A"):
        return "bull"
    if g.startswith("B"):
        return "watch"
    if g in ("UNTRADEABLE", "D", "F"):
        return "bear"
    return "neutral"


def _risk_tone(level) -> str:
    return {"LOW": "bull", "MEDIUM": "watch", "HIGH": "bear",
            "EXTREME": "bear"}.get(_s(level), "neutral")


# ── card 2 · overall bias ───────────────────────────────────────────────
def bias_card(fr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Direction, how hard, and which way it is travelling.

    Velocity and transition matter more than the label: a weakening bull is a
    different trade from a strengthening one, and the word "Bullish" alone
    hides that completely.
    """
    f = fr or {}
    tr = f.get("transition") or {}
    bias = _s(f.get("bias")) or "NEUTRAL"
    tone = ("bull" if "BULL" in bias else
            "bear" if "BEAR" in bias else "neutral")
    return {
        "title": "Overall Bias",
        "bias": bias.replace("_", " ").title() or _MISSING,
        "tone": tone,
        "strength": f.get("bias_strength") or tr.get("strength") or _MISSING,
        "velocity": tr.get("velocity") or _MISSING,
        "transition": tr.get("label") or tr.get("state") or _MISSING,
        "reversal_pct": _f(tr.get("reversal_probability")),
    }


# ── card 3 · market state ───────────────────────────────────────────────
def state_card(fr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Stage 48, with how long it has held.

    Duration is the part that stops a trader acting on a state that formed
    ninety seconds ago as if it were the day's character.
    """
    f = fr or {}
    ms = f.get("market_state") or {}
    mem = f.get("memory_read") or {}
    mins = _f(ms.get("duration_min")) or _f(mem.get("state_duration_min"))
    return {
        "title": "Market State",
        "state": (ms.get("label") or ms.get("state") or _MISSING),
        "tone": _state_tone(ms.get("state")),
        "duration": _duration(mins),
        "duration_min": mins,
        "next": ms.get("next_label"),
        "next_pct": _f(ms.get("next_probability")),
    }


def _state_tone(state) -> str:
    s = _s(state)
    if s in ("TRENDING", "EXPANSION", "RANGE_EXPANSION"):
        return "bull"
    if s in ("CHOPPY", "VOLATILE", "EVENT_DRIVEN"):
        return "bear"
    if s in ("COMPRESSION", "RANGE_COMPRESSION", "SIDEWAYS"):
        return "watch"
    return "info"


def _duration(mins: Optional[float]) -> str:
    if mins is None:
        return _MISSING
    m = int(round(mins))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


# ── card 4 · support & resistance ───────────────────────────────────────
def sr_card(fr: Optional[Dict[str, Any]],
            spot: Optional[float] = None) -> Dict[str, Any]:
    """Levels, each with its distance from price.

    Every row carries `distance` because a level without one makes the trader
    do the arithmetic, and they will do it wrong at the moment it matters.
    """
    f = fr or {}
    bz = f.get("battle_zone") or {}
    htf = (f.get("htf") or {}).get("levels") or {}
    mf = f.get("money_flow") or {}

    rows: List[Dict[str, Any]] = []

    def add(label, value, tone="info"):
        v = _f(value)
        if v is None:
            return
        rows.append({"label": label, "value": v, "tone": tone,
                     "distance": _pts(v, spot)})

    add("Support", f.get("strong_support"), "bull")
    add("Resistance", f.get("strong_resistance"), "bear")
    add("Major Support", f.get("major_support"), "bull")
    add("Major Resistance", f.get("major_resistance"), "bear")
    add("War Zone", bz.get("price"), "watch")
    add("Liquidity", f.get("liquidity"), "info")
    add("Today POC", mf.get("poc_price") or htf.get("Today"), "dealer")
    for name in POC_ORDER[1:]:
        add(f"{name} POC", htf.get(name), "dealer")

    war_lo, war_hi = _f(bz.get("lower")), _f(bz.get("upper"))
    return {
        "title": "Support & Resistance",
        "rows": rows,
        "war_zone": (f"{war_lo:,.0f}-{war_hi:,.0f}"
                     if war_lo is not None and war_hi is not None else None),
        "spot": _f(spot),
        "empty": not rows,
    }


# ── card 5 · market controller ──────────────────────────────────────────
def controller_card(controller: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Who is running the tape, from Stage 53's family strengths.

    Quoted from `thesis.market_controller` — this does not re-rank anything.
    """
    c = dict(controller or {})
    groups = []
    for row in (c.get("ranked") or c.get("families") or []):
        if not isinstance(row, dict):
            continue
        score = _f(row.get("score")) or _f(row.get("strength")) or 0.0
        groups.append({
            "name": str(row.get("label") or row.get("family") or "—").title(),
            "score": score,
            "stars": _stars(score),
            "tone": ("bull" if _s(row.get("direction")) in ("BULL", "BULLISH")
                     else "bear" if _s(row.get("direction")) in ("BEAR", "BEARISH")
                     else "neutral"),
        })
    return {
        "title": "Market Controller",
        "groups": groups[:6],
        "winner": c.get("controller") or c.get("winner") or _MISSING,
        "winner_note": c.get("note") or c.get("summary"),
        "empty": not groups,
    }


def _stars(score: float) -> str:
    n = max(0, min(5, int(round((score or 0) / 20.0))))
    return "★" * n + "☆" * (5 - n)


# ── card 6 · the thesis ─────────────────────────────────────────────────
def thesis_card(thesis: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Why · Expect · Invalidation, quoted from the thesis builder.

    Invalidation is listed last and never truncated to nothing: the reason to
    be out of a trade is the one line a trader most needs and least wants.
    """
    t = dict(thesis or {})
    return {
        "title": "AI Thesis",
        "why": list(t.get("why") or [])[:3],
        "expect": list(t.get("expect") or [])[:2],
        "invalidation": list(t.get("invalidation") or [])[:3],
        "has_edge": bool(t.get("has_edge")),
        "empty": not (t.get("why") or t.get("expect") or t.get("invalidation")),
    }


# ── the whole header ────────────────────────────────────────────────────
def build(fr: Optional[Dict[str, Any]] = None,
          spot: Optional[float] = None,
          quality: Optional[Dict[str, Any]] = None,
          risk: Optional[Dict[str, Any]] = None,
          controller: Optional[Dict[str, Any]] = None,
          thesis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """All six cards. Every input is an engine output already computed."""
    return {
        "decision": decision_card(fr, quality, risk),
        "bias": bias_card(fr),
        "state": state_card(fr),
        "sr": sr_card(fr, spot),
        "controller": controller_card(controller),
        "thesis": thesis_card(thesis),
        "spot": _f(spot),
    }
