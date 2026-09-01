"""MIOS Stage 71 — the Trade Opportunity Matrix.

**An orchestrator, not an engine.** It computes no market fact. It reads the
reads that already exist, sorts them into the five horizons the ownership
registry assigns, and ranks the result. Not registered in `ALL_ENGINES`, no
mutators, `advisory_only` on every output — the same standing as Stage 70.

## The question it answers

47 engines answer *what is happening*. The Decision Engine answers *act or
wait*. Neither answers the question a trader actually opens the screen with:

> **Where is the best opportunity right now, and over what hold time?**

## Why the score is a Wilson lower bound

Horizons own very different numbers of producers — scalp 22, swing 5. Raw
agreement makes those look comparable when they are not: 4/5 and 18/22 are
both "about 80%", and only one of them is evidence.

    n=22   18/22 = 81.8%  ->  score 61.5
    n= 5    4/5  = 80.0%  ->  score 37.6

So the ranking uses `wilson(...).low` — the conservative end of the interval —
multiplied by coverage. A thin horizon must be *very* one-sided to outrank a
broad one, which is the honest ordering. This reuses Stage 56's own rule that
small samples are labelled rather than hidden, and its `wilson()` helper.

Two terms were deliberately left out. An earlier draft multiplied by Quality
and Risk Adjustment as well, and neither has a universal producer: Decision
v0's quality is `None` unless a setup is ARMED or CONFIRMED, and risk needs a
stop that positional and swing do not have. Defaulting a missing term to 1.0
is asserting a fact nobody measured — principle 9, the one this architecture
is most militant about. They can be added when a per-horizon source exists.

## Stability is a separate axis, and never a vote

Stages 44, 47 and 54 shape *how much to trust* a row, never *which way it
leans*. That is not a new judgement — `v6_bias.py` reached it first: 44 and 54
return `Bias.NONE` by design, and 47's bias is derived from Stage 53's
families, so letting it vote would count the families twice. Here that tier
gets a name, a display, and a per-horizon veto: a flow shift destroys a scalp
and can be the swing thesis, so it vetoes the fast horizons and leaves the
slow ones alone.

## Swing never returns a side

The option chain is current-expiry intelligence. A CALL/PUT held for weeks
would be backed by positioning that expires before the horizon does. Swing
returns structure, bias and levels, and the `side` key is **absent** rather
than `None` — an absent key cannot be rendered as a recommendation by
accident.

Pure module: reads in, view model out. No IO, no Streamlit, no pandas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .engine_accuracy import wilson
from .horizon_owner import (AGGREGATE, DEGRADED, EXCLUDED, FLOW_SHIFT_DISCOUNT,
                            FLOW_SHIFT_EFFECT, HOLD, HORIZONS, HTF_TIMEFRAME,
                            NATIVE_LABEL, NO_OPTION_SIDE, OWNED, Horizon,
                            owners_of)

#: bias strings that count as a directional vote
_BULL = ("BULL", "STRONG_BULL")
_BEAR = ("BEAR", "STRONG_BEAR")

#: engine ids whose read is shown beside the matrix but never counted
_REFERENCE_ORDER = ("stage27_conflict", "stage53_evidence", "v6_bias",
                    "stage25_intent", "stage35_reaction_zone")

#: Stage 47 state → how much it costs a horizon's stability, and the words
_TRANSITION_TONE = {
    "STRENGTHENING": (1.00, "strengthening"), "STABLE": (1.00, "stable"),
    "WEAKENING": (0.80, "weakening"), "TRANSITION": (0.70, "in transition"),
    "REVERSING": (0.55, "reversing"),
}

_STABILITY_BANDS = ((70.0, "High", "🟢"), (45.0, "Medium", "🟡"))


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _sign(bias: Any) -> int:
    b = str(bias or "").upper()
    return 1 if b in _BULL else -1 if b in _BEAR else 0


def _side(sign: int) -> Optional[str]:
    return "CALL" if sign > 0 else "PUT" if sign < 0 else None


# ── gathering the votes ─────────────────────────────────────────────────

def _producer_reads(final_read: Dict[str, Any],
                    native_reads: Optional[Dict[str, Any]]) -> Dict[str, Dict]:
    """Every OWNED producer's current read, keyed by producer id.

    Three sources, one shape. A producer that did not report is simply absent —
    it is never defaulted to NEUTRAL, because "abstained" and "balanced" are
    different facts and only one of them should shrink the evidence base.
    """
    fr = dict(final_read or {})
    out: Dict[str, Dict] = {}

    # 1 · MIOS engines — the uniform map final_read publishes
    eb = fr.get("engine_bias") or {}
    for pid in OWNED:
        node = eb.get(pid)
        if not isinstance(node, dict):
            continue
        if str(node.get("status") or "") in ("DISABLED", "ERROR"):
            continue
        out[pid] = {"bias": node.get("bias"),
                    "confidence": _f(node.get("confidence")) or 0.0,
                    "label": node.get("headline") or pid}

    # 2 · higher-timeframe reads — Stage 45 publishes one per timeframe
    reads = ((fr.get("htf") or {}).get("reads")) or {}
    for pid, tf in HTF_TIMEFRAME.items():
        node = reads.get(tf)
        if not isinstance(node, dict):
            continue
        if str(node.get("status") or "OK") not in ("OK", "DEGRADED"):
            continue
        out[pid] = {"bias": node.get("bias"),
                    "confidence": _f(node.get("confidence")) or 0.0,
                    "label": f"HTF {tf}"}

    # 3 · native vob_minimal signals — handed in as a parameter, never read
    #     out of session_state from here (principle 4)
    for pid, node in (native_reads or {}).items():
        if pid not in OWNED:
            continue
        if isinstance(node, str):
            node = {"bias": node}
        if not isinstance(node, dict) or not node.get("bias"):
            continue
        out[pid] = {"bias": node.get("bias"),
                    "confidence": _f(node.get("confidence")) or 0.0,
                    "label": node.get("label") or NATIVE_LABEL.get(pid, pid)}
    return out


# ── stability ───────────────────────────────────────────────────────────

def stability(final_read: Dict[str, Any]) -> Dict[str, Any]:
    """The non-directional read: how much is this tape worth trusting?

    Explainable by construction — every field names the stage behind it, so
    "Medium" is never a bare adjective. Sourced entirely from Stages 44, 47
    and 54, none of which may vote.
    """
    fr = dict(final_read or {})
    fs = fr.get("flow_shift") or {}
    tr = fr.get("transition") or {}
    mem = fr.get("memory_read") or {}

    score, parts = 100.0, []

    # Stage 44 — did the tape this read was computed on stop existing?
    frozen = bool(fs.get("freeze_entries"))
    stab = str(fr.get("stability") or "").upper()
    if frozen:
        score, flow = 20.0, "shifted"
    elif stab == "RECOVERY":
        score, flow = score * 0.65, "settling"
    elif stab in ("UNSTABLE", "SHOCK"):
        score, flow = score * 0.55, stab.lower()
    else:
        flow = "stable"
    parts.append({"stage": 44, "label": "Flow", "value": flow})

    # Stage 47 — is the read strengthening or decaying under us?
    tstate = str(tr.get("state") or "").upper()
    mult, tword = _TRANSITION_TONE.get(tstate, (1.0, tstate.lower() or "—"))
    score *= mult
    parts.append({"stage": 47, "label": "Bias", "value": tword})

    # Stage 54 — how established is the state that produced it?
    held = _f(mem.get("state_duration_min"))
    risk = _f(mem.get("state_transition_risk")) or 0.0
    if mem.get("state_fresh"):
        score *= 0.85
        mword = "fresh"
    elif mem.get("state_mature"):
        score *= 1.05
        mword = "strong"
    else:
        mword = "forming" if held is None else "held"
    if risk >= 60:
        score *= 0.80
    parts.append({"stage": 54, "label": "Memory", "value": mword})
    if held is not None:
        parts.append({"stage": 54, "label": "State held",
                      "value": f"{held:.0f} min"})
    parts.append({"stage": 54, "label": "Transition risk",
                  "value": f"{risk:.0f}%"})

    score = max(0.0, min(100.0, score))
    band, emoji = "Low", "🔴"
    for cut, name, em in _STABILITY_BANDS:
        if score >= cut:
            band, emoji = name, em
            break
    return {"score": round(score, 1), "band": band, "emoji": emoji,
            "frozen": frozen, "parts": parts,
            "sentence": " · ".join(f"{p['label']} {p['value']}" for p in parts)}


# ── one horizon ─────────────────────────────────────────────────────────

def _horizon_row(h: Horizon, reads: Dict[str, Dict],
                 stab: Dict[str, Any]) -> Dict[str, Any]:
    """One horizon's read, scored and explained."""
    owned = owners_of(h)
    reporting = [p for p in owned if p in reads]
    bull = [p for p in reporting if _sign(reads[p]["bias"]) > 0]
    bear = [p for p in reporting if _sign(reads[p]["bias"]) < 0]
    directional = len(bull) + len(bear)

    row: Dict[str, Any] = {
        "horizon": h.value, "hold": HOLD[h],
        "owned": len(owned), "reporting": len(reporting),
        "evidence": f"{len(reporting)}/{len(owned)}",
        "bull": len(bull), "bear": len(bear),
        "stability": stab["band"], "stability_emoji": stab["emoji"],
        "stability_score": stab["score"],
        "lost_because": [],
        "reasons": [],
        "advisory_only": True,
    }
    if h in DEGRADED:
        row["degraded"] = DEGRADED[h]

    # nothing to say — reported honestly rather than as a neutral verdict
    if not directional:
        row.update({"verdict": "NO READ", "score": 0.0, "confidence": 0.0,
                    "coverage": 0.0})
        row["lost_because"].append(
            "no owned producer reported a direction"
            if not reporting else
            f"all {len(reporting)} reporting producers are neutral")
        return row

    lead, agreeing = (1, len(bull)) if len(bull) >= len(bear) else (-1, len(bear))
    winners = bull if lead > 0 else bear
    coverage = len(reporting) / float(len(owned)) if owned else 0.0
    conf = 100.0 * agreeing / directional

    w = wilson(agreeing, directional)          # returns PERCENT, not fraction
    base = (w or {}).get("low", 0.0)
    score = base * coverage

    # Stage 44, per horizon. A shift destroys a scalp; it can be the swing
    # thesis — so the effect is looked up, never applied globally.
    effect = FLOW_SHIFT_EFFECT.get(h)
    veto = False
    if stab.get("frozen") and effect == "veto":
        veto, score = True, 0.0
        row["lost_because"].append("Stage 44 flow-shift veto — tape changed")
    elif stab.get("frozen") and effect == "discount":
        score *= FLOW_SHIFT_DISCOUNT
        row["lost_because"].append(
            f"Stage 44 flow shift — score discounted "
            f"{(1 - FLOW_SHIFT_DISCOUNT) * 100:.0f}%")

    row.update({
        "score": round(score, 1), "confidence": round(conf, 1),
        "coverage": round(coverage, 3), "agreeing": agreeing,
        "directional": directional, "veto": veto,
        "flow_shift_effect": effect,
        "reasons": [reads[p]["label"] for p in winners[:5]],
    })

    if h in NO_OPTION_SIDE:
        # structure only — `side` is ABSENT, so no renderer can mistake it
        row["verdict"] = ("Bullish Structure" if lead > 0 else
                          "Bearish Structure")
        row["bias"] = "BULL" if lead > 0 else "BEAR"
        row["no_option_side"] = (
            "today's option chain is current-expiry positioning and cannot "
            "support a multi-week side — structure and levels only")
    else:
        row["side"] = _side(lead)
        row["verdict"] = row["side"]

    # why this row is weak, said plainly
    if coverage < 0.6:
        row["lost_because"].append(
            f"thin coverage — only {len(reporting)} of {len(owned)} reported")
    if directional < 5:
        row["lost_because"].append(
            f"small sample — {directional} directional producers")
    if conf < 65:
        row["lost_because"].append(f"split evidence — {conf:.0f}% agreement")
    if stab["band"] == "Low" and not veto:
        row["lost_because"].append(f"low stability — {stab['sentence']}")
    return row


# ── the matrix ──────────────────────────────────────────────────────────

def build_matrix(final_read: Optional[Dict[str, Any]] = None,
                 native_reads: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Any]:
    """The Trade Opportunity Matrix. Always a dict, never raises.

    `native_reads` carries the vob_minimal signal reads as `{producer_id:
    bias}` or `{producer_id: {bias, confidence, label}}`. It is a PARAMETER
    because this module may not reach into `session_state` — the caller
    extracts, this module interprets.
    """
    fr = dict(final_read or {})
    stab = stability(fr)
    reads = _producer_reads(fr, native_reads)

    rows = [_horizon_row(h, reads, stab) for h in HORIZONS]

    # Swing is reported but never ranked — it competes on a different question
    rankable = [r for r in rows
                if r.get("side") and r["score"] > 0 and not r.get("veto")]
    rankable.sort(key=lambda r: (-r["score"], -r["confidence"], r["horizon"]))
    for i, r in enumerate(rankable):
        r["rank"] = i + 1
    best = rankable[0]["horizon"] if rankable else None
    for r in rankable[1:]:
        top = rankable[0]
        r["lost_because"].insert(
            0, f"{top['horizon']} scored {top['score']:.0f} vs {r['score']:.0f}")

    # ── the order the panel renders in ──
    # `rows` stays in horizon order (fastest first) because that is the stable
    # shape callers iterate. But rendering it that way puts 🥉 above 🥈 whenever
    # a slower horizon outranks a faster one, which reads as a broken widget.
    # The order is decided here, where it is tested, rather than in the panel.
    # Ranked first by score, then everything unranked, swing always last —
    # it answers a different question and never competes for a medal.
    _rank_pos = {h: i for i, h in enumerate(r["horizon"] for r in rankable)}
    display_order = sorted(
        (r["horizon"] for r in rows),
        key=lambda h: (h == Horizon.SWING.value,
                       _rank_pos.get(h, len(_rank_pos)),
                       [x.value for x in HORIZONS].index(h)))

    return {
        "rows": rows,
        "ranked": [r["horizon"] for r in rankable],
        "display_order": display_order,
        "best": best,
        "stability": stab,
        "reference": _reference(fr),
        "excluded": _excluded(),
        "reporting_total": len(reads),
        "owned_total": len(OWNED),
        # binding: this is displayed and ranked. It is not consumed.
        "advisory_only": True,
    }


#: `_dir` on an all-bias row → the Bias vocabulary the registry speaks
_DIR_TO_BIAS = {"bull": "BULL", "bear": "BEAR", "neutral": "NEUTRAL"}

#: label → producer id, inverted once at import
_LABEL_TO_ID = {v: k for k, v in NATIVE_LABEL.items()}


def native_reads_from_rows(rows: Optional[List[Dict[str, Any]]]
                           ) -> Dict[str, Dict[str, Any]]:
    """Translate vob_minimal's all-bias rows into `{producer_id: read}`.

    The app publishes `_all_bias_rows` as
    `{'Engine': <label>, '_dir': 'bull'|'bear'|'neutral', 'Detail': ...}`.
    This is the ONLY bridge between that display vocabulary and the registry's
    immutable ids, and it lives here — pure and testable — rather than in the
    panel, so the panel never has to know how a producer is named.

    A label with no registered id is **skipped, not guessed**. That is the
    visible half of the CI rule: an unregistered signal cannot sneak into a
    horizon's evidence just because it happened to render a row.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        pid = _LABEL_TO_ID.get(str(row.get("Engine") or ""))
        if pid is None or pid not in OWNED:
            continue                      # unregistered, aggregate or excluded
        bias = _DIR_TO_BIAS.get(str(row.get("_dir") or "").lower())
        if not bias:
            continue
        out[pid] = {"bias": bias,
                    # the all-bias table carries no per-signal confidence; a
                    # fabricated one would flow straight into the star display
                    "confidence": _f(row.get("confidence")),
                    "label": row.get("Engine"),
                    "detail": row.get("Detail") or ""}
    return out


def _reference(fr: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The aggregates — shown beside the matrix, never inside it.

    If the matrix says CALL and the V5 headline says PUT, that disagreement is
    the most useful thing on the panel. It is displayed for exactly the reason
    the V5‖V6 strip exists, and it votes for exactly the reason Stage 53 does
    not let correlated evidence vote twice.
    """
    eb = fr.get("engine_bias") or {}
    out: List[Dict[str, Any]] = []
    for pid in _REFERENCE_ORDER:
        if pid == "v6_bias":
            continue                       # supplied by the caller if present
        node = eb.get(pid)
        if not isinstance(node, dict) or not node.get("bias"):
            continue
        if str(node["bias"]).upper() == "NONE":
            continue
        out.append({"id": pid, "bias": node["bias"],
                    "confidence": node.get("confidence"),
                    "reason": AGGREGATE.get(pid, ""), "voting": False})
    # the V5 headline itself
    if fr.get("preferred_bias"):
        out.insert(0, {"id": "v5_preferred_bias", "bias": fr["preferred_bias"],
                       "confidence": fr.get("confidence_tempered",
                                            fr.get("confidence")),
                       "reason": "the Conflict-Engine arbitrated read",
                       "voting": False})
    return out


def _excluded() -> List[Dict[str, Any]]:
    """Everything deliberately kept out, with the reason. Debugging a matrix
    that looks wrong starts here — a silently dropped producer is
    indistinguishable from one that never existed."""
    out = [{"id": pid, "reason": why, "kind": "excluded"}
           for pid, why in sorted(EXCLUDED.items())]
    out += [{"id": pid, "reason": why, "kind": "aggregate"}
            for pid, why in sorted(AGGREGATE.items())]
    return out
