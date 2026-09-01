"""The legs' S/R read as a table under the charts.

The chart marks the level and names the state; the table says how far the leg
actually is from it, which a line on a premium axis cannot show at a glance.

Same values either way — nothing is recomputed here, the reads come from the
store `_publish_atm_legs` already fills each cycle. The one job these tests do
is make sure the table cannot disagree with the chart above it.
"""

from __future__ import annotations

import re

import pytest

from mios_v5.ui.leg_sr_table import (
    CHARTS,
    build_table,
    row_for,
    rows,
    table_html,
)
from mios_v5.ui.terminal_chart import SR_STATE_TONE


def _text(html: str) -> str:
    """The table's visible text, tags stripped."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


BREAK = {"state": "BREAKING", "side": "resistance", "level": 124.5}
REJECT = {"state": "REJECTING", "side": "support", "level": 88.0}


# ── one row per leg, always ────────────────────────────────────────────

def test_every_leg_gets_a_row_per_side():
    """A leg sits BETWEEN its levels. Showing only the winning side hid half
    the picture, and which side won could come down to a tie broken by the
    classifier's iteration order."""
    out = rows(call_sr=BREAK, put_sr=REJECT)
    assert [(r["chart"], r["side"]) for r in out] == [
        ("CALL", "resistance"), ("CALL", "support"),
        ("PUT", "resistance"), ("PUT", "support")]


def test_a_leg_with_no_read_still_gets_its_rows():
    """An empty table would look broken. "No level" is a fact worth showing —
    it is the engine saying it has no verdict, not a failure."""
    out = rows()
    assert len(out) == 4
    assert all(r["state"] == "NONE" for r in out)
    assert all(r["level"] is None for r in out)
    assert all(r["side"] in ("resistance", "support") for r in out)


def test_an_unknown_state_degrades_to_none():
    r = row_for("CALL", {"state": "WOBBLING", "level": 10.0})
    assert r["state"] == "NONE"


# ── the numbers ────────────────────────────────────────────────────────

def test_distance_is_ltp_minus_level():
    r = row_for("CALL", BREAK, ltp=126.6)
    assert r["distance"] == pytest.approx(2.1)


def test_distance_is_negative_below_the_level():
    r = row_for("PUT", REJECT, ltp=86.35)
    assert r["distance"] == pytest.approx(-1.65)


def test_distance_is_none_without_both_numbers():
    assert row_for("CALL", BREAK, ltp=None)["distance"] is None
    assert row_for("CALL", {"state": "BREAKING"}, ltp=120.0)["distance"] is None


def test_a_non_numeric_ltp_does_not_raise():
    assert row_for("CALL", BREAK, ltp="n/a")["ltp"] is None


# ── the rendered table ─────────────────────────────────────────────────

def test_the_table_shows_state_level_ltp_and_distance():
    html = build_table(call_sr=BREAK, call_ltp=126.6, call_label="ATM CE 24500")
    text = _text(html)
    for want in ("ATM CE 24500", "BREAKING", "resistance",
                 "₹124.50", "₹126.60", "+2.10"):
        assert want in text, f"{want!r} missing from: {text}"


def test_distance_carries_its_sign():
    """+2.10 reads as "above the level" at a glance, which is the half of the
    answer the state word does not carry."""
    assert "+2.10" in _text(build_table(call_sr=BREAK, call_ltp=126.6))
    assert "-1.65" in _text(build_table(put_sr=REJECT, put_ltp=86.35))


def test_missing_numbers_render_as_a_dash_not_a_zero():
    text = _text(build_table(call_sr={"state": "NONE"}))
    assert "—" in text
    assert "₹0.00" not in text


def test_empty_rows_render_nothing():
    assert table_html([]) == ""
    assert table_html(None) == ""


def test_the_legs_are_labelled_by_their_strike():
    text = _text(build_table(call_sr=BREAK, put_sr=REJECT,
                             call_label="ATM CE 24500",
                             put_label="ATM PE 24500"))
    assert "ATM CE 24500" in text and "ATM PE 24500" in text


def test_call_and_put_reads_stay_on_their_own_rows():
    out = rows(call_sr=BREAK, put_sr=REJECT)
    states = {(r["chart"], r["side"]): r["state"] for r in out}
    assert states[("CALL", "resistance")] == "BREAKING"
    assert states[("PUT", "support")] == "REJECTING"
    # neither leg inherits the other's verdict
    assert states[("CALL", "support")] == "NONE"
    assert states[("PUT", "resistance")] == "NONE"


# ── the table and the chart agree ──────────────────────────────────────

@pytest.mark.parametrize("state", sorted(SR_STATE_TONE))
def test_every_charted_state_has_a_meaning_in_the_table(state):
    """The chart can draw a state the table has no wording for only if these
    two vocabularies drift apart. They must not."""
    r = row_for("CALL", {"state": state, "level": 10.0}, ltp=11.0)
    assert r["state"] == state
    assert r["meaning"] and r["meaning"] != "No level in range"


def test_the_table_colours_match_the_chart():
    """A state must not be one colour on the chart and another in the table.

    It was: ACCEPTING is mint (#7fe8b0) on the panel, and a parallel colour map
    here rendered it the same green as BREAKING — indistinguishable at a
    glance. The table now takes the colour from the chart, so they cannot
    drift; this asserts the wiring, not a copied value."""
    from mios_v5.ui.leg_sr_table import state_colour
    for state, (_label, colour) in SR_STATE_TONE.items():
        assert state_colour(state) == colour, state


def test_an_unknown_state_gets_a_neutral_colour():
    from mios_v5.ui.leg_sr_table import state_colour
    assert state_colour("NONE") == "#8c9bad"
    assert state_colour("nonsense") == "#8c9bad"


# ── the table follows the theme, like the charts above it ──────────────

def test_the_table_has_a_light_and_a_dark_chrome():
    from mios_v5.ui.leg_sr_table import chrome
    assert chrome("light") != chrome("dark")
    assert chrome("light")["row_bg"] == "#ffffff"


def test_unknown_theme_falls_back_to_dark():
    from mios_v5.ui.leg_sr_table import chrome
    assert chrome("nonsense") == chrome("dark")
    assert chrome(None) == chrome("dark")


def test_the_rendered_table_takes_the_theme():
    """A dark-only table under a light chart is the same mismatch the chart
    theming just fixed, in miniature.

    Asserts on the ROW BACKGROUND, which is what actually differs. Testing for
    "#ffffff" alone would pass on dark too — dark puts white *text* on its
    header, so the colour appears in both.
    """
    from mios_v5.ui.leg_sr_table import chrome
    light = build_table(call_sr=BREAK, call_ltp=126.6, theme="light")
    dark = build_table(call_sr=BREAK, call_ltp=126.6, theme="dark")
    assert f"background:{chrome('light')['row_bg']}" in light
    assert f"background:{chrome('dark')['row_bg']}" not in light
    assert f"background:{chrome('dark')['row_bg']}" in dark
    assert f"background:{chrome('light')['row_bg']}" not in dark


def test_both_themes_show_the_same_numbers():
    """Only the chrome changes — the read must be identical."""
    args = dict(call_sr=BREAK, put_sr=REJECT, call_ltp=126.6, put_ltp=86.35)
    assert _text(build_table(theme="light", **args)) == \
        _text(build_table(theme="dark", **args))


# ── "NONE" has to say WHICH kind of nothing ────────────────────────────

def test_a_missing_read_is_not_the_same_as_no_level():
    """Regression: both rendered as "No level in range", so a leg whose frame
    was too short to analyse looked identical to one trading in clear air.

    `_publish_atm_legs` only stores a truthy read, and
    `classify_leg_sr_behavior` returns None outright for a short frame — so a
    missing entry means the engine never got to look."""
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason(None) == "unmeasured"
    assert no_level_reason({}) == "unmeasured"
    assert no_level_reason({"state": "NONE"}) == "no_blocks"


def test_blocks_present_but_no_level_says_wrong_side():
    """Support counts only at or below the LTP and resistance only at or
    above, so blocks can exist while none is on the side being tested."""
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason({"state": "NONE"}, zones=[{"mid": 130.0}]) == "wrong_side"
    assert no_level_reason({"state": "NONE"}, zones=[]) == "no_blocks"


def test_a_real_state_reports_no_reason():
    from mios_v5.ui.leg_sr_table import no_level_reason
    assert no_level_reason(BREAK) == "none"


def test_the_reason_reaches_the_rendered_row():
    unmeasured = _text(build_table(call_sr=None, call_ltp=117.25))
    assert "Not measured" in unmeasured

    no_blocks = _text(build_table(call_sr={"state": "NONE"}, call_ltp=117.25))
    assert "28+" in no_blocks, no_blocks

    wrong_side = _text(build_table(call_sr={"state": "NONE"}, call_ltp=117.25,
                                   call_zones=[{"mid": 130.0}]))
    assert "wrong" in wrong_side.lower() or "tested side" in wrong_side


def test_the_bar_threshold_matches_the_detector():
    """`VolumeOrderBlocks(sensitivity)` needs `sensitivity + 13 + 10` bars.
    If that changes, this wording becomes a lie."""
    from mios_v5.ui.leg_sr_table import MIN_BARS_FOR_BLOCKS
    sensitivity = 5                      # what classify_leg_sr_behavior uses
    assert MIN_BARS_FOR_BLOCKS == sensitivity + 13 + 10


def test_a_verdict_still_reads_as_before():
    """The reason must not intrude on a leg that actually has a state.

    Scoped to the CALL row: passing only `call_sr` leaves the PUT genuinely
    unmeasured, so "Not measured" belongs in the table — just not in this row.
    """
    text = _text(build_table(call_sr=BREAK, call_ltp=126.6, call_label="CE",
                             put_label="PE"))
    call_row = text[text.index("CE "):text.index("PE ")]
    assert "Broke through" in call_row
    assert "Not measured" not in call_row and "28+" not in call_row


# ── both sides, for both legs ──────────────────────────────────────────

def test_sides_publishes_each_sides_own_read():
    """The classifier evaluates resistance AND support and used to return only
    the winner. `sides` carries both, so a leg between two levels shows both."""
    from mios_v5.ui.leg_sr_table import rows_for_leg
    sr = {"state": "BUILDING", "side": "resistance", "level": 109.88,
          "sides": {"resistance": {"state": "BUILDING", "side": "resistance",
                                   "level": 109.88},
                    "support": {"state": "REJECTING", "side": "support",
                                "level": 104.20}}}
    out = rows_for_leg("CALL", sr, ltp=109.30)
    assert [(r["side"], r["state"]) for r in out] == [
        ("resistance", "BUILDING"), ("support", "REJECTING")]
    assert out[0]["distance"] == pytest.approx(-0.58)
    assert out[1]["distance"] == pytest.approx(5.10)


def test_a_measured_leg_missing_one_side_says_so():
    """Regression: the put's resistance row claimed "no read published" while
    its support row on the SAME leg showed a live state — the unmeasured/
    no-level ambiguity, one column over."""
    from mios_v5.ui.leg_sr_table import rows_for_leg
    sr = {"state": "BUILDING", "side": "support", "level": 58.83,
          "sides": {"support": {"state": "BUILDING", "side": "support",
                                "level": 58.83}}}
    res, sup = rows_for_leg("PUT", sr, ltp=58.90)
    assert res["reason"] == "side_none"
    assert "resistance" in res["meaning"]
    assert "Not measured" not in res["meaning"]
    assert sup["state"] == "BUILDING"


def test_a_truly_unmeasured_leg_still_says_unmeasured():
    """`side_none` must not swallow the case it was carved out of."""
    from mios_v5.ui.leg_sr_table import rows_for_leg
    for row in rows_for_leg("CALL", None, ltp=109.30):
        assert row["reason"] == "unmeasured"


def test_an_older_read_without_sides_still_renders_both_rows():
    """A cached read from before `sides` existed must not lose a row — the
    headline goes on its own side and the other reports no level."""
    from mios_v5.ui.leg_sr_table import rows_for_leg
    res, sup = rows_for_leg("CALL", BREAK, ltp=126.6)
    assert res["state"] == "BREAKING" and res["side"] == "resistance"
    assert sup["state"] == "NONE" and sup["side"] == "support"


def test_the_table_shows_four_rows_for_two_legs():
    text = _text(build_table(
        call_sr={"state": "BUILDING", "side": "resistance", "level": 109.88,
                 "sides": {"resistance": {"state": "BUILDING",
                                          "side": "resistance", "level": 109.88},
                           "support": {"state": "REJECTING", "side": "support",
                                       "level": 104.20}}},
        call_ltp=109.30, call_label="ATM CE 24250", put_label="ATM PE 24250"))
    assert text.count("ATM CE 24250") == 2
    assert text.count("ATM PE 24250") == 2
    assert "₹109.88" in text and "₹104.20" in text


def test_a_leg_level_reason_is_not_swallowed_by_side_none():
    """Regression: making every empty side say "no level on this side" threw
    away WHY the leg had nothing — the 28-bar and wrong-side diagnoses. The
    leg-level reason wins when the leg found nothing anywhere; `side_none`
    applies only when the other side does have a level."""
    from mios_v5.ui.leg_sr_table import rows_for_leg

    for row in rows_for_leg("CALL", {"state": "NONE"}, ltp=117.25):
        assert row["reason"] == "no_blocks", row
        assert "28+" in row["meaning"]

    for row in rows_for_leg("CALL", {"state": "NONE"}, ltp=117.25,
                            zones=[{"mid": 130.0}]):
        assert row["reason"] == "wrong_side", row


def test_side_none_only_when_the_other_side_has_a_level():
    from mios_v5.ui.leg_sr_table import rows_for_leg
    sr = {"state": "BUILDING", "side": "support", "level": 58.83,
          "sides": {"support": {"state": "BUILDING", "side": "support",
                                "level": 58.83}}}
    res, sup = rows_for_leg("PUT", sr, ltp=58.90)
    assert res["reason"] == "side_none"
    assert sup["reason"] == "none" and sup["state"] == "BUILDING"
