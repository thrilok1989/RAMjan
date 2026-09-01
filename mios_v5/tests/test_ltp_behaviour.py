"""Stage 50 — LTP Behaviour (what price is TRYING to do)."""

from mios_v5.ltp_behaviour import (analyse, classify_money_flow,
                                   classify_option_side, classify_price,
                                   classify_side, classify_volume, describe,
                                   trace_push)


def _m(spot, cvd=0.0, mf=0.0, vol=100_000.0, **kw):
    d = {"spot": spot, "cvd": cvd, "mf_net": mf, "volume": vol}
    d.update(kw)
    return d


def test_price_states():
    rising = [_m(23700 + i * 25) for i in range(5)]
    assert classify_price(rising)["state"] == "rising"
    falling = [_m(23700 - i * 25) for i in range(5)]
    assert classify_price(falling)["state"] == "falling"
    flat = [_m(23700 + (i % 2)) for i in range(6)]
    assert classify_price(flat)["state"] in ("flat", "compressing")
    boom = [_m(23700), _m(23705), _m(23710), _m(23800)]
    assert classify_price(boom)["state"] == "exploding"


def test_compression_detected_on_tight_range():
    tight = [_m(23700 + (i % 3) * 2) for i in range(6)]
    p = classify_price(tight)
    assert p["state"] == "compressing"


def test_buyers_building_when_pressure_and_price_rise():
    tr = [_m(23700 + i * 20, cvd=i * 12) for i in range(6)]
    b = classify_side(tr, "buyers")
    assert b["state"] == "building"


def test_absorption_is_pressure_without_price_response():
    """The read a snapshot can never produce: buyers pushing hard, price flat."""
    tr = [_m(23700 + (i % 2), cvd=i * 15) for i in range(6)]
    b = classify_side(tr, "buyers")
    assert b["state"] == "absorbing"


def test_seller_absorption_mirrors():
    tr = [_m(23700 + (i % 2), cvd=-i * 15) for i in range(6)]
    s = classify_side(tr, "sellers")
    assert s["state"] == "absorbing"


def test_exhaustion_is_high_pressure_now_collapsing():
    # buyers pushed hard, price advanced, now pressure is falling away
    tr = [_m(23700, cvd=10), _m(23730, cvd=60), _m(23760, cvd=90),
          _m(23775, cvd=70), _m(23780, cvd=48)]
    b = classify_side(tr, "buyers")
    assert b["state"] in ("exhausted", "weakening")


def test_weakening_when_pressure_drains_to_nothing():
    tr = [_m(23700, cvd=90), _m(23700, cvd=60), _m(23700, cvd=30),
          _m(23700, cvd=8), _m(23700, cvd=2)]
    assert classify_side(tr, "buyers")["state"] == "weakening"


def test_option_side_ltp_oi_matrix():
    assert classify_option_side(2.0, 5.0)["state"] == "building"     # OI↑ LTP↑
    assert classify_option_side(-2.0, 5.0)["state"] == "distribution"  # OI↑ LTP↓
    assert classify_option_side(-2.0, -5.0)["state"] == "unwinding"   # OI↓ LTP↓
    assert classify_option_side(2.0, -5.0)["state"] == "squeeze"      # OI↓ LTP↑
    assert classify_option_side(2.0, 0.1)["state"] == "flat"
    assert classify_option_side(None, None)["state"] == "flat"


def test_money_flow_states():
    inflow = [_m(23700, mf=i * 100) for i in range(5)]
    assert classify_money_flow(inflow)["state"] == "entering"
    outflow = [_m(23700, mf=-i * 100) for i in range(5)]
    assert classify_money_flow(outflow)["state"] == "leaving"


def test_volume_states():
    dry = [_m(23700, vol=100_000)] * 4 + [_m(23700, vol=30_000)]
    assert classify_volume(dry)["state"] == "dry"
    boom = [_m(23700, vol=100_000)] * 4 + [_m(23700, vol=400_000)]
    assert classify_volume(boom)["state"] == "explosive"
    ok = [_m(23700, vol=100_000)] * 5
    assert classify_volume(ok)["state"] == "healthy"


def test_overall_sentence_prioritises_absorption():
    d = describe({"state": "flat"}, {"state": "absorbing"}, {"state": "building"},
                 {"state": "neutral"}, {"state": "healthy"})
    assert "absorbing" in d["text"].lower() and d["tone"] == "bull"


def test_overall_sellers_gaining_control():
    d = describe({"state": "falling"}, {"state": "weakening"},
                 {"state": "building"}, {"state": "leaving"},
                 {"state": "healthy"})
    assert "sellers" in d["text"].lower() and d["tone"] == "bear"


def test_overall_is_one_sentence():
    d = describe({"state": "flat"}, {"state": "neutral"}, {"state": "neutral"},
                 {"state": "neutral"}, {"state": "healthy"})
    assert d["text"].count(".") <= 1 and len(d["text"]) < 120


def test_analyse_end_to_end():
    tr = []
    for i in range(6):
        tr = trace_push(tr, _m(23700 - i * 20, cvd=-i * 14, mf=-i * 80,
                               vol=120_000, ce_ltp=100 - i * 5,
                               pe_ltp=80 + i * 6, ce_oi_chg_pct=3.0,
                               pe_oi_chg_pct=4.0))
    a = analyse(tr)
    assert a["ready"]
    assert a["price"]["state"] == "falling"
    assert a["sellers"]["state"] in ("building", "absorbing")
    assert a["calls"]["state"] == "distribution"   # OI↑ LTP↓ = call writing
    assert a["puts"]["state"] == "building"        # OI↑ LTP↑ = put buying
    assert a["overall"]["text"]


def test_not_enough_history_is_honest():
    a = analyse([_m(23700)])
    assert not a["ready"] and "warming up" in a["overall"]["text"].lower()


def test_trace_push_bounded():
    t = []
    for i in range(30):
        t = trace_push(t, _m(23700 + i), keep=12)
    assert len(t) == 12


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"LTP behaviour tests passed ({len(fns)})")
