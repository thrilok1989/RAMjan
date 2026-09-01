"""MIOS V6 — tests for the shared expiry charm-pin read."""

from mios_v5.charm_pin import NEAR_POINTS, from_market_picture, read
from mios_v5.ui.charm_pin_panel import charm_pin_html


def test_not_expiry_day_is_inactive():
    r = read(False, 24000, 24000, -390.9)
    assert r["active"] is False and r["reason"] == "not expiry day"


def test_pin_above_spot_reads_upward_drag():
    r = read(True, 23950, 24000, -390.9)
    assert r["active"] is True
    assert "above spot — upward drag" == r["drift"]
    assert r["distance"] == 50.0


def test_pin_below_spot_reads_downward_drag():
    r = read(True, 24050, 24000, -390.9)
    assert "below spot — downward drag" == r["drift"]
    assert r["distance"] == -50.0


def test_pin_at_spot():
    assert read(True, 24000, 24000)["drift"] == "at spot"


def test_far_pin_is_not_a_pin():
    """Beyond the near band the dealer hedge is not anchored to the strike —
    calling it 'pinned' anyway would be superstition."""
    r = read(True, 23800, 24000, -390.9)
    assert r["active"] is False
    assert "pts away" in r["reason"]
    assert r["distance"] == 200.0


def test_boundary_is_inclusive():
    assert read(True, 24000 - NEAR_POINTS, 24000)["active"] is True
    assert read(True, 24000 - NEAR_POINTS - 1, 24000)["active"] is False


def test_missing_charm_still_produces_a_read():
    """The drag exists whether or not the greek is computable; withholding the
    whole read for one missing number would be worse than showing it without."""
    r = read(True, 23950, 24000, None)
    assert r["active"] is True and r["net_charm"] is None
    assert "net charm" not in r["sentence"]


def test_charm_appears_in_the_sentence_when_present():
    r = read(True, 23950, 24000, -390.9)
    assert "net charm -390.9L/day" in r["sentence"]
    assert "₹24,000" in r["sentence"]


def test_no_pin_available():
    assert read(True, 24000, None)["active"] is False
    assert read(True, None, 24000)["active"] is False


def test_bad_values_never_raise():
    for bad in ("x", None, float("nan"), [], {}):
        assert read(True, bad, 24000)["active"] is False
        assert read(True, 24000, bad)["active"] is False


def test_it_is_always_context_only():
    assert read(True, 23950, 24000, -390.9)["context_only"] is True


def test_market_picture_prefers_the_oi_pin_over_max_pain():
    """OI wall over max pain — they usually agree, and when they don't, the
    wall is the one price reacts to."""
    mp = {"oi_pin": (24000, "heavy CE+PE OI"),
          "vc_exp": {"net_charm": -390.9}}
    r = from_market_picture(True, 23950, mp, max_pain=23800)
    assert r["pin"] == 24000.0
    assert r["pin_label"] == "heavy CE+PE OI"
    assert r["net_charm"] == -390.9


def test_market_picture_falls_back_to_max_pain():
    r = from_market_picture(True, 23950, {"vc_exp": {}}, max_pain=24000)
    assert r["pin"] == 24000.0 and r["pin_label"] == "max pain"


def test_market_picture_with_nothing():
    assert from_market_picture(True, 23950, None, None)["active"] is False
    assert from_market_picture(True, 23950, {}, None)["active"] is False


def test_malformed_oi_pin_does_not_raise():
    assert from_market_picture(True, 23950, {"oi_pin": ()}, 24000)["pin"] == 24000.0
    assert from_market_picture(True, 23950, {"oi_pin": (24000,)},
                               None)["pin"] == 24000.0


def test_html_matches_the_wording_the_guardian_panel_used():
    html = charm_pin_html(read(True, 23950, 24000, -390.9))
    assert "Expiry charm-pin" in html
    assert "₹24,000" in html
    assert "above spot — upward drag" in html
    assert "net charm -390.9L/day" in html
    assert "fade" in html
    assert "does NOT change the" in html


def test_html_is_empty_when_inactive():
    assert charm_pin_html(read(False, 24000, 24000)) == ""
    assert charm_pin_html(None) == ""
    assert charm_pin_html({}) == ""


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"charm pin tests passed ({len(fns)})")
