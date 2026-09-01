"""Stage 17 — Liquidity Engine (pools + walls).

Where the fuel sits. Two kinds of liquidity, both inferable from executed
data (no L2 needed):
  • WALLS — the heaviest OI strikes: the CE wall (resistance ceiling) and PE
            wall (support floor) dealers/writers defend.
  • POOLS — resting-stop shelves: equal highs/lows, PDH/PDL, round numbers.
            UNTOUCHED pools are magnets — price is drawn to them before
            reversing (liquidity grab).

Directional lean = the magnet pull: untapped liquidity above pulls price up,
untapped liquidity below pulls it down. Low-to-mid weight — liquidity says
WHERE price wants to go, not that it will right now. Reads
`market_picture` (oi walls + liq_pools); NEUTRAL when neither is present.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A


class LiquidityEngine(Engine):
    name = "stage17_liquidity"
    stage = 17
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        mp = A.mp(state.raw)
        spot = state.raw.get("spot") or mp.get("spot")
        floor = mp.get("oi_floor")      # (strike, OI_L) — PE wall = support
        ceiling = mp.get("oi_ceiling")  # (strike, OI_L) — CE wall = resistance
        pin = mp.get("oi_pin")
        pools = mp.get("liq_pools") or {}
        above = [p for p in (pools.get("above") or []) if not p.get("touched")]
        below = [p for p in (pools.get("below") or []) if not p.get("touched")]

        if not (floor or ceiling or above or below):
            return EngineResult.neutral(
                self.name, "no liquidity map yet (walls/pools warming up)",
                data_source="session:_market_picture.liq_pools")

        evidence, risks, opps = [], [], []

        # ── walls (context S/R) ──
        if ceiling:
            evidence.append(f"CE wall ₹{ceiling[0]:.0f} ({ceiling[1]:.1f}L) — "
                            "resistance ceiling above")
        if pin:
            evidence.append(f"🧲 Pin ₹{pin[0]:.0f} — magnet strike")
        if floor:
            evidence.append(f"PE wall ₹{floor[0]:.0f} ({floor[1]:.1f}L) — "
                            "support floor below")

        # ── pools (magnets) — nearest untapped each side ──
        na = above[0] if above else None
        nb = below[0] if below else None
        if na:
            evidence.append(f"Untapped liquidity above: ₹{na['price']:.0f} "
                            f"({na['kind']}) — upside magnet")
        if nb:
            evidence.append(f"Untapped liquidity below: ₹{nb['price']:.0f} "
                            f"({nb['kind']}) — downside magnet")

        # ── directional lean = net magnet pull ──
        # weight by count of untapped pools each side + wall size tilt
        pull = len(above) - len(below)
        # OI-wall tilt: a much bigger opposite wall = stronger draw toward the
        # thinner side (price seeks the path of least resistance / the fuel)
        if floor and ceiling:
            try:
                if ceiling[1] > floor[1] * 1.4:
                    pull -= 1          # heavy ceiling caps → downside pull
                elif floor[1] > ceiling[1] * 1.4:
                    pull += 1          # heavy floor holds → upside pull
            except (TypeError, IndexError):
                pass

        if pull >= 2:
            bias, conf = Bias.BULL, 52.0
            opps.append("Net untapped liquidity ABOVE — upside magnets; dips get "
                        "bought toward the pools")
        elif pull <= -2:
            bias, conf = Bias.BEAR, 52.0
            risks.append("Net untapped liquidity BELOW — downside magnets; bounces "
                         "sold toward the pools")
        elif pull == 1:
            bias, conf = Bias.BULL, 35.0
        elif pull == -1:
            bias, conf = Bias.BEAR, 35.0
        else:
            bias, conf = Bias.NEUTRAL, 25.0

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias,
            confidence=conf, evidence=evidence, risks=risks, opportunities=opps,
            data={
                "ce_wall": (ceiling[0] if ceiling else None),
                "pe_wall": (floor[0] if floor else None),
                "pin": (pin[0] if pin else None),
                "pools_above": above[:4],
                "pools_below": below[:4],
                "nearest_above": (na["price"] if na else None),
                "nearest_below": (nb["price"] if nb else None),
                "magnet_pull": pull,
            },
            provenance=A.prov("mios:liquidity(walls+pools)", Tier.EXECUTED),
        )
