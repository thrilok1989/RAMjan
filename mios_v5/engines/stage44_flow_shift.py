"""Stage 44 — Sudden Flow Shift + Stability ⚠️ (the interrupt).

Reads the DERIVATIVE of the tape, not its level: CVD/delta swing, OI velocity,
dealer-gamma repricing, IV jump, volume explosion, raw price displacement and
money-flow swing. When enough of them move at once, institutional flow has
shifted and every read computed a moment ago is describing a market that no
longer exists → **freeze entries, recalculate**.

Also owns market STABILITY (STABLE / UNSTABLE / SHOCK / RECOVERY) — the same
measurement on a slower clock, so it doesn't need a second engine.

Non-directional: returns Bias.NONE and never votes. A flow shift is not a
direction — it is a warning that direction is being repriced. It informs the
Decision Engine's veto gate; it does not lean.

v0 is OBSERVATIONAL: it logs and warns. Thresholds get tuned from the logged
data before this is allowed to block anything.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..flow_shift import detect_shift
from . import _adapters as A


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def flow_metrics(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract this cycle's flow metrics from the raw blackboard. Missing inputs
    stay missing — the detector skips what it can't see rather than guessing."""
    m: Dict[str, Any] = {}
    m["spot"] = _num(raw.get("spot"))

    # CVD / delta aggression (zone-reset summary preferred, same as Stage 28)
    vd = raw.get("volume_delta") or {}
    vds = (vd.get("zone_summary") if vd.get("zone_reset") else None) or vd.get("summary") or {}
    m["cvd_pct"] = _num(vds.get("delta_pct"))
    m["volume"] = _num(vds.get("total_volume")) or _num(vds.get("volume"))

    # total OI across the chain (positions being built / torn down)
    opt = raw.get("option_data") or {}
    for _k in ("total_oi", "oi_total"):
        if opt.get(_k) is not None:
            m["oi_total"] = _num(opt.get(_k))
            break
    else:
        fmr = raw.get("full_market_read") or {}
        m["oi_total"] = _num(fmr.get("total_oi"))

    # dealer gamma
    gex = raw.get("gex_data") or {}
    m["gamma_net"] = _num(gex.get("net_gex"))

    # implied vol
    vix = raw.get("vix") or {}
    m["iv"] = _num(vix.get("value"))

    # money flow net
    mf = raw.get("money_flow") or {}
    m["mf_net"] = (_num(mf.get("net_flow")) if mf.get("net_flow") is not None
                   else _num(mf.get("total_delta")))
    return m


class FlowShiftEngine(Engine):
    name = "stage44_flow_shift"
    stage = 44
    deps = []          # reads raw only — must run even when other engines fail

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        cur = flow_metrics(raw)
        if cur.get("spot") is None:
            return EngineResult.neutral(
                self.name, "spot not available yet", data_source="session:flow")

        trace = raw.get("flow_trace") or []
        prev_state = raw.get("flow_stability_prev")
        try:
            since = int(raw.get("flow_cycles_since_shock") or 99)
        except (TypeError, ValueError):
            since = 99

        res = detect_shift(cur, trace, prev_state=prev_state, cycles_since_shock=since)

        evidence = [res["label"]]
        if res["signals"]:
            evidence.extend(s["label"] for s in res["signals"][:4])
        else:
            evidence.append("No abnormal velocity in CVD / OI / gamma / IV / volume")

        risks = []
        if res["freeze_entries"]:
            risks.append("⚠️ Institutional flow shift — freeze entries, recalculate; "
                         "reads taken before this moment are stale")
        elif res["stability"] == "RECOVERY":
            risks.append("Tape still settling after a shift — size down until it stabilises")

        # Status describes ENGINE health, not market health — a shocked tape is
        # a perfectly successful computation. The warning travels in data/risks,
        # so `.ok` stays True and the final read can still consume it.
        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(res["score"]), evidence=evidence, risks=risks,
            data={"metrics": cur, **res},
            provenance=A.prov("mios:flow_shift", Tier.DERIVED))
