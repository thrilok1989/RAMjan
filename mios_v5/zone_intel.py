"""MIOS V5 — Zone Intelligence (Phase 1: perfect the S/R before anything else).

Everything downstream — entries, traps, targets — is only as good as the S/R it
stands on. So a level is not a number: it is an object that knows *where it came
from*, *how strong it is*, *where it is in its life*, *who is defending it*, *who
is winning the fight there*, *whether price is accepting or rejecting it*, *how
likely it is to break or trap*, and *whether higher timeframes agree*.

Ten reads, one card:

    1 Origin      — which source families formed it (POC/HVN/OB/round/PDH…)
    2 Strength    — confluence + touches + freshness + OI/gamma/liquidity
    3 Lifecycle   — Created→Untested→Holding→Building→Under Attack→Breaking→
                    Broken→Retest→Recovered→Retired
    4 Health      — Spot · Options · Dealers · Institutions · Liquidity → %
    5 Battle      — buyer vs seller strength, winner, confidence
    6 Acceptance  — Accepted / Rejected / Trap Active
    7 Probability — break % · rejection % · trap %
    8 HTF         — which higher timeframes confirm the level
    9 Explanation — the short "why is this strong" bullets
   10 Card        — the assembled display object

Every function here is PURE (no session, no I/O, no pandas) so the whole layer is
testable and reusable by the app, the MIOS dashboard and the Telegram signal.
Observation-first: this describes the zone, it never emits a buy/sell.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# ── source families → how much "origin authority" each carries ──────────
# A level confirmed by structurally different families (a volume POC *and* an
# order block *and* a round number) is far stronger than one confirmed three
# times by the same family. Weights are per-family; the score saturates.
_SOURCE_WEIGHT = {
    "poc": 1.0, "vah": 0.85, "val": 0.85, "hvn": 0.9, "lvn": 0.5,
    "ob": 0.95, "order block": 0.95, "vob": 0.95,
    "oi": 0.9, "oi-ce": 0.9, "oi-pe": 0.9, "gamma": 0.85, "gex": 0.85,
    "liquidity": 0.7, "pool": 0.7, "round": 0.6,
    "pdh": 0.8, "pdl": 0.8, "prev": 0.75, "swing": 0.8, "vwap": 0.7,
    "mf": 0.7, "vpfr": 0.8, "hvp": 0.7,
}

_LIFECYCLE_ORDER = ["created", "untested", "holding", "building", "under-attack",
                    "breaking", "broken", "retest", "recovered", "retired"]

_LIFECYCLE_LABEL = {
    "created": "🆕 Created", "untested": "⚪ Untested", "holding": "🟦 Holding",
    "building": "🟢 Building", "under-attack": "⚔️ Under Attack",
    "breaking": "🟠 Breaking", "broken": "❌ Broken", "retest": "🔁 Retest",
    "recovered": "🟢 Recovered", "retired": "🗑 Retired",
}


def stars(pct: Optional[float]) -> str:
    """0-100 → ★★★★☆ (always 5 glyphs, minimum one star for a real level)."""
    try:
        p = max(0.0, min(100.0, float(pct)))
    except (TypeError, ValueError):
        return "☆☆☆☆☆"
    n = max(1, min(5, int(round(p / 20.0))))
    return "★" * n + "☆" * (5 - n)


def _family(tag: str) -> str:
    """Normalize a raw source tag ('MF-POC', 'OI-CE', 'W-VAH') to a family key."""
    t = str(tag or "").strip().lower()
    for key in ("order block", "poc", "vah", "val", "hvn", "lvn", "vob", "ob",
                "oi-ce", "oi-pe", "oi", "gamma", "gex", "liquidity", "pool",
                "round", "pdh", "pdl", "prev", "swing", "vwap", "vpfr", "hvp", "mf"):
        if key in t:
            return key
    return t or "other"


# ── 1 · ORIGIN ──────────────────────────────────────────────────────────
def origin(sources: Optional[Sequence[str]]) -> Dict[str, Any]:
    """Where the level came from. Distinct FAMILIES matter more than raw count —
    six tags from one family is one piece of evidence wearing six hats."""
    tags = [str(s) for s in (sources or []) if s]
    fams: Dict[str, str] = {}
    for t in tags:
        fams.setdefault(_family(t), t)
    weight = sum(_SOURCE_WEIGHT.get(f, 0.55) for f in fams)
    # ~4 strong distinct families ≈ full marks
    score = max(0.0, min(100.0, weight / 3.6 * 100.0))
    return {"sources": tags, "families": sorted(fams), "family_count": len(fams),
            "score": round(score), "stars": stars(score)}


# ── 2 · STRENGTH ────────────────────────────────────────────────────────
def strength(origin_score: Optional[float], defense: Optional[float] = None,
             touches: int = 0, freshness: Optional[float] = None,
             concentration: Optional[float] = None) -> Dict[str, Any]:
    """Blend how the level was formed with how it has behaved and how much
    positioning sits on it.

    origin_score  — from origin() (structural pedigree)
    defense       — options-defense strength % (OI/confluence) if known
    touches       — times price has tested it (a level earns respect by holding,
                    but each extra test also wears it down: 2-3 is the sweet spot)
    freshness     — 0-100, 100 = untouched/new, decays as it ages
    concentration — OI / gamma / liquidity concentration % if known
    """
    o = float(origin_score or 0)
    parts: List[Tuple[float, float]] = [(o, 0.40)]
    if defense is not None:
        parts.append((max(0.0, min(100.0, float(defense))), 0.30))
    if concentration is not None:
        parts.append((max(0.0, min(100.0, float(concentration))), 0.20))
    if freshness is not None:
        parts.append((max(0.0, min(100.0, float(freshness))), 0.10))
    total_w = sum(w for _, w in parts)
    base = sum(v * w for v, w in parts) / total_w if total_w else o

    # touch curve: 0 = unproven, 2-3 = proven, >4 = worn out
    t = max(0, int(touches or 0))
    touch_adj = {0: -4.0, 1: +2.0, 2: +6.0, 3: +4.0, 4: 0.0}.get(t, -3.0 * (t - 4))
    score = max(0.0, min(100.0, base + touch_adj))
    return {"score": round(score), "stars": stars(score), "touches": t,
            "touch_note": ("unproven" if t == 0 else "proven" if 2 <= t <= 3
                           else "tested once" if t == 1 else "worn")}


# ── 3 · LIFECYCLE ───────────────────────────────────────────────────────
def advance(prev: Optional[str], *, at_zone: bool, broken: bool,
            reclaimed: bool = False, touches: int = 0,
            building: int = 0, fading: int = 0,
            age_cycles: int = 0, far_away: bool = False) -> str:
    """The zone's life as a state machine. `building` / `fading` are counts of
    health categories pulling each way; `broken` means price closed through it.

    Created → Untested → Holding → Building → Under Attack → Breaking → Broken
              → Retest → Recovered → Retired
    """
    p = (prev or "created") if prev in _LIFECYCLE_ORDER else "created"

    # a broken level's own arc: broken → retest → recovered (or retired)
    if p in ("broken", "retest", "recovered"):
        if reclaimed:
            return "recovered"
        if at_zone:
            return "retest"
        if far_away or age_cycles > 60:
            return "retired"
        return "broken"

    if broken:
        return "broken"
    if far_away and age_cycles > 60 and touches == 0:
        return "retired"

    if at_zone:
        if fading >= 3 and building == 0:
            return "breaking"
        if building and fading:
            return "under-attack"
        if fading >= 2:
            return "under-attack"
        if building >= 2:
            return "building"
        return "holding"

    # away from the level
    if touches == 0:
        return "untested" if p in ("created", "untested") else p
    if building >= 2 and not fading:
        return "building"
    if fading >= 2 and not building:
        return "under-attack"
    return "holding"


def lifecycle_label(state: Optional[str]) -> str:
    return _LIFECYCLE_LABEL.get(str(state or ""), "⚪ Unknown")


def is_dangerous(state: Optional[str]) -> bool:
    """States where a trade *off* this zone should not be taken at face value."""
    return str(state or "") in ("under-attack", "breaking", "broken", "retired")


# ── 4 · HEALTH ──────────────────────────────────────────────────────────
_HEALTH_KEYS = ("spot", "options", "dealers", "institutions", "liquidity")


def health(cats: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """Five defender groups, each building / fading / neutral → one %.
    A zone is only trustworthy when the groups AGREE — a 50% health with two
    groups fighting is a warning, not a mild reading."""
    c = {k: str((cats or {}).get(k) or "neutral") for k in _HEALTH_KEYS}
    nb = sum(1 for v in c.values() if v == "building")
    nf = sum(1 for v in c.values() if v == "fading")
    nn = len(_HEALTH_KEYS) - nb - nf
    pct = (nb + 0.5 * nn) / len(_HEALTH_KEYS) * 100.0
    return {"categories": c, "building": nb, "fading": nf, "neutral": nn,
            "pct": round(pct), "aligned": bool(nb and not nf) or bool(nf and not nb),
            "conflicted": bool(nb and nf)}


# ── 5 · BATTLE ──────────────────────────────────────────────────────────
def battle(side: str, zone_strength: Optional[float],
           dir_score: float = 0.0, health_pct: Optional[float] = None) -> Dict[str, Any]:
    """Who is winning AT the level. `dir_score` ∈ [-1, +1] is the blended
    directional lean (＋ = bulls). At a SUPPORT the defenders are buyers; at a
    RESISTANCE they are sellers — so the same inputs flip meaning by side."""
    s = float(zone_strength if zone_strength is not None else 50.0)
    h = float(health_pct) if health_pct is not None else 50.0
    defenders = 50.0 + 0.35 * (s - 50.0) + 0.25 * (h - 50.0)
    lean = 35.0 * max(-1.0, min(1.0, float(dir_score or 0.0)))
    if str(side).upper() == "SUPPORT":
        buyers = defenders + lean
    else:
        buyers = 100.0 - defenders + lean
    buyers = max(5.0, min(95.0, buyers))
    sellers = 100.0 - buyers
    margin = abs(buyers - sellers)
    if margin < 8:
        winner, conf = "Contested", round(50 + margin)
    elif buyers > sellers:
        winner, conf = "Buyers", round(min(95, 50 + margin))
    else:
        winner, conf = "Sellers", round(min(95, 50 + margin))
    return {"buyer": round(buyers), "seller": round(sellers), "winner": winner,
            "confidence": conf, "war": margin < 20,
            "label": "⚔️ WAR ZONE" if margin < 20 else f"🏳️ {winner} in control"}


# ── 6 · ACCEPTANCE / REJECTION / TRAP ───────────────────────────────────
def acceptance(side: str, spot: Optional[float], price: Optional[float],
               pierced: bool = False, closed_beyond: bool = False,
               health_pct: Optional[float] = None,
               tol_pct: float = 0.12) -> Dict[str, Any]:
    """What price is DOING at the level right now.

    Accepted    — price closed beyond and the defenders are not fighting back
    Rejected    — price probed beyond and came back (the level did its job)
    Trap Active — price is beyond the level but health says the move is not
                  supported: the classic liquidity grab before the snap-back
    """
    try:
        s, p = float(spot), float(price)
    except (TypeError, ValueError):
        return {"state": "unknown", "label": "—", "beyond": False}
    beyond = (s < p * (1 - tol_pct / 100.0)) if str(side).upper() == "SUPPORT" \
        else (s > p * (1 + tol_pct / 100.0))
    h = float(health_pct) if health_pct is not None else 50.0
    # defenders still strong while price sits beyond the level = trap
    defenders_strong = h >= 55.0
    if closed_beyond and not defenders_strong:
        state, label = "accepted", "✅ Accepted (level given up)"
    elif beyond and defenders_strong:
        state, label = "trap", "🪤 Trap Active (grab, defenders holding)"
    elif pierced and not beyond:
        state, label = "rejected", "🛡 Rejected (probed & pushed back)"
    elif beyond:
        state, label = "accepted", "✅ Accepted (trading beyond)"
    else:
        state, label = "defended", "🛡 Defended (holding)"
    return {"state": state, "label": label, "beyond": beyond}


# ── 7 · PROBABILITY ─────────────────────────────────────────────────────
def probabilities(side: str, zone_strength: Optional[float],
                  health_pct: Optional[float], dir_score: float = 0.0,
                  lifecycle: Optional[str] = None,
                  acceptance_state: Optional[str] = None) -> Dict[str, int]:
    """Break · Rejection · Trap. Break and rejection are complements; TRAP is an
    independent read — how likely a move through this level is a liquidity grab
    rather than a real break (high when price pushes through while the defending
    groups are still strong, and when the level is fresh/strong)."""
    s = float(zone_strength if zone_strength is not None else 50.0)
    h = float(health_pct) if health_pct is not None else 50.0
    d = max(-1.0, min(1.0, float(dir_score or 0.0)))
    # pressure pushing THROUGH the level (up through resistance, down through support)
    through = d if str(side).upper() == "RESISTANCE" else -d
    brk = 50.0 - 0.32 * (s - 50.0) - 0.22 * (h - 50.0) + 30.0 * through
    life_adj = {"building": -8.0, "holding": -4.0, "recovered": -4.0,
                "under-attack": +8.0, "breaking": +18.0, "broken": +22.0,
                "retest": +4.0, "untested": +2.0}.get(str(lifecycle or ""), 0.0)
    brk = max(5.0, min(95.0, brk + life_adj))
    rej = 100.0 - brk

    trap = 30.0 + 0.30 * (h - 50.0) + 0.20 * (s - 50.0)
    if acceptance_state == "trap":
        trap += 25.0
    elif acceptance_state == "accepted":
        trap -= 15.0
    elif acceptance_state == "rejected":
        trap += 5.0
    if str(lifecycle or "") in ("building", "recovered"):
        trap += 6.0
    trap = max(5.0, min(95.0, trap))
    return {"break": round(brk), "rejection": round(rej), "trap": round(trap)}


# ── 8 · HIGHER-TIMEFRAME ALIGNMENT ──────────────────────────────────────
def htf_alignment(price: Optional[float], levels: Optional[Dict[str, Any]],
                  tol_pct: float = 0.15) -> Dict[str, Any]:
    """Which higher timeframes put a level at the same price. `levels` maps a
    label ('1H POC', 'Daily HVN', …) → price. Confluence across timeframes is
    what separates a real wall from an intraday artifact."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return {"matches": [], "count": 0, "score": 0, "stars": stars(0)}
    tol = max(8.0, p * tol_pct / 100.0)
    matches = []
    for label, lv in (levels or {}).items():
        try:
            if lv and abs(float(lv) - p) <= tol:
                matches.append(str(label))
        except (TypeError, ValueError):
            continue
    score = max(0.0, min(100.0, len(matches) / 4.0 * 100.0))
    return {"matches": matches, "count": len(matches),
            "score": round(score), "stars": stars(score)}


# ── 9 · EXPLANATION ─────────────────────────────────────────────────────
def explain(side: str, org: Dict[str, Any], hl: Dict[str, Any],
            btl: Dict[str, Any], acc: Dict[str, Any],
            probs: Dict[str, int], invalidation: Optional[float] = None,
            max_bullets: int = 4) -> Dict[str, Any]:
    """The short "why is this strong / what do I expect" read. Bullets, not prose
    — a trader glancing at the card has two seconds."""
    bullets: List[str] = []
    pretty = {"poc": "Volume POC", "hvn": "High-Volume Node", "ob": "Order Block",
              "order block": "Order Block", "vob": "Order Block",
              "oi": "Heavy OI", "oi-ce": "Heavy Call OI", "oi-pe": "Heavy Put OI",
              "gamma": "Dealer Gamma Wall", "gex": "Dealer Gamma Wall",
              "round": "Round Number", "pdh": "Prev Day High", "pdl": "Prev Day Low",
              "swing": "Swing Level", "vwap": "VWAP", "liquidity": "Liquidity Pool",
              "pool": "Liquidity Pool", "vah": "Value-Area High",
              "val": "Value-Area Low", "vpfr": "Multi-TF Value", "mf": "Money-Flow Node"}
    for f in (org or {}).get("families", [])[:max_bullets]:
        bullets.append(pretty.get(f, str(f).title()))
    cats = (hl or {}).get("categories") or {}
    for k, lbl in (("dealers", "Dealer defence"), ("institutions", "Institutional defence")):
        if cats.get(k) == "building" and len(bullets) < max_bullets + 1:
            bullets.append(lbl)

    is_sup = str(side).upper() == "SUPPORT"
    if (hl or {}).get("conflicted"):
        expect = "Groups disagree — wait for one side to win"
    elif (btl or {}).get("winner") == "Buyers":
        expect = "Buyer defence" if is_sup else "Buyers pressing for a break"
    elif (btl or {}).get("winner") == "Sellers":
        expect = "Seller defence" if not is_sup else "Sellers pressing for a break"
    else:
        expect = "Contested — no edge yet"
    if (acc or {}).get("state") == "trap":
        expect = "Liquidity grab in progress — expect a snap-back"
    return {"why": bullets, "expect": expect,
            "invalidation": invalidation,
            "headline": f"{expect} · break {probs.get('break', '—')}% · "
                        f"reject {probs.get('rejection', '—')}% · "
                        f"trap {probs.get('trap', '—')}%"}


# ── 10 · THE CARD ───────────────────────────────────────────────────────
def build_zone_card(side: str, zone: Optional[Dict[str, Any]], spot: Optional[float],
                    *, dir_score: float = 0.0, htf_levels: Optional[Dict[str, Any]] = None,
                    touches: int = 0, freshness: Optional[float] = None,
                    concentration: Optional[float] = None,
                    prev_lifecycle: Optional[str] = None,
                    age_cycles: int = 0, pierced: bool = False,
                    closed_beyond: bool = False,
                    reclaimed: bool = False) -> Optional[Dict[str, Any]]:
    """Assemble the complete Zone Intelligence object for ONE level — the ten
    reads in one dict, ready for any display (MIOS dashboard, Trade Card,
    Telegram). Pure: give it the zone dict + context, get the card back."""
    if not zone or zone.get("price") is None:
        return None
    price = float(zone["price"])
    org = origin(zone.get("sources"))
    cats = dict(zone.get("zone_health") or {})
    cats.setdefault("liquidity", "neutral")
    hl = health(cats)
    st_ = strength(org["score"], defense=zone.get("strength"), touches=touches,
                   freshness=freshness, concentration=concentration)
    at_zone = False
    if spot:
        at_zone = abs(float(spot) - price) / price * 100.0 <= 0.35
    broken = str(zone.get("status") or "") == "broken"
    far = bool(spot) and abs(float(spot) - price) / price * 100.0 > 1.5
    life = advance(prev_lifecycle or zone.get("lifecycle"), at_zone=at_zone,
                   broken=broken, reclaimed=reclaimed, touches=touches,
                   building=hl["building"], fading=hl["fading"],
                   age_cycles=age_cycles, far_away=far)
    btl = battle(side, st_["score"], dir_score=dir_score, health_pct=hl["pct"])
    acc = acceptance(side, spot, price, pierced=pierced,
                     closed_beyond=closed_beyond, health_pct=hl["pct"])
    probs = probabilities(side, st_["score"], hl["pct"], dir_score=dir_score,
                          lifecycle=life, acceptance_state=acc["state"])
    htf = htf_alignment(price, htf_levels)
    inval = round(price * (0.997 if str(side).upper() == "SUPPORT" else 1.003))
    exp = explain(side, org, hl, btl, acc, probs, invalidation=inval)
    return {
        "side": str(side).upper(), "price": price,
        "origin": org, "strength": st_, "lifecycle": life,
        "lifecycle_label": lifecycle_label(life), "dangerous": is_dangerous(life),
        "health": hl, "battle": btl, "acceptance": acc,
        "probabilities": probs, "htf": htf, "explain": exp,
        "invalidation": inval, "at_zone": at_zone,
    }
