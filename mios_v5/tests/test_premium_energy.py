"""Stage 71.7 — Premium Energy & Spike Probability.

Most of these guard the two claims the stage is built on, because both are easy
to break with a change that looks like a simplification:

1. **Energy is not Spike.** Different substrates, different meanings. Merging
   them is the tempting refactor and it destroys the whole point.
2. **CALL and PUT are scored independently, never by subtraction.** `70 vs 65`
   is two live premiums, not a 5-point edge.

The rest guard against reporting a market read as if it were a per-side one —
the defect the first working version actually had.
"""

import pathlib

import pytest

from mios_v5 import premium_energy as PE
from mios_v5.ui.premium_energy_panel import premium_energy_html
from mios_v5.ui.opportunity_panel import matrix_html


def _rows(call_dir="🟢", put_dir="🟢", zone="🚀 BUILD"):
    """Six ATM±1 legs. Each signal is in the LEG's own direction, the way
    `build_leg_bias_table` publishes it."""
    out = []
    for tag, d in (("ATM-1 CE 24200", call_dir), ("ATM CE 24250", call_dir),
                   ("ATM+1 CE 24300", call_dir), ("ATM-1 PE 24200", put_dir),
                   ("ATM PE 24250", put_dir), ("ATM+1 PE 24300", put_dir)):
        out.append({"Leg": tag, "LTP": "₹80.0", "Sup VOB": zone, "Res VOB": zone,
                    "VOB": d, "S/R": d, "Div": d, "Ign": d, "Absorb": d,
                    "CVD": d, "OIvel": d, "VWAP": d, "VIDYA": d, "MFP": d})
    return out


def _fr(**over):
    fr = {
        "energy_read": {"strength": 62, "compression": 58,
                        "release_probability": 70, "expansion_readiness": 66,
                        "state": "COMPRESSION", "ready": True},
        "absorption": {"behaviour": "NONE"},
        "reaction": {"state": "ACCEPTANCE"},
        "htf": {"alignment": {"score": 78, "bias": "BULL"}},
        "flow_shift": {}, "liquidity": {},
        "sections": {"dealer": {"bias": "BULL"}},
    }
    fr.update(over)
    return fr


# ── the architectural rules ─────────────────────────────────────────────

def test_it_is_advisory_only():
    assert PE.ADVISORY_ONLY is True
    assert PE.build(_fr(), _rows())["advisory_only"] is True


def test_it_never_reaches_into_session_state():
    """The caller extracts, this module interprets — the same rule
    `opportunity.build_matrix` follows. A session read here would make the
    engine untestable and couple it to Streamlit."""
    src = pathlib.Path(PE.__file__).read_text()
    # the prose says "may not reach into session_state", so match the CODE form
    assert "st.session_state" not in src
    assert ".session_state" not in src.replace("`session_state`", "")
    assert "import streamlit" not in src


def test_it_computes_no_market_intelligence():
    """Stage 71.7 is an orchestrator. A rolling mean or a cumsum here would mean
    it had started measuring the market instead of reading it."""
    src = pathlib.Path(PE.__file__).read_text()
    for banned in ("cumsum", "rolling(", "ewm(", "pd.", "numpy", "np."):
        assert banned not in src, banned


def test_it_never_raises():
    for args in ((None, None), ({}, []), (_fr(), None),
                 ({"energy_read": None}, [{"Leg": None}, "junk", 7])):
        assert isinstance(PE.build(*args), dict)


# ── Energy is not Spike ─────────────────────────────────────────────────

def test_energy_and_spike_use_different_substrates():
    """If these sets converge the two numbers stop meaning different things."""
    energy_keys = {k for k, _ in PE._ENERGY_SIGNALS}
    spike_keys = {k for k, _ in PE._SPIKE_SIGNALS}
    assert energy_keys != spike_keys
    assert energy_keys - spike_keys, "Energy has no signal of its own"
    assert spike_keys - energy_keys, "Spike has no signal of its own"


def test_a_grinding_premium_can_be_high_energy_and_low_spike():
    """The spec's own example: CALL grinding higher — energy 82, spike 28. Both
    numbers have to be free to move independently."""
    rows = _rows(call_dir="🟢", put_dir="⚪", zone="• INTACT")
    fr = _fr(energy_read={"strength": 80, "compression": 10,
                          "release_probability": 12, "expansion_readiness": 15,
                          "state": "EXPANSION", "ready": True})
    call = PE.build(fr, rows)["call"]
    assert call["energy"] is not None and call["energy"] >= 60
    assert call["spike"] is not None and call["spike"] < call["energy"]


def test_compression_raises_spike_because_a_coil_is_potential_energy():
    quiet = {"strength": 45, "compression": 15, "release_probability": 10,
             "expansion_readiness": 12, "state": "BUILDING", "ready": True}
    coiled = dict(quiet, compression=85, release_probability=80,
                  expansion_readiness=78, state="COMPRESSION")
    lo = PE.build(_fr(energy_read=quiet), _rows())["call"]["spike"]
    hi = PE.build(_fr(energy_read=coiled), _rows())["call"]["spike"]
    assert hi > lo


# ── independence, never subtraction ─────────────────────────────────────

def test_both_sides_can_be_strong_at_once():
    """Two live premiums is a real market state. A subtractive score would
    report it as "no edge", which is the specific error this avoids."""
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🟢"))
    assert out["call"]["energy"] > 50 and out["put"]["energy"] > 50


def test_a_narrow_gap_is_balanced_not_a_winner():
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🟢"))
    assert out["dominance"] == PE.DOM_BALANCED
    assert out["preferred"]["preferred"] == PE.PREFER_NONE
    assert out["call"]["energy"] == out["put"]["energy"]


def test_a_clear_gap_names_the_dominant_side():
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"))
    assert out["dominance"] == PE.DOM_CALL
    assert out["call"]["energy"] > out["put"]["energy"]


def test_no_energy_is_not_balanced():
    """The four-state fix. Two premiums that never reported and two premiums at
    74/70 both rendered "Balanced", which told a trader to wait for an edge in
    one case and hid an empty tape in the other."""
    nothing = PE.build(_fr(), _rows(call_dir="⚪", put_dir="⚪"))
    assert nothing["dominance"] == PE.DOM_NONE
    both = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🟢"))
    assert both["dominance"] == PE.DOM_BALANCED
    assert nothing["dominance"] != both["dominance"]


def test_balance_is_a_presentation_not_a_source():
    """Balance must be derivable FROM the two scores, never the other way."""
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"))
    b = out["balance"]
    assert b["CALL"] + b["PUT"] in (99, 100, 101)     # rounding
    assert out["call"]["energy"] is not None           # the source still stands


# ── the defect the first version had ────────────────────────────────────

def test_a_dead_premium_cannot_report_a_high_spike():
    """The real bug: compression / release / vacuum / absorption describe the
    TAPE and are identical for both sides. Averaged in ungated they gave a
    premium with 0% participation a 62% "High" spike, because the market was
    coiled. A premium nobody trades cannot expand explosively — the tape has to
    act THROUGH a side."""
    fr = _fr(absorption={"behaviour": "RELEASED"},
             liquidity={"vacuum": True},
             energy_read={"strength": 62, "compression": 85,
                          "release_probability": 90, "expansion_readiness": 88,
                          "state": "RELEASED", "ready": True})
    out = PE.build(fr, _rows(call_dir="🟢", put_dir="🔴"))
    assert out["put"]["energy"] == 0
    assert out["put"]["spike"] <= 40, \
        f"dead premium reported spike {out['put']['spike']}"
    assert PE.spike_band(out["put"]["spike"]) in ("Very Low", "Low")


def test_the_two_sides_do_not_get_an_identical_trigger_list():
    """Both sides once showed "Dealer Wall Break · Absorption Release ·
    Liquidity Vacuum" — one market read printed twice."""
    fr = _fr(absorption={"behaviour": "RELEASED"}, liquidity={"vacuum": True})
    out = PE.build(fr, _rows(call_dir="🟢", put_dir="🔴"))
    assert out["call"]["top_triggers"] != out["put"]["top_triggers"]


def test_a_directional_trigger_goes_to_the_side_it_favours():
    fr = _fr(absorption={"behaviour": "RELEASED"},
             htf={"alignment": {"score": 80, "bias": "BULL"}},
             sections={"dealer": {"bias": "BULL"}})
    out = PE.build(fr, _rows(call_dir="🟢", put_dir="🔴"))
    assert "Absorption Release" in out["call"]["top_triggers"]
    assert "Absorption Release" not in out["put"]["top_triggers"]


def test_an_unknown_direction_withholds_nothing():
    """With no HTF and no dealer read there is no basis to deny a side its
    trigger — silence is not evidence against it."""
    fr = _fr(absorption={"behaviour": "RELEASED"},
             htf={}, sections={})
    out = PE.build(fr, _rows(call_dir="🟢", put_dir="🟢"))
    for s in ("call", "put"):
        assert "Absorption Release" in out[s]["top_triggers"]


def test_stage44_touches_stability_and_nothing_else():
    """The double-count fix. Stage 71's `stability()` already consumes
    `freeze_entries`; capping Spike on it as well counted one veto twice, which
    the stage's own binding rule forbids. Stage 44 must reach the output through
    Stability only."""
    fr = _fr(flow_shift={"freeze_entries": True, "score": 80},
             energy_read={"strength": 90, "compression": 90,
                          "release_probability": 95,
                          "expansion_readiness": 92, "state": "RELEASED",
                          "ready": True})
    out = PE.build(fr, _rows())
    assert out["stability"]["word"] == "Shock"
    # the veto is visible where it belongs — and it still stops a preference
    assert out["preferred"]["preferred"] == PE.PREFER_AVOID


def test_stage44_is_not_named_in_the_spike_path():
    """An AST-free guard: `_side_spike` may not read the flow-shift freeze."""
    import inspect
    src = inspect.getsource(PE._side_spike)
    assert "flow_frozen" not in src and "freeze_entries" not in src


# ── the leg-row bridge ──────────────────────────────────────────────────

def test_the_bridge_splits_ce_and_pe():
    s = PE.sides_from_leg_rows(_rows())
    assert s["CALL"]["legs"] == 3 and s["PUT"]["legs"] == 3


def test_a_leg_whose_side_cannot_be_read_is_skipped_not_guessed():
    """Counting it as flat would dilute a real read toward neutral."""
    s = PE.sides_from_leg_rows([{"Leg": "MYSTERY 24250", "CVD": "🟢"}])
    assert s["CALL"]["legs"] == 0 and s["PUT"]["legs"] == 0


def test_the_bridge_is_the_only_place_the_emoji_vocabulary_is_decoded():
    """One mapping, not several. A second glyph→direction dict is how the panel
    and the engine end up disagreeing about what 🟢 means."""
    import ast
    tree = ast.parse(pathlib.Path(PE.__file__).read_text())
    # Docstrings legitimately quote the glyphs while explaining them; only real
    # code counts. Line-prefix filtering misses continuation lines, so strip the
    # docstring nodes properly.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    assert code.count("🟢") == 1, "the leg glyph vocabulary leaked into code"
    assert set(PE._EMOJI_DIR) == {"🟢", "🔴", "⚪"}


def test_no_legs_reporting_yields_none_not_zero():
    """`None` means unmeasured; `0` means measured-and-dead. Conflating them is
    how a warming-up panel reads as a bearish signal."""
    out = PE.build(_fr(), [])
    assert out["call"]["energy"] is None
    assert out["ready"] is False


# ── it reads rotation and stability, never recomputes them ──────────────

def test_stability_keeps_stage44s_own_words():
    """`Stable / Unstable / Shock / Recovery` is Stage 44's vocabulary. Stage 71
    bands it numerically for ranking; translating that band back into a second
    set of words gave the workstation two names for one fact."""
    matrix = {"rows": [], "stability": "High", "stability_emoji": "🟢",
              "stability_score": 88}
    out = PE.build(_fr(stability="RECOVERY"), _rows(), matrix=matrix)
    assert out["stability"]["word"] == "Recovery"
    assert out["stability"]["band"] == "High"        # the band is kept beside it
    assert "Stage 44" in out["stability"]["source"]


def test_a_frozen_tape_is_shock_whatever_the_band_says():
    """`freeze_entries` is the strongest thing Stage 44 can publish, so it
    cannot render as anything softer."""
    out = PE.build(_fr(flow_shift={"freeze_entries": True}), _rows(),
                   matrix={"rows": [], "stability": "High"})
    assert out["stability"]["word"] == "Shock"


def test_it_does_not_reimplement_stability():
    src = pathlib.Path(PE.__file__).read_text()
    assert "def stability" not in src, "stability is Stage 71's — read it"


# ── the horizon join, which is what 71.7 exists to add to 71 ────────────

_MATRIX = {
    "rows": [{"horizon": "scalp", "side": "CALL", "score": 40},
             {"horizon": "midday", "side": "PUT", "score": 33},
             {"horizon": "intraday", "side": "CALL", "score": 30},
             {"horizon": "positional", "side": None, "score": 12},
             {"horizon": "swing", "side": None, "score": 20}],
    "display_order": ["scalp", "midday", "intraday", "positional", "swing"],
    "stability": "High", "best_trade": {},
}


def _by_horizon(out):
    return {h["horizon"]: h for h in out["horizons"]}


def test_a_horizon_whose_premium_is_dead_is_contradicted():
    """The whole reason for the join. Stage 71 can rank a horizon on directional
    evidence while its option has no participation, and before this nothing on
    the screen could say so."""
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"), matrix=_MATRIX)
    assert _by_horizon(out)["midday"]["agreement"] == "CONTRADICTED"
    assert "PUT" in _by_horizon(out)["midday"]["note"]


def test_a_horizon_whose_premium_is_live_and_coiled_is_hot():
    fr = _fr(energy_read={"strength": 70, "compression": 80,
                          "release_probability": 78,
                          "expansion_readiness": 75, "state": "COMPRESSION",
                          "ready": True})
    out = PE.build(fr, _rows(call_dir="🟢", put_dir="🔴"), matrix=_MATRIX)
    assert _by_horizon(out)["scalp"]["agreement"] == "CONFIRMED_HOT"


def test_swing_is_not_applicable_because_it_names_no_premium():
    """`horizon_owner.NO_OPTION_SIDE` — a weeks-long read cannot be expressed as
    an option that decays in days. N/A, not blank and not zero."""
    out = PE.build(_fr(), _rows(), matrix=_MATRIX)
    swing = _by_horizon(out)["swing"]
    assert swing["agreement"] == "N/A"
    assert swing["energy"] is None
    assert "by design" in swing["note"]


def test_swing_matches_the_registry_rather_than_a_local_opinion():
    from mios_v5.horizon_owner import NO_OPTION_SIDE
    assert {h.value for h in NO_OPTION_SIDE} == set(PE._NO_PREMIUM)


def test_a_horizon_with_no_side_says_so_rather_than_guessing():
    out = PE.build(_fr(), _rows(), matrix=_MATRIX)
    assert _by_horizon(out)["positional"]["agreement"] == "NO_SIDE"


def test_the_join_covers_every_matrix_row():
    out = PE.build(_fr(), _rows(), matrix=_MATRIX)
    assert len(out["horizons"]) == len(_MATRIX["rows"])


# ── energy shift needs history ──────────────────────────────────────────

def test_the_first_cycle_reports_unknown_not_flat():
    """A move that was never observed is not a move — "Flat" would assert
    stability nobody measured."""
    out = PE.build(_fr(), _rows())
    assert out["shift"]["CALL"]["state"] == PE.SHIFT_UNKNOWN


def test_a_rising_side_reports_increasing():
    """`⚪` legs report NOTHING, so they give energy `None`, not a low energy —
    the shift then has no baseline. A measured-but-weak previous cycle is `🔴`."""
    weak = PE.build(_fr(), _rows(call_dir="🔴"))
    assert weak["call"]["energy"] is not None, "need a measured baseline"
    strong = PE.build(_fr(), _rows(call_dir="🟢"), previous=weak)
    assert strong["shift"]["CALL"]["state"] in (PE.SHIFT_INCREASING,
                                                PE.SHIFT_EXPLODING)


def test_a_side_that_never_reported_has_no_shift_to_measure():
    blank = PE.build(_fr(), _rows(call_dir="⚪"))
    assert blank["call"]["energy"] is None
    nxt = PE.build(_fr(), _rows(call_dir="🟢"), previous=blank)
    assert nxt["shift"]["CALL"]["state"] == PE.SHIFT_UNKNOWN


# ── bands, exactly as specified ─────────────────────────────────────────

@pytest.mark.parametrize("pct,band", [
    (0, "Very Low"), (20, "Very Low"), (21, "Low"), (40, "Low"),
    (41, "Moderate"), (60, "Moderate"), (61, "High"), (80, "High"),
    (81, "Extreme"), (100, "Extreme")])
def test_spike_bands_match_the_spec(pct, band):
    assert PE.spike_band(pct) == band


def test_an_unmeasured_spike_has_no_band():
    assert PE.spike_band(None) == "Unknown"
    assert PE.strength_band(None) == "Unknown"


# ── named absences ──────────────────────────────────────────────────────

def test_a_missing_consumer_is_named_not_assumed():
    """Stage 72 does not exist. An unbuilt consumer is named, so a bridge with
    one signature cannot be mistaken for a contract with two."""
    out = PE.build(_fr(), _rows())
    assert "entry_engine" in out["missing_inputs"]


def test_the_retired_spike_engines_are_recorded_with_a_reason():
    """The spec assumed `compute_spike_probability` et al. All three went in the
    V6 reduction; naming them stops the next reader hunting for ghosts."""
    out = PE.build(_fr(), _rows())
    assert "compute_spike_probability" in out["retired_inputs"]
    assert "reduction" in out["retired_inputs"]["compute_spike_probability"]


# ── the panel ───────────────────────────────────────────────────────────

def test_an_unmeasured_value_renders_a_dash_not_zero_percent():
    """A bar at 0% asserts a measurement nobody took."""
    html = premium_energy_html(PE.build(_fr(), _rows(call_dir="⚪")))
    assert "—" in html


def test_the_panel_renders_nothing_when_the_stage_is_cold():
    assert premium_energy_html(PE.build(_fr(), [])) == ""
    assert premium_energy_html(None) == ""


def test_the_panel_names_the_stage_and_its_advisory_status():
    html = premium_energy_html(PE.build(_fr(), _rows()))
    assert "71.7" in html and "advisory" in html.lower()


def test_the_panel_shows_the_horizon_cross_check():
    html = premium_energy_html(PE.build(_fr(), _rows(), matrix=_MATRIX))
    for h in ("scalp", "midday", "intraday", "swing"):
        assert h in html


def test_the_panel_uses_no_retired_grey():
    from mios_v5.ui.theme import RETIRED
    src = pathlib.Path(
        __file__).resolve().parents[1] / "ui" / "premium_energy_panel.py"
    body = src.read_text().lower()
    assert not [g for g in RETIRED if g in body]


# ── the Stage 71 table it is folded into ────────────────────────────────

def test_the_matrix_table_gains_a_premium_column():
    html = matrix_html(_MATRIX, PE.build(_fr(), _rows(), matrix=_MATRIX))
    assert "Premium" in html


def test_the_matrix_table_still_renders_without_stage_71_7():
    """71.7 failing may never blank Stage 71 — the ranking stands on its own."""
    assert "Horizon" in matrix_html(_MATRIX)
    assert "Horizon" in matrix_html(_MATRIX, None)


def test_the_contradiction_glyph_reaches_the_table():
    html = matrix_html(_MATRIX,
                       PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"),
                                matrix=_MATRIX))
    assert "⚠️" in html, "a dead premium must be visible in the row"


def test_premium_energy_is_rendered_exactly_once():
    """It used to render below Market Energy as well. Two copies of the same
    numbers is the drift the Stage 71 stack exists to prevent."""
    dash = (pathlib.Path(__file__).resolve().parents[1]
            / "ui" / "dashboard_v6.py").read_text()
    assert dash.count("premium_energy import build") == 1
    assert "render_premium_energy(st" not in dash


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        if not hasattr(fn, "pytestmark"):
            fn()
    print(f"premium energy tests passed ({len(fns)})")


# ══════════════════════════════════════════════════════════════════════
#  the completion plan — mandatory inputs, outputs, vocabulary, bridge
# ══════════════════════════════════════════════════════════════════════

def _totals(call_buy=18.4e6, call_sell=8.6e6, put_buy=7.1e6, put_sell=15.3e6):
    """`(leg_tag, order_flow.totals(...))` pairs, the shape `_atm_leg_ltf_delta`
    holds after `_publish_atm_legs` writes it."""
    out = []
    for tag, b, s in (("ATM-1 CE 24200", call_buy / 3, call_sell / 3),
                      ("ATM CE 24250", call_buy / 3, call_sell / 3),
                      ("ATM+1 CE 24300", call_buy / 3, call_sell / 3),
                      ("ATM-1 PE 24200", put_buy / 3, put_sell / 3),
                      ("ATM PE 24250", put_buy / 3, put_sell / 3),
                      ("ATM+1 PE 24300", put_buy / 3, put_sell / 3)):
        out.append((tag, {"buy_total": b, "sell_total": s,
                          "delta": b - s,
                          "delta_pct": round((b - s) / (b + s) * 100, 2)}))
    return out


# ── Phase 1 · the three mandatory inputs ────────────────────────────────

def test_cbv_csv_and_cvd_are_first_class_inputs():
    """The spec makes all three mandatory. Only CVD was wired, and only as a
    glyph — a direction, where CBV and CSV are amounts."""
    out = PE.build(_fr(), _rows(), leg_totals=_totals())
    call = out["call"]
    assert call["cbv"] == pytest.approx(18.4e6)
    assert call["csv"] == pytest.approx(8.6e6)
    assert call["cvd"] == pytest.approx(9.8e6)
    assert call["buy_share"] == pytest.approx(68.1, abs=0.2)
    put = out["put"]
    assert put["cvd"] == pytest.approx(-8.2e6)
    assert put["buy_share"] < 50


def test_the_flow_bridge_sums_a_side_rather_than_averaging_it():
    """CBV is a volume. "How much buying went into CALL premium" is the total
    across the strikes a trader would use, not their mean."""
    flow = PE.flow_from_leg_totals(_totals())
    assert flow["CALL"]["cbv"] == pytest.approx(18.4e6)
    assert flow["CALL"]["legs"] == 3


def test_a_side_with_no_flow_reports_none_not_zero():
    """`0` reads as "measured, and nobody traded it"."""
    flow = PE.flow_from_leg_totals([("ATM CE 24250", {"buy_total": 5.0,
                                                      "sell_total": 5.0})])
    assert flow["PUT"]["cbv"] is None and flow["PUT"]["buy_share"] is None


def test_flow_moves_the_energy_score():
    """If the mandatory input cannot change the answer it is not wired, it is
    decoration."""
    bid = PE.build(_fr(), _rows(), leg_totals=_totals(call_buy=19e6,
                                                      call_sell=1e6))
    ask = PE.build(_fr(), _rows(), leg_totals=_totals(call_buy=1e6,
                                                      call_sell=19e6))
    assert bid["call"]["energy"] > ask["call"]["energy"]


def test_the_leg_side_decoder_is_shared_by_both_bridges():
    """Two decoders would eventually disagree about which legs are CALLs."""
    assert PE.side_of("ATM CE 24250") == "CALL"
    assert PE.side_of("ATM PE 24250") == "PUT"
    assert PE.side_of("MYSTERY 24250") is None


# ── Phase 1 · Stage 50, Stage 42 and HTF ────────────────────────────────

def _s50(call_state="building", put_state="flat", buyers="building"):
    return {"ready": True,
            "calls": {"state": call_state, "label": call_state},
            "puts": {"state": put_state, "label": put_state},
            "buyers": {"state": buyers, "label": buyers},
            "sellers": {"state": "neutral", "label": "steady"},
            "volume": {"state": "healthy"}}


def test_stage50_premium_behaviour_is_read_not_re_derived():
    """Stage 50 already classifies each option side. Deriving "accumulation"
    here from CVD would be a second answer to a question that has one."""
    building = PE.build(_fr(ltp_behaviour=_s50(call_state="building")),
                        _rows(), leg_totals=_totals())
    unwinding = PE.build(_fr(ltp_behaviour=_s50(call_state="unwinding",
                                                buyers="exhausted")),
                         _rows(), leg_totals=_totals())
    assert building["call"]["energy"] > unwinding["call"]["energy"]
    assert building["call"]["behaviour"]["state"] == "building"
    assert unwinding["call"]["behaviour"]["pressure"] == "exhausted"


def test_stage50_reaches_the_shift_vocabulary():
    """Building and Distributing are Stage 50's words, and the Shift states the
    spec asks for. Flat energy plus a Stage 50 state is not "Holding"."""
    prev = PE.build(_fr(ltp_behaviour=_s50()), _rows(), leg_totals=_totals())
    now = PE.build(_fr(ltp_behaviour=_s50(call_state="distribution")),
                   _rows(), leg_totals=_totals(), previous=prev)
    assert now["shift"]["CALL"]["state"] == PE.SHIFT_DISTRIBUTING


def test_stage42_acceptance_raises_the_spike_claim():
    """Executed evidence. It was extracted into the context and dropped."""
    idle = PE.build(_fr(reaction={"state": "WATCHING"}), _rows(),
                    leg_totals=_totals())
    broke = PE.build(_fr(reaction={"state": "CONFIRMED_BREAKOUT"}), _rows(),
                     leg_totals=_totals())
    assert broke["call"]["spike"] > idle["call"]["spike"]


def test_stage42_is_routed_to_the_side_it_favours():
    """A market read printed on both premiums is one finding shown twice."""
    out = PE.build(_fr(reaction={"state": "CONFIRMED_BREAKOUT"},
                       htf={"alignment": {"score": 80, "bias": "BULL"}},
                       sections={"dealer": {"bias": "BULL"}}),
                   _rows(), leg_totals=_totals())
    assert "Acceptance Breakout" in out["call"]["top_triggers"]
    assert "Acceptance Breakout" not in out["put"]["top_triggers"]


def test_htf_score_weights_confidence():
    """`ctx["htf"]` was extracted and never read; only the bias was used."""
    strong = PE.build(_fr(htf={"alignment": {"score": 95, "bias": "BULL"}}),
                      _rows(), leg_totals=_totals())
    weak = PE.build(_fr(htf={"alignment": {"score": 10, "bias": "BULL"}}),
                    _rows(), leg_totals=_totals())
    assert strong["confidence"]["components"]["htf"] > \
        weak["confidence"]["components"]["htf"]
    assert strong["confidence"]["avg"] > weak["confidence"]["avg"]


# ── Phase 2 · the four missing outputs ──────────────────────────────────

def test_preferred_premium_is_a_field_with_four_states():
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"),
                   leg_totals=_totals())
    assert out["preferred"]["preferred"] == PE.PREFER_CALL
    assert out["preferred"]["side"] == "CALL"
    assert out["preferred"]["reason"]


def test_no_participation_is_avoid_both_not_no_edge():
    """"No edge" says two live premiums are level. "Avoid both" says there is
    nothing there. Collapsing them loses the more important warning."""
    out = PE.build(_fr(), _rows(call_dir="⚪", put_dir="⚪"))
    assert out["preferred"]["preferred"] == PE.PREFER_AVOID


def test_confidence_reuses_stage52_bands():
    """Imported, not reproduced — a band this stage prints can never disagree
    with the one the Decision Engine prints."""
    from mios_v5.decision import _grade
    out = PE.build(_fr(), _rows(), leg_totals=_totals())
    assert out["confidence"]["grade"] in ("A+", "A", "B", "C")
    assert out["confidence"]["grade"] == _grade(out["confidence"]["avg"])


def test_a_grade_resting_on_one_number_is_unknown():
    """Stage 63's rule — unknown components are excluded, never scored zero,
    and too few reporting is UNKNOWN rather than a letter."""
    bare = PE.build({}, _rows(call_dir="⚪", put_dir="⚪"))
    assert bare["confidence"]["grade"] == "UNKNOWN"


def test_top_trigger_is_exactly_one():
    out = PE.build(_fr(reaction={"state": "CONFIRMED_BREAKOUT"},
                       absorption={"behaviour": "RELEASED"}),
                   _rows(), leg_totals=_totals())
    assert isinstance(out["top_trigger"], str)
    assert out["top_trigger"] in PE.TRIGGER_PRIORITY


def test_the_trigger_priority_is_causal():
    """A dealer wall giving way changes what every other read means; a volume
    spike underneath it is a consequence, not a second finding."""
    assert PE._top_trigger(["Volume Explosion", "Dealer Wall",
                            "VOB Breakout"]) == "Dealer Wall"
    assert PE._top_trigger(["Volume Explosion",
                            "VOB Breakout"]) == "VOB Breakout"
    assert PE._top_trigger([]) is None
    assert PE._top_trigger(["Something Unlisted"]) is None


def test_dealer_wall_and_gamma_flip_come_from_stage11_levels():
    """The old code labelled a *leg VOB* break "Dealer Wall Break". The dealer
    wall is a price, and Stage 11 already publishes it."""
    out = PE.build(_fr(dealer_levels={"dealer_wall": 24000.0,
                                      "gamma_flip": 23900.0},
                       spot=24100.0),
                   _rows(), leg_totals=_totals())
    assert out["top_trigger"] == "Dealer Wall"
    assert "Gamma Flip" in out["call"]["top_triggers"]


def test_top_reasons_are_machine_readable_and_capped_at_five():
    out = PE.build(_fr(ltp_behaviour=_s50()), _rows(), leg_totals=_totals())
    reasons = out["top_reasons"]
    assert 0 < len(reasons) <= 5
    for r in reasons:
        assert set(r) >= {"code", "label", "side", "weight"}
        assert r["code"] == r["label"].upper().replace(" ", "_")
        assert " " not in r["code"]


# ── Phase 3 · vocabulary ────────────────────────────────────────────────

@pytest.mark.parametrize("pct,band", [
    (0, "Dead"), (20, "Dead"), (21, "Weak"), (40, "Weak"),
    (41, "Healthy"), (60, "Healthy"), (61, "Strong"), (80, "Strong"),
    (81, "Explosive"), (100, "Explosive")])
def test_energy_bands_match_the_spec(pct, band):
    assert PE.energy_band(pct) == band


def test_the_six_shift_states_all_exist():
    assert {PE.SHIFT_INCREASING, PE.SHIFT_DECREASING, PE.SHIFT_BUILDING,
            PE.SHIFT_DISTRIBUTING, PE.SHIFT_COMPRESSING,
            PE.SHIFT_EXPLODING} == {"Increasing", "Decreasing", "Building",
                                    "Distributing", "Compressing", "Exploding"}


def test_compression_is_read_where_energy_is_flat():
    fr = _fr(energy_read={"strength": 62, "compression": 80,
                          "release_probability": 70,
                          "expansion_readiness": 66, "state": "COMPRESSION",
                          "ready": True},
             ltp_behaviour=_s50(call_state="flat"))
    prev = PE.build(fr, _rows(), leg_totals=_totals())
    now = PE.build(fr, _rows(), leg_totals=_totals(), previous=prev)
    assert now["shift"]["CALL"]["state"] == PE.SHIFT_COMPRESSING


# ── Phase 5 · rotation measures energy, not the matrix's side ───────────

def test_rotation_measures_energy_migration():
    """The matrix's best side can flip on directional evidence while both
    premiums keep exactly the participation they had. Reporting that as
    rotation names a migration that never happened."""
    prev = PE.build(_fr(), _rows(call_dir="🟢", put_dir="🔴"),
                    leg_totals=_totals(call_buy=19e6, call_sell=1e6,
                                       put_buy=1e6, put_sell=19e6))
    now = PE.build(_fr(), _rows(call_dir="🔴", put_dir="🟢"),
                   leg_totals=_totals(call_buy=1e6, call_sell=19e6,
                                      put_buy=19e6, put_sell=1e6),
                   previous=prev)
    assert now["rotation"]["rotation"] == "ROTATION"
    assert now["rotation"]["label"] == "CALL → PUT"


def test_an_unmoved_pair_is_stable_not_rotating():
    prev = PE.build(_fr(), _rows(), leg_totals=_totals())
    now = PE.build(_fr(), _rows(), leg_totals=_totals(), previous=prev)
    assert now["rotation"]["rotation"] == "STABLE"


def test_rotation_is_unknown_on_the_first_cycle():
    assert PE.build(_fr(), _rows())["rotation"]["rotation"] == "UNKNOWN"


# ── Phase 4 · no instruction, ever ──────────────────────────────────────

def test_the_conclusion_never_says_trade():
    """"Trade CALL" is a buy instruction in plain words — forbidden by the
    stage's own rules, and by Stage 65's rule that actions are quoted from
    Stage 52 and never invented."""
    import itertools
    for c, p in itertools.product("🟢🔴⚪", repeat=2):
        for fr in (_fr(), _fr(reaction={"state": "CONFIRMED_BREAKOUT"}),
                   _fr(flow_shift={"freeze_entries": True})):
            txt = PE.build(fr, _rows(call_dir=c, put_dir=p),
                           leg_totals=_totals())["conclusion"].lower()
            for banned in ("trade call", "trade put", "buy ", "sell ",
                           "enter ", "avoid options"):
                assert banned not in txt, f"{banned!r} in {txt!r}"


def test_no_module_source_emits_an_instruction():
    src = pathlib.Path(PE.__file__).read_text().lower()
    assert '"trade call' not in src and '"trade put' not in src


# ── Phase 6 · the bridge downstream ─────────────────────────────────────

def test_the_bridge_publishes_every_field_71_8_consumes():
    out = PE.build(_fr(), _rows(), leg_totals=_totals())
    bridge = out["bridge"]
    for key in PE.BRIDGE_KEYS:
        assert key in bridge, f"{key} missing from the 71.8 bridge"
    assert bridge["advisory_only"] is True


def test_the_bridge_is_flat_and_needs_no_internals():
    """Whoever builds 71.8 must not have to walk `sides['CALL']['energy']`."""
    b = PE.build(_fr(), _rows(), leg_totals=_totals())["bridge"]
    assert set(b["energy_score"]) == {"CALL", "PUT"}
    assert set(b["spike_probability"]) == {"CALL", "PUT"}
    assert b["preferred_premium"] in (PE.PREFER_CALL, PE.PREFER_PUT,
                                      PE.PREFER_NONE, PE.PREFER_AVOID)


def test_stage_72_is_the_named_absence():
    """71.8 now exists and consumes the bridge; Stage 72 does not."""
    out = PE.build(_fr(), _rows())
    assert "entry_engine" in out["missing_inputs"]
    assert "strike_validation" not in out["missing_inputs"]


def test_stage_71_8_consumes_the_bridge_this_stage_publishes():
    """The contract has a second signature now — assert the two agree rather
    than trusting that they do."""
    from mios_v5 import strike_validation as SV
    out = PE.build(_fr(), _rows(), leg_totals=_totals())
    graded = SV.build(premium=out, chain_rows=[], selected={"CALL": 24250.0})
    assert graded["bridge"]["preferred_premium"] == \
        out["preferred"]["preferred"]
    assert graded["call"]["energy"] == out["sides"]["CALL"]["energy"]


# ── Phase 7 · the horizon join survives ─────────────────────────────────

def test_the_horizon_cross_check_still_flags_a_dead_premium():
    """The most valuable thing the stage does, and it is not in the spec."""
    matrix = {"rows": [{"horizon": "scalp", "side": "PUT", "score": 40}]}
    out = PE.build(_fr(), _rows(call_dir="🟢", put_dir="⚪"), matrix=matrix,
                   leg_totals=_totals(put_buy=0.1e6, put_sell=0.1e6))
    row = out["horizons"][0]
    assert row["agreement"] in ("CONTRADICTED", "UNKNOWN")


# ── the panel renders the new fields ────────────────────────────────────

def test_the_panel_shows_preferred_confidence_and_one_trigger():
    out = PE.build(_fr(dealer_levels={"dealer_wall": 24000.0}, spot=24100.0),
                   _rows(), leg_totals=_totals())
    html = premium_energy_html(out)
    assert "Preferred" in html and "Confidence" in html
    assert "Top trigger" in html
    assert html.count("Top trigger") == 1
    assert "CBV" in html and "CSV" in html


# ══════════════════════════════════════════════════════════════════════
#  seven Shift states, and Energy Acceleration
# ══════════════════════════════════════════════════════════════════════

def test_holding_is_an_official_state_not_a_fallback():
    """Energy that exists and is not changing is a different fact from energy
    that is coiling. Compression is a structure Stage 37 measures; "nothing
    moved" is not evidence of one."""
    assert len(PE.SHIFT_STATES) == 7
    assert PE.SHIFT_HOLDING in PE.SHIFT_STATES
    assert len(set(PE.SHIFT_STATES)) == 7


def test_every_shift_state_is_reachable_and_named():
    """A state nothing can produce is a word in a docstring, not a reading."""
    seen = set()
    fr_flat = _fr(energy_read={"strength": 62, "compression": 10,
                               "release_probability": 40,
                               "expansion_readiness": 40, "state": "NEUTRAL",
                               "ready": True})
    fr_comp = _fr(energy_read={"strength": 62, "compression": 80,
                               "release_probability": 40,
                               "expansion_readiness": 40, "state": "NEUTRAL",
                               "ready": True})
    ctx_flat = PE._market_context(fr_flat)
    ctx_comp = PE._market_context(fr_comp)
    none_beh = {"state": None, "pressure": None}
    seen.add(PE._shift(90.0, 50.0, none_beh, ctx_flat)["state"])   # Exploding
    seen.add(PE._shift(60.0, 50.0, none_beh, ctx_flat)["state"])   # Increasing
    seen.add(PE._shift(40.0, 50.0, none_beh, ctx_flat)["state"])   # Decreasing
    seen.add(PE._shift(50.0, 50.0, none_beh, ctx_flat)["state"])   # Holding
    seen.add(PE._shift(50.0, 50.0, none_beh, ctx_comp)["state"])   # Compressing
    seen.add(PE._shift(51.0, 50.0, {"state": "building"},
                       ctx_flat)["state"])                          # Building
    seen.add(PE._shift(49.0, 50.0, {"state": "distribution"},
                       ctx_flat)["state"])                          # Distributing
    assert seen == set(PE.SHIFT_STATES)


def test_acceleration_is_the_energy_change():
    """Current energy minus previous, published under its own name."""
    weak = PE.build(_fr(), _rows(call_dir="🔴"), leg_totals=_totals())
    strong = PE.build(_fr(), _rows(call_dir="🟢"), leg_totals=_totals(),
                      previous=weak)
    acc = strong["shift"]["CALL"]["acceleration"]
    assert acc == round(strong["call"]["energy"] - weak["call"]["energy"])
    assert acc > 0


def test_acceleration_is_unknown_before_it_can_be_measured():
    """Cycle one has nothing to subtract from."""
    out = PE.build(_fr(), _rows())
    assert out["shift"]["CALL"]["acceleration"] is None


def test_speeding_up_needs_a_third_cycle():
    """Two points describe a change; three are the fewest that can describe a
    change *in* the change."""
    c1 = PE.build(_fr(), _rows(call_dir="🔴"), leg_totals=_totals())
    c2 = PE.build(_fr(), _rows(call_dir="🟢"), leg_totals=_totals(),
                  previous=c1)
    assert c2["shift"]["CALL"]["accelerating"]["state"] == "UNKNOWN"
    c3 = PE.build(_fr(), _rows(call_dir="🟢"), leg_totals=_totals(),
                  previous=c2)
    assert c3["shift"]["CALL"]["accelerating"]["state"] in ("UP", "DOWN",
                                                            "STEADY")


def test_acceleration_compares_magnitude_not_sign():
    """A fall accelerating from −4 to −15 is speeding up in the sense a trader
    means, even though the number went down."""
    assert PE._accelerating(-15.0, -4.0)["state"] == "UP"
    assert PE._accelerating(-4.0, -15.0)["state"] == "DOWN"
    assert PE._accelerating(6.0, 5.0)["state"] == "STEADY"
    assert PE._accelerating(None, 5.0)["state"] == "UNKNOWN"


def test_acceleration_reaches_the_bridge():
    c1 = PE.build(_fr(), _rows(call_dir="🔴"), leg_totals=_totals())
    c2 = PE.build(_fr(), _rows(call_dir="🟢"), leg_totals=_totals(),
                  previous=c1)
    assert "energy_acceleration" in PE.BRIDGE_KEYS
    assert set(c2["bridge"]["energy_acceleration"]) == {"CALL", "PUT"}
    assert c2["bridge"]["energy_acceleration"]["CALL"] is not None


def test_the_panel_shows_the_acceleration_beside_the_state():
    """Either alone misleads: the word without a size, or a size without the
    mechanism behind it."""
    c1 = PE.build(_fr(), _rows(call_dir="🔴"), leg_totals=_totals())
    c2 = PE.build(_fr(), _rows(call_dir="🟢"), leg_totals=_totals(),
                  previous=c1)
    html = premium_energy_html(c2)
    acc = c2["shift"]["CALL"]["acceleration"]
    assert f"{acc:+.0f}" in html


# ══════════════════════════════════════════════════════════════════════
#  the compact form on the MIOS V6 card
# ══════════════════════════════════════════════════════════════════════

def _live_energy():
    """The reading that prompted this: energy prefers PUT, spike prefers CALL."""
    return {"ready": True,
            "call": {"energy": 27, "spike": 39},
            "put": {"energy": 46, "spike": 34},
            "dominance": "PUT Dominant",
            "preferred": {"label": "Prefer PUT"},
            "confidence": {"grade": "C"}}


def test_the_compact_card_carries_both_sides_of_both_rows():
    from mios_v5.ui.premium_energy_panel import compact_html
    html = compact_html(_live_energy())
    for probe in ("C 27%", "P 46%", "C 39%", "P 34%"):
        assert probe in html, probe


def test_the_compact_card_never_drops_spike_for_energy():
    """⭐ Energy and spike answer different questions and routinely disagree —
    27/46 energy against 39/34 spike is the side with the participation not
    being the side with the expansion odds. A compact view is exactly where the
    second row gets quietly dropped, and choosing one for the trader is not a
    panel's call."""
    from mios_v5.ui.premium_energy_panel import compact_html
    html = compact_html(_live_energy())
    assert "energy" in html and "spike" in html
    # …and the disagreement is shown, never scored: no verdict Stage 71.7
    # never published
    for invented in ("conflict", "diverge", "disagree", "override"):
        assert invented not in html.lower(), invented


def test_the_compact_card_carries_the_verdicts_it_was_given():
    from mios_v5.ui.premium_energy_panel import compact_html
    html = compact_html(_live_energy())
    assert "Prefer PUT" in html and "conf C" in html and "PUT Dominant" in html


def test_a_missing_verdict_draws_no_chip_rather_than_a_dash():
    from mios_v5.ui.premium_energy_panel import compact_html
    d = _live_energy()
    d.pop("preferred"); d.pop("confidence"); d.pop("dominance")
    html = compact_html(d)
    assert "C 27%" in html
    assert "conf" not in html and "Dominant" not in html


def test_the_compact_card_says_nothing_when_the_stage_is_not_ready():
    """A hollow strip on the card above the app is worse than no strip."""
    from mios_v5.ui.premium_energy_panel import compact_html
    assert compact_html({"ready": False}) == ""
    assert compact_html(None) == ""
    assert compact_html({"ready": True, "call": {}, "put": {}}) == "", \
        "ready with no numbers is still nothing to say"


def test_a_missing_number_is_a_dash_not_a_zero():
    from mios_v5.ui.premium_energy_panel import compact_html
    html = compact_html({"ready": True, "call": {"energy": 27},
                         "put": {"spike": 34}})
    assert "C 27%" in html and "P 34%" in html
    assert "0%" not in html


def test_the_compact_card_recomputes_nothing():
    """It lives in the panel that owns this data, so the card and the full
    section below cannot disagree."""
    import ast
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "mios_v5" / "ui"
           / "premium_energy_panel.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)
              and n.name == "compact_html")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert not (called & {"build", "run", "compute", "evaluate"})


def test_the_v6_card_renders_it_from_the_published_object():
    """Not a second read of the raw legs — the same `_premium_energy` the full
    section renders."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    tree = ast.parse((root / "vob_minimal.py").read_text())
    consts = {n.value for n in ast.walk(tree)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_premium_energy" in consts
    src = (root / "vob_minimal.py").read_text()
    assert "_pe_html" in src, "the compact block is never assembled"
