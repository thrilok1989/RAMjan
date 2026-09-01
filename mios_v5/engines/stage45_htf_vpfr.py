"""Stage 45 — Higher-Timeframe VPFR ⭐ (the institutional big picture).

Six independent references — 1H · 4H · Daily · Weekly · Monthly · Yearly — each
with its own value area, volume nodes, market structure, value migration and
bias. Then compared, so MIOS knows whether today's move is happening *inside or
against* the larger structure.

It emits no buy/sell. It exists to make two other things reliable:
  • Stage 41 confluence — a zone backed by "Daily VAH + Weekly LVN + Monthly POC"
    earns its stars, instead of three intraday windows agreeing with themselves;
  • Stage 51 validity — a signal can finally be checked against real higher
    timeframes before it is taken.

The profiles are built by the app (which owns the candle series) and forwarded on
`raw["htf_profiles"]`, cached and recomputed only when the relevant bar closes —
recomputing a Yearly profile every tick would be absurd.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from ..htf_vpfr import (TIMEFRAMES, alignment, htf_levels, migration_summary,
                        tf_read)
from . import _adapters as A

_BIAS = {"BULL": Bias.BULL, "BEAR": Bias.BEAR, "NEUTRAL": Bias.NEUTRAL}


class HTFVpfrEngine(Engine):
    name = "stage45_htf_vpfr"
    stage = 45
    deps = []          # reads the forwarded profiles only

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        spot = raw.get("spot")
        profiles = raw.get("htf_profiles") or {}
        if not spot or not profiles:
            return EngineResult.neutral(
                self.name, "higher-timeframe profiles not built yet",
                data_source="session:_htf_profiles")

        reads: Dict[str, Any] = {}
        for tf in TIMEFRAMES:
            entry = profiles.get(tf) or {}
            if not entry.get("profile"):
                continue
            reads[tf] = tf_read(tf, spot, entry.get("profile"),
                                entry.get("structure"), entry.get("migration"))
        if not reads:
            return EngineResult.neutral(self.name, "no timeframe profiles yet")

        al = alignment(reads)
        mig = migration_summary(reads)
        levels = htf_levels(reads)

        evidence = [f"Institutional alignment {al['stars']} · {al['label']}"]
        for tf in TIMEFRAMES:
            r = reads.get(tf)
            if not r or r["status"] != "OK":
                continue
            em = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}[r["bias"]]
            loc = f" · {r['location']}" if r.get("location") else ""
            evidence.append(f"{em} {tf} {r['bias']}{loc}")
        evidence.append(f"Value migration — short {mig['short']} · "
                        f"medium {mig['medium']} · long {mig['long']}")

        risks = []
        if al["disagree"]:
            risks.append("Higher timeframes disagree: " + ", ".join(al["disagree"])
                         + " — intraday signals against them are lower-quality")
        if mig["short"] != mig["long"] and "?" not in (mig["short"], mig["long"]):
            risks.append(f"Short-term value {mig['short']} inside a long-term "
                         f"{mig['long']} market — counter-trend context")

        return EngineResult(
            engine=self.name, status=Status.OK,
            bias=_BIAS.get(al["bias"], Bias.NEUTRAL),
            confidence=float(al["score"]), evidence=evidence, risks=risks,
            data={"reads": reads, "alignment": al, "migration": mig,
                  "levels": levels, "n_timeframes": len(reads)},
            provenance=A.prov("mios:htf_vpfr", Tier.RESTING))
