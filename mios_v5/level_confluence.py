"""⚔️ Level Confluence — does the other evidence agree with the S/R read?

**Observational only.** Nothing here creates, modifies or influences a
BUY/SELL decision, a Guardian verdict, the Entry Gate, or any V5/V6 verdict.
It is not a signal engine. It recomputes nothing: every input is an output
some existing engine already published this cycle.

`classify_leg_sr_behavior` decides BUILDING / ACCEPTING / REJECTING / BREAKING
from ONE input — the leg's own volume order blocks. That is a structural read.
It says nothing about whether the volume profile, the high-volume nodes, the
block's own buyer/seller split, or the order flow agree with it. All four are
computed per leg every cycle and published; this module reads them and answers
one question per level: **how many independent sources corroborate it.**

Three states, never two
-----------------------
Every component reports `confirmed`, `contradicted` or `not_reported`. Missing
data is not disagreement — the money-flow profile does not exist early in a
session, and scoring its absence as a failure would mark every leg down all
morning for a reason that has nothing to do with the market.

The score is `confirmed / checked`, and `checked` counts only sources that
actually had data. It is an evidence tally, NOT a probability, and the labels
are deliberately explanatory rather than directional.

Level-specific, not direction-generic
-------------------------------------
"Is delta bullish?" is the wrong question. What confirms a level depends on
which level and what price is doing to it: falling flow supports a rejection
at resistance and contradicts a break of it. BUILDING and ACCEPTING are
proximity states — flow direction does not confirm or contradict them, so
they report `not_reported` for flow rather than borrowing a verdict.

Pure: no Streamlit, no Telegram, no orders, no network, no state mutation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

CONFIRMED = "confirmed"
CONTRADICTED = "contradicted"
NOT_REPORTED = "not_reported"

#: Glyph per verdict, for whatever renders this.
GLYPH = {CONFIRMED: "✓", CONTRADICTED: "✕", NOT_REPORTED: "?"}

#: Components, in the order they read on screen.
COMPONENTS = ("structure", "mfp", "hvn", "vob", "oi", "depth", "delta", "cvd")

#: ⚠️ OI and depth belong to the CONTRACT — a strike and a side — not to a
#: price level on the leg's own premium chart. Neither can tell you whether
#: ₹109.88 is a real resistance for that call; they describe the pressure on
#: the leg as a whole. They are included on the same footing as the flow
#: columns, and never as structural evidence about the level itself.
CONTRACT_LEVEL = ("oi", "depth")

#: Explanatory only. Never BUY / SELL / ENTRY / TRADE / TARGET / PROFIT — this
#: layer describes evidence, it does not advise.
HIGH = "HIGH CONFIRMATION"
MODERATE = "MODERATE CONFIRMATION"
LOW = "LOW CONFIRMATION"
MIXED = "MIXED"
INSUFFICIENT = "INSUFFICIENT DATA"

#: The app's order-flow delta is inferred from 1-minute OHLC — the CLV split,
#: `(close - low) / (high - low)` — not from tick or lower-timeframe data. It
#: is an estimate and is labelled as one wherever it is shown.
DELTA_LABEL = "Δ proxy"

#: States where price is AT a level rather than resolving it. Flow direction
#: neither confirms nor contradicts proximity, so it is not scored.
PROXIMITY_STATES = ("BUILDING", "ACCEPTING")

#: States where flow direction is meaningful, and which sign supports them.
#: (state, side) -> True when POSITIVE flow supports it.
_POSITIVE_SUPPORTS = {
    ("REJECTING", "resistance"): False,   # rejected at resistance -> sellers
    ("BREAKING", "resistance"): True,     # broke resistance -> buyers
    ("REJECTING", "support"): True,       # bounced off support -> buyers
    ("BREAKING", "support"): False,       # broke support -> sellers
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def level_tolerance(ltp) -> float:
    """`max(LTP * 0.005, 0.50)` — the classifier's own tolerance, unchanged.

    Shared deliberately. If this differed, a level the classifier calls
    BUILDING could simultaneously be reported here as far from its POC.
    """
    price = _f(ltp) or 0.0
    return max(price * 0.005, 0.5)


def _near(a, b, tol: float) -> Optional[bool]:
    fa, fb = _f(a), _f(b)
    if fa is None or fb is None:
        return None
    return abs(fa - fb) <= tol


def _verdict(agreed: Optional[bool]) -> str:
    if agreed is None:
        return NOT_REPORTED
    return CONFIRMED if agreed else CONTRADICTED


def flow_expectation(state: Any, side: Any) -> Optional[bool]:
    """Does POSITIVE flow support this state at this side?

    `None` for proximity states and anything unrecognised — the caller must
    then report flow as `not_reported` rather than inventing a direction.
    """
    key = (str(state or "").strip().upper(), str(side or "").strip().lower())
    if key[0] in PROXIMITY_STATES:
        return None
    return _POSITIVE_SUPPORTS.get(key)


def _prices(nodes: Optional[Sequence[Any]]) -> List[float]:
    out: List[float] = []
    for n in nodes or []:
        v = (_f(n.get("price") or n.get("mid") or n.get("level"))
             if isinstance(n, Mapping) else _f(n))
        if v is not None:
            out.append(v)
    return out


def zone_for_level(zones: Optional[Sequence[Any]], level, tol: float):
    """The order block a level came from — containment first, midpoint second.

    The level IS a block's midpoint by construction, so a block whose range
    covers it is the one that produced it.
    """
    lv = _f(level)
    if lv is None:
        return None
    for z in zones or []:
        if not isinstance(z, Mapping):
            continue
        lo, hi = _f(z.get("lower")), _f(z.get("upper"))
        if lo is not None and hi is not None and lo <= lv <= hi:
            return z
    for z in zones or []:
        if isinstance(z, Mapping) and _near(z.get("mid"), lv, tol):
            return z
    return None


def _mfp_detail(level, mfp: Optional[Mapping[str, Any]], tol: float):
    """(verdict, note) for the money-flow profile — POC, then value edges."""
    poc = _f((mfp or {}).get("poc_price"))
    vah = _f((mfp or {}).get("value_area_high"))
    val = _f((mfp or {}).get("value_area_low"))
    if poc is None and vah is None and val is None:
        return NOT_REPORTED, "no profile"
    if _near(level, poc, tol):
        return CONFIRMED, "POC"
    if _near(level, vah, tol):
        return CONFIRMED, "VAH"
    if _near(level, val, tol):
        return CONFIRMED, "VAL"
    return CONTRADICTED, "not at POC/VA"


def _node_detail(level, hvn, lvn, tol: float):
    """(verdict, note) for volume nodes. An LVN is reported, not scored as a
    contradiction: a level in thin volume is a different fact, not a failure
    of the level to exist."""
    highs, lows = _prices(hvn), _prices(lvn)
    if not highs and not lows:
        return NOT_REPORTED, "no nodes"
    if any(_near(level, p, tol) for p in highs):
        return CONFIRMED, "HVN"
    if any(_near(level, p, tol) for p in lows):
        return CONTRADICTED, "LVN (thin)"
    return CONTRADICTED, "not at a node"


def _vob_detail(zone, wants_positive: Optional[bool]):
    """(verdict, note) from the block's own buyer/seller split.

    `bull_pct` is the share of the zone's volume that was buying. Whether that
    supports the read depends on the interaction, which is why the expectation
    is passed in rather than decided here.
    """
    if not zone:
        return NOT_REPORTED, "no zone"
    bull = _f(zone.get("bull_pct"))
    if bull is None:
        return NOT_REPORTED, "no split"
    if wants_positive is None:
        return NOT_REPORTED, "proximity state"
    buyer_heavy = bull > 50.0
    note = "buyer-heavy" if buyer_heavy else "seller-heavy"
    return _verdict(buyer_heavy is wants_positive), note


def _oi_detail(oi: Optional[Mapping[str, Any]]):
    """(verdict, note) from the leg's own open interest.

    Deliberately NOT directional. "Is OI bullish?" has no answer without
    knowing who wrote what; what OI does say is whether positions are being
    ADDED at this level or closed out. Fresh positioning corroborates an
    interaction; unwinding is the same price doing less work.

    That makes it the one flow-family column that means something for the
    proximity states too — "positions building here" is precisely what
    BUILDING describes, and it needs no direction to say so.
    """
    if not oi:
        return NOT_REPORTED, "no OI"
    chg = _f(oi.get("chg_oi"))
    if chg is None:
        return NOT_REPORTED, "no ΔOI"
    if chg == 0:
        return NOT_REPORTED, "flat"
    scale = f" ({chg / 1e5:+.2f}L)" if abs(chg) >= 1e4 else ""
    if chg > 0:
        return CONFIRMED, f"OI rising — fresh positions{scale}"
    return CONTRADICTED, f"OI falling — unwinding{scale}"


def _depth_detail(depth: Optional[Mapping[str, Any]],
                  wants_positive: Optional[bool]):
    """(verdict, note) from resting bid/ask quantity on this leg.

    A snapshot of orders WAITING, not trades DONE — which is what separates it
    from the delta column beside it. Resting size can be pulled; executed
    volume cannot. Treated as directional pressure, so like delta it says
    nothing about a proximity state.
    """
    if not depth:
        return NOT_REPORTED, "no depth"
    bid = _f(depth.get("bid_qty"))
    ask = _f(depth.get("ask_qty"))
    if bid is None or ask is None or (bid + ask) <= 0:
        return NOT_REPORTED, "no depth"
    if wants_positive is None:
        return NOT_REPORTED, "proximity state"
    if bid == ask:
        return NOT_REPORTED, "balanced"
    bid_heavy = bid > ask
    ratio = (bid / ask) if ask else float("inf")
    note = (f"bids {ratio:.1f}x asks" if bid_heavy
            else f"asks {(ask / bid if bid else float('inf')):.1f}x bids")
    return _verdict(bid_heavy is wants_positive), note


def _flow_detail(delta: Optional[Mapping[str, Any]],
                 wants_positive: Optional[bool]):
    """(verdict, note) for the estimated delta."""
    dpct = _f((delta or {}).get("delta_pct"))
    if dpct is None:
        return NOT_REPORTED, "no flow"
    if wants_positive is None:
        return NOT_REPORTED, "proximity state"
    sign = "positive" if dpct > 0 else "negative" if dpct < 0 else "flat"
    if dpct == 0:
        return NOT_REPORTED, "flat"
    return _verdict((dpct > 0) is wants_positive), f"{sign} {DELTA_LABEL}"


def _cvd_detail(delta: Optional[Mapping[str, Any]],
                wants_positive: Optional[bool]):
    """(verdict, note) for CVD — only when a CVD is actually published.

    `order_flow.totals` publishes buy/sell/delta and no CVD, so on today's
    stores this reports `not_reported`. It is wired anyway so that adding a
    CVD writer needs no change here, and NOT faked from delta in the meantime.
    """
    for key in ("cvd", "cvd_sum", "cvd_normalised"):
        v = _f((delta or {}).get(key))
        if v is not None:
            if wants_positive is None:
                return NOT_REPORTED, "proximity state"
            if v == 0:
                return NOT_REPORTED, "flat"
            return _verdict((v > 0) is wants_positive), (
                "rising" if v > 0 else "falling")
    state = str((delta or {}).get("cvd_state") or "").strip().upper()
    if state in ("RISING", "FALLING"):
        if wants_positive is None:
            return NOT_REPORTED, "proximity state"
        return _verdict((state == "RISING") is wants_positive), state.lower()
    return NOT_REPORTED, "no CVD"


def quality(confirmed: int, checked: int, contradicted: int) -> str:
    """An explanatory label for the tally. Never directional, never advice."""
    if checked <= 1:
        return INSUFFICIENT
    share = confirmed / checked
    if share >= 0.8:
        return HIGH
    if share >= 0.6:
        return MODERATE
    if confirmed and contradicted:
        return MIXED
    return LOW


def evaluate_level(read: Optional[Mapping[str, Any]], ltp=None, *,
                   side: Optional[str] = None,
                   mfp: Optional[Mapping[str, Any]] = None,
                   hvn: Optional[Sequence[Any]] = None,
                   lvn: Optional[Sequence[Any]] = None,
                   zones: Optional[Sequence[Any]] = None,
                   delta: Optional[Mapping[str, Any]] = None,
                   oi: Optional[Mapping[str, Any]] = None,
                   depth: Optional[Mapping[str, Any]] = None
                   ) -> Dict[str, Any]:
    """One level's evidence tally.

    Returns `{side, state, level, ltp, distance, reported, components,
    confirmed, contradicted, checked, score, quality}`.

    `reported` is False when there is no level to evaluate — the caller shows
    "not reported", never a failed score.
    """
    side_name = str(side or (read or {}).get("side") or "").strip().lower() or None
    state = str((read or {}).get("state") or "").strip().upper()
    level = _f((read or {}).get("level"))
    price = _f(ltp)

    base: Dict[str, Any] = {
        "side": side_name, "state": state or None, "level": level,
        "ltp": price, "distance": None, "reported": False,
        "components": {}, "confirmed": 0, "contradicted": 0, "checked": 0,
        "score": None, "quality": INSUFFICIENT,
    }
    if level is None or state in ("", "NONE"):
        return base

    tol = level_tolerance(price if price is not None else level)
    wants_positive = flow_expectation(state, side_name)

    zone = zone_for_level(zones, level, tol)
    near = _near(level, price, tol) if price is not None else None

    # The structure check is ±1 tolerance. The classifier's BUILDING band is
    # ±3, so a leg can legitimately read BUILDING here and still fail this —
    # it is inside the state's band but outside the tighter "at the level"
    # test. The note carries both numbers so that pairing explains itself
    # instead of looking like a contradiction.
    gap = abs(price - level) if price is not None else None
    if near is None:
        structure = (NOT_REPORTED, "no LTP")
    elif near:
        structure = (CONFIRMED, f"at level (±{tol:.2f})")
    else:
        structure = (CONTRADICTED, f"{gap:.2f} away, outside ±{tol:.2f}")

    details = {
        "structure": structure,
        "mfp": _mfp_detail(level, mfp, tol),
        "hvn": _node_detail(level, hvn, lvn, tol),
        "vob": _vob_detail(zone, wants_positive),
        "oi": _oi_detail(oi),
        "depth": _depth_detail(depth, wants_positive),
        "delta": _flow_detail(delta, wants_positive),
        "cvd": _cvd_detail(delta, wants_positive),
    }

    components: Dict[str, Dict[str, str]] = {}
    confirmed = contradicted = checked = 0
    for key in COMPONENTS:
        verdict, note = details[key]
        components[key] = {"verdict": verdict, "note": note,
                           "glyph": GLYPH[verdict]}
        if verdict == NOT_REPORTED:
            continue
        checked += 1
        if verdict == CONFIRMED:
            confirmed += 1
        else:
            contradicted += 1

    base.update({
        "reported": True,
        "distance": (price - level) if price is not None else None,
        "components": components,
        "confirmed": confirmed, "contradicted": contradicted,
        "checked": checked,
        "score": (f"{confirmed}/{checked}" if checked else None),
        "quality": quality(confirmed, checked, contradicted),
    })
    return base


def evaluate_leg(sr: Optional[Mapping[str, Any]], ltp=None, *,
                 label: Optional[str] = None, reason: Optional[str] = None,
                 mfp=None, hvn=None, lvn=None, zones=None, delta=None,
                 oi=None, depth=None) -> List[Dict[str, Any]]:
    """Both sides of one leg — resistance first, then support.

    `sr["sides"]` carries each side's own read. An absent side is returned
    with `reported: False` so the caller can say "no valid level" rather than
    dropping the row or showing it as a failure.

    `reason` is carried through untouched onto every unreported row. A table
    of four blanks that cannot say WHY is the same defect this app has now hit
    twice: "no level" and "the engine never ran" look identical, and only one
    of them means something is wrong. The caller supplies it from the owner
    that already computes it rather than a second copy being grown here.
    """
    per_side = dict((sr or {}).get("sides") or {})
    if not per_side and (sr or {}).get("side"):
        per_side = {str(sr["side"]).strip().lower(): sr}

    out: List[Dict[str, Any]] = []
    for side in ("resistance", "support"):
        row = evaluate_level(per_side.get(side), ltp, side=side, mfp=mfp,
                             hvn=hvn, lvn=lvn, zones=zones, delta=delta,
                             oi=oi, depth=depth)
        row["label"] = str(label or "")
        if not row["reported"] and reason:
            row["reason"] = reason
        out.append(row)
    return out
