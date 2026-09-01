"""Two things reported from the running app: no Trade Card, and a 3-day chart.

Both were call-site defects in the reduced `_render_main_analyzer`, not in the
things being called.

* **The card was absent with no explanation.** `render_clean_card` opens with
  `if not mp or not spot_price: return` — correct for the card (it will not
  invent a read) and wrong for the page, because an empty slot looks exactly
  like a card that decided there was no trade. It was also nested inside
  `if underlying and option_data:`, so a failed chain fetch skipped the call
  entirely.
* **The chart drew 3 days.** `_nifty_df_live` ("chart path") and `_last_df`
  ("analysis path") are separate keys in `NIFTY_SOURCES` for exactly this
  reason, and both were being handed the same multi-day fetch.

`_today_session` is pure pandas, so it is exec'd out of the source and tested
for real rather than grepped for.
"""

import pathlib
import re

import pandas as pd
import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC = (_ROOT / "vob_minimal.py").read_text(encoding="utf-8")


def _load(func_name):
    """Exec one top-level function out of the app source.

    `vob_minimal.py` cannot be imported (it boots Streamlit and reads secrets),
    but a self-contained helper can be lifted and exercised properly. Source
    assertions cannot tell a working filter from a broken one.
    """
    import ast
    tree = ast.parse(_SRC)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == func_name)
    ns = {"pd": pd}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<app>", "exec"), ns)
    return ns[func_name]


_today_session = _load("_today_session")


def _session(day, bars=75):
    idx = pd.date_range(f"{day} 09:15", periods=bars, freq="5min",
                        tz="Asia/Kolkata")
    return pd.DataFrame({"datetime": idx, "open": 1.0, "high": 1.0,
                         "low": 1.0, "close": 1.0, "volume": 1})


# ── the chart frame ─────────────────────────────────────────────────────

def test_three_sessions_are_cut_down_to_one():
    multi = pd.concat([_session(d) for d in
                       ("2026-07-27", "2026-07-28", "2026-07-29")],
                      ignore_index=True)
    out = _today_session(multi)
    assert len(out) == 75
    assert out["datetime"].dt.date.nunique() == 1


def test_it_keeps_the_latest_session_not_the_first():
    multi = pd.concat([_session("2026-07-27"), _session("2026-07-29")],
                      ignore_index=True)
    out = _today_session(multi)
    assert str(out["datetime"].iloc[0].date()) == "2026-07-29"


def test_a_single_session_passes_through_untouched():
    one = _session("2026-07-29")
    assert len(_today_session(one)) == len(one)


def test_today_is_the_last_bars_date_not_the_wall_clock():
    """Before the open, and on a holiday, the newest bars belong to the previous
    session. Anchoring on `datetime.now()` would return an empty frame and blank
    the chart — indistinguishable from a data outage."""
    stale = _session("2020-01-02")          # long past, definitely not "today"
    out = _today_session(stale)
    assert len(out) == len(stale), "a past-dated frame must still draw"


def test_it_never_returns_an_empty_frame_from_a_non_empty_one():
    for day in ("2026-07-29", "2019-06-03"):
        assert len(_today_session(_session(day))) > 0


def test_it_degrades_to_the_input_rather_than_raising():
    """Too much history is a smaller problem than no chart."""
    assert _today_session(None) is None
    assert len(_today_session(pd.DataFrame())) == 0
    assert len(_today_session(pd.DataFrame({"a": [1, 2]}))) == 2


# ── the two frames stay separate ────────────────────────────────────────

def test_the_chart_frame_is_filtered_and_the_analysis_frame_is_not():
    """Truncating the FETCH would break Stage 3 market memory (previous-session
    H/L/C), `build_htf_profiles` (weekly/monthly need multiple days) and
    `compute_dual_profile`'s COMPOSITE profile (~5 sessions by definition).
    Only the chart frame may be cut."""
    assert "st.session_state['_nifty_df_live'] = _today_session(df)" in _SRC
    assert re.search(r"st\.session_state\['_last_df'\] = df\b", _SRC), \
        "the analysis frame must keep its full history"


def test_the_chart_path_key_is_the_one_the_terminal_reads_first():
    """`NIFTY_SOURCES` is ordered — filtering a key the chart never reaches
    would change nothing on screen."""
    runner = (_ROOT / "mios_v5" / "runner.py").read_text(encoding="utf-8")
    order = re.findall(r'\("(_[a-z0-9_]+)",', runner[runner.index("NIFTY_SOURCES"):])
    assert order[0] == "_nifty_df_live", f"chart path is no longer first: {order}"


def test_the_atm_legs_are_already_today_only():
    """`_leg_intraday` filters each leg to the last bar's date, so the option
    panels never showed the extra days and must not be double-filtered."""
    body = _SRC[_SRC.index("def _leg_intraday("):]
    body = body[:body.index("\ndef ")]
    assert "frame['datetime'].dt.date == today" in body


# ── the Trade Card call site ────────────────────────────────────────────

def _card_block():
    """The Trade Card's own block, bounded by the section that follows it.

    ⚠️ Was a fixed 2200-character slice, which silently truncated when the
    standing-by reason grew and made two assertions pass on absence.
    """
    start = _SRC.index("# 🎯 The Trade Card")
    end = _SRC.index("# ── 11 · the MIOS pass", start)
    return _SRC[start:end]


def test_the_card_is_not_nested_behind_the_chain_fetch():
    """Nested inside `if underlying and option_data:`, a Dhan 502 skipped the
    call and the card was absent with nothing said about why."""
    block = _card_block()
    assert "with _card_container:" in block
    # the container must be entered unconditionally, before any data guard
    assert block.index("with _card_container:") < block.index("if _mp_ready")


def test_a_missing_market_picture_is_reported_not_left_blank():
    """`render_clean_card` returns silently without one. An empty slot is
    indistinguishable from a card that decided there was no trade."""
    block = _card_block()
    assert "_mp_ready" in block
    assert "Trade Card** standing by" in block


def test_the_reason_distinguishes_the_three_causes():
    """"no chain", "no spot" and "Market Picture not ready yet" need different
    reactions — reporting them identically is how a stale read gets acted on.

    The no-chain branch now defers to `mios_v5.feed_status`, which answers the
    question the old text could not: is this broken, or is the market shut?
    """
    block = _card_block()
    assert "no spot price" in block
    assert "Market Picture has not produced a read yet" in block
    assert "feed_status" in block, "the chain reason lost its owner"


def test_the_chain_failure_reason_comes_from_the_one_owner():
    """⚠️ It used to read `_dhan_last_error` directly and fall back to "chain fetch
    returned nothing" — which was the fallback on the 401 and 429 paths, i.e. the
    two failures the app knew most about, and also the message it showed at 08:25
    when nothing was wrong at all.

    `feed_status` is now the single answer, shared with both cockpits.
    """
    block = _card_block()
    assert "feed_status" in block
    # ⚠️ On the st.info ARGUMENTS, not the block text — the retired phrase still
    # appears in the comment explaining why it went, and a raw grep matching my
    # own prose has now happened seven times in this work.
    import ast
    for node in ast.walk(ast.parse(_SRC)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("info", "caption", "markdown")):
            for piece in ast.walk(node):
                if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                    assert "chain fetch returned nothing" not in piece.value

    # and the owner really does consult the token / rate-limit / clock state
    src = (_ROOT / "mios_v5" / "feed_status.py").read_text()
    for key in ("_dhan_token_expired", "_dhan_429_until", "_dhan_last_error"):
        assert key in src, key


def test_the_card_still_renders_into_its_own_slot_at_the_top():
    """The card is claimed above V6 but filled after the bias dashboard, because
    it reads what that publishes. Both halves have to stay true."""
    claim = _SRC.index("_card_container = st.container()")
    v6 = _SRC.index("_v6_container = st.container()")
    fill = _SRC.index("# 🎯 The Trade Card")
    # Matched without the closing paren: the call gained a `picture_slot=`
    # argument when the Market Picture moved above V6, and this test is about
    # ORDER, not about the argument list.
    bias = _SRC.index("render_all_bias_dashboard(underlying, df, option_data")
    assert claim < v6, "the card must be claimed above the V6 container"
    assert bias < fill, "the card must be filled after the bias dashboard runs"


# ══════════════════════════════════════════════════════════════════════
#  🗺️ the Market Picture sits above MIOS V6
# ══════════════════════════════════════════════════════════════════════

def test_the_market_picture_slot_is_claimed_above_the_v6_dashboard():
    """The regime read — UP/DOWN/SIDEWAYS, the levels, the odds — belongs above
    MIOS V6, not below V6 and V5 both. It is a claimed container rather than a
    moved call for the reason the Trade Card is: it cannot be computed this
    early."""
    claim = _SRC.index("_picture_container = st.container()")
    v6 = _SRC.index("_v6_container = st.container()")
    assert claim < v6, "the Market Picture must be claimed above MIOS V6"


def test_the_slot_is_handed_to_the_bias_dashboard():
    """A container nothing draws into leaves a blank band above V6 — the exact
    failure this repo has shipped three times."""
    assert "picture_slot=_picture_container" in _SRC


def test_the_market_picture_is_still_computed_inside_the_bias_dashboard():
    """⚠️ Only the container moved. `cat_scores` is built part-way through
    `render_all_bias_dashboard` and is the Market Picture's input, and
    `_market_picture` — which it publishes — is what the Trade Card and Entry
    Gate read. Hoisting the CALL above the dashboard would hand it a half-built
    vote tally and publish a regime nothing downstream could trust.
    """
    body = _SRC[_SRC.index("def render_all_bias_dashboard("):]
    body = body[:body.index("\ndef ")]
    assert "render_market_picture(spot_price, df, option_data, cat_scores)" in body
    bias_call = _SRC.index("render_all_bias_dashboard(underlying, df, option_data")
    card_fill = _SRC.index("# 🎯 The Trade Card")
    assert bias_call < card_fill, (
        "the Trade Card still has to be filled after the dashboard publishes "
        "_market_picture")


def test_the_slot_is_a_parameter_and_not_a_session_key():
    """Principle 4: an input that arrives through `session_state` is invisible
    in the signature and cannot be tested or replayed. The card slot precedent
    is a local; this is a parameter."""
    sig = _SRC[_SRC.index("def render_all_bias_dashboard("):]
    sig = sig[:sig.index(")")]
    assert "picture_slot" in sig


def test_a_market_picture_failure_reports_into_the_slot_it_was_given():
    """⚪ could not report is a report. With the panel lifted above V6, a
    swallowed failure would leave an empty band at the top of the page, which
    reads as 'no regime' rather than 'this broke'."""
    body = _SRC[_SRC.index("def render_all_bias_dashboard("):]
    body = body[:body.index("\ndef ")]
    block = body[body.index("🗺️ Market Picture"):]
    block = block[:block.index("Strike-Mode Cockpit")]
    assert block.count("with picture_slot:") == 2, (
        "both the render and its failure caption must go into the slot")
    assert "Market picture unavailable" in block


def test_the_dashboard_still_works_without_a_slot():
    """`picture_slot=None` must draw inline, exactly where it used to. A helper
    that only works when wired one way is a trap for the next caller."""
    sig = _SRC[_SRC.index("def render_all_bias_dashboard("):]
    sig = sig[:sig.index(")")]
    assert "picture_slot=None" in sig
    body = _SRC[_SRC.index("def render_all_bias_dashboard("):]
    body = body[:body.index("\ndef ")]
    assert "if picture_slot is not None:" in body
    assert "else:" in body


def test_the_card_body_was_not_edited():
    """It was restored verbatim on request. The wiring around it is fair game;
    the card itself is not."""
    body = _SRC[_SRC.index("def render_clean_card("):]
    body = body[:body.index("\ndef ")]
    assert "if not mp or not spot_price:" in body, \
        "the card's own guard was changed — the fix belongs at the call site"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"chart + card wiring tests passed ({len(fns)})")
