"""MIOS V5 — Error / Data-Integrity strip (makes every 'Neutral' explainable).

Reads the engine results already produced this pass and answers the question
that matters during a validation phase: *is this read genuine, or is it running
on degraded / missing data?* — so a "Neutral" market is never confused with a
data-feed problem, and trades taken on a degraded cycle can be flagged.

Pure (no Streamlit / no DB) so it is unit-testable.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .core import MarketState, Status

# the data-dependent engines worth surfacing (label kept short for a strip)
_WATCH = [
    ("stage14_orderflow", "Order Flow / CVD"),
    ("stage12_options", "Greeks / Options"),
    ("stage11_dealer", "GEX / DEX"),
    ("stage35_reaction_zone", "S/R Zones"),
    ("stage05_regime", "Regime"),
    ("stage19_global", "Global"),
    ("stage21_news", "News"),
]

# the ones whose absence actually compromises a trade decision
_CORE = {"stage14_orderflow", "stage12_options", "stage11_dealer",
         "stage35_reaction_zone"}

_EMOJI = {
    Status.OK: "✅", Status.DEGRADED: "⚠️", Status.NEUTRAL: "⚠️",
    Status.ERROR: "⛔", Status.DISABLED: "⚫",
}


def _reason(r) -> str:
    """Short human reason for a non-OK status (why it's neutral/degraded)."""
    if r is None:
        return "not run this pass"
    if r.status == Status.OK:
        return "live"
    if r.errors:
        return (r.errors[0].reason or "")[:60]
    if r.evidence:
        # evidence[0] often starts with 'NEUTRAL: ...' / 'DISABLED: ...'
        e = r.evidence[0]
        return e.split(":", 1)[1].strip()[:60] if ":" in e else e[:60]
    return r.status.value.lower()


def build_engine_status(state: MarketState) -> Dict[str, Any]:
    """Per-engine status + an overall data-integrity verdict."""
    engines: List[Dict[str, Any]] = []
    ok_n = 0
    worst_core = Status.OK
    any_error = False
    for name, label in _WATCH:
        r = state.get(name) if state is not None else None
        stt = r.status if r is not None else Status.NEUTRAL
        engines.append({
            "engine": label, "name": name,
            "status": stt.value, "emoji": _EMOJI.get(stt, "⚪"),
            "reason": _reason(r),
        })
        if stt == Status.OK:
            ok_n += 1
        if stt == Status.ERROR:
            any_error = True
        if name in _CORE and stt in (Status.DEGRADED, Status.NEUTRAL, Status.ERROR):
            # track the most severe core impairment
            worst_core = stt if worst_core == Status.OK else worst_core

    # overall verdict: an ERROR anywhere, or an impaired CORE engine, degrades trust
    if any_error:
        integrity = "COMPROMISED"
    elif worst_core != Status.OK:
        integrity = "DEGRADED"
    else:
        integrity = "OK"

    impaired = [e for e in engines if e["status"] != "OK"
                and e["status"] != "DISABLED"]
    return {
        "engines": engines,
        "integrity": integrity,
        "ok_n": ok_n,
        "total": len(engines),
        "impaired": impaired,
        "trust_note": {
            "OK": "all core feeds live — read is genuine",
            "DEGRADED": "a core feed is stale/missing — treat signals with caution "
                        "(a 'Neutral' here may be data, not the market)",
            "COMPROMISED": "an engine errored — do NOT trust this read; verify the "
                           "feed before acting/logging",
        }[integrity],
    }
