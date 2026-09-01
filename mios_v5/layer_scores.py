"""MIOS V5 — 7-Layer Scorecard + Trade-Quality grade (additive synthesis).

This is a **read-only** synthesis layer. It does not compute any new market
signal and it never emits BUY/SELL — it simply reads the biases/confidences the
existing engines already produced and rolls them up into:

  • a 0–100 score for each of the 7 perception layers
  • a weighted composite score (priority: structure > positioning > order flow
    > liquidity > options > environment > psychology — patterns/psychology are
    confirmation, so they carry the least weight)
  • a directional lean (BULL / BEAR / NEUTRAL) and an alignment %
  • a **read-quality grade** A+ / A / B / C — how good/clean the current read
    is, NOT a trade instruction. The trader still decides.

Honest-neutral rule is respected: a layer whose engines could not compute is
marked N/A and excluded from the composite (weights renormalise) — never faked.
Pure (no Streamlit) so it can be unit-tested and reused anywhere.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import Bias, MarketState, Status

# bias → signed lean
_LEAN = {
    Bias.STRONG_BULL: 2, Bias.BULL: 1, Bias.NEUTRAL: 0, Bias.SIDEWAYS: 0,
    Bias.BEAR: -1, Bias.STRONG_BEAR: -2, Bias.NONE: 0,
}

# Each layer maps to the engines that already produce its read. Weight follows
# the user's priority ladder (structure/positioning/flow first, patterns last).
_LAYERS = [
    ("environment", "🌍 Environment", 0.08,
     ["stage19_global", "stage20_macro", "stage21_news", "stage05_regime"]),
    ("structure", "🏗 Structure", 0.22,
     ["stage35_reaction_zone", "stage03_memory"]),
    ("positioning", "🏦 Positioning", 0.20,
     ["stage13_institutional"]),
    ("orderflow", "🌊 Order Flow", 0.18,
     ["stage14_orderflow"]),
    ("options", "🎛 Options / Dealer", 0.12,
     ["stage12_options", "stage11_dealer"]),
    ("liquidity", "💧 Liquidity", 0.15,
     ["stage25_intent", "stage35_reaction_zone"]),
    ("psychology", "🧠 Psychology", 0.05,
     ["stage05_regime", "stage29_evolution"]),
]


def _score_layer(state: MarketState, engine_names: List[str]) -> Dict[str, Any]:
    """Roll a layer's contributing engines into one score + lean.

    score  = confidence-weighted average over AVAILABLE engines (DEGRADED
             results are discounted ×0.6). N/A when nothing computed.
    lean   = signed direction (sum of bias×confidence over available engines).
    """
    confs: List[float] = []
    lean_sum = 0.0
    used: List[str] = []
    for name in engine_names:
        r = state.get(name)
        if r is None or r.status not in (Status.OK, Status.DEGRADED):
            continue
        disc = 0.6 if r.status == Status.DEGRADED else 1.0
        conf = float(r.confidence) * disc
        confs.append(conf)
        lean_sum += _LEAN.get(r.bias, 0) * max(conf, 1.0)
        used.append(name)
    if not confs:
        return {"score": None, "lean": "N/A", "sign": 0, "status": "N/A",
                "engines": []}
    score = round(sum(confs) / len(confs))
    sign = 1 if lean_sum > 0 else (-1 if lean_sum < 0 else 0)
    lean = "BULL" if sign > 0 else ("BEAR" if sign < 0 else "NEUTRAL")
    return {"score": score, "lean": lean, "sign": sign, "status": "OK",
            "engines": used}


def build_layer_scores(state: MarketState,
                       health_score: Optional[float] = None) -> Dict[str, Any]:
    """Build the 7-layer scorecard + read-quality grade from the pipeline.

    `health_score` (0–100, optional) tempers the grade — a degraded pipeline
    can't earn an A+.
    """
    layers: List[Dict[str, Any]] = []
    for key, label, weight, engines in _LAYERS:
        s = _score_layer(state, engines)
        layers.append({"key": key, "label": label, "weight": weight, **s})

    # composite = weighted mean over AVAILABLE layers (renormalise weights)
    avail = [ly for ly in layers if ly["score"] is not None]
    wsum = sum(ly["weight"] for ly in avail)
    composite = 0.0
    dir_sum = 0.0          # weighted directional lean (signed)
    agree_w = 0.0          # weight of layers agreeing with the net direction
    dir_w = 0.0            # weight of layers that HAVE a direction
    if wsum > 0:
        for ly in avail:
            w = ly["weight"] / wsum
            composite += w * ly["score"]
            dir_sum += w * ly["sign"] * ly["score"]
            if ly["sign"] != 0:
                dir_w += w
    net_sign = 1 if dir_sum > 0 else (-1 if dir_sum < 0 else 0)
    direction = "BULL" if net_sign > 0 else ("BEAR" if net_sign < 0 else "NEUTRAL")
    if wsum > 0 and dir_w > 0:
        for ly in avail:
            if ly["sign"] == net_sign and ly["sign"] != 0:
                agree_w += ly["weight"] / wsum
        alignment = round(100 * agree_w / dir_w)
    else:
        alignment = 0
    composite = round(composite)

    # ── read-quality grade (NOT a buy/sell call) ──────────────────────
    n_avail = len(avail)
    notes: List[str] = []
    if composite >= 72 and alignment >= 80:
        grade = "A+"
    elif composite >= 62 and alignment >= 68:
        grade = "A"
    elif composite >= 52 and alignment >= 55:
        grade = "B"
    else:
        grade = "C"
    # temper: too few layers, weak health, or no clear direction can't be top
    if n_avail < 4 and grade in ("A+", "A"):
        grade = "B"
        notes.append(f"only {n_avail}/7 layers available — capped at B")
    if health_score is not None and float(health_score) < 60 and grade == "A+":
        grade = "A"
        notes.append(f"pipeline health {float(health_score):.0f}% — capped at A")
    if direction == "NEUTRAL" and grade in ("A+", "A"):
        grade = "B"
        notes.append("no clear directional agreement — capped at B")

    return {
        "layers": layers,
        "composite": composite,
        "alignment": alignment,
        "direction": direction,
        "grade": grade,
        "available": n_avail,
        "total_layers": len(layers),
        "notes": notes,
        "disclaimer": "read-quality grade — decision support, NOT a buy/sell order",
    }


def leans_of(ls: Dict[str, Any]) -> Dict[str, str]:
    """{layer_key: lean} snapshot — logged at signal time for shadow learning."""
    return {ly["key"]: ly["lean"] for ly in ls.get("layers", [])}


def layer_scores_line(ls: Dict[str, Any]) -> str:
    """One-line plain-text summary (for captions / briefing)."""
    return (f"Trade-Quality {ls['grade']} · {ls['direction']} · composite "
            f"{ls['composite']}/100 · alignment {ls['alignment']}% "
            f"({ls['available']}/{ls['total_layers']} layers)")
