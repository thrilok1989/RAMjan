"""Stage 1 of Focus Mode — which panels may be skipped, and which may not.

Focus Mode shows the header and a minimal chart and hides everything else. The
danger is not the hiding. It is that **compute and draw are entangled**: three of
the header's own inputs — `_premium_energy`, `_trading_context`,
`_premium_structures` — are written *inside* `dashboard_v6`'s render path, and
`_trading_context` is what Stage 72 → 73 → 72.9 → Telegram reads. Skip the wrong
render and the alerts go quiet with nothing on screen to say so, which has
already happened three times in this repo.

So the rule this tool exists to enforce:

> **Focus Mode may suppress presentation. It may not suppress computation
> required by MIOS state, the decision stages, or Telegram alerts.**

## What it decides

For every function reachable from the render entry points, it answers one
question: *if this were not called, would anything else lose an input?*

* **DRAW-ONLY** — writes nothing that anyone outside it reads. Safe to skip.
* **PRODUCER** — writes a session-state key someone else reads. Must keep
  running, and Stage 4 has to split its compute from its draw.
* **CRITICAL** — a producer whose key is in `PROTECTED`: the header, the charts,
  or the alert chain depends on it. Skipping it is the regression.

## How the call graph is built, and its limit

Functions are matched **by name**, because this repo calls across modules by
bare name after a local import (`from .foo import bar` then `bar(...)`). Two
functions sharing a name are therefore merged, which can only ever make a panel
look like it writes MORE than it does.

That bias is deliberate: the expensive mistake is calling a producer draw-only,
not the reverse. A false PRODUCER costs a panel that keeps running; a false
DRAW-ONLY costs the Telegram chain.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Dict, List, Set, Tuple

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where a render pass begins.
ENTRIES = ("_render_main_analyzer", "render_dashboard_v6", "_trading_screen")

#: Session-state keys Focus Mode must never lose.
#:
#: The header and the minimal chart read the first group; the alert chain reads
#: `_trading_context`. Anything writing one of these is CRITICAL by definition,
#: whatever else it does.
PROTECTED: Tuple[str, ...] = (
    # the header's own inputs
    "_cached_option_data", "_mios_state", "_gap_today", "_reaction_sr",
    "_premium_energy", "_chrome_last",
    # the minimal chart
    "_last_df", "_atm_leg_dfs", "_money_flow_data", "_leg_profiles",
    # ⚠️ the alert chain: Stage 72 reads this, 73 and 72.9 follow, Telegram is
    # the far end. This one key is the whole reason the audit exists.
    "_trading_context", "_entry_decision", "_lifecycle_decision",
    "_dispatch_decision", "_mios_transport",
    # the simple entry system, which sends on its own path
    "_sr_levels", "_premium_structures", "_simple_entry_on",
)

_DRAW = {"markdown", "plotly_chart", "dataframe", "caption", "metric", "write",
         "table", "altair_chart", "pyplot", "image", "json", "code", "text",
         "subheader", "header", "title", "success", "warning", "error", "info"}


def _files() -> List[pathlib.Path]:
    skip = {"archive", ".git", "__pycache__", "tests", ".venv"}
    return [p for p in ROOT.rglob("*.py") if not skip & set(p.parts)]


def _key_of(node: ast.AST) -> str:
    """`st.session_state['x']` / `.get("x")` → `x`, else ``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return ""


class _Scan(ast.NodeVisitor):
    """Per function: what it writes, what it reads, who it calls, does it draw."""

    def __init__(self) -> None:
        self.writes: Dict[str, Set[str]] = {}
        self.reads: Dict[str, Set[str]] = {}
        self.calls: Dict[str, Set[str]] = {}
        self.draws: Set[str] = set()
        self._fn: List[str] = []
        #: ⚠️ Local names bound to `st.session_state`, per function.
        #:
        #: `_is_state` matched only `<x>.session_state`, so the idiomatic
        #: `ss = st.session_state` followed by `ss["k"] = v` was INVISIBLE — the
        #: audit reported no writes for four functions that write plenty. That is
        #: how `_adaptive_greeks` failed to register as a producer at all, which
        #: in turn hid it from the orphan check written to catch exactly it.
        self._alias: Dict[str, Set[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._fn.append(node.name)
        self._alias.setdefault(node.name, set())
        self.writes.setdefault(node.name, set())
        self.reads.setdefault(node.name, set())
        self.calls.setdefault(node.name, set())
        self.generic_visit(node)
        self._fn.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        # `ss = st.session_state` — remember the local name before using it.
        if self._fn and self._is_state(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self._alias[self._fn[-1]].add(t.id)
        for t in node.targets:
            if isinstance(t, ast.Subscript) and self._is_state(t.value):
                k = _key_of(t.slice)
                if k and self._fn:
                    self.writes[self._fn[-1]].add(k)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if self._fn:
            if name:
                self.calls[self._fn[-1]].add(name)
            if name in _DRAW:
                self.draws.add(self._fn[-1])
            # session_state.get("x") / .setdefault("x") — a read, and
            # `setdefault` is also a write
            if name in ("get", "setdefault") and self._is_state(
                    getattr(node.func, "value", None)) and node.args:
                k = _key_of(node.args[0])
                if k:
                    self.reads[self._fn[-1]].add(k)
                    if name == "setdefault":
                        self.writes[self._fn[-1]].add(k)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_state(node.value) and isinstance(node.ctx, ast.Load):
            k = _key_of(node.slice)
            if k and self._fn:
                self.reads[self._fn[-1]].add(k)
        self.generic_visit(node)

    def _is_state(self, node) -> bool:
        """`st.session_state`, or a local name bound to it in this function."""
        if getattr(node, "attr", "") == "session_state":
            return True
        name = getattr(node, "id", "")
        return bool(name and self._fn
                    and name in self._alias.get(self._fn[-1], ()))


def orphan_producers(module: str = "mios_v5/ui/dashboard_v6.py",
                     entry: str = "render_dashboard_v6") -> Dict[str, list]:
    """Functions in `module` that write a key somebody reads — and are never called.

    ⚠️ The bug class this exists for, in the exact shape it shipped in.

    `_adaptive_greeks` was defined, wrote `_adaptive_greeks` to session state, and
    three other surfaces read that key. Nothing called it. The key was never
    published, so the header chip, the Market Picture line and the Trade Card line
    each read an absent value and drew nothing — three failures presenting as
    "the market has nothing to say", which is the one misreading this repo keeps
    paying for.

    The tests at the time did not catch it because they tested **existence**: the
    panel function was called directly, and the wiring test asserted the write
    statement appeared in the file. It did — inside a function nobody invoked.

    ## Why the scope is one module

    Run repo-wide this returns 16 hits and almost all are false positives, for two
    blind spots that are already documented:

    * **`ast.Call` misses a reference.** `_render_main_analyzer` calls its side-
      market panels by putting them in a tuple and looping — a Name, never a
      Call — so `render_news_bias_panel` reads as uncalled. `docs/V6_DEPENDENCY_AUDIT.md`
      records the same trap deleting eleven live functions.
    * **`ENTRIES` is not every entry.** `main()`, `ws_worker`, `discord_bot`,
      `auto_option_trader` and `seller_perspective` are separate programs, and a
      producer reached only from one of those is not an orphan.

    A check that is 90% noise gets relaxed until it catches nothing. Scoped to
    `dashboard_v6` reached from `render_dashboard_v6` — where every call is a real
    call and the entry point is the only one — it is exact, it is currently zero,
    and it is where the bug happened.
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    target = root / module
    try:
        tree = ast.parse(target.read_text())
    except Exception:
        return {}
    own = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    writes: Dict[str, Set[str]] = {}
    reads: Dict[str, Set[str]] = {}
    calls: Dict[str, Set[str]] = {}
    for path in _files():
        try:
            other = ast.parse(path.read_text())
        except Exception:
            continue
        scan = _Scan()
        scan.visit(other)
        for store, got in ((writes, scan.writes), (reads, scan.reads),
                           (calls, scan.calls)):
            for fn, keys in got.items():
                store.setdefault(fn, set()).update(keys)

    reachable: Set[str] = set()
    stack = [entry]
    while stack:
        fn = stack.pop()
        if fn in reachable:
            continue
        reachable.add(fn)
        stack.extend(calls.get(fn, ()))

    consumed_anywhere: Set[str] = set()
    for keys in reads.values():
        consumed_anywhere |= keys

    out: Dict[str, list] = {}
    for fn in sorted(own):
        if fn in reachable or fn.startswith("__"):
            continue
        orphaned = sorted(k for k in (writes.get(fn) or ())
                          if k in consumed_anywhere)
        if orphaned:
            out[fn] = orphaned
    return out


def build() -> Dict[str, object]:
    writes: Dict[str, Set[str]] = {}
    reads: Dict[str, Set[str]] = {}
    calls: Dict[str, Set[str]] = {}
    draws: Set[str] = set()

    for path in _files():
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        scan = _Scan()
        scan.visit(tree)
        for store, got in ((writes, scan.writes), (reads, scan.reads),
                           (calls, scan.calls)):
            for fn, keys in got.items():
                store.setdefault(fn, set()).update(keys)
        draws |= scan.draws

    def transitive(fn: str, table: Dict[str, Set[str]],
                   seen: Set[str] | None = None) -> Set[str]:
        """Everything `fn` touches, directly or through what it calls."""
        seen = seen if seen is not None else set()
        if fn in seen:
            return set()
        seen.add(fn)
        out = set(table.get(fn, ()))
        for callee in calls.get(fn, ()):
            out |= transitive(callee, table, seen)
        return out

    # every function the render pass can reach
    reachable: Set[str] = set()
    for entry in ENTRIES:
        stack = [entry]
        while stack:
            fn = stack.pop()
            if fn in reachable:
                continue
            reachable.add(fn)
            stack.extend(calls.get(fn, ()))

    def draws_anything(fn: str, seen: Set[str] | None = None) -> bool:
        """Does `fn` put something on screen — directly OR through a helper?

        ⚠️ This used to be a direct-membership test (`fn in draws`), and that was
        a blind spot: a panel whose only `st.*` call moved behind a helper
        vanished from this report entirely. It was found the moment
        `_opportunity`'s single `st.caption` was routed through the debug gate —
        `_opportunity` is CRITICAL, it publishes `_premium_energy` for the
        header's ⚡ chip, and the audit stopped listing it at all.

        A report whose job is to say "this panel may not be hidden" must not go
        quiet because the panel got tidier. Following calls is the same treatment
        `writes` and `reads` already get.
        """
        seen = seen if seen is not None else set()
        if fn in seen:
            return False
        seen.add(fn)
        if fn in draws:
            return True
        return any(draws_anything(c, seen) for c in calls.get(fn, ()))

    rows = []
    for fn in sorted(reachable):
        if not draws_anything(fn):
            continue                      # not a panel; nothing to suppress
        own = transitive(fn, writes)
        # who else reads what this writes?
        consumers = {k for k in own
                     if any(k in reads.get(other, ()) for other in reads
                            if other != fn)}
        protected = sorted(own & set(PROTECTED))
        verdict = ("CRITICAL" if protected else
                   "PRODUCER" if consumers else "DRAW-ONLY")
        rows.append({"panel": fn, "verdict": verdict,
                     "protected": protected,
                     "writes": sorted(own)[:12],
                     "read_by_others": sorted(consumers)[:12]})

    rows.sort(key=lambda r: ({"CRITICAL": 0, "PRODUCER": 1, "DRAW-ONLY": 2}[
        r["verdict"]], r["panel"]))
    tally = {v: sum(1 for r in rows if r["verdict"] == v)
             for v in ("CRITICAL", "PRODUCER", "DRAW-ONLY")}
    return {"tally": tally, "panels": rows}


def main() -> None:
    data = build()
    out = ROOT / "focus_audit.json"
    out.write_text(json.dumps(data, indent=2))
    t = data["tally"]
    print(f"CRITICAL {t['CRITICAL']}  ·  PRODUCER {t['PRODUCER']}  ·  "
          f"DRAW-ONLY {t['DRAW-ONLY']}")
    print(f"→ {out}")
    for r in data["panels"]:
        if r["verdict"] != "DRAW-ONLY":
            print(f"  {r['verdict']:9} {r['panel']:34} "
                  f"{' '.join(r['protected'][:3])}")


if __name__ == "__main__":
    main()
