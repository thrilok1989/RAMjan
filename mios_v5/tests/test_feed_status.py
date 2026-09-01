"""📡 "Why is there no data?" — one answer, and it must not cry wolf.

## The report this came from

> Trade Card standing by — no option chain — chain fetch returned nothing.
> Options cockpit standing by — … Those land once the chain and the ATM legs are
> both in.

Both at **08:25 IST**, on a healthy app. NSE publishes no option chain before
09:15, so the single most common cause of that message was *"the market is not
open yet"* — and it was worded as a fault.

It was also frequently a guess: `_dhan_last_error` is unset on the 401 and 429
paths, so "chain fetch returned nothing" was the fallback for the two failures the
app knew most about.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import datetime

import pytest
import pytz

from mios_v5 import feed_status as F

IST = pytz.timezone("Asia/Kolkata")
_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _t(h, m, day=12):          # 2026-08-12 is a Wednesday
    return IST.localize(datetime(2026, 8, day, h, m))


# ══════════════════════════════════════════════════════════════════════
#  the reported case
# ══════════════════════════════════════════════════════════════════════

def test_the_reported_case_names_the_clock_without_excusing_the_absence():
    """⚠️ 08:25 on a Wednesday. The clock explains why figures would be STATIC — it
    must not claim the absence is fine.

    Dhan serves the option chain outside market hours (it returns the last settled
    state) and there is no market-hours gate on `analyze_option_chain`. So an EMPTY
    chain at 08:25 is a genuine fetch failure. An earlier version of this module
    said "Nothing is wrong", which would have hidden exactly that.
    """
    code, msg = F.read({}, _t(8, 25))
    assert code == F.PREMARKET
    assert "09:15" in msg and "static" in msg
    assert "Nothing is wrong" not in msg
    assert "fetch problem" in msg, "the absence must still be called a problem"
    # frozen is expected; absent is not
    assert F.would_be_static({}, _t(8, 25)) is True


def test_the_old_wording_reaches_no_panel():
    """"chain fetch returned nothing" was a guess dressed as a diagnosis.

    ⚠️ Asserted on the ARGUMENTS of `st.info` / `st.caption` / `st.warning`, not on
    raw file text — the phrase still appears in comments and docstrings that
    explain why it was removed, and a text grep matched my own prose (the sixth
    time that has happened in this work).
    """
    banned = "chain fetch returned nothing"
    for rel in ("vob_minimal.py", "mios_v5/ui/dashboard_v6.py"):
        tree = ast.parse((_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("info", "caption", "warning",
                                           "error", "markdown")):
                continue
            for piece in ast.walk(node):
                if (isinstance(piece, ast.Constant)
                        and isinstance(piece.value, str)):
                    assert banned not in piece.value, f"{rel}:{node.lineno}"


@pytest.mark.parametrize("h,m", [(8, 30), (8, 59), (9, 0), (9, 14)])
def test_the_whole_pre_open_stretch_is_recognised(h, m):
    code, _ = F.read({}, _t(h, m))
    assert code == F.PREMARKET
    assert F.would_be_static({}, _t(h, m))


def test_the_pre_open_auction_is_distinguished():
    """09:00–09:15 is the call auction — the chain exists but is partial, which is
    a different thing to say than "not open yet"."""
    assert "auction" in F.read({}, _t(9, 5))[1]
    assert "auction" not in F.read({}, _t(8, 25))[1]


# ══════════════════════════════════════════════════════════════════════
#  precedence — most actionable cause first
# ══════════════════════════════════════════════════════════════════════

def test_a_token_expiry_outranks_the_clock():
    """⚠️ The one cause only the user can fix. Reporting "market not open yet" at
    08:25 while the token is dead would send them away from the fix."""
    code, msg = F.read({"_dhan_token_expired": True}, _t(8, 25))
    assert code == F.TOKEN
    assert "Refresh Dhan Token" in msg
    assert F.would_be_static({"_dhan_token_expired": True}, _t(8, 25)) is False


def test_a_rate_limit_outranks_the_clock_and_names_the_time():
    code, msg = F.read({"_dhan_429_until": _t(10, 32)}, _t(10, 30))
    assert code == F.RATE_LIMIT
    assert "10:32" in msg and "clears itself" in msg


def test_an_expired_rate_limit_is_ignored():
    """A stale back-off timestamp must not keep explaining a later silence."""
    code, _ = F.read({"_dhan_429_until": _t(10, 0)}, _t(10, 30))
    assert code != F.RATE_LIMIT


def test_a_recorded_error_is_reported_verbatim_during_market_hours():
    code, msg = F.read({"_dhan_last_error": "Dhan 502 on optionchain"},
                       _t(10, 30))
    assert code == F.ERROR
    assert "Dhan 502 on optionchain" in msg


def test_a_recorded_error_OUTRANKS_the_clock():
    """⚠️ Reversed deliberately. This asserted the opposite — that at 08:25 the
    clock was "the better answer" than a recorded 502.

    It is not. Dhan answers outside market hours, so if the fetch recorded a real
    failure, the calendar is not the explanation and offering it would send the
    user looking at their watch instead of their token.
    """
    code, msg = F.read({"_dhan_last_error": "Dhan 502 on optionchain"},
                       _t(8, 25))
    assert code == F.ERROR
    assert "Dhan 502 on optionchain" in msg


def test_nothing_recorded_says_exactly_that():
    """⚠️ The honest replacement. Several fetch paths return None without noting a
    reason, so claiming a fetch happened and came back empty was wrong."""
    code, msg = F.read({}, _t(10, 30))
    assert code == F.UNKNOWN
    assert "no error was recorded" in msg
    assert F.would_be_static({}, _t(10, 30)) is False


def test_after_the_close_and_the_weekend():
    assert F.read({}, _t(16, 10))[0] == F.POSTMARKET
    assert F.read({}, _t(11, 0, day=15))[0] == F.WEEKEND      # Saturday
    assert F.read({}, _t(11, 0, day=16))[0] == F.WEEKEND      # Sunday
    assert F.would_be_static({}, _t(16, 10))
    assert F.would_be_static({}, _t(11, 0, day=15))


def test_market_hours_are_the_exchange_session_not_the_apps_refresh_window():
    """⚠️ 09:15/15:30 is NSE. The app's own `st_autorefresh` window is
    08:30–15:45, and conflating the two is what produced the false alarm."""
    assert (F.OPEN_H, F.OPEN_M) == (9, 15)
    assert (F.CLOSE_H, F.CLOSE_M) == (15, 30)
    assert F.read({}, _t(15, 40))[0] == F.POSTMARKET


# ══════════════════════════════════════════════════════════════════════
#  shape, purity, junk
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("state", [None, {}, "nope", 7, []])
@pytest.mark.parametrize("now", [None, "nope", 7])
def test_junk_never_raises_and_always_returns_a_sentence(state, now):
    code, msg = F.read(state, now)
    assert isinstance(code, str) and isinstance(msg, str) and msg


def test_a_hostile_state_does_not_crash():
    class Hostile:
        def get(self, _k):
            raise RuntimeError("boom")
    assert F.read(Hostile(), _t(10, 30))[1]


def test_no_clock_falls_back_to_the_recorded_reason():
    """`now=None` must not silently claim the market is open."""
    code, _ = F.read({"_dhan_last_error": "boom"}, None)
    assert code == F.ERROR
    assert F.read({}, None)[0] == F.UNKNOWN


def test_every_code_is_declared():
    codes = {F.TOKEN, F.RATE_LIMIT, F.PREMARKET, F.POSTMARKET, F.WEEKEND,
             F.ERROR, F.UNKNOWN}
    seen = set()
    for st_, now in (({"_dhan_token_expired": True}, _t(10, 0)),
                     ({"_dhan_429_until": _t(10, 5)}, _t(10, 0)),
                     ({}, _t(8, 25)), ({}, _t(16, 10)),
                     ({}, _t(11, 0, day=15)),
                     ({"_dhan_last_error": "x"}, _t(10, 0)), ({}, _t(10, 0))):
        seen.add(F.read(st_, now)[0])
    assert seen == codes
    assert set(F.STATIC) <= codes


def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "feed_status.py").read_text()
    names = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "requests"}
    assert "session_state" not in src


# ══════════════════════════════════════════════════════════════════════
#  wiring — and the failure paths that recorded nothing
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("panel", ["Trade Card", "NIFTY cockpit",
                                   "Options cockpit"])
def test_all_three_standing_by_panels_use_the_one_owner(panel):
    """⚠️ Three panels explained one silence three different ways, and none of them
    mentioned the market being shut."""
    v6 = (_ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text()
    app = (_ROOT / "vob_minimal.py").read_text()
    src = app if panel == "Trade Card" else v6
    assert panel in src
    assert ("feed_status" in src or "_feed_reason" in src), panel


def test_every_401_handler_raises_the_token_flag():
    """⚠️ There are EIGHT 401 handlers across the Dhan fetchers, and my first pass
    patched one of them. What makes a token expiry reportable is not
    `_dhan_last_error` — it is `_dhan_token_expired`, which `feed_status` checks
    FIRST and which every handler already sets. That flag is the invariant."""
    app = (_ROOT / "vob_minimal.py").read_text()
    lines = app.splitlines()
    handlers = [i for i, l in enumerate(lines) if "status_code == 401" in l]
    assert len(handlers) >= 8, f"only found {len(handlers)} 401 handlers"
    for i in handlers:
        window = "\n".join(lines[i:i + 5])
        assert "_dhan_token_expired" in window, (
            f"the 401 handler at line {i + 1} does not raise the token flag, so "
            f"a token expiry there would be reported as an unexplained silence")


def test_feed_status_keys_off_the_flag_not_the_error_string():
    """Which is why all eight handlers are covered without touching all eight."""
    assert F.read({"_dhan_token_expired": True}, _t(10, 30))[0] == F.TOKEN
    # and it wins even with a completely unrelated error recorded
    assert F.read({"_dhan_token_expired": True,
                   "_dhan_last_error": "Dhan 502"}, _t(10, 30))[0] == F.TOKEN


def test_the_rate_limit_path_now_records_its_reason():
    app = (_ROOT / "vob_minimal.py").read_text()
    i = app.index("Rate limit exceeded after multiple retries")
    assert "_dhan_last_error" in app[max(0, i - 300):i]


def test_the_expiry_list_failure_says_it_was_the_expiry_list():
    """⚠️ Returning None here made every panel report "no option chain" when the
    chain was never requested — a different Dhan endpoint failed."""
    app = (_ROOT / "vob_minimal.py").read_text()
    i = app.index("Failed to get expiry list from Dhan API")
    block = app[max(0, i - 400):i]
    assert "_dhan_last_error" in block
    assert "expiry list" in block


def test_the_expiry_reason_does_not_overwrite_a_more_specific_one():
    """`setdefault`, not `=` — a 401 recorded inside the same call is the more
    useful reason and must survive."""
    app = (_ROOT / "vob_minimal.py").read_text()
    i = app.index("Failed to get expiry list from Dhan API")
    assert "setdefault('_dhan_last_error'" in app[max(0, i - 400):i]
