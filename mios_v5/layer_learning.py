"""MIOS V5 — SHADOW layer-weight learning (parallel, non-live).

This learns, from graded trade outcomes, how much each perception layer
*actually* deserves to be weighted — but it runs **in parallel** and never
mutates the live scorecard. It answers: "if we re-weighted the layers by how
often each one was right, what would the read look like?" so you can compare
the learned weighting against the fixed one BEFORE ever trusting it live.

Per layer, over graded trades:
  a layer was RIGHT when (it leaned the trade's direction) == (the trade won).
  accuracy = right / (rows where the layer had a direction)
  shadow multiplier = clamp(accuracy / 0.5, 0.4, 1.8)   # 50% ⇒ ×1.0 (neutral)
  shadow weight = base_weight × multiplier, renormalised to sum 1.0

Layers with too few samples keep their base weight. Below a minimum total the
learner reports "insufficient" and returns the base weights unchanged. Pure
(no Streamlit / no DB) so it is unit-testable and safe.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .layer_scores import _LAYERS

_MIN_TOTAL = 10        # graded trades needed before shadow weights mean anything
_MIN_PER_LAYER = 8     # per-layer samples needed to move that layer's weight


def base_weights() -> Dict[str, float]:
    """The fixed priority-ladder weights the live scorecard uses."""
    return {key: weight for key, _label, weight, _e in _LAYERS}


def _labels() -> Dict[str, str]:
    return {key: label for key, label, _w, _e in _LAYERS}


def build_shadow_weights(graded: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Learn shadow weights from graded rows.

    Each row: {"leans": {layer_key: "BULL"/"BEAR"/"NEUTRAL"/"N/A"},
               "side": "CALL"/"PUT", "win": bool}
    """
    base = base_weights()
    labels = _labels()
    right: Dict[str, int] = {k: 0 for k in base}
    total: Dict[str, int] = {k: 0 for k in base}

    for row in graded or []:
        side = row.get("side")
        win = bool(row.get("win"))
        side_sign = 1 if side == "CALL" else (-1 if side == "PUT" else 0)
        if side_sign == 0:
            continue
        leans = row.get("leans") or {}
        for key in base:
            lean = leans.get(key)
            lean_sign = 1 if lean == "BULL" else (-1 if lean == "BEAR" else 0)
            if lean_sign == 0:            # NEUTRAL / N/A → layer made no call
                continue
            total[key] += 1
            agreed = (lean_sign == side_sign)
            if agreed == win:             # right when agreement matched outcome
                right[key] += 1

    n = len(graded or [])
    accuracy: Dict[str, Any] = {}
    mult: Dict[str, float] = {}
    for key in base:
        if total[key] >= _MIN_PER_LAYER:
            acc = right[key] / total[key]
            accuracy[key] = round(100 * acc)
            m = acc / 0.5
            mult[key] = max(0.4, min(1.8, m))
        else:
            accuracy[key] = None          # not enough data → no change
            mult[key] = 1.0

    raw = {k: base[k] * mult[k] for k in base}
    tot = sum(raw.values()) or 1.0
    shadow = {k: round(raw[k] / tot, 4) for k in base}

    sufficient = n >= _MIN_TOTAL and any(a is not None for a in accuracy.values())
    notes: List[str] = []
    if not sufficient:
        notes.append(f"learning — {n}/{_MIN_TOTAL} graded trades logged "
                     f"(need ≥{_MIN_PER_LAYER} per layer to re-weight it); "
                     f"self-populates going forward")
        shadow = dict(base)               # don't pretend until there's data

    return {
        "n": n,
        "sufficient": sufficient,
        "base": base,
        "shadow": shadow,
        "accuracy": accuracy,
        "multiplier": {k: round(mult[k], 2) for k in base},
        "samples": total,
        "labels": labels,
        "notes": notes,
        "disclaimer": "SHADOW weights — parallel/what-if, they do NOT drive the "
                      "live scorecard",
    }


def weight_delta_table(sw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rows for a base-vs-shadow comparison table (largest change first)."""
    base, shadow = sw["base"], sw["shadow"]
    labels, acc, samples = sw["labels"], sw["accuracy"], sw["samples"]
    rows = []
    for k in base:
        rows.append({
            "layer": labels.get(k, k),
            "base": round(100 * base[k]),
            "shadow": round(100 * shadow[k]),
            "delta": round(100 * (shadow[k] - base[k])),
            "accuracy": acc.get(k),
            "samples": samples.get(k, 0),
        })
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows
