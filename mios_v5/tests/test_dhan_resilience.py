"""Guards on how the app survives Dhan being broken.

Reported from the running app:

    Request error: 502 Server Error: Bad Gateway for url:
    https://api.dhan.co/v2/optionchain/expirylist

A 502 is Dhan's problem, but three things about the app's reaction were ours:

1. `_dhan_post` retried **only** 429. A 502 fell through to the generic
   `RequestException` handler, failed the `"429" in str(e)` check, and returned
   `None` after zero retries — the one failure class retries exist for.
2. `get_dhan_expiry_list_cached` was `@st.cache_data(ttl=300)` wrapped around
   the fetch, so it cached the **failure**. One blip blanked the expiry list for
   five minutes after Dhan recovered, and with no expiry there is no option
   chain, so every chain-derived V6 stage degraded with it.
3. Bounding the retry *sleep* to 7s left wall time unbounded: four attempts at
   `timeout=10` is 47s inside a 20s refresh — worse on the timeout path than the
   ladder it replaced.

`vob_minimal.py` boots Streamlit and reads secrets, so these read the source —
the technique `test_fetch_budget.py` uses.
"""

import pathlib
import re

_SRC = (pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
        ).read_text(encoding="utf-8")

REFRESH_S = 20          # st_autorefresh interval


def _post_body():
    body = _SRC[_SRC.index("def _dhan_post("):]
    return body[:body.index("\ndef ")]


# ── 5xx is transient and must be retried ────────────────────────────────

def test_a_5xx_is_retried_not_surrendered_to():
    """The reported 502 got zero retries because only 429 was handled."""
    body = _post_body()
    assert "500 <= response.status_code < 600" in body, \
        "no 5xx branch — a 502 still returns None on the first attempt"


def test_the_generic_handler_retries_transient_classes():
    """`raise_for_status()` turns a 502 into an HTTPError, so the string check
    has to cover it as well as the status-code branch."""
    body = _post_body()
    assert "transient" in body
    for cls in ('"502"', '"503"', '"504"'):
        assert cls in body, f"{cls} not treated as transient"
    assert "requests.exceptions.Timeout" in body
    assert "requests.exceptions.ConnectionError" in body


def test_a_permanent_failure_still_fails_immediately():
    """A 400 or a bad token will not fix itself on a second attempt. Retrying
    everything would turn every hard error into a multi-second stall."""
    body = _post_body()
    assert "if attempt < max_retries and transient:" in body
    # 401 must still short-circuit to the token prompt
    assert "response.status_code == 401" in body
    assert "_dhan_token_expired" in body


# ── total wall time, not just sleep time ────────────────────────────────

def test_the_total_elapsed_time_is_bounded_not_just_the_sleeps():
    """Bounding the ladder to [1,2,4] capped 7s of SLEEP. With timeout=10 and
    four attempts the socket waits added 40s more — 47s inside a 20s cycle."""
    body = _post_body()
    assert "deadline = time.time() +" in body, "no wall-clock deadline"
    m = re.search(r"deadline = time\.time\(\) \+ ([\d.]+)", body)
    assert m and float(m.group(1)) < REFRESH_S, \
        f"deadline {m.group(1) if m else '?'}s must fit inside a {REFRESH_S}s cycle"


def test_the_per_attempt_timeout_cannot_outlive_the_deadline():
    body = _post_body()
    assert "timeout=min(" in body, \
        "per-attempt timeout must be clamped to the remaining budget"


def test_an_exhausted_budget_returns_rather_than_starting_another_attempt():
    body = _post_body()
    assert "remaining = deadline - time.time()" in body
    assert "if remaining <= 0.5:" in body


def test_the_retry_ladder_still_fits_the_cycle():
    m = re.search(r"delays = \[([\d, ]+)\]", _SRC)
    assert m, "retry delays not found"
    assert sum(int(x) for x in m.group(1).split(",")) < REFRESH_S


# ── a failure must never be cached ──────────────────────────────────────

def test_the_expiry_list_does_not_cache_its_own_failure():
    """`@st.cache_data` around the fetch cached `None` for the full 300s TTL,
    so a one-second blip cost five minutes of option chain."""
    head = _SRC[:_SRC.index("def get_dhan_expiry_list_cached(")]
    assert not head.rstrip().endswith("@st.cache_data(ttl=300)"), \
        "the failure-caching decorator is back"


def test_a_good_expiry_list_is_remembered():
    body = _SRC[_SRC.index("def get_dhan_expiry_list_cached("):]
    body = body[:body.index("\ndef ")]
    assert "_expiry_cache_" in body
    assert "st.session_state[key] = {'ts': time.time(), 'data': fresh}" in body


def test_only_a_non_empty_result_is_remembered():
    """Caching a `{'data': []}` would pin an empty list as the last good answer
    and the fallback would serve emptiness forever."""
    body = _SRC[_SRC.index("def get_dhan_expiry_list_cached("):]
    body = body[:body.index("\ndef ")]
    assert "fresh.get('data')" in body, "a good result is not shape-checked"


def test_a_failed_fetch_falls_back_to_the_last_good_list():
    body = _SRC[_SRC.index("def get_dhan_expiry_list_cached("):]
    body = body[:body.index("\ndef ")]
    assert "if cached:" in body
    assert "return cached['data']" in body


# ── stale is reported, never passed off as fresh ────────────────────────

def test_serving_a_stale_expiry_list_says_so():
    """Three-state discipline: an expiry Dhan could not re-confirm is not the
    same as a confirmed one, and a trader has to be able to tell."""
    body = _SRC[_SRC.index("def get_dhan_expiry_list_cached("):]
    body = body[:body.index("\ndef ")]
    assert "_expiry_stale" in body


def test_the_two_expiry_failures_are_reported_differently():
    """"no expiry at all" and "a stale expiry" need different reactions."""
    assert "Expiry list is the last good copy" in _SRC
    assert "No expiry list from Dhan" in _SRC


def test_the_stale_flag_is_reset_each_render():
    """A sticky flag would keep warning about staleness after recovery, which
    trains the trader to ignore the warning."""
    assert "st.session_state['_expiry_stale'] = False" in _SRC


def test_a_5xx_is_attributed_to_dhan_not_the_user():
    """The old message was a bare `Request error: 502 …`, which reads like a
    local misconfiguration. It is not — nothing the user can change fixes it."""
    body = _post_body()
    assert "their end, not yours" in body
    assert "_dhan_last_error" in body


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"dhan resilience tests passed ({len(fns)})")
