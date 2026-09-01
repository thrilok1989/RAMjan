"""Guards that keep `docs/V6_DEPENDENCY_AUDIT.md` from going stale.

The audit answers one question: what in `vob_minimal.py` can V6 not see? Its
whole method rests on a single claim — that `run_mios_pass` is the only door,
and it reads nothing but session state. If someone adds a fetch inside
`mios_v5`, or feeds a stage from somewhere other than a published cache, the
audit's numbers stop meaning anything and nobody finds out.

These tests do not re-derive the audit's counts. Line counts move every commit,
and a guard that fails on correct code gets disabled. They pin the three claims
the audit would be *wrong* without.

`vob_minimal.py` cannot be imported (it boots Streamlit and reads secrets), so
these read the source — the technique `test_fetch_budget.py` uses.
"""

import ast
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_APP = _ROOT / "vob_minimal.py"
_SRC = _APP.read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
_DOC = (_ROOT / "docs" / "V6_DEPENDENCY_AUDIT.md").read_text(encoding="utf-8")


def _tops():
    return {n.name: n for n in _TREE.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


# ── the door ────────────────────────────────────────────────────────────

def test_the_runner_is_still_the_only_entry_point():
    """The audit's method is a call-graph closure seeded at `run_mios_pass`. A
    second entry point would mean a second, unaudited input surface."""
    assert _SRC.count("from mios_v5.runner import run_mios_pass") == 1
    assert _SRC.count("run_mios_pass(") == 1      # exactly one invocation


def test_the_runner_fetches_nothing_of_its_own():
    """`raw` is assembled from session state alone. The moment the runner
    fetches, 'what V6 reads' stops being a list of cache keys — which is the
    only reason the audit can be exhaustive."""
    src = (_ROOT / "mios_v5" / "runner.py").read_text(encoding="utf-8")
    for banned in ("requests.", "yfinance", "yf.", "urllib", "httpx"):
        assert banned not in src, f"runner.py reaches the network via {banned}"


def test_no_mios_module_imports_the_app():
    """The dependency runs one way. If `mios_v5` could import `vob_minimal` it
    could call any of the 216 blocks this audit calls unreachable."""
    for path in (_ROOT / "mios_v5").rglob("*.py"):
        if "tests" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        for banned in ("import vob_minimal", "from vob_minimal"):
            assert banned not in src, f"{path.name} imports the app"


# ── the input surface ───────────────────────────────────────────────────

#: keys the audit lists as app-produced V6 inputs. Not the full set — the ones
#: whose loss would silently blank a stage rather than raise.
_CLAIMED_INPUTS = (
    "_cached_option_data", "_market_picture", "_full_market_read",
    "_market_structure", "_leg_bias_cache", "_all_bias_rows", "_gex_data",
    "_volume_delta_data", "_money_flow_data", "_composite_profile",
    "_value_migration", "_value_alignment", "_sector_rotation", "_news_bias",
    "_fii_dii_cash", "_fii_deriv_stats", "_nifty_spot_live", "_df_5m",
    "_day_open_spot", "_htf_profiles", "_reaction_sr", "vix_history",
)


def test_every_claimed_input_is_read_by_mios():
    """A key the app publishes that nothing in `mios_v5` reads is not an input
    — it is dead weight, and listing it as needed hides real dead weight."""
    mios = "\n".join(p.read_text(encoding="utf-8")
                     for p in (_ROOT / "mios_v5").rglob("*.py")
                     if "tests" not in p.parts)
    unread = [k for k in _CLAIMED_INPUTS if k not in mios]
    assert not unread, f"claimed V6 inputs nothing reads: {unread}"


def test_every_claimed_input_is_written_by_the_app():
    """The other direction: a key V6 reads that the app never fills makes the
    stage permanently NEUTRAL, which reads as 'no edge' rather than 'no data'."""
    missing = []
    for k in _CLAIMED_INPUTS:
        if not re.search(rf"session_state(\[['\"]{k}['\"]\]|\.{k})\s*=(?!=)", _SRC):
            missing.append(k)
    assert not missing, f"V6 inputs the app never publishes: {missing}"


def test_the_audit_lists_every_input_it_claims():
    for k in _CLAIMED_INPUTS:
        assert f"`{k}`" in _DOC, f"{k} missing from the audit's input table"


# ── the ordering the audit explains ─────────────────────────────────────

def _pass_offset():
    return _SRC.index("run_mios_pass(st.session_state")


def test_the_mios_pass_runs_after_the_chain_is_published():
    """Running the pass earlier read every cache from the PREVIOUS cycle, which
    is why spot sat still on the V5/V6 panels."""
    assert _SRC.index("st.session_state['_cached_option_data']") < _pass_offset()


def test_every_producer_now_runs_before_the_pass():
    """The reduction's structural fix. In the full app four producers ran AFTER
    the pass, so Stage 42 judged acceptance against S/R built a cycle earlier
    and Stage 45 profiled the previous frame. Nothing V6 reads may be written
    below the pass again — that is the whole point of the new ordering."""
    call = _pass_offset()
    late = []
    for key in ("_reaction_sr", "_gex_data", "_iv_history", "_last_df",
                "_df_5m", "vix_history", "_sector_rotation", "_money_flow_data",
                "_nifty_spot_live", "_cached_option_data"):
        m = re.search(rf"session_state\[['\"]{key}['\"]\]\s*=(?!=)", _SRC)
        if m and m.start() > call:
            late.append(key)
    assert not late, f"written after the MIOS pass — V6 reads these stale: {late}"


# ── the dead list ───────────────────────────────────────────────────────

#: the largest entries from the audit's §A. Kept short on purpose: this exists
#: to catch a *revival* (someone wiring one back up without updating the doc),
#: not to police every two-line colour helper.
#: `ReversalDetector` is deliberately NOT here. The audit listed it as dead
#: because the call-graph pass only followed `ast.Call`, and every use is
#: `ReversalDetector.calculate_reversal_score(...)` — an Attribute on the class
#: name. It is live, and so were the eight styling callbacks handed to
#: `df.style.applymap(...)`. That correction is recorded in the audit's §A.
_CLAIMED_DEAD = ("show_auto_trade_section", "run_stage2_backfill",
                 "compute_depth_sr", "send_major_sr_alert")


def test_the_blocks_called_dead_are_still_uncalled():
    tops = _tops()
    called = set()
    for sub in ast.walk(_TREE):
        if isinstance(sub, ast.Call):
            f = sub.func
            nm = (f.id if isinstance(f, ast.Name)
                  else f.attr if isinstance(f, ast.Attribute) else None)
            if nm in tops:
                called.add(nm)
    revived = [n for n in _CLAIMED_DEAD if n in called]
    assert not revived, (
        f"the audit calls these unreachable but they now have callers: {revived}")


def test_the_dead_blocks_are_gone_from_the_reduced_app():
    """They were removed by the reduction. Re-adding one means someone put an
    unreachable block back."""
    tops = _tops()
    back = [n for n in _CLAIMED_DEAD if n in tops]
    assert not back, f"unreachable blocks reintroduced: {back}"


def test_a_name_referenced_block_is_never_reported_dead_again():
    """The specific bug the reduction hit: a class used only as
    `Cls.method()`, or a function passed as a callback, reads as uncalled to a
    call-graph pass and gets deleted. pyflakes caught all eleven; this pins the
    survivors so they cannot be swept up a second time."""
    tops = _tops()
    for name in ("ReversalDetector", "color_bias", "color_pcr", "color_score",
                 "highlight_atm_row", "determine_level", "_GatePinned"):
        assert name in tops, f"{name} is referenced by name — it is not dead"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"v6 dependency audit guards passed ({len(fns)})")


# ── the blind spot the reduction had ────────────────────────────────────
#
# The audit's method is the closure of everything V6 *reads*. That is correct
# for its question and structurally blind to writers: a store the app fills for
# a LATER cycle, or for a panel, produces no read edge and falls outside the
# closure. The reduction removed `_atm_leg_ltf_delta`'s writer and kept both its
# readers, and nothing failed — `dashboard_v6._leg_flow_readings` and Stage 71.7
# simply got `{}` forever, which is indistinguishable from a quiet market.
#
# A closure cannot catch this. An assertion can.

_LEG_STORE = re.compile(r"['\"](_atm_leg_[a-z_]+)['\"]")


def _stores_read_by_v6():
    """Every `_atm_leg_*` session key any module under `mios_v5/` reads."""
    found = set()
    for path in (_ROOT / "mios_v5").rglob("*.py"):
        if "tests" in path.parts:
            continue
        found |= set(_LEG_STORE.findall(path.read_text(encoding="utf-8")))
    return found


def test_every_leg_store_v6_reads_still_has_a_writer():
    """A reader without a writer degrades silently, which is the worst way.

    This is the assertion that would have caught the severed `_atm_leg_ltf_delta`
    the day it happened, instead of Stage 71.7 being built on top of an input
    that had already stopped arriving.
    """
    # Direct writes, plus every literal inside the publisher itself: the loop
    # `for store, fn in (('_atm_leg_vob_volume', …), …)` writes through a
    # variable, so pattern-matching the assignment alone would call two live
    # stores orphaned. The publisher's body is the honest boundary — a store
    # named there is one the app still fills.
    writers = set(re.findall(
        r"st\.session_state\[['\"](_atm_leg_[a-z_]+)['\"]\]\s*(?:\[|=)", _SRC))
    writers |= set(re.findall(
        r"st\.session_state\.setdefault\(['\"](_atm_leg_[a-z_]+)['\"]", _SRC))
    pub = _tops().get("_publish_atm_legs")
    assert pub is not None, "the ATM leg publisher is gone"
    writers |= set(_LEG_STORE.findall(ast.get_source_segment(_SRC, pub) or ""))
    orphans = sorted(_stores_read_by_v6() - writers)
    assert not orphans, (
        f"{orphans} are read by mios_v5/ and written by nobody in the app — "
        f"they will return empty forever and the stage reading them will "
        f"report a quiet market rather than a missing input")


def test_the_mandatory_premium_flow_input_is_published():
    """Stage 71.7's spec makes CBV/CSV/CVD mandatory, and they come from one
    store. Named explicitly so a future reduction has to argue with a test."""
    assert "_atm_leg_ltf_delta" in _SRC, (
        "Stage 71.7's CBV/CSV/CVD input lost its writer again")
    assert "_of.totals(" in _SRC, (
        "the buyer/seller split must come from indicators/order_flow, which "
        "owns it — not from a reinstated inline copy")
