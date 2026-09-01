"""🔢 Dashboard V6 — the tab bodies must run in dependency order.

## The bug

`st.tabs()` returns containers that can be filled in ANY sequence; the strip's
left-to-right order is fixed by `_TABS` and is unaffected. Filling them in tab
order therefore looked harmless and was not, because there is a real dependency
between the bodies:

    _charts_screen      writes  _leg_profiles
    _trading_screen     reads   _leg_profiles
                        writes  _sr_levels · _premium_energy
                                _premium_structures · _entry_decision
    _nifty_cockpit      reads   _sr_levels · _entry_decision
    _options_cockpit    reads   _premium_energy · _premium_structures

The three new cockpits were moved to the FRONT of the strip. Their producer was
not, so they ran before it:

* first render of a session — the keys did not exist, the blocks drew nothing,
  and the tab printed *"⚪ Not reporting yet: sr table"* /
  *"premium energy · premium structure · option flow"*;
* every render after — they silently showed the PREVIOUS cycle's data, one 20s
  cycle behind the panels beside them, which is the worse failure because it
  looks like it is working.

## Why this test computes the graph instead of hardcoding an order

Hardcoding "fill 0, then 4, then 1" pins the symptom. Deriving producers and
consumers from the AST pins the *rule*, so moving a tab, adding a block, or
moving a `session_state` write between functions is checked on its own terms.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[2] / "mios_v5" / "ui"
        / "dashboard_v6.py").read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)
_FNS = {n.name: n for n in ast.walk(_TREE)
        if isinstance(n, ast.FunctionDef)}

#: Session-state aliases this file writes through. `ss = st.session_state` is
#: used in most collectors, and missing it made an earlier audit see no writes at
#: all.
_STATE_NAMES = ("session_state", "ss")


def _reachable(name, seen=None):
    """Every function `name` can reach. Transitive, because a write moved into a
    helper is still that screen's write."""
    seen = seen if seen is not None else set()
    if name in seen or name not in _FNS:
        return seen
    seen.add(name)
    for node in ast.walk(_FNS[name]):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            _reachable(node.func.id, seen)
    return seen


def _base(node):
    return getattr(node, "attr", None) or getattr(node, "id", None)


def _writes(fnames):
    out = set()
    for f in fnames:
        for node in ast.walk(_FNS.get(f) or ast.Module(body=[], type_ignores=[])):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.slice, ast.Constant)
                            and _base(t.value) in _STATE_NAMES):
                        out.add(t.slice.value)
    return out


def _reads(fnames):
    out = set()
    for f in fnames:
        for node in ast.walk(_FNS.get(f) or ast.Module(body=[], type_ignores=[])):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and _base(node.func.value) in _STATE_NAMES
                    and node.args and isinstance(node.args[0], ast.Constant)):
                out.add(node.args[0].value)
    return out


def _fill_order():
    """The screens, in the order `render_dashboard_v6` actually executes them.

    Read off the `with tabs[i]:` blocks in source order — which is execution
    order — rather than off `_TABS`, which is only the strip's layout.
    """
    fn = _FNS["render_dashboard_v6"]
    out = []
    for node in ast.walk(fn):
        if isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if (isinstance(ctx, ast.Subscript)
                        and isinstance(ctx.value, ast.Name)
                        and ctx.value.id == "tabs"):
                    idx = (ctx.slice.value
                           if isinstance(ctx.slice, ast.Constant) else None)
                    # Any call, not only a locally-defined one — the Debug tab
                    # fills through a locally-imported `_debug_panel`, and
                    # requiring a local def silently dropped that tab from the
                    # count.
                    called = [c.func.id for c in ast.walk(node)
                              if isinstance(c, ast.Call)
                              and isinstance(c.func, ast.Name)]
                    if called:
                        out.append((node.lineno, idx, called[0]))
    return [(i, n) for _ln, i, n in sorted(out)]


#: Ordering faults that CANNOT be fixed by ordering, each with its reason.
#:
#: ⚠️ There is a genuine cycle in the graph:
#:
#:     _charts_screen  writes _leg_profiles  → _trading_screen needs it first
#:     _trading_screen writes _premium_structures → _charts_screen reads it
#:
#: Both cannot be first. `_leg_profiles` wins because `_trading_screen` uses it
#: for the leg reads its whole execution chain is built on, whereas
#: `_premium_structures` reaches `_charts_screen` only through `_leg_levels`,
#: where it adds OPTIONAL overlay lines (S/R, VWAP, entry, stop) to the leg
#: charts — each already `or {}`-guarded, so one cycle of lag moves a marker
#: rather than blanking a panel.
#:
#: Kept as an explicit list rather than a loosened assertion: a NEW entry here
#: has to be argued for, and the count is asserted below so the list cannot grow
#: quietly.
KNOWN_CYCLE = {
    ("_premium_structures", "_charts_screen", "_trading_screen"),
}


# ══════════════════════════════════════════════════════════════════════
#  the rule
# ══════════════════════════════════════════════════════════════════════

def test_no_screen_reads_a_key_a_later_screen_writes():
    """⚠️ The guard. A consumer filled before its producer shows nothing on the
    first render of a session and last cycle's data on every render after."""
    order = _fill_order()
    assert len(order) >= 6, f"the tab fills could not be read: {order}"

    reach = {name: _reachable(name) for _i, name in order}
    pos = {name: i for i, (_idx, name) in enumerate(order)}

    # A screen's own writes do not count against it, and neither do writes in
    # helpers it shares with another screen — only keys written EXCLUSIVELY
    # downstream are a real ordering fault.
    faults = []
    for i, (_idx, consumer) in enumerate(order):
        own = reach[consumer]
        for key in _reads(own):
            if key in _writes(own):
                continue
            for _j, producer in order[i + 1:]:
                exclusive = reach[producer] - own
                if key in _writes(exclusive):
                    faults.append((key, consumer, producer))

    unexpected = set(faults) - KNOWN_CYCLE
    assert not unexpected, "\n".join(
        f"  {k} read by {c} but written later by {p}" for k, c, p in
        sorted(unexpected))


def test_the_known_cycle_is_still_the_only_one_and_is_still_real():
    """⚠️ Two-way: the allowlist may not grow silently, and it may not go stale
    either. An entry that no longer reproduces is a fault that was fixed and left
    permitted — which would let the same bug back in unnoticed."""
    order = _fill_order()
    reach = {name: _reachable(name) for _i, name in order}
    live = set()
    for i, (_idx, consumer) in enumerate(order):
        own = reach[consumer]
        for key in _reads(own):
            if key in _writes(own):
                continue
            for _j, producer in order[i + 1:]:
                if key in _writes(reach[producer] - own):
                    live.add((key, consumer, producer))
    assert live == KNOWN_CYCLE, (
        f"allowlist drifted — no longer reproducing: {KNOWN_CYCLE - live}; "
        f"newly failing: {live - KNOWN_CYCLE}")
    assert len(KNOWN_CYCLE) == 1, "a second unresolvable cycle needs arguing for"


def test_the_producer_screen_is_filled_before_the_three_cockpits():
    """The specific ordering the fix installed, stated plainly so the intent
    survives a refactor that satisfies the graph test by another route."""
    order = [n for _i, n in _fill_order()]
    assert "_trading_screen" in order and "_nifty_cockpit" in order
    assert order.index("_charts_screen") < order.index("_trading_screen"), (
        "_trading_screen reads _leg_profiles, which _charts_screen writes")
    for consumer in ("_nifty_cockpit", "_options_cockpit"):
        assert order.index("_trading_screen") < order.index(consumer), (
            f"{consumer} reads keys _trading_screen writes")


def test_the_tab_strip_order_is_unchanged_by_the_fill_order():
    """⚠️ The layout is the user's, and this fix must not move it. `_TABS` is what
    the strip shows; the fill order only decides what runs first."""
    from mios_v5.ui.dashboard_v6 import _TABS

    assert [t.split(" ", 1)[-1] for t in _TABS[:5]] == [
        "Charts", "NIFTY", "OPTIONS", "Decision", "Trading"]
    # every tab index is filled exactly once, so reordering the fills cannot
    # silently drop or double a screen
    idxs = [i for i, _n in _fill_order() if i is not None]
    assert len(idxs) == len(set(idxs)), f"a tab is filled twice: {idxs}"
    assert set(idxs) == set(range(len(_TABS))), (
        f"unfilled tab(s): {set(range(len(_TABS))) - set(idxs)}")


def test_every_screen_named_in_TABS_actually_exists():
    for name in ("_charts_screen", "_nifty_cockpit", "_options_cockpit",
                 "_decision_center", "_trading_screen", "_intelligence"):
        assert name in _FNS, name


# ══════════════════════════════════════════════════════════════════════
#  the htf_vpfr crash the ordering audit uncovered
# ══════════════════════════════════════════════════════════════════════

def test_a_timeframe_with_no_migration_does_not_take_stage_45_down():
    """⚠️ `tf_read` stores `"migration": migration` verbatim and defaults that
    parameter to `None`, so the key exists holding `None`. `.get("migration", {})`
    returns that `None` — never the default — and the chained `.get("direction")`
    raised, taking ALL of Stage 45 to ERROR and degrading Stage 51 (validity) and
    Stage 68 (day type) which depend on it."""
    from mios_v5.htf_vpfr import migration_summary, tf_read

    read = tf_read("1H", 24583.0, {"vah": 24700.0, "val": 24450.0,
                                   "poc": 24592.0})
    assert read["migration"] is None, "the None default stopped being stored"
    out = migration_summary({"1H": read})
    assert set(out) == {"short", "medium", "long"}
    assert out["short"] == "?", "no migration means unknown, not a direction"


def test_a_missing_profile_also_survives():
    """The MISSING branch of `tf_read` stores the same `None`."""
    from mios_v5.htf_vpfr import migration_summary, tf_read

    read = tf_read("Daily", 24583.0, None)
    assert read["status"] == "MISSING"
    assert migration_summary({"Daily": read})["medium"] == "?"


@pytest.mark.parametrize("node", [None, {}, {"direction": None},
                                  {"direction": "unknown"}])
def test_every_shape_a_migration_node_arrives_in(node):
    from mios_v5.htf_vpfr import migration_summary
    out = migration_summary({"1H": {"migration": node}})
    assert out["short"] == "?"


def test_a_real_migration_is_still_read():
    """The fix must not cost the working path."""
    from mios_v5.htf_vpfr import migration_summary

    up = {t: {"migration": {"direction": "up"}} for t in ("1H", "4H")}
    assert migration_summary(up)["short"] == "↑"
    down = {t: {"migration": {"direction": "down"}} for t in ("Daily", "Weekly")}
    assert migration_summary(down)["medium"] == "↓"


def test_stage_45_reports_ok_when_one_timeframe_lacks_migration():
    """End to end: the engine must degrade to a partial read, not ERROR."""
    from mios_v5.core.contract import MarketState, Status
    from mios_v5.engines.stage45_htf_vpfr import HTFVpfrEngine

    prof = {"vah": 24700.0, "val": 24450.0, "poc": 24592.0}
    state = MarketState(raw={
        "spot": 24583.0,
        "htf_profiles": {
            "1H": {"profile": prof, "structure": {"trend": "uptrend"}},
            "Daily": {"profile": prof, "structure": {"trend": "uptrend"},
                      "migration": {"direction": "up"}},
        }})
    res = HTFVpfrEngine().compute(state)
    assert res.status is not Status.ERROR, res.evidence


# ══════════════════════════════════════════════════════════════════════
#  raw inputs: read by an engine, but is anything publishing them?
# ══════════════════════════════════════════════════════════════════════
#
# This is the `fii_net` failure again, one layer down: an engine reads a key,
# nothing puts it in `raw`, and the engine reports its honest fallback forever.
# Nothing errors, nothing warns — the stage just quietly never uses that input.

_RUNNER = (pathlib.Path(__file__).resolve().parents[2] / "mios_v5"
           / "runner.py")


def _raw_published():
    """Every key the runner puts into `raw`.

    ⚠️ Covers BOTH `raw["k"] = v` and the `raw: Dict[str, Any] = {...}` literal.
    The literal is an `AnnAssign`, not an `Assign`, and missing it made a first
    pass of this audit report four false positives.
    """
    out = set()
    for node in ast.walk(ast.parse(_RUNNER.read_text())):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            for t in targets:
                if (isinstance(t, ast.Name) and t.id == "raw"
                        and isinstance(node.value, ast.Dict)):
                    out |= {k.value for k in node.value.keys
                            if isinstance(k, ast.Constant)}
                if (isinstance(t, ast.Subscript)
                        and isinstance(t.value, ast.Name) and t.value.id == "raw"
                        and isinstance(t.slice, ast.Constant)):
                    out.add(t.slice.value)
    return out


def _raw_read(path):
    """`.get("k")` / `["k"]` on anything named `raw` — engines alias
    `raw = state.raw`, so matching only `state.raw` misses most reads."""
    out = set()
    for node in ast.walk(ast.parse(pathlib.Path(path).read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"):
            base, args = node.func.value, node.args
        elif isinstance(node, ast.Subscript):
            base, args = node.value, [node.slice]
        else:
            continue
        if ((getattr(base, "attr", None) or getattr(base, "id", None)) == "raw"
                and args and isinstance(args[0], ast.Constant)
                and isinstance(args[0].value, str)):
            out.add(args[0].value)
    return out


#: Keys an engine reads that the runner deliberately does not publish.
#:
#: The first three are documented TEST INJECTION points — each engine computes a
#: real default from the clock and the raw key only exists so a test can move it
#: (`stage30_calendar` says so in a comment). They are not wiring gaps.
#:
#: The last two are genuine gaps I am NOT fixing blind: no key anywhere in the app
#: holds either value, so `stage52_decision` always decides as if flat.
#: `_entry_signal_open` exists but is a per-leg dict, not the `position` shape
#: `decide()` expects, and guessing at that contract would change a trading
#: decision to satisfy an audit. Reported rather than patched.
KNOWN_UNPUBLISHED = {
    "calendar_today": "test injection; stage30 defaults to the IST clock",
    "now_ist_time": "test injection; stage06/38/39 default to the IST clock",
    "now_ist_dt": "test injection; stage40 defaults to the IST clock",
    # ⛔ `zone_extremes` stays. Its meaning turned out to be unambiguous —
    # `stage52_decision.py:72` defines it as "the sequence of lows/highs made
    # while price sat at the zone" — but the consequence is worse than first
    # reported: `floor_ceiling.detect_refusal([])` can never prove, `refusal` is
    # in `CHECKS`, so `confirmed` is never True, so `decide()` can never reach
    # ENTER. Stage 52 is structurally incapable of an entry, not merely flat.
    #
    # Supplying it is therefore a STRATEGY change, not a wiring fix: it takes a
    # trade-entry path from never-fires to fires, and needs four sampling
    # decisions nobody has made (what counts as "at" the zone, when the sequence
    # resets, one extreme per candle/touch/tick, and which sampling
    # `_MIN_ATTEMPTS`/`_FLAT_PCT` were calibrated against).
    "zone_extremes": "NOT WIRED — meaning is known, consequence is that Stage 52 "
                     "can never ENTER. Supplying it unblocks a dead trade-entry "
                     "path. See docs/CONTRACT_POSITION_STATE.md",
}

#: ✅ `open_position` was on the list above and is now WIRED — `runner._open_position`
#: maps it from `_entry_gate_active` with `entry_spot` → `entry`. The contract was
#: derivable from evidence (three fields, verified against identical arithmetic at
#: `vob_minimal.py:8266` and `decision_v2.py:187`), so it needed no guess.
#: `test_open_position.py` owns it.


def test_the_position_contract_gap_is_documented_not_just_excused():
    """⚠️ An allowlist entry with no written rationale becomes a permanent excuse.
    Both keys are trading-decision inputs, so the reason they are unwired has to
    live somewhere a reviewer will find it."""
    doc = (pathlib.Path(__file__).resolve().parents[2] / "docs"
           / "CONTRACT_POSITION_STATE.md")
    assert doc.exists(), "the contract note is gone but the gap is still allowed"
    text = doc.read_text()
    for key in ("open_position", "zone_extremes"):
        assert key in text, key
    # the distinction that makes this a contract task rather than a patch
    assert "_entry_signal_open" in text
    assert "per-leg" in text


def test_every_raw_key_an_engine_reads_is_published_or_listed():
    """⚠️ The guard. A stage reading a key nobody publishes reports its fallback
    forever, with no error and no warning — indistinguishable from the market
    simply being quiet."""
    root = pathlib.Path(__file__).resolve().parents[2] / "mios_v5" / "engines"
    read = set()
    for f in sorted(root.glob("stage*.py")):
        read |= _raw_read(f)
    read |= _raw_read(root / "_adapters.py")

    unpublished = read - _raw_published() - set(KNOWN_UNPUBLISHED)
    assert not unpublished, (
        "engine(s) read raw key(s) nothing publishes: "
        + ", ".join(sorted(unpublished)))


def test_the_gap_signal_finally_has_its_input():
    """⚠️ `stage33_event_impact` checks `gap_today["type"] in ("GAP-UP",
    "GAP-DOWN")` and nothing ever put `gap_today` in `raw`, so that signal had
    never once fired. `capture_day_open_and_gap` publishes `_gap_today` with
    exactly that `type` key, and the app header already reads it."""
    assert "gap_today" in _raw_published()

    src = _RUNNER.read_text()
    assert '"gap_today": session_state.get("_gap_today")' in src, (
        "forwarded, not recomputed — the producer stays the only owner")

    # and the engine really does key off "type"
    from mios_v5.engines import stage33_event_impact as S33
    import inspect
    esrc = inspect.getsource(S33)
    assert 'get("gap_today")' in esrc and '"GAP-UP"' in esrc


def test_the_gap_shape_the_app_publishes_matches_what_the_engine_checks():
    """The two have to agree on the key name, or forwarding it changes nothing —
    which is exactly how `fii_net` looked correct for months."""
    app = (pathlib.Path(__file__).resolve().parents[2]
           / "vob_minimal.py").read_text()
    assert "_gap_today" in app
    # the documented shape line in vob_minimal names the keys
    assert "'type'" in app and "prev_close" in app


def test_the_known_unpublished_list_does_not_go_stale():
    """An entry that IS now published is a gap that got closed and left
    excused — which would hide the next one."""
    published = _raw_published()
    stale = sorted(k for k in KNOWN_UNPUBLISHED if k in published)
    assert not stale, f"now published, remove from the list: {stale}"
