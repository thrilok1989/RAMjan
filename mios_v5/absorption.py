"""MIOS V6 — Stage 43 Institutional Absorption (WHY it is happening).

Stage 42 says *what happened* at the level. Stage 50 says *what price is trying
to do*. This says **who is doing it and why** — it interprets institutional
participation rather than detecting more order flow.

    Stage 42  →  Accepted? Rejected? Trap?
    Stage 50  →  Building? Absorbing? Exhausted?
    Stage 43  →  Passive buying · Passive selling · Aggressive buying ·
                 Aggressive selling · Reloading · Exhaustion

The classification that earns its place is **passive vs aggressive**, and the
distinction is counter-intuitive: heavy aggressive SELLING into flat price is
bullish. It means an institution is quietly absorbing that supply — accumulating
inventory — and price has stopped responding to pressure that should be moving
it. A retail read sees "heavy selling"; the institutional read sees a buyer
being filled.

    Selling aggressive + price flat + buyer absorbing  →  PASSIVE BUYING
    Buying aggressive  + price flat + seller absorbing →  PASSIVE SELLING

**Reloading** is the pattern only visible across cycles: absorb → pause →
absorb again → price resumes. One absorption is a fill; a repeated one is a
programme.

It does NOT detect icebergs or hidden orders — that needs L2 depth this feed does
not carry, and inferring them would be fabrication. Absorption is measurable;
icebergs are not.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

BEHAVIOURS = ("PASSIVE_BUYING", "PASSIVE_SELLING", "AGGRESSIVE_BUYING",
              "AGGRESSIVE_SELLING", "BUYER_RELOADING", "SELLER_RELOADING",
              "BUYER_EXHAUSTION", "SELLER_EXHAUSTION", "NONE")

LABEL = {
    "PASSIVE_BUYING": "🟢 Passive Buying",
    "PASSIVE_SELLING": "🔴 Passive Selling",
    "AGGRESSIVE_BUYING": "🟢 Aggressive Buying",
    "AGGRESSIVE_SELLING": "🔴 Aggressive Selling",
    "BUYER_RELOADING": "🔁 Buyer Reloading",
    "SELLER_RELOADING": "🔁 Seller Reloading",
    "BUYER_EXHAUSTION": "🥵 Buyer Exhaustion",
    "SELLER_EXHAUSTION": "🥵 Seller Exhaustion",
    "NONE": "— No clear institutional footprint",
}

TONE = {
    "PASSIVE_BUYING": "bull", "AGGRESSIVE_BUYING": "bull",
    "BUYER_RELOADING": "bull", "SELLER_EXHAUSTION": "bull",
    "PASSIVE_SELLING": "bear", "AGGRESSIVE_SELLING": "bear",
    "SELLER_RELOADING": "bear", "BUYER_EXHAUSTION": "bear",
}

EXPECTATION = {
    "PASSIVE_BUYING": "Accumulation continues — dips likely bought",
    "PASSIVE_SELLING": "Distribution continues — rallies likely capped",
    "AGGRESSIVE_BUYING": "Continuation while the aggression lasts",
    "AGGRESSIVE_SELLING": "Continuation while the aggression lasts",
    "BUYER_RELOADING": "Programme buying — expect the advance to resume",
    "SELLER_RELOADING": "Programme selling — expect the decline to resume",
    "BUYER_EXHAUSTION": "Advance out of fuel — reversal risk rising",
    "SELLER_EXHAUSTION": "Decline out of fuel — reversal risk rising",
    "NONE": "No institutional edge to read",
}

_STARS = ((5, 5), (4, 4), (3, 3), (2, 2), (0, 1))


def _s(v) -> str:
    return str(v or "").upper()


def _stars(cycles: int) -> str:
    n = next((st for th, st in _STARS if cycles >= th), 1)
    return "★" * n + "☆" * (5 - n)


def trace_push(trace: Optional[List[str]], behaviour: str,
               keep: int = 12) -> List[str]:
    t = list(trace or [])
    t.append(behaviour)
    return t[-keep:]


def _reloading(trace: Sequence[str], side: str) -> bool:
    """absorb → pause → absorb again = a programme, not a one-off fill.

    Requires the pattern to have BROKEN and RESUMED; continuous absorption is
    just one long fill and is already reported as passive buying/selling.
    """
    want = "PASSIVE_BUYING" if side == "buyer" else "PASSIVE_SELLING"
    recent = list(trace or [])[-8:]
    if recent.count(want) < 2:
        return False
    idx = [i for i, v in enumerate(recent) if v == want]
    # a genuine gap between two absorption episodes
    return any(b - a >= 2 for a, b in zip(idx, idx[1:]))


def classify(ltp: Optional[Dict[str, Any]] = None,
             reaction: Optional[Dict[str, Any]] = None,
             flow: Optional[Dict[str, Any]] = None,
             trace: Optional[Sequence[str]] = None,
             duration_cycles: int = 0) -> Dict[str, Any]:
    """Interpret institutional behaviour from finished engine reads.

    ltp      — Stage 50 output (price/buyers/sellers/flow/volume states)
    reaction — Stage 42 active reaction (acceptance/rejection/trap)
    flow     — {'cvd_slope', 'volume_state', 'mf_state'} extras if available
    trace    — this engine's own recent behaviours (for reloading)
    """
    lb, rc, fl = ltp or {}, reaction or {}, flow or {}
    price = _s((lb.get("price") or {}).get("state"))
    buyers = _s((lb.get("buyers") or {}).get("state"))
    sellers = _s((lb.get("sellers") or {}).get("state"))
    vol = _s((lb.get("volume") or {}).get("state"))
    mflow = _s((lb.get("flow") or {}).get("state"))
    react = _s(rc.get("state"))

    reasons: List[str] = []
    flat = price in ("FLAT", "COMPRESSING")

    behaviour = "NONE"

    # ── 1-2 · PASSIVE: the counter-intuitive read. Aggression on one side with
    # price refusing to move means the OTHER side is quietly being filled.
    if buyers == "ABSORBING" or (sellers == "BUILDING" and flat and
                                 react in ("REJECTION", "DEFENDED", "")):
        behaviour = "PASSIVE_BUYING"
        reasons.append("Aggressive selling met by flat price — supply being "
                       "absorbed")
    elif sellers == "ABSORBING" or (buyers == "BUILDING" and flat and
                                    react in ("REJECTION", "DEFENDED", "")):
        behaviour = "PASSIVE_SELLING"
        reasons.append("Aggressive buying met by flat price — demand being "
                       "capped")
    # ── 6 · EXHAUSTION: the move continues but its fuel is draining
    elif buyers == "EXHAUSTED" or (price == "RISING" and vol == "DRY"
                                   and mflow != "ENTERING"):
        behaviour = "BUYER_EXHAUSTION"
        reasons.append("Advance continuing on fading volume and flow")
    elif sellers == "EXHAUSTED" or (price == "FALLING" and vol == "DRY"
                                    and mflow != "LEAVING"):
        behaviour = "SELLER_EXHAUSTION"
        reasons.append("Decline continuing on fading volume and flow")
    # ── 3-4 · AGGRESSIVE: price, volume and delta all pushing the same way
    elif price in ("RISING", "EXPLODING") and buyers == "BUILDING" and \
            vol in ("HEALTHY", "EXPLOSIVE"):
        behaviour = "AGGRESSIVE_BUYING"
        reasons.append("Price, volume and delta advancing together")
    elif price in ("FALLING", "EXPLODING") and sellers == "BUILDING" and \
            vol in ("HEALTHY", "EXPLOSIVE"):
        behaviour = "AGGRESSIVE_SELLING"
        reasons.append("Price, volume and delta declining together")

    # ── 5 · RELOADING outranks a single passive episode ──
    if behaviour == "PASSIVE_BUYING" and _reloading(trace, "buyer"):
        behaviour = "BUYER_RELOADING"
        reasons.append("Absorbed, paused, absorbing again — programme buying")
    elif behaviour == "PASSIVE_SELLING" and _reloading(trace, "seller"):
        behaviour = "SELLER_RELOADING"
        reasons.append("Absorbed, paused, absorbing again — programme selling")

    if react in ("BULL_TRAP", "BEAR_TRAP") and behaviour != "NONE":
        reasons.append(f"{react.replace('_', ' ').title()} in play at the level")

    conf = _confidence(behaviour, lb, rc, duration_cycles)
    return {"behaviour": behaviour, "label": LABEL[behaviour],
            "tone": TONE.get(behaviour, "neutral"),
            "confidence": conf, "duration_cycles": duration_cycles,
            "stars": _stars(duration_cycles),
            "expectation": EXPECTATION[behaviour],
            "reasons": reasons, "passive": behaviour.startswith("PASSIVE"),
            "aggressive": behaviour.startswith("AGGRESSIVE")}


def _confidence(behaviour: str, lb: Dict[str, Any], rc: Dict[str, Any],
                duration: int) -> int:
    if behaviour == "NONE":
        return 0
    base = 55.0
    # a direct absorbing read from Stage 50 is stronger evidence than an
    # inference from price-plus-pressure
    if _s((lb.get("buyers") or {}).get("state")) == "ABSORBING" or \
            _s((lb.get("sellers") or {}).get("state")) == "ABSORBING":
        base += 15.0
    if behaviour.endswith("RELOADING"):
        base += 12.0
    base += min(20.0, duration * 2.5)
    if rc.get("confidence"):
        try:
            base += min(8.0, float(rc["confidence"]) * 0.08)
        except (TypeError, ValueError):
            pass
    return int(max(0, min(96, round(base))))


def story(read: Optional[Dict[str, Any]],
          zone_label: Optional[str] = None) -> str:
    """The institutional explanation — what the AI thesis says instead of
    'buyers absorbing selling'."""
    r = read or {}
    b = r.get("behaviour")
    if not b or b == "NONE":
        return "No clear institutional footprint in the current flow."
    where = f" near {zone_label}" if zone_label else ""
    dur = r.get("duration_cycles", 0)
    held = f" This has persisted {dur} cycles." if dur >= 3 else ""
    if b == "PASSIVE_BUYING":
        return (f"Institutions are passively absorbing aggressive selling"
                f"{where}. Price is no longer responding to heavy sell "
                f"pressure, suggesting inventory accumulation rather than "
                f"panic selling.{held}")
    if b == "PASSIVE_SELLING":
        return (f"Institutions are passively absorbing aggressive buying"
                f"{where}. Price is not extending despite persistent demand, "
                f"suggesting inventory distribution into strength.{held}")
    if b == "BUYER_RELOADING":
        return (f"Buyers have absorbed, paused and are absorbing again{where} — "
                f"the signature of programme buying rather than a single fill."
                f"{held}")
    if b == "SELLER_RELOADING":
        return (f"Sellers have absorbed, paused and are absorbing again{where} — "
                f"the signature of programme selling rather than a single fill."
                f"{held}")
    if b == "AGGRESSIVE_BUYING":
        return (f"Buyers are lifting offers aggressively{where}; price, volume "
                f"and delta are advancing together.{held}")
    if b == "AGGRESSIVE_SELLING":
        return (f"Sellers are hitting bids aggressively{where}; price, volume "
                f"and delta are declining together.{held}")
    if b == "BUYER_EXHAUSTION":
        return (f"The advance is continuing{where} but on fading volume and "
                f"flow — buyers are running out of fuel, not being overwhelmed."
                f"{held}")
    return (f"The decline is continuing{where} but on fading volume and flow — "
            f"sellers are running out of fuel, not being overwhelmed.{held}")
