"""MIOS V6 — Support & Resistance Intelligence (a level is an object, not a line).

A horizontal line tells you where. This tells you **why it matters, who is
defending it, whether it is strengthening, whether it can be trusted, what to
expect, and exactly where to enter, stop, trail and target.**

It assembles — it computes almost nothing. Origin/strength/lifecycle/health/
battle/probabilities/HTF come from `zone_intel`; acceptance from Stage 42;
absorption from Stage 43; bias-at-level from Stage 47; entry/stop/trail from
Stage 52. This module's job is to put twenty scattered facts into one object a
trader can read in ten seconds, and to RANK the levels so the most important one
is unmistakably first.

Ranking matters more than it looks: three levels shown as equals force the
trader to compare them. One level shown as 🥇 has already made the comparison.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_TRAP_BANDS = ((80, "Extreme", "#ff2d55"), (65, "High", "#ff4444"),
               (45, "Medium", "#ff9500"), (25, "Low", "#ffcc33"),
               (0, "Very Low", "#00ff88"))

_DEFENDER = {
    "dealers": "Dealers", "institutions": "Institutions",
    "options": "Options Writers", "liquidity": "Liquidity",
    "spot": "Buyers/Sellers",
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def trap_risk(pct: Optional[float]) -> Dict[str, Any]:
    """Trap probability → the five-band label a trader can act on."""
    p = _f(pct)
    if p is None:
        return {"pct": None, "label": "Unknown", "colour": "#8fa1b3"}
    for threshold, label, colour in _TRAP_BANDS:
        if p >= threshold:
            return {"pct": round(p), "label": label, "colour": colour}
    return {"pct": round(p), "label": "Very Low", "colour": "#00ff88"}


def defended_by(card: Optional[Dict[str, Any]],
                absorption: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """WHO is holding this level — read from the zone's own health categories,
    not from a global controller. A level can be defended by dealers while
    institutions are elsewhere; that distinction is the useful part."""
    hl = (card or {}).get("health") or {}
    cats = hl.get("categories") or {}
    building = [k for k, v in cats.items() if v == "building"]
    beh = _s((absorption or {}).get("behaviour"))

    if not building:
        if hl.get("conflicted"):
            return {"who": "Mixed", "detail": "groups disagree at this level"}
        return {"who": "Nobody", "detail": "no group is actively defending"}

    # authority order — the highest-authority group that is building owns it
    for key in ("institutions", "dealers", "options", "liquidity", "spot"):
        if key in building:
            who = _DEFENDER.get(key, key.title())
            extra = ""
            if "PASSIVE" in beh or "RELOADING" in beh:
                extra = f" · {(absorption or {}).get('label', '')}"
            return {"who": who,
                    "detail": f"{len(building)}/{len(cats)} groups building{extra}"}
    return {"who": "Mixed", "detail": f"{len(building)} groups building"}


def bias_at_level(card: Optional[Dict[str, Any]],
                  transition: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Bullish / bearish at THIS level, plus whether that is strengthening.

    A support defended by buyers is locally bullish even inside a bearish
    market — that is the whole reason to trade a level rather than a forecast.
    """
    c = card or {}
    btl = c.get("battle") or {}
    winner = btl.get("winner")
    if winner == "Buyers":
        bias, colour = "Bullish", "#00ff88"
    elif winner == "Sellers":
        bias, colour = "Bearish", "#ff4444"
    else:
        bias, colour = "Neutral", "#ffd000"

    life = str(c.get("lifecycle") or "")
    if life in ("building", "recovered"):
        trend = "Strengthening"
    elif life in ("fading", "under-attack", "breaking", "broken"):
        trend = "Weakening"
    else:
        trend = {"WEAKENING": "Weakening", "STRENGTHENING": "Strengthening",
                 "REVERSING": "Reversing"}.get(_s((transition or {}).get("state")),
                                               "Stable")
    return {"bias": bias, "trend": trend, "colour": colour,
            "confidence": btl.get("confidence", 0)}


def summarise(card: Dict[str, Any], defender: Dict[str, Any],
              bias: Dict[str, Any], trap: Dict[str, Any],
              absorption: Optional[Dict[str, Any]] = None) -> List[str]:
    """Maximum three lines. Plain language, no jargon dump."""
    side = str(card.get("side", "")).title()
    lines: List[str] = []

    who = defender.get("who")
    if who not in ("Nobody", "Mixed"):
        lines.append(f"{side} is being defended by {who.lower()}.")
    elif who == "Mixed":
        lines.append(f"{side} is contested — the groups disagree.")
    else:
        lines.append(f"{side} has no active defender.")

    beh = (absorption or {}).get("label")
    if beh and _s((absorption or {}).get("behaviour")) != "NONE":
        lines.append(f"{beh.split(' ', 1)[-1]} continues." if " " in beh
                     else f"{beh} continues.")
    elif card.get("strength", {}).get("touch_note") == "proven":
        lines.append("The level has been tested and has held.")

    probs = card.get("probabilities") or {}
    if trap.get("label") in ("High", "Extreme"):
        lines.append(f"Trap risk is {trap['label'].lower()} — do not chase.")
    elif probs.get("rejection", 0) >= 60:
        lines.append(f"Bounce probability remains "
                     f"{'high' if probs['rejection'] >= 70 else 'moderate'}.")
    elif probs.get("break", 0) >= 60:
        lines.append("Break probability is increasing.")
    return lines[:3]


def _as_scored(v: Any, key: str = "score") -> Dict[str, Any]:
    """`{"score": n}` from either the enriched dict or a bare number."""
    if isinstance(v, dict):
        return v
    n = _f(v)
    return {key: n} if n is not None else {}


def resolve_side(price, spot, labelled=None):
    """`(side, flipped)` — where the level sits NOW, not what it was called.

    The Reaction-Zone engine names a level when it forms. Once price crosses
    it, that name goes stale: a resistance the market breaks above becomes
    support, and the panel kept calling it resistance — printing "Bounce
    probability remains high" about a floor, and pairing it with a short's
    stop above the entry.

    Polarity is not an opinion. A level below spot is support; above is
    resistance. `flipped` records that the market overturned the original
    label, which is itself worth showing — a flipped level is a level that has
    just been broken.

    With no spot to compare against, the stored label stands: guessing would
    be worse than deferring.
    """
    p, s = _f(price), _f(spot)
    lab = _s(labelled) or None
    if p is None or s is None:
        return lab, False
    side = "SUPPORT" if p <= s else "RESISTANCE"
    return side, bool(lab and lab != side)


def target_for(side: Optional[str], price, target):
    """A target only counts when it is on the side the trade would run to.

    The panel showed the same `next_target` on both cards, so a resistance
    short was given a target ABOVE its own entry — and, in the case that
    prompted this, a target identical to its stop. A target that is not in the
    direction of the trade is not a target.
    """
    p, t = _f(price), _f(target)
    if p is None or t is None:
        return None
    if _s(side) == "SUPPORT":
        return t if t > p else None
    if _s(side) == "RESISTANCE":
        return t if t < p else None
    return None


def build_level_intel(card: Optional[Dict[str, Any]],
                      reaction: Optional[Dict[str, Any]] = None,
                      absorption: Optional[Dict[str, Any]] = None,
                      transition: Optional[Dict[str, Any]] = None,
                      decision: Optional[Dict[str, Any]] = None,
                      next_target: Optional[float] = None,
                      target_label: Optional[str] = None,
                      age_min: Optional[float] = None,
                      spot: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """The full twenty-field intelligence object for ONE level."""
    if not card or card.get("price") is None:
        return None
    c = dict(card)
    # ── the side is where the level sits NOW, not what it was called when it
    # was created. See `resolve_side`.
    side, flipped = resolve_side(c.get("price"), spot, c.get("side"))
    labelled_side = c.get("side")
    c["side"] = side
    probs = c.get("probabilities") or {}
    trap = trap_risk(probs.get("trap"))
    defender = defended_by(c, absorption)
    bias = bias_at_level(c, transition)

    # entry / stop / trail come from the Decision Engine — never invented here,
    # and only when the decision actually refers to THIS side
    dec = decision or {}
    same_side = (_s(dec.get("side")) == "CALL" and c.get("side") == "SUPPORT") or \
                (_s(dec.get("side")) == "PUT" and c.get("side") == "RESISTANCE")
    entry = dec.get("entry") if same_side else None
    stop = dec.get("stop") if same_side else None
    trail = (dec.get("trail") or {}) if same_side else {}

    price = _f(c.get("price")) or 0.0
    # an entry ZONE, not a point — the level plus the proven refusal
    if entry:
        lo, hi = sorted((float(entry), price))
        entry_zone = (round(lo), round(hi))
    else:
        band = max(3.0, price * 0.0002)
        entry_zone = (round(price - band), round(price + band))

    # A caller handing a plain number where the enriched card carries a dict
    # should not take the panel down — that is how one malformed level blanked
    # the whole S/R screen.
    strength = _as_scored(c.get("strength"))
    origin = _as_scored(c.get("origin"))
    health = _as_scored(c.get("health"), key="pct")
    conf = int(round((float(origin.get("score") or 0) * 0.35
                      + float(strength.get("score") or 0) * 0.35
                      + float(health.get("pct") or 0) * 0.30)))

    return {
        # 1 basic
        "price": price, "side": c.get("side"),
        "type": ("War Zone" if (c.get("battle") or {}).get("war")
                 else str(c.get("side", "")).title()),
        "active": bool(c.get("at_zone")),
        # 2-5
        "origin": origin, "confluence_stars": origin.get("stars"),
        "confluence_score": origin.get("score"),
        "strength": strength, "lifecycle": c.get("lifecycle"),
        "lifecycle_label": c.get("lifecycle_label"),
        # 6 health
        "health": c.get("health"), "touches": strength.get("touches"),
        "age_min": age_min,
        "freshness": ("High" if (age_min or 0) < 60 else
                      "Medium" if (age_min or 0) < 240 else "Low"),
        # 7-9
        "acceptance": (reaction or {}).get("label") or (c.get("acceptance") or {}).get("label"),
        "acceptance_state": (reaction or {}).get("state"),
        "absorption": (absorption or {}).get("label"),
        "absorption_state": (absorption or {}).get("behaviour"),
        "trap": trap,
        # 10-12
        "htf": c.get("htf"), "defended_by": defender, "bias": bias,
        # 13
        "expected": (c.get("explain") or {}).get("expect"),
        # 14-17
        "entry_zone": entry_zone, "entry": entry,
        "stop": stop or c.get("invalidation"),
        "stop_is_dynamic": bool(stop),
        "trail": trail,
        "next_target": target_for(side, price, next_target),
        "target_label": (target_label
                         if target_for(side, price, next_target) else None),
        "flipped": flipped, "labelled_side": labelled_side,
        # 18-19
        "confidence": conf,
        "summary": summarise(c, defender, bias, trap, absorption),
        "probabilities": probs,
    }


def rank_levels(levels: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Order by how much the trader should care. Three levels shown as equals
    force a comparison; a ranked list has already made it.

    Active (price is here) outranks everything, then confidence, then confluence.
    """
    lv = [l for l in (levels or []) if l]
    medals = ["🥇", "🥈", "🥉"]

    def _key(l):
        return (-int(bool(l.get("active"))),
                -float(l.get("confidence") or 0),
                -float((l.get("origin") or {}).get("score") or 0))

    out = sorted(lv, key=_key)
    for i, l in enumerate(out):
        l["rank"] = i + 1
        l["medal"] = medals[i] if i < len(medals) else f"#{i + 1}"
    return out


def card_from_zone(zone: Optional[Dict[str, Any]], side: str
                   ) -> Optional[Dict[str, Any]]:
    """A minimal zone card from the RAW canonical S/R object.

    `enrich_zone_intel` attaches a full card under `intel`, but it can fail or
    partially fail — the import guard, a bad price, a missing memory row. When
    it does, the panel used to render nothing at all and say "still warming
    up", which is indistinguishable from a cold start and stays on screen
    forever.

    A level with a price and a strength is genuinely useful on its own. This
    builds the smallest card `build_level_intel` accepts so the trader sees the
    level, clearly marked as unenriched, instead of an empty panel.
    """
    z = dict(zone or {})
    price = _f(z.get("price"))
    if price is None:
        return None
    zh = z.get("zone_health") or {}
    strength = _f(z.get("strength"))
    pct = _f(z.get("health_pct"))
    if pct is None:
        pct = _f(zh.get("pct"))
    # shaped to the ENRICHED contract, not to whatever the raw object holds —
    # `build_level_intel` reads `strength["score"]` and `health["pct"]`, and a
    # bare number there is what blanked the panel in the first place
    return {
        "price": price, "side": str(side or "").upper(),
        "strength": {"score": strength} if strength is not None else {},
        "origin": {},
        "health": {"pct": pct} if pct is not None else {},
        "lifecycle": z.get("lifecycle"),
        "lifecycle_label": z.get("lifecycle_label"),
        "status": z.get("status"),
        "enriched": False,
    }
