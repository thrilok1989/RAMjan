"""📈 ATM IV history — kept across reruns, deduped, timestamped.

`volatility_state` needs TWO samples to say anything, and the history lived in
`st.session_state['_iv_history']` — per browser session. So the Adaptive Greeks
card reported "IV: not reporting" after every restart and in every new tab, and
samples were appended on every rerun with no timestamp, so a stalled chain fetch
built fake history out of one number.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import iv_history as H

_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOW = 1_775_000_000.0


def _store():
    return {"samples": []}


# ── what counts as a sample ───────────────────────────────────────────

@pytest.mark.parametrize("iv", [12.4, 0.5, 300.0, "13.1"])
def test_a_believable_iv_is_kept(iv):
    assert H.valid(iv) is not None


@pytest.mark.parametrize("iv", [0, 0.0, 0.4, 300.1, -12.0, None, "", "abc",
                                float("nan"), float("inf"), True, [], {}])
def test_an_impossible_iv_is_refused(iv):
    """⚠️ The old guard was `if _iv > 0`, which admits 0.0001 and 9999. Both wreck
    a read that works on differences."""
    assert H.valid(iv) is None
    assert H.record(_store(), iv, NOW) is False


# ── the dedup ─────────────────────────────────────────────────────────

def test_an_unchanged_reading_is_not_recorded_twice_in_quick_succession():
    """⚠️ The old list appended on EVERY rerun. Ten cycles of the same IV is one
    observation, not ten — counting it as ten made a stalled feed look like a
    settled market."""
    s = _store()
    assert H.record(s, 12.40, NOW) is True
    assert H.record(s, 12.40, NOW + 5) is False
    assert H.record(s, 12.405, NOW + 10) is False        # below MIN_MOVE
    assert len(s["samples"]) == 1


def test_a_move_is_always_recorded():
    s = _store()
    H.record(s, 12.40, NOW)
    assert H.record(s, 12.55, NOW + 2) is True
    assert H.series(s) == [12.40, 12.55]


def test_a_flat_but_live_market_still_builds_history():
    """After MIN_GAP_S an unchanged reading IS a fresh observation."""
    s = _store()
    H.record(s, 12.40, NOW)
    assert H.record(s, 12.40, NOW + H.MIN_GAP_S) is True
    assert len(s["samples"]) == 2


def test_samples_are_capped():
    s = _store()
    for i in range(H.CAP + 60):
        H.record(s, 12.0 + i * 0.05, NOW + i)
    assert len(s["samples"]) == H.CAP


def test_a_backwards_clock_does_not_reorder_the_series():
    """A restart or a DST edit must not put a stale sample in front of newer
    ones — `series()` assumes order."""
    s = _store()
    H.record(s, 12.4, NOW)
    H.record(s, 12.9, NOW - 600)
    assert [t for t, _v in s["samples"]] == sorted(t for t, _v in s["samples"])


# ── what the consumer gets ────────────────────────────────────────────

def test_series_is_bare_floats_oldest_first():
    """`volatility_state` takes a plain sequence; reinterpreting its contract here
    would make this a second owner."""
    s = _store()
    for i, iv in enumerate((11.8, 12.0, 12.6)):
        H.record(s, iv, NOW + i * 60)
    assert H.series(s) == [11.8, 12.0, 12.6]
    assert all(isinstance(v, float) for v in H.series(s))


def test_a_window_keeps_only_recent_samples():
    s = _store()
    H.record(s, 11.0, NOW - 3600)
    H.record(s, 12.0, NOW - 60)
    assert H.series(s, window_s=600, now=NOW) == [12.0]


def test_one_sample_is_honestly_not_reporting():
    """⚠️ `volatility_state` needs two. One must not be dressed up as a flat
    market — that was the "IV: not reporting" confusion in reverse."""
    s = _store()
    assert H.read(s, NOW)["reporting"] is False
    assert "no IV samples" in H.read(s, NOW)["why"]
    H.record(s, 12.4, NOW)
    r = H.read(s, NOW)
    assert r["reporting"] is False and r["n"] == 1
    assert "one IV sample" in r["why"]


def test_two_samples_report_with_their_change_and_span():
    s = _store()
    H.record(s, 11.8, NOW)
    H.record(s, 12.6, NOW + 120)
    r = H.read(s, NOW + 120)
    assert r["reporting"] is True and r["n"] == 2
    assert r["change"] == 0.8 and r["span_s"] == 120.0


def test_volatility_state_can_finally_report_from_it():
    """End to end: the store feeds the engine that was saying "not reporting"."""
    from mios_v5.adaptive_greeks import volatility_state

    s = _store()
    for i, iv in enumerate((11.8, 12.1, 12.6)):
        H.record(s, iv, NOW + i * 60)
    v = volatility_state(iv_series=H.series(s), price_sign=1)
    assert v["reporting"] is True
    assert v["state"] == "EXPANDING"


# ── the one-time bridge ───────────────────────────────────────────────

def test_a_legacy_list_seeds_an_empty_store_once():
    s = _store()
    assert H.adopt(s, [11.9, 12.0, 12.2], NOW) == 3
    assert H.series(s) == [11.9, 12.0, 12.2]
    # and never again, so the old key is not re-imported every cycle
    assert H.adopt(s, [99.0], NOW) == 0
    assert 99.0 not in H.series(s)


def test_adopt_ignores_junk_and_an_empty_legacy_list():
    for legacy in (None, [], [0], ["x"], [None, 0.0]):
        s = _store()
        assert H.adopt(s, legacy, NOW) == 0


@pytest.mark.parametrize("store", [None, "x", 7, [], ()])
def test_a_junk_store_never_raises(store):
    assert H.record(store, 12.4, NOW) is False
    assert H.series(store) == []
    assert H.read(store, NOW)["reporting"] is False
    assert H.adopt(store, [12.0], NOW) == 0


# ── purity and wiring ─────────────────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "iv_history.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas"}
    # ⚠️ On the AST, not the text — the module docstring explains why it moved OFF
    # session_state, and a raw grep matched my own prose (the ninth time here).
    attrs = {n.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_the_store_is_cache_resource_not_cache_data_or_session_state():
    """⚠️ `cache_data` returns a COPY, so appends would be silently discarded.
    `cache_resource` hands back the same mutable object — which is what a growing
    series needs, and what makes it survive a new tab."""
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "iv_store")
    decs = []
    for d in fn.decorator_list:
        f = d.func if isinstance(d, ast.Call) else d
        decs.append(getattr(f, "attr", "") or getattr(f, "id", ""))
    assert "cache_resource" in decs, decs
    assert "cache_data" not in decs


def test_the_writer_uses_the_store_and_the_module():
    """⚠️ Bounded by the NEXT SECTION, not by a character count. The first version
    sliced a fixed 1600 chars, so inserting the per-strike recorder ahead of the IV
    write pushed `iv_store()` out of the window and failed a wiring that was fine
    — the same fixed-length-slice trap already sprung once in
    `test_chart_and_card_wiring.py`."""
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_atm_row = df_summary.iloc[")
    j = src.index("# ── 7 · the ATM legs", i)
    block = src[i:j]
    assert "iv_store()" in block
    assert "iv_history" in block
    assert ".record(" in block


def test_the_writer_reads_a_column_that_actually_exists():
    """⚠️ THE reason the card said "⚪ not reporting · no IV history published"
    forever. The write was `_atm_row.get('CE_IV', pd.Series([0]))` — and `CE_IV`
    appears NOWHERE else in the app. Because it was a `.get()` with a default it
    never raised: it yielded 0 every cycle, `valid(0)` refused it, and the store
    stayed permanently empty. The engine was right, the frame had the number, and
    the lookup asked for a column nothing writes.

    Same bug class as the `CE_OI_Change` guess in `strike_history`, caught the same
    way: assert the name against the frame's real producer.
    """
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_atm_row = df_summary.iloc[")
    block = src[i:src.index("# ── 7 · the ATM legs", i)]
    assert "impliedVolatility_CE" in block, \
        "the IV write must read the column analyze_option_chain really merges"
    # …and that column is genuinely the one the chain publishes
    merge = src[src.index("merge_cols = ["):src.index("merge_cols = [col for col")]
    assert "'impliedVolatility_CE'" in merge
    assert "'CE_IV'" not in merge, "CE_IV is not a column this app produces"


def test_a_missing_iv_column_stays_missing_rather_than_arriving_as_zero():
    """Principle 9: MISSING is not 0. The old `.get(col, pd.Series([0]))` turned an
    absent column into the number 0, which `valid()` then had to reject — the
    absence was laundered into a bad reading before anything could notice."""
    src = (_ROOT / "vob_minimal.py").read_text()
    i = src.index("_atm_row = df_summary.iloc[")
    block = src[i:src.index("# ── 7 · the ATM legs", i)]
    assert "_iv = None" in block
    assert "pd.Series([0])" not in block
    # and the store still refuses a 0 if one ever reaches it
    assert H.valid(0.0) is None and H.record(_store(), 0.0, NOW) is False
