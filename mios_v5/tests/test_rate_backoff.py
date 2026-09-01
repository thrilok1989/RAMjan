"""Escalating Dhan rate-limit back-off.

The point: a transient 429 must free the chart fast, while sustained limiting
still backs off to the historical 90s cap — and escalation never exceeds it.
"""

import ast
import pathlib

from mios_v5.rate_backoff import BASE_S, CAP_S, backoff_seconds

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_first_trip_is_the_short_base_pause():
    assert backoff_seconds(1) == BASE_S
    assert BASE_S < CAP_S            # the first pause is much shorter than today's flat 90s


def test_consecutive_trips_double_up_to_the_cap():
    assert backoff_seconds(2) == BASE_S * 2
    assert backoff_seconds(3) == BASE_S * 4
    # never exceeds the historical flat window
    for n in (4, 5, 10, 100):
        assert backoff_seconds(n) == CAP_S


def test_junk_or_zero_counts_as_the_first_trip():
    for bad in (0, -3, None, "x"):
        assert backoff_seconds(bad) == BASE_S


def test_cap_is_the_old_flat_window_so_worst_case_matches_today():
    assert CAP_S == 90.0            # regression: sustained limiting == prior behaviour


def test_app_uses_escalating_helper_and_resets_on_success():
    """The three former flat-90s trip sites now call the escalating helper, and a
    clean 200 resets the ladder — so an isolated blip only pays the short pause."""
    src = (_ROOT / "vob_minimal.py").read_text()
    # the flat 90s literal is gone from the 429 trip sites
    assert "timedelta(seconds=90)" not in src
    assert src.count("_trip_dhan_backoff()") >= 3      # all three trip sites
    assert "_clear_dhan_backoff()" in src              # reset on success
    # reset is wired on the 200 path of _handle_response
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_handle_response")
    seg = ast.get_source_segment(src, fn) or ""
    assert "_clear_dhan_backoff()" in seg and "_trip_dhan_backoff()" in seg
