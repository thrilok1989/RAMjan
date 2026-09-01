"""🧭 Dashboard 1 — the NIFTY index cockpit.

Five blocks, five questions about the index. The properties worth testing are
not "does it draw" but the two that make a display panel trustworthy:

1. **It never invents a number.** A missing reading renders `—`, never `0`.
   Zero is a market fact — perfectly balanced flow, a wall that did not move —
   and printing one that was never measured is fabricating data the reader
   cannot tell apart from the real thing.
2. **It never re-derives an owned fact.** `compute_market_picture` owns which
   strike the wall is on; `rank_levels` owns the S/R order. A second
   implementation that disagreed by one strike would be worse than no panel.

The module is pure — data in, HTML out, no streamlit and no session state — so
all of this is testable without a market.
"""

import ast
import pathlib
import re

import pytest

from mios_v5.ui import nifty_cockpit as NC

ROOT = pathlib.Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════════════════
#  1 · it never invents a number
# ══════════════════════════════════════════════════════════════════════

def test_a_missing_reading_is_a_dash_not_a_zero():
    """⚠️ The rule this repo states as `MISSING is not 0`, at the display edge.

    A wall printed as `0.0L` reads as "measured, and empty". A `—` reads as
    "not measured". They must never render the same.
    """
    for v in (None, "", "n/a", float("nan"), [], {}):
        assert NC._n(v) == "—", v
        assert NC._pct(v) == "—", v
        assert NC._lakh(v) == "—", v
        assert NC._doi(v) == "—", v


def test_a_real_zero_still_prints_as_zero():
    """The other half. Zero IS a reading — a wall that genuinely did not move —
    and turning it into `—` would hide a fact just as badly."""
    assert NC._n(0) == "0"
    assert NC._pct(0) == "0%"
    assert "0" in NC._doi(0)
    assert NC._f(0) == 0.0


def test_booleans_are_not_numbers():
    """`float(True)` is 1.0. A flag that leaked into a price field would render
    as a level of ₹1."""
    assert NC._f(True) is None and NC._f(False) is None


def test_every_block_is_empty_rather_than_a_hollow_frame():
    """A card drawn with nothing in it costs screen space to say nothing, and
    reads as "measured, no result" instead of "not measured"."""
    assert NC.price_map_html(None) == ""
    assert NC.oi_walls_html(None) == ""
    assert NC.sr_table_html(None) == ""
    assert NC.sr_table_html([]) == ""
    assert NC.battle_zone_html() == ""


def test_the_collector_drops_blocks_with_nothing_to_say():
    assert NC.cockpit_blocks(None) == {}
    assert NC.cockpit_blocks({}) == {}
    got = NC.cockpit_blocks({"spot": 24583.8})
    assert "price_map" in got                      # spot alone is a reading
    assert "sr_table" not in got


def test_nothing_here_raises_on_junk():
    """A display panel may never take a tab down."""
    for junk in (None, {}, [], "x", 7, {"spot": "abc"},
                 {"oi_ceiling": "not a tuple", "sr_levels": ["x", None, 3]},
                 {"ladder": [{"strike": None}, "junk"], "gate": []}):
        NC.cockpit_blocks(junk)


# ══════════════════════════════════════════════════════════════════════
#  2 · the price map
# ══════════════════════════════════════════════════════════════════════

_PROFILE = {"poc_price": 24592.0, "value_area_high": 24612.0,
            "value_area_low": 24551.0}


def test_the_price_map_is_ordered_by_price_not_by_importance():
    """It is a MAP. Rows sorted by significance cannot be read as one — the
    reader has to do the arithmetic the layout was supposed to do."""
    html = NC.price_map_html(24583.8, _PROFILE, vwap=24570.0,
                             day={"high": 24700.0, "low": 24400.0},
                             prev_day={"prev_high": 24750.0,
                                       "prev_low": 24350.0})
    order = [float(m.replace(",", ""))
             for m in re.findall(r">([\d,]{6,9})<", html)]
    assert order == sorted(order, reverse=True), order


def test_spot_is_marked_in_its_place_in_the_ladder():
    """"Where am I" should be answered by position, not by comparing numbers."""
    html = NC.price_map_html(24583.8, _PROFILE)
    assert "SPOT" in html
    # between VAH (24,612) and VAL (24,551)
    assert html.index("24,612") < html.index("SPOT") < html.index("24,551")


def test_spot_below_every_level_still_gets_a_row():
    """The loop places spot when it first meets a lower level. Below all of
    them there is no such level, and an unplaced spot is a map with no ●."""
    html = NC.price_map_html(1.0, _PROFILE)
    assert "SPOT" in html


def test_the_map_names_the_levels_it_could_not_get():
    """A map with a hole should say which hole. Silence reads as "there is no
    previous day high", which is never true."""
    html = NC.price_map_html(24583.8, _PROFILE)
    assert "not reported" in html
    assert "VWAP" in html and "Prev Day High" in html


def test_distance_from_spot_is_signed():
    """`24,605` means nothing without `+22 away`, and an unsigned distance hides
    which side of price the level is on."""
    assert NC._dist(24605, 24583) == "+22"
    assert NC._dist(24550, 24583) == "-33"
    assert NC._dist(None, 24583) == "—"


# ══════════════════════════════════════════════════════════════════════
#  3 · the OI walls
# ══════════════════════════════════════════════════════════════════════

def test_the_walls_are_read_from_the_market_picture_tuple():
    """`(strike, oi_in_lakhs)` is the shape `compute_market_picture` publishes.
    Taken as-is — no maximum is recomputed here."""
    html = NC.oi_walls_html(24583.8, ceiling=(24600.0, 153.2),
                            floor=(24500.0, 116.9))
    assert "24,600" in html and "24,500" in html
    assert "153.2L" in html and "116.9L" in html


def test_a_wall_that_was_not_reported_says_so():
    html = NC.oi_walls_html(24583.8, ceiling=None, floor=(24500.0, 116.9),
                            ladder=[{"strike": 24500.0}])
    assert "not reported" in html


def test_delta_oi_keeps_its_sign():
    """A wall BUILDING and a wall being unwound are opposite facts. An unsigned
    ΔOI hides which one is happening."""
    assert "+" in NC._doi(340000)
    assert "-" in NC._doi(-340000)


def test_the_strike_sits_between_the_two_sides_in_the_ladder():
    """The strike is the axis both sides are measured against. In the first
    column the reader scans back to it for every comparison."""
    html = NC._ladder_html(
        [{"strike": 24600.0, "ce_oi": 1.5e6, "pe_oi": 1.2e6,
          "ce_doi": 3.4e5, "pe_doi": -1.1e5}], 24600.0, 24583.8)
    assert html.index("CE OI") < html.index("STRIKE") < html.index("PE OI")


def test_the_atm_row_is_marked():
    html = NC._ladder_html([{"strike": 24600.0, "ce_oi": 1e6},
                            {"strike": 24650.0, "ce_oi": 1e6}],
                           24600.0, 24583.8)
    assert "◀" in html


def test_the_ladder_is_ordered_high_strike_first():
    """Same direction as an option chain and as the price map above it. A table
    that runs the other way on the same screen is a misread waiting to happen."""
    html = NC._ladder_html([{"strike": 24500.0, "ce_oi": 1e6},
                            {"strike": 24700.0, "ce_oi": 1e6},
                            {"strike": 24600.0, "ce_oi": 1e6}], None, None)
    assert html.index("24,700") < html.index("24,600") < html.index("24,500")


# ══════════════════════════════════════════════════════════════════════
#  4 · the pin — detection and decision are different facts
# ══════════════════════════════════════════════════════════════════════

_PIN = (24600.0, "heaviest CE+PE at one strike — magnet/pin")
_GATE = {"state": "PINNED", "level": 24600.0,
         "why": ["pinned at ₹24600 — heaviest CE+PE at one strike — "
                 "magnet/pin; no directional edge, WAIT"]}


def test_the_pin_reports_the_gates_verdict_when_it_is_live():
    html = NC.market_pin_html(24584.0, _PIN, _GATE, poc=24592.0,
                              gamma_flip=24573.0)
    assert "24,600" in html
    assert "PINNED" in html and "no directional edge" in html
    assert "24,573" in html and "24,592" in html


def test_a_detected_pin_price_has_walked_away_from_is_not_PINNED():
    """⚠️ The distinction the block exists to keep. `oi_pin` is the DETECTION —
    the coincident CE+PE wall. `gate['state']` is the DECISION — price is close
    enough that every directional read is vetoed.

    Price can walk away while the walls stay put. Collapsing the two would tell
    a trader PINNED when nothing is vetoed.
    """
    html = NC.market_pin_html(24800.0, _PIN, {"state": "CALL"})
    assert "NOT PINNED" in html
    assert "ABOVE PIN" in html


def test_the_side_of_the_pin_is_named():
    assert "ABOVE PIN" in NC.market_pin_html(24700.0, _PIN, None)
    assert "BELOW PIN" in NC.market_pin_html(24500.0, _PIN, None)
    assert "AT PIN" in NC.market_pin_html(24603.0, _PIN, None)


def test_no_pin_at_all_still_draws_the_regime():
    """Absence of a pin is a reading a trader acts on — it means the directional
    logic is live. Drawing nothing would make it indistinguishable from a panel
    that failed."""
    html = NC.market_pin_html(24584.0, None, None)
    assert "NOT PINNED" in html


# ══════════════════════════════════════════════════════════════════════
#  5 · support and resistance
# ══════════════════════════════════════════════════════════════════════

def _lv(side, price, brk, rej, active=False):
    return {"side": side, "price": price, "active": active,
            "probabilities": {"break": brk, "rejection": rej}}


def test_at_most_two_levels_a_side():
    """A ranked list of six is a list nobody finishes, and the fifth-best
    support is not a level anyone trades."""
    levels = [_lv("RESISTANCE", 24600 + i * 10, 45, 55) for i in range(4)]
    levels += [_lv("SUPPORT", 24500 - i * 10, 48, 52) for i in range(4)]
    html = NC.sr_table_html(levels, 24583.8)
    # Counted inside the <table> only. Both the word "Support" and the glyph 🛡
    # also appear in the card's own title ("🛡 Support & resistance"), so
    # counting over the whole string reported three supports for two rows.
    body = html[html.index("<table"):html.index("</table>")]
    assert body.count("🧱") == NC.MAX_PER_SIDE
    assert body.count("🛡") == NC.MAX_PER_SIDE
    assert "4 lower-ranked levels not shown" in html


def test_the_ranking_is_taken_not_recomputed():
    """`sr_intel.rank_levels` owns the order — active first, then confidence,
    then confluence. Re-sorting here would be a second implementation of a
    judgement that already has an owner, and the two would drift."""
    first = _lv("SUPPORT", 24000, 10, 90)
    second = _lv("SUPPORT", 24550, 48, 52)
    html = NC.sr_table_html([first, second], 24583.8)
    assert html.index("24,000") < html.index("24,550")


def test_break_and_rejection_always_travel_together():
    """They are complements. Printing one invites the reader to supply the other
    from a wrong prior."""
    html = NC.sr_table_html([_lv("RESISTANCE", 24605, 45, 55)], 24583.8)
    assert "45%" in html and "55%" in html


def test_an_active_level_says_price_is_at_it():
    html = NC.sr_table_html([_lv("SUPPORT", 24550, 48, 52, active=True)],
                            24551.0)
    assert "AT PRICE" in html


def test_a_level_with_no_odds_still_lists_its_price():
    """Stage 42 may not have graded a level yet. Dropping the row would hide a
    level price is sitting on."""
    html = NC.sr_table_html([{"side": "SUPPORT", "price": 24550}], 24583.8)
    assert "24,550" in html and "—" in html


# ══════════════════════════════════════════════════════════════════════
#  6 · the battle zone
# ══════════════════════════════════════════════════════════════════════

def test_the_battle_zone_names_the_winner():
    html = NC.battle_zone_html({"type": "RESISTANCE", "price": 24605.0},
                               "Contested", {"break": 48, "rejection": 52},
                               24583.8)
    assert "24,605" in html and "CONTESTED" in html
    assert "48%" in html and "52%" in html


def test_a_zone_with_only_a_winner_still_draws():
    assert NC.battle_zone_html(None, "Buyers") != ""


# ══════════════════════════════════════════════════════════════════════
#  7 · it stays a display module
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_engine_no_streamlit_and_no_io():
    """⚠️ Principle 4 and the reason this file can be screenshotted from
    synthetic data: data arrives as parameters. The moment it reads
    `session_state` it stops being testable and starts being a second place
    market facts come from."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "nifty_cockpit.py").read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    for banned in ("streamlit", "requests", "supabase", "pandas", "numpy"):
        assert banned not in mods, banned
    # Attribute access, not a text search: this module's docstring explains
    # why it does not read `session_state`, and grepping finds the explanation.
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_it_escapes_what_it_is_given():
    """Notes and status strings arrive from engines; one of them containing a
    tag must not become markup."""
    html = NC.market_pin_html(24584.0, (24600.0, "<script>x</script>"), _GATE)
    assert "<script>" not in html and "&lt;script&gt;" in html


#: A fully-populated cockpit, so a test can assert on every block at once.
#: Kept beside `BLOCK_ORDER` in spirit: if a block is added and this fixture is
#: not extended, `test_the_block_order_matches_the_questions_it_answers` fails
#: rather than quietly covering nine of ten.
_FULL = {
    "spot": 24583.8, "profile": _PROFILE, "vwap": 24570.4,
    "day": {"high": 24607.0, "low": 24351.0},
    "prev_day": {"prev_high": 24750.0, "prev_low": 24350.0},
    "oi_ceiling": (24600.0, 153.2), "oi_floor": (24500.0, 116.9),
    "oi_pin": _PIN, "gate": _GATE, "gamma_flip": 24573.0, "atm": 24600.0,
    "pcr": 0.76,
    "ladder": [{"strike": 24600.0, "ce_oi": 1.53e7, "pe_oi": 7.47e6,
                "ce_doi": 2.18e6, "pe_doi": 3.29e6}],
    "sr_levels": [_lv("RESISTANCE", 24605, 45, 55, active=True),
                  _lv("SUPPORT", 24550, 48, 52)],
    "battle_zone": {"type": "RESISTANCE", "price": 24605.0},
    "winner": "Contested", "probabilities": {"break": 48, "rejection": 52},
    "bias_rows": [("Price structure", "SIDEWAYS"), ("ΔOI", "Bull"),
                  ("Order flow", "Bear")],
    "overall": "SIDEWAYS", "confidence": 56.0,
    "liq_pools": {"above": [{"price": 24619.0, "touched": False}],
                  "below": [{"price": 24543.0, "touched": True}]},
    "poc_regime": "STABLE", "poc_stability": "HIGH",
    "htf": {"Daily": {"profile": {"vah": 24700.0, "poc": 24592.0,
                                  "val": 24450.0},
                      "structure": {"trend": "bull"}}},
    "external_rows": [("Global", "Bull"), ("India VIX", "12.40")],
    "fii_dii_cash": {"FII": {"date": "08-Aug-2026", "buy": 12480.5,
                             "sell": 16702.3, "net": -4221.8},
                     "DII": {"date": "08-Aug-2026", "buy": 15310.2,
                             "sell": 11290.6, "net": 4019.6}},
    "fii_deriv": {"date": "08-Aug-2026", "fut_index_long": 82450.0,
                  "fut_index_short": 141200.0, "fut_index_net": -58750.0,
                  "opt_index_call_long": 210300.0,
                  "opt_index_put_long": 168900.0,
                  "opt_index_call_short": 189400.0,
                  "opt_index_put_short": 233100.0},
    "flows_bias": "BEAR", "flows_confidence": 38.5, "flows_conflict": True,
    "flows_evidence": ["FII -4,222cr · DII +4,020cr · net -202cr "
                       "(as of 08-Aug-2026, EOD)"],
    "regime": "SIDEWAYS", "need": ["Acceptance", "Signal validity"],
}


def test_the_block_order_matches_the_questions_it_answers():
    """Kept as data so a test can assert the sequence rather than trusting a
    comment, and so the collector cannot silently reorder it."""
    assert NC.BLOCK_ORDER == (
        "price_map", "oi_walls", "market_pin", "sr_table", "battle_zone",
        "bias_stack", "liquidity", "htf", "external", "fii_dii",
        "market_state")
    got = NC.cockpit_blocks(_FULL)
    assert set(got) == set(NC.BLOCK_ORDER), (
        f"blocks that did not render: {set(NC.BLOCK_ORDER) - set(got)}")


def test_the_market_state_stays_last():
    """It is the only line worth anything after reading the ones above it, so a
    new block must never be appended past it."""
    assert NC.BLOCK_ORDER[-1] == "market_state"


# ══════════════════════════════════════════════════════════════════════
#  9 · who controls the market
# ══════════════════════════════════════════════════════════════════════

def test_the_bias_stack_shows_one_line_per_input():
    html = NC.bias_stack_html([("ΔOI", "Bull"), ("Order flow", "Bear"),
                               ("Global", "Bull")], "SIDEWAYS", 56)
    assert html.count("🟢") == 2 and html.count("🔴") == 1
    assert "OVERALL NIFTY BIAS" in html and "56%" in html


def test_the_overall_bias_is_not_averaged_from_the_rows():
    """⚠️ The one thing that would make this block dangerous.

    `overall` is `compute_market_picture`'s own regime. Averaging the rows here
    would produce a second verdict from the same inputs by a different method,
    on the same screen — the exact disagreement the architecture principles open
    by forbidding. Three bull rows with a SIDEWAYS regime must render SIDEWAYS.
    """
    html = NC.bias_stack_html([("a", "Bull"), ("b", "Bull"), ("c", "Bull")],
                              "SIDEWAYS", 51)
    assert "SIDEWAYS" in html
    assert "OVERALL NIFTY BIAS" in html
    body = html[:html.index("OVERALL NIFTY BIAS")]
    assert "BULL" in body                       # the rows still say bull


def test_a_silent_input_is_listed_not_called_neutral():
    """An engine that said nothing and an engine that said "balanced" are
    different facts, and rendering both as NEUTRAL loses the difference."""
    html = NC.bias_stack_html([("ΔOI", "Bull"), ("Dealer DEX", None),
                               ("IV skew", "")], "UP", 60)
    assert "silent" in html and "Dealer DEX" in html and "IV skew" in html


def test_the_bias_stack_is_empty_with_nothing_to_stack():
    assert NC.bias_stack_html([], None) == ""
    assert NC.bias_stack_html([("a", None)], None) == ""


def test_a_confidence_that_was_not_reported_is_simply_absent():
    html = NC.bias_stack_html([("ΔOI", "Bull")], "UP", None)
    assert "OVERALL NIFTY BIAS" in html and "%" not in html


# ══════════════════════════════════════════════════════════════════════
#  10 · liquidity
# ══════════════════════════════════════════════════════════════════════

def test_a_swept_pool_is_not_offered_as_a_target():
    """A pool whose liquidity has been taken is SPENT. Listing it as the next
    target is how a level that already did its job gets traded twice."""
    html = NC.liquidity_html(
        {"above": [{"price": 24619.0, "touched": False}],
         "below": [{"price": 24543.0, "touched": True}]}, 24583.8)
    assert "24,619" in html
    swept = html[html.index("Swept"):]
    assert "24,543" in swept


def test_the_nearest_untouched_pool_is_the_target():
    html = NC.liquidity_html(
        {"above": [{"price": 24590.0, "touched": False}],
         "below": [{"price": 24400.0, "touched": False}]}, 24583.8)
    target = html[html.index("Nearest target"):]
    assert "24,590" in target


def test_liquidity_is_empty_when_nothing_was_measured():
    assert NC.liquidity_html(None, 24583.8) == ""
    assert NC.liquidity_html({}, 24583.8) == ""


# ══════════════════════════════════════════════════════════════════════
#  11 · higher timeframes
# ══════════════════════════════════════════════════════════════════════

def test_the_htf_table_runs_fastest_timeframe_first():
    """A 1H/Monthly disagreement should be a row apart, not a scan away."""
    html = NC.htf_html({
        "Monthly": {"profile": {"poc": 24000.0}, "structure": {"trend": "bull"}},
        "1H": {"profile": {"poc": 24592.0}, "structure": {"trend": "neutral"}},
        "Daily": {"profile": {"poc": 24500.0}, "structure": {"trend": "bull"}}})
    assert html.index(">1H<") < html.index(">Daily<") < html.index(">Monthly<")


def test_the_htf_tally_counts_the_timeframes_it_actually_has():
    """3/5 BULL with only three profiles built would be arithmetic on data that
    does not exist."""
    html = NC.htf_html({
        "1H": {"structure": {"trend": "bull"}},
        "Daily": {"structure": {"trend": "bull"}},
        "Weekly": {"structure": {"trend": "bear"}}})
    assert "2/3 BULL" in html


def test_a_timeframe_with_no_profile_is_absent_not_dashed():
    html = NC.htf_html({"1H": {"structure": {"trend": "bull"}},
                        "Yearly": None, "Monthly": {}})
    assert ">1H<" in html
    assert ">Yearly<" not in html and ">Monthly<" not in html


def test_htf_is_empty_with_no_profiles():
    assert NC.htf_html(None) == "" and NC.htf_html({}) == ""


# ══════════════════════════════════════════════════════════════════════
#  12 · the final state — an observation, never a recommendation
# ══════════════════════════════════════════════════════════════════════

def test_the_state_says_it_is_not_a_recommendation():
    """⚠️ MIOS V5 is decision-SUPPORT. The spec says it and this repo says it:
    no trade recommendation on this dashboard."""
    html = NC.market_state_html(_GATE, "SIDEWAYS")
    assert "PINNED" in html
    assert "not a recommendation" in html
    for word in ("BUY", "SELL", "Enter", "Target", "Stop"):
        assert word not in html, word


def test_the_reason_is_the_gates_own_words():
    """Taken verbatim so the top of this dashboard cannot describe the market
    differently from the panel that decided it."""
    html = NC.market_state_html(_GATE, None)
    assert "no directional edge" in html


def test_what_it_needs_is_read_never_inferred():
    """Guessing that a WAIT needs "acceptance" would put a condition on screen
    no engine asked for, and the trader would wait for the wrong thing."""
    html = NC.market_state_html({"state": "WAIT"}, None,
                                need=["Acceptance", "Signal validity"])
    assert "NEEDS" in html and "Acceptance" in html
    assert "NEEDS" not in NC.market_state_html({"state": "WAIT"}, None)


def test_the_state_is_empty_when_nothing_reported_one():
    assert NC.market_state_html(None, None) == ""
    assert NC.market_state_html({}, "") == ""


# ══════════════════════════════════════════════════════════════════════
#  8 · the collector reads and does not compute
# ══════════════════════════════════════════════════════════════════════

def _v6_src():
    return (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()


def _fn(name):
    return next(n for n in ast.walk(ast.parse(_v6_src()))
                if isinstance(n, ast.FunctionDef) and n.name == name)


def test_the_nifty_tab_is_wired():
    from mios_v5.ui.dashboard_v6 import _TABS
    assert "🧭 NIFTY" in _TABS
    block = _v6_src()
    block = block[block.index("tabs = st.tabs(_TABS)"):
                  block.index("# ── 0 · CHARTS")]
    assert "_nifty_cockpit(st, fr)" in block


def test_the_collector_does_not_pick_the_wall_itself():
    """⚠️ The one thing that would make this dashboard dangerous. The wall
    strikes are `compute_market_picture`'s (`oi_ceiling` / `oi_floor`); a second
    `idxmax` here could put the wall one strike from where every other panel
    shows it, and both would look right."""
    src = _v6_src()
    body = src[src.index("def _oi_ladder"):src.index("def _total_pcr")]
    for banned in ("idxmax", "idxmin", "nlargest", "max(", "sort_values"):
        assert banned not in body, f"_oi_ladder should not pick a wall: {banned}"


def test_the_ladder_is_centred_on_the_published_atm():
    """Not on a locally chosen strike. The ATM is `_atm_pm1_vpfr`'s, which is
    the same one the legs were fetched for."""
    body = _v6_src()
    body = body[body.index("def _nifty_cockpit"):body.index("def _oi_ladder")]
    assert "_atm_pm1_vpfr" in body


def test_the_cockpit_reads_only_published_keys():
    """Every value has an owner that already published it. A `compute_` or
    `calculate_` call here would mean the display layer had started deriving
    market facts."""
    fn = _fn("_nifty_cockpit")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for name in called:
        assert not name.startswith(("compute_", "calculate_", "analyze_")), name


def test_the_cockpit_says_why_it_is_empty():
    """⚪ could not report is a report. A blank tab is indistinguishable from a
    tab that decided there was nothing to say — the misreading that makes a
    working system look broken."""
    fn = _fn("_nifty_cockpit")
    text = " ".join(n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str))
    assert "standing by" in text
    assert "Not reporting yet" in text


def test_a_card_title_is_not_escaped_twice():
    """⚠️ Caught by looking at the render, not by the suite.

    `_card` escapes its own title, so a title passed in pre-escaped as `&amp;`
    became `&amp;amp;` and the panel header read literally
    "SUPPORT &AMP; RESISTANCE". Titles arrive as plain text; escaping is the
    card's job and happens exactly once.
    """
    html = NC.sr_table_html([_lv("SUPPORT", 24550, 48, 52)], 24583.8)
    assert "&amp;amp;" not in html
    assert "&amp;" in html          # the single, correct escape of "&"
    assert "Support & resistance" not in html   # raw & never reaches the page


def test_no_block_title_carries_a_pre_escaped_entity():
    """The same mistake in any other block would look identical. One assertion
    over every title beats four that each cover one."""
    blocks = NC.cockpit_blocks({
        "spot": 24583.8, "profile": _PROFILE, "oi_ceiling": (24600.0, 153.2),
        "oi_floor": (24500.0, 116.9), "oi_pin": _PIN, "gate": _GATE,
        "sr_levels": [_lv("SUPPORT", 24550, 48, 52)],
        "battle_zone": {"price": 24605.0}, "winner": "Contested"})
    assert blocks, "nothing rendered — the fixture stopped being representative"
    for name, html in blocks.items():
        assert "&amp;amp;" not in html, name
        assert "&amp;lt;" not in html, name


# ══════════════════════════════════════════════════════════════════════
#  13 · the colour must survive this repo's actual wording
# ══════════════════════════════════════════════════════════════════════

#: The labels `compute_market_picture` really publishes today, transcribed from
#: the source rather than invented, with the colour each MUST get.
#:
#: ⚠️ This exists because a preview with a made-up label ("PE writers building")
#: rendered grey, and the made-up label was the only reason. The real one reads
#: "Bullish (PE writers building support)" and colours correctly — but that is
#: luck depending on the word "Bullish" surviving a rewording. Pinning the live
#: vocabulary means a rewording that greys a row fails here, not on screen.
_REAL_LABELS = (
    ("Bullish (PE writers building support)", "🟢"),
    ("Bearish (CE writers capping)", "🔴"),
    ("Both building / mixed", "⚪"),
    ("Risk-on", "🟢"),
    ("Risk-off", "🔴"),
)


@pytest.mark.parametrize("label,emoji", _REAL_LABELS)
def test_the_real_labels_this_repo_produces_are_coloured(label, emoji):
    assert NC._emoji_of(label) == emoji, label


def test_a_published_direction_beats_the_wording():
    """The reliable path. `dex_bias` and `skew_bias` publish `bias` as BULL/BEAR
    outright, so their colour never depends on parsing prose."""
    assert NC._emoji_of("Balanced", "BULL") == "🟢"
    assert NC._emoji_of("anything at all", "BEAR") == "🔴"
    assert NC._emoji_of("Bullish (PE writers building)", "NEUTRAL") == "⚪"


def test_a_three_tuple_row_carries_its_direction_through():
    html = NC.bias_stack_html([("Dealer DEX", "Balanced", "BULL")], "UP", 60)
    assert "🟢" in html


def test_two_and_three_tuple_rows_mix_freely():
    """The collector hands over a direction only where an owner published one, so
    both shapes arrive in the same list."""
    html = NC.bias_stack_html(
        [("ΔOI", "Bullish (PE writers building support)"),
         ("IV skew", "Put fear", "BEAR")], "SIDEWAYS", 51)
    assert "🟢" in html and "🔴" in html


def test_the_collector_hands_over_the_directions_it_has():
    """`_bias_rows` must emit 3-tuples, or the direction path is dead code."""
    from mios_v5.ui.dashboard_v6 import _bias_rows
    rows = _bias_rows({"regime": "UP",
                       "dex_bias": {"label": "Balanced", "bias": "BULL"},
                       "skew_bias": {"label": "Put fear", "bias": "BEAR"}})
    by_name = {r[0]: r for r in rows}
    assert len(by_name["Dealer DEX"]) == 3
    assert by_name["Dealer DEX"][2] == "BULL"
    assert by_name["IV skew"][2] == "BEAR"
    assert by_name["Price structure"][2] == "UP"


def test_the_regime_confidence_matches_the_regime():
    """⚠️ Selection, not calculation. Taking a max independently of the regime
    would let a SIDEWAYS verdict carry `p_up` — the number under the verdict
    disagreeing with the verdict."""
    from mios_v5.ui.dashboard_v6 import _regime_confidence
    mp = {"regime": "SIDEWAYS", "p_up": 31.0, "p_down": 24.0, "p_side": 56.0}
    assert _regime_confidence(mp) == 56.0
    assert _regime_confidence({**mp, "regime": "UP"}) == 31.0
    assert _regime_confidence({"regime": "???"}) is None
    assert _regime_confidence({}) is None
