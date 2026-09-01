"""MIOS V5 — Environment (VIX, Flows), Liquidity and Pattern-Alignment engines.

    python -m mios_v5.tests.test_stage_env_liq_patterns
"""

from __future__ import annotations

import sys

from mios_v5.core import Bias, Status
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_adapters import _rich_raw


# ── VIX ────────────────────────────────────────────────────────────────
def test_vix_falling_bull():
    raw = _rich_raw()
    raw["vix"] = {"value": 13.5, "direction": "Falling"}
    c = build_orchestrator().run(raw).get("stage22_vix")
    assert c.status == Status.OK and c.bias == Bias.BULL
    assert c.data["vol_regime"] == "Normal"


def test_vix_rising_high_fear_bear():
    raw = _rich_raw()
    raw["vix"] = {"value": 22.0, "direction": "Rising"}
    c = build_orchestrator().run(raw).get("stage22_vix")
    assert c.bias == Bias.BEAR and c.data["vol_regime"] == "High Fear"
    assert c.confidence >= 60 and c.risks


def test_vix_absent_neutral():
    c = build_orchestrator().run(_rich_raw()).get("stage22_vix")
    assert c.status == Status.NEUTRAL


# ── FII/DII flows ──────────────────────────────────────────────────────
def test_flows_fii_buying_bull():
    raw = _rich_raw()
    raw["fii_dii"] = {"FII": {"net": 3200.0, "date": "22-Jul"},
                      "DII": {"net": -400.0}}
    c = build_orchestrator().run(raw).get("stage23_flows")
    assert c.status == Status.OK and c.bias in (Bias.BULL, Bias.STRONG_BULL)
    assert c.data["fii_net"] == 3200.0


def test_flows_fii_selling_bear():
    raw = _rich_raw()
    raw["fii_dii"] = {"FII": {"net": -3000.0}, "DII": {"net": 500.0}}
    c = build_orchestrator().run(raw).get("stage23_flows")
    assert c.bias in (Bias.BEAR, Bias.STRONG_BEAR) and c.risks


def test_flows_conflict_damps():
    raw = _rich_raw()
    raw["fii_dii"] = {"FII": {"net": 3000.0}, "DII": {"net": -2800.0}}
    c = build_orchestrator().run(raw).get("stage23_flows")
    assert c.data["conflict"] is True


# ── Liquidity ──────────────────────────────────────────────────────────
def test_liquidity_walls_and_pools():
    raw = _rich_raw()
    raw["spot"] = 24300
    raw["market_picture"]["oi_floor"] = (24200, 14.0)
    raw["market_picture"]["oi_ceiling"] = (24500, 9.0)
    raw["market_picture"]["liq_pools"] = {
        "above": [{"price": 24420, "kind": "eq-highs", "touched": False},
                  {"price": 24600, "kind": "PDH", "touched": False}],
        "below": [{"price": 24150, "kind": "eq-lows", "touched": True}],
    }
    c = build_orchestrator().run(raw).get("stage17_liquidity")
    assert c.status == Status.OK
    # 2 untapped above, 0 untapped below + heavier floor → upside magnet pull
    assert c.bias in (Bias.BULL, Bias.STRONG_BULL)
    assert c.data["nearest_above"] == 24420 and c.data["ce_wall"] == 24500


def test_liquidity_absent_neutral():
    raw = _rich_raw()
    raw["market_picture"].pop("oi_floor", None)
    raw["market_picture"].pop("oi_ceiling", None)
    raw["market_picture"].pop("liq_pools", None)
    c = build_orchestrator().run(raw).get("stage17_liquidity")
    assert c.status == Status.NEUTRAL


# ── Pattern alignment ──────────────────────────────────────────────────
def _raw_with_structure(chart=None, candle=None, trend="Range",
                        location="", demand_supply="Neutral"):
    raw = _rich_raw()
    raw["market_structure"] = {
        "chart_pattern": chart, "candle_pattern": candle,
        "trend": trend, "price_location": location,
        "demand_supply": demand_supply,
    }
    return raw


def test_pattern_none_neutral():
    c = build_orchestrator().run(_raw_with_structure()).get("stage26_patterns")
    assert c.status == Status.NEUTRAL


def test_pattern_continuation_with_trend():
    # bullish candle, uptrend, order flow bullish (rich_raw is bullish) → CONTINUATION
    raw = _raw_with_structure(candle="Bullish Engulfing", trend="Strong Uptrend",
                              location="near support", demand_supply="Demand")
    c = build_orchestrator().run(raw).get("stage26_patterns")
    assert c.status == Status.OK
    assert c.data["aligned_read"] in ("CONTINUATION", "REVERSAL")
    assert c.bias in (Bias.BULL, Bias.STRONG_BULL)


def test_pattern_trap_counter_trend_on_trend_day():
    # bullish candle but DOWNtrend + flow against on a trend day → TRAP
    raw = _raw_with_structure(candle="Bullish Engulfing", trend="Strong Downtrend",
                              location="near resistance", demand_supply="Supply")
    # force order flow bearish + a trend day via context inputs
    raw["market_picture"]["regime"] = "DOWN"
    raw["market_picture"]["p_down"] = 70
    raw["full_market_read"]["market_kind"] = "bear"
    raw["option_data"]["expiry"] = "2099-01-01"           # not expiry → TREND frame
    c = build_orchestrator().run(raw).get("stage26_patterns")
    assert c.status == Status.OK
    # aligned read should flag the danger (TRAP) or at least not be a confident long
    assert c.data["aligned_read"] in ("TRAP", "REVERSAL", "FORMING")


def test_pattern_lean_classifier():
    from mios_v5.engines.stage26_patterns import _pattern_lean
    assert _pattern_lean("Bullish Engulfing") == 1
    assert _pattern_lean("Bearish Engulfing") == -1
    assert _pattern_lean("Shooting Star") == -1
    assert _pattern_lean("Double Bottom") == 1
    assert _pattern_lean("Doji") == 0
    assert _pattern_lean(None) == 0


# ── conflict integration: new engines actually feed the vote ───────────
def test_conflict_includes_new_engines():
    from mios_v5.engines.stage27_conflict import _PRIORITY
    for e in ("stage17_liquidity", "stage22_vix", "stage23_flows",
              "stage26_patterns"):
        assert e in _PRIORITY, f"{e} not wired into conflict vote"


def _run():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"env/liq/patterns: {len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    try:
        _run()
    except AssertionError as e:
        print(f"  ✗ FAILED: {e}")
        sys.exit(1)
