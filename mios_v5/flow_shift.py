"""MIOS V6 — Sudden Flow Shift + Stability (the interrupt).

Every other engine answers *what the market is*. This one answers *did it just
change underneath us* — and if so, it interrupts: *freeze entries, recalculate*.

The distinction that makes it worth its own engine: everything else reads
**levels**, this reads the **derivative**. CVD at -40% is a state; CVD going from
+10% to -40% in one cycle is an event. A signal computed a minute ago may already
be describing a market that no longer exists.

Watched: CVD/delta · OI velocity · money-flow · dealer gamma · IV/VIX · volume ·
raw price displacement.

It also owns **stability** (merged in rather than a separate engine — it is the
same measurement at a different time constant):

    STABLE ──shock──▶ SHOCK ──calms──▶ RECOVERY ──settles──▶ STABLE
       └──elevated──▶ UNSTABLE ──────────┘

Non-directional by design: a flow shift is not a direction, it is a *warning that
direction is being repriced*. It returns Bias.NONE and never votes — it vetoes.

`detect_shift` is PURE (plain numbers in, verdict out) so the thresholds are
testable and tunable from logged data rather than by feel.
"""

from __future__ import annotations

from statistics import mean, pstdev
from typing import Any, Dict, List, Optional, Sequence

# ── v0 thresholds — OBSERVATIONAL. Deliberately conservative: this engine can
# freeze entries, so it must not cry wolf. Tune from logged data, not by feel.
_TH = {
    "cvd_jump": 25.0,        # delta-% swing vs the rolling mean (percentage points)
    "oi_velocity": 3.0,      # % change in total OI in one cycle
    "gamma_shift": 30.0,     # % change in net gamma
    "iv_jump": 4.0,          # % change in IV / VIX
    "volume_mult": 2.2,      # × the rolling-mean volume
    "price_move": 0.25,      # % spot displacement in one cycle
    "mf_jump": 30.0,         # % swing in net money flow
}

_WEIGHT = {
    "cvd": 1.3, "oi": 1.2, "gamma": 1.1, "iv": 1.0,
    "volume": 1.0, "price": 1.2, "mf": 1.0,
}

#: score at/above which the tape is in shock
_SHOCK = 65.0
#: score at/above which it is unstable
_UNSTABLE = 35.0
#: below this, the tape has calmed
_CALM = 20.0

_STATES = ("STABLE", "UNSTABLE", "SHOCK", "RECOVERY")


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # reject NaN


def _mean_of(hist: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [_f(h.get(key)) for h in (hist or [])]
    vals = [v for v in vals if v is not None]
    return mean(vals) if vals else None


def _pct_change(cur: Optional[float], ref: Optional[float]) -> Optional[float]:
    if cur is None or ref is None or ref == 0:
        return None
    return (cur - ref) / abs(ref) * 100.0


def zscore(cur: Optional[float], hist: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    """How many standard deviations the current reading sits from its own recent
    history. Returns None when there isn't enough history to be meaningful —
    never fabricate an outlier from two data points."""
    c = _f(cur)
    vals = [_f(h.get(key)) for h in (hist or [])]
    vals = [v for v in vals if v is not None]
    if c is None or len(vals) < 4:
        return None
    sd = pstdev(vals)
    if sd <= 1e-9:
        return None
    return (c - mean(vals)) / sd


def detect_shift(cur: Optional[Dict[str, Any]],
                 hist: Optional[Sequence[Dict[str, Any]]] = None,
                 prev_state: Optional[str] = None,
                 cycles_since_shock: int = 99) -> Dict[str, Any]:
    """Compare this cycle's flow metrics against their recent history.

    `cur` / each `hist` entry: {spot, cvd_pct, oi_total, gamma_net, iv, volume,
    mf_net} — any subset; missing inputs are skipped, never guessed.

    Returns {signals, score, detected, stability, freeze_entries, velocity,
    reason}. `stability` is one of STABLE / UNSTABLE / SHOCK / RECOVERY.
    """
    c = dict(cur or {})
    h = list(hist or [])
    signals: List[Dict[str, Any]] = []
    velocity: Dict[str, Optional[float]] = {}

    def _fire(key: str, label: str, magnitude: float):
        signals.append({"key": key, "label": label,
                        "magnitude": round(magnitude, 1),
                        "weight": _WEIGHT.get(key, 1.0)})

    prev = h[-1] if h else {}

    # ── CVD / delta: the swing in aggression (percentage POINTS, not %) ──
    cvd, cvd_ref = _f(c.get("cvd_pct")), _mean_of(h, "cvd_pct")
    if cvd is not None and cvd_ref is not None:
        d = cvd - cvd_ref
        velocity["cvd"] = round(d, 1)
        if abs(d) >= _TH["cvd_jump"]:
            _fire("cvd", f"CVD {'surge' if d > 0 else 'collapse'} {d:+.0f}pp "
                         f"({'aggressive buying' if d > 0 else 'aggressive selling'})", abs(d))

    # ── OI velocity: positions being built/torn down fast ──
    oi_ch = _pct_change(_f(c.get("oi_total")), _f(prev.get("oi_total")))
    if oi_ch is not None:
        velocity["oi"] = round(oi_ch, 2)
        if abs(oi_ch) >= _TH["oi_velocity"]:
            _fire("oi", f"OI velocity {oi_ch:+.1f}% "
                        f"({'positions building' if oi_ch > 0 else 'positions unwinding'})",
                  abs(oi_ch))

    # ── dealer gamma repricing ──
    g_ch = _pct_change(_f(c.get("gamma_net")), _f(prev.get("gamma_net")))
    if g_ch is not None:
        velocity["gamma"] = round(g_ch, 1)
        if abs(g_ch) >= _TH["gamma_shift"]:
            _fire("gamma", f"Dealer gamma shift {g_ch:+.0f}%", abs(g_ch))

    # ── IV / VIX jump ──
    iv_ch = _pct_change(_f(c.get("iv")), _f(prev.get("iv")))
    if iv_ch is not None:
        velocity["iv"] = round(iv_ch, 2)
        if abs(iv_ch) >= _TH["iv_jump"]:
            _fire("iv", f"IV {'spike' if iv_ch > 0 else 'crush'} {iv_ch:+.1f}%", abs(iv_ch))

    # ── volume explosion vs its own recent mean ──
    vol, vol_ref = _f(c.get("volume")), _mean_of(h, "volume")
    if vol is not None and vol_ref and vol_ref > 0:
        mult = vol / vol_ref
        velocity["volume"] = round(mult, 2)
        if mult >= _TH["volume_mult"]:
            _fire("volume", f"Volume explosion {mult:.1f}× normal", (mult - 1) * 40)

    # ── raw price displacement (the large candle) ──
    p_ch = _pct_change(_f(c.get("spot")), _f(prev.get("spot")))
    if p_ch is not None:
        velocity["price"] = round(p_ch, 3)
        if abs(p_ch) >= _TH["price_move"]:
            _fire("price", f"Large move {p_ch:+.2f}% in one cycle", abs(p_ch) * 100)

    # ── money-flow swing ──
    mf_ch = _pct_change(_f(c.get("mf_net")), _f(prev.get("mf_net")))
    if mf_ch is not None:
        velocity["mf"] = round(mf_ch, 1)
        if abs(mf_ch) >= _TH["mf_jump"]:
            _fire("mf", f"Money-flow swing {mf_ch:+.0f}%", abs(mf_ch))

    # ── score: weighted evidence, saturating (≈4 strong signals = 100) ──
    got = sum(s["weight"] for s in signals)
    score = min(100.0, got / 4.0 * 100.0)
    n = len(signals)
    # one lone signal is noise; a shift is corroborated OR extreme
    detected = (n >= 2 and score >= 40) or (n >= 1 and score >= _SHOCK)

    # ── stability state machine (same measurement, slower clock) ──
    ps = prev_state if prev_state in _STATES else "STABLE"
    if score >= _SHOCK:
        stability = "SHOCK"
    elif score >= _UNSTABLE:
        stability = "UNSTABLE"
    elif ps in ("SHOCK", "UNSTABLE"):
        # calmed down, but it hasn't earned STABLE back yet
        stability = "RECOVERY" if score < _CALM else "UNSTABLE"
    elif ps == "RECOVERY":
        stability = "STABLE" if cycles_since_shock >= 3 else "RECOVERY"
    else:
        stability = "STABLE"

    # entries freeze while the tape is actively repricing — not during recovery,
    # or we'd never trade again after a busy open
    freeze = stability == "SHOCK" or detected

    if signals:
        top = sorted(signals, key=lambda s: -s["weight"] * min(s["magnitude"], 100))[:3]
        reason = " · ".join(s["label"] for s in top)
    else:
        reason = "flow steady"

    return {
        "signals": signals, "n": n, "score": round(score),
        "detected": bool(detected), "stability": stability,
        "freeze_entries": bool(freeze), "velocity": velocity,
        "reason": reason,
        "label": {"SHOCK": "🚨 SHOCK — tape repricing",
                  "UNSTABLE": "⚠️ UNSTABLE — flow turning",
                  "RECOVERY": "🩹 RECOVERY — settling",
                  "STABLE": "✅ STABLE"}[stability],
    }


def trace_push(trace: Optional[List[Dict[str, Any]]], metrics: Dict[str, Any],
               keep: int = 12) -> List[Dict[str, Any]]:
    """Append this cycle's metrics to the rolling trace (bounded). Kept here so
    the app and the tests share one definition of the window."""
    t = list(trace or [])
    t.append(dict(metrics or {}))
    return t[-keep:]
