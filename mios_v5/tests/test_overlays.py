"""Dashboard 2 overlays — collected from engines, never derived here."""

from mios_v5 import overlays as ov


def _fr():
    return {"decision_v2": {"entry": 23650, "stop": 23600,
                            "trail": {"stop": 23682}},
            "strong_support": 23612, "strong_resistance": 23718,
            "next_target": 23760, "battle_zone": {"price": 23650},
            "htf": {"levels": {"1H": 23640, "Daily": 23660,
                               "Weekly": 23595, "Monthly": 23500}}}


def _mp():
    return {"vwap": 23634, "oi_ceiling": 23800, "oi_floor": 23500,
            "oi_pin": 23700,
            "liq_pools": {"above": [{"price": 23720}],
                          "below": [{"price": 23580}]}}


def _all():
    return ov.collect(_fr(), spot=23634, market_picture=_mp(),
                      gex={"gamma_flip_level": 23655},
                      money_flow={"poc_price": 23648,
                                  "value_area_high": 23690,
                                  "value_area_low": 23610},
                      master={"order_blocks": {
                          "bullish": [{"mid": 23620, "type": "bullish"}]}},
                      charm={"active": True, "pin": 23700,
                             "drag": "upward drag"})


def test_every_engine_with_a_producer_is_wired():
    """Phase 1: everything that already produces a usable output."""
    labels = {i["label"] for i in _all()}
    for expected in ("Support", "Resistance", "War Zone", "POC", "VAH", "VAL",
                     "1H POC", "Daily POC", "Weekly POC", "Monthly POC",
                     "Entry", "Stop", "Trail", "Target",
                     "Call Wall", "Put Wall", "Gamma Flip", "Charm Pin",
                     "VWAP"):
        assert expected in labels, expected
    assert any(l.startswith("Liquidity") for l in labels)
    assert any(l.startswith("OB") for l in labels)


def test_every_overlay_names_the_engine_that_produced_it():
    """A level on screen should always be traceable to the thing that claimed
    it — otherwise a trader is asked to trust a line with no author."""
    for i in _all():
        assert i["source"], i["label"]
        assert i["group"] in ov.GROUPS, i["group"]
        assert i["colour"] and i["width"]


def test_every_overlay_carries_its_distance_from_price():
    for i in _all():
        assert i["distance"] is not None
    # …and copes when there is no spot to measure from
    assert all(i["distance"] is None
               for i in ov.collect(_fr(), spot=None))


def test_nothing_is_invented_when_the_engine_is_silent():
    """No placeholders. An invented level looks exactly like a real one at a
    glance, which makes it worse than a missing one."""
    empty = ov.collect({}, spot=23600)
    assert empty == []
    # charm pin is drawn ONLY when its engine says it is active
    labels = {i["label"] for i in ov.collect(
        _fr(), spot=23634, charm={"active": False, "pin": 23700})}
    assert "Charm Pin" not in labels


def test_a_missing_price_drops_one_overlay_not_the_set():
    fr = _fr()
    fr["strong_support"] = None
    labels = {i["label"] for i in ov.collect(fr, spot=23634)}
    assert "Support" not in labels
    assert "Resistance" in labels


def test_toggling_a_group_filters_and_never_recomputes():
    items = _all()
    off = dict(ov.defaults())
    off["poc"] = False
    off["dealer"] = False
    shown = ov.visible(items, off)
    assert len(shown) < len(items)
    assert not any(i["group"] in ("poc", "dealer") for i in shown)
    # the underlying list is untouched — hiding is a filter
    assert len(items) == len(_all())


def test_defaults_cover_every_group():
    d = ov.defaults()
    assert set(d) == set(ov.GROUPS)
    # the noisy families start hidden
    assert d["orderblk"] is False and d["liquidity"] is False
    assert d["sr"] is True and d["trade"] is True


def test_summary_reports_zero_for_a_group_with_nothing_to_draw():
    """"Off" and "empty" are different states, and a trader who cannot tell
    them apart will keep toggling a group that was never going to draw."""
    s = ov.summary(_all())
    assert s["vob"] == 0
    assert s["poc"] == 7 and s["dealer"] == 3
    assert set(s) == set(ov.GROUPS)


def test_levels_are_keyed_by_label_so_none_are_lost():
    """Keying by KIND would silently keep only the last of six HTF POCs."""
    lv = ov.as_levels(_all())
    for k in ("1H POC", "Daily POC", "Weekly POC", "Monthly POC"):
        assert k in lv
    assert lv["Call Wall"] == 23800 and lv["Put Wall"] == 23500


def test_the_collector_computes_nothing():
    import inspect
    src = inspect.getsource(ov)
    for banned in ("cumsum", "rolling(", "ewm(", ".sum()", "np."):
        assert banned not in src, banned


def test_the_toggle_panel_offers_every_group():
    import inspect
    from mios_v5.ui import overlay_panel
    src = inspect.getsource(overlay_panel.overlay_controls)
    assert "GROUPS.items()" in src
    # a group with nothing to draw is disabled, not silently identical to "off"
    assert "disabled=(n == 0)" in src
    # and the choice survives the rerun
    assert "session_state" in src


def test_the_legend_names_sources():
    from mios_v5.ui.overlay_panel import legend_html
    html = legend_html(_all())
    assert "Stage 52 Decision Engine" in html or "Decision Engine" in html
    assert legend_html([]) == ""


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"overlay tests passed ({len(fns)})")
