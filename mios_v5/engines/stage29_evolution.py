"""Stage 29 — Market Evolution Engine.

Track how the market is changing in real time by diffing this pass against the
previous one. The runner stashes a compact snapshot of key engine outputs each
pass and forwards the prior snapshot in `raw['prev_snapshot']`; this engine
reports what flipped — regime, dealer gamma, dominant bias, gamma-blast,
institution score, reaction-zone winner — as a "what changed" list that feeds
the briefing channel (shift alerts).

`bias = NONE` — it reports change, not direction.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


def snapshot_of(state: MarketState) -> Dict[str, Any]:
    """Compact snapshot the runner persists for next-pass diffing."""
    def g(name):
        r = state.get(name)
        return r if r is not None else None

    snap: Dict[str, Any] = {}
    for name in ("stage05_regime", "stage11_dealer", "stage25_intent",
                 "stage27_conflict", "stage35_reaction_zone",
                 "stage13_institutional"):
        r = g(name)
        if r is not None:
            snap[name] = {"bias": r.bias.value, "conf": r.confidence,
                          "data": dict(r.data)}
    return snap


class EvolutionEngine(Engine):
    name = "stage29_evolution"
    stage = 29
    deps = ["stage05_regime", "stage11_dealer", "stage25_intent",
            "stage27_conflict", "stage35_reaction_zone",
            "stage13_institutional"]

    def compute(self, state: MarketState) -> EngineResult:
        prev: Dict[str, Any] = state.raw.get("prev_snapshot") or {}
        changes: List[str] = []

        def _bias(name, snap):
            n = snap.get(name)
            return (n or {}).get("bias")

        def _data(name, snap, key):
            return ((snap.get(name) or {}).get("data") or {}).get(key)

        cur = snapshot_of(state)

        if not prev:
            return EngineResult(
                engine=self.name, status=Status.OK, bias=Bias.NONE,
                confidence=0.0,
                evidence=["Baseline captured — evolution tracks from next pass"],
                data={"changes": [], "n_changes": 0},
                provenance=A.prov("mios:evolution", Tier.DERIVED))

        # regime flip
        if _bias("stage05_regime", prev) and \
                _bias("stage05_regime", prev) != _bias("stage05_regime", cur):
            changes.append(f"🔄 Regime {_bias('stage05_regime', prev)} → "
                           f"{_bias('stage05_regime', cur)}")
        # dealer gamma flip (GEX sign)
        pg = _data("stage11_dealer", prev, "gex") or {}
        cg = _data("stage11_dealer", cur, "gex") or {}
        if pg.get("total") is not None and cg.get("total") is not None:
            if (pg["total"] < 0) != (cg["total"] < 0):
                changes.append(f"🧨 Dealer gamma flipped: {pg.get('signal')} → "
                               f"{cg.get('signal')} ({cg['total']:+.0f}L)")
        # dominant bias flip (conflict)
        if _bias("stage27_conflict", prev) and \
                _bias("stage27_conflict", prev) != _bias("stage27_conflict", cur):
            changes.append(f"⚖️ Dominant bias {_bias('stage27_conflict', prev)} → "
                           f"{_bias('stage27_conflict', cur)}")
        # institution score jump
        pi = _data("stage13_institutional", prev, "institution_score")
        ci = _data("stage13_institutional", cur, "institution_score")
        try:
            if pi is not None and ci is not None and abs(ci - pi) >= 20:
                changes.append(f"🏛 Institution score {pi:.0f} → {ci:.0f}")
        except (TypeError, ValueError):
            pass
        # reaction-zone winner change
        pw = _data("stage35_reaction_zone", prev, "expected_winner")
        cw = _data("stage35_reaction_zone", cur, "expected_winner")
        if pw and cw and pw != cw:
            changes.append(f"⚔️ Battle winner {pw} → {cw}")

        evidence = changes if changes else ["No material change since last pass"]
        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(min(len(changes) * 25, 100)),
            evidence=evidence[:8],
            data={"changes": changes, "n_changes": len(changes)},
            provenance=A.prov("mios:evolution", Tier.DERIVED),
        )
