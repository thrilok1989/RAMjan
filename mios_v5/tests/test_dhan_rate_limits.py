"""The app must stay inside Dhan's published rate limits.

From Dhan's docs:

  Quote APIs (marketfeed/ltp, marketfeed/quote)  1 request / second
  Data APIs (intraday, historical)               5 / second, 100k / day
  Option Chain                                   "one unique request every
                                                  3 seconds"

The option chain is the strictest and was the only fetch with no throttle at
all — `get_dhan_option_chain` was a bare post, called once for the main read
and three more times inside the cross-expiry loop, back to back. Four requests
into a window that permits one per three seconds.

Two of those four were the *same* request: the main read takes `expiry[0]` and
the cross-expiry loop iterates `expiry[:3]`, whose first element is the same
expiry. With no cache on the function, that was fetched twice every cycle.

`vob_minimal` boots Streamlit on import, so these are source-level checks.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"


@pytest.fixture(scope="module")
def source() -> str:
    return _SRC.read_text()


@pytest.fixture(scope="module")
def tree(source: str) -> ast.Module:
    return ast.parse(source)


def _func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name}() not found")


def _consts(source: str) -> dict:
    ns: dict = {}
    for line in source.splitlines():
        if line[:1].isupper() and "=" in line and not line.startswith(("def", "class")):
            name = line.split("=")[0].strip()
            if name.isupper() and name.replace("_", "").isalnum():
                try:
                    exec(line, ns)  # noqa: S102 - literals from our own source
                except Exception:
                    pass
    return ns


# ── the published limits are encoded, not guessed ──────────────────────

def test_option_chain_gap_matches_dhans_three_seconds(source: str):
    gap = _consts(source).get("OPTION_CHAIN_MIN_GAP_S")
    assert gap is not None, "OPTION_CHAIN_MIN_GAP_S is not defined"
    assert gap >= 3.0, f"Dhan allows one chain request per 3s, gate is {gap}"


def test_quote_gap_matches_dhans_one_per_second(source: str):
    gap = _consts(source).get("QUOTE_MIN_GAP_S")
    assert gap is not None, "QUOTE_MIN_GAP_S is not defined"
    assert gap >= 1.0, f"Dhan allows one quote per second, gate is {gap}"


def test_chain_cache_outlives_a_single_render(source: str):
    """Long enough to dedupe within a render, short enough that the next
    render (~20s later) still refetches."""
    ttl = _consts(source).get("OPTION_CHAIN_TTL_S")
    assert ttl is not None
    assert 3.0 <= ttl < 20.0, ttl


# ── the chain fetch is cached and gated ────────────────────────────────

def test_option_chain_is_cached(tree: ast.Module):
    """Regression: it was a bare `_dhan_post`, so the nearest expiry was
    fetched once for the main read and again for the cross-expiry loop."""
    src = ast.unparse(_func(tree, "get_dhan_option_chain"))
    assert "_option_chain_cache" in src, "the chain fetch has no cache"
    assert "OPTION_CHAIN_TTL_S" in src


def test_option_chain_waits_out_the_window(tree: ast.Module):
    src = ast.unparse(_func(tree, "get_dhan_option_chain"))
    assert "OPTION_CHAIN_MIN_GAP_S" in src
    assert "sleep" in src, "nothing spaces consecutive chain requests"


def test_a_failed_chain_fetch_does_not_blank_a_good_one(tree: ast.Module):
    """The expiry-list cache documents this exact mistake: caching the failure
    blanked a good answer for the whole TTL."""
    fn = _func(tree, "get_dhan_option_chain")
    src = ast.unparse(fn)
    assert "if resp:" in src, "the cache is written unconditionally"


# ── quote calls are gated ──────────────────────────────────────────────

def test_every_marketfeed_post_is_gated(source: str, tree: ast.Module):
    """Both direct posts in DhanAPI plus the shared `_dhan_post` path."""
    assert "_quote_gate" in source
    gated = source.count("_quote_gate(")
    # one def + one in _dhan_post + two direct posts in get_quote
    assert gated >= 4, f"only {gated} references to the quote gate"


def test_quote_gate_only_touches_marketfeed(tree: ast.Module):
    src = ast.unparse(_func(tree, "_quote_gate"))
    assert "marketfeed" in src, "the gate must not throttle unrelated endpoints"


# ── the spot LTP is resolved once per render ───────────────────────────

def test_spot_ltp_is_scoped_to_the_render(tree: ast.Module):
    """A 4s TTL was shorter than a render — the legs alone spend 0.3s apiece
    under their gate — so the four call sites kept missing it and refetching
    the same spot on a 1-request-per-second endpoint."""
    src = ast.unparse(_func(tree, "get_index_spot_ltp"))
    assert "_render_seq" in src, "spot cache is not scoped to the render"


# ── leg fetches share one budget ───────────────────────────────────────

def test_both_wing_fetches_respect_the_leg_budget(source: str):
    """The strike loop runs ATM±2 on both sides but only ATM±1 is in
    `_atm_leg_dfs`, so the four ±2 legs fell through to a wing fetch that
    nothing capped — on top of the five the budget already allows."""
    assert source.count("_leg_fetch_budget") >= 4, (
        "a wing fetch is still bypassing the render's leg budget")


def test_leg_budget_is_bounded(source: str):
    per_render = _consts(source).get("LEG_FETCH_PER_RENDER")
    assert per_render is not None
    assert 1 <= per_render <= 8, per_render


# ── identical intraday requests cost one call ──────────────────────────

def test_intraday_is_memoised_per_render(tree: ast.Module):
    """The chart frame asks for `interval` over `days_back`; the 5-minute
    frame asks for "5" over `max(days_back, 3)`. Pick "5 min" on the timeframe
    selector with Days at 3 or more and those are byte-identical — and neither
    index fetch had a cache of its own, so it went out twice per render."""
    src = ast.unparse(_func(tree, "get_intraday_data"))
    assert "_intraday_memo" in src, "identical intraday requests are not deduped"
    assert "_render_seq" in src, "the memo must be scoped to the render"


def test_intraday_memo_does_not_cache_failures(tree: ast.Module):
    """A memoised None would make one failed fetch look like 'no data' to
    every other caller this render, each of which has its own fallback."""
    src = ast.unparse(_func(tree, "get_intraday_data"))
    assert "if out:" in src, "the memo is written unconditionally"


def test_memo_hit_skips_the_throttle(source: str):
    """A cache hit must return before the 0.3s inter-call sleep, or deduping
    would cost the very time it exists to save."""
    body = source.split("def get_intraday_data(")[1].split("\n    def ")[0]
    hit = body.index("_memo['by_key'][_memo_key]")
    sleep = body.index("time.sleep(0.3")
    assert hit < sleep, "the throttle runs before the memo returns"
