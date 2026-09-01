"""Measure the per-cycle recompute before optimising it.

The duplication survey found 11 call sites for `calculate_money_flow_profile()`
and 8 for `compute_vpfr()` in a path that reruns every ~20 seconds, against 6
`@st.cache_data` decorators — and said, deliberately:

> Call sites are not executions. This is a place to measure, not a proven cost.

This is the measurement. It is **opt-in and off by default**: nothing happens
unless `MIOS_PROFILE=1` is set in the environment, so production carries a
single `os.environ.get` per process and no wrapper at all.

## Usage

```bash
MIOS_PROFILE=1 streamlit run vob_minimal.py
```

One caption line is drawn at the bottom of the page, and the full report is
written to `profile_hotpath.json` at the end of every rerun — so the numbers
can be read from a file without watching the screen.

## What it measures, and what it cannot

Per rerun, per function: **calls**, **total wall time**, and **the distinct
argument shapes seen**. That last one is the number that decides whether
caching would help — twelve calls with twelve different frames is real work,
and twelve calls with the same frame is eleven wasted.

It cannot tell you whether a result is *needed*. A function called once per
cycle with a fresh frame is not a problem however slow it is; that is a
profiling question, not a caching one.
"""

from __future__ import annotations

import functools
import json
import os
import pathlib
import time
from typing import Any, Callable, Dict, List, Sequence

#: Off unless explicitly enabled. Checked once, at import.
ENABLED = os.environ.get("MIOS_PROFILE", "").strip() in ("1", "true", "yes")

REPORT_PATH = pathlib.Path("profile_hotpath.json")

#: The functions the survey named. Extend the list; do not extend the wrapper.
WATCH: Sequence[str] = (
    "calculate_money_flow_profile", "compute_vpfr", "compute_dynamic_poc",
    "detect_blocks", "calculate_vidya", "calculate_dealer_gex",
    "calculate_greeks", "calculate_max_pain", "detect_order_blocks",
)

_stats: Dict[str, Dict[str, Any]] = {}


def _shape(value: Any) -> str:
    """A cheap identity for an argument, for counting DISTINCT inputs.

    Deliberately not a hash of the data: hashing a 400-row frame per call would
    make the profiler the thing being measured. Length plus the last index is
    enough to separate "the same frame twelve times" from "twelve frames".
    """
    try:
        if hasattr(value, "shape"):
            tail = ""
            try:
                tail = str(value.index[-1])
            except Exception:
                pass
            return f"{type(value).__name__}{tuple(value.shape)}@{tail}"
        if isinstance(value, (list, tuple, dict, set)):
            return f"{type(value).__name__}[{len(value)}]"
        return repr(value)[:40]
    except Exception:
        return "?"


def wrap(fn: Callable, name: str = "") -> Callable:
    """Count and time one function. Returns `fn` unchanged when disabled.

    `name` is the name the caller knows the function by, not `fn.__name__`.
    They differ whenever a function is aliased or assigned — and the report is
    read by someone searching for the name in the call site, so keying on
    anything else makes it unfindable.
    """
    if not ENABLED:
        return fn
    name = name or getattr(fn, "__name__", "?")

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            rec = _stats.setdefault(
                name, {"calls": 0, "seconds": 0.0, "shapes": {}})
            rec["calls"] += 1
            rec["seconds"] += time.perf_counter() - start
            key = " | ".join(_shape(a) for a in args[:2])
            rec["shapes"][key] = rec["shapes"].get(key, 0) + 1
    return inner


def install(namespace: Dict[str, Any], names: Sequence[str] = WATCH) -> List[str]:
    """Wrap every watched function found in a module namespace.

    Called with `globals()` from the app. Idempotent — a function already
    wrapped is skipped, so a Streamlit rerun that re-executes the module top to
    bottom does not nest wrappers twelve deep.
    """
    if not ENABLED:
        return []
    done = []
    for n in names:
        fn = namespace.get(n)
        if callable(fn) and not getattr(fn, "__wrapped__", None):
            namespace[n] = wrap(fn, n)
            done.append(n)
    return done


def report() -> Dict[str, Any]:
    """Per-function calls, seconds, and how many DISTINCT inputs were seen.

    `wasted` is the headline: calls minus distinct inputs. It is the number of
    times an identical computation was repeated inside one rerun, which is
    exactly what a cache would remove — and nothing else in the report is
    evidence for caching.
    """
    out = {}
    for name, rec in sorted(_stats.items(),
                            key=lambda kv: -kv[1]["seconds"]):
        distinct = len(rec["shapes"])
        out[name] = {
            "calls": rec["calls"],
            "seconds": round(rec["seconds"], 4),
            "ms_per_call": round(1000 * rec["seconds"] / max(1, rec["calls"]), 2),
            "distinct_inputs": distinct,
            "wasted_calls": max(0, rec["calls"] - distinct),
        }
    return out


def flush(path: pathlib.Path = REPORT_PATH) -> Dict[str, Any]:
    """Write the report and clear the counters for the next rerun.

    Cleared on purpose: the question is what ONE cycle costs. Totals across a
    session answer a different question and would grow without bound.
    """
    data = report()
    try:
        path.write_text(json.dumps(data, indent=2))
    except Exception:
        pass
    _stats.clear()
    return data


def summary_line(data: Dict[str, Any]) -> str:
    """One line for a caption — total time and total repeated work."""
    if not data:
        return "hotpath: nothing measured this cycle"
    secs = sum(d["seconds"] for d in data.values())
    wasted = sum(d["wasted_calls"] for d in data.values())
    calls = sum(d["calls"] for d in data.values())
    return (f"hotpath: {calls} calls · {secs * 1000:.0f} ms · "
            f"{wasted} repeated on identical input")
