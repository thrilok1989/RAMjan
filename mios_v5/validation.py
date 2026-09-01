"""MIOS V5 — Validation Dashboard (evaluates the SYSTEM, not the market).

Pure aggregation over closed ENTRY GATE trades (entry_gate_signals rows). It
answers the questions that turn intuition-set thresholds into evidence:

  • Does the gate have edge?          → win-rate + expectancy (avg R)
  • Where does it work?               → by side / zone / regime
  • Are the thresholds right?         → win-rate by strength / R:R / grade bucket
  • Is the 60% noise band right?      → MAE distribution of WINNERS
  • Does the Guardian exit well?      → exit-reason mix + reversal save-rate
  • Which layers deserve weight?      → handed to the shadow learner

No Streamlit / no DB — unit-testable. Every metric guards on sample size and
says "insufficient" honestly rather than reporting noise as signal.
"""

from __future__ import annotations

from statistics import mean, median
from typing import Any, Dict, List, Optional

_MIN_TRADES = 30          # below this, headline numbers are noise
_L2 = 30                  # unlock breakdowns / quality quadrant
_L3 = 100                 # unlock layer-contribution / re-weighting

# layer keys we log leans for (mirrors layer_scores._LAYERS order)
_LAYER_KEYS = ["environment", "structure", "positioning", "orderflow",
               "options", "liquidity", "psychology"]


def _risk(row: Dict[str, Any]) -> Optional[float]:
    try:
        entry = float(row.get("spot"))
        inval = float(row.get("invalidation"))
        r = abs(entry - inval)
        return r if r > 0 else None
    except Exception:
        return None


def _pts(row: Dict[str, Any]) -> Optional[float]:
    try:
        return float(row.get("points_moved"))
    except Exception:
        return None


def _wr(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Win-rate + expectancy for a set of resolved rows."""
    ps = [_pts(r) for r in rows]
    ps = [p for p in ps if p is not None]
    if not ps:
        return None
    wins = sum(1 for p in ps if p > 0)
    n = len(ps)
    rs = []
    for r in rows:
        p, rk = _pts(r), _risk(r)
        if p is not None and rk:
            rs.append(p / rk)
    return {
        "n": n,
        "win_rate": round(100 * wins / n),
        "avg_pts": round(mean(ps), 1),
        "avg_R": round(mean(rs), 2) if rs else None,
        "expectancy_R": round(mean(rs), 2) if rs else None,
    }


def _bucket_wr(rows, key, edges, labels):
    """Win-rate within numeric buckets of `key` (edges ascending)."""
    out = []
    for i, lab in enumerate(labels):
        lo = edges[i]
        hi = edges[i + 1] if i + 1 < len(edges) else float("inf")
        sub = []
        for r in rows:
            try:
                v = float(r.get(key))
            except Exception:
                continue
            if lo <= v < hi:
                sub.append(r)
        w = _wr(sub)
        out.append({"bucket": lab, **(w or {"n": 0, "win_rate": None})})
    return out


def _group_wr(rows, key):
    groups: Dict[str, List] = {}
    for r in rows:
        g = r.get(key)
        if g is None:
            continue
        groups.setdefault(str(g), []).append(r)
    out = []
    for g, sub in sorted(groups.items()):
        w = _wr(sub)
        if w:
            out.append({"group": g, **w})
    return out


def _quality_quadrant(resolved):
    """Process vs outcome — reuses the logged Trade-Quality grade (A+/A = high
    quality). Separates 'good trade, bad result' from 'lucky win'."""
    q = {"hi_win": 0, "hi_loss": 0, "lo_win": 0, "lo_loss": 0}
    seen = 0
    for r in resolved:
        g = r.get("layer_grade")
        p = _pts(r)
        if g is None or p is None:
            continue
        seen += 1
        hi = g in ("A+", "A")
        win = p > 0
        q[("hi_" if hi else "lo_") + ("win" if win else "loss")] += 1
    if seen == 0:
        return None
    return {
        "n": seen, **q,
        # trades worth keeping (good process) vs worth NOT reinforcing (luck)
        "good_process_bad_result": q["hi_loss"],
        "lucky_wins": q["lo_win"],
        "note": ("high-grade losers = keep taking · low-grade winners = don't "
                 "reinforce (luck, not skill)"),
    }


def _layer_contribution(resolved):
    """Per layer: WR when it AGREED with the trade vs when it did not. The
    delta is the layer's observational 'contribution'. Needs logged leans."""
    out = []
    for key in _LAYER_KEYS:
        agree, disagree = [], []
        for r in resolved:
            leans = r.get("layer_leans")
            if isinstance(leans, str):
                try:
                    import json as _json
                    leans = _json.loads(leans)
                except Exception:
                    leans = None
            if not isinstance(leans, dict):
                continue
            lean = leans.get(key)
            side = r.get("side")
            ls = 1 if lean == "BULL" else (-1 if lean == "BEAR" else 0)
            ss = 1 if side == "CALL" else (-1 if side == "PUT" else 0)
            if ls == 0 or ss == 0:
                continue
            (agree if ls == ss else disagree).append(r)
        wa, wd = _wr(agree), _wr(disagree)
        if wa and wa["n"] >= 8:
            out.append({
                "layer": key,
                "agree_wr": wa["win_rate"], "agree_n": wa["n"],
                "against_wr": wd["win_rate"] if wd else None,
                "against_n": wd["n"] if wd else 0,
                "contribution": (wa["win_rate"] - wd["win_rate"]) if wd else None,
            })
    out.sort(key=lambda r: (r["contribution"] is None, -(r["contribution"] or 0)))
    return out


def build_validation_report(rows: List[Dict[str, Any]],
                            shadow: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Aggregate closed-trade rows into the system scorecard."""
    resolved = [r for r in (rows or []) if r.get("exit_reason")]
    n = len(resolved)
    head = _wr(resolved)
    level = 3 if n >= _L3 else (2 if n >= _L2 else 1)

    # exit-reason mix + reversal save-rate
    reasons: Dict[str, int] = {}
    for r in resolved:
        reasons[r.get("exit_reason", "?")] = reasons.get(r.get("exit_reason", "?"), 0) + 1
    # Guardian "save": a REVERSED/ SWEPT exit that got out ABOVE the full stop
    saved = tot_rev = 0
    for r in resolved:
        if r.get("exit_reason") in ("REVERSED", "SWEPT"):
            tot_rev += 1
            p, rk = _pts(r), _risk(r)
            if p is not None and rk and p > -rk:      # better than a full stop-out
                saved += 1
    guardian_save_rate = round(100 * saved / tot_rev) if tot_rev else None

    # false-gate: hit invalidation with almost no favourable excursion
    false_gate = tot_inval = 0
    for r in resolved:
        if r.get("exit_reason") == "INVALIDATED":
            tot_inval += 1
            try:
                if float(r.get("mfe", 0) or 0) < 10:
                    false_gate += 1
            except Exception:
                pass
    false_gate_rate = round(100 * false_gate / tot_inval) if tot_inval else None

    # MAE of winners (validates the noise band)
    win_mae = []
    for r in resolved:
        p = _pts(r)
        if p is not None and p > 0:
            try:
                win_mae.append(abs(float(r.get("mae", 0) or 0)))
            except Exception:
                pass
    mae_stats = None
    if win_mae:
        mae_stats = {"n": len(win_mae), "avg": round(mean(win_mae), 1),
                     "median": round(median(win_mae), 1), "max": round(max(win_mae), 1)}

    sufficient = n >= _MIN_TRADES
    notes = []
    if level == 1:
        notes.append(f"Level 1 ({n}/{_L2} trades) — win-rate/expectancy only; "
                     f"breakdowns unlock at {_L2}. Insufficient data for tuning.")
    elif level == 2:
        notes.append(f"Level 2 ({n} trades) — breakdowns unlocked; "
                     f"layer-contribution + re-weighting unlock at {_L3}.")
    else:
        notes.append(f"Level 3 ({n} trades) — full analysis unlocked; "
                     f"tune ONE threshold at a time and log the change.")

    # Level 2+ analyses (breakdowns need a real sample); Level 3 (contribution)
    _l2 = level >= 2
    _l3 = level >= 3
    return {
        "n": n,
        "level": level,
        "sufficient": sufficient,
        "headline": head,
        # ── Level 2 (30+) ──
        "by_grade": _group_wr(resolved, "layer_grade") if _l2 else None,
        "by_side": _group_wr(resolved, "side") if _l2 else None,
        "by_zone": _group_wr(resolved, "zone_type") if _l2 else None,
        "by_regime": _group_wr(resolved, "regime") if _l2 else None,
        "by_strength": (_bucket_wr(resolved, "strength", [0, 45, 55, 65],
                                   ["<45", "45–55", "55–65", "65+"]) if _l2 else None),
        "by_rr": (_bucket_wr(resolved, "rr", [0, 1.5, 2.0, 3.0],
                             ["<1.5", "1.5–2", "2–3", "3+"]) if _l2 else None),
        "quality_quadrant": _quality_quadrant(resolved) if _l2 else None,
        "winner_mae": mae_stats if _l2 else None,
        # ── always-on system health ──
        "exit_mix": reasons,
        "guardian_save_rate": guardian_save_rate,
        "false_gate_rate": false_gate_rate,
        # ── Level 3 (100+) ──
        "layer_contribution": _layer_contribution(resolved) if _l3 else None,
        "layers": ((shadow or {}).get("accuracy") if shadow else None) if _l3 else None,
        "notes": notes,
        "disclaimer": "evaluates the SYSTEM (gate + guardian), not the market — "
                      "raw signal edge, independent of your discretionary fills",
    }
