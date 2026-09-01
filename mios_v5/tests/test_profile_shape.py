"""Stage 71.86 — Profile Shape, and the profile overlay.

Two things are under test, and the first matters more than the classifier:

**that this module computes nothing anybody else owns.** The specification it
came from asked for HVN, LVN, POC, VAH, VAL, per-level sentiment, dynamic POC,
liquidity behaviour and volume behaviour — every one of which already has an
owner, and one of which (`compute_vpfr`) is protected by a test that forbids a
fifth implementation. The audit cut the build down to the one fact with no
owner. These tests are what keeps it cut down.
"""

import ast
import pathlib

import pytest

from mios_v5 import profile_shape as PS
from mios_v5.ui import profile_overlay as PO

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "profile_shape.py"


# ══════════════════════════════════════════════════════════════════════
#  profile builders — bins in the shape the producer publishes
# ══════════════════════════════════════════════════════════════════════

def _rows(weights, low=100.0, step=1.0, sentiment="Bullish"):
    """Bins low→high with the given volumes, shaped like the real producer's."""
    top = max(weights) or 1.0
    out = []
    for i, w in enumerate(weights):
        ratio = w / top
        out.append({
            "bin_low": low + i * step, "bin_high": low + (i + 1) * step,
            "price_level": low + (i + 0.5) * step,
            "total_volume": w, "ratio": round(ratio, 4),
            "volume_pct": round(100 * w / (sum(weights) or 1), 2),
            "node_type": "High" if ratio > 0.73 else "Low" if ratio < 0.21
                         else "Average",
            "sentiment": sentiment, "sentiment_strength": 50.0,
            "is_poc": w == top,
        })
    return out


def _p_shape():
    """Mass high in the range, thin below — the short-covering signature."""
    return _rows([1, 1, 1, 2, 2, 3, 5, 30, 46, 50, 44, 28])


def _b_shape():
    return _rows([28, 44, 50, 46, 30, 5, 3, 2, 2, 1, 1, 1])


def _d_shape():
    return _rows([1, 3, 8, 20, 38, 50, 48, 34, 17, 7, 2, 1])


def _double():
    return _rows([4, 22, 48, 26, 8, 3, 2, 4, 9, 30, 50, 24])


def _trend():
    return _rows([40, 42, 39, 41, 43, 40, 38, 42, 41, 39, 40, 42])


def _thin():
    return _rows([1, 0.5, 50, 1, 0.4, 0.6, 1, 0.5, 0.3, 1, 0.8, 0.5])


# ══════════════════════════════════════════════════════════════════════
#  ⛔ it computes nothing that already has an owner
# ══════════════════════════════════════════════════════════════════════

def test_it_does_not_compute_a_fifth_poc():
    """Audit 71.8 chose `compute_vpfr` and forbade a fifth POC implementation.

    The check is on the AST, not the text — the docstring explains the rule at
    length and a grep for "poc" trips on the prose every time.
    """
    tree = ast.parse(SRC.read_text())
    defined = {n.name for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for forbidden in ("compute_poc", "find_poc", "calculate_poc",
                      "compute_vpfr", "value_area", "compute_value_area",
                      "classify_node", "hvn", "lvn"):
        assert forbidden not in defined, f"{forbidden} duplicates an owner"


def test_every_consumed_fact_names_its_owner():
    for name, owner in PS.CONSUMED.items():
        assert owner and owner != PS.UNKNOWN, name
        assert name not in PS.COMPUTED_HERE, f"{name} is both consumed and owned"


def test_it_imports_no_market_data_and_no_io():
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"requests", "httpx", "supabase", "streamlit",
                            "pandas", "numpy", "plotly"})


def test_the_levels_are_carried_not_recomputed():
    """`poc`, `vah` and `val` travel on the metadata untouched."""
    out = PS.classify(_d_shape(), poc=105.5, vah=108.0, val=103.0)
    assert out.metadata["poc"] == 105.5
    assert out.metadata["vah"] == 108.0
    assert out.metadata["val"] == 103.0


# ══════════════════════════════════════════════════════════════════════
#  the shapes
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rows,expected", [
    (_p_shape(), PS.P_SHAPE),
    (_b_shape(), PS.B_SHAPE),
    (_double(), PS.DOUBLE),
    (_trend(), PS.TREND),
])
def test_each_signature_is_recognised(rows, expected):
    assert PS.classify(rows).shape == expected


def test_a_central_tight_profile_is_a_balance_shape():
    """D and Balanced are both central; which one is a question of width, and
    either answer is a balance — the test asserts the family, not the label."""
    assert PS.classify(_d_shape()).shape in (PS.D_SHAPE, PS.BALANCED)


def test_p_and_b_are_mirror_images():
    p, b = PS.classify(_p_shape()), PS.classify(_b_shape())
    assert p.shape == PS.P_SHAPE and b.shape == PS.B_SHAPE
    assert p.poc_position > 0.5 > b.poc_position


def test_a_thin_profile_reports_low_participation():
    out = PS.classify(_thin())
    assert out.participation < 0.5


def test_a_rough_top_is_one_distribution_not_two():
    """Two humps with a shallow dip between them is texture, not a second
    distribution. Calling it Double would split one value area in half."""
    rows = _rows([2, 8, 40, 50, 44, 38, 42, 48, 36, 10, 3, 1])
    assert PS.classify(rows).shape != PS.DOUBLE


# ══════════════════════════════════════════════════════════════════════
#  Neutral is an absence, not a weak read
# ══════════════════════════════════════════════════════════════════════

def test_no_profile_is_neutral_with_unknown_confidence():
    out = PS.classify([])
    assert out.shape == PS.NEUTRAL
    assert out.confidence == PS.UNKNOWN
    assert out.poc_position == PS.UNKNOWN


def test_too_few_bins_reports_unknown_rather_than_guessing():
    out = PS.classify(_rows([1, 5, 9, 4]))
    assert out.shape == PS.NEUTRAL
    assert out.confidence == PS.UNKNOWN
    assert out.reporting == 0


def test_bins_with_no_volume_are_not_a_flat_profile():
    out = PS.classify(_rows([0] * 12))
    assert out.shape == PS.NEUTRAL
    assert out.confidence == PS.UNKNOWN


def test_two_shapes_fitting_equally_is_neutral_not_a_coin_toss():
    """The margin gate. Below it the honest answer is that we could not tell —
    exactly as Stage 71.85's Neutral behaves."""
    out = PS.classify(_d_shape())
    if out.shape == PS.NEUTRAL:
        assert out.confidence == PS.UNKNOWN
    else:
        ranked = sorted(out.scores.values(), reverse=True)
        assert (ranked[0] - ranked[1]) / ranked[0] >= PS._MARGIN


def test_a_named_shape_always_carries_a_number():
    for rows in (_p_shape(), _b_shape(), _double(), _trend()):
        out = PS.classify(rows)
        assert out.confidence != PS.UNKNOWN
        assert 0 < float(out.confidence) <= 100


# ══════════════════════════════════════════════════════════════════════
#  identity · immutability · never raising
# ══════════════════════════════════════════════════════════════════════

def test_identity_and_integrity():
    out = PS.classify(_p_shape())
    assert out.verify() is True
    assert out.version == PS.VERSION
    assert set(out.identity()) == {"id", "version", "created_at", "hash"}


def test_two_profiles_get_different_ids():
    assert PS.classify(_p_shape()).id != PS.classify(_p_shape()).id


def test_the_verdict_is_frozen():
    out = PS.classify(_p_shape())
    with pytest.raises(Exception):
        out.shape = PS.TREND
    with pytest.raises(Exception):
        out.scores["P"] = 1.0


def test_it_never_raises_on_junk():
    for junk in (None, [], [{}], "rows", [{"bin_low": "x"}], [None, 3],
                 [{"bin_low": 1, "bin_high": 0, "ratio": 1}]):
        out = PS.run(junk)
        assert out.shape in PS.SHAPES


def test_the_measurements_are_on_the_object():
    """A shape a reader cannot check against the numbers is a label."""
    out = PS.classify(_p_shape())
    for field in ("poc_position", "concentration", "participation", "skew"):
        assert getattr(out, field) != PS.UNKNOWN
    assert out.why


def test_rows_are_sorted_by_price_not_trusted_in_order():
    forward = PS.classify(_p_shape())
    shuffled = list(_p_shape())[::-1]
    assert PS.classify(shuffled).shape == forward.shape


# ══════════════════════════════════════════════════════════════════════
#  the overlay — presentation only
# ══════════════════════════════════════════════════════════════════════

def test_the_overlay_computes_nothing():
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "profile_overlay.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not (imported & {"numpy", "pandas", "plotly", "streamlit",
                            "profile_shape", "indicators"})


def test_a_bin_with_no_ratio_draws_nothing():
    """Without the producer's own volume/max there is no scale, and inventing
    one would make a thin level look heavy."""
    assert PO.bands([{"bin_low": 1, "bin_high": 2}]) == []


def test_volume_sets_opacity_and_sentiment_sets_hue():
    out = PO.bands(_rows([50, 5], sentiment="Bearish"))
    assert len(out) == 2
    assert out[0]["opacity"] > out[1]["opacity"]
    assert all("239, 83, 80" in b["colour"] for b in out)


def test_the_heaviest_band_never_hides_the_candles():
    for band in PO.bands(_rows([50, 40, 30])):
        assert band["opacity"] <= PO.MAX_OPACITY


def test_neutral_sentiment_is_grey_not_a_blend():
    grey = PO.bands(_rows([10], sentiment="Neutral"))[0]["colour"]
    assert "120, 123, 134" in grey


def test_unreported_levels_draw_no_line():
    assert PO.levels({}) == []
    assert PO.levels({"poc_price": None, "value_area_high": "x"}) == []
    keys = {lv["key"] for lv in PO.levels({"poc_price": 100.0,
                                           "value_area_low": 98.0})}
    assert keys == {"poc", "val"}


def test_the_badge_reads_a_live_shape_and_a_stored_one_the_same():
    live = PS.classify(_p_shape())
    assert PO.shape_badge(live)["text"] == PO.shape_badge(live.to_dict())["text"]


def test_a_neutral_badge_is_the_faintest_tone():
    """Neutral means the read was absent; it must not draw the eye."""
    assert PO.SHAPE_TONE["Neutral"] != PO.SHAPE_TONE["P"]
    assert PO.shape_badge(PS.classify([]))["text"] == "Neutral"


def test_no_badge_tone_is_a_retired_grey():
    """The obvious grey for "faintest" is one the palette retired for sitting
    near 4:1 on a card. Faint is not the same as unreadable."""
    from mios_v5.ui.theme import RETIRED
    assert not (set(PO.SHAPE_TONE.values()) & set(RETIRED))


def test_drawing_never_raises_without_plotly():
    assert PO.draw(None, 1, 1, rows=_p_shape()) == {"bands": 0, "levels": 0,
                                                    "badge": 0, "dyn_poc": 0}


# ══════════════════════════════════════════════════════════════════════
#  the three charts
# ══════════════════════════════════════════════════════════════════════

def test_all_three_panels_accept_their_own_profile():
    """Each panel gets its OWN profile. Drawing the index POC on a premium
    panel would mark a price that series can never trade — the rule Stage 71.8
    settled and the same one `_leg_overlay` already follows."""
    import inspect

    from mios_v5.ui.terminal_chart import terminal_chart
    params = inspect.signature(terminal_chart).parameters
    for name in ("nifty_profile", "call_profile", "put_profile"):
        assert name in params, name
        assert params[name].default is None


def test_all_three_panels_are_actually_passed_a_profile():
    """A parameter nothing passes is the regression this repo has hit twice —
    `cfb6c93` and `_atm_leg_ltf_delta`. A test that the overlay works says
    nothing about whether it runs.

    ⚠️ The terminal is now drawn by `terminal_charts_split` (three figures, one
    per chart, each with its own Fullscreen button), so the profile arguments are
    passed to it rather than to the combined `terminal_chart`."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text())
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "terminal_charts_split")
    passed = {kw.arg for kw in call.keywords}
    assert {"nifty_profile", "call_profile", "put_profile"} <= passed


def test_the_leg_profile_is_cached_on_the_bar_count():
    """The terminal reruns every ~20s and a profile only changes when a bar
    closes. Recomputing 25 bins per leg per rerun is the shape of the problem
    that made egress 0.59 GB/day."""
    src = (ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    assert "_panel_profiles" in src
    assert '_bars' in src


def test_the_dashboard_builds_no_second_profile_implementation():
    """It may CALL the owner; it may not become one."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_panel_profile")
    names = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "calculate_money_flow_profile" in names, "must use the owner"
    assert not (names & {"compute_vpfr", "compute_dynamic_poc"})


def test_the_leg_profile_uses_the_app_s_registered_builder():
    """`_premium_builders["mfp"]` already exists for exactly this. Calling the
    indicator directly builds a SECOND premium profile with different
    parameters — `source="Volume"` against the builder's "Money Flow" — so one
    leg would carry two profiles that disagree."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_panel_profile")
    # AST, not text. A grep for `source="Volume"` matches the COMMENT that
    # explains why "Volume" is wrong — the same way every source-text guard in
    # this repo has tripped on the prose describing its own rule.
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_premium_builders" in literals, "must use the registered builder"
    assert "mfp" in literals
    sources = {kw.value.value for c in ast.walk(fn)
               if isinstance(c, ast.Call) for kw in c.keywords
               if kw.arg == "source" and isinstance(kw.value, ast.Constant)}
    assert "Volume" not in sources, "the registered builder uses Money Flow"


def test_the_profile_is_drawn_under_the_candles():
    """Bands over the price series would hide it.

    ⚠️ This used to assert that `_profile_overlay` appeared *before*
    `_add_series` in the source, on the reasoning that call order is what
    stacks a Plotly figure. It is not, and that reading of it was actively
    harmful: `add_hrect`/`add_hline` with `row=`/`col=` are **silently dropped
    when the subplot has no trace yet**, so drawing the profile first did not
    put it underneath the candles — it threw it away. Every panel's bands, POC,
    VAH and VAL were computed each cycle and reached the figure on none of
    them, and this test held that in place.

    `layer="below"` is what actually controls the stacking, so that is what is
    asserted now. `test_terminal_chart_labels` covers the other half — that the
    marks reach the figure at all — by reading the rendered figure rather than
    the source.
    """
    src = (ROOT / "mios_v5" / "ui" / "profile_overlay.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "draw")
    rects = [c for c in ast.walk(fn)
             if isinstance(c, ast.Call)
             and getattr(c.func, "attr", "") == "add_hrect"]
    assert rects, "the bands are no longer drawn as rects"
    for call in rects:
        below = {kw.value.value for kw in call.keywords
                 if kw.arg == "layer" and isinstance(kw.value, ast.Constant)}
        assert below == {"below"}, "a band would render over the candles"
