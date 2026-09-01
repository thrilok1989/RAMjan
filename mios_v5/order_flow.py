"""MIOS V6 — the Order Flow Family.

Money Flow, Candle Delta, CVD, CSV, CBV, Volume and VOB are **not** seven
indicators. They are seven views of one thing: who is transacting, and with how
much urgency. Letting them vote separately counts the same order flow up to
seven times, which is how a single tape ends up outvoting the dealer book.

So they collapse here, once, into a single family result:

    direction · strength · reliability · confidence

and only that result is allowed into Stage 53.

## This module calculates NOTHING

Every input is a value V5 already computed. There is no `money_flow_v6()`, no
`cvd_v6()`, no `delta_v6()` — deliberately, and `test_no_duplicate_order_flow_
engine_exists` fails the build if one appears. V5 is the calculation layer; V6
reads it, correlates it, and explains it. A second implementation of CVD would
not just be waste, it would be a second *answer*, and the two would drift.

## Volume does not vote

Volume has no direction. A big bar is not bullish; it is *loud*. Making volume
a directional member would be casting a ballot on magnitude. It feeds
reliability instead — the same for a volume spike whichever way price went.

## Reliability is not agreement

Because these members are correlated by construction, six of them agreeing is
much weaker evidence than six independent families agreeing. Reliability
therefore reflects **coverage** (how many members actually reported) as well as
coherence, and is capped so a family speaking from two members can never claim
the confidence of one speaking from seven.

Pure module: dicts in, dict out. No pandas, no session, no IO.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: directional members, and their weight inside the family.
#: CVD and Money Flow lead: they are cumulative, so they carry the session's
#: memory rather than the last bar's noise. Candle Delta is the fastest and the
#: least reliable alone. CSV/CBV are the two halves of the same split, so they
#: are weighted as one between them.
MEMBERS: Dict[str, float] = {
    "money_flow": 3.0,
    "cvd": 3.0,
    "vob": 2.0,
    "candle_delta": 1.5,
    "cbv": 0.75,
    "csv": 0.75,
}

#: present, but never directional. See the module docstring.
NON_DIRECTIONAL = ("volume",)

#: every member the family knows about, for display and coverage counting
ALL_MEMBERS = tuple(MEMBERS) + NON_DIRECTIONAL

_SIGN = {
    "BULL": 1.0, "BULLISH": 1.0, "STRONG_BULL": 2.0, "STRONG_BULLISH": 2.0,
    "BUY": 1.0, "POSITIVE": 1.0, "UP": 1.0, "ENTERING": 1.0, "BUILDING": 1.0,
    "BEAR": -1.0, "BEARISH": -1.0, "STRONG_BEAR": -2.0, "STRONG_BEARISH": -2.0,
    "SELL": -1.0, "NEGATIVE": -1.0, "DOWN": -1.0, "LEAVING": -1.0,
    "FADING": -1.0,
    "NEUTRAL": 0.0, "FLAT": 0.0, "NONE": 0.0, "BALANCED": 0.0,
}

#: below this the family says NEUTRAL rather than inventing a lean
_DIRECTION_FLOOR = 0.12


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def member_sign(reading: Any) -> Optional[float]:
    """One member's lean in [-2, +2], or `None` when it did not report.

    Accepts the shapes the app's caches actually use: a label ("BULL",
    "💰 Entering"), a signed number (delta, CVD slope), or a dict carrying
    either under `direction`/`state`/`bias`/`value`.

    `None` is not zero. A member that did not report must not be counted as a
    member that reported "neutral" — that would quietly inflate coverage, and
    coverage is what reliability is built on.
    """
    if reading is None:
        return None
    if isinstance(reading, dict):
        for key in ("direction", "bias", "state", "label", "value", "net"):
            if key in reading and reading[key] is not None:
                got = member_sign(reading[key])
                if got is not None:
                    return got
        return None
    if isinstance(reading, bool):
        return None
    num = _f(reading)
    if num is not None and not isinstance(reading, str):
        return 1.0 if num > 0 else -1.0 if num < 0 else 0.0

    text = str(reading).strip().upper()
    if not text:
        return None
    for word, sign in _SIGN.items():
        if word in text:
            return sign
    return None


def family(readings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The whole family as one vote.

    `readings` maps member name → whatever V5 already produced for it. Members
    absent from the dict simply do not participate; nothing is defaulted.
    """
    r = dict(readings or {})

    members: List[Dict[str, Any]] = []
    weighted = 0.0
    total_weight = 0.0
    bulls = bears = 0

    for name, weight in MEMBERS.items():
        sign = member_sign(r.get(name))
        members.append({
            "name": name, "weight": weight, "sign": sign,
            "reported": sign is not None,
            "direction": ("BULLISH" if (sign or 0) > 0 else
                          "BEARISH" if (sign or 0) < 0 else
                          "NEUTRAL" if sign is not None else None),
        })
        if sign is None:
            continue
        total_weight += weight
        weighted += sign * weight
        if sign > 0:
            bulls += 1
        elif sign < 0:
            bears += 1

    # volume: reported for display and for reliability, never for direction
    vol = r.get("volume")
    vol_mult = _volume_multiple(vol)
    members.append({"name": "volume", "weight": 0.0,
                    "sign": None, "reported": vol is not None,
                    "direction": None, "multiple": vol_mult,
                    "note": "confirms conviction, not direction"})

    reported = [m for m in members if m["reported"]]
    directional = [m for m in members if m["reported"] and m["weight"] > 0]

    if not directional:
        return _empty(members, r)

    # ── strength: the net lean, normalised. `total_weight` is the weight that
    # actually reported, so a family speaking from two members is measured
    # against two members — not penalised twice, once here and again below.
    net = weighted / total_weight if total_weight else 0.0
    strength = int(round(min(1.0, abs(net) / 2.0) * 100))

    direction = ("BULLISH" if net > _DIRECTION_FLOOR else
                 "BEARISH" if net < -_DIRECTION_FLOOR else "NEUTRAL")

    # ── reliability: coverage × coherence, then the volume confirmation.
    coverage = total_weight / sum(MEMBERS.values())
    voted = bulls + bears
    coherence = (max(bulls, bears) / voted) if voted else 0.0
    reliability = int(round(100 * coverage * coherence))
    if vol_mult is not None:
        # a lean on thin volume is a lean nobody had to pay for
        reliability = int(round(reliability *
                                (1.15 if vol_mult >= 1.5 else
                                 0.80 if vol_mult < 0.7 else 1.0)))
    reliability = max(0, min(100, reliability))

    # ── confidence: never above reliability. A hard lean from two of seven
    # members is a strong reading of very little, and must not present as
    # certainty.
    confidence = int(round(min(strength, reliability)
                           if direction != "NEUTRAL" else
                           min(strength, reliability) * 0.5))

    return {
        "family": "orderflow",
        "direction": direction,
        "strength": strength,
        "reliability": reliability,
        "confidence": confidence,
        "net": round(net, 3),
        "members": members,
        "reported": len(reported),
        "of": len(ALL_MEMBERS),
        "missing": [m["name"] for m in members if not m["reported"]],
        "agreement": f"{max(bulls, bears)}/{voted}" if voted else "0/0",
        "volume_multiple": vol_mult,
        "summary": _summarise(direction, strength, reliability,
                              len(reported), vol_mult),
        # binding: this family produces ONE vote. Its members never vote
        # individually — they describe the same order flow from different
        # angles, and counting them separately counts the tape seven times.
        "single_vote": True,
    }


def _empty(members, readings) -> Dict[str, Any]:
    return {
        "family": "orderflow", "direction": "NEUTRAL",
        "strength": 0, "reliability": 0, "confidence": 0, "net": 0.0,
        "members": members, "reported": 0, "of": len(ALL_MEMBERS),
        "missing": [m["name"] for m in members if not m["reported"]],
        "agreement": "0/0",
        "volume_multiple": _volume_multiple(readings.get("volume")),
        "summary": "No order-flow member has reported yet.",
        "single_vote": True,
    }


def _volume_multiple(vol) -> Optional[float]:
    """Volume as a multiple of its own average, when the caller supplied one."""
    if isinstance(vol, dict):
        for key in ("mult", "multiple", "ratio", "vs_avg"):
            got = _f(vol.get(key))
            if got is not None:
                return round(got, 2)
        return None
    got = _f(vol)
    return round(got, 2) if got is not None else None


def _summarise(direction, strength, reliability, reported, vol_mult) -> str:
    if direction == "NEUTRAL":
        base = "Order flow is balanced"
    else:
        word = "buyers" if direction == "BULLISH" else "sellers"
        base = f"Order flow favours {word} ({strength}%)"
    tail = f"{reported}/{len(ALL_MEMBERS)} members reporting"
    if reliability < 40:
        tail += " — thin, treat as a hint"
    if vol_mult is not None and vol_mult < 0.7:
        tail += "; volume below average"
    return f"{base} · {tail}."


def readings_for_nifty(mf=None, delta=None, cvd=None, cbv=None, csv=None,
                       volume=None, vob=None) -> Dict[str, Any]:
    """Name the seven values without touching how any of them was produced."""
    return {"money_flow": mf, "candle_delta": delta, "cvd": cvd,
            "cbv": cbv, "csv": csv, "volume": volume, "vob": vob}


def display_rows(fam: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per member, for the dashboard — values only, never recomputed."""
    out = []
    for m in (fam or {}).get("members", []):
        out.append({
            "name": m["name"].replace("_", " ").title(),
            "direction": m.get("direction") or "—",
            "reported": m.get("reported", False),
            "note": m.get("note"),
            "multiple": m.get("multiple"),
        })
    return out
