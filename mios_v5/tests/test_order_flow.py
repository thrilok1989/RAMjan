"""Order Flow Family — one vote from seven views of the same tape."""

import os
import re

from mios_v5 import order_flow as of


# ── the binding rule: V6 must never re-implement a V5 calculation ───────
def test_no_duplicate_order_flow_engine_exists():
    """`money_flow_v6()`, `cvd_v6()`, `delta_v6()` and friends must not exist.

    A second implementation of CVD is not merely waste — it is a second
    ANSWER, and the two will drift. V5 is the calculation layer.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    banned = re.compile(
        r"def\s+(money_flow|cvd|delta|csv|cbv|volume|vob|mfp)_v6\s*\(", re.I)
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        if "tests" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path, encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if banned.search(line):
                        hits.append(f"{fn}:{i}")
    assert not hits, "duplicate order-flow engine: " + "; ".join(hits)


def test_v6_never_fetches_its_own_data():
    """MIOS reads the caches the app already filled. A second fetch would be a
    second rate-limit budget and a second, different answer."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    banned = re.compile(r"^\s*(import\s+requests|from\s+requests|"
                        r"import\s+urllib|import\s+yfinance|"
                        r"from\s+yfinance)")
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        if "tests" in dirpath:
            continue
        for fn in files:
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                for i, line in enumerate(fh, 1):
                    if banned.match(line):
                        hits.append(f"{fn}:{i} {line.strip()}")
    assert not hits, "mios_v5 must not fetch: " + "; ".join(hits)


# ── the family collapses to ONE vote ────────────────────────────────────
def test_the_family_is_one_vote_not_seven():
    """Seven views of the same tape, voting separately, count the tape seven
    times — which is how one order book outvotes the dealer positioning."""
    f = of.family({"money_flow": "BULL", "cvd": "BULL", "candle_delta": "BULL",
                   "cbv": "BULL", "csv": "BULL", "vob": "BULL"})
    assert f["single_vote"] is True
    assert f["family"] == "orderflow"
    assert set(f) >= {"direction", "strength", "reliability", "confidence"}


def test_a_unanimous_bullish_tape_reads_bullish():
    f = of.family({"money_flow": "BULL", "cvd": "BULL", "candle_delta": "BULL",
                   "cbv": "BULL", "csv": "BULL", "vob": "BULL",
                   "volume": {"mult": 1.8}})
    assert f["direction"] == "BULLISH"
    assert f["strength"] >= 45
    assert f["agreement"] == "6/6"


def test_a_split_tape_refuses_to_lean():
    f = of.family({"money_flow": "BULL", "cvd": "BEAR",
                   "candle_delta": "BULL", "vob": "BEAR"})
    assert f["direction"] == "NEUTRAL"
    # and a neutral family cannot claim confidence
    assert f["confidence"] <= f["strength"]


# ── volume has no direction ─────────────────────────────────────────────
def test_volume_never_votes_on_direction():
    """A big bar is not bullish, it is loud. Making volume directional would
    be casting a ballot on magnitude."""
    assert "volume" not in of.MEMBERS
    assert "volume" in of.NON_DIRECTIONAL

    up = of.family({"cvd": "BULL", "volume": {"mult": 3.0}})
    down = of.family({"cvd": "BEAR", "volume": {"mult": 3.0}})
    assert up["direction"] == "BULLISH" and down["direction"] == "BEARISH"
    # identical magnitude effect either way
    assert up["strength"] == down["strength"]
    assert up["reliability"] == down["reliability"]


def test_thin_volume_lowers_reliability_not_direction():
    loud = of.family({"cvd": "BULL", "money_flow": "BULL",
                      "volume": {"mult": 2.0}})
    thin = of.family({"cvd": "BULL", "money_flow": "BULL",
                      "volume": {"mult": 0.4}})
    assert loud["direction"] == thin["direction"] == "BULLISH"
    assert loud["strength"] == thin["strength"]
    assert thin["reliability"] < loud["reliability"]


# ── reliability reflects coverage, because the members are correlated ───
def test_two_members_cannot_speak_with_seven_members_authority():
    """These members are correlated by construction, so six agreeing is much
    weaker evidence than six INDEPENDENT families agreeing."""
    thin = of.family({"cvd": "STRONG_BULL"})
    full = of.family({"money_flow": "BULL", "cvd": "BULL", "vob": "BULL",
                      "candle_delta": "BULL", "cbv": "BULL", "csv": "BULL"})
    assert thin["reliability"] < full["reliability"]
    assert thin["confidence"] < full["confidence"]


def test_confidence_never_exceeds_reliability():
    """A hard lean read off two of seven members is a strong reading of very
    little, and must not present as certainty."""
    for readings in ({"cvd": "STRONG_BULL"},
                     {"cvd": "STRONG_BEAR", "candle_delta": "STRONG_BEAR"},
                     {"money_flow": "BULL", "cvd": "BULL", "vob": "BULL"}):
        f = of.family(readings)
        assert f["confidence"] <= f["reliability"], readings


# ── a member that did not report is not a neutral member ────────────────
def test_silence_is_not_neutrality():
    """Counting an absent member as "neutral" quietly inflates coverage, and
    coverage is what reliability is built on."""
    assert of.member_sign(None) is None
    assert of.member_sign("") is None
    assert of.member_sign({}) is None
    assert of.member_sign("NEUTRAL") == 0.0     # reported, and flat

    f = of.family({"cvd": "BULL"})
    assert f["reported"] == 1
    assert "money_flow" in f["missing"]


def test_nothing_reported_is_safe():
    f = of.family(None)
    assert f["direction"] == "NEUTRAL"
    assert f["strength"] == f["reliability"] == f["confidence"] == 0
    assert "No order-flow member has reported yet" in f["summary"]


# ── the shapes the app's caches actually use ────────────────────────────
def test_member_sign_reads_every_shape_the_caches_use():
    assert of.member_sign("💰 Entering") == 1.0
    assert of.member_sign("🏃 Leaving") == -1.0
    assert of.member_sign("🚀 BUILDING") == 1.0
    assert of.member_sign("🌫️ FADING") == -1.0
    assert of.member_sign(1_234_567) == 1.0        # a signed delta
    assert of.member_sign(-42.5) == -1.0
    assert of.member_sign(0) == 0.0
    assert of.member_sign({"direction": "BEAR"}) == -1.0
    assert of.member_sign({"state": "entering"}) == 1.0
    assert of.member_sign({"net": -12.0}) == -1.0
    assert of.member_sign("something unparseable") is None


def test_display_rows_name_every_member_including_the_silent_ones():
    rows = of.display_rows(of.family({"cvd": "BULL"}))
    names = {r["name"] for r in rows}
    assert "Cvd" in names and "Money Flow" in names and "Volume" in names
    silent = next(r for r in rows if r["name"] == "Money Flow")
    assert silent["reported"] is False and silent["direction"] == "—"
    vol = next(r for r in rows if r["name"] == "Volume")
    assert "direction" in (vol["note"] or "")
    assert of.display_rows(None) == []


# ── Stage 53 still sees exactly one order-flow family ───────────────────
def test_stage_53_has_one_orderflow_family_and_no_loose_members():
    from mios_v5.evidence import EXCLUDED, FAMILIES

    assert "orderflow" in FAMILIES
    # the descriptive order-flow engines must never appear as extra voters
    voters = {e for members in FAMILIES.values() for e in members}
    for engine in ("stage43_absorption", "stage48_market_state",
                   "stage50_ltp_behaviour", "stage44_flow_shift"):
        assert engine not in voters or engine in EXCLUDED, engine


def test_the_descriptive_flow_engines_stay_non_directional():
    """Absorption, Market State and LTP Behaviour describe the same tape the
    order-flow family already voted on. If they leaned too, that tape would be
    counted again — once per describer."""
    import inspect

    from mios_v5.engines import stage43_absorption, stage48_market_state
    for mod in (stage43_absorption, stage48_market_state):
        src = inspect.getsource(mod)
        assert "bias=Bias.NONE" in src, mod.__name__


def test_the_panel_shows_what_the_family_is_standing_on():
    """A family speaking from two of seven looks confident until you can see
    the other five are silent."""
    from mios_v5.ui.order_flow_panel import family_html

    html = family_html("ATM Call", of.family({"cvd": "BULL",
                                              "volume": {"mult": 1.8}}))
    assert "ATM Call" in html
    for label in ("STRENGTH", "RELIABILITY", "CONFIDENCE"):
        assert label in html
    # the silent members are listed, not hidden
    assert "Money Flow" in html and "—" in html
    assert "reporting" in html
    assert family_html("x", None)          # empty renders rather than raising


def test_the_dashboard_reads_the_leg_caches_it_already_has():
    """Every member here comes from a store V5 filled. The point of the family
    is that there is nowhere else for these numbers to come from."""
    from mios_v5.ui.dashboard_v6 import _leg_flow_readings

    class _St:
        def __init__(self, state):
            self.session_state = state

    st = _St({
        "_leg_bias_cache": ([{"Leg": "ATM CE 24250", "MFP": "🔴 BEAR",
                              "CVD": "🟢 BULL", "Div": "⚪ NEUTRAL"}], None),
        "_atm_leg_ltf_delta": {"CE 24250": {"buy_total": 62397010,
                                            "sell_total": 45061055,
                                            "delta_pct": 16.1}},
        "_atm_leg_vob_volume": {"CE 24250": [{"status": "BUILDING"},
                                             {"status": "FADING"}]},
    })
    r = _leg_flow_readings(st, "ATM CE 24250")
    assert of.member_sign(r["money_flow"]) == -1.0
    assert of.member_sign(r["cvd"]) == 1.0
    assert r["cbv"] == 62397010
    # CSV is sell pressure — negated, so more selling reads bearish rather
    # than a big positive number reading as a bid
    assert r["csv"] == -45061055
    assert _leg_flow_readings(st, None) == {}


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"order flow family tests passed ({len(fns)})")
