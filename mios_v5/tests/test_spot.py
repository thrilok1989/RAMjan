"""📍 `mios_v5.spot` — the one NIFTY spot precedence.

Four different rules used to decide which number was "spot", and two of the four
read the option chain first. The chain almost always HAS a value, so those panels
never reached the live LTP at all: they moved on the chain's slow cadence while
the header beside them ticked. These tests pin the rule down so it cannot drift
back apart, and pin the *reasons* down too — the age bound and the refusal to
treat `0` as a price are the two places a well-meaning edit would reintroduce a
desync.
"""

from __future__ import annotations

import pytest

from mios_v5 import spot

NOW = 1_775_000_000.0
LIVE, CHAIN, CLOSE = 24610.5, 24555.0, 24480.25


def _state(**kw):
    """A session-state dict with only the keys a case cares about."""
    st = {}
    if "live" in kw:
        st[spot.LIVE_KEY] = kw["live"]
    if "ts" in kw:
        st[spot.LIVE_TS_KEY] = kw["ts"]
    if "chain" in kw:
        st[spot.CHAIN_KEY] = {"underlying": kw["chain"]}
    return st


# ══════════════════════════════════════════════════════════════════════
#  the precedence
# ══════════════════════════════════════════════════════════════════════

def test_a_fresh_live_ltp_wins_over_the_chain():
    """The whole point. The chain is a snapshot from its own last fetch."""
    r = spot.read(_state(live=LIVE, ts=NOW, chain=CHAIN), NOW)
    assert r["price"] == LIVE
    assert r["source"] == "live LTP"
    assert r["stale"] is False


def test_the_chain_is_used_when_there_is_no_live_ltp():
    r = spot.read(_state(chain=CHAIN), NOW)
    assert (r["price"], r["source"]) == (CHAIN, "option chain")


def test_an_aged_out_live_ltp_loses_to_the_chain():
    """⚠️ The bound matters. `_nifty_spot_live` is written once per cycle, so a
    quote older than a couple of cycles means the Dhan call has been failing. The
    chain came from a different endpoint and is the better read at that point —
    preferring the stale LTP unconditionally would trade one desync for another.
    """
    r = spot.read(_state(live=LIVE, ts=NOW - 300, chain=CHAIN), NOW)
    assert (r["price"], r["source"]) == (CHAIN, "option chain")
    assert r["stale"] is True, "the caller must be able to see the LTP aged out"
    assert r["age_s"] == 300.0


def test_an_aged_live_ltp_still_beats_having_nothing():
    """No chain at all — an old number that says it is old is better than a
    blank price box, and the source label carries the warning."""
    r = spot.read(_state(live=LIVE, ts=NOW - 300), NOW)
    assert (r["price"], r["source"]) == (LIVE, "live LTP (stale)")
    assert r["stale"] is True


def test_the_candle_frame_is_the_last_resort():
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"close": [24400.0, CLOSE]})
    r = spot.read({spot.FRAME_KEY: df}, NOW)
    assert (r["price"], r["source"]) == (CLOSE, "last candle close")
    assert r["stale"] is True


def test_nothing_reported_is_none_and_not_zero():
    """A panel that cannot tell `0` from "no data" draws a chart through the
    floor and prints ₹0 next to a live verdict."""
    r = spot.read({}, NOW)
    assert r["price"] is None and r["source"] is None


# ══════════════════════════════════════════════════════════════════════
#  the age bound
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("age,expected", [
    (0.0, "live LTP"),
    (spot.MAX_AGE - 0.1, "live LTP"),
    (spot.MAX_AGE, "live LTP"),           # inclusive — exactly at the bound
    (spot.MAX_AGE + 0.1, "option chain"),
])
def test_the_freshness_bound_is_inclusive(age, expected):
    r = spot.read(_state(live=LIVE, ts=NOW - age, chain=CHAIN), NOW)
    assert r["source"] == expected


def test_a_live_ltp_with_no_timestamp_is_trusted():
    """Not every writer stamps the clock. Treating a missing timestamp as
    infinitely old would silently demote the good path on those cycles."""
    r = spot.read(_state(live=LIVE, chain=CHAIN), NOW)
    assert (r["price"], r["source"], r["age_s"]) == (LIVE, "live LTP", None)


def test_the_clock_is_injectable():
    """`now` exists so the age logic is testable without sleeping. Passing it
    must actually be used rather than quietly ignored for `time.time()`."""
    old = spot.read(_state(live=LIVE, ts=NOW - 300, chain=CHAIN), NOW)
    fresh = spot.read(_state(live=LIVE, ts=NOW - 300, chain=CHAIN), NOW - 299)
    assert old["source"] == "option chain"
    assert fresh["source"] == "live LTP"


# ══════════════════════════════════════════════════════════════════════
#  junk in, no crash out
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("junk", [0, 0.0, -1, -24500.0, "", "  ", "abc",
                                  None, True, False, [], {}, float("nan")])
def test_a_non_price_is_refused_and_falls_through(junk):
    """Every one of these has appeared in session state at some point. A `0`
    from a failed fetch must not outrank a real chain quote."""
    r = spot.read(_state(live=junk, ts=NOW, chain=CHAIN), NOW)
    assert r["price"] == CHAIN, f"{junk!r} was accepted as a price"


def test_a_numeric_string_is_accepted():
    """Dhan hands numbers back as strings often enough that refusing them would
    blank the header on real cycles."""
    assert spot.price(_state(live="24610.5", ts=NOW), NOW) == LIVE


@pytest.mark.parametrize("bad", [None, {}, "not a dict", 7, [1, 2]])
def test_a_junk_chain_does_not_crash(bad):
    st = {spot.LIVE_KEY: LIVE, spot.LIVE_TS_KEY: NOW, spot.CHAIN_KEY: bad}
    assert spot.read(st, NOW)["price"] == LIVE


def test_a_junk_state_object_does_not_crash():
    class Hostile:
        def get(self, _k):
            raise RuntimeError("boom")

    assert spot.read(Hostile(), NOW)["price"] is None
    assert spot.read(None, NOW)["price"] is None


def test_an_empty_frame_is_not_read():
    pd = pytest.importorskip("pandas")
    assert spot.read({spot.FRAME_KEY: pd.DataFrame({"close": []})},
                     NOW)["price"] is None


# ══════════════════════════════════════════════════════════════════════
#  the contract the callers rely on
# ══════════════════════════════════════════════════════════════════════

def test_read_always_reports_the_same_shape():
    """Callers index these keys directly; a missing one on the empty path would
    be an AttributeError on exactly the cycle the data is worst."""
    keys = {"price", "source", "age_s", "stale", "candidates"}
    for st in ({}, _state(chain=CHAIN), _state(live=LIVE, ts=NOW),
               _state(live=LIVE, ts=NOW - 900, chain=CHAIN)):
        assert set(spot.read(st, NOW)) == keys


def test_the_candidates_show_every_reading_for_the_debug_panel():
    """Principle 12 — a computed decision must be inspectable. Seeing all three
    numbers side by side is how the next desync gets diagnosed in one look
    instead of five greps."""
    r = spot.read(_state(live=LIVE, ts=NOW - 5, chain=CHAIN), NOW)
    assert r["candidates"] == {"live": LIVE, "live_age_s": 5.0,
                              "chain": CHAIN, "close": None}


def test_price_is_just_reads_number():
    for st in ({}, _state(chain=CHAIN), _state(live=LIVE, ts=NOW, chain=CHAIN)):
        assert spot.price(st, NOW) == spot.read(st, NOW)["price"]


def test_reading_never_writes_to_the_state_it_was_given():
    """Pure and read-only. A reader that mutates session state turns a display
    fix into a source of truth nobody declared."""
    st = _state(live=LIVE, ts=NOW, chain=CHAIN)
    before = {k: (dict(v) if isinstance(v, dict) else v) for k, v in st.items()}
    spot.read(st, NOW)
    spot.price(st, NOW)
    assert st == before


def test_spot_does_not_import_streamlit_or_the_app():
    """It takes state as a parameter (principle 4), which is what lets every
    panel and the runner share one precedence without a circular import."""
    import ast
    import pathlib

    src = pathlib.Path(spot.__file__).read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas"}
