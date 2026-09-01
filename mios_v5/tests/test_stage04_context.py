"""MIOS V5 — Stage 4 Market Context engine tests.

    python -m mios_v5.tests.test_stage04_context
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pytz

from mios_v5.core import Bias, Status
from mios_v5.final_read import build_final_read, final_read_line
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_adapters import _rich_raw

IST = pytz.timezone("Asia/Kolkata")


def _today_str():
    return datetime.now(IST).date().isoformat()


def _in_days(n):
    return (datetime.now(IST).date() + timedelta(days=n)).isoformat()


def test_context_neutral_without_chain():
    """No option chain → cannot frame the day → honest NEUTRAL."""
    st = build_orchestrator().run({"api_ok": True, "db_ok": True})
    c = st.get("stage04_context")
    assert c is not None and c.status == Status.NEUTRAL


def test_expiry_pin_long_gamma():
    """🧲 expiry + LONG gamma + at pin → genuine PIN (damped, low energy)."""
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()          # expiry TODAY
    raw["spot"] = 24300                                   # AT the pin
    raw["market_picture"]["oi_pin"] = (24300, "balanced walls — pin")
    raw["market_picture"]["gex_disp"] = {"total": 250, "signal": "Pin"}  # long gamma
    raw["market_picture"]["regime"] = "SIDEWAYS"
    raw["full_market_read"]["gamma_blast"] = "LOW"
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.status == Status.OK and c.bias == Bias.NONE
    assert c.data["is_expiry"] is True and c.data["dte"] == 0
    assert c.data["day_type"] == "EXPIRY · PIN"
    assert c.data["long_gamma"] is True
    # damped → LOW energy, LOW breakout risk
    assert c.data["energy"] < 45 and c.data["breakout_risk"] < 40
    assert c.risks and any("theta" in r.lower() for r in c.risks)


def test_expiry_coiled_spring():
    """⚡ expiry + SHORT gamma + at pin → COILED SPRING (quiet but LOADED)."""
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()
    raw["spot"] = 24300                                   # at the pin…
    raw["market_picture"]["oi_pin"] = (24300, "pin")
    raw["market_picture"]["gex_disp"] = {"total": -220, "signal": "Breakout"}  # short gamma
    raw["full_market_read"]["gamma_blast"] = "HIGH"
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["day_type"] == "EXPIRY · COILED SPRING"
    assert c.data["short_gamma"] is True and c.data["at_pin"] is True
    # loaded → HIGH energy, HIGH compression, HIGH breakout risk
    assert c.data["energy"] >= 80 and c.data["compression"] >= 70
    assert c.data["breakout_risk"] >= 80
    assert any("compression" in e.lower() for e in c.evidence)
    assert any("break" in o.lower() for o in c.opportunities)


def test_expiry_gamma_unwind():
    """🚀 expiry + SHORT gamma + price LEFT pin → GAMMA UNWIND (trend, don't fade)."""
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()
    raw["market_picture"]["oi_pin"] = (24300, "pin")
    raw["market_picture"]["gex_disp"] = {"total": -260, "signal": "Breakout"}  # short gamma
    raw["spot"] = 24500                                   # 200 pts off the pin
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["day_type"] == "EXPIRY · GAMMA UNWIND"
    assert c.data["pin_zone"] == "left"
    assert c.data["breakout_risk"] >= 80
    assert any("fade" in r.lower() for r in c.risks)      # do NOT fade


def test_expiry_pin_break_long_gamma_left():
    """⚠️ expiry + LONG gamma + price left pin → PIN BREAK (genuine or pullback?)."""
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()
    raw["market_picture"]["oi_pin"] = (24300, "pin")
    raw["market_picture"]["gex_disp"] = {"total": 140, "signal": "Pin"}  # long gamma
    raw["spot"] = 24500                                   # left the pin
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["day_type"] == "EXPIRY · PIN BREAK"
    assert c.data["long_gamma"] is True and c.data["pin_zone"] == "left"


def test_expiry_volatile_day():
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()
    raw["market_picture"].pop("oi_pin", None)            # no pin
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["is_expiry"] is True
    assert c.data["day_type"] == "EXPIRY · VOLATILE"
    assert any("charm" in r.lower() for r in c.risks)


def test_pre_expiry_day():
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _in_days(1)           # expiry tomorrow
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["dte"] == 1 and c.data["is_expiry"] is False
    assert c.data["day_type"] == "PRE-EXPIRY"


def test_gap_up_day():
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _in_days(3)           # not near expiry
    raw["market_memory"] = {"prev_close": 24000.0}
    raw["day_open"] = 24160.0                             # +0.67% gap up
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    assert c.data["day_type"] == "GAP-UP"
    assert c.data["gap_pct"] > 0.4


def test_normal_day_and_finalread_surfacing():
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _in_days(3)
    raw["market_picture"].pop("oi_pin", None)
    raw["market_memory"] = {"prev_close": 24300.0}
    raw["day_open"] = 24305.0                             # flat open
    st = build_orchestrator().run(raw)
    c = st.get("stage04_context")
    # regime is UP in _rich_raw → TREND frame
    assert c.data["day_type"] in ("TREND", "NORMAL / RANGE")
    # final read surfaces the context
    fr = build_final_read(st)
    assert fr["day_type"] == c.data["day_type"]
    assert fr["is_expiry"] is False
    assert isinstance(final_read_line(fr), str)


def test_finalread_line_flags_expiry():
    raw = _rich_raw()
    raw["option_data"]["expiry"] = _today_str()
    raw["market_picture"]["oi_pin"] = (24300, "pin")
    fr = build_final_read(build_orchestrator().run(raw))
    line = final_read_line(fr)
    assert "EXPIRY" in line


def _run():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ✓ {fn.__name__}")
    print(f"stage04 context: {len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    try:
        _run()
    except AssertionError as e:
        print(f"  ✗ FAILED: {e}")
        sys.exit(1)
