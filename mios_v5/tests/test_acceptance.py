"""Stage 42 — Acceptance / Rejection / Trap (the timing engine)."""

from mios_v5.acceptance import (evaluate_reaction, is_actionable, label_for)

RES = {"side": "RESISTANCE", "price": 23700.0, "strength": 88}
SUP = {"side": "SUPPORT", "price": 23700.0, "strength": 88}


def _m(cvd=10.0, vol=100_000.0, mf=200.0, ce=-500.0, pe=0.0, dealer="bull"):
    return {"cvd_pct": cvd, "volume": vol, "mf_net": mf,
            "oi_ce_chg": ce, "oi_pe_chg": pe, "dealer_dir": dealer}


def _run(zone, steps):
    """Feed a price/metric sequence through the machine, carrying memory."""
    mem, out = None, []
    for spot, met in steps:
        r = evaluate_reaction(zone, spot, met, mem)
        mem = r["memory"]
        out.append(r)
    return out


def test_touch_then_watching():
    r = _run(RES, [(23695.0, _m()), (23697.0, _m())])
    assert r[0]["state"] == "TOUCH" and r[0]["confidence"] == 0
    assert r[1]["state"] == "WATCHING"


def test_away_from_level_is_idle():
    r = evaluate_reaction(RES, 23500.0, _m())
    assert r["state"] == "IDLE" and not r["actionable"]


def test_break_then_confirmed_breakout():
    # breaks up, and volume/CVD/flow/OI/dealers all follow through
    steps = [(23695.0, _m()),
             (23712.0, _m(cvd=12, vol=110_000)),                 # BREAK
             (23725.0, _m(cvd=30, vol=180_000, mf=400, ce=-2000)),
             (23740.0, _m(cvd=45, vol=220_000, mf=600, ce=-3000))]
    r = _run(RES, steps)
    assert r[1]["state"] == "BREAK"
    assert r[-1]["state"] in ("ACCEPTANCE", "CONFIRMED_BREAKOUT")
    assert r[-1]["winner"] == "Buyers" and r[-1]["action"] == "ENTER CALL"
    assert r[-1]["confidence"] >= 70


def test_the_fake_breakout_scenario_end_to_end():
    """The exact sequence: breaks resistance, flow doesn't follow, price returns
    below, flow reverses → BULL TRAP → ENTER PUT."""
    steps = [
        (23695.0, _m()),                                          # touch
        (23712.0, _m(cvd=12, vol=110_000)),                       # break
        (23708.0, _m(cvd=8, vol=90_000, mf=150)),                 # stalling
        (23702.0, _m(cvd=2, vol=80_000, mf=100)),
        # back below, flow fully reversed, call writers returning
        (23690.0, _m(cvd=-25, vol=60_000, mf=-300, ce=+2500, dealer="bear")),
    ]
    r = _run(RES, steps)
    assert r[1]["state"] == "BREAK"
    final = r[-1]
    assert final["state"] == "BULL_TRAP"
    assert final["winner"] == "Sellers" and final["action"] == "ENTER PUT"
    assert final["confidence"] >= 70
    assert any("reversed" in x.lower() for x in final["reasons"])


def test_failed_breakout_without_reversal_stays_failed():
    # comes back inside, but flow still supportive → not yet a trap
    steps = [(23695.0, _m()),
             (23715.0, _m(cvd=12, vol=110_000)),
             (23718.0, _m(cvd=14, vol=115_000)),
             (23720.0, _m(cvd=15, vol=118_000)),
             (23694.0, _m(cvd=20, vol=140_000, mf=500, ce=-1500, dealer="bull"))]
    r = _run(RES, steps)
    assert r[-1]["state"] == "FAILED_BREAKOUT"
    assert r[-1]["action"] is None          # failed ≠ tradable until confirmed


def test_liquidity_sweep_is_distinct_from_failed_breakout():
    # shallow spike beyond for one cycle then straight back = stop hunt
    steps = [(23695.0, _m()),
             (23715.0, _m(cvd=11, vol=105_000)),
             (23692.0, _m(cvd=6, vol=95_000))]
    r = _run(RES, steps)
    assert r[-1]["state"] == "SWEEP_BUY"
    assert r[-1]["winner"] == "Sellers"


def test_support_side_mirrors():
    steps = [(23705.0, _m(dealer="bear")),
             (23688.0, _m(cvd=-12, vol=110_000, dealer="bear", pe=-800)),
             (23670.0, _m(cvd=-35, vol=200_000, mf=-500, pe=-2500, dealer="bear")),
             (23655.0, _m(cvd=-50, vol=240_000, mf=-800, pe=-3000, dealer="bear"))]
    r = _run(SUP, steps)
    assert r[-1]["state"] in ("ACCEPTANCE", "CONFIRMED_BREAKDOWN")
    assert r[-1]["winner"] == "Sellers" and r[-1]["action"] == "ENTER PUT"


def test_bear_trap_gives_call():
    steps = [(23705.0, _m(dealer="bear")),
             (23685.0, _m(cvd=-12, vol=110_000, dealer="bear")),
             (23682.0, _m(cvd=-14, vol=100_000, dealer="bear")),
             (23680.0, _m(cvd=-15, vol=95_000, dealer="bear")),
             (23712.0, _m(cvd=25, vol=60_000, mf=500, pe=+2500, dealer="bull"))]
    r = _run(SUP, steps)
    assert r[-1]["state"] == "BEAR_TRAP"
    assert r[-1]["action"] == "ENTER CALL" and r[-1]["winner"] == "Buyers"


def test_absorption_heavy_volume_no_progress():
    steps = [(23700.0, _m(vol=100_000)),
             (23700.0, _m(vol=250_000))]
    r = _run(RES, steps)
    assert r[-1]["state"] == "ABSORPTION"


def test_missing_inputs_are_unknown_not_agreement():
    steps = [(23695.0, {}), (23712.0, {}), (23725.0, {})]
    r = _run(RES, steps)
    # with no evidence at all it must not manufacture a confirmed breakout
    assert r[-1]["state"] not in ("CONFIRMED_BREAKOUT", "ACCEPTANCE")


def test_resolved_state_is_sticky_while_at_level():
    steps = [(23695.0, _m()),
             (23715.0, _m(cvd=11, vol=105_000)),
             (23692.0, _m(cvd=6, vol=95_000)),      # → SWEEP_BUY
             (23694.0, _m(cvd=6, vol=95_000))]      # still at level
    r = _run(RES, steps)
    assert r[-2]["state"] == "SWEEP_BUY" and r[-1]["state"] == "SWEEP_BUY"


def test_bad_zone_is_safe():
    assert evaluate_reaction(None, 23700, _m())["state"] == "IDLE"
    assert evaluate_reaction({"side": "X", "price": 1}, 1, _m())["state"] == "IDLE"
    assert evaluate_reaction(RES, None, _m())["state"] == "IDLE"


def test_helpers():
    assert is_actionable("BULL_TRAP") and not is_actionable("WATCHING")
    assert "TRAP" in label_for("BULL_TRAP")


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"acceptance/rejection/trap tests passed ({len(fns)})")
