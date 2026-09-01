"""📍 The spot strip — the one number with its own clock.

Two things are being pinned here. The strip's own behaviour (never draw a
confident zero, always show the age, never colour a fall green), and the wiring
in `vob_minimal.py` that gives it a clock — because a fragment that is defined
and never decorated is exactly the failure mode that shipped a whole Adaptive
Greeks layer rendering nothing.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from mios_v5.ui import spot_ticker as t


def _read(price=24610.5, source="live LTP", age=3.0, stale=False):
    return {"price": price, "source": source, "age_s": age, "stale": stale,
            "candidates": {}}


# ══════════════════════════════════════════════════════════════════════
#  the price
# ══════════════════════════════════════════════════════════════════════

def test_the_price_is_drawn_with_paise():
    """Two decimals on purpose. The strip ticks every 10 seconds and NIFTY moves
    in fractions of a point over that span — rounded to rupees it would look
    frozen, which is the impression this whole change exists to fix."""
    assert "₹24,610.50" in t.spot_strip_html(_read())


@pytest.mark.parametrize("price", [None, 0, 0.0, -1, "", "abc", float("nan"),
                                   True, False])
def test_no_price_draws_nothing_at_all(price):
    """⚠️ Not a ₹0 row. A strip that draws a confident zero at the top of the
    page is how a trader reads the floor as the market."""
    assert t.spot_strip_html(_read(price=price)) == ""


def test_a_missing_read_draws_nothing():
    for bad in (None, {}, "nope", 7, []):
        assert t.spot_strip_html(bad) == ""


# ══════════════════════════════════════════════════════════════════════
#  the change
# ══════════════════════════════════════════════════════════════════════

def test_a_rise_is_green_and_a_fall_is_red():
    from mios_v5.ui.theme import BEAR, BULL

    up = t.spot_strip_html(_read(price=24700.0), prev_close=24600.0)
    assert "+100.00" in up and "+0.41%" in up and BULL in up

    down = t.spot_strip_html(_read(price=24500.0), prev_close=24600.0)
    assert "-100.00" in down and "-0.41%" in down and BEAR in down


def test_the_change_is_omitted_when_there_is_nothing_to_compare_to():
    """`_gap_today` has not published yet on the first cycle of a day. A `+0.00`
    against a missing close would be a fabricated flat open."""
    for pc in (None, 0, 0.0, -5, "", "abc", float("nan")):
        html = t.spot_strip_html(_read(), prev_close=pc)
        assert html and "%" not in html, f"prev_close={pc!r} produced a change"


def test_the_change_is_arithmetic_on_the_two_numbers_given():
    html = t.spot_strip_html(_read(price=24000.0), prev_close=24000.0)
    assert "+0.00" in html and "(+0.00%)" in html


# ══════════════════════════════════════════════════════════════════════
#  the age — the part that must never be silent
# ══════════════════════════════════════════════════════════════════════

def test_a_fresh_live_quote_reads_live_and_green():
    html = t.spot_strip_html(_read(age=3.0))
    assert "🟢" in html and "live" in html and "3s ago" in html


def test_an_aged_quote_is_flagged_even_when_the_read_calls_itself_fresh():
    """The strip has its own bound. `spot.read` marks `stale` only once the LTP
    loses to the chain at 45s; a price 30 seconds old under a 10-second clock is
    already something the trader needs to see."""
    html = t.spot_strip_html(_read(age=30.0, stale=False))
    assert "🔴" in html and "30s ago" in html


def test_a_cold_quote_stops_calling_itself_live():
    """⚠️ Caught on a real render: `🔴 live · 30s ago` asked the trader to believe
    both halves of a contradiction. Once the strip has decided a quote is cold,
    the word has to change too, not just the colour."""
    html = t.spot_strip_html(_read(age=30.0, stale=False))
    assert "last tick" in html
    assert ">🔴 live" not in html and "🔴 live ·" not in html


def test_the_stale_flag_alone_is_enough_to_warn():
    from mios_v5.ui.theme import WARN

    html = t.spot_strip_html(_read(source="option chain", age=None, stale=True))
    assert WARN in html and "from chain" in html
    assert "🟢" not in html


@pytest.mark.parametrize("source,age,stale,dot", [
    ("live LTP", 3.0, False, "🟢"),           # live and fresh
    ("live LTP", 30.0, False, "🔴"),          # live endpoint, gone quiet
    ("option chain", None, False, "🟡"),      # real quote, age unknowable
    ("option chain", 300.0, True, "🟡"),      # ditto, with a cold LTP behind it
    ("live LTP (stale)", 300.0, True, "🔴"),  # nothing better exists
    ("last candle close", None, True, "🔴"),  # yesterday, effectively
])
def test_the_three_freshness_states(source, age, stale, dot):
    """Three states, not two. The chain is a real quote whose age the strip
    cannot know — green would claim a freshness it cannot show, and red would
    cry wolf about a price that was just fetched by the chain."""
    assert dot in t.spot_strip_html(_read(source=source, age=age, stale=stale))


def test_only_a_live_fresh_quote_is_green():
    for source, age, stale in (("option chain", None, False),
                               ("live LTP", 99.0, False),
                               ("live LTP (stale)", 300.0, True),
                               ("last candle close", None, True)):
        html = t.spot_strip_html(_read(source=source, age=age, stale=stale))
        assert "🟢" not in html, f"{source} @ {age}s drew a live dot"


def test_the_strip_and_the_micro_line_never_disagree():
    """⚠️ Caught on a real render: the strip drew a green live dot on a chain
    price while `micro` warned about the same read. One `_status` decides now, so
    a green strip and a warning line cannot both appear for one cycle."""
    for source, age, stale in (("live LTP", 3.0, False),
                               ("live LTP", 30.0, False),
                               ("option chain", None, False),
                               ("option chain", 300.0, True),
                               ("live LTP (stale)", 300.0, True),
                               ("last candle close", None, True)):
        r = _read(source=source, age=age, stale=stale)
        green = "🟢" in t.spot_strip_html(r)
        warned = bool(t.micro(r))
        assert green is not warned, (
            f"{source} @ {age}s: strip green={green} but micro warned={warned}")


@pytest.mark.parametrize("age,text", [
    (0.0, "0s ago"), (9.4, "9s ago"), (59.0, "59s ago"),
    (60.0, "1m 00s ago"), (72.0, "1m 12s ago"), (605.0, "10m 05s ago"),
])
def test_the_age_is_readable_at_every_scale(age, text):
    assert text in t.spot_strip_html(_read(age=age, stale=True))


def test_a_missing_age_omits_the_clock_rather_than_inventing_one():
    html = t.spot_strip_html(_read(age=None))
    assert html and "ago" not in html


def test_every_source_gets_a_word_a_trader_can_read():
    """`spot.read` emits exactly these four. A source with no label would print
    the raw internal string, or worse, an em dash where the provenance was."""
    from mios_v5 import spot

    sources = set()
    for node in ast.walk(ast.parse(pathlib.Path(spot.__file__).read_text())):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "LTP" in node.value or "chain" in node.value or "candle" in node.value:
                sources.add(node.value)
    emitted = {s for s in sources if s in ("live LTP", "option chain",
                                           "live LTP (stale)",
                                           "last candle close")}
    assert emitted, "the source strings moved — this test can no longer see them"
    assert emitted <= set(t.SOURCE_LABEL), (
        f"unlabelled source(s): {emitted - set(t.SOURCE_LABEL)}")


def test_the_cadence_mismatch_is_stated_on_the_strip():
    """⚠️ The strip is 10s fresh and the panels below it are one page cycle
    behind. That is a real limitation of doing this cheaply, and the strip says
    so where it is visible rather than only in a commit message."""
    html = t.spot_strip_html(_read())
    assert "10s" in html and "20s" in html


# ══════════════════════════════════════════════════════════════════════
#  the micro form
# ══════════════════════════════════════════════════════════════════════

def test_the_micro_form_is_silent_when_the_price_is_live():
    """The header already carries spot. Repeating it would spend permanently
    frozen screen space telling the trader what they can already see."""
    assert t.micro(_read()) == ""


def test_the_micro_form_speaks_up_when_the_price_is_not_live():
    assert "from chain" in t.micro(_read(source="option chain", stale=True))
    assert "last tick" in t.micro(_read(source="live LTP (stale)", age=90.0,
                                        stale=True))
    assert "1m 30s ago" in t.micro(_read(source="live LTP (stale)", age=90.0,
                                         stale=True))


def test_the_micro_form_says_nothing_without_a_price():
    assert t.micro(_read(price=None)) == ""
    assert t.micro(None) == ""


# ══════════════════════════════════════════════════════════════════════
#  purity, so this stays screenshot-testable
# ══════════════════════════════════════════════════════════════════════

def test_the_strip_module_imports_no_streamlit_and_no_session_state():
    src = pathlib.Path(t.__file__).read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal"}
    assert "session_state" not in src


def test_html_is_escaped_where_it_takes_a_string():
    """`source` reaches the strip from a dict. It is app-internal today, but a
    label is the kind of thing that later gets fed from a config."""
    html = t.spot_strip_html(_read(source="<script>x</script>"))
    assert "<script>" not in html or "&lt;script&gt;" in html


# ══════════════════════════════════════════════════════════════════════
#  the wiring — a fragment nobody calls refreshes nothing
# ══════════════════════════════════════════════════════════════════════

# ⚠️ Parsed, never imported. `vob_minimal.py` boots Streamlit and reads secrets
# at module scope, so importing it in a unit test fails on the machine and, worse,
# would make these guards silently skip on the machine where it happens to work.
_VOB = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
_SRC = _VOB.read_text(encoding="utf-8")


def _func(name):
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not defined in vob_minimal.py")


def _body_src(name):
    """The function's own source — comments included, which is why every
    assertion on it is made against the AST rather than this text."""
    return ast.get_source_segment(_SRC, _func(name)) or ""


def test_main_actually_calls_the_ticker():
    """⚠️ The one that matters. A whole layer shipped defined-and-never-called
    once already this session and rendered nothing on four surfaces; the only
    guard against a repeat is asserting the call, on the AST so a comment
    mentioning the name cannot satisfy it."""
    called = {n.func.id for n in ast.walk(_func("main"))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_spot_ticker" in called


def test_the_ticker_is_drawn_before_the_analyzer():
    """Spot is the first number read, and `_render_main_analyzer` takes seconds
    to build. Below it the strip would appear last on every rerun."""
    body = _func("main").body

    def _at(name):
        hits = [i for i, node in enumerate(body) for n in ast.walk(node)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == name]
        assert hits, f"{name} is never called in main()"
        return min(hits)

    assert _at("_spot_ticker") < _at("_render_main_analyzer")


def test_the_ticker_asks_for_a_ten_second_clock():
    """The cadence is a named constant so the strip's own prose, the tests and
    the fragment cannot drift to three different numbers."""
    tree = ast.parse(_SRC)
    const = {t.id: n.value.value
             for n in ast.walk(tree) if isinstance(n, ast.Assign)
             for t in n.targets
             if isinstance(t, ast.Name) and isinstance(n.value, ast.Constant)}
    assert const.get("SPOT_REFRESH") == "10s"

    kwargs = {kw.arg: kw.value for n in ast.walk(_func("_spot_ticker"))
              if isinstance(n, ast.Call) for kw in n.keywords}
    assert "run_every" in kwargs, "the fragment is never given a cadence"
    assert isinstance(kwargs["run_every"], ast.Name), (
        "the cadence must come from SPOT_REFRESH, not a hardcoded literal")
    assert kwargs["run_every"].id == "SPOT_REFRESH"


def test_the_ticker_does_not_tick_when_the_market_is_closed():
    """Polling Dhan every 10 seconds overnight buys a number that has not moved
    since 15:30."""
    names = {n.id for n in ast.walk(_func("_spot_ticker"))
             if isinstance(n, ast.Name)}
    assert "_is_market_open" in names


def test_the_ticker_falls_back_rather_than_leaving_the_strip_blank():
    """Three ways there may be no clock — old Streamlit, closed market, a raising
    fragment — and all three must still draw the price once. A missing clock is a
    downgrade; a missing price is a bug."""
    fn = _func("_spot_ticker")
    branches = [n for n in ast.walk(fn) if isinstance(n, (ast.If, ast.Try))]
    assert len(branches) >= 2, "the guards are gone"
    # Counted as references, not calls: the fragment path hands `_draw` over to
    # be called by Streamlit, so it is a Load and not a Call like the other two.
    reached = [n for n in ast.walk(fn) if isinstance(n, ast.Name)
               and n.id == "_draw" and isinstance(n.ctx, ast.Load)]
    assert len(reached) >= 3, (
        f"only {len(reached)} path(s) reach the draw — one leaves the strip blank")


def test_the_ticker_never_writes_to_supabase():
    """⚠️ `_render_main_analyzer` still owns `upsert_spot_data` on the 20s cycle.
    Persisting here would double the spot writes — against the whole point of
    the egress work — to buy a row nobody reads twice."""
    for name in ("_spot_ticker", "_spot_ticker_body"):
        fn = _func(name)
        attrs = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
        assert not attrs & {"upsert_spot_data", "insert", "upsert", "table",
                            "execute"}, f"{name} reaches for a database call"
        bases = {n.value.id for n in ast.walk(fn)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)}
        assert "db" not in bases, f"{name} touches the db client"


def test_the_ticker_makes_exactly_one_dhan_call():
    """The cadence is only affordable because the read is one `marketfeed/ltp`
    quote. A chain fetch in here would make the strip cost more than the page."""
    calls = [n.func.id for n in ast.walk(_func("_spot_ticker_body"))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert calls.count("get_index_spot_ltp") == 1
    assert "analyze_option_chain" not in calls
    assert "get_dhan_option_chain" not in calls


def test_the_ticker_publishes_the_live_spot_for_every_other_panel():
    """The refresh is only worth doing if the panels inherit it. They all read
    through `mios_v5.spot`, which reads `_nifty_spot_live` — so writing that key
    is what makes the next page rerun agree with the strip."""
    written = set()
    for node in ast.walk(_func("_spot_ticker_body")):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Subscript) and isinstance(
                        tgt.slice, ast.Constant):
                    written.add(tgt.slice.value)
    assert {"_nifty_spot_live", "_nifty_spot_live_ts"} <= written


def test_the_ticker_reads_spot_through_the_one_owner():
    """Not `option_data['underlying']`, and not the raw key either. The strip
    and the panels must be answering the same question the same way."""
    imported = {a.name for n in ast.walk(_func("_spot_ticker_body"))
                if isinstance(n, ast.ImportFrom) and n.module == "mios_v5.spot"
                for a in n.names}
    assert "read" in imported
