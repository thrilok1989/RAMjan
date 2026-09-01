"""Stage 35 — Reaction Zone Engine ⭐ (the keystone).

Predict where price is most likely to react and who wins the battle there.
Consumes: the S/R levels + OI walls from `_market_picture`, the S/R strength
+ breakout/breakdown probabilities from `_full_market_read`, and the
directional read from the dealer / intent / order-flow / probability engines.

Outputs a Reaction Map:
    strong/near support & resistance, the active BATTLE ZONE (the level spot
    is contesting now), the EXPECTED WINNER (buyers vs sellers), bounce /
    rejection / breakout / breakdown %, next target, and the invalidation
    (stop) level.

No BUY/SELL — it states the probabilistic reaction and the level where the
read fails, and leaves the decision to the trader.
"""

from __future__ import annotations

from typing import Optional

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

#: within this % of a level, spot is "at" the zone (active battle)
_AT_ZONE_PCT = 0.35


def _dir_score(state: MarketState) -> float:
    """Blended directional lean in [-1, 1] from the directional engines,
    weighted by their confidence."""
    weights = {"stage25_intent": 2.0, "stage14_orderflow": 1.5,
               "stage11_dealer": 1.5, "stage31_probability": 1.0}
    num = den = 0.0
    for eng, w in weights.items():
        r = state.get(eng)
        if r is None or not r.ok:
            continue
        sign = A.bias_sign(r.bias)
        num += w * (sign / 2.0) * (r.confidence / 100.0 if r.confidence else 0.4)
        den += w
    return (num / den) if den else 0.0


def _clamp(x: float, lo: float = 5.0, hi: float = 95.0) -> float:
    return max(lo, min(hi, x))


def _structure_factor(state: MarketState) -> float:
    """Multiplier in [0.7, 1.0] from Stage 2's Structure Score — a battle at
    a location Stage 2 rates as low-conviction shouldn't read as confidently
    as one at a location it flags HIGH QUALITY. 1.0 (no temper) when Stage 2
    hasn't computed yet — never fabricate certainty from a missing input."""
    s2 = state.get("stage02_structure")
    if s2 is None or not s2.ok or s2.data.get("structure_score") is None:
        return 1.0
    score = float(s2.data["structure_score"])
    return 0.7 + 0.3 * (score / 100.0)


class ReactionZoneEngine(Engine):
    name = "stage35_reaction_zone"
    stage = 35
    deps = ["stage02_structure", "stage11_dealer", "stage25_intent",
            "stage14_orderflow", "stage12_options", "stage31_probability"]

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        spot = raw.get("spot")
        m = A.mp(raw)
        f = A.fmr(raw)
        if not spot or not m:
            return EngineResult.neutral(
                self.name, "spot / levels not available yet",
                data_source="session:_market_picture")

        sup = m.get("sup") or {}
        res = m.get("res") or {}
        oi_floor = m.get("oi_floor")        # (strike, OI_L)
        oi_ceiling = m.get("oi_ceiling")
        support_price = sup.get("price") or (oi_floor[0] if oi_floor else None)
        resist_price = res.get("price") or (oi_ceiling[0] if oi_ceiling else None)
        sup_sources = sup.get("sources")
        res_sources = res.get("sources")
        # Stage-3 memory levels join the candidate set: previous-day low is a
        # support candidate, previous-day high a resistance candidate — the
        # market-tested prev-day extremes are among the most-respected real
        # levels. Nearest level to spot on each side wins.
        mem = state.raw.get("market_memory") or {}
        pdl, pdh = mem.get("prev_low"), mem.get("prev_high")
        if pdl and pdl < spot and (support_price is None or pdl > support_price):
            support_price, sup_sources = float(pdl), ["PDL"]
        if pdh and pdh > spot and (resist_price is None or pdh < resist_price):
            resist_price, res_sources = float(pdh), ["PDH"]
        sup_strength = A.clamp_conf(f.get("support_strength"), 50)
        res_strength = A.clamp_conf(f.get("resistance_strength"), 50)

        # distances (as % of spot)
        d_sup = ((spot - support_price) / spot * 100) if support_price else None
        d_res = ((resist_price - spot) / spot * 100) if resist_price else None

        # which level is being contested?
        zone_type: Optional[str] = None
        zone_price: Optional[float] = None
        if d_sup is not None and d_res is not None:
            if abs(d_sup) <= abs(d_res) and abs(d_sup) <= _AT_ZONE_PCT:
                zone_type, zone_price = "SUPPORT", support_price
            elif abs(d_res) < abs(d_sup) and abs(d_res) <= _AT_ZONE_PCT:
                zone_type, zone_price = "RESISTANCE", resist_price
        elif d_sup is not None and abs(d_sup) <= _AT_ZONE_PCT:
            zone_type, zone_price = "SUPPORT", support_price
        elif d_res is not None and abs(d_res) <= _AT_ZONE_PCT:
            zone_type, zone_price = "RESISTANCE", resist_price

        dir_score = _dir_score(state)          # -1 (bear) .. +1 (bull)
        breakout = A.clamp_conf(f.get("breakout"), 50)

        data = {
            "spot": spot,
            "strong_support": support_price, "support_strength": round(sup_strength),
            "strong_resistance": resist_price, "resistance_strength": round(res_strength),
            "support_sources": sup_sources,
            "resistance_sources": res_sources,
        }
        evidence = []
        if support_price:
            evidence.append(f"🟢 Support ₹{support_price:.0f} "
                            f"(str {sup_strength:.0f}%, {d_sup:+.2f}%)")
        if resist_price:
            evidence.append(f"🔴 Resistance ₹{resist_price:.0f} "
                            f"(str {res_strength:.0f}%, {d_res:+.2f}%)")

        if zone_type is None:
            # mid-range: no active battle — report levels, low conviction
            data["battle_zone"] = None
            evidence.append("Spot in mid-range — no active battle zone")
            bias = (Bias.BULL if dir_score > 0.25 else
                    Bias.BEAR if dir_score < -0.25 else Bias.NEUTRAL)
            confidence = A.clamp_conf(abs(dir_score) * 60 * _structure_factor(state))
            return EngineResult(
                engine=self.name, status=Status.OK, bias=bias,
                confidence=confidence, evidence=evidence,
                data=data, provenance=A.prov("mios:reaction_zone", Tier.DERIVED))

        # ── active battle at a level ────────────────────────────────
        if zone_type == "SUPPORT":
            # buyers defend; directional lean up helps the bounce
            bounce = _clamp(50 + 0.5 * (sup_strength - 50) + 35 * dir_score)
            breakdown = 100 - bounce
            if bounce >= 55:
                winner, bias = "Buyers (bounce)", Bias.BULL
            elif bounce <= 45:
                winner, bias = "Sellers (breakdown)", Bias.BEAR
            else:
                winner, bias = "Contested", Bias.NEUTRAL
            next_target = resist_price if bias == Bias.BULL else (
                round(zone_price * 0.995) if zone_price else None)
            invalidation = round(zone_price * 0.997) if zone_price else None
            probs = {"bounce": round(bounce), "breakdown": round(breakdown)}
            buyer_str, seller_str = round(sup_strength), round(100 - sup_strength)
        else:  # RESISTANCE
            rejection = _clamp(50 + 0.5 * (res_strength - 50) - 35 * dir_score)
            brk = 100 - rejection
            if rejection >= 55:
                winner, bias = "Sellers (rejection)", Bias.BEAR
            elif rejection <= 45:
                winner, bias = "Buyers (breakout)", Bias.BULL
            else:
                winner, bias = "Contested", Bias.NEUTRAL
            next_target = support_price if bias == Bias.BEAR else (
                round(zone_price * 1.005) if zone_price else None)
            invalidation = round(zone_price * 1.003) if zone_price else None
            probs = {"rejection": round(rejection), "breakout": round(brk)}
            seller_str, buyer_str = round(res_strength), round(100 - res_strength)

        # session-conviction temper (Stage 6) + structure-quality temper (Stage 2)
        tc = state.get("stage06_timecycle")
        conv = (tc.data.get("conviction") if tc and tc.data else 60) or 60
        margin = max(probs.values()) - 50
        confidence = A.clamp_conf(margin * 2 * (0.6 + 0.4 * conv / 100) * _structure_factor(state))

        data.update({
            "battle_zone": {"type": zone_type, "price": zone_price},
            "expected_winner": winner,
            "buyer_strength": buyer_str, "seller_strength": seller_str,
            "probabilities": probs,
            "next_target": next_target, "invalidation": invalidation,
            "dir_score": round(dir_score, 2),
        })
        _pstr = " · ".join(f"{k} {v}%" for k, v in probs.items())
        evidence.append(f"⚔️ Battle @ {zone_type} ₹{zone_price:.0f} → "
                        f"expected winner: {winner} ({_pstr})")
        if next_target:
            evidence.append(f"🎯 Next target ₹{next_target:.0f} · "
                            f"invalidation ₹{invalidation:.0f}")
        s2 = state.get("stage02_structure")
        if s2 is not None and s2.ok and s2.data.get("price_location"):
            evidence.append(f"Stage 2 structure: {s2.data['price_location']} "
                            f"({s2.data.get('structure_score', 0):.0f}%)")
        risks = []
        if winner == "Contested":
            risks.append("Battle contested (~50/50) — no edge, wait for a break")
        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=confidence, evidence=evidence, risks=risks,
            data=data, provenance=A.prov("mios:reaction_zone", Tier.DERIVED))
