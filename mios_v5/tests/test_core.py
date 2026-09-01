"""MIOS V5 core tests — contract, orchestrator, Stage 0 health.

Runs with plain python (no pytest dependency):
    python -m mios_v5.tests.test_core
"""

from __future__ import annotations

import sys

from mios_v5.core import (
    Bias, Engine, EngineResult, ErrorType, MarketState, Orchestrator,
    Severity, Status,
)
from mios_v5.engines import HealthEngine


# ── helpers ──────────────────────────────────────────────────────────

class _Ok(Engine):
    name = "ok_a"
    stage = 1

    def compute(self, state):
        return EngineResult(engine=self.name, status=Status.OK,
                            bias=Bias.BULL, confidence=80,
                            evidence=["fine"])


class _Dependent(Engine):
    name = "dep_b"
    stage = 2
    deps = ["ok_a"]

    def compute(self, state):
        up = state.require("ok_a")
        assert up.ok, "upstream should be OK"
        return EngineResult(engine=self.name, status=Status.OK,
                            bias=up.bias, confidence=up.confidence / 2)


class _Crasher(Engine):
    name = "crash_c"
    stage = 3

    def compute(self, state):
        raise ValueError("intentional boom")


class _NeedsMissing(Engine):
    name = "needs_missing"
    stage = 4
    deps = ["never_registered"]

    def compute(self, state):
        up = state.require("never_registered")
        # missing upstream must arrive as honest NEUTRAL, not raise
        assert up.status == Status.NEUTRAL
        return EngineResult(engine=self.name, status=Status.NEUTRAL,
                            bias=Bias.NEUTRAL)


def test_contract_constructors():
    n = EngineResult.neutral("x", "no data", ErrorType.MISSING_DATA)
    assert n.status == Status.NEUTRAL and n.bias == Bias.NEUTRAL
    assert n.errors and n.errors[0].error_type == ErrorType.MISSING_DATA

    d = EngineResult.disabled("x", "no L2 depth at retail Dhan")
    assert d.status == Status.DISABLED
    assert d.errors[0].severity == Severity.INFO
    assert d.errors[0].recovery == "permanent"

    f = EngineResult.failure("x", RuntimeError("kaput"))
    assert f.status == Status.ERROR and "kaput" in f.errors[0].reason

    row = n.errors[0].to_row()
    for k in ("ts", "trading_day", "engine", "error_type", "reason",
              "severity", "data_source", "recovery"):
        assert k in row, f"missing column {k}"


def test_orchestrator_order_and_capture():
    orch = Orchestrator()
    # register out of order on purpose — topo sort must fix it
    orch.register(_Crasher())
    orch.register(_Dependent())
    orch.register(_Ok())
    orch.register(_NeedsMissing())
    state = orch.run({"hello": 1})
    rep = state.raw["_run_report"]

    assert rep.order.index("ok_a") < rep.order.index("dep_b"), \
        "dependency must run before dependent"
    assert state.get("dep_b").ok and state.get("dep_b").confidence == 40
    # crash captured as structured ERROR, pipeline continued
    c = state.get("crash_c")
    assert c.status == Status.ERROR and "intentional boom" in c.errors[0].reason
    assert state.get("needs_missing").status == Status.NEUTRAL
    assert rep.ok == 2 and rep.errors == 1 and rep.neutral == 1
    assert 0 < rep.health_pct < 100


def test_cycle_detection():
    class A(Engine):
        name, stage, deps = "cyc_a", 1, ["cyc_b"]

        def compute(self, state):   # pragma: no cover
            return EngineResult(engine=self.name)

    class B(Engine):
        name, stage, deps = "cyc_b", 2, ["cyc_a"]

        def compute(self, state):   # pragma: no cover
            return EngineResult(engine=self.name)

    orch = Orchestrator()
    orch.register(A())
    try:
        orch.register(B())
    except ValueError as e:
        assert "cycle" in str(e)
    else:
        raise AssertionError("cycle not detected")


def test_health_engine():
    # healthy pass
    orch = Orchestrator()
    orch.register(HealthEngine())
    st = orch.run({"api_ok": True, "db_ok": True})
    h = st.get("stage00_health")
    assert h.status == Status.OK and h.data["health_score"] >= 90
    assert h.data["api"] == "OK" and h.data["db"] == "OK"

    # broken pass: token expired + db down → degraded + errors recorded
    st2 = orch.run({"token_expired": True, "db_ok": False})
    h2 = st2.get("stage00_health")
    assert h2.data["health_score"] <= 60
    sevs = {e.severity for e in h2.errors}
    assert Severity.CRITICAL in sevs
    assert h2.status == Status.DEGRADED
    # error rows are well-formed
    for row in h2.data["active_errors"]:
        assert row["engine"] == "stage00_health" and row["severity"]


def main() -> int:
    tests = [test_contract_constructors, test_orchestrator_order_and_capture,
             test_cycle_detection, test_health_engine]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:            # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
