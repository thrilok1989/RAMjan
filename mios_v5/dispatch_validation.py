"""Stage 72.9 — the dispatch validation harness.

Proves the gates under fault injection at scale, and produces the report that
Phase 6 gates the freeze on.

**It validates; it does not dispatch.** Every run uses a fake transport and a
fresh registry, so nothing leaves the process. What it exercises is the logic:
duplicates, races, restarts, timeouts, corruption and edits.

## What a simulation can and cannot prove

It can prove the *decision* logic: that two racing instances produce one send,
that a failure releases its claim, that a restart re-reads the registry rather
than a cache. Those are properties of this code and they are fully testable
here.

It cannot prove the *environment*: that Telegram's API behaves as assumed, that
Supabase's unique index fires under real concurrency, that a real network
partition looks like the timeout modelled here. Those need a live run, and the
report says so rather than implying the simulation covered them.
"""

from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from . import dispatcher as DP

#: The live criterion the freeze is gated on. A simulation cannot satisfy it.
LIVE_DISPATCH_TARGET = 500


@dataclass
class FaultTransport:
    """A transport that fails in the ways a real one does."""
    fail_rate: float = 0.0
    timeout_rate: float = 0.0
    garbage_rate: float = 0.0
    rate_limit_rate: float = 0.0
    seed: int = 7
    calls: List[Dict[str, Any]] = field(default_factory=list)
    _next_id: int = 1000

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def __call__(self, payload, edits=None):
        self.calls.append({"payload": payload, "edits": edits})
        roll = self._rng.random()
        if roll < self.fail_rate:
            raise RuntimeError("simulated network failure")
        if roll < self.fail_rate + self.timeout_rate:
            raise TimeoutError("simulated timeout")
        if roll < self.fail_rate + self.timeout_rate + self.garbage_rate:
            return object()                       # unreadable — never SENT
        if roll < (self.fail_rate + self.timeout_rate + self.garbage_rate
                   + self.rate_limit_rate):
            return {"status": "RATE_LIMIT"}
        self._next_id += 1
        return {"status": "ok", "message_id": str(self._next_id),
                "chat_id": "-100"}


def _decision(idx: int, when: datetime, state: str = "ENTER"):
    """A minimal object satisfying everything the dispatcher reads.

    Built here rather than by running Stage 72 so the harness exercises the
    dispatcher in isolation — a failure in this report is a dispatch failure,
    not an entry-engine one.
    """
    from .entry_engine import EntryDecision, decision_hash
    created = when.replace(microsecond=0).isoformat()
    did = f"decision-{idx:06d}"
    # ⚠️ `idx` must vary a field the SIGNATURE covers, not just the id.
    #
    # This used to differ by `id` alone, and the volume scenario passed —
    # because the duplicate gate compared `decision.hash`, which covers the id,
    # so 600 identical tickets counted as 600 distinct signals. That is the
    # production bug in miniature: the harness modelled "distinct" as "a new
    # object" rather than "a different trade", and therefore could never have
    # caught it. A distinct signal means a distinct strike.
    strike = 24250.0 + idx * 50.0
    base = EntryDecision(
        state=state, confidence=70, quality="A", entry_type="Breakout",
        side="CALL", strike=strike, horizon="intraday", timing="NOW",
        risk="Medium", reward="Good", entry_zone="Optimal", stop=112.0,
        targets={"target1": 138.0}, lifetime="today", readiness="READY",
        score=83, entry=118.0, risk_reward=3.3, reason_codes=(),
        top_trigger="x", warnings=(), invalidations=(),
        telegram={"state": state, "side": "CALL"}, metadata={},
        id=did, version="72.0", created_at=created, hash="")
    return dataclasses.replace(base, hash=decision_hash(
        did, "72.0", state, 70, 83, created))


@dataclass(frozen=True)
class ValidationResult:
    name: str
    passed: bool
    detail: str
    observed: Dict[str, Any] = field(default_factory=dict)


def _r(name: str, passed: bool, detail: str, **obs) -> ValidationResult:
    return ValidationResult(name, passed, detail, obs)


# ══════════════════════════════════════════════════════════════════════
#  the scenarios
# ══════════════════════════════════════════════════════════════════════

def scenario_volume(n: int = 600) -> ValidationResult:
    """N distinct decisions → N messages, no more and no fewer."""
    reg, tx = DP.MemoryRegistry(), FaultTransport()
    now = datetime.now(timezone.utc)
    for i in range(n):
        d = _decision(i, now)
        DP.Dispatcher(d, None, registry=reg, transport=tx,
                      now=now.replace(microsecond=0).isoformat()).run()
    sent = sum(1 for r in reg.rows() if r.status == DP.DELIVERED)
    return _r("volume", sent == n,
              f"{n} distinct decisions produced {sent} messages",
              dispatched=n, sent=sent)


def scenario_duplicates(n: int = 200) -> ValidationResult:
    """The same decision N times → exactly one message."""
    reg, tx = DP.MemoryRegistry(), FaultTransport()
    now = datetime.now(timezone.utc)
    d = _decision(1, now)
    iso = now.replace(microsecond=0).isoformat()
    for _ in range(n):
        DP.Dispatcher(d, None, registry=reg, transport=tx, now=iso).run()
    return _r("duplicates", len(tx.calls) == 1,
              f"{n} identical dispatches produced {len(tx.calls)} message(s)",
              attempts=n, messages=len(tx.calls))


def scenario_race(instances: int = 8) -> ValidationResult:
    """N instances sharing one registry, same decision → one message.

    Models the claim, not the thread scheduler: each instance calls `reserve()`
    through the same registry, which is exactly the contended resource. A real
    race adds OS scheduling on top, and only Postgres can prove that half.
    """
    reg, tx = DP.MemoryRegistry(), FaultTransport()
    now = datetime.now(timezone.utc)
    d = _decision(2, now)
    iso = now.replace(microsecond=0).isoformat()
    outs = [DP.Dispatcher(d, None, registry=reg, transport=tx, now=iso).run()
            for _ in range(instances)]
    sends = len(tx.calls)
    winners = sum(1 for o in outs if o.dispatch_state == DP.SENT)
    return _r("race", sends == 1 and winners == 1,
              f"{instances} concurrent instances produced {sends} message(s), "
              f"{winners} winner(s)",
              instances=instances, messages=sends, winners=winners)


def scenario_restart(n: int = 50) -> ValidationResult:
    """A restart must not re-send: the registry, not memory, is the truth."""
    reg, tx = DP.MemoryRegistry(), FaultTransport()
    now = datetime.now(timezone.utc)
    iso = now.replace(microsecond=0).isoformat()
    decisions = [_decision(i, now) for i in range(n)]
    for d in decisions:
        DP.Dispatcher(d, None, registry=reg, transport=tx, now=iso).run()
    before = len(tx.calls)
    for d in decisions:                     # "process restarted"
        DP.Dispatcher(d, None, registry=reg, transport=tx, now=iso).run()
    return _r("restart", len(tx.calls) == before,
              f"replaying {n} decisions after a restart produced "
              f"{len(tx.calls) - before} extra message(s)",
              before=before, after=len(tx.calls))


def scenario_failures(n: int = 300) -> ValidationResult:
    """Under a 40% fault rate: no silent successes, no lost retries.

    Two properties: nothing is marked SENT that the transport did not confirm,
    and a failed hash is still sendable afterwards — a failure must not poison
    the claim, because the message never went out.
    """
    reg = DP.MemoryRegistry()
    tx = FaultTransport(fail_rate=.15, timeout_rate=.1, garbage_rate=.1,
                        rate_limit_rate=.05)
    now = datetime.now(timezone.utc)
    iso = now.replace(microsecond=0).isoformat()
    outs = []
    for i in range(n):
        outs.append(DP.Dispatcher(_decision(i, now), None, registry=reg,
                                  transport=tx, now=iso).run())
    bad = [o for o in outs
           if o.dispatch_state == DP.SENT and o.telegram_state != DP.DELIVERED]
    # a failed decision must be retryable
    failed = next((o for o in outs if o.dispatch_state == DP.FAILED), None)
    retried = None
    if failed is not None:
        clean = FaultTransport()
        d = next(_decision(i, now) for i in range(n)
                 if _decision(i, now).id == failed.decision_id)
        retried = DP.Dispatcher(d, None, registry=reg, transport=clean,
                                now=iso).run()
    ok = not bad and (retried is None or retried.dispatch_state == DP.SENT)
    return _r("failures", ok,
              f"{n} dispatches at a 40% fault rate: {len(bad)} silent "
              f"success(es); a failed hash "
              f"{'retried cleanly' if retried and retried.dispatch_state == DP.SENT else 'was not retried'}",
              silent_successes=len(bad),
              retry_state=(retried.dispatch_state if retried else None))


def scenario_corruption() -> ValidationResult:
    """A tampered record, an unknown version and a broken registry."""
    now = datetime.now(timezone.utc)
    iso = now.replace(microsecond=0).isoformat()
    checks = []

    tx = FaultTransport()
    tampered = dataclasses.replace(_decision(9, now), confidence=999)
    o = DP.Dispatcher(tampered, None, registry=DP.MemoryRegistry(),
                      transport=tx, now=iso).run()
    checks.append(("tampered blocked", o.dispatch_state == DP.BLOCKED))

    bad_ver = dataclasses.replace(_decision(10, now), version="99.9")
    o = DP.Dispatcher(bad_ver, None, registry=DP.MemoryRegistry(),
                      transport=tx, now=iso).run()
    checks.append(("unknown version blocked", o.dispatch_state == DP.BLOCKED))

    class _BrokenRegistry(DP.MemoryRegistry):
        def reserve(self, decision_hash):
            raise RuntimeError("registry unreachable")

    o = DP.Dispatcher(_decision(11, now), None, registry=_BrokenRegistry(),
                      transport=tx, now=iso).run()
    checks.append(("unreachable registry does not send",
                   o.dispatch_state != DP.SENT))

    stale = _decision(12, now - timedelta(seconds=900))
    o = DP.Dispatcher(stale, None, registry=DP.MemoryRegistry(),
                      transport=tx, now=iso).run()
    checks.append(("stale decision expired", o.dispatch_state == DP.EXPIRED))

    failed = [n for n, ok in checks if not ok]
    return _r("corruption", not failed,
              "; ".join(f"{n}: {'ok' if ok else 'FAILED'}" for n, ok in checks),
              failures=failed)


def scenario_edits(n: int = 100) -> ValidationResult:
    """A lifecycle update edits the live message; it never posts a second."""
    from .trade_lifecycle import TradeLifecycleDecision
    reg, tx = DP.MemoryRegistry(), FaultTransport()
    now = datetime.now(timezone.utc)
    iso = now.replace(microsecond=0).isoformat()
    wrong = 0
    for i in range(n):
        d = _decision(1000 + i, now)
        first = DP.Dispatcher(d, None, registry=reg, transport=tx,
                              now=iso).run()
        lc = TradeLifecycleDecision(
            state="EXIT", action="EXIT", confidence=70, quality="A",
            risk="Medium", health="Poor", intent="ENTERED_INTENT",
            position_known="UNKNOWN", trail="Aggressive Trail", scale="Reduce",
            exit_reason="Illiquidity", reason_codes=(), top_trigger="x",
            warnings=(), telegram_payload={}, metadata={},
            id=f"lc-{i}", decision_id=d.id, created_at=iso, hash="")
        upd = DP.Dispatcher(d, None, lifecycle=lc, registry=reg,
                            transport=tx, now=iso).run()
        if upd.edits != first.record.telegram_message_id:
            wrong += 1
    return _r("edits", wrong == 0,
              f"{n} lifecycle updates edited the right message; {wrong} wrong",
              wrong_edits=wrong)


SCENARIOS = (scenario_volume, scenario_duplicates, scenario_race,
             scenario_restart, scenario_failures, scenario_corruption,
             scenario_edits)


def run_all() -> Dict[str, Any]:
    """Every scenario, plus the live criterion that a simulation cannot meet."""
    results = [fn() for fn in SCENARIOS]
    simulated_ok = all(r.passed for r in results)
    return {
        "simulated": {
            "passed": simulated_ok,
            "scenarios": [dataclasses.asdict(r) for r in results],
        },
        "live": {
            "passed": False,
            "dispatches": 0,
            "target": LIVE_DISPATCH_TARGET,
            "why": "no live run has been performed — this environment has no "
                   "market data, no Telegram credentials and no Supabase "
                   "instance. A simulation cannot satisfy a live criterion.",
        },
        "freeze_ready": False,
        "status": DP.STATUS,
        "contract_version": DP.CONTRACT_VERSION,
    }
