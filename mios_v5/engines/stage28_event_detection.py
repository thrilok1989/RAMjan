"""Stage 28 — Event Detection Engine (surprise-reaction mirror of Stage 24).

Stage 24 spots the market *coiling* before something. This spots the *reaction*
when a surprise actually hits — war, a tariff headline, a shock RBI move: nobody
can predict the event, so the engine detects the REACTION, not the event.

Reads sudden shocks from data already computed:
  • VIX spike / crash        (raw["vix"].history — fast move either way)
  • Gamma blast              (full_market_read.gamma_blast == HIGH)
  • Order-flow shock (CVD)   (raw["volume_delta"] — extreme delta% / divergence)
  • News shock               (Stage 21 news — a STRONG sudden sentiment read)

It is a DETECTOR: Bias.NONE (it does not vote a direction into the Conflict
Engine — the real move is already carried by order flow / dealer), but it reports
the reaction's *direction* as data (selling vs short-covering) and fires a
"🚨 Breaking Event" flag. Like Stage 24 it never names the cause — that is the
job of a later news-explain layer. Market reacts; news explains.
"""

from __future__ import annotations

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

_VIX_SPIKE_PCT = 5.0       # % move over the recent window = a VIX shock
_CVD_EXTREME = 55.0        # |delta %| beyond this = an order-flow shock


def _vix_spike(vix_data):
    """(spike_pct, direction) over the last few readings, or (0, None)."""
    hist = (vix_data or {}).get("history") or []
    try:
        hist = [float(x) for x in hist if x is not None]
    except Exception:
        return 0.0, None
    if len(hist) < 3:
        return 0.0, None
    window = hist[-6:]
    base = window[0]
    if base <= 0:
        return 0.0, None
    pct = (window[-1] - base) / base * 100.0
    return abs(pct), ("up" if pct > 0 else "down")


class EventDetectionEngine(Engine):
    name = "stage28_event_detection"
    stage = 28
    deps = ["stage22_vix", "stage21_news"]

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        signals = []          # (label, weight)
        react_up = react_dn = 0.0

        # ── VIX shock ──
        vspike, vdir = _vix_spike(raw.get("vix"))
        if vspike >= _VIX_SPIKE_PCT:
            if vdir == "up":
                signals.append((f"VIX spike +{vspike:.0f}% (fear)", 1.3)); react_dn += 1.0
            else:
                signals.append((f"VIX crash -{vspike:.0f}% (relief)", 1.1)); react_up += 0.8

        # ── gamma blast ──
        fmr = raw.get("full_market_read") or {}
        if str(fmr.get("gamma_blast", "")).upper() == "HIGH":
            signals.append(("Gamma blast (dealer hedging accelerant)", 1.1))

        # ── order-flow (CVD) shock ──
        vd = raw.get("volume_delta") or {}
        vds = (vd.get("zone_summary") if vd.get("zone_reset") else None) or vd.get("summary") or {}
        try:
            dp = float(vds.get("delta_pct")) if vds.get("delta_pct") is not None else None
        except Exception:
            dp = None
        if dp is not None and abs(dp) >= _CVD_EXTREME:
            if dp < 0:
                signals.append((f"CVD collapse {dp:+.0f}% (aggressive selling)", 1.3)); react_dn += 1.2
            else:
                signals.append((f"CVD surge {dp:+.0f}% (aggressive buying)", 1.2)); react_up += 1.2

        # ── news shock ──
        news = state.get("stage21_news")
        if news is not None and news.ok and news.bias.value in ("STRONG_BULL", "STRONG_BEAR"):
            signals.append(("News sentiment shock", 1.0))
            if news.bias.value == "STRONG_BULL":
                react_up += 0.8
            else:
                react_dn += 0.8

        got = sum(w for _, w in signals)
        score = round(min(100.0, got / 4.5 * 100.0))
        n = len(signals)
        detected = n >= 2 and score >= 45

        # reaction direction (reported, NOT voted)
        if react_up > react_dn + 0.3:
            reaction = "up (short-covering / relief)"
        elif react_dn > react_up + 0.3:
            reaction = "down (aggressive selling)"
        else:
            reaction = "two-sided / unclear"

        if detected:
            headline = (f"🚨 Breaking Event Detected — {score}% · {n} shocks: "
                        + ", ".join(l for l, _ in signals)
                        + f". Market reaction: {reaction}. Cause unknown — trust flow, "
                        "expect high volatility.")
        else:
            headline = f"No shock event ({score}%)."

        risks = (["Sudden shock in progress — spreads widen and stops get run; "
                  "wait for the dust to settle, don't chase the spike"] if detected else [])

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=float(score) if detected else 0.0,
            evidence=[headline] + [f"✓ {l}" for l, _ in signals],
            risks=risks,
            data={"event_detected": detected, "event_score": score,
                  "shocks": n, "reaction": reaction, "cause": "unknown",
                  "vix_spike_pct": round(vspike, 1),
                  "signals": [l for l, _ in signals]},
            provenance=A.prov("mios:event_detection", Tier.DERIVED),
        )
