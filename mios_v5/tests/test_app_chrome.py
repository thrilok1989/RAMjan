"""The app's header, footer and browser-tab title.

Chrome is the one part of a screen a trader reads without meaning to, so the
tests here are mostly about what it must NEVER say: a price it does not have, a
direction nobody reported, or a change of `+0.00` when the previous close is
unknown.
"""

import ast
import pathlib

from mios_v5.ui import app_chrome as C
from mios_v5.ui import theme as T

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "mios_v5" / "ui" / "app_chrome.py"


# ══════════════════════════════════════════════════════════════════════
#  the browser tab
# ══════════════════════════════════════════════════════════════════════

def test_the_tab_leads_with_the_price():
    """A background tab is ~20 characters wide. The number is the reason to
    look at it, so the app name is dropped once there is one."""
    title = C.tab_title(24650.3, "BULLISH")
    assert title.startswith("🟢")
    assert "24,650.30" in title
    assert C.APP_NAME not in title


def test_the_bias_reaches_the_tab_as_a_coloured_glyph():
    """A tab renders plain text — no markup, no styling, no colour. An emoji is
    the only coloured thing it can show."""
    assert C.tab_title(24650.3, "STRONG BULLISH").startswith("🟢")
    assert C.tab_title(24650.3, "BEARISH").startswith("🔴")
    assert C.tab_title(24650.3, "NEUTRAL").startswith("🟡")
    assert C.tab_title(24650.3, None).startswith("⚪")


def test_a_missing_spot_leaves_the_price_out_rather_than_printing_zero():
    assert "0.00" not in C.tab_title(None, "BULLISH")
    assert C.APP_NAME in C.tab_title(None, "BULLISH")
    assert C.tab_title(None, None) == C.APP_NAME


def test_the_title_script_targets_the_parent_document():
    """A Streamlit component renders inside an iframe; `document.title` there
    renames a frame nobody can see."""
    js = C.tab_title_script("x")
    assert "parent.document.title" in js
    assert "try" in js and "catch" in js


def test_a_quote_in_the_title_cannot_break_out_of_the_script():
    js = C.tab_title_script('a " b \\ c')
    assert '\\"' in js and "\\\\" in js


# ══════════════════════════════════════════════════════════════════════
#  the header
# ══════════════════════════════════════════════════════════════════════

def test_the_header_carries_price_change_and_both_biases():
    html = C.header_html(24650.3, 24580.0, "BULLISH", "NEUTRAL",
                         "🟢 Market open", "15:22:04 IST")
    assert "24,650.30" in html
    assert "+70.30" in html and "+0.29%" in html
    assert "V5" in html and "V6" in html
    assert "Market open" in html and "15:22:04 IST" in html


def _colour_of(html, needle):
    """The colour on the span that renders `needle`."""
    i = html.index(needle)
    window = html[max(0, i - 120):i]
    return window.rsplit("color:", 1)[-1].split(";")[0].split("'")[0].strip()


def test_the_price_takes_the_bias_colour_and_the_change_takes_the_moves():
    """⭐ The owner asked for this, and it is a real trade.

    Both used to follow the move, so a down day painted the number red however
    bullish the engines were. The price now follows the bias — the reading a
    glance off a frozen strip is for.

    The change keeps the MOVE's colour on purpose. Colouring both by bias would
    leave a bullish read with nothing on the strip saying price is falling, and
    green on a −80 is a contradiction a trader should see rather than one the
    strip quietly resolves.
    """
    html = C.header_html(24500.0, 24580.0, "BULLISH", "BULLISH")
    assert _colour_of(html, "24,500.00") == T.BULL, "price follows the bias"
    assert _colour_of(html, "-80.00") == T.BEAR, "change still follows the move"


def test_a_missing_bias_leaves_the_price_on_the_move():
    """Never uncoloured: with nothing to take a side from, the move is the only
    honest thing left to colour by."""
    down = C.header_html(24500.0, 24580.0)
    assert _colour_of(down, "24,500.00") == T.BEAR
    up = C.header_html(24650.0, 24580.0)
    assert _colour_of(up, "24,650.00") == T.BULL


def test_v6_wins_the_price_colour_and_v5_stands_in_when_it_is_silent():
    both = C.header_html(24650.0, 24580.0, "BEARISH", "BULLISH")
    assert _colour_of(both, "24,650.00") == T.BULL, "V6 is the newer engine"
    only_v5 = C.header_html(24650.0, 24580.0, "BEARISH", None)
    assert _colour_of(only_v5, "24,650.00") == T.BEAR


def test_no_previous_close_means_no_change_rather_than_a_flat_one():
    """`+0.00` says the market has not moved. Unknown is not flat."""
    html = C.header_html(24650.3, None)
    assert "24,650.30" in html
    assert "+0.00" not in html and "0.00%" not in html


def test_a_missing_spot_draws_a_dash_not_a_zero():
    html = C.header_html(None, 24580.0)
    assert "—" in html and "0.00" not in html


def test_a_bias_nobody_reported_draws_no_chip():
    """An absent engine is not a neutral one."""
    html = C.header_html(24650.3, 24580.0, v5="BULLISH", v6=None)
    assert "V5" in html and "V6" not in html
    assert "V5" not in C.header_html(24650.3, 24580.0)


def test_the_header_escapes_what_it_is_given():
    html = C.header_html(24650.3, 24580.0, market="<script>x</script>")
    assert "<script>" not in html and "&lt;script&gt;" in html


# ══════════════════════════════════════════════════════════════════════
#  the footer
# ══════════════════════════════════════════════════════════════════════

def test_the_footer_says_nothing_here_is_advice():
    """The one thing it exists to say."""
    html = C.footer_html("15:22 IST", "🟢 Market open", C.CHROME_VERSION)
    assert "Advisory only" in html
    assert "no order is placed" in html
    assert C.CHROME_VERSION in html


def test_the_footer_renders_with_nothing_to_say():
    assert C.footer_html()


# ══════════════════════════════════════════════════════════════════════
#  it computes nothing, and it cannot take the app down
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_engine_no_io_and_no_streamlit():
    """Every value arrives as a parameter. `streamlit` is imported inside
    `render_tab_title` only, for the component call — never at module scope,
    so the panel stays testable without a session."""
    tree = ast.parse(SRC.read_text())
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            top.add((node.module or "").split(".")[0])
    assert not (top & {"streamlit", "requests", "pandas", "numpy", "db"})


def test_the_bias_colour_comes_from_the_shared_map():
    """Not a fourth private copy of bull-is-green."""
    tree = ast.parse(SRC.read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and "theme" in (n.module or ""):
            imported |= {a.name for a in n.names}
    assert {"bias_tone", "bias_emoji"} <= imported


def test_nothing_here_raises_on_junk():
    for junk in (None, "x", [], {}, float("nan"), object()):
        C.tab_title(junk, junk)
        C.header_html(junk, junk, junk, junk, "", "")
        C.footer_html(str(junk), str(junk), str(junk))


# ══════════════════════════════════════════════════════════════════════
#  wiring
# ══════════════════════════════════════════════════════════════════════

def test_the_chrome_is_filled_after_the_cycle_not_before():
    """The header sits at the TOP and its values arrive at the BOTTOM. Written
    at the top it would show the previous cycle's price under a live
    timestamp — worse than a blank strip for the second it takes to fill.

    AST, not a text scan: the source comment explains this rule and names both
    functions, so a substring search matches the prose rather than the code.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    order = [c.func.id for c in ast.walk(fn)
             if isinstance(c, ast.Call) and getattr(c.func, "id", "") in
             ("_render_main_analyzer", "_render_app_chrome")]
    assert order == ["_render_main_analyzer", "_render_app_chrome"]


def test_the_chrome_reads_producers_rather_than_computing_anything():
    """Spot and both biases come from `_mios_market_read`, the previous close
    from `_gap_today`, the clock from `_is_market_open`. None is derived here."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "_mios_market_read" in called
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_is_market_open" in names
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_gap_today" in literals


def test_the_old_static_title_is_gone():
    """`st.title` printed a name and nothing else, every cycle, above a page
    whose whole point is the number."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    titles = [c for c in ast.walk(fn) if isinstance(c, ast.Call)
              and getattr(c.func, "attr", "") == "title"]
    assert not titles


def test_the_tab_title_uses_the_api_that_can_actually_run_a_script():
    """⚠️ Streamlit's own deprecation warning is misleading.

    `st.components.v1.html` is deprecated with a removal date already past, and
    the warning says to use `st.iframe`. But `st.iframe` takes a `src` URL and
    cannot render markup at all — following the warning literally makes the tab
    title silently stop working. The real replacement is `st.html` with
    `unsafe_allow_javascript=True`, which is the only one of the three that
    both accepts markup and lets a script run.
    """
    import inspect
    import streamlit as st
    assert "src" in inspect.signature(st.iframe).parameters, (
        "st.iframe still takes a URL — it is not a markup renderer")
    assert "unsafe_allow_javascript" in inspect.signature(st.html).parameters

    src = SRC.read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "render_tab_title")
    body = "\n".join(src.splitlines()[fn.lineno - 1:(fn.end_lineno or fn.lineno)])
    assert "unsafe_allow_javascript" in body
    assert '"iframe"' not in body and "'iframe'" not in body


def test_the_chrome_failure_is_loud_rather_than_swallowed():
    """A swallowed failure here looks exactly like the feature was never built
    — which is what it looked like, and why this test exists.

    Scoped to the handlers that guard the CHROME. `main` also has a legitimate
    silent handler: a disabled hot-path profiler sets `_prof = None` and has
    nothing to announce, and asserting over every handler in the function
    flagged that as a bug.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())

    def _guards(fn_name, needle):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == fn_name)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Try):
                continue
            calls = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            if needle in calls:
                yield node

    # the call site: a chrome that raises must say so
    for node in _guards("main", "_render_app_chrome"):
        spoken = {getattr(c.func, "attr", "") for h in node.handlers
                  for c in ast.walk(h) if isinstance(c, ast.Call)}
        assert spoken & {"warning", "error", "caption"}, (
            "main swallows a chrome failure silently")

    # …and the import guard inside, which used to `return` with no message
    for node in _guards("_render_app_chrome", "render_header"):
        pass
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    silent = [h for t in ast.walk(fn) if isinstance(t, ast.Try)
              for h in t.handlers
              if not [c for c in ast.walk(h) if isinstance(c, ast.Call)]
              and any(isinstance(x, ast.Return) for x in ast.walk(h))]
    assert not silent, "_render_app_chrome returns silently on failure"


# ══════════════════════════════════════════════════════════════════════
#  frozen in place, Word-style
# ══════════════════════════════════════════════════════════════════════

def test_the_strips_carry_the_markers_the_css_needs():
    """The CSS selects the wrapper by what it contains. Without a class on the
    strip there is nothing to select on."""
    assert C.HEADER_CLASS in C.header_html(24650.3, 24580.0)
    assert C.FOOTER_CLASS in C.footer_html("15:22", "open", "v1")


def test_the_rule_targets_the_wrapper_not_the_strip():
    """⭐ The reason this is CSS and not an inline style.

    `position: sticky` moves an element within its containing block, and
    Streamlit sizes `.element-container` to exactly the height of what it
    holds. A sticky div inside a box its own height has nowhere to travel, so
    an inline rule is accepted and does nothing — the confusing kind of broken.
    """
    css = C.chrome_css()
    assert ":has(" in css, "the wrapper can only be selected by its contents"
    assert "position: sticky" in css
    # the strip's own style must NOT try to do it alone
    assert "position:sticky" not in C.header_html(24650.3, 24580.0)
    assert "position: sticky" not in C.header_html(24650.3, 24580.0)


def test_the_header_parks_below_streamlits_own_toolbar():
    """Sticking at 0 slides it underneath."""
    assert C.HEADER_TOP not in ("0", "0px", "0rem")
    assert f"top: {C.HEADER_TOP}" in C.chrome_css()


def test_the_footer_sticks_to_the_bottom():
    assert "bottom: 0" in C.chrome_css()


def test_both_strips_are_opaque():
    """A transparent bar lets the page scroll visibly through it."""
    css = C.chrome_css()
    assert "backdrop-filter" in css
    header = C.header_html(24650.3, 24580.0)
    assert "background:" in header, "the header paints its own ground"
    assert "background: #0e1117" in css, "and so does the footer"


def test_the_footer_returns_to_the_flow_on_a_phone():
    """Two frozen strips would eat most of a short viewport."""
    css = C.chrome_css()
    assert "max-width: 640px" in css
    phone = css.split("max-width: 640px")[1]
    assert "position: static" in phone
    assert C.FOOTER_CLASS in phone and C.HEADER_CLASS not in phone


def test_the_css_is_injected_before_the_strips_are_drawn():
    """A `<style>` block after the markup still applies, but a missing one
    silently un-freezes the page — so it is asserted to run, and first."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    order = [getattr(c.func, "id", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") in
             ("render_chrome_css", "render_header", "render_footer")]
    assert "render_chrome_css" in order
    assert order.index("render_chrome_css") < order.index("render_header")


def test_the_css_never_raises():
    class Boom:
        def markdown(self, *a, **k): raise RuntimeError("no")
    C.render_chrome_css(Boom())


# ══════════════════════════════════════════════════════════════════════
#  ⭐ they must not be empty for most of every refresh
# ══════════════════════════════════════════════════════════════════════

def test_both_strips_are_primed_before_the_cycle_runs():
    """The reported "sometimes it vanishes".

    Both strips are FILLED at the end of the cycle so they carry this cycle's
    spot — but `st_autorefresh` rebuilds the page from the top every twenty
    seconds, so an unprimed placeholder is empty for the entire render, network
    fetches included. They were not vanishing at random: they were absent for
    most of every refresh and present only between cycles.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    order = [getattr(c.func, "id", "") for c in ast.walk(fn)
             if isinstance(c, ast.Call) and getattr(c.func, "id", "") in
             ("_prime_app_chrome", "_render_main_analyzer", "_render_app_chrome")]
    assert order == ["_prime_app_chrome", "_render_main_analyzer",
                     "_render_app_chrome"], (
        "prime, then render the page, then overwrite with this cycle's values")


def test_the_footer_gets_a_placeholder_too():
    """Without one it has no reserved position and is absent for the whole
    render, exactly like the header was."""
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "main")
    empties = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and getattr(n.func, "attr", "") == "empty"]
    assert len(empties) >= 2, "header and footer each need a slot"


def test_the_primed_strip_carries_the_stored_timestamp_not_a_fresh_one():
    """⚠️ The whole reason the fill was late in the first place.

    A previous-cycle price under a live clock claims to be current. Under its
    OWN timestamp it is simply a reading from a moment ago, which is true.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_prime_app_chrome")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "now" not in called and "strftime" not in called, (
        "the priming render must not mint a timestamp")
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "updated" in literals, "it reads the stored one"


def test_the_cycle_stores_what_the_next_prime_needs():
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_render_app_chrome")
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_chrome_last" in literals
    for field in ("spot", "prev_close", "v5", "v6", "market", "updated"):
        assert field in literals, field


def test_nothing_is_primed_on_the_first_run():
    """One blank cycle at startup is unavoidable — there is nothing to prime
    from — and is not what was reported."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_prime_app_chrome")
    assert any(isinstance(n, ast.Return) for n in ast.walk(fn)), (
        "it must bail out when there is no stored state")


def test_the_footer_renders_into_a_slot_when_given_one():
    drawn = []

    class Slot:
        def markdown(self, html, **kw): drawn.append(("slot", html))

    class Page:
        def markdown(self, html, **kw): drawn.append(("page", html))

    C.render_footer(Page(), Slot(), updated="15:22")
    C.render_footer(Page(), None, updated="15:22")
    assert [w for w, _ in drawn] == ["slot", "page"]


# ══════════════════════════════════════════════════════════════════════
#  the second row
# ══════════════════════════════════════════════════════════════════════

_EXTRAS = ["🛡 24,558 brk 44 · rej 56", "🧱 24,608 brk 49 · rej 51",
           "⚔️ ₹24,561 · Sellers · bounce 35 · breakdown 65",
           "⚡ C46 P41 · spk C65 P61"]


def test_the_extras_row_carries_every_reading_it_was_given():
    html = C.header_html(24650.3, 24580.0, extras=_EXTRAS)
    for probe in ("24,558", "rej 56", "24,608", "24,561", "Sellers",
                  "breakdown 65", "C46 P41", "spk C65 P61"):
        assert probe in html, probe


def test_no_extras_draws_no_row():
    """The strip is frozen at the top, so a row it grows costs that space on
    every screen for the session. An empty one earns nothing."""
    assert "flex-basis" not in C.header_html(24650.3, 24580.0)
    assert "flex-basis" not in C.header_html(24650.3, 24580.0, extras=[])


def test_a_blank_reading_is_dropped_rather_than_drawn_hollow():
    assert "flex-basis" not in C.header_html(
        24650.3, 24580.0, extras=["", "  ", None, "UNKNOWN"])


def test_the_extras_are_escaped():
    html = C.header_html(24650.3, 24580.0, extras=["<script>x</script>"])
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_readings_are_worded_by_the_panels_that_own_them():
    """The header collects; it does not phrase. Otherwise the strip and the
    panel further down the page can describe one fact two ways."""
    from mios_v5.ui.premium_energy_panel import micro as pe_micro
    from mios_v5.ui.war_zone import micro as wz_micro
    from mios_v5.ui.zone_card import zone_micro

    assert zone_micro({"side": "SUPPORT", "price": 24558,
                       "probabilities": {"break": 44, "rejection": 56}}) \
        == "🛡 24,558 brk 44 · rej 56"
    assert wz_micro({"battle_zone": {"type": "SUPPORT", "price": 24561},
                     "expected_winner": "Contested"}) \
        == "⚔️ ₹24,561 · Contested"
    assert pe_micro({"ready": True, "call": {"energy": 46, "spike": 65},
                     "put": {"energy": 41, "spike": 61}}) \
        == "⚡ C46 P41 · spk C65 P61"


def test_both_odds_travel_on_the_level_chip():
    """`brk 44 · rej 56` are complements, and printing one is the edit that
    lets a reader supply the other from a wrong prior."""
    from mios_v5.ui.zone_card import zone_micro
    line = zone_micro({"side": "SUPPORT", "price": 24558,
                       "probabilities": {"break": 44, "rejection": 56}})
    assert "brk 44" in line and "rej 56" in line


def test_both_energy_rows_survive_the_shortest_form():
    """Participation and expansion routinely point opposite ways, so the
    second one is not the thing to cut when space runs out."""
    from mios_v5.ui.premium_energy_panel import micro
    line = micro({"ready": True, "call": {"energy": 46, "spike": 65},
                  "put": {"energy": 41, "spike": 61}})
    assert "C46 P41" in line and "C65 P61" in line


def test_a_source_that_reported_nothing_contributes_nothing():
    from mios_v5.ui.premium_energy_panel import micro as pe_micro
    from mios_v5.ui.pin_chip import micro as pin_micro
    from mios_v5.ui.war_zone import micro as wz_micro
    from mios_v5.ui.zone_card import zone_micro
    assert zone_micro(None) == "" and zone_micro({"side": "SUPPORT"}) == ""
    assert wz_micro({}) == "" and wz_micro(None) == ""
    assert pe_micro({"ready": False}) == "" and pe_micro(None) == ""
    assert pin_micro(None) == "" and pin_micro({}) == ""


# ══════════════════════════════════════════════════════════════════════
#  🧲 the PIN veto on the strip
# ══════════════════════════════════════════════════════════════════════

_PINNED_GATE = {
    "state": "PINNED", "level": 24600.0,
    "why": ["pinned at ₹24600 — heaviest CE+PE at one strike — magnet/pin; "
            "no directional edge, WAIT"],
}


def test_the_pin_chip_carries_the_strike_the_cause_and_the_verdict():
    """All three, because each answers a different question: WHERE the magnet
    is, WHY it is one, and what to do about it."""
    from mios_v5.ui.pin_chip import micro
    line = micro(_PINNED_GATE)
    assert line == ("🧲 pinned at ₹24600 — heaviest CE+PE at one strike — "
                    "magnet/pin; no directional edge, WAIT")


def test_the_sentence_is_the_owners_taken_verbatim():
    """⚠️ The point of the whole module. `compute_market_picture` decides what a
    pin is and words it; this adds a glyph. Re-phrasing here would let the strip
    and the Market Picture panel describe one strike two ways."""
    from mios_v5.ui.pin_chip import GLYPH, micro
    own = "pinned at ₹24600 — some future wording nobody has written yet"
    assert micro({"state": "PINNED", "why": [own]}) == f"{GLYPH} {own}"


def test_a_gate_that_is_not_pinned_draws_no_chip():
    """The normal case. The strip is frozen on every screen for the session, so
    a chip reporting "not pinned" would cost that space permanently."""
    from mios_v5.ui.pin_chip import micro
    for state in ("CALL", "PUT", "WAIT", "", None):
        assert micro({"state": state, "why": ["something"]}) == ""


def test_a_pin_with_no_reason_still_reports_the_veto():
    """PINNED is a veto on every directional read. Saying nothing because the
    `why` list came back empty would leave the S/R odds beside it looking like a
    live contest."""
    from mios_v5.ui.pin_chip import micro
    assert micro({"state": "PINNED", "level": 24600.0, "why": []}) == (
        "🧲 pinned at ₹24600 — no directional edge, WAIT")
    assert "WAIT" in micro({"state": "PINNED"})


def test_a_frozen_mapping_is_still_a_gate():
    """⚠️ `isinstance(x, dict)` is False for a `MappingProxyType`, and this repo
    has shipped that confusion three times — `execution_panel._get`, the panel
    metadata block, and `_mios_market_read`'s per-side behaviour."""
    from types import MappingProxyType

    from mios_v5.ui.pin_chip import micro
    assert micro(MappingProxyType(dict(_PINNED_GATE))).startswith("🧲")


def test_the_pin_chip_never_raises_on_junk():
    from mios_v5.ui.pin_chip import micro
    for junk in (None, {}, [], "PINNED", 7, {"state": "PINNED", "why": None},
                 {"state": "PINNED", "level": "not a number", "why": ()}):
        micro(junk)


def _extras_fn():
    """`_chrome_extras` as a parse tree.

    Parsed rather than grepped because the function is heavily commented and its
    own docstring names `war_zone.micro` — a text search finds the prose, not the
    code, and would pass or fail on a comment edit.
    """
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                and n.name == "_chrome_extras")


def test_the_veto_is_drawn_before_the_chips_it_contradicts():
    """Order is the product here. The S/R odds and the war-zone winner both
    describe a directional contest; read without the veto beside them they
    invite a trade the gate has already refused."""
    order = [n.module for n in ast.walk(_extras_fn())
             if isinstance(n, ast.ImportFrom) and n.module]
    pin = next(i for i, m in enumerate(order) if "pin_chip" in m)
    for other in ("zone_card", "war_zone", "premium_energy_panel"):
        idx = next(i for i, m in enumerate(order) if other in m)
        assert pin < idx, f"the pin veto must be collected before {other}"


def test_the_header_reads_the_decided_state_rather_than_the_raw_walls():
    """`oi_pin` is the detection and `entry_gate['state']` is the decision. The
    strip must read the decision — re-deriving "is this pinned?" from the walls
    would be a second implementation of the gate's proximity rule."""
    fn = _extras_fn()
    literals = {n.value for n in ast.walk(fn)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    idents = {getattr(n, "id", "") or getattr(n, "attr", "")
              for n in ast.walk(fn)}
    assert "entry_gate" in literals, \
        "the header should read the gate's decided state"
    assert "oi_pin" not in literals | idents, \
        "the header should not touch the raw pin detection"


def test_the_extras_are_collected_not_phrased_by_the_app():
    """`_chrome_extras` calls each owner's `micro`; it builds no strings of its
    own beyond joining them."""
    tree = ast.parse((ROOT / "vob_minimal.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_chrome_extras")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert {"zone_micro"} <= called
    assert any("micro" in c for c in called)
    # no f-string assembling a reading here
    assert not [n for n in ast.walk(fn) if isinstance(n, ast.JoinedStr)]


def test_the_extras_survive_the_priming_render():
    """Primed from `_chrome_last`, so the second row does not blink out on
    every refresh either."""
    src = (ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    for name in ("_render_app_chrome", "_prime_app_chrome"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == name)
        literals = {n.value for n in ast.walk(fn)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "extras" in literals, name


# ══════════════════════════════════════════════════════════════════════
#  the Guardian's idle line
# ══════════════════════════════════════════════════════════════════════

def test_the_idle_guardian_line_is_not_a_muted_caption():
    """🛡 The one line that says the Guardian exists and is watching.

    ⚠️ It was an `st.caption`, which Streamlit ALWAYS renders in muted grey — so
    the standing-watch message read as disabled chrome next to the Guardian's
    other states, which each carry their own colour. A pink FILL with white
    letters, in the padded/rounded shape those states use, and asserted on the
    source so it cannot quietly go back to a caption.
    """
    src = (ROOT / "vob_minimal.py").read_text()
    i = src.index("🛡 Position Guardian — idle")
    call_start = src.rindex("st.", 0, i)
    block = src[call_start:src.index("EXIT FAST.", i)]
    assert block.startswith("st.markdown("), block[:40]
    assert "background:#ff2d95" in block, "the idle line lost its pink fill"
    assert "color:#ffffff" in block, "the letters must be bright white"
    assert "st.caption" not in block
    # a fill needs padding or the text sits flush against the colour edge
    assert "padding:" in block and "border-radius:" in block
