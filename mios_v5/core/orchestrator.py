"""MIOS V5 — Orchestrator.

Runs registered engines in dependency order (topological sort), collects
every EngineResult into the shared MarketState, and produces the run
summary that Stage 0 (System Health) scores.

Design rules:
* The pipeline NEVER crashes because one engine crashes — Engine.run()
  converts exceptions into structured ERROR results.
* An engine whose dependency failed still runs; it reads the upstream
  result via state.require() and decides for itself whether to go
  NEUTRAL/DEGRADED. (Market engines must degrade gracefully, not vanish.)
* Cycles are a registration bug → raised loudly at registration time,
  never silently reordered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .contract import Engine, EngineResult, MarketState, Status


@dataclass
class RunReport:
    """Summary of one full pipeline pass (input for Stage 0 health)."""
    order: List[str] = field(default_factory=list)
    ok: int = 0
    degraded: int = 0
    neutral: int = 0
    errors: int = 0
    disabled: int = 0
    total_runtime_ms: float = 0.0
    per_engine_ms: Dict[str, float] = field(default_factory=dict)

    @property
    def health_pct(self) -> float:
        """% of *runnable* engines that produced a usable result.
        DISABLED engines (structural data limits) are excluded from the
        denominator — they are not failures."""
        runnable = self.ok + self.degraded + self.neutral + self.errors
        if runnable == 0:
            return 0.0
        return round((self.ok + 0.5 * self.degraded) / runnable * 100, 1)


class Orchestrator:
    def __init__(self) -> None:
        self._engines: Dict[str, Engine] = {}
        self._order: Optional[List[str]] = None   # cached topo order

    # -- registration ----------------------------------------------------
    def register(self, engine: Engine) -> None:
        if engine.name in self._engines:
            raise ValueError(f"duplicate engine name: {engine.name}")
        self._engines[engine.name] = engine
        self._order = None                        # invalidate cached order
        self._toposort()                          # fail fast on cycles

    def register_all(self, engines: List[Engine]) -> None:
        for e in engines:
            self.register(e)

    # -- ordering --------------------------------------------------------
    def _toposort(self) -> List[str]:
        """Kahn's algorithm over the registered engines. Unknown deps are
        tolerated (they resolve to NEUTRAL at read time via state.require)
        so Phase B can wire engines incrementally; cycles raise."""
        if self._order is not None:
            return self._order
        known = set(self._engines)
        indeg: Dict[str, int] = {n: 0 for n in known}
        dependents: Dict[str, List[str]] = {n: [] for n in known}
        for name, eng in self._engines.items():
            for d in eng.deps:
                if d in known:
                    indeg[name] += 1
                    dependents[d].append(name)
        # stable ordering: stage number then name, so equal-rank engines
        # always run in spec order
        ready = sorted([n for n, k in indeg.items() if k == 0],
                       key=lambda n: (self._engines[n].stage, n))
        order: List[str] = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in dependents[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
            ready.sort(key=lambda x: (self._engines[x].stage, x))
        if len(order) != len(known):
            stuck = sorted(known - set(order))
            raise ValueError(f"dependency cycle among engines: {stuck}")
        self._order = order
        return order

    # -- execution -------------------------------------------------------
    def run(self, raw: Optional[Dict[str, Any]] = None,
            state: Optional[MarketState] = None) -> MarketState:
        """Run every registered engine once, in dependency order."""
        st = state or MarketState(raw)
        if raw and state is not None:
            st.raw.update(raw)
        report = RunReport()
        for name in self._toposort():
            result = self._engines[name].run(st)
            st.results[name] = result
            report.order.append(name)
            report.per_engine_ms[name] = result.runtime_ms
            report.total_runtime_ms += result.runtime_ms
            if result.status == Status.OK:
                report.ok += 1
            elif result.status == Status.DEGRADED:
                report.degraded += 1
            elif result.status == Status.NEUTRAL:
                report.neutral += 1
            elif result.status == Status.DISABLED:
                report.disabled += 1
            else:
                report.errors += 1
        st.raw["_run_report"] = report
        return st

    @property
    def engines(self) -> Dict[str, Engine]:
        return dict(self._engines)
