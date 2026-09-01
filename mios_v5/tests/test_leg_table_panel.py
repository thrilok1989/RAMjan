"""🧮 The ATM±1 leg tabulation, finally on screen.

`build_leg_bias_table` computed 19 per-signal columns for 6 legs every cycle and
**nothing ever drew them**. The rows reached `_leg_bias_cache`, and every consumer
— Stage 14's order flow, three alert paths, a gate check — took the *verdicts* and
threw the detail away. So the app could say "Leg Fast Verdict: BEARISH" with no way
to see which of VOB / S/R / Div / Ign / Absorb / CVD voted for it.

Same class as the FII/DII row: produced, published, drawn nowhere.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from mios_v5.ui import leg_table_panel as L

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: A row in exactly the shape `build_leg_bias_table` emits — `vob_minimal.py:10266`.
def _row(leg="ATM CE 24600", ltp=118.4, **over):
    r = {
        "Leg": leg, "LTP": f"₹{ltp:.1f}",
        "VOB": "🟢", "Sup VOB": "🚀 BUILD", "Res VOB": "• INTACT",
        "S/R": "🟢", "Div": "⚪", "Ign": "🟢",
        "Absorb": "⚪", "CVD": "🟢", "OIvel": "🔴",
        "VWAP": "🟢", "VWAP50": "🟢", "VWAP20": "🔴",
        "VIDYA": "🟢", "VIDYA50": "⚪", "VIDYA20": "🟢",
        "MFP": "🔴", "MFP50": "⚪", "MFP20": "🟢",
        "Leg Verdict": "🟢 BULL (+6)", "→ NIFTY": "🟢 BULL",
    }
    r.update(over)
    return r


_ROWS = [_row(), _row("ATM PE 24600", 96.2, VOB="🔴",
                      **{"Leg Verdict": "🔴 BEAR (-4)", "→ NIFTY": "🟢 BULL"})]
_OVERALL = {
    "dir": "BULL", "em": "🟢", "label": "STRONG BULLISH",
    "bull": 4, "bear": 1, "net": 3,
    "by_speed": {"fast": {"dir": "BULL", "em": "🟢", "label": "BULLISH",
                          "bull": 3, "bear": 1, "net": 2},
                 "lag": {"dir": "BEAR", "em": "🔴", "label": "BEARISH",
                         "bull": 1, "bear": 3, "net": -2},
                 "mis": {"dir": "NEUTRAL", "em": "⚪", "label": "NEUTRAL / MIXED",
                         "bull": 1, "bear": 1, "net": 0}},
}


# ══════════════════════════════════════════════════════════════════════
#  the grouping must match the engine that scores it
# ══════════════════════════════════════════════════════════════════════

def test_the_speed_groups_hold_the_same_signals_the_app_scores():
    """⚠️ The load-bearing assertion. `overall['by_speed']` is scored from
    `_SPEED_GROUPS` in `vob_minimal.py`; if this panel groups a column under a
    different heading, the detail and the verdict above it describe different
    things.

    Compared as SETS: the panel orders `lag` as VWAP·VWAP50·VWAP20·VIDYA·VIDYA50·
    VIDYA20 for readability while the app lists VIDYA first. Order does not affect
    the app's score (it sums), but membership must be identical.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_SPEED_GROUPS = {")
    block = src[i:src.index("}", src.index("'mis'", i)) + 1]
    app = ast.literal_eval(block.split("=", 1)[1].strip())

    panel = {k: set(cols) for k, _label, cols in L.GROUPS}
    assert {k: set(v) for k, v in app.items()} == panel
    assert set(app) == {"fast", "lag", "mis"}


def test_the_status_columns_are_outside_the_groups():
    """`Sup VOB` / `Res VOB` are zone BEHAVIOUR words, not votes — the app leaves
    them out of `_SPEED_GROUPS`, so showing them inside a scored bucket would
    imply they contributed to that bucket's verdict."""
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_SPEED_GROUPS = {")
    block = src[i:src.index("}", src.index("'mis'", i)) + 1]
    app = ast.literal_eval(block.split("=", 1)[1].strip())
    scored = {s for cols in app.values() for s in cols}
    for c in L.STATUS_COLS:
        assert c not in scored, c
        assert not any(c in cols for _k, _l, cols in L.GROUPS)


def test_every_row_key_the_builder_emits_is_displayed():
    """⚠️ Derived from the app's own row literal. A signal added to
    `build_leg_bias_table` and not to this panel would be computed and hidden —
    which is the bug being fixed."""
    src = (_ROOT / "vob_minimal.py").read_text()
    start = src.index("rows.append({", src.index("def build_leg_bias_table"))
    literal = src[start + len("rows.append("):src.index("})", start) + 2]
    keys = set(re.findall(r"'([^']+)':", literal))

    shown = ({"Leg", "LTP", "Leg Verdict", "→ NIFTY"} | set(L.STATUS_COLS)
             | {c for _k, _l, cols in L.GROUPS for c in cols})
    assert keys - shown == set(), f"computed but not displayed: {keys - shown}"


# ══════════════════════════════════════════════════════════════════════
#  what it draws
# ══════════════════════════════════════════════════════════════════════

def test_every_leg_and_every_signal_reaches_the_table():
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "ATM CE 24600" in html and "ATM PE 24600" in html
    assert "₹118.4" in html and "₹96.2" in html
    for _k, _l, cols in L.GROUPS:
        for c in cols:
            assert c in html, c


def test_the_group_headers_carry_their_own_verdicts():
    """Fast BULL against lagging BEAR is the actionable read — the move is
    turning. A flat table hides it."""
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "FAST" in html and "LAGGING" in html and "MISGUIDING" in html
    assert "BULL +2" in html and "BEAR -2" in html


def test_the_overall_verdict_is_the_builders_not_recomputed():
    """⚠️ Two answers to "what is the net read?" on one card is the disagreement
    this panel must not create."""
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "STRONG BULLISH" in html
    assert "4 bull / 1 bear" in html

    # hand it a contradictory aggregate — it must echo, not correct
    odd = dict(_OVERALL, label="BEARISH", dir="BEAR", em="🔴", bull=0, bear=5)
    assert "BEARISH" in L.leg_table_html(_ROWS, odd)


def test_the_pe_flip_is_shown_as_the_builder_worded_it():
    """A PE leg reading BEAR on its own premium is BULL for NIFTY. The row already
    carries both, and the table must not collapse them to one."""
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "BEAR (-4)" in html          # the leg's own verdict
    assert "→ NIFTY" in html            # and the flipped implication


def test_the_legend_explains_the_glyphs():
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "🟢 bull" in html and "🔴 bear" in html
    assert "flips for PE" in html


def test_the_table_scrolls_inside_its_own_box():
    """⚠️ 19 signal columns will not fit a narrow pane, and a table that makes the
    PAGE scroll sideways makes every other panel unusable."""
    assert "overflow-x:auto" in L.leg_table_html(_ROWS, _OVERALL)


# ══════════════════════════════════════════════════════════════════════
#  absence and junk
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rows", [None, [], (), "nope", 7, [{}], [{"Leg": ""}],
                                  [None], ["x"]])
def test_no_legs_draws_nothing(rows):
    """Not an empty grid with six blank rows."""
    assert L.leg_table_html(rows, _OVERALL) == ""


def test_no_overall_still_draws_the_rows():
    """The per-leg detail is useful on its own; inventing an aggregate to fill the
    footer is the one thing this file must not do."""
    html = L.leg_table_html(_ROWS, None)
    assert "ATM CE 24600" in html
    assert "STRONG BULLISH" not in html


def test_a_missing_signal_shows_neutral_not_a_gap():
    thin = [{"Leg": "ATM CE 24600", "LTP": "₹118.4"}]
    html = L.leg_table_html(thin, None)
    assert html and "⚪" in html


@pytest.mark.parametrize("junk", [None, {}, "x", 7, [], {"by_speed": "no"},
                                  {"by_speed": {"fast": "no"}}])
def test_a_junk_overall_does_not_crash(junk):
    assert L.leg_table_html(_ROWS, junk)


def test_html_is_escaped():
    html = L.leg_table_html([_row(leg="<script>x</script>")], None)
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_micro_form_gives_the_three_speed_verdicts():
    line = L.micro(_ROWS, _OVERALL)
    assert "bull" in line and "bear" in line
    assert L.micro(_ROWS, None) == ""
    assert L.micro(None, None) == ""


def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "ui" / "leg_table_panel.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas"}
    assert "session_state" not in src


# ══════════════════════════════════════════════════════════════════════
#  wiring — below the chart, and reading the published cache
# ══════════════════════════════════════════════════════════════════════

def _charts_fn():
    src = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    return next(n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen"), src


def test_the_table_is_drawn_by_the_charts_screen():
    """⚠️ The guard that matters — a renderer nothing calls is the bug this fixes."""
    fn, _src = _charts_fn()
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "leg_table_html" in called


def test_it_is_drawn_BELOW_the_chart():
    fn, src = _charts_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert body.index("_terminal_chart") < body.index("leg_table_html")


def test_it_reads_the_published_cache_and_does_not_rebuild():
    """⚠️ `_render_main_analyzer` owns the `build_leg_bias_table` call. Rebuilding
    here would repeat six legs of VOB/VIDYA/MFP work every cycle AND risk two
    different answers on one screen."""
    fn, src = _charts_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert "_leg_bias_cache" in body
    # ⚠️ On the CALLS, not the text — the comment above the wiring names the
    # builder to explain why it is not called, and a raw grep matched my own
    # prose (the eighth time in this work).
    called = {c.func.id for c in ast.walk(fn)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "build_leg_bias_table" not in called


def test_an_absent_cache_says_why_rather_than_drawing_nothing():
    fn, src = _charts_fn()
    body = ast.get_source_segment(src, fn) or ""
    assert "_feed_reason" in body, (
        "an empty tabulation must explain itself like every other standing-by "
        "panel, not vanish")


def test_the_verdict_column_is_not_labelled_LEG():
    """⚠️ Caught by rendering: the header read "LEG", duplicating the first
    column, so a row's own conclusion looked like a second leg name."""
    html = L.leg_table_html(_ROWS, _OVERALL)
    assert "VERDICT" in html
    assert html.count(">LEG<") == 1
