"""MIOS V6 — Stage 55 Trade Attribution (the foundation of Phase 6).

Every stage after this one — engine accuracy, confidence calibration, threshold
optimisation, engine contribution, false-signal analysis — is a *query over this
record*. If the record is thin, all five are guesswork. So this module captures
the whole state of the world at the moment a trade is proposed, and then the
whole life of the trade, and never rewrites either.

    BEFORE ENTRY   what MIOS believed, engine by engine, and why
    DURING         what actually happened, as it happened (append-only)
    AFTER EXIT     what it cost or made, and how well it was traded

**Why per-engine rows and not one blob.** A single `engine_snapshot` JSON tells
you a trade lost. It cannot tell you *which engine was wrong*, because you can
never join it back to an outcome per engine. One row per engine per trade is
what turns "MIOS is 54% accurate" into "Stage 43 is 71% accurate and Stage 31 is
44% — stop weighting Stage 31."

**The three fields that do the real work** are `agreement`, `conflict` and
`reliability`:

    agreement    did this engine point the same way as the trade?
    conflict     did it actively point the other way? (NEUTRAL is neither)
    reliability  what was this engine's historical accuracy AT THAT TIME?

That last one matters more than it looks. Recording today's reliability score
against a trade taken last month would make every backtest look prescient. The
value stored is the one the engine had *earned by then*.

This module is pure — dicts in, dicts out, no pandas, no Streamlit, no IO. The
caller owns persistence and supplies the clock.

**Boundary (binding):** nothing in here is imported by the live decision path.
The Learning Engine observes, measures, explains, recommends and validates. It
does not vote.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: The engines whose read is worth attributing to a trade. Not every stage —
#: only the ones that express a directional or confirming opinion, which is
#: exactly the set that can be *wrong* in a way worth measuring.
ATTRIBUTED_ENGINES = (
    "stage05_regime", "stage11_dealer", "stage12_options",
    "stage13_institutional", "stage14_orderflow", "stage17_liquidity",
    "stage22_vix", "stage25_intent", "stage26_patterns", "stage27_conflict",
    "stage31_probability", "stage35_reaction_zone", "stage37_energy",
    "stage42_acceptance", "stage43_absorption", "stage44_flow_shift",
    "stage45_htf_vpfr", "stage47_transition", "stage48_market_state",
    "stage50_ltp_behaviour", "stage51_validity", "stage53_evidence",
    "stage54_memory",
)

#: Terminal exit reasons. A trade always ends for exactly one of these.
EXIT_REASONS = (
    "TARGET_HIT", "TRAILING_STOP", "MANUAL", "FLOW_SHIFT", "DEALER_FLIP",
    "BIAS_CHANGE", "ACCEPTANCE_FAILED", "STOP_LOSS", "TIME_EXIT", "AI_EXIT",
)

#: Append-only event kinds recorded during the life of a trade.
EVENT_KINDS = (
    "excursion", "trail", "stop", "partial", "scale_in", "scale_out",
    "flow_shift", "bias_change", "state_change", "note",
)

_BULL = ("STRONG_BULL", "BULL")
_BEAR = ("STRONG_BEAR", "BEAR")

#: A CALL is a bullish trade, a PUT is a bearish one.
_SIDE_BIAS = {"CALL": 1, "PUT": -1}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").strip()


def bias_sign(bias: Any) -> int:
    """+1 bullish · -1 bearish · 0 neutral/none. `Bias.NONE` and `NEUTRAL` both
    collapse to 0 — an engine that declined to lean did not agree *or* conflict,
    and scoring it either way would corrupt every accuracy number downstream."""
    b = _s(getattr(bias, "value", bias)).upper()
    if b in _BULL:
        return 1
    if b in _BEAR:
        return -1
    return 0


def side_sign(direction: Any) -> int:
    return _SIDE_BIAS.get(_s(direction).upper(), 0)


# ── BEFORE ENTRY ────────────────────────────────────────────────────────
def engine_rows(reads: Optional[Dict[str, Any]], direction: str,
                weights: Optional[Dict[str, float]] = None,
                reliability: Optional[Dict[str, float]] = None,
                freshness: Optional[Dict[str, float]] = None,
                engines: Sequence[str] = ATTRIBUTED_ENGINES,
                ) -> List[Dict[str, Any]]:
    """One attribution row per engine, for one proposed trade.

    `reads` is `{engine_name: {"bias", "status", "confidence", "output",
    "stage", "data"}}` — already flattened by the caller so this stays pure.
    `reliability` is the engine's accuracy **as known at this moment**; pass
    `None` for an engine with no history yet rather than defaulting it to 50,
    which would fabricate a track record it has not earned.
    """
    rd, w = reads or {}, weights or {}
    rel, fr = reliability or {}, freshness or {}
    tside = side_sign(direction)
    rows: List[Dict[str, Any]] = []

    for name in engines:
        r = rd.get(name)
        if not r:
            continue
        sign = bias_sign(r.get("bias"))
        conf = _f(r.get("confidence")) or 0.0
        status = _s(r.get("status")).upper() or "NEUTRAL"
        # a DEGRADED/ERROR engine still gets a row — "it was broken that day" is
        # itself an attributable cause of a loss
        rows.append({
            "engine": name,
            "stage": r.get("stage"),
            "output": _s(r.get("output")) or None,
            "bias": _s(getattr(r.get("bias"), "value", r.get("bias"))).upper()
                    or "NONE",
            "status": status,
            "confidence": round(conf, 1),
            # strength = how hard it leaned, direction-signed
            "strength": round(sign * conf, 1),
            "weight": _f(w.get(name)),
            "agreement": bool(tside and sign == tside),
            "conflict": bool(tside and sign == -tside),
            "reliability": _f(rel.get(name)),
            "freshness_min": _f(fr.get(name)),
            "data": r.get("data") or {},
        })
    return rows


def _market_quality(fr: Dict[str, Any]) -> Optional[str]:
    """The derived tradeability grade. Imported lazily so Stage 55 keeps no
    hard dependency on the V6.5 explainability layer."""
    try:
        from .explain_decision import market_quality
        q = market_quality(fr)
        return q["grade"] if q.get("grade") != "—" else None
    except Exception:
        return None


def entry_attribution(signal: Optional[Dict[str, Any]],
                      final_read: Optional[Dict[str, Any]] = None,
                      thesis: Optional[str] = None,
                      controller: Optional[str] = None,
                      snapshot: Optional[Dict[str, Any]] = None,
                      ) -> Dict[str, Any]:
    """The trade-level half of Stage 55 — the market as MIOS read it."""
    sig, fr = signal or {}, final_read or {}

    def _lab(key, *path):
        node = fr.get(key) or {}
        for p in path:
            if not isinstance(node, dict):
                return None
            node = node.get(p)
        return _s(node) or None

    return {
        "signal_id": sig.get("signal_id"),
        "trading_day": sig.get("trading_day"),
        "direction": sig.get("side"),
        "entry_price": _f(sig.get("entry_price")),
        "stop": _f(sig.get("stop")),
        "target": _f(sig.get("target")),
        "trail": _f(sig.get("trail")),
        "rr": _f(sig.get("rr")),
        "confidence": _f(sig.get("confidence")),
        "quality": sig.get("quality"),
        "market_quality": _market_quality(fr),
        "market_controller": _s(controller) or None,
        "market_state": _lab("market_state", "label"),
        "market_bias": _s(fr.get("preferred_bias")) or None,
        "bias_transition": _lab("transition", "label"),
        "ltp_behaviour": _lab("ltp_behaviour", "sentence"),
        "acceptance": _lab("acceptance", "label"),
        "absorption": _lab("absorption", "label"),
        "flow_shift": _s(fr.get("stability")) or None,
        "sr_state": _lab("battle_zone", "type"),
        "dealer_state": _lab("dealer", "label"),
        "order_flow": _lab("orderflow", "label"),
        "options_state": _lab("options", "label"),
        "htf_alignment": _lab("htf", "alignment"),
        "ai_thesis": _s(thesis) or None,
        "decision_reason": sig.get("reason") or {},
        "snapshot": snapshot or {},
    }


# ── DURING THE TRADE ────────────────────────────────────────────────────
def track_excursion(prior: Optional[Dict[str, Any]], direction: str,
                    entry: Any, spot: Any) -> Dict[str, Any]:
    """Running MFE / MAE in points, signed by side.

    MFE is how far the trade went *for* you at its best; MAE how far *against*
    you at its worst. Both matter more than the exit price: a trade that ran
    +40 and closed +2 is a management failure, not a bad signal, and only the
    excursion pair can tell those apart.
    """
    st = dict(prior or {})
    e, p, sgn = _f(entry), _f(spot), side_sign(direction)
    if e is None or p is None or not sgn:
        return st
    move = (p - e) * sgn
    st["mfe"] = round(max(_f(st.get("mfe")) or 0.0, move), 2)
    st["mae"] = round(min(_f(st.get("mae")) or 0.0, move), 2)
    st["last"] = round(move, 2)
    st["samples"] = int(st.get("samples", 0)) + 1
    # max drawdown from the running peak — the pain endured after being ahead
    peak = _f(st.get("_peak"))
    peak = move if peak is None else max(peak, move)
    st["_peak"] = round(peak, 2)
    st["max_drawdown"] = round(max(_f(st.get("max_drawdown")) or 0.0,
                                   peak - move), 2)
    return st


def event(kind: str, ts: Any = None, spot: Any = None,
          excursion: Optional[Dict[str, Any]] = None,
          **detail) -> Dict[str, Any]:
    """One append-only row in the life of a trade. Never an update."""
    k = _s(kind).lower()
    ex = excursion or {}
    return {
        "kind": k if k in EVENT_KINDS else "note",
        "ts": ts,
        "spot": _f(spot),
        "mfe": _f(ex.get("mfe")),
        "mae": _f(ex.get("mae")),
        "detail": {k: v for k, v in detail.items() if v is not None},
    }


# ── AFTER EXIT ──────────────────────────────────────────────────────────
_QUALITY_STEPS = ((0.80, "EXCELLENT"), (0.60, "GOOD"), (0.35, "FAIR"),
                  (0.15, "POOR"))


def trade_quality(pnl: Optional[float], mfe: Optional[float],
                  mae: Optional[float]) -> str:
    """How well was the trade *managed*, independent of whether it won.

    Efficiency = captured / available. A +50 winner out of a +55 run is
    excellent; the same +50 out of a +200 run is not, and calling both "win"
    hides the second problem forever.
    """
    p, m = _f(pnl), _f(mfe)
    if p is None:
        return "—"
    if p <= 0:
        # a loss that never went your way is a bad *signal*; one that ran +30
        # first is a bad *exit*. Both are BAD, but the reason differs.
        return "BAD" if (m or 0.0) < 5 else "POOR"
    if not m or m <= 0:
        return "GOOD"
    eff = p / m
    for threshold, label in _QUALITY_STEPS:
        if eff >= threshold:
            return label
    return "POOR"


def exit_attribution(attribution: Optional[Dict[str, Any]],
                     exit_price: Any, exit_reason: str,
                     excursion: Optional[Dict[str, Any]] = None,
                     entered_price: Any = None,
                     holding_secs: Any = None, exit_at: Any = None,
                     ) -> Dict[str, Any]:
    """The outcome row — written once, at exit, and never revised."""
    a, ex = attribution or {}, excursion or {}
    side = a.get("direction")
    sgn = side_sign(side)
    entry = _f(entered_price)
    if entry is None:
        entry = _f(a.get("entry_price"))
    xp = _f(exit_price)

    pnl = round((xp - entry) * sgn, 2) if (xp is not None and entry and sgn) else None
    ret = round(100.0 * pnl / entry, 3) if (pnl is not None and entry) else None

    target, stop = _f(a.get("target")), _f(a.get("stop"))
    expected = round(abs(target - entry), 2) if (target and entry) else None
    actual = abs(pnl) if pnl is not None else None
    mfe = _f(ex.get("mfe"))
    eff = round(pnl / mfe, 3) if (pnl is not None and mfe and mfe > 0) else None

    reason = _s(exit_reason).upper()
    if reason not in EXIT_REASONS:
        reason = "MANUAL"

    if pnl is None:
        outcome = "never_entered"
    elif pnl > 0:
        outcome = "win"
    elif pnl < 0:
        outcome = "loss"
    else:
        outcome = "scratch"

    return {
        "signal_id": a.get("signal_id"),
        "trading_day": a.get("trading_day"),
        "exit_price": xp,
        "exit_at": exit_at,
        "exit_reason": reason,
        "outcome": outcome,
        "pnl_points": pnl,
        "return_pct": ret,
        "holding_secs": _f(holding_secs),
        "mfe": mfe,
        "mae": _f(ex.get("mae")),
        "max_drawdown": _f(ex.get("max_drawdown")),
        "expected_move": expected,
        "actual_move": actual,
        "efficiency": eff,
        "trade_quality": trade_quality(pnl, mfe, _f(ex.get("mae"))),
        "notes": {"stop": stop, "target": target, "side": side},
    }


# ── JOIN: what Stages 56-60 actually consume ────────────────────────────
def join_outcomes(engine_rows_all: Optional[Sequence[Dict[str, Any]]],
                  results: Optional[Sequence[Dict[str, Any]]],
                  ) -> List[Dict[str, Any]]:
    """Join per-engine rows to their trade's outcome.

    Ungraded trades are dropped rather than counted as losses — an open trade
    is not a failure, and treating it as one is the single easiest way to make
    a learning system permanently pessimistic.
    """
    by_id = {}
    for r in results or []:
        sid = r.get("signal_id")
        if sid and r.get("outcome") in ("win", "loss"):
            by_id[sid] = r
    out = []
    for row in engine_rows_all or []:
        res = by_id.get(row.get("signal_id"))
        if not res:
            continue
        merged = dict(row)
        merged.update({
            "outcome": res.get("outcome"),
            "won": res.get("outcome") == "win",
            "pnl_points": _f(res.get("pnl_points")),
            "holding_secs": _f(res.get("holding_secs")),
            "mfe": _f(res.get("mfe")),
            "mae": _f(res.get("mae")),
            "exit_reason": res.get("exit_reason"),
            "trade_quality": res.get("trade_quality"),
            "result_day": res.get("trading_day"),
        })
        out.append(merged)
    return out
