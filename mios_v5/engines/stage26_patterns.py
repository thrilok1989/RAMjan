"""Stage 26 — Pattern Alignment Engine.

Patterns have NO fixed meaning — the same candle/chart pattern is a
continuation, a reversal, or a TRAP depending on context. This engine takes
the patterns the app already detects (chart + candle, via Stage 2 structure)
and interprets them THROUGH:

  • LOCATION   — is the pattern at a support/resistance zone? (Stage 2)
  • TREND      — with the trend (continuation) or against it (reversal)?
  • DAY CONTEXT— Stage 4: long-gamma pin day favours REVERSALS at the edges
                 (mean-reversion); trend / gamma-unwind days favour
                 CONTINUATION and turn counter-trend reversals into TRAPS.
  • ORDER FLOW — does CVD / order-flow (Stage 14) confirm the pattern's lean?

Output: an aligned read (CONTINUATION / REVERSAL / TRAP / FORMING) + a bias
scaled by how many context factors agree. This is a FRAMEWORK with
conservative starting weights — the intent is to tune the pattern weights
from logged outcomes (bias_predictions / alert_log) rather than textbook
theory. Non-triggering when no pattern is present.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

# keyword → directional lean for pattern-name strings (case-insensitive)
_BULL_KEYS = ("bullish", "hammer", "morning star", "piercing", "white soldier",
              "dragonfly", "tweezer bottom", "double bottom", "inverse head",
              "ascending triangle", "bull flag", "cup", "falling wedge",
              "rounding bottom", "higher low")
_BEAR_KEYS = ("bearish", "shooting star", "hanging man", "evening star",
              "dark cloud", "black crow", "gravestone", "tweezer top",
              "double top", "head and shoulders", "descending triangle",
              "bear flag", "rising wedge", "rounding top", "lower high")
_NEUTRAL_KEYS = ("doji", "spinning top", "harami", "inside", "indecision")


def _pattern_lean(name) -> int:
    """+1 bull / -1 bear / 0 neutral-or-none from a pattern-name string."""
    if not name:
        return 0
    s = str(name).strip().lower()
    if not s or s in ("none", "n/a", "-"):
        return 0
    # bearish 'engulfing' vs bullish 'engulfing' — the bull/bear word decides
    if "bear" in s:
        return -1
    if "bull" in s:
        return 1
    for k in _NEUTRAL_KEYS:
        if k in s:
            return 0
    for k in _BULL_KEYS:
        if k in s:
            return 1
    for k in _BEAR_KEYS:
        if k in s:
            return -1
    return 0


class PatternAlignmentEngine(Engine):
    name = "stage26_patterns"
    stage = 26
    deps = ["stage00_health", "stage02_structure", "stage04_context",
            "stage14_orderflow"]

    def compute(self, state: MarketState) -> EngineResult:
        ms = state.raw.get("market_structure") or {}
        chart = ms.get("chart_pattern")
        candle = ms.get("candle_pattern")
        c_lean = _pattern_lean(chart)
        k_lean = _pattern_lean(candle)

        # combined raw lean (chart weighted a touch higher than a single candle)
        raw_score = 1.5 * c_lean + 1.0 * k_lean
        raw_lean = 1 if raw_score > 0 else (-1 if raw_score < 0 else 0)
        if raw_lean == 0:
            return EngineResult.neutral(
                self.name,
                "no directional pattern detected this cycle"
                if not (chart or candle) else
                f"pattern(s) indecisive (chart={chart}, candle={candle})",
                data_source="session:_market_structure")

        # ── context inputs ──
        trend = str(ms.get("trend", "") or "")
        loc = str(ms.get("price_location", "") or "")
        demand_supply = str(ms.get("demand_supply", "") or "")
        trend_up = "up" in trend.lower()
        trend_dn = "down" in trend.lower()
        at_support = "support" in loc.lower() or demand_supply.lower() == "demand"
        at_resist = "resist" in loc.lower() or demand_supply.lower() == "supply"

        ctx = state.get("stage04_context")
        day_type = (ctx.data.get("day_type") if ctx and ctx.ok and ctx.data else "") or ""
        pin_day = day_type in ("EXPIRY · PIN", "PIN / RANGE")
        trend_day = day_type in ("TREND", "EXPIRY · GAMMA UNWIND", "GAP-UP", "GAP-DOWN")

        of = state.get("stage14_orderflow")
        flow_sign = A.bias_sign(of.bias) if of and of.ok else 0

        # ── alignment scoring ──
        continuation = (trend_up and raw_lean > 0) or (trend_dn and raw_lean < 0)
        counter_trend = (trend_up and raw_lean < 0) or (trend_dn and raw_lean > 0)
        loc_supports = (raw_lean > 0 and at_support) or (raw_lean < 0 and at_resist)
        loc_fights = (raw_lean > 0 and at_resist) or (raw_lean < 0 and at_support)
        flow_confirms = (flow_sign > 0 and raw_lean > 0) or (flow_sign < 0 and raw_lean < 0)
        flow_against = (flow_sign > 0 and raw_lean < 0) or (flow_sign < 0 and raw_lean > 0)

        score = 0
        why = []
        if continuation:
            score += 1; why.append("with the trend")
        if loc_supports:
            score += 1; why.append("at the right zone")
        if loc_fights:
            score -= 1; why.append("fighting the zone")
        if flow_confirms:
            score += 1; why.append("order flow confirms")
        if flow_against:
            score -= 1; why.append("order flow AGAINST")
        # day-context modifier
        if pin_day and counter_trend and loc_supports:
            score += 1; why.append("pin day favours mean-reversion here")
        if trend_day and continuation:
            score += 1; why.append("trend day favours continuation")
        trap = trend_day and counter_trend and (flow_against or not loc_supports)
        if trap:
            score -= 1; why.append("trend/unwind day — counter-trend = TRAP risk")

        # ── classify ──
        _dir = "bullish" if raw_lean > 0 else "bearish"
        _pats = " + ".join([p for p in (chart, candle) if p and _pattern_lean(p)])
        if trap:
            aligned_read = "TRAP"
            bias = Bias.NEUTRAL
            conf = 30.0
        elif continuation and score >= 2:
            aligned_read = "CONTINUATION"
            bias = A.bias_from_net(raw_lean * (2 + score), strong=5, weak=1)
            conf = min(45.0 + 8.0 * score, 78.0)
        elif counter_trend and loc_supports and score >= 1:
            aligned_read = "REVERSAL"
            bias = Bias.BULL if raw_lean > 0 else Bias.BEAR
            conf = min(40.0 + 7.0 * score, 68.0)
        elif score >= 1:
            aligned_read = "CONTINUATION" if continuation else "REVERSAL"
            bias = Bias.BULL if raw_lean > 0 else Bias.BEAR
            conf = 38.0
        else:
            aligned_read = "FORMING"
            bias = Bias.NEUTRAL
            conf = 25.0

        evidence = [f"{_dir.title()} pattern ({_pats or '—'}) → {aligned_read}"
                    + (f": {', '.join(why)}" if why else "")]
        risks, opps = [], []
        if aligned_read == "TRAP":
            risks.append(f"{_dir.title()} {_pats} looks tempting but it's counter-"
                         "trend on a trend/unwind day with flow against — high "
                         "trap risk; do NOT take it")
        elif aligned_read == "CONTINUATION":
            opps.append(f"{_pats} confirms the {'up' if raw_lean > 0 else 'down'}"
                        "trend — continuation entry with the flow")
        elif aligned_read == "REVERSAL":
            opps.append(f"{_pats} at the zone with confirmation — reversal setup; "
                        "still wants a trigger candle")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=conf, evidence=evidence, risks=risks, opportunities=opps,
            data={
                "chart_pattern": chart, "candle_pattern": candle,
                "raw_lean": _dir, "aligned_read": aligned_read,
                "agreement_score": score, "at_support": at_support,
                "at_resistance": at_resist, "day_type": day_type,
                "flow_confirms": flow_confirms,
            },
            provenance=A.prov("mios:patterns×context", Tier.DERIVED),
        )
