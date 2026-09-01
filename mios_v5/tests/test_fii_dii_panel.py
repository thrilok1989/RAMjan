"""🏛 FII / DII institutional flows on the NIFTY dashboard.

## The bug this started from

`_fii_dii_cash` has been fetched every cycle and published to session state
since Stage 23 was written. The ONE display site read `fd.get("fii_net")` — which
is `stage23_flows`' *output* key, not the raw NSE payload's shape — so the lookup
always missed and the row showed a dash. Fetched, published, drawn nowhere.

## What these tests protect

1. **Both sides, always.** `FII −4,200` alone is a rout or a non-event depending
   entirely on what DII did against it.
2. **EOD is stated on the card.** Every other block on this dashboard is live, so
   a ₹-crore figure among them reads as current unless the card says otherwise.
3. **The verdict is Stage 23's.** The thresholds, the bias and the
   absorption-battle test live in the engine. A second answer in the display
   layer would drift the first time either moved.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5.ui import fii_dii_panel as F

_CASH = {"FII": {"date": "08-Aug-2026", "buy": 12480.5, "sell": 16702.3,
                 "net": -4221.8},
         "DII": {"date": "08-Aug-2026", "buy": 15310.2, "sell": 11290.6,
                 "net": 4019.6}}

_DERIV = {"date": "08-Aug-2026", "fut_index_long": 82450.0,
          "fut_index_short": 141200.0, "fut_index_net": -58750.0,
          "opt_index_call_long": 210300.0, "opt_index_put_long": 168900.0,
          "opt_index_call_short": 189400.0, "opt_index_put_short": 233100.0}


# ══════════════════════════════════════════════════════════════════════
#  the numbers
# ══════════════════════════════════════════════════════════════════════

def test_both_sides_are_shown():
    """⚠️ The whole point of showing DII. A reader who sees FII −4,222 without
    DII +4,020 absorbing it reads a one-sided rout."""
    html = F.fii_dii_html(_CASH)
    assert "FII cash" in html and "DII cash" in html
    assert "-4,222" in html and "+4,020" in html


def test_the_net_is_signed_in_both_directions():
    """An institutional net of 1,240 and −1,240 are opposite facts. Unsigned
    leaves the reader to infer it from a colour."""
    html = F.fii_dii_html(_CASH)
    assert "+4,020" in html, "a positive net must carry its plus"
    assert "-4,222" in html


def test_a_buy_and_a_sell_are_shown_beside_the_net():
    """Whole ₹crore, the unit NSE reports in. The gross pair matters as well as
    the net: −200cr on 12,000cr turnover and −200cr on 400cr are the same net
    from very different sessions."""
    html = F.fii_dii_html(_CASH)
    assert "buy 12,480" in html and "sell 16,702" in html
    assert "buy 15,310" in html and "sell 11,291" in html


def test_the_combined_net_is_the_two_added():
    r = F.read(_CASH)
    assert round(r["combined"], 1) == round(-4221.8 + 4019.6, 1)
    assert r["combined_complete"] is True
    assert "Combined" in F.fii_dii_html(_CASH)


def test_a_rise_is_green_and_a_fall_is_red():
    from mios_v5.ui.theme import BEAR, BULL
    html = F.fii_dii_html(_CASH)
    assert BULL in html and BEAR in html


def test_the_published_net_is_used_not_a_recomputed_one():
    """⚠️ `buy − sell` is computed only to CHECK the feed. NSE's published net is
    what a trader will compare against every other source, so the panel shows
    that number."""
    cash = {"FII": {"buy": 100.0, "sell": 40.0, "net": 55.0}}
    r = F.read(cash)
    assert r["sides"]["FII"]["net"] == 55.0
    assert r["sides"]["FII"]["derived"] == 60.0
    assert "+55" in F.fii_dii_html(cash)


def test_a_net_that_disagrees_with_buy_minus_sell_is_flagged():
    """A mismatch means the payload changed shape or a field arrived empty.
    Silently trusting one of three inconsistent numbers is how a wrong ₹-crore
    figure ends up on screen looking authoritative."""
    cash = {"FII": {"buy": 100.0, "sell": 40.0, "net": 55.0}}
    r = F.read(cash)
    assert r["sides"]["FII"]["mismatch"] is True
    assert any("does not match" in n for n in r["notes"])
    assert "does not match" in F.fii_dii_html(cash)


def test_a_consistent_payload_is_not_flagged():
    r = F.read(_CASH)
    assert not any(r["sides"][s]["mismatch"] for s in F.SIDES)
    assert not any("does not match" in n for n in r["notes"])


# ══════════════════════════════════════════════════════════════════════
#  EOD — the part that must never be silent
# ══════════════════════════════════════════════════════════════════════

def test_the_card_says_end_of_day_on_its_own_face():
    """⚠️ Every other block on this dashboard is live. NSE publishes these once
    daily around 18:30 IST, so during trading hours every figure here describes
    YESTERDAY — and a ₹-crore number among ticking panels reads as current."""
    html = F.fii_dii_html(_CASH)
    assert "END-OF-DAY" in html
    assert "not an intraday trigger" in html


def test_the_publication_date_is_shown():
    assert "08-Aug-2026" in F.fii_dii_html(_CASH)


def test_a_missing_date_says_so_rather_than_implying_today():
    html = F.fii_dii_html({"FII": {"buy": 1.0, "sell": 2.0, "net": -1.0}})
    assert "date not published" in html
    assert "END-OF-DAY" in html, "the warning is never conditional"


def test_the_derivatives_date_is_shown_when_it_differs():
    """The two feeds are separate archives and can be a day apart."""
    html = F.fii_dii_html(_CASH, dict(_DERIV, date="07-Aug-2026"))
    assert "07-Aug-2026" in html and "08-Aug-2026" in html


def test_the_short_form_also_marks_it_eod():
    assert "(EOD)" in F.micro(_CASH)


# ══════════════════════════════════════════════════════════════════════
#  the derivatives block
# ══════════════════════════════════════════════════════════════════════

def test_index_futures_show_net_with_the_two_legs():
    html = F.fii_dii_html(_CASH, _DERIV)
    assert "FII index futures" in html
    assert "-58,750" in html
    assert "L 82,450" in html and "S 141,200" in html


def test_index_options_are_netted_per_side():
    """Four raw contract counts are four numbers nobody reads. Netted per side
    they answer one question: which way are FIIs positioned in index options?"""
    html = F.fii_dii_html(_CASH, _DERIV)
    assert "FII index options" in html
    assert "CE +20,900" in html          # 210,300 − 189,400
    assert "PE -64,200" in html          # 168,900 − 233,100


def test_a_partial_options_payload_draws_no_options_row():
    """Netting three of four counts would print a confident wrong number."""
    html = F.fii_dii_html(_CASH, dict(_DERIV, opt_index_put_short=None))
    assert "FII index options" not in html
    assert "FII index futures" in html, "the futures row is independent"


def test_no_derivatives_at_all_still_draws_the_cash_block():
    """The participant-wise OI archive fails from cloud hosts more often than the
    cash endpoint. Losing it must not cost the cash figures too."""
    html = F.fii_dii_html(_CASH, None)
    assert "FII cash" in html and "FII index futures" not in html


# ══════════════════════════════════════════════════════════════════════
#  the verdict is read, never re-derived
# ══════════════════════════════════════════════════════════════════════

def test_the_engines_bias_and_confidence_are_echoed():
    html = F.fii_dii_html(_CASH, _DERIV, "BEAR", 38.5)
    assert "STAGE 23 FLOWS" in html and "BEAR" in html and "38/100" in html


def test_no_verdict_handed_in_means_no_verdict_row():
    """The flows are a fact worth seeing on their own. Inventing a lean to fill
    the row is the one thing this file must not do."""
    html = F.fii_dii_html(_CASH, _DERIV)
    assert "STAGE 23" not in html
    assert "FII cash" in html


@pytest.mark.parametrize("word", ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR",
                                  "STRONG_BEAR"])
def test_every_bias_the_engine_can_emit_is_worded(word):
    assert word in F.BIAS_TONE and word in F.BIAS_EMOJI
    assert word.replace("_", " ") in F.fii_dii_html(_CASH, None, word, 50)


def test_the_absorption_battle_is_called_out():
    """⚠️ The single most important thing this block can say. When FII and DII
    pull opposite ways the net is NOT a directional edge — Stage 23 damps its own
    conviction for exactly this — and a reader seeing only FII reads a rout."""
    html = F.fii_dii_html(_CASH, _DERIV, "BEAR", 38.5, conflict=True)
    assert "absorption battle" in html
    assert "not a clean directional edge" in html
    assert "absorption battle" not in F.fii_dii_html(_CASH, _DERIV, "BEAR", 38.5)


def test_the_engines_sentence_is_quoted_not_rephrased():
    line = "FII -4,222cr · DII +4,020cr · net -202cr (as of 08-Aug-2026, EOD)"
    assert line in F.fii_dii_html(_CASH, _DERIV, "BEAR", 38.5,
                                  evidence=[line]).replace("&#x27;", "'")


def test_the_module_owns_no_thresholds():
    """⚠️ `stage23_flows` owns `_STRONG = 2500` and `_MILD = 800`. Deciding "is
    ₹2,500cr a lot?" a second time here would put two answers to one question on
    the same screen, and they would drift the first time either moved.

    The one number allowed is `STALE_DAYS`, which is a feed-health bound rather
    than a market judgement.
    """
    src = pathlib.Path(F.__file__).read_text()
    tree = ast.parse(src)
    nums = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
            and not isinstance(n.value, bool) and abs(n.value) >= 100}
    assert not nums, f"a ₹-crore-scale threshold appeared here: {nums}"

    from mios_v5.engines import stage23_flows as S
    assert (S._STRONG, S._MILD) == (2500.0, 800.0), "the owner moved"


# ══════════════════════════════════════════════════════════════════════
#  three states, and junk
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cash", [None, {}, "nope", 7, [], {"FII": None},
                                  {"FII": {}}, {"FII": {"net": None}}])
def test_nothing_published_draws_nothing(cash):
    """Not a row of zeroes. ₹0 Cr of FII flow is a real and very different claim
    from "NSE has not published yet"."""
    assert F.fii_dii_html(cash) == ""
    assert F.micro(cash) == ""


def test_one_side_published_shows_that_side_and_names_the_other():
    """NSE occasionally publishes one category before the other."""
    html = F.fii_dii_html({"FII": {"date": "08-Aug-2026", "buy": 100.0,
                                   "sell": 200.0, "net": -100.0}})
    assert "FII cash" in html
    assert "not published" in html
    assert "Combined" not in html, (
        "a combined figure that is really just FII reads as agreement between "
        "two parties when one has not reported")


def test_the_combined_row_needs_both_sides():
    r = F.read({"FII": {"net": -100.0}})
    assert r["combined_complete"] is False


@pytest.mark.parametrize("junk", ["", "  ", "abc", None, [], {},
                                  float("nan")])
def test_junk_values_fall_through_without_crashing(junk):
    cash = {"FII": {"buy": junk, "sell": junk, "net": junk},
            "DII": {"buy": junk, "sell": junk, "net": junk}}
    assert F.fii_dii_html(cash, {"fut_index_net": junk}) == ""


def test_a_zero_net_is_a_real_reading_and_is_shown():
    """⚠️ Distinct from the case above. A genuine 0 published by NSE means the
    two sides were level — that IS information, unlike a missing field."""
    html = F.fii_dii_html({"FII": {"date": "08-Aug-2026", "buy": 500.0,
                                   "sell": 500.0, "net": 0.0}})
    assert html and "FII cash" in html and "+0" in html


def test_a_hostile_payload_does_not_crash():
    for bad in (object(), (1, 2), {"FII": [1, 2]}, {"FII": "x"}):
        F.fii_dii_html(bad)
        F.micro(bad)


def test_read_always_reports_the_same_shape():
    keys = {"sides", "combined", "combined_complete", "as_of", "deriv",
            "reporting", "notes"}
    for cash in (None, {}, _CASH, {"FII": {"net": 1.0}}):
        assert set(F.read(cash)) == keys


# ══════════════════════════════════════════════════════════════════════
#  purity and wiring
# ══════════════════════════════════════════════════════════════════════

def test_the_panel_is_pure():
    src = pathlib.Path(F.__file__).read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "requests"}
    assert "session_state" not in src


def test_the_html_is_escaped():
    html = F.fii_dii_html({"FII": {"date": "<script>x</script>", "buy": 1.0,
                                   "sell": 2.0, "net": -1.0}})
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_the_cockpit_renders_the_block():
    """⚠️ The guard that matters — this data was fetched and published for months
    and drawn by nothing. Asserted through `cockpit_blocks`, the entry point the
    dashboard actually calls."""
    from mios_v5.ui import nifty_cockpit as NC
    blocks = NC.cockpit_blocks({"spot": 24583.8, "fii_dii_cash": _CASH,
                               "fii_deriv": _DERIV, "flows_bias": "BEAR",
                                "flows_confidence": 38.5,
                                "flows_conflict": True})
    assert "fii_dii" in blocks
    assert "FII cash" in blocks["fii_dii"] and "DII cash" in blocks["fii_dii"]
    assert "fii_dii" in NC.BLOCK_ORDER


def test_the_collector_passes_both_feeds_and_the_engine_verdict():
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_nifty_cockpit")
    body = ast.get_source_segment(src, fn) or ""
    for key in ("_fii_dii_cash", "_fii_deriv_stats", "fii_dii_cash",
                "fii_deriv", "_flows_read"):
        assert key in body, key


def test_the_dashboard_no_longer_reads_the_wrong_key():
    """⚠️ The original bug. `fii_net` is `stage23_flows`' OUTPUT key; the raw
    session payload is `{"FII": {...}, "DII": {...}}`. Reading the former off the
    latter always missed, so the row was a permanent dash."""
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_external_rows")
    strings = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "fii_net" not in strings


def test_the_external_row_names_both_sides():
    """It said "FII cash" while showing nothing. Now it names both, because one
    number invites the one-sided reading."""
    root = pathlib.Path(__file__).resolve().parents[2]
    src = (root / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_external_rows")
    strings = {n.value for n in ast.walk(fn)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert any("FII" in s and "DII" in s for s in strings)


def test_the_flows_read_survives_a_missing_engine():
    """Stage 23 returns NEUTRAL when NSE has not published. The reader must cope
    with the engine result being absent entirely — a replay, or a failed pass."""
    from mios_v5.ui.dashboard_v6 import _flows_read
    for state in ({}, {"_mios_state": None}, {"_mios_state": {}},
                  {"_mios_state": "junk"}):
        assert _flows_read(state) == {}


# ══════════════════════════════════════════════════════════════════════
#  found by rendering, not by a fixture
# ══════════════════════════════════════════════════════════════════════

def test_the_futures_net_carries_its_unit():
    """⚠️ A bare `-58,750` sitting directly under `₹-4,222 Cr` rows reads as
    another crore figure. Contracts and crore are not remotely comparable."""
    html = F.fii_dii_html(_CASH, _DERIV)
    assert "contracts" in html
    idx = html.index("FII index futures")
    assert "contracts" in html[idx:idx + 400], "the futures row has no unit"


def test_the_futures_unit_survives_a_missing_leg():
    html = F.fii_dii_html(_CASH, {"fut_index_net": -58750.0})
    assert "FII index futures" in html and "contracts" in html


def test_the_verdict_says_it_read_cash_only():
    """⚠️ `stage23_flows` reads `raw["fii_dii"]` — the cash segment only. Rendering
    showed STRONG BULL directly beneath "FII index futures −58,750 contracts",
    which is heavily short. Real behaviour (hedged cash longs), and an apparent
    self-contradiction unless the verdict names what it read."""
    html = F.fii_dii_html(_CASH, _DERIV, "STRONG_BULL", 55.0)
    assert "STAGE 23 FLOWS (cash)" in html

    # and the engine really does only look at cash
    import inspect
    from mios_v5.engines import stage23_flows as S
    src = inspect.getsource(S.FlowsEngine.compute)
    assert 'raw.get("fii_dii")' in src
    assert "fii_deriv" not in src, "the engine now reads derivatives too"


def test_a_numeric_external_row_is_not_marked_not_reporting():
    """⚠️ `_emoji_of` falls back to `⚪`, which means "not reporting" on every
    other card here. India VIX rendered as `⚪ 12.40` — value shown AND flagged
    absent — and the flows row inherited it. Every fixture had used bias words, so
    only a render caught it."""
    from mios_v5.ui import nifty_cockpit as NC
    html = NC.external_html([("India VIX", "12.40"),
                             ("FII / DII (EOD)", F.micro(_CASH, True))])
    assert "12.40" in html and "-4,222" in html
    assert "⚪" not in html, "a real value is being flagged as absent"


def test_a_numeric_external_row_is_not_shouted():
    """`.upper()` turned "Cr" into "CR" and the absorption note into a shout. It
    belongs on a bias word, not on a value someone already worded."""
    from mios_v5.ui import nifty_cockpit as NC
    html = NC.external_html([("FII / DII (EOD)", F.micro(_CASH, True))])
    assert "Cr" in html and "CR ·" not in html
    assert "absorption battle" in html and "ABSORPTION BATTLE" not in html


def test_a_bias_word_still_gets_its_glyph_and_caps():
    """The fix must not cost the rows that were right."""
    from mios_v5.ui import nifty_cockpit as NC
    html = NC.external_html([("Global", "Bull"), ("News", "Bearish")])
    assert "🟢 BULL" in html and "🔴 BEARISH" in html


def test_a_still_absent_external_row_is_named_as_absent():
    from mios_v5.ui import nifty_cockpit as NC
    html = NC.external_html([("Global", "Bull"), ("India VIX", None)])
    assert "not reporting" in html and "India VIX" in html


def test_is_bias_reading_separates_the_two_shapes():
    from mios_v5.ui.nifty_cockpit import is_bias_reading
    for word in ("Bull", "Bearish", "Risk-Off", "Contested", "PIN"):
        assert is_bias_reading(word), word
    for value in ("12.40", "🏛 FII -4,222 · DII +4,020 Cr (EOD)", "0.76", "—"):
        assert not is_bias_reading(value), value
