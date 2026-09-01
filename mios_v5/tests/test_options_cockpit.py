"""📈 Dashboard 2 — option / LTP intelligence.

Same two properties that make Dashboard 1 trustworthy, plus one this dashboard
adds:

1. **It never invents a number** — a missing reading is `—`, never `0`.
2. **It never re-derives an owned fact** — `break_probability` and
   `fakeout_probability` are Stage 71.8's, `preferred` is Stage 71.7's. A second
   estimate computed in a display panel is a competing engine wearing a panel's
   clothes.
3. **No Greeks on the default screen.** The spec removes them and keeps them
   behind an expander; nine Greek columns across five strikes is the single
   biggest contributor to the overload this dashboard exists to fix.

Pure module, so all of it is testable without a market.
"""

import ast
import pathlib

import pytest

from mios_v5.ui import options_cockpit as OC

ROOT = pathlib.Path(__file__).resolve().parents[2]

_CALL = {"strike": 24600.0, "ltp": 73.0, "change_pct": -4.2, "volume": 4.1e6,
         "oi": 1.53e7, "doi": 2.18e6, "rvol": 2.0, "cbv": 5.08e8,
         "csv": 5.49e8, "cvd": -4.1e7, "buy_share": 48.1,
         "bid_ask": "1,200 / 1,350", "money_flow": "bear"}
_PUT = {"strike": 24600.0, "ltp": 74.8, "change_pct": 1.9, "volume": 3.8e6,
        "oi": 7.47e6, "doi": 3.29e6, "rvol": 1.9, "cbv": 5.79e8,
        "csv": 5.12e8, "cvd": 6.7e7, "buy_share": 53.1,
        "bid_ask": "900 / 980", "money_flow": "bull"}
_LEGS = {"CALL": _CALL, "PUT": _PUT}

_STRUCT = {
    "CALL": {"ltp": 73.0, "vp_poc": 78.5, "support": 72.2, "resistance": 81.1,
             "structure_score": 47, "momentum": -22.0,
             "acceptance": False, "rejection": True,
             "acceptance_read": {"state": "REJECTING"},
             "break_probability": 42, "fakeout_probability": 67,
             "cbv": 5.08e8, "csv": 5.49e8, "cvd": -4.1e7,
             "flow": {"buy_share": 48.1}},
    "PUT": {"ltp": 74.8, "vp_poc": 73.5, "support": 74.5, "resistance": 86.2,
            "structure_score": 48, "momentum": -7.0,
            "acceptance": True, "rejection": False,
            "acceptance_read": {"state": "ACCEPTING"},
            "break_probability": 42, "fakeout_probability": 67,
            "cbv": 5.79e8, "csv": 5.12e8, "cvd": 6.7e7,
            "flow": {"buy_share": 53.1}},
}

_ENERGY = {"ready": True, "preferred": "PUT", "confidence": 58,
           "sides": {"CALL": {"energy": 39, "spike": 61, "strength": "Weak",
                              "spike_band": "Healthy", "cvd": -4.1e7},
                     "PUT": {"energy": 50, "spike": 65, "strength": "Healthy",
                             "spike_band": "Healthy", "cvd": 6.7e7}}}

_LADDER = [
    {"strike": 24700.0, "ce_ltp": 34.4, "pe_ltp": 136.7, "ce_doi": 9.7e5,
     "pe_doi": 1.28e6},
    {"strike": 24600.0, "ce_ltp": 73.2, "pe_ltp": 74.7, "ce_doi": 2.18e6,
     "pe_doi": 3.29e6, "ce_cvd": -4.1e7, "pe_cvd": 6.7e7,
     "ce_flow": "BEAR", "pe_flow": "BULL"},
    {"strike": 24500.0, "ce_ltp": 135.1, "pe_ltp": 36.5, "ce_doi": 3.4e5,
     "pe_doi": 3.73e6},
]

_FULL = {"expiry": "2026-08-13", "atm": 24600.0, "spot": 24583.8,
         "legs": _LEGS, "ladder": _LADDER, "energy": _ENERGY,
         "structures": _STRUCT, "flows": _STRUCT, "flow_verdict": "PUT"}


# ══════════════════════════════════════════════════════════════════════
#  1 · nothing is invented
# ══════════════════════════════════════════════════════════════════════

def test_every_block_is_empty_rather_than_a_hollow_frame():
    assert OC.option_header_html() == ""
    assert OC.leg_cards_html(None) == ""
    assert OC.premium_ladder_html(None) == ""
    assert OC.premium_energy_html(None) == ""
    assert OC.premium_structure_html(None) == ""
    assert OC.option_flow_html(None) == ""
    assert OC.greeks_table_html(None) == ""


def test_the_collector_drops_blocks_with_nothing_to_say():
    assert OC.cockpit_blocks(None) == {}
    assert OC.cockpit_blocks({}) == {}


def test_a_missing_premium_reads_as_a_dash():
    """A premium of `₹0.00` and a premium nobody quoted are different facts."""
    html = OC.leg_cards_html({"CALL": {"strike": 24600.0, "ltp": None}})
    assert "—" in html and "₹0" not in html


def test_nothing_here_raises_on_junk():
    for junk in (None, {}, [], "x", 7,
                 {"legs": "not a dict", "ladder": ["junk", None]},
                 {"structures": {"CALL": "no"}, "energy": []},
                 {"ladder": [{"strike": None}], "flows": 3}):
        OC.cockpit_blocks(junk)


def test_a_frozen_mapping_is_still_a_side():
    """⚠️ Stage 71.95 freezes per-side values as `MappingProxyType`, which is not
    a dict subclass. Four bugs in this repo have been that exact confusion."""
    from types import MappingProxyType
    legs = MappingProxyType({"CALL": MappingProxyType(dict(_CALL))})
    assert OC.leg_cards_html(legs) != ""


# ══════════════════════════════════════════════════════════════════════
#  2 · the two legs are comparable
# ══════════════════════════════════════════════════════════════════════

def test_both_legs_show_the_same_rows_in_the_same_order():
    """A trader reads ACROSS. Two cards with different row orders force them to
    find every field twice."""
    html = OC.leg_cards_html(_LEGS)
    labels = [lbl for lbl, _k, _f in OC.LEG_ROWS]
    call = html[html.index("CALL"):html.index("PUT")]
    put = html[html.index("PUT"):]
    for block in (call, put):
        seen = [l for l in labels if l in block]
        assert seen == [l for l in labels if l in call], "row order differs"


def test_cvd_sign_is_coloured_on_the_leg_card():
    """A negative CVD in the same grey as a positive one is the reading nobody
    sees."""
    html = OC.leg_cards_html(_LEGS)
    assert OC.BEAR in html and OC.BULL in html


def test_the_option_header_carries_expiry_strike_and_both_premiums():
    html = OC.option_header_html("2026-08-13", 24600.0, _LEGS, 24583.8)
    assert "2026-08-13" in html and "24,600" in html
    assert "73.00" in html and "74.80" in html


def test_the_header_stands_aside_with_no_expiry_and_no_strike():
    assert OC.option_header_html(None, None, _LEGS) == ""


# ══════════════════════════════════════════════════════════════════════
#  3 · no Greeks by default
# ══════════════════════════════════════════════════════════════════════

_GREEK_WORDS = ("Delta", "Gamma", "Vega", "Theta", "Charm", "Vanna",
                "delta", "gamma", "vega", "theta")


def test_no_greek_appears_on_any_default_block():
    """⚠️ The spec's clearest instruction. Nine Greek columns across five strikes
    is the single biggest contributor to the overload this dashboard removes."""
    for name, html in OC.cockpit_blocks(_FULL).items():
        for word in _GREEK_WORDS:
            assert word not in html, f"{word} leaked into {name}"


def test_the_greeks_are_still_available_behind_the_expander():
    """Removed from the default view, not deleted — a trader who wants delta on
    expiry day should not have to read the chain on another tab."""
    html = OC.greeks_table_html([
        {"strike": 24600.0, "ce_delta": 0.512, "pe_delta": -0.488,
         "ce_gamma": 0.0011, "pe_gamma": 0.0011, "ce_vega": 8.4,
         "pe_vega": 8.4, "ce_theta": -12.1, "pe_theta": -11.8}])
    assert "0.512" in html and "-0.488" in html


def test_the_greeks_table_is_not_in_the_block_order():
    """It must be drawn by the collector inside an expander, never as a block —
    a block would put it on the default screen."""
    assert "greeks" not in " ".join(OC.BLOCK_ORDER)


# ══════════════════════════════════════════════════════════════════════
#  4 · the ladder
# ══════════════════════════════════════════════════════════════════════

def test_the_strike_sits_between_the_two_sides():
    html = OC.premium_ladder_html(_LADDER, 24600.0)
    assert html.index("CE LTP") < html.index("STRIKE") < html.index("PE LTP")


def test_the_ladder_runs_high_strike_first():
    html = OC.premium_ladder_html(_LADDER, 24600.0)
    assert html.index("24,700") < html.index("24,600") < html.index("24,500")


def test_the_atm_row_is_marked():
    assert "◀" in OC.premium_ladder_html(_LADDER, 24600.0)


def test_a_wing_strike_with_no_published_flow_shows_a_dash_not_a_zero():
    """Stage 71.8 publishes structure for the strikes it validated. A wing with
    no CVD is an honest hole; a `0` would read as balanced flow."""
    html = OC.premium_ladder_html(_LADDER, 24600.0)
    rows = html.split("<tr")
    wing = next(r for r in rows if "24,700" in r)
    assert "—" in wing


# ══════════════════════════════════════════════════════════════════════
#  5 · energy and flow are read, not derived
# ══════════════════════════════════════════════════════════════════════

def test_the_preferred_side_is_stage_71_7s_own_verdict():
    """⚠️ Comparing the two CVDs here would be a second opinion on a question
    Stage 71.7 already answers — and the two would disagree exactly when it
    mattered. CALL has the worse energy AND the negative CVD, and the panel still
    prints whatever `preferred` says."""
    html = OC.premium_energy_html({**_ENERGY, "preferred": "CALL"})
    assert "PREMIUM EDGE" in html
    edge = html[html.index("PREMIUM EDGE"):]
    assert "CALL" in edge and "PUT" not in edge


def test_no_edge_is_rendered_as_an_answer():
    """"No edge" is a real reading a trader acts on, not a blank."""
    html = OC.premium_energy_html({**_ENERGY, "preferred": None})
    assert "NO EDGE" in html


def test_both_energy_and_spike_are_shown_for_both_sides():
    """They routinely point opposite ways — participation healthy, expansion
    dead — so the second is not the one to cut for space."""
    html = OC.premium_energy_html(_ENERGY)
    for v in ("39%", "61%", "50%", "65%"):
        assert v in html


def test_option_flow_shows_both_sides_of_the_book():
    html = OC.option_flow_html(_STRUCT, "PUT")
    assert "Cum buy" in html and "Cum sell" in html and "CVD" in html
    assert "OPTION FLOW" in html


# ══════════════════════════════════════════════════════════════════════
#  6 · premium structure
# ══════════════════════════════════════════════════════════════════════

def test_the_structure_card_uses_the_premiums_own_levels():
    """A premium has support and resistance of its own, in rupees. That pair is
    what a leg trade is managed against — not the index's levels."""
    html = OC.premium_structure_html(_STRUCT)
    assert "72.20" in html and "81.10" in html      # CALL support / resistance
    assert "78.50" in html                          # CALL premium POC


def test_the_two_probabilities_are_stage_71_8s():
    html = OC.premium_structure_html(_STRUCT)
    assert "42%" in html and "67%" in html


def test_a_high_fakeout_probability_is_flagged():
    """67% printed in the same grey as a support level is a warning nobody
    reads."""
    html = OC.premium_structure_html(_STRUCT)
    assert OC.WARN in html


def test_acceptance_renders_as_the_word_not_a_boolean():
    """"REJECTING" and "False" are the same fact worded very differently, and
    only one of them is legible."""
    html = OC.premium_structure_html(_STRUCT)
    assert "REJECTING" in html and "ACCEPTING" in html
    assert "False" not in html and "True" not in html


def test_acceptance_falls_back_to_the_flags_when_no_word_was_published():
    html = OC.premium_structure_html(
        {"CALL": {"ltp": 73.0, "acceptance": True, "rejection": False}})
    assert "ACCEPTING" in html


# ══════════════════════════════════════════════════════════════════════
#  7 · it stays a display module
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_engine_no_streamlit_and_no_io():
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "options_cockpit.py").read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    for banned in ("streamlit", "requests", "supabase", "pandas", "numpy"):
        assert banned not in mods, banned
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_it_escapes_what_it_is_given():
    html = OC.option_header_html("<script>x</script>", 24600.0, _LEGS)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_no_block_title_is_escaped_twice():
    for name, html in OC.cockpit_blocks(_FULL).items():
        assert "&amp;amp;" not in html, name


def test_the_block_order_matches_the_questions_it_answers():
    assert OC.BLOCK_ORDER == ("option_header", "leg_cards", "premium_ladder",
                              "premium_energy", "premium_structure",
                              "option_flow")
    got = OC.cockpit_blocks(_FULL)
    assert set(got) == set(OC.BLOCK_ORDER), (
        f"did not render: {set(OC.BLOCK_ORDER) - set(got)}")


def test_it_draws_nothing_about_the_index():
    """The whole reason for two dashboards. No spot, no regime, no index level —
    that read is Dashboard 1's and repeating it is the duplication being removed.
    """
    blocks = OC.cockpit_blocks(_FULL)
    joined = " ".join(blocks.values())
    for word in ("SIDEWAYS", "Nifty price map", "Battle zone", "OI walls",
                 "Gamma flip", "VWAP", "PCR"):
        assert word not in joined, word


# ══════════════════════════════════════════════════════════════════════
#  8 · the collector
# ══════════════════════════════════════════════════════════════════════

def _v6_src():
    return (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()


def test_the_options_tab_is_wired():
    from mios_v5.ui.dashboard_v6 import _TABS
    assert "📈 OPTIONS" in _TABS
    block = _v6_src()
    block = block[block.index("tabs = st.tabs(_TABS)"):
                  block.index("# ── 0 · CHARTS")]
    assert "_options_cockpit(st, fr)" in block


def test_the_tuple_keyed_structures_are_rekeyed_by_side():
    """⚠️ `_premium_structures` is keyed by `(side, strike)`. Handing the tuple
    keys to a consumer that reads `{side}` yields nothing for every field —
    present, wrong shape, no error — which is how both legs once rendered the
    same raw dict into a Telegram message."""
    from mios_v5.ui.dashboard_v6 import _by_side
    got = _by_side({("CALL", 24600.0): {"ltp": 73.0},
                    ("PUT", 24600.0): {"ltp": 74.8}})
    assert set(got) == {"CALL", "PUT"}
    assert got["CALL"]["ltp"] == 73.0
    assert got["CALL"]["strike"] == 24600.0


def test_rekeying_keeps_the_first_strike_per_side():
    """The picker publishes the chosen strike first; a wing must not overwrite
    the leg actually being traded."""
    from mios_v5.ui.dashboard_v6 import _by_side
    got = _by_side({("CALL", 24600.0): {"ltp": 73.0},
                    ("CALL", 24700.0): {"ltp": 34.4}})
    assert got["CALL"]["ltp"] == 73.0


def test_rekeying_survives_junk():
    from mios_v5.ui.dashboard_v6 import _by_side
    for junk in (None, {}, "x", 7, {"CALL": "no"}, {(): {}}, {("X", 1): {}}):
        assert isinstance(_by_side(junk), dict)


def test_the_flow_word_is_the_sign_and_not_a_threshold():
    """A positive cumulative delta means buyers were adding — the sign IS the
    reading. Anything with a threshold in it belongs to Stage 71.7."""
    from mios_v5.ui.dashboard_v6 import _flow_of
    assert _flow_of({"cvd": 1.0}) == "BULL"
    assert _flow_of({"cvd": -1.0}) == "BEAR"
    assert _flow_of({"cvd": 0}) == "FLAT"
    assert _flow_of({}) is None and _flow_of(None) is None


def test_the_collector_does_not_pick_a_maximum():
    """The chain projection must stay a projection. An `idxmax` here would make
    this a second opinion on which strike matters."""
    src = _v6_src()
    body = src[src.index("def _premium_ladder"):src.index("def _flow_of")]
    for banned in ("idxmax", "idxmin", "nlargest", "sort_values"):
        assert banned not in body, banned


def test_the_collector_reads_only_published_keys():
    fn = next(n for n in ast.walk(ast.parse(_v6_src()))
              if isinstance(n, ast.FunctionDef) and n.name == "_options_cockpit")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    for name in called:
        assert not name.startswith(("compute_", "calculate_", "analyze_")), name


def test_the_greeks_are_drawn_inside_an_expander():
    src = _v6_src()
    body = src[src.index("def _options_cockpit"):src.index("def _by_side")]
    assert "st.expander" in body
    exp = body[body.index("st.expander"):]
    assert "greeks" in exp.lower()


def test_the_options_tab_points_at_the_charts_tab_rather_than_redrawing():
    """Block 7 of the spec is the synchronised charts, and they already exist on
    the Charts tab. A second copy here would be the duplication being removed."""
    src = _v6_src()
    body = src[src.index("def _options_cockpit"):src.index("def _by_side")]
    assert "_terminal_chart" not in body
    assert "Charts" in body


def test_the_options_tab_says_why_it_is_empty():
    src = _v6_src()
    body = src[src.index("def _options_cockpit"):src.index("def _by_side")]
    assert "standing by" in body and "Not reporting yet" in body


def test_the_row_helper_does_not_shadow_the_modules_number_parser():
    """⚠️ Caught in review: the chain-row reader was first written as `_num`,
    which is already a module-level float parser used throughout this file. The
    second definition shadowed the first for every function below it."""
    src = _v6_src()
    tree = ast.parse(src)
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert names.count("_num") == 1, "two _num definitions — one shadows the other"
    assert "_row_num" in names


# ══════════════════════════════════════════════════════════════════════
#  9 · three defects the render caught, not the suite
# ══════════════════════════════════════════════════════════════════════

def test_one_unit_for_the_whole_delta_oi_column():
    """⚠️ The ladder printed `+80,000` directly beneath `+21.8L`, so comparing two
    rows of the same column meant converting units in your head. Lakh is the unit
    Indian option OI is quoted in, so every row uses it."""
    assert OC._lakh_signed(80000) == "+0.8L"
    assert OC._lakh_signed(2.18e6) == "+21.8L"
    assert OC._lakh_signed(-3.4e5) == "-3.4L"
    assert OC._lakh_signed(None) == "—"


def test_the_ladder_column_never_mixes_units():
    html = OC.premium_ladder_html(
        [{"strike": 24600.0, "ce_doi": 80000, "pe_doi": 2.18e6},
         {"strike": 24550.0, "ce_doi": 3.4e5, "pe_doi": 5.24e6}], 24600.0)
    import re
    # every ΔOI cell ends in L — no bare thousands separators in that column
    assert "+80,000" not in html
    assert "+0.8L" in html and "+21.8L" in html


def test_buy_share_is_found_where_stage_71_8_actually_puts_it():
    """⚠️ It is nested inside `flow`, not at the top level, so the flat read
    printed — for a value that was right there in the payload."""
    html = OC.option_flow_html({"CALL": {"cvd": 1.0,
                                         "flow": {"buy_share": 48.1}}}, None)
    assert "48%" in html


def test_a_top_level_buy_share_still_works():
    """Both shapes accepted — `_leg_quotes` flattens it, Stage 71.8 nests it."""
    html = OC.option_flow_html({"PUT": {"cvd": 1.0, "buy_share": 53.1}}, None)
    assert "53%" in html


def test_the_money_flow_row_is_populated_from_the_published_cvd():
    """The card and the ladder row for one leg must not say different things
    about it, so both read the same published sign."""
    from mios_v5.ui.dashboard_v6 import _flow_of, _leg_quotes
    legs = _leg_quotes(None, 24600.0, {"CALL": {"cvd": -4.1e7},
                                       "PUT": {"cvd": 6.7e7}})
    assert legs["CALL"]["money_flow"] == "BEAR"
    assert legs["PUT"]["money_flow"] == "BULL"
    assert legs["CALL"]["money_flow"] == _flow_of({"cvd": -4.1e7})
