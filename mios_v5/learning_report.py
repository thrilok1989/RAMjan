"""MIOS V6 — Phase 6 assembler: Stages 55-60 → one Dashboard-5 payload.

Kept pure and separate from the panel so the whole Learning Dashboard can be
built and asserted from plain lists of dicts, with no database and no Streamlit.
The caller fetches rows; this decides what they mean.

One ordering rule matters: **history arrives newest-first**, because every
rolling window in Stages 56 and 57 is a head slice. Feeding it oldest-first
would silently report the first thirty trades MIOS ever took as its current
form, which is exactly the kind of quiet wrongness a learning system must not
have.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from . import (attribution, calibration, contribution, engine_accuracy,
               false_signal, threshold_opt)


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _mean(vals) -> Optional[float]:
    xs = [x for x in (_f(v) for v in vals) if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def overall(results: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    rs = [r for r in (results or []) if r.get("outcome") in ("win", "loss")]
    wins = [r for r in rs if r["outcome"] == "win"]
    losses = [r for r in rs if r["outcome"] == "loss"]
    gw = sum(abs(_f(r.get("pnl_points")) or 0.0) for r in wins)
    gl = sum(abs(_f(r.get("pnl_points")) or 0.0) for r in losses)
    hold = _mean(r.get("holding_secs") for r in rs)
    return {
        "graded": len(rs), "wins": len(wins), "losses": len(losses),
        "win_rate": round(100.0 * len(wins) / len(rs), 1) if rs else None,
        "profit_factor": round(gw / gl, 2) if gl else None,
        "avg_mfe": _mean(r.get("mfe") for r in rs),
        "avg_mae": _mean(r.get("mae") for r in rs),
        "avg_hold_min": round(hold / 60.0, 1) if hold is not None else None,
        "expectancy": _mean(r.get("pnl_points") for r in rs),
    }


def build(engine_rows: Optional[Sequence[Dict[str, Any]]] = None,
          results: Optional[Sequence[Dict[str, Any]]] = None,
          trades: Optional[Sequence[Dict[str, Any]]] = None,
          events: Optional[Sequence[Dict[str, Any]]] = None,
          window: str = "last100") -> Dict[str, Any]:
    """The whole Learning Dashboard payload.

    All four inputs are newest-first lists of plain dicts:
    `engine_attribution`, `trade_results`, `trade_attribution`, `trade_events`.
    """
    joined = attribution.join_outcomes(engine_rows, results)

    acc = engine_accuracy.by_engine(joined)
    cal = calibration.by_engine(joined)
    contrib = contribution.by_engine(joined)

    # Stage 58 sweeps trade-level fields, so it needs the trade rows flattened
    # with their outcome rather than the per-engine rows.
    by_id = {str(r.get("signal_id")): r for r in (results or [])}
    flat: List[Dict[str, Any]] = []
    for t in (trades or []):
        res = by_id.get(str(t.get("signal_id")))
        if not res or res.get("outcome") not in ("win", "loss"):
            continue
        snap = t.get("snapshot") or {}
        flat.append({**{k: v for k, v in t.items() if k != "snapshot"},
                     **(snap if isinstance(snap, dict) else {}),
                     "outcome": res.get("outcome"),
                     "won": res.get("outcome") == "win",
                     "pnl_points": _f(res.get("pnl_points"))})
    thresholds = threshold_opt.optimise(flat)

    # Stage 60 investigates every loss individually
    ev_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for e in (events or []):
        ev_by_id.setdefault(str(e.get("signal_id")), []).append(e)
    rows_by_id: Dict[str, List[Dict[str, Any]]] = {}
    for r in (engine_rows or []):
        rows_by_id.setdefault(str(r.get("signal_id")), []).append(r)

    investigations = []
    trades_by_id = {str(t.get("signal_id")): t for t in (trades or [])}
    for res in (results or []):
        if res.get("outcome") != "loss":
            continue
        sid = str(res.get("signal_id"))
        investigations.append(false_signal.investigate(
            trades_by_id.get(sid) or {"signal_id": sid}, rows_by_id.get(sid),
            res, ev_by_id.get(sid)))

    return {
        "window": window,
        "overall": overall(results),
        "accuracy": acc,
        "rankings": engine_accuracy.rank(acc, window=window),
        "calibration": cal,
        "calibration_suggestions": calibration.suggestions(cal, window=window),
        "thresholds": thresholds,
        "contribution": contrib,
        "contribution_lines": contribution.explain(contrib),
        "false_signals": false_signal.analyse(investigations),
        "recent_losses": investigations[:5],
        # every consumer of this payload must be able to see, without reading
        # any code, that none of it is applied anywhere
        "advisory_only": True,
    }


def snapshot_rows(payload: Optional[Dict[str, Any]],
                  trading_day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Flatten the payload into append-only `learning_snapshots` rows.

    Learning conclusions are history too. Storing each run lets you ask what
    MIOS believed about itself last month and whether that was right — and it
    makes any future threshold change traceable to the snapshot that
    recommended it.
    """
    p = payload or {}
    window = p.get("window", "last100")
    out = []
    for stage, key, n in (
            ("accuracy", "rankings", len(p.get("rankings") or [])),
            ("calibration", "calibration_suggestions",
             len(p.get("calibration_suggestions") or [])),
            ("thresholds", "thresholds",
             len((p.get("thresholds") or {}).get("suggestions") or [])),
            ("contribution", "contribution",
             int((p.get("contribution") or {}).get("trades") or 0)),
            ("false_signal", "false_signals",
             int((p.get("false_signals") or {}).get("losses") or 0))):
        out.append({"stage": stage, "window_label": window,
                    "trading_day": trading_day, "sample_size": n,
                    "payload": p.get(key) or {}, "applied": False})
    return out
