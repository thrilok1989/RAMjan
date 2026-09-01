"""MIOS V6 — the V6 overall bias, computed the V6 way.

V5 arrives at a bias by arbitrating ~34 engines through the Conflict Engine.
V6 was built because that count is a lie: CVD, Money Flow, Delta and VOB are the
same evidence counted four times, so the V5 tally is loudest exactly where it is
most correlated. Wave 1-4 replaced counting with **families, confirmation,
structure and footprint**. This module is what that produces when you let it
speak on its own.

## Four voters, and why only four

    Stage 53  Evidence families   ×3.0   the de-duplicated institutional vote
    Stage 42  Reaction at level   ×2.5   what ACTUALLY happened, not what is predicted
    Stage 45  HTF alignment       ×2.0   the structure the day sits inside
    Stage 43  Absorption          ×1.5   who is doing it, and passively or aggressively

Stage 42 is weighted second only to the family vote on purpose. Everything else
is inference about what price *should* do; a rejection or a confirmed breakdown
is a thing that *has already occurred*. Executed evidence outranks derived
evidence — that is the tier rule the whole system is built on.

## Four modifiers, and why they are not voters

Stage 47 (transition), 54 (memory), 51 (validity) and 44 (flow shift) never add
a directional vote. They change **how much the vote is worth**:

    47  is this bias strengthening or decaying?     ×0.55 … ×1.10
    54  is the state mature or two minutes old?     ×0.80 … ×1.05
    51  does the gatekeeper accept this side?       caps confidence
    44  did institutional flow just shift?          hard cap — the tape changed

Stage 47's own bias is *derived from Stage 53's families*. Letting it vote would
count the family read twice, quietly, and inflate confidence precisely when the
families are already unanimous. It modifies instead. Stage 54 and 44 return
`Bias.NONE` by design for the same reason.

## This does not replace V5

It is displayed **beside** V5, not instead of it. Nothing here feeds the
Decision Engine. The point of showing both is the divergence: the days they
disagree are the data that decides whether V6 is actually better, and until
there are enough of those days, promoting V6 would be a guess wearing a
roadmap. Observational first — the rule that outranks every other item on the
V6 roadmap.

Pure module: a final read in, a bias out. No IO, no Streamlit, no state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

#: voter → weight. Executed evidence over derived evidence over resting.
WEIGHTS = {
    "families": 3.0,      # Stage 53
    "reaction": 2.5,      # Stage 42
    "htf": 2.0,           # Stage 45
    "absorption": 1.5,    # Stage 43
}

LABELS = {"STRONG_BULL": "STRONG BULLISH", "BULL": "BULLISH",
          "NEUTRAL": "NEUTRAL", "BEAR": "BEARISH",
          "STRONG_BEAR": "STRONG BEARISH", "NONE": "NO READ"}

EMOJI = {"STRONG_BULL": "🟢", "BULL": "🟢", "NEUTRAL": "🟡",
         "BEAR": "🔴", "STRONG_BEAR": "🔴", "NONE": "⚪"}

COLOUR = {"STRONG_BULL": "#00ff88", "BULL": "#17c98b", "NEUTRAL": "#ffd000",
          "BEAR": "#ff6666", "STRONG_BEAR": "#ff4444", "NONE": "#cfd9e6"}

#: Stage 47 state → confidence multiplier. A weakening bias is still the bias;
#: it is just worth less, and a reversing one is worth very little.
_TRANSITION_MULT = {"STRENGTHENING": 1.10, "STABLE": 1.0, "WEAKENING": 0.80,
                    "TRANSITION": 0.70, "REVERSING": 0.55}

#: net-ratio bands → label. Same geometry as Stage 53 so the two never disagree
#: on wording while agreeing on direction.
_BANDS = ((0.60, "STRONG_BULL"), (0.15, "BULL"),
          (-0.15, "NEUTRAL"), (-0.60, "BEAR"))

_BULL = ("STRONG_BULL", "BULL")
_BEAR = ("STRONG_BEAR", "BEAR")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def sign(bias: Any) -> int:
    b = str(getattr(bias, "value", bias) or "").upper()
    if b in _BULL or b == "BULLISH":
        return 1
    if b in _BEAR or b == "BEARISH":
        return -1
    return 0


def _band(ratio: float) -> str:
    if ratio >= 0.60:
        return "STRONG_BULL"
    if ratio > 0.15:
        return "BULL"
    if ratio <= -0.60:
        return "STRONG_BEAR"
    if ratio < -0.15:
        return "BEAR"
    return "NEUTRAL"


# ── the four voters ─────────────────────────────────────────────────────
def _voter_families(fr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    fam = fr.get("families_read") or {}
    dom = fam.get("dominant")
    if not dom or dom == "NEUTRAL":
        return None
    agree = _f(fam.get("agreement_pct")) or 0.0
    return {"key": "families", "label": "Evidence families", "stage": 53,
            "bias": dom, "sign": sign(dom), "confidence": round(agree, 1),
            "detail": f"{LABELS.get(dom, dom)} · {agree:.0f}% agreement "
                      f"({fam.get('severity', '—')} conflict)"}


def _voter_reaction(fr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rc = fr.get("reaction") or {}
    winner = str(rc.get("winner") or "")
    if not winner:
        return None
    sgn = 1 if winner == "Buyers" else -1 if winner == "Sellers" else 0
    if not sgn:
        return None
    conf = _f(rc.get("confidence")) or 0.0
    return {"key": "reaction", "label": "Reaction at level", "stage": 42,
            "bias": "BULL" if sgn > 0 else "BEAR", "sign": sgn,
            "confidence": conf,
            "detail": f"{rc.get('label', rc.get('state'))} — {winner} won "
                      f"({conf:.0f}%)"}


def _voter_htf(fr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    al = ((fr.get("htf") or {}).get("alignment")) or {}
    b = str(al.get("bias") or "").upper()
    if b not in ("BULL", "BEAR"):
        return None
    score = _f(al.get("score")) or 0.0
    return {"key": "htf", "label": "Higher timeframes", "stage": 45,
            "bias": b, "sign": sign(b), "confidence": score,
            "detail": f"{al.get('label', '')} {al.get('stars', '')}"
                      + (f" · {', '.join(al.get('disagree') or [])} disagree"
                         if al.get("disagree") else "")}


def _voter_absorption(fr: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    ab = fr.get("absorption") or {}
    tone = str(ab.get("tone") or "")
    sgn = 1 if tone == "bull" else -1 if tone == "bear" else 0
    if not sgn or ab.get("behaviour") in (None, "NONE"):
        return None
    conf = _f(ab.get("confidence")) or 0.0
    return {"key": "absorption", "label": "Institutional footprint", "stage": 43,
            "bias": "BULL" if sgn > 0 else "BEAR", "sign": sgn,
            "confidence": conf,
            "detail": f"{ab.get('label', '')} ({conf:.0f}%)"}


_VOTERS = (_voter_families, _voter_reaction, _voter_htf, _voter_absorption)


# ── the four modifiers ──────────────────────────────────────────────────
def _modifiers(fr: Dict[str, Any], bias: str) -> List[Dict[str, Any]]:
    """Each returns a multiplier and the reason for it. Never a direction."""
    out: List[Dict[str, Any]] = []

    # Stage 47 — is the leading bias strengthening or decaying?
    tr = fr.get("transition") or {}
    state = str(tr.get("state") or "").upper()
    if state in _TRANSITION_MULT:
        m = _TRANSITION_MULT[state]
        # a reversal warning only bites when it points AGAINST the read
        if state in ("WEAKENING", "REVERSING", "TRANSITION") and \
                sign(tr.get("bias")) and sign(tr.get("bias")) != sign(bias):
            m = min(m, 0.6)
        if m != 1.0:
            out.append({"key": "transition", "stage": 47, "mult": m,
                        "reason": f"{tr.get('label', state)}"})

    # Stage 54 — how established is the state that produced this read?
    mem = fr.get("memory_read") or {}
    if mem.get("state"):
        if mem.get("state_fresh"):
            out.append({"key": "memory", "stage": 54, "mult": 0.85,
                        "reason": f"state only "
                                  f"{_f(mem.get('state_duration_min')) or 0:.0f} min old"})
        elif mem.get("state_mature"):
            out.append({"key": "memory", "stage": 54, "mult": 1.05,
                        "reason": f"state held "
                                  f"{_f(mem.get('state_duration_min')) or 0:.0f} min"})
        risk = _f(mem.get("state_transition_risk")) or 0.0
        if risk >= 60:
            out.append({"key": "memory_risk", "stage": 54, "mult": 0.80,
                        "reason": f"transition risk {risk:.0f}%"})
    return out


def _gates(fr: Dict[str, Any], bias: str, conf: float) -> Dict[str, Any]:
    """Stage 51 and Stage 44 do not scale confidence — they cap it. A gate that
    merely discounted a read would let a strong-enough score walk through a
    veto, which is exactly what those two engines exist to prevent."""
    cap, notes, frozen = 100.0, [], False

    # Stage 44 — the tape this read was computed on no longer exists
    fs = fr.get("flow_shift") or {}
    if fs.get("freeze_entries"):
        cap, frozen = 25.0, True
        notes.append(f"flow shift {_f(fs.get('score')) or 0:.0f}% — read is stale")
    elif fr.get("stability") == "RECOVERY":
        cap = min(cap, 60.0)
        notes.append("tape still settling after a shift")

    # Stage 51 — the gatekeeper's verdict on the side this bias implies
    side = "CALL" if sign(bias) > 0 else "PUT" if sign(bias) < 0 else None
    vb = fr.get("validity_both") or {}
    v = (vb.get(side) if side else None) or {}
    if v.get("verdict") and side:
        pct = _f(v.get("pct"))
        if not v.get("valid"):
            cap = min(cap, max(35.0, pct if pct is not None else 35.0))
            notes.append(f"validity {v.get('verdict')} for {side}"
                         + (f" ({pct:.0f}%)" if pct is not None else ""))
        elif pct is not None:
            cap = min(cap, pct + 15.0)

    return {"cap": cap, "notes": notes, "frozen": frozen,
            "capped": conf > cap}


# ── the read ────────────────────────────────────────────────────────────
def compute(final_read: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The MIOS V6 overall bias.

    Returns `{bias, label, emoji, colour, confidence, agreement_pct, voters,
    modifiers, gates, sentence, v5_bias, agrees, divergence}` — always a dict,
    never raises, and honest about having no read when the V6 engines have not
    warmed up.
    """
    fr = dict(final_read or {})
    voters = [v for v in (fn(fr) for fn in _VOTERS) if v]

    if not voters:
        return _empty(fr, "V6 engines still warming up — no independent read yet.")

    bull_w = bear_w = total_w = 0.0
    for v in voters:
        w = WEIGHTS[v["key"]] * max(0.25, (v["confidence"] or 0.0) / 100.0)
        v["weight"] = round(w, 2)
        total_w += w
        if v["sign"] > 0:
            bull_w += w
        else:
            bear_w += w

    if total_w <= 0:
        return _empty(fr, "V6 voters present but carry no confidence yet.")

    net = bull_w - bear_w
    ratio = net / total_w
    bias = _band(ratio)
    opposing = (bear_w if net >= 0 else bull_w) / total_w
    agreement = round((1 - opposing) * 100)

    # base confidence: how one-sided the vote is, tempered by how much evidence
    # actually turned up. Three voters agreeing is not four voters agreeing.
    coverage = len(voters) / float(len(WEIGHTS))
    conf = abs(ratio) * 100.0 * (0.6 + 0.4 * coverage)

    mods = _modifiers(fr, bias)
    for m in mods:
        conf *= m["mult"]

    gates = _gates(fr, bias, conf)
    conf = min(conf, gates["cap"])
    conf = int(max(0, min(97, round(conf))))

    if bias == "NEUTRAL":
        conf = min(conf, 40)

    v5 = fr.get("preferred_bias")
    agrees = (sign(v5) == sign(bias)) if v5 else None

    return {
        "bias": bias, "label": LABELS[bias], "emoji": EMOJI[bias],
        "colour": COLOUR[bias], "confidence": conf,
        "agreement_pct": agreement, "coverage": len(voters),
        "coverage_of": len(WEIGHTS),
        "bull_weight": round(bull_w, 2), "bear_weight": round(bear_w, 2),
        "voters": voters, "modifiers": mods, "gates": gates,
        "frozen": gates["frozen"],
        "v5_bias": v5, "v5_confidence": fr.get("confidence_tempered",
                                               fr.get("confidence")),
        "agrees": agrees,
        "divergence": _divergence(v5, bias, agrees),
        "sentence": _sentence(bias, conf, voters, mods, gates, agreement),
        # binding: this is displayed, logged and compared. It is not consumed.
        "advisory_only": True,
    }


def _empty(fr: Dict[str, Any], why: str) -> Dict[str, Any]:
    v5 = fr.get("preferred_bias")
    return {"bias": "NONE", "label": LABELS["NONE"], "emoji": EMOJI["NONE"],
            "colour": COLOUR["NONE"], "confidence": 0, "agreement_pct": 0,
            "coverage": 0, "coverage_of": len(WEIGHTS), "voters": [],
            "modifiers": [], "gates": {"cap": 100.0, "notes": [], "frozen": False,
                                       "capped": False},
            "frozen": False, "v5_bias": v5,
            "v5_confidence": fr.get("confidence_tempered", fr.get("confidence")),
            "agrees": None, "divergence": None, "sentence": why,
            "advisory_only": True}


def _divergence(v5: Any, v6: str, agrees: Optional[bool]) -> Optional[str]:
    """The sentence that makes a disagreement useful instead of confusing."""
    if agrees is not False:
        return None
    s5, s6 = sign(v5), sign(v6)
    if s5 and not s6:
        return ("V6 sees no clean edge where V5 does — the V5 read is likely "
                "correlated evidence counted more than once.")
    if s6 and not s5:
        return ("V6 finds a directional read V5 calls flat — usually the "
                "reaction at the level, which V5 does not weight.")
    return ("V5 and V6 point OPPOSITE ways — treat this as a stand-aside, not "
            "as a choice between two opinions.")


def _sentence(bias: str, conf: int, voters: List[Dict[str, Any]],
              mods: List[Dict[str, Any]], gates: Dict[str, Any],
              agreement: int) -> str:
    if gates.get("frozen"):
        return ("Institutional flow just shifted — the V6 read is frozen until "
                "the tape settles.")
    names = ", ".join(v["label"].lower() for v in voters)
    head = (f"{LABELS[bias]} at {conf}% — {len(voters)} of {len(WEIGHTS)} V6 "
            f"voters ({names}), {agreement}% agreement.")
    cut = [m["reason"] for m in mods if m["mult"] < 1.0]
    if cut:
        head += " Discounted for " + "; ".join(cut) + "."
    if gates.get("notes"):
        head += " Capped: " + "; ".join(gates["notes"]) + "."
    return head


# ── the side-by-side comparison the card renders ────────────────────────
def compare(final_read: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """V5 and V6 as one payload — the whole point being that both are shown,
    including on the days they disagree."""
    v6 = compute(final_read)
    fr = dict(final_read or {})
    v5b = fr.get("preferred_bias") or "NONE"
    v5c = fr.get("confidence_tempered", fr.get("confidence"))
    v5k = str(v5b).upper().replace(" ", "_")
    if v5k not in LABELS:
        v5k = "STRONG_BULL" if "STRONG" in v5k and "BULL" in v5k else \
              "STRONG_BEAR" if "STRONG" in v5k and "BEAR" in v5k else \
              "BULL" if "BULL" in v5k else "BEAR" if "BEAR" in v5k else \
              "NEUTRAL" if v5b else "NONE"
    return {
        "v5": {"bias": v5k, "label": LABELS[v5k], "emoji": EMOJI[v5k],
               "colour": COLOUR[v5k],
               "confidence": int(round(_f(v5c) or 0))},
        "v6": {"bias": v6["bias"], "label": v6["label"], "emoji": v6["emoji"],
               "colour": v6["colour"], "confidence": v6["confidence"]},
        "agrees": v6["agrees"], "divergence": v6["divergence"],
        "sentence": v6["sentence"], "read": v6,
    }
