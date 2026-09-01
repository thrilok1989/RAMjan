"""Stage 71.8 — Premium Strike Selection & Validation.

The stage answers *is this strike worth trading*, and most of these tests guard
the boundary rather than the arithmetic — because the boundary is what keeps the
71.7 / 71.8 / 72 split from collapsing back into one engine:

1. **It never picks the strike.** Disagreement with the busiest strike is
   reported; the selection is untouched.
2. **It never re-derives 71.7.** Side energy, behaviour and preference are read.
3. **It never says buy, sell, enter or exit.** That is Stage 72's, and Stage 72
   does not exist.
"""

import inspect
import pathlib

import pytest

from mios_v5 import strike_validation as SV
from mios_v5 import premium_energy as PE
from mios_v5.ui.strike_validation_panel import strike_validation_html


# ── fixtures ────────────────────────────────────────────────────────────

def _chain(atm=24250.0, gap=50.0, busiest_ce=24250.0, busiest_pe=24250.0):
    """Seven strikes, ATM±3, with volume peaking where the args say."""
    rows = []
    for k in range(-3, 4):
        s = atm + k * gap
        rows.append({
            "Strike": s,
            "totalTradedVolume_CE": 90000.0 if abs(s - busiest_ce) < 0.5 else 9000.0,
            "totalTradedVolume_PE": 90000.0 if abs(s - busiest_pe) < 0.5 else 9000.0,
            "openInterest_CE": 500000.0, "openInterest_PE": 500000.0,
            "changeinOpenInterest_CE": 1000.0, "changeinOpenInterest_PE": 1000.0,
            "bidQty_CE": 750.0, "askQty_CE": 750.0,
            "bidQty_PE": 750.0, "askQty_PE": 750.0,
        })
    return rows


def _fr(**over):
    fr = {
        "spot": 24280.0,
        "dealer_levels": {"dealer_wall": 24200.0, "gamma_flip": 24150.0},
        "htf": {"alignment": {"score": 78, "bias": "BULL"}},
        "reaction": {"state": "CONFIRMED_BREAKOUT"},
        "reaction_zone": {"bias": "BULLISH", "label": "demand zone"},
        "absorption": {"behaviour": "BUYER ABSORPTION"},
        "charm_pin": {},
    }
    fr.update(over)
    return fr


def _premium(call_energy=78, put_energy=22, preferred="CALL"):
    """A Stage 71.7-shaped output, only the parts 71.8 reads."""
    return {
        "sides": {
            "CALL": {"energy": call_energy, "spike": 71,
                     "strength": PE.energy_band(call_energy),
                     "behaviour": {"state": "building", "label": "📈 Building"}},
            "PUT": {"energy": put_energy, "spike": 30,
                    "strength": PE.energy_band(put_energy),
                    "behaviour": {"state": "distribution",
                                  "label": "📉 Distribution"}},
        },
        "shift": {"CALL": {"state": PE.SHIFT_INCREASING},
                  "PUT": {"state": PE.SHIFT_DECREASING}},
        "preferred": {"preferred": f"Prefer {preferred}", "side": preferred},
    }


def _candles(n=40, vol=1000.0, last_vol=None):
    out = []
    for i in range(n):
        base = 100.0 + i * 0.2
        out.append({"open": base, "high": base + 1.0, "low": base - 1.0,
                    "close": base + 0.4,
                    "volume": (last_vol if (last_vol and i == n - 1) else vol)})
    return out


def _legs(strike=24250.0):
    """Real `premium_structure.analyse` output — 71.8 consumes the orchestrator,
    so the fixture exercises the integration rather than a hand-built stub."""
    from mios_v5 import premium_structure as PS
    return {
        ("CALL", strike): {"structure": PS.analyse(
            sr={"state": "BREAKING", "direction": "bull", "level": 118.0},
            vob=[{"mid": 112.0, "status": "BUILDING", "bull_pct": 70}],
            vidya={"trend": "Uptrend", "delta_pct": 22.0},
            flow={"buy_total": 18.4e6, "sell_total": 8.6e6},
            vpfr={"poc": 115.0, "vah": 122.0, "val": 108.0},
            candles=_candles(), absorb="bull", ltp=118.0)},
        ("PUT", strike): {"structure": PS.analyse(
            sr={"state": "REJECTING", "direction": "bull", "level": 90.0},
            vob=[{"mid": 95.0, "status": "FADING", "bear_pct": 68}],
            vidya={"trend": "Downtrend", "delta_pct": -18.0},
            flow={"buy_total": 7.1e6, "sell_total": 15.3e6},
            candles=_candles(), absorb="bear", ltp=90.0)},
    }


def _build(**over):
    kw = dict(final_read=_fr(), premium=_premium(), chain_rows=_chain(),
              selected={"CALL": 24250.0, "PUT": 24250.0},
              leg_reads=_legs(), spot=24280.0)
    kw.update(over)
    return SV.build(**kw)


# ── the architectural boundary ──────────────────────────────────────────

def test_it_is_advisory_only():
    assert SV.ADVISORY_ONLY is True
    assert _build()["advisory_only"] is True
    assert all(r["advisory_only"] is True for r in _build()["sides"].values())


def test_it_is_not_an_engine():
    """`ALL_ENGINES` is the list of things that can vote. This is not one."""
    from mios_v5.engines import ALL_ENGINES
    names = {c().name for c in ALL_ENGINES} | {c.__name__ for c in ALL_ENGINES}
    assert "strike_validation" not in names
    assert not any("strike" in str(n).lower() for n in names)


def test_it_exposes_no_mutator():
    banned = ("apply", "deploy", "promote", "set_", "update_", "override",
              "switch_strike", "select_strike")
    for name in dir(SV):
        if name.startswith("_"):
            continue
        assert not name.startswith(banned), f"{name} looks like a mutator"


def test_it_never_reaches_into_session_state():
    """The caller extracts, this module interprets — the rule the whole Stage 71
    stack follows.

    Checked on the parse tree, not the text: the module *documents* the rule in
    prose, and a grep that cannot tell a comment from an access fails on the
    sentence explaining why the access is forbidden."""
    import ast
    tree = ast.parse(pathlib.Path(SV.__file__).read_text())
    hits = [n for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "session_state"]
    assert not hits, "this module reached into session_state"


#: Whole words that turn a reading into an instruction. `buy`/`sell` are not
#: here as substrings: Stage 43 publishes "BUYER ABSORPTION" and quoting that
#: back is a description of the tape, not a command to anybody.
_ACTION_WORDS = ("buy", "sell", "enter", "exit", "long", "short")


def _all_strings(node, out=None):
    """Every string anywhere in a nested result, so nothing hides in a list."""
    out = [] if out is None else out
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            _all_strings(k, out)
            _all_strings(v, out)
    elif isinstance(node, (list, tuple, set)):
        for v in node:
            _all_strings(v, out)
    return out


def test_it_never_generates_an_action():
    """BUY · SELL · ENTER · EXIT belong to Stage 72. This stage grades a strike
    and stops.

    Checked on the OUTPUT rather than the source, because the output is the
    contract: every string the stage can emit, over a matrix of preferences,
    selections and reaction states, with the action words matched as whole
    words."""
    import re
    pattern = re.compile(r"\b(" + "|".join(_ACTION_WORDS) + r")\b", re.I)
    for pref in ("CALL", "PUT"):
        for sel in ({"CALL": 24250.0, "PUT": 24250.0},
                    {"CALL": 24400.0, "PUT": 24100.0},
                    {"CALL": 24250.0}):
            for state in ("CONFIRMED_BREAKOUT", "BULL_TRAP", "REJECTION",
                          "IDLE"):
                out = _build(final_read=_fr(reaction={"state": state}),
                             premium=_premium(preferred=pref), selected=sel)
                for txt in _all_strings(out):
                    hit = pattern.search(txt)
                    assert not hit, f"{hit.group(0)!r} in {txt!r}"


def test_the_module_defines_no_action_vocabulary():
    """A constant named like an instruction is one refactor from being one."""
    for name in dir(SV):
        if name.startswith("_"):
            continue
        val = getattr(SV, name)
        if isinstance(val, str):
            assert val.strip().lower() not in _ACTION_WORDS, name


def test_it_does_not_recompute_stage_71_7():
    """Energy, behaviour and preference are READ. Recomputing them here would
    give the workstation two answers to the question 71.7 owns."""
    src = pathlib.Path(SV.__file__).read_text()
    assert "_side_energy" not in src and "buy_share" not in src
    assert "def _energy" not in src
    hot = _build(premium=_premium(call_energy=90))
    cold = _build(premium=_premium(call_energy=10))
    assert hot["call"]["energy"] == 90 and cold["call"]["energy"] == 10


# ── the trader picks; this stage reports ────────────────────────────────

def test_the_selected_strike_is_never_changed():
    out = _build(selected={"CALL": 24400.0, "PUT": 24100.0})
    assert out["call"]["strike"] == 24400.0
    assert out["put"]["strike"] == 24100.0
    assert out["selected"] == {"CALL": 24400.0, "PUT": 24100.0}


def test_agreement_when_the_trader_is_on_the_busiest_strike():
    out = _build(chain_rows=_chain(busiest_ce=24250.0),
                 selected={"CALL": 24250.0, "PUT": 24250.0})
    assert out["call"]["checks"]["most_traded_agreement"]["state"] == SV.AGREE


def test_one_strike_away_is_partial_not_disagree():
    """The adjacent strike is routinely the right choice for delta reasons.
    Calling that a disagreement trains a trader to ignore the check."""
    out = _build(chain_rows=_chain(busiest_ce=24250.0),
                 selected={"CALL": 24300.0, "PUT": 24250.0})
    assert out["call"]["checks"]["most_traded_agreement"]["state"] == SV.PARTIAL


def test_far_from_the_busiest_strike_disagrees_and_says_so():
    out = _build(chain_rows=_chain(busiest_ce=24250.0),
                 selected={"CALL": 24400.0, "PUT": 24250.0})
    chk = out["call"]["checks"]["most_traded_agreement"]
    assert chk["state"] == SV.DISAGREE
    assert "trader's choice stands" in chk["why"]
    assert out["call"]["strike"] == 24400.0        # still not moved


def test_most_traded_prefers_volume_over_open_interest():
    """OI is what is HELD; volume is what is being TRADED today. A strike can
    carry huge OI from last week and trade nothing this morning."""
    mt = SV.most_traded(SV.strikes_from_chain(_chain(busiest_ce=24350.0)))
    assert mt["CALL"] == 24350.0
    assert mt["by_side"]["CALL"]["basis"] == "volume"


def test_the_oi_fallback_is_labelled_not_silent():
    rows = _chain()
    for r in rows:
        r.pop("totalTradedVolume_CE")
        r.pop("totalTradedVolume_PE")
    rows[5]["openInterest_CE"] = 9_000_000.0
    mt = SV.most_traded(SV.strikes_from_chain(rows))
    assert mt["by_side"]["CALL"]["basis"] == "open interest"
    assert mt["source"] == "open interest"


# ── liquidity, the check that can disqualify ────────────────────────────

def test_an_illiquid_strike_is_avoid_whatever_else_agrees():
    """Ten agreeing opinions about direction cannot rescue a premium nobody is
    quoting — you cannot exit at the price on the screen."""
    rows = _chain(busiest_ce=24250.0)
    for r in rows:
        if abs(r["Strike"] - 24400.0) < 0.5:
            r["totalTradedVolume_CE"] = 100.0
    out = _build(chain_rows=rows, selected={"CALL": 24400.0, "PUT": 24250.0})
    assert out["call"]["checks"]["premium_liquidity"]["state"] == SV.DISAGREE
    assert out["call"]["stars"] == SV.AVOID
    assert out["call"]["hard_fail"] == "premium_liquidity"
    assert out["call"]["premium_validation"] == SV.INVALID


def test_liquidity_is_relative_to_the_ladder_not_a_fixed_threshold():
    """What counts as thin depends on the expiry, the day and the underlying."""
    src = inspect.getsource(SV._liquidity)
    assert "busiest" in src
    thin = _build(chain_rows=_chain(busiest_ce=24250.0),
                  selected={"CALL": 24400.0, "PUT": 24250.0})
    assert thin["call"]["checks"]["premium_liquidity"]["value"] == 10.0


# ── unknowns are excluded, never zeroed ─────────────────────────────────

def test_an_unknown_check_leaves_the_denominator():
    """Stage 63's rule. A strike graded on three of ten checks is not a bad
    strike, it is a barely-measured one."""
    full = _build()
    thin = _build(final_read={"spot": 24280.0})       # no stages reporting
    assert full["call"]["reporting"] > thin["call"]["reporting"]
    for key, chk in thin["call"]["checks"].items():
        if chk["state"] == SV.UNKNOWN:
            assert key not in (full["call"].get("reported") or [])


def test_too_few_checks_is_avoid_not_a_confident_rating():
    """A five-star rating resting on two inputs is the exact failure this stack
    exists to prevent."""
    out = SV.build(final_read={}, premium={}, chain_rows=[],
                   selected={"CALL": 24250.0}, leg_reads={})
    assert out["call"]["stars"] == SV.AVOID
    assert "not enough to grade" in out["call"]["stars_reason"]


def test_the_reporting_count_travels_with_the_score():
    out = _build()
    for row in out["sides"].values():
        assert row["reporting"] <= row["of"] == len(SV.WEIGHTS)
        assert str(row["reporting"]) in row["score_reason"]


def test_nothing_reported_scores_none_not_zero():
    out = SV.build()
    assert out["call"]["overall_strike_score"] is None
    assert out["ready"] is False


# ── the individual checks ───────────────────────────────────────────────

def test_dealer_agreement_reads_stage_11_levels():
    up = _build(final_read=_fr(spot=24280.0))
    assert up["call"]["checks"]["dealer_agreement"]["state"] == SV.AGREE
    assert up["put"]["checks"]["dealer_agreement"]["state"] == SV.DISAGREE


def test_a_charm_pin_counts_against_both_sides():
    """A strike dealers are defending is one where neither premium runs."""
    out = _build(final_read=_fr(charm_pin={"pin": 24250.0}))
    for side in ("CALL", "PUT"):
        chk = out["sides"][side]["checks"]["dealer_agreement"]
        assert chk["state"] == SV.DISAGREE
        assert "pin" in chk["why"]


def test_acceptance_routes_a_trap_to_the_opposite_premium():
    """A bull trap favours PUT premium by reversal, exactly as a confirmed
    breakdown favours it by continuation."""
    out = _build(final_read=_fr(reaction={"state": "BULL_TRAP"}))
    assert out["put"]["checks"]["acceptance_agreement"]["state"] == SV.AGREE
    assert out["call"]["checks"]["acceptance_agreement"]["state"] == SV.DISAGREE


def test_premium_sr_comes_from_the_premium_structure_orchestrator():
    """71.8 used to grade `sr["state"]` itself, which made two modules owners of
    "what is this premium's structure doing". It now converts a finished score
    into an agreement and derives no premium fact."""
    out = _build()
    chk = out["call"]["checks"]["premium_sr_strength"]
    assert chk["state"] == SV.AGREE
    assert chk["source"] == "Premium Structure"
    assert chk["value"] is not None          # the structure score, carried in


def test_a_barely_measured_structure_cannot_read_agree():
    """LOW confidence means two components reported. A strong score on two
    components is not a strong structure."""
    from mios_v5 import premium_structure as PS
    thin = {("CALL", 24250.0): {"structure": PS.analyse(
        sr={"state": "BREAKING", "direction": "bull", "level": 118.0})}}
    out = _build(leg_reads=thin)
    chk = out["call"]["checks"]["premium_sr_strength"]
    assert chk["state"] == SV.PARTIAL
    assert "too little measured" in chk["why"]


def test_71_8_derives_no_premium_structure_of_its_own():
    """The integration rule, asserted rather than documented."""
    src = pathlib.Path(SV.__file__).read_text()
    for banned in ("ACCEPTING", "REJECTING", "BREAKING", "classify_leg_sr"):
        assert banned not in src, f"{banned!r} — 71.8 is grading structure again"


def test_a_wing_strike_without_leg_reads_is_unknown_not_borrowed():
    """Substituting a neighbour's S/R would grade the wrong option, and nothing
    on screen would say so."""
    out = _build(selected={"CALL": 24400.0, "PUT": 24250.0}, leg_reads=_legs())
    assert out["call"]["checks"]["premium_sr_strength"]["state"] == SV.UNKNOWN


def test_every_check_names_its_producer():
    """A bare Disagree is an accusation without evidence."""
    for row in _build()["sides"].values():
        for key, chk in row["checks"].items():
            assert chk.get("source"), f"{key} has no source"
            assert chk.get("why"), f"{key} has no reason"


def test_all_ten_weights_have_a_check_and_the_reverse():
    out = _build()
    for row in out["sides"].values():
        assert set(row["checks"]) == set(SV.WEIGHTS)


def test_liquidity_outweighs_every_directional_opinion():
    """It is the only check that can make a correct read untradeable."""
    assert SV.WEIGHTS["premium_liquidity"] == max(SV.WEIGHTS.values())
    assert SV.WEIGHTS["premium_liquidity"] > SV.WEIGHTS["htf_agreement"]


# ── stars ───────────────────────────────────────────────────────────────

def test_a_well_supported_strike_earns_stars():
    out = _build()
    assert out["call"]["stars"] in ("★★★★★", "★★★★☆", "★★★☆☆")
    assert out["call"]["premium_validation"] in (SV.VALID, SV.WEAK)


def test_the_star_bands_descend():
    cuts = [c for c, _ in SV._STAR_BANDS]
    assert cuts == sorted(cuts, reverse=True)
    assert len(SV._STAR_BANDS) == 5


@pytest.mark.parametrize("score,glyph", [
    (100, "★★★★★"), (80, "★★★★★"), (79, "★★★★☆"), (65, "★★★★☆"),
    (64, "★★★☆☆"), (50, "★★★☆☆"), (49, "★★☆☆☆"), (35, "★★☆☆☆"),
    (34, "★☆☆☆☆"), (20, "★☆☆☆☆"), (19, SV.AVOID)])
def test_star_bands(score, glyph):
    ok = {k: {"state": SV.AGREE} for k in SV.WEIGHTS}
    assert SV._stars(score, ok, len(SV.WEIGHTS))["stars"] == glyph


# ── the bridge to Stage 72 ──────────────────────────────────────────────

def test_the_bridge_publishes_every_field_72_consumes():
    b = _build()["bridge"]
    for key in SV.BRIDGE_KEYS:
        assert key in b, f"{key} missing from the Stage 72 bridge"
    assert b["advisory_only"] is True


def test_the_bridge_carries_71_7s_preference_rather_than_deciding_again():
    b = _build(premium=_premium(preferred="PUT"))["bridge"]
    assert b["preferred_premium"] == "Prefer PUT"


def test_stage_72_is_a_named_absence():
    out = _build()
    assert "entry_engine" in out["missing_inputs"]


# ── the panel ───────────────────────────────────────────────────────────

def test_the_panel_shows_the_checks_and_the_stars():
    html = strike_validation_html(_build())
    assert "Strike Validation" in html and "Stage 71.8" in html
    assert "Liquidity" in html and "Most-traded" in html
    assert "★" in html


def test_the_panel_says_nothing_when_the_stage_has_nothing():
    assert strike_validation_html(SV.build()) == ""
    assert strike_validation_html(None) == ""


def test_the_panel_keeps_unknown_rows_visible():
    """Hiding them would make a thin read look like a complete one."""
    html = strike_validation_html(_build(final_read={"spot": 24280.0}))
    assert "⚪" in html
    for label in ("HTF", "Absorption", "Reaction zone"):
        assert label in html


# ── the premium structure summary and the chart overlays ────────────────

def test_the_panel_shows_the_call_put_structure_summary():
    """Phase 6's block — score · support · resistance · acceptance · momentum ·
    absorption · top reason, per side."""
    html = strike_validation_html(_build())
    for label in ("Structure", "Support", "Resistance", "POC", "Acceptance",
                  "Momentum", "RVOL", "Absorption", "Break", "Fakeout",
                  "Top reason"):
        assert label in html, f"{label} missing from the summary"


def test_break_and_fakeout_are_shown_side_by_side():
    """A single blended number would hide the case a trader most needs: a break
    that is both likely to go and likely to fail."""
    html = strike_validation_html(_build())
    assert "Break" in html and "Fakeout" in html


def test_the_structure_is_carried_not_re_described():
    """71.8 passes Premium Structure's own read through to the panel rather than
    restating it in a second vocabulary."""
    from mios_v5 import premium_structure as PS
    legs = _legs()
    out = _build(leg_reads=legs)
    assert out["call"]["structure"] is legs[("CALL", 24250.0)]["structure"]
    assert out["call"]["structure"]["structure_score"] is not None
    assert set(out["call"]["structure"]["computed_here"]) == set(PS.COMPUTED_HERE)


def test_the_chart_overlay_vocabulary_covers_the_structure_levels():
    """Phase 5 reuses the existing renderer — the overlay keys must exist in the
    chart's own vocabulary or the levels are silently dropped."""
    from mios_v5.ui.terminal_chart import LEVELS, LEVEL_LABEL
    for key in ("support", "resistance", "poc", "hvn", "lvn"):
        assert key in LEVELS, f"{key} has no chart style"
        assert key in LEVEL_LABEL, f"{key} has no chart label"


def test_no_second_chart_was_created():
    """The overlays go on the terminal chart that already exists.

    Guards against a FORKED RENDERER, which is what "a second chart" means
    here — a module that builds its own figure instead of drawing onto the one
    `terminal_chart` makes. It used to assert the filename list was exactly
    `["terminal_chart.py"]`, which also rejected a `chart_*` helper that
    renders nothing at all (`chart_theme.py` is a palette lookup and imports no
    plotly). Testing for figure construction keeps the real protection and is
    strictly stronger: a fork named without "chart" in it would now be caught
    too, where the filename check let it through.
    """
    import pathlib as _p
    ui = _p.Path(SV.__file__).parent / "ui"
    for f in ui.glob("*chart*.py"):
        if f.name == "terminal_chart.py":
            continue
        src = f.read_text()
        assert "make_subplots(" not in src and "go.Figure(" not in src, (
            f"{f.name} builds its own figure — the terminal chart was forked")
