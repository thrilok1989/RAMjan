"""Dashboard 2's Top Command Center — six cards, quoted never computed."""

from mios_v5 import command_center as cc
from mios_v5.ui import command_center_panel as panel


def _fr():
    return {
        "decision_v2": {"state": "ENTRY_READY", "confidence": 91,
                        "side": "CALL", "entry": 23650,
                        "trail": {"stop": 23682, "state": "Tightening"}},
        "bias": "BULL", "bias_strength": "Strong",
        "transition": {"label": "Strengthening", "velocity": "Fast",
                       "reversal_probability": 18},
        "market_state": {"state": "TRENDING", "label": "Trending",
                         "duration_min": 136, "next_label": "Expansion",
                         "next_probability": 55},
        "strong_support": 23612, "strong_resistance": 23718,
        "battle_zone": {"price": 23650, "lower": 23642, "upper": 23658},
        "money_flow": {"poc_price": 23648},
        "htf": {"levels": {"Weekly": 23595, "Daily": 23660, "1H": 23640}},
    }


def test_the_six_cards_reproduce_the_specs_worked_example():
    c = cc.build(_fr(), spot=23634.0, quality={"grade": "A+"},
                 risk={"level": "LOW"})
    d = c["decision"]
    assert d["state"] == "ENTRY_READY" and d["confidence"] == 91.0
    assert d["quality"] == "A+" and d["risk"] == "LOW" and d["trail"] == 23682.0
    assert c["bias"]["bias"] == "Bull"
    assert c["bias"]["transition"] == "Strengthening"
    assert c["state"]["state"] == "Trending"
    assert c["state"]["duration"] == "2h 16m"


def test_every_level_carries_its_distance_from_price():
    """A level without one makes the trader do the arithmetic, and they will do
    it wrong at the moment it matters."""
    c = cc.sr_card(_fr(), spot=23634.0)
    by = {r["label"]: r for r in c["rows"]}
    assert by["Support"]["distance"] == "-22 pts"
    assert by["Resistance"]["distance"] == "+84 pts"
    assert c["war_zone"] == "23,642-23,658"
    # every row, no exceptions
    assert all(r["distance"] for r in c["rows"])


def test_a_level_without_a_spot_still_renders():
    c = cc.sr_card(_fr(), spot=None)
    assert c["rows"] and all(r["distance"] is None for r in c["rows"])


def test_an_unarmed_trail_prints_nothing_not_the_last_value():
    """A header tile is exactly where a stale number does the most damage —
    it is the one thing a trader reads without checking."""
    fr = _fr()
    fr["decision_v2"] = {"state": "WAIT", "trail": {"stop": 23682}}
    d = cc.decision_card(fr)
    assert d["armed"] is False
    html = panel.decision_html(d)
    assert "23,682" not in html
    assert "—" in html


def test_the_decision_card_knows_every_state_the_spec_names():
    for state in ("BUY", "SELL", "WAIT", "ENTRY_READY", "SCALE_IN",
                  "SCALE_OUT", "EXIT", "ABORT"):
        assert state in cc.DECISIONS, state
    assert cc.DECISIONS["ABORT"] == "bear"
    assert cc.DECISIONS["ENTRY_READY"] == "watch"


def test_quality_and_risk_get_the_tone_they_deserve():
    assert cc.decision_card({}, {"grade": "A+"})["quality_tone"] == "bull"
    assert cc.decision_card({}, {"grade": "UNTRADEABLE"})["quality_tone"] == "bear"
    assert cc.decision_card({}, None, {"level": "HIGH"})["risk_tone"] == "bear"
    assert cc.decision_card({}, None, {"level": "LOW"})["risk_tone"] == "bull"


def test_market_state_duration_reads_as_a_clock():
    assert cc.state_card({"market_state": {"duration_min": 136}})["duration"] == "2h 16m"
    assert cc.state_card({"market_state": {"duration_min": 7}})["duration"] == "7m"
    assert cc.state_card({})["duration"] == "—"


def test_the_controller_is_quoted_not_re_ranked():
    c = cc.controller_card({
        "ranked": [{"label": "institutions", "score": 98, "direction": "BULL"},
                   {"label": "dealer", "score": 78, "direction": "BULL"}],
        "controller": "Institutions"})
    assert c["winner"] == "Institutions"
    assert c["groups"][0]["name"] == "Institutions"
    assert c["groups"][0]["stars"] == "★★★★★"
    assert c["groups"][1]["stars"] == "★★★★☆"
    # order preserved — this card does not sort
    assert [g["name"] for g in c["groups"]] == ["Institutions", "Dealer"]


def test_invalidation_is_always_shown():
    """The line a trader most needs and least wants."""
    t = cc.thesis_card({"why": ["a"], "expect": ["b"],
                        "invalidation": ["Acceptance below 23610"]})
    html = panel.thesis_html(t)
    assert "Invalidation" in html and "23610" in html
    # and it is rendered in the bear tone, after the others
    assert html.index("Invalidation") > html.index("Expect")


def test_every_card_survives_an_empty_read():
    c = cc.build()
    for key in ("decision", "bias", "state", "sr", "controller", "thesis"):
        assert key in c
    assert c["decision"]["state"] == "WAIT"
    assert c["sr"]["empty"] and c["controller"]["empty"] and c["thesis"]["empty"]
    for fn, key in ((panel.decision_html, "decision"), (panel.bias_html, "bias"),
                    (panel.state_html, "state"), (panel.sr_html, "sr"),
                    (panel.controller_html, "controller"),
                    (panel.thesis_html, "thesis")):
        assert fn(c[key])


def test_the_command_center_computes_nothing():
    """Principle 5: engines interpret indicators; a header renders them."""
    import inspect
    src = inspect.getsource(cc)
    for banned in ("cumsum", "rolling(", "ewm(", "clip(0, 1)"):
        assert banned not in src, banned


def test_the_panel_uses_the_house_colour_convention():
    assert cc.TONE["bull"] == "#00ff88"      # green  bullish
    assert cc.TONE["bear"] == "#ff4444"      # red    bearish
    assert cc.TONE["watch"] == "#ffcc33"     # orange building/watch
    assert cc.TONE["info"] == "#4da6ff"      # blue   neutral/info
    assert cc.TONE["dealer"] == "#a78bfa"    # purple dealer/gamma/charm
    assert cc.TONE["off"] == "#6f7d8f"       # grey   inactive


def test_the_header_is_sticky_and_the_charts_scroll_under_it():
    import inspect
    src = inspect.getsource(panel.render_command_center)
    assert "position:sticky" in src


def test_one_failing_source_costs_one_card_not_the_header():
    """A header that vanishes takes the decision off the screen with it."""
    import inspect
    from mios_v5.ui import dashboard_v6
    src = inspect.getsource(dashboard_v6._command_center)
    assert "_try(" in src
    assert src.count("_try(") >= 4


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"command center tests passed ({len(fns)})")
