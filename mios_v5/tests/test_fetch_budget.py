"""Guards on the fetch-throttling fixes in `vob_minimal.py`.

These are performance changes on the live data path, so what matters is that
the *bounds* survive. Each guard names the failure it prevents:

* an unbounded retry ladder that sleeps longer than the refresh cycle
* a network call with no timeout, which blocks a render forever
* a leg-fetch budget that is under-provisioned and starves a leg
* a second spot fetch on a value already cached four seconds ago

`vob_minimal.py` cannot be imported (it boots Streamlit and reads secrets), so
these read the source, which is the same technique
`test_order_flow_source.py` uses.
"""

import pathlib
import re

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
        ).read_text(encoding="utf-8")

REFRESH_S = 20          # st_autorefresh interval
THROTTLE_S = 0.3        # min gap between intraday calls
MAIN_LEGS = 6           # ATM-1 / ATM / ATM+1, both sides
WING_LEGS = 4           # cockpit ATM±2


def _const(name):
    m = re.search(rf"^{name}\s*=\s*(\d+)", _SRC, re.M)
    assert m, f"{name} not found"
    return int(m.group(1))


# ── the retry ladder must fit inside a refresh cycle ────────────────────

def test_the_dhan_retry_ladder_is_shorter_than_one_refresh():
    """It was [2, 4, 8, 16] — 30s of blocking sleep inside a 20s render, so
    the page could not draw and the next autorefresh queued behind it."""
    m = re.search(r"delays = \[([\d, ]+)\]", _SRC)
    assert m, "retry delays not found"
    total = sum(int(x) for x in m.group(1).split(","))
    assert total < REFRESH_S, f"retry ladder sleeps {total}s of a {REFRESH_S}s cycle"


def test_the_retry_count_cannot_exceed_the_ladder():
    """`delays[min(attempt, 3)]` silently repeated the last delay when
    max_retries outgrew the list."""
    assert "max_retries = min(max_retries, len(delays))" in _SRC
    assert "delays[min(attempt, 3)]" not in _SRC


def test_every_dhan_post_has_a_timeout():
    """No timeout meant a hung socket blocked the render forever, with no
    error and no way to tell it from a slow response."""
    body = _SRC[_SRC.index("def _dhan_post("):]
    body = body[:body.index("\ndef ")]
    for call in re.findall(r"requests\.post\((.*?)\)", body, re.S):
        assert "timeout=" in call, "requests.post without a timeout"


def test_a_429_trips_the_global_backoff():
    """Otherwise every other caller in the same render queues behind its own
    retry ladder instead of serving cached data."""
    body = _SRC[_SRC.index("def _dhan_post("):]
    body = body[:body.index("\ndef ")]
    assert "_dhan_429_until" in body


# ── the leg-fetch budget ────────────────────────────────────────────────

def test_the_budget_is_provisioned_for_every_leg():
    """budget × (ttl / refresh) must cover the leg count, or a leg starves —
    its cache never wins the budget and it is never refreshed again.

    Modelling this is what caught it: at ttl=40 the same budget produced legs
    that went 600s without a fetch.
    """
    budget = _const("LEG_FETCH_PER_RENDER")
    ttl = 60                                   # _opt_analyze default
    renders_per_ttl = ttl / REFRESH_S
    assert budget * renders_per_ttl >= MAIN_LEGS + WING_LEGS, (
        f"budget {budget} × {renders_per_ttl:.0f} renders < "
        f"{MAIN_LEGS + WING_LEGS} legs — a leg will starve")


def test_the_budget_actually_caps_the_worst_render():
    budget = _const("LEG_FETCH_PER_RENDER")
    before = (MAIN_LEGS + WING_LEGS) * THROTTLE_S
    after = budget * THROTTLE_S
    assert after < before, "the budget must reduce the worst-case block"


def test_the_budget_resets_once_per_render():
    """Keyed on a render id — without it the budget refills mid-pass and the
    cap does nothing."""
    assert "_render_seq" in _SRC
    assert "budget[0] != render_id" in _SRC


def test_both_leg_fetchers_share_one_budget():
    """The ATM±1 loop and the cockpit wings have different TTLs and expire on
    the same render often enough that capping them separately still let the
    combined spike through."""
    assert _SRC.count("_leg_fetch_budget") >= 3


def test_going_over_budget_serves_cache_rather_than_nothing():
    """A skipped fetch must fall back to the stale bars, not drop the leg."""
    body = _SRC[_SRC.index("def _leg_intraday("):]
    body = body[:body.index("\ndef ")]
    assert "budget[1] <= 0" in body
    assert "fresh = True" in body


# ── the duplicate spot fetch ────────────────────────────────────────────

def test_spot_is_not_fetched_twice_per_render():
    """`get_index_spot_ltp` (4s cache) and `api.get_ltp_data` hit the SAME
    endpoint for the same instrument. Both firing every render was one
    redundant network call per cycle.

    The reduction removed the second caller outright — `display_metrics` was
    the only thing that needed the nested response shape, and it went with the
    native chart header. One cached read now serves the whole render.
    """
    assert "spot = get_index_spot_ltp(" in _SRC
    assert "api.get_ltp_data(" not in _SRC, "a second spot fetch is back"


# ── the throttle itself is still there ──────────────────────────────────

def test_the_intraday_throttle_survives():
    """These fixes reduce how OFTEN it is paid, never remove it — it is what
    keeps the leg fetches under Dhan's per-second limit."""
    assert "if _gap < 0.3:" in _SRC
    assert "time.sleep(0.3 - _gap)" in _SRC


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"fetch budget tests passed ({len(fns)})")
