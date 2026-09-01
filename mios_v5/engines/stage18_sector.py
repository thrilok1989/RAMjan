"""Stage 18 — Sector Rotation Engine (macro context).

Institutions don't buy "NIFTY" — they buy and sell sectors; NIFTY is the
weighted result of those sector flows. This engine reads the app's sector
snapshot (`raw["sector_rotation"]`) and turns it into a breadth + leadership +
risk-on/off context lean.

It is a CONTEXT engine, never an execution trigger, and it is SELF-AWARE about
its own (Yahoo-sourced, ~15-min-delayed) data. It votes only when the data is
trustworthy and otherwise stands aside as NEUTRAL:

    • coverage < _MIN_SECTORS (of 11)          → NEUTRAL, not voting
    • snapshot older than _MAX_STALE_MIN        → NEUTRAL, not voting
    • no snapshot / fetch failed                → NEUTRAL, not voting

Even when it votes, the Conflict Engine gives it a low weight (~1.5) so a weak
data source can never overpower Order Flow / Dealer / Zone Lifecycle.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

_MIN_SECTORS = 8          # of 11 — below this, breadth isn't trustworthy
_MAX_STALE_MIN = 20.0     # snapshot older than this → stand aside

_CYCLICALS = {"AUTO", "METAL", "REALTY", "BANK", "ENERGY", "INFRA", "PSU BANK"}
_DEFENSIVES = {"PHARMA", "FMCG", "IT", "MEDIA"}


def _stale_minutes(fetched_at) -> float | None:
    if not fetched_at:
        return None
    try:
        ts = datetime.fromisoformat(str(fetched_at))
        now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        return max(0.0, (now - ts).total_seconds() / 60.0)
    except Exception:
        return None


def _stars(reliability: float) -> str:
    n = max(0, min(5, int(round(reliability / 20.0))))
    return "★" * n + "☆" * (5 - n)


class SectorRotationEngine(Engine):
    name = "stage18_sector"
    stage = 18
    deps = ["stage00_health"]

    def _stand_aside(self, reason, coverage=0, stale=None):
        data = {"voting": False, "coverage": coverage, "risk_mode": "—",
                "stale_min": round(stale, 1) if stale is not None else None,
                "reliability": 0, "stars": _stars(0)}
        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE, confidence=0.0,
            evidence=[f"Sector rotation not voting — {reason}"],
            data=data, provenance=A.prov("yfinance:sectors", Tier.RESTING))

    def compute(self, state: MarketState) -> EngineResult:
        sr = state.raw.get("sector_rotation")
        if not isinstance(sr, dict) or not sr.get("all"):
            return self._stand_aside("no sector snapshot yet")

        rows = [r for r in (sr.get("all") or []) if isinstance(r, dict)]
        coverage = len(rows)
        stale = _stale_minutes(sr.get("fetched_at"))

        # ── quality gate ──
        if coverage < _MIN_SECTORS:
            return self._stand_aside(f"thin coverage {coverage}/11", coverage, stale)
        if stale is not None and stale > _MAX_STALE_MIN:
            return self._stand_aside(f"stale ({stale:.0f} min old)", coverage, stale)

        # ── breadth ──
        up = sum(1 for r in rows if float(r.get("day_chg_pct", 0) or 0) > 0)
        down = coverage - up
        breadth_pct = round(up / coverage * 100)
        breadth_lbl = ("Broad participation" if breadth_pct >= 65 else
                       "Narrow rally" if breadth_pct >= 50 else
                       "Broad weakness" if breadth_pct <= 35 else "Mixed")

        # ── leadership + risk mode (from the top-3 leaders) ──
        leaders = [r.get("name") for r in (sr.get("leading") or []) if r.get("name")]
        top = set(leaders[:3])
        cyc = len(top & _CYCLICALS)
        deff = len(top & _DEFENSIVES)
        rb = str(sr.get("rotation_bias", "")).upper()
        if "RISK-ON" in rb or cyc >= 2:
            risk_mode, bias = "Risk-On", Bias.BULL
        elif "RISK-OFF" in rb or deff >= 2:
            risk_mode, bias = "Risk-Off", Bias.BEAR
        else:
            risk_mode, bias = "Mixed", Bias.NEUTRAL

        # breadth can strengthen or veto the lean
        if bias == Bias.BULL and breadth_pct < 45:
            bias, risk_mode = Bias.NEUTRAL, "Mixed (leaders up, breadth weak)"
        if bias == Bias.BEAR and breadth_pct > 55:
            bias, risk_mode = Bias.NEUTRAL, "Mixed (defensives up, breadth firm)"

        # ── confidence — low by design (context engine), scaled by conviction
        # (how far breadth is from 50) and data reliability. Never high. ──
        reliability = min(100.0, (coverage / 11.0) * 100.0
                          * (1.0 if stale is None else max(0.4, 1.0 - stale / 40.0)))
        conviction = abs(breadth_pct - 50) / 50.0            # 0..1
        confidence = 0.0 if bias == Bias.NEUTRAL else round(
            min(50.0, 20.0 + 30.0 * conviction) * reliability / 100.0)

        lead_txt = ", ".join(leaders[:3]) or "—"
        evidence = [
            f"{risk_mode} · {breadth_lbl} ({up}/{coverage} sectors up)",
            f"Leadership: {lead_txt}",
        ]
        if stale is not None:
            evidence.append(f"freshness {stale:.0f} min · coverage {coverage}/11 "
                            f"· reliability {_stars(reliability)}")
        risks, opps = [], []
        if bias in (Bias.BULL, Bias.STRONG_BULL):
            opps.append(f"Money rotating into {lead_txt} — broad participation supports "
                        "the bullish backdrop (slow institutional context, not a trigger)")
        elif bias in (Bias.BEAR, Bias.STRONG_BEAR):
            risks.append(f"Defensives ({lead_txt}) leading while cyclicals lag — "
                         "institutions look defensive (slow context; real-time flow rules)")

        return EngineResult(
            engine=self.name, status=Status.OK, bias=bias, confidence=confidence,
            evidence=evidence, risks=risks, opportunities=opps,
            data={"voting": bias != Bias.NEUTRAL, "risk_mode": risk_mode,
                  "breadth_pct": breadth_pct, "breadth_label": breadth_lbl,
                  "up": up, "down": down, "coverage": coverage,
                  "leaders": leaders[:3], "stale_min": round(stale, 1) if stale is not None else None,
                  "reliability": round(reliability), "stars": _stars(reliability)},
            provenance=A.prov("yfinance:sectors(~15m delayed)", Tier.RESTING),
        )
