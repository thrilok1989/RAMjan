"""MIOS V6 — Dashboard 2 as a trading terminal: the execution adapter.

The index, the ATM Call and the ATM Put evolving together, so a trader can see
*which side is gaining control* without switching screens.

**This module creates nothing.** Every value it emits is read from an engine
that already computed it — Stage 12 Options, Stage 43 Absorption, Stage 50 LTP
Behaviour, Stage 52 Decision, the per-leg VOB store and the leg-bias table.
Its whole job is to assemble those reads into one execution view and to say,
for every number, which engine it came from. A dashboard that invents an
indicator is a dashboard that can disagree with the system it is displaying.

## Two places where the honest answer is "not available"

**Option-premium entry and stop.** The Decision Engine works in NIFTY points,
not premium. Converting a spot stop to an option stop needs delta, which is
not part of any engine's output. So premium entry/stop/trail are shown only
when the leg-level Entry Gate has actually armed a setup — which quotes real
premium — and are otherwise blank. A delta-free conversion would put a
confident ₹ figure on the screen that no engine stands behind.

**Per-leg strength.** There is no "call strength" engine. What exists is the
leg-bias table's own signal tally, so strength is that tally's vote share —
the same quantity Stage 53 reports for families — and it is labelled with its
source rather than presented as a new metric.

Pure module: reads in, view model out. No IO, no pandas, no Streamlit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: Stage 50's option-side state → the badge a trader recognises, per side.
#: The LTP × OI matrix already decides this; the badge only renames it.
_BADGE = {
    "CE": {"building": ("CALL BUILDING", "bull"),
           "distribution": ("CALL WRITING", "bear"),
           "squeeze": ("CALL SHORT COVERING", "bull"),
           "unwinding": ("CALL FADING", "bear")},
    "PE": {"building": ("PUT BUILDING", "bear"),
           "distribution": ("PUT WRITING", "bull"),
           "squeeze": ("PUT SHORT COVERING", "bear"),
           "unwinding": ("PUT FADING", "bull")},
}

#: Stage 43 exhaustion → the leg badge. Exhaustion is the absorption engine's
#: word, not a second calculation.
_EXHAUST = {"CE": "CALL EXHAUSTION", "PE": "PUT EXHAUSTION"}
_BUYING = {"CE": "CALL BUYING", "PE": "PUT BUYING"}

TONE_COLOUR = {"bull": "#00ff88", "bear": "#ff4444", "neutral": "#cfd9e6"}

#: the leg-bias table's signal columns — the tally that becomes `strength`
BIAS_SIGNALS = ("VOB", "S/R", "Div", "Ign", "Absorb", "CVD", "OIvel",
                "VWAP", "VWAP50", "VWAP20", "VIDYA", "VIDYA50", "VIDYA20",
                "MFP", "MFP50", "MFP20")

_BULL_EM, _BEAR_EM = "🟢", "🔴"


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def stars(pct: Optional[float]) -> str:
    p = _f(pct)
    if p is None:
        return "☆☆☆☆☆"
    n = max(0, min(5, int(round(p / 20.0))))
    return "★" * n + "☆" * (5 - n)


# ── one option leg ──────────────────────────────────────────────────────
def leg_read(side: str, tag: Optional[str] = None,
             ltp_side: Optional[Dict[str, Any]] = None,
             bias_row: Optional[Dict[str, Any]] = None,
             vob_zones: Optional[Sequence[Dict[str, Any]]] = None,
             setup: Optional[Dict[str, Any]] = None,
             open_sig: Optional[Dict[str, Any]] = None,
             absorption: Optional[Dict[str, Any]] = None,
             money_flow: Optional[Dict[str, Any]] = None,
             ltp: Any = None) -> Dict[str, Any]:
    """One leg's execution read — badges, bias, strength, entry, trail.

    `side` is "CE" or "PE". Everything else is an existing engine's output;
    anything absent simply does not appear, rather than defaulting.
    """
    sd = _s(side) or "CE"
    ls = dict(ltp_side or {})
    row = dict(bias_row or {})
    zones = list(vob_zones or [])

    # ── badges: Stage 50's state, renamed per side. Only ACTIVE ones. ──
    badges: List[Dict[str, str]] = []
    state = str(ls.get("state") or "").lower()
    mapped = _BADGE.get(sd, {}).get(state)
    if mapped:
        badges.append({"text": mapped[0], "tone": mapped[1],
                       "engine": "Stage 50 LTP Behaviour"})

    mf = dict(money_flow or {})
    if str(mf.get("state") or "").lower() == "entering":
        badges.append({"text": _BUYING[sd], "tone": "bull" if sd == "CE" else "bear",
                       "engine": "Stage 50 Money Flow"})

    ab = dict(absorption or {})
    if str(ab.get("behaviour") or "").endswith("EXHAUSTION"):
        badges.append({"text": _EXHAUST[sd], "tone": "neutral",
                       "engine": "Stage 43 Absorption"})

    # ── strength: the leg-bias table's own vote share, not a new metric ──
    strength, agree, total = _leg_strength(row)
    verdict = str(row.get("Leg Verdict") or "")
    bias = ("bull" if _BULL_EM in verdict else
            "bear" if _BEAR_EM in verdict else "neutral")

    # ── VOB: the per-leg zone store, summarised not recomputed ──
    building = [z for z in zones if _s(z.get("status")) == "BUILDING"]
    fading = [z for z in zones if _s(z.get("status")) == "FADING"]
    vob_state = ("Rising" if len(building) > len(fading) else
                 "Falling" if fading else "Flat" if zones else None)
    buy_vol = sum(_f(z.get("buy_vol")) or 0.0 for z in building)

    # ── entry / trail: premium only when the leg gate actually armed one ──
    entry_block = _entry_block(setup, open_sig)

    return {
        "side": sd, "tag": tag,
        "ltp": _f(ltp) if ltp is not None else _f(str(row.get("LTP", "")).lstrip("₹") or None),
        "badges": badges,
        "bias": bias, "bias_label": bias.title(),
        "bias_colour": TONE_COLOUR[bias],
        "strength": strength, "stars": stars(strength),
        "strength_source": (f"{agree}/{total} leg signals agree"
                            if total else "no leg-bias row yet"),
        "state": state or None,
        "state_label": ls.get("label"),
        "vob": vob_state, "vob_building": len(building),
        "vob_buy_volume": round(buy_vol, 1) if buy_vol else None,
        "accumulation": bool(building) and state in ("building", "squeeze"),
        "distribution": state == "distribution",
        "money_flow": mf.get("label"),
        "money_flow_state": mf.get("state"),
        "cvd": row.get("CVD"), "delta": row.get("Div"),
        "volume": row.get("VOB"),
        **entry_block,
        "sentence": _leg_sentence(sd, state, bias, strength, vob_state,
                                  bool(building)),
    }


def _leg_strength(row: Dict[str, Any]) -> Tuple[Optional[float], int, int]:
    """Vote share of the leg's own signal tally — the same quantity Stage 53
    reports for families, not a new indicator."""
    bull = bear = 0
    for k in BIAS_SIGNALS:
        v = str(row.get(k) or "")
        if _BULL_EM in v:
            bull += 1
        elif _BEAR_EM in v:
            bear += 1
    total = bull + bear
    if not total:
        return None, 0, 0
    lead = max(bull, bear)
    return round(100.0 * lead / total, 1), lead, total


def _entry_block(setup: Optional[Dict[str, Any]],
                 open_sig: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Premium entry / stop / trail — ONLY from the leg gate, which quotes
    real premium. No delta-free conversion of a spot stop."""
    live = dict(open_sig or {})
    armed = dict(setup or {})
    src = live or armed
    if not src:
        return {"entry": None, "stop": None, "target": None, "trail": None,
                "trail_state": None, "entry_state": None,
                "entry_note": "No leg-level setup armed — the Decision Engine "
                              "works in NIFTY points, and premium levels are "
                              "not derivable without delta."}
    trail = _f(src.get("trail"))
    return {
        "entry": _f(src.get("entry")), "stop": _f(src.get("sl")),
        "target": _f(src.get("t1")), "trail": trail,
        "trail_state": src.get("trail_state") or ("Tightening" if trail else None),
        "entry_state": "LIVE" if live else "ARMED",
        "entry_note": None,
        "entry_confidence": _f(src.get("confidence")),
    }


def _leg_sentence(side: str, state: str, bias: str, strength: Optional[float],
                  vob: Optional[str], building: bool) -> str:
    """One sentence, assembled from the states above — never generic."""
    who = "Call" if side == "CE" else "Put"
    if not state or state == "flat":
        return f"{who} side flat — no clear participation."
    parts = {
        "building": f"{who} buyers accumulating",
        "distribution": f"{who} writers defending aggressively",
        "squeeze": f"{who} writers being covered — short squeeze",
        "unwinding": f"{who} holders leaving — position unwinding",
    }.get(state, f"{who} side {state}")
    tail = []
    if vob == "Rising" and building:
        tail.append("VOB building")
    elif vob == "Falling":
        tail.append("VOB fading")
    if strength is not None:
        tail.append(f"{strength:g}% of leg signals agree")
    return parts + (". " + ", ".join(tail) + "." if tail else ".")


# ── CALL vs PUT ─────────────────────────────────────────────────────────
_COMPARE_ROWS = (
    ("Bias", "bias_label"), ("Strength", "strength"),
    ("Money Flow", "money_flow"), ("VOB", "vob"),
    ("Accumulation", "accumulation"), ("Distribution", "distribution"),
    ("Entry", "entry_state"), ("Trail", "trail_state"),
)


def compare_ribbon(call: Optional[Dict[str, Any]],
                   put: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The side-by-side ribbon, with the stronger side marked.

    "Stronger" is decided by strength alone when both sides report it — a
    composite scoring of eight display rows would be a new indicator, which is
    exactly what this dashboard is not allowed to invent.
    """
    c, p = dict(call or {}), dict(put or {})
    rows = []
    for label, key in _COMPARE_ROWS:
        cv, pv = c.get(key), p.get(key)
        rows.append({"metric": label,
                     "call": _fmt_cell(cv), "put": _fmt_cell(pv)})

    cs, ps = _f(c.get("strength")), _f(p.get("strength"))
    if cs is None and ps is None:
        winner, why = None, "neither leg has reported a signal tally yet"
    elif ps is None or (cs is not None and cs > ps):
        winner, why = "CALL", f"{cs:g}% vs {ps if ps is not None else '—'}%"
    elif cs is None or ps > cs:
        winner, why = "PUT", f"{ps:g}% vs {cs if cs is not None else '—'}%"
    else:
        winner, why = None, f"both at {cs:g}% — no edge"

    return {"rows": rows, "winner": winner, "why": why,
            "call_strength": cs, "put_strength": ps}


def _fmt_cell(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, (int, float)):
        return f"{v:g}%"
    return str(v)


def dominance(call: Optional[Dict[str, Any]],
              put: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Which side is in control — drives the chart tint.

    Requires a real gap. Tinting the whole screen green on a 51/49 split would
    read as a signal where there is none.
    """
    c, p = _f((call or {}).get("strength")), _f((put or {}).get("strength"))
    if c is None or p is None:
        return {"side": "neutral", "gap": None, "tint": "rgba(140,150,170,.05)"}
    gap = round(c - p, 1)
    if gap >= 10:
        return {"side": "call", "gap": gap, "tint": "rgba(0,255,136,.06)"}
    if gap <= -10:
        return {"side": "put", "gap": gap, "tint": "rgba(255,68,68,.06)"}
    return {"side": "neutral", "gap": gap, "tint": "rgba(140,150,170,.05)"}


# ── the market ribbon on the NIFTY chart ────────────────────────────────
def market_ribbon(final_read: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    from .explain_decision import market_quality
    fr = dict(final_read or {})
    ms = fr.get("market_state") or {}
    tr = fr.get("transition") or {}
    dec = fr.get("decision_v2") or {}
    mq = market_quality(fr)
    conf = _f(dec.get("confidence"))
    if not conf:
        conf = _f(fr.get("confidence_tempered", fr.get("confidence")))
    return {
        "state": ms.get("label") or ms.get("state") or "—",
        "transition": tr.get("label") or "—",
        "bias": fr.get("preferred_bias") or "—",
        "quality": mq["grade"], "quality_colour": mq["colour"],
        "confidence": int(round(conf or 0)),
        "day_type": (fr.get("day_classification") or {}).get("label"),
    }


# ── the mini intelligence panel ─────────────────────────────────────────
def option_intelligence(final_read: Optional[Dict[str, Any]],
                        call: Optional[Dict[str, Any]] = None,
                        put: Optional[Dict[str, Any]] = None
                        ) -> List[Dict[str, Any]]:
    """Six rows, each quoting the engine behind it."""
    from .final_read import section
    fr = dict(final_read or {})
    c, p = dict(call or {}), dict(put or {})
    fam = fr.get("families") or {}
    dc = fr.get("day_classification") or {}
    rows: List[Dict[str, Any]] = []

    def add(label, value, engine, stars_pct=None, tone="neutral"):
        if value in (None, "", "—"):
            return
        rows.append({"label": label, "value": value, "engine": engine,
                     "stars": stars(stars_pct) if stars_pct is not None else None,
                     "tone": tone})

    add("Calls", (c.get("state_label") or c.get("state") or "").strip() or None,
        "Stage 50", c.get("strength"), c.get("bias", "neutral"))
    add("Puts", (p.get("state_label") or p.get("state") or "").strip() or None,
        "Stage 50", p.get("strength"), p.get("bias", "neutral"))

    writers = None
    if c.get("state") == "distribution" or p.get("state") == "distribution":
        writers = "Dominating"
    elif c.get("state") == "squeeze" or p.get("state") == "squeeze":
        writers = "Being covered"
    elif c.get("state") or p.get("state"):
        writers = "Passive"
    add("Writers", writers, "Stage 50 LTP × OI")

    inst = fam.get("institutions") or {}
    if inst.get("direction") and inst["direction"] != "NEUTRAL":
        add("Institutions", f"{inst['direction']} {inst.get('strength', 0)}%",
            "Stage 53 Evidence",
            _f(inst.get("strength")),
            "bull" if inst["direction"] == "BULL" else "bear")

    dealer = section(fr, "dealer")
    add("Dealer", dealer.get("headline") or dealer.get("bias"), "Stage 11")

    of = section(fr, "orderflow")
    add("Flow", of.get("headline") or of.get("bias"), "Stage 14")

    ab = fr.get("absorption") or {}
    if ab.get("behaviour") and ab["behaviour"] != "NONE":
        add("Absorption", ab.get("label"), "Stage 43",
            _f(ab.get("confidence")), ab.get("tone", "neutral"))

    if dc.get("expected"):
        add("Expected", dc["expected"][0], f"Stage 68 · {dc.get('label', '')}")
    return rows


# ── the recommendation banner ───────────────────────────────────────────
def recommendation(final_read: Optional[Dict[str, Any]],
                   call: Optional[Dict[str, Any]] = None,
                   put: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The bottom banner: the trade, or an explicit WAIT with the reason.

    Levels are quoted in NIFTY points, which is what the Decision Engine
    actually produced. The matching leg's premium levels are attached
    separately when — and only when — the leg gate armed them.
    """
    from .explain_decision import explain
    fr = dict(final_read or {})
    dec = fr.get("decision_v2") or {}
    e = explain(fr)
    act = e["action"]

    leg = (call if _s(dec.get("side")) == "CALL"
           else put if _s(dec.get("side")) == "PUT" else None) or {}

    if act in ("BUY", "SELL"):
        return {
            "trading": True, "action": f"{act} {dec.get('side', '')}".strip(),
            "colour": e["colour"], "emoji": e["emoji"],
            "entry": _f(dec.get("entry")), "stop": _f(dec.get("stop")),
            "trail": _f((dec.get("trail") or {}).get("stop")),
            "target": _f(fr.get("next_target")),
            "confidence": e["confidence"], "quality": dec.get("quality"),
            "reasons": [r["text"] for r in e["reasons"][:4]],
            "risk": e["risk"],
            "leg_entry": leg.get("entry"), "leg_stop": leg.get("stop"),
            "leg_trail": leg.get("trail"), "leg_tag": leg.get("tag"),
            "leg_note": leg.get("entry_note"),
            "units": "NIFTY points",
        }
    return {
        "trading": False, "action": act,
        "colour": e["colour"], "emoji": e["emoji"],
        "headline": ("No high-probability setup" if act == "WAIT"
                     else e.get("label") or act),
        "confidence": e["confidence"],
        "readiness": e.get("readiness", 0),
        "reasons": ([e["blocked_by"]] if e.get("blocked_by") else [])
                   + [f"{n['label']} — have: {n['have']}"
                      for n in (e.get("needs") or [])[:3]],
        "risk": e["risk"],
        "units": None,
    }
