"""🧲 The dealer magnet on every day — without touching `charm_pin`.

Two properties carry this module:

1. **On expiry day it changes nothing.** `charm_pin` owned the expiry read and
   still does; a byte-for-byte comparison holds it.
2. **Off expiry it reports the same magnet with a weaker instruction.** The level
   is real all week; the expiry-strength drag is not, and claiming it would
   invent an edge out of a calendar.
"""

import pathlib

from mios_v5 import charm_pin as CP
from mios_v5 import dealer_magnet as DM
from mios_v5.ui.charm_pin_panel import charm_pin_html

ROOT = pathlib.Path(__file__).resolve().parents[2]

# ⚠️ Spot within `NEAR_POINTS` (120) of the pin. The first fixture used spot
# 24,583.8 against a 24,450 pin — 134 pts, BEYOND the threshold — so every read
# came back inactive and fourteen tests failed on the fixture rather than the
# code. The threshold is charm_pin's and applies on every day.
_SPOT, _PIN, _CHARM = 24520.0, 24450.0, -619.5


# ══════════════════════════════════════════════════════════════════════
#  1 · charm_pin is untouched and still owns the measurement
# ══════════════════════════════════════════════════════════════════════

def test_charm_pin_still_refuses_off_expiry():
    """The frozen module keeps its original behaviour exactly."""
    assert CP.read(False, _SPOT, _PIN, _CHARM)["active"] is False
    assert CP.read(False, _SPOT, _PIN, _CHARM)["reason"] == "not expiry day"


def test_charm_pin_has_no_dependency_on_the_new_module():
    src = (ROOT / "mios_v5" / "charm_pin.py").read_text()
    assert "dealer_magnet" not in src


def test_the_expiry_read_is_byte_identical():
    """⚠️ The safety property. Expiry day is what `charm_pin` was written for, and
    adding normal days must not move it by a character."""
    mine = DM.read(True, _SPOT, _PIN, _CHARM, pin_label="max pain")
    theirs = CP.read(True, _SPOT, _PIN, _CHARM, pin_label="max pain")
    for key, val in theirs.items():
        assert mine[key] == val, key
    # only the two new labels are added
    assert set(mine) - set(theirs) == {"expiry", "title", "strength"}


def test_the_measurement_is_delegated_not_copied():
    """No second implementation of distance, drift or the near threshold."""
    src = (ROOT / "mios_v5" / "dealer_magnet.py").read_text()
    assert "from .charm_pin import" in src
    assert "NEAR_POINTS" in src
    for copied in ("pn - sp", "abs(dist)", "upward drag"):
        assert copied not in src, f"re-implemented: {copied}"
    assert DM.NEAR_POINTS == CP.NEAR_POINTS


# ══════════════════════════════════════════════════════════════════════
#  2 · it works on a normal day
# ══════════════════════════════════════════════════════════════════════

def test_a_normal_day_now_reports_the_magnet():
    """The whole request. The level is real every day; only its strength is not."""
    got = DM.read(False, _SPOT, _PIN, _CHARM)
    assert got["active"] is True
    assert got["pin"] == _PIN
    assert got["expiry"] is False


def test_the_numbers_are_the_same_on_both_days():
    """Same magnet, same distance, same drift, same charm — only the wording of
    the consequence differs, because only the strength does."""
    a = DM.read(True, _SPOT, _PIN, _CHARM)
    b = DM.read(False, _SPOT, _PIN, _CHARM)
    for key in ("pin", "distance", "drift", "net_charm"):
        assert a[key] == b[key], key


def test_a_normal_day_does_not_claim_expiry_strength():
    """⚠️ The honesty constraint. "Breakouts likely to fade" is an expiry-day
    instruction; repeating it on a Monday is a fabricated edge."""
    got = DM.read(False, _SPOT, _PIN, _CHARM)
    assert "fade" not in got["expect"].lower()
    assert "drags" not in got["sentence"]
    assert "gravitate" in got["sentence"]
    assert got["strength"] == "MODERATE"


def test_expiry_keeps_the_stronger_instruction():
    got = DM.read(True, _SPOT, _PIN, _CHARM)
    assert "fade" in got["expect"].lower()
    assert got["strength"] == "STRONG"


def test_it_is_context_only_on_both_days():
    for day in (True, False):
        assert DM.read(day, _SPOT, _PIN, _CHARM)["context_only"] is True


def test_days_to_expiry_is_reported_when_known_and_omitted_when_not():
    with_days = DM.read(False, _SPOT, _PIN, _CHARM, days_to_expiry=3)
    assert "3 days to expiry" in with_days["sentence"]
    assert with_days["days_to_expiry"] == 3
    without = DM.read(False, _SPOT, _PIN, _CHARM)
    assert "to expiry" not in without["sentence"]
    assert "days_to_expiry" not in without


def test_one_day_is_singular():
    assert "1 day to expiry" in DM.read(False, _SPOT, _PIN, _CHARM,
                                        days_to_expiry=1)["sentence"]


def test_a_far_magnet_is_still_inactive_on_a_normal_day():
    """The `near` threshold is charm_pin's and still applies — a magnet 400 pts
    away is not exerting force on any day."""
    got = DM.read(False, _SPOT, 25000.0, _CHARM)
    assert got["active"] is False
    assert "away" in got["reason"]


def test_a_missing_pin_is_reported_not_invented():
    got = DM.read(False, _SPOT, None, _CHARM)
    assert got["active"] is False
    assert got["reason"] == "no pin strike available"


def test_the_market_picture_wrapper_works_on_both_days():
    mp = {"oi_pin": (_PIN, "heaviest CE+PE at one strike"),
          "vc_exp": {"net_charm": _CHARM}}
    for day in (True, False):
        got = DM.from_market_picture(day, _SPOT, mp)
        assert got["active"] is True and got["pin"] == _PIN
        assert got["expiry"] is day
    assert "gravitate" in DM.from_market_picture(False, _SPOT, mp)["sentence"]


def test_the_pin_choice_is_delegated_to_charm_pin():
    """OI pin first, max pain second — that preference has one owner. Two modules
    disagreeing about which strike is the magnet is worse than showing none."""
    mp = {"oi_pin": (_PIN, "oi"), "vc_exp": {}}
    assert DM.from_market_picture(False, _SPOT, mp, max_pain=99999.0)["pin"] == _PIN
    assert DM.from_market_picture(False, _SPOT, {}, max_pain=24500.0)["pin"] == 24500.0


def test_nothing_here_raises_on_junk():
    for junk in (None, "x", [], {}, True):
        DM.read(False, junk, junk, junk)
        DM.from_market_picture(False, junk, junk if isinstance(junk, dict) else None,
                               junk)


# ══════════════════════════════════════════════════════════════════════
#  3 · the strip
# ══════════════════════════════════════════════════════════════════════

def test_the_expiry_strip_is_unchanged():
    """A read with no `expiry` key renders as expiry — the old default — so a
    caller still using `charm_pin` directly cannot have its output changed by
    upgrading this panel."""
    legacy = CP.read(True, _SPOT, _PIN, _CHARM, pin_label="max pain")
    html = charm_pin_html(legacy)
    assert "Expiry charm-pin" in html
    assert "drags price toward the magnet" in html
    assert "Breakouts likely to <b>fade</b>" in html
    assert "₹24,450" in html and "-619.5L/day" in html


def test_the_normal_day_strip_says_magnet_not_pin():
    html = charm_pin_html(DM.read(False, _SPOT, _PIN, _CHARM,
                                  pin_label="max pain", days_to_expiry=3))
    assert "Dealer magnet" in html
    assert "Expiry charm-pin" not in html
    assert "gravitate toward" in html
    assert "defend</b>, not a ceiling" in html
    assert "3 days to expiry" in html
    # the facts survive
    assert "₹24,450" in html and "-619.5L/day" in html
    assert "below spot — downward drag" in html


def test_both_strips_say_it_is_context_only():
    for r in (CP.read(True, _SPOT, _PIN, _CHARM), DM.read(False, _SPOT, _PIN, _CHARM)):
        assert "does NOT change the" in charm_pin_html(r)


def test_no_strip_when_the_magnet_is_not_near():
    assert charm_pin_html(DM.read(False, _SPOT, 25000.0, _CHARM)) == ""
    assert charm_pin_html(None) == "" and charm_pin_html({}) == ""


# ══════════════════════════════════════════════════════════════════════
#  4 · the consumers moved over
# ══════════════════════════════════════════════════════════════════════

def test_the_trade_card_uses_the_always_on_reader():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "dealer_magnet import from_market_picture" in src
    assert "charm_pin import from_market_picture" not in src


def test_the_greeks_collector_uses_the_always_on_reader():
    """⚠️ The pin gate meant the PINNED regime could never be detected off
    expiry, so a normal day with price sat on the max-OI strike read as RANGE and
    got range weights."""
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "dealer_magnet import read" in src
    assert "from ..charm_pin import read" not in src


def test_the_pinned_regime_is_now_reachable_off_expiry():
    from mios_v5.adaptive_greeks import regime
    pin = DM.read(False, _SPOT, _PIN, _CHARM)
    assert pin["active"] is True
    got, ev = regime({"regime": "SIDEWAYS"}, is_expiry=False, pin=pin)
    assert got == "PINNED", got
    assert ev
