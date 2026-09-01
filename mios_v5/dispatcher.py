"""Stage 72.9 — the Decision Dispatcher & Telegram Orchestrator.

**The single gateway between MIOS and the outside world.**

It is not an analysis engine, not an execution engine and not a lifecycle
engine. It owns one question:

> **Should this decision leave MIOS?**

```
Stage 72 → Stage 72.9 → Telegram
              ↑ the only door
Stage 73 ────┘  (optional, when a trade is being managed)
```

## It owns the gateway, not the socket

`import requests` inside `mios_v5` is a named forbidden failure mode, and this
module is inside `mios_v5`. So the **transport is injected**:

```python
Dispatcher(decision, ctx, registry=..., transport=app_sender).run()
```

`transport` is any callable taking the payload and returning a delivery result.
The dispatcher never learns what is behind it.

This is *stronger* than owning the client. A send is impossible without passing
the gates below, the "exactly one gateway" guarantee holds by construction, and
the whole stage is unit-testable with no network at all. The same applies to the
`registry`: history lives in Supabase, and this module reaches no database.

## The gates are the product

Everything here exists to stop the wrong message going out:

* **Validation** — a decision whose hash does not verify is `BLOCKED`. A record
  altered since it was made must never be broadcast as though it were current.
* **Duplicates** — the same hash never dispatches twice. `SENT` is terminal.
* **Supersession** — when a newer decision has already gone out, the older one
  is `SUPERSEDED` and dies quietly. Only the newest survives.
* **Expiry** — a decision older than `MAX_AGE_SECONDS` is stale; the tape has
  moved and the message would be about a market that no longer exists.

## Editing beats re-sending

When the registry already holds a live message for this `decision_id`, the
dispatcher names it in `edits` so a trade going `ENTER → TRAIL → EXIT` updates
one message instead of posting three that each look like a new signal.

**Editing is a decision, not a default.** A message whose content has not
materially changed is neither re-sent nor edited — a message that rewrites
itself every cycle is as ignorable as one that repeats, which is the reasoning
Stage 65's narrator uses for writing on transitions only.

## What it never does

It does not modify the payload's wording. Stage 72 wrote it; this stage adds
identity and nothing else. It re-derives no decision, and it cannot choose what
to trade — that is two stages upstream.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, fields as _fields
from datetime import datetime, timezone
from time import perf_counter as _perf
from types import MappingProxyType
from typing import (Any, Callable, Dict, List, Mapping, Optional,
                    Sequence, Tuple)

from .entry_engine import EntryDecision
from .trade_lifecycle import TradeLifecycleDecision
from .trading_context import UNKNOWN, TradingContext, _thaw

VERSION = "72.9"

#: The frozen contract version. Bumped only for a breaking change to
#: `DispatchDecision` or to the registry protocol.
CONTRACT_VERSION = "72.9.0"

#: ⚠️ Not `FROZEN`. Every gate is proven in simulation and the live criterion is
#: not met — see `docs/STAGE72_9_VALIDATION_REPORT.md`. A dispatcher is the one
#: stage where a bug is loud and public, so it freezes on live evidence rather
#: than on green tests. Flip to "FROZEN" when the report says the live run
#: passed; nothing else changes.
STATUS = "VALIDATED_SIMULATED"

#: Entry-decision contract versions this dispatcher understands. A decision
#: written against a shape this stage has never seen is `BLOCKED` rather than
#: best-effort parsed — a misread field in a broadcast message is worse than
#: silence.
#:
#: `72.1` added Stage 71.85's behaviour block to the payload. `72.0` stays
#: supported because a stored decision must keep replaying against the shape it
#: was written for — the new keys are additive, and a `72.0` payload simply has
#: none of them rather than having them wrong.
SUPPORTED_DECISION_VERSIONS: Tuple[str, ...] = ("72.0", "72.1")

#: A decision older than this describes a market that has moved on.
MAX_AGE_SECONDS = 300

# ── the signal's identity, which is NOT the decision's identity ───────
#: `decision.hash` covers `id` and `created_at`, both minted fresh every cycle.
#: That is correct for what it is — a tamper check identifying *this decision
#: instance* — but it means two consecutive cycles describing the identical
#: setup hash differently, so a duplicate check comparing it **can never fire**.
#: That is exactly what happened: the same signal went out on every refresh.
#:
#: These are the fields that make two messages the SAME SIGNAL to a reader. No
#: id, no timestamp, and deliberately no score or confidence — a setup whose
#: score ticks 80 → 81 is not news, and including them would restore the bug in
#: a slower form.
SIGNATURE_FIELDS: Tuple[str, ...] = ("state", "side", "strike", "entry",
                                     "stop", "entry_zone")

#: Even a genuinely different signature is not worth repeating immediately.
#: A level re-tested three minutes later is the same idea arriving twice; this
#: is the floor between two messages about the same side and strike.
COOLDOWN_SECONDS = 900

# ── Phase 4 · the states ──────────────────────────────────────────────
READY, WAIT, BLOCKED = "READY", "WAIT", "BLOCKED"
SUPERSEDED, DUPLICATE, EXPIRED = "SUPERSEDED", "DUPLICATE", "EXPIRED"
SENT, FAILED = "SENT", "FAILED"
COOLDOWN = "COOLDOWN"

DISPATCH_STATES: Tuple[str, ...] = (READY, WAIT, BLOCKED, SUPERSEDED,
                                    DUPLICATE, EXPIRED, SENT, FAILED,
                                    COOLDOWN, UNKNOWN)


def decision_signature(decision: Any) -> str:
    """A stable SHA-256 over what makes a decision the same *signal*.

    Two cycles describing one setup produce one signature, which is the whole
    point: `decision.hash` cannot do this job because it is unique by design.
    Rendered through `str` per field so `24650` and `"24650"` cannot diverge.
    """
    parts = []
    for name in SIGNATURE_FIELDS:
        val = getattr(decision, name, None)
        if val is None and isinstance(decision, Mapping):
            val = decision.get(name)
        parts.append(str(val))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

# ── Phase 7 · delivery ────────────────────────────────────────────────
NOT_SENT, DELIVERED = "NOT_SENT", "SENT"
DELIVERY_FAILED, RETRY, RATE_LIMIT = "FAILED", "RETRY", "RATE_LIMIT"

DELIVERY_STATES: Tuple[str, ...] = (NOT_SENT, DELIVERED, DELIVERY_FAILED,
                                    RETRY, RATE_LIMIT, UNKNOWN)

#: Entry states that are worth telling anybody about. `WAIT` is the engine
#: working correctly and saying so every cycle would train the reader to mute
#: the channel — the one outcome a signal channel cannot survive.
SENDABLE_STATES: Tuple[str, ...] = ("ENTER", "ENTRY_READY", "ABORT")

#: Lifecycle actions worth an update to a live message.
SENDABLE_ACTIONS: Tuple[str, ...] = ("EXIT", "SCALE_OUT", "ADD", "ABORT")

#: Transport results this stage understands. Anything else is `UNKNOWN`, never
#: assumed successful.
_TRANSPORT_OK = ("ok", "sent", "delivered", True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def dispatch_hash(dispatch_id: str, decision_id: str, version: str,
                  dispatch_state: str, created_at: str) -> str:
    """Stable SHA-256 over the dispatch's own identity."""
    parts = [str(dispatch_id), str(decision_id), str(version),
             str(dispatch_state), str(created_at)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════
#  Phase 8 · 9 · 10 — the registry
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DispatchRecord:
    """One append-only history row. Never updated in place."""
    decision_id: str
    decision_hash: str
    dispatch_state: str
    created_at: str
    telegram_message_id: Optional[str] = None
    chat_id: Optional[str] = None
    status: str = NOT_SENT
    #: The SIGNAL's identity — see `decision_signature`. Defaulted so a stored
    #: row written before this field existed still loads.
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"decision_id": self.decision_id,
                "decision_hash": self.decision_hash,
                "dispatch_state": self.dispatch_state,
                "created_at": self.created_at,
                "telegram_message_id": self.telegram_message_id,
                "chat_id": self.chat_id, "status": self.status,
                "signature": self.signature}


class MemoryRegistry:
    """The default registry — append-only history plus the Phase 10 cache.

    Enough for one session, and what the tests run against. A Supabase-backed
    implementation satisfies the same three methods and is injected by the app,
    because this module reaches no database.

    **`record()` appends. Nothing is ever updated in place** — a decision that
    was `READY` and then `SENT` is two rows, so the history says what happened
    rather than only where it ended.
    """

    def __init__(self) -> None:
        self._rows: List[DispatchRecord] = []
        self._claims: set = set()

    # ── the claim protocol ────────────────────────────────────────────
    # `reserve` → send → `confirm` or `release`.
    #
    # Checking "have I sent this?" and then sending is two operations with a gap
    # between them, and two app instances starting together both pass the check
    # before either sends. `reserve()` closes the gap: it is the *claim*, and
    # only one caller can win it. In Supabase that is a unique index doing the
    # work; here it is a set.
    def reserve(self, decision_hash: str) -> bool:
        """Claim this hash. `False` means somebody else already holds it."""
        if not decision_hash or decision_hash in self._claims:
            return False
        if decision_hash in self.sent_hashes():
            return False
        self._claims.add(decision_hash)
        return True

    def confirm(self, decision_hash: str) -> None:
        """The send succeeded — the claim becomes permanent via the SENT row."""
        self._claims.discard(decision_hash)

    def release(self, decision_hash: str) -> None:
        """The send failed. Release the claim so a retry is not blocked by a
        message that never went out."""
        self._claims.discard(decision_hash)

    # ── the three methods any registry must provide ───────────────────
    def record(self, row: DispatchRecord) -> None:
        self._rows.append(row)

    def rows(self) -> Tuple[DispatchRecord, ...]:
        return tuple(self._rows)

    def sent_hashes(self) -> Tuple[str, ...]:
        return tuple(r.decision_hash for r in self._rows
                     if r.status == DELIVERED)

    def sent_signatures(self) -> Tuple[str, ...]:
        """The SIGNALS already delivered — the check `sent_hashes` cannot do,
        because a decision hash is unique per cycle by construction."""
        return tuple(r.signature for r in self._rows
                     if r.status == DELIVERED and r.signature)

    def last_sent_at(self, signature: str) -> Optional[str]:
        """When this signal last went out, for the cooldown."""
        for row in reversed(self._rows):
            if row.signature == signature and row.status == DELIVERED:
                return row.created_at
        return None

    # ── Phase 10 · the cache, derived rather than stored twice ────────
    @property
    def last_dispatched_hash(self) -> Optional[str]:
        sent = [r for r in self._rows if r.status == DELIVERED]
        return sent[-1].decision_hash if sent else None

    @property
    def last_dispatched_id(self) -> Optional[str]:
        sent = [r for r in self._rows if r.status == DELIVERED]
        return sent[-1].decision_id if sent else None

    @property
    def last_dispatch_time(self) -> Optional[str]:
        sent = [r for r in self._rows if r.status == DELIVERED]
        return sent[-1].created_at if sent else None

    def live_message(self, decision_id: str) -> Optional[DispatchRecord]:
        """The most recent delivered message for this decision, if any — the
        one an update should EDIT rather than replace."""
        for row in reversed(self._rows):
            if (row.decision_id == decision_id and row.status == DELIVERED
                    and row.telegram_message_id):
                return row
        return None


# ══════════════════════════════════════════════════════════════════════
#  Phase 4 · 5 — metrics and health
# ══════════════════════════════════════════════════════════════════════
#
# ⛔ MONITORING ONLY. Nothing here may reach a trading decision, and a test
# asserts the dispatcher never reads its own metrics. A dispatch layer that
# throttled itself because its failure rate looked high would turn an outage
# into a silence, which is the worse of the two.

@dataclass(frozen=True)
class DispatchMetrics:
    """Operational counters, derived from the registry rather than accumulated.

    Derived on read because a counter incremented alongside the rows is a second
    source of truth that drifts the first time a write fails halfway.
    """
    dispatch_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    duplicate_block_count: int = 0
    edit_count: int = 0
    retry_count: int = 0
    average_dispatch_latency_ms: Optional[float] = None
    average_edit_latency_ms: Optional[float] = None
    maximum_dispatch_latency_ms: Optional[float] = None
    failure_percentage: Optional[float] = None
    duplicate_percentage: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in _fields(self)}


def _pct(part: int, whole: int) -> Optional[float]:
    return None if not whole else round(100.0 * part / whole, 2)


def metrics(registry: Any, latencies: Optional[Sequence[float]] = None,
            edit_latencies: Optional[Sequence[float]] = None
            ) -> DispatchMetrics:
    """Read the counters off the history. Never mutates anything."""
    rows = tuple(getattr(registry, "rows", lambda: ())())
    total = len(rows)
    success = sum(1 for r in rows if r.status == DELIVERED)
    failed = sum(1 for r in rows if r.status in (DELIVERY_FAILED, UNKNOWN))
    dupes = sum(1 for r in rows if r.dispatch_state == DUPLICATE)
    retries = sum(1 for r in rows if r.status in (RETRY, RATE_LIMIT))
    edits = sum(1 for r in rows if r.dispatch_state == SENT
                and r.telegram_message_id
                and any(o.telegram_message_id == r.telegram_message_id
                        and o is not r for o in rows))
    lat = [float(x) for x in (latencies or []) if x is not None]
    ed = [float(x) for x in (edit_latencies or []) if x is not None]
    return DispatchMetrics(
        dispatch_count=total, success_count=success, failed_count=failed,
        duplicate_block_count=dupes, edit_count=edits, retry_count=retries,
        average_dispatch_latency_ms=(round(sum(lat) / len(lat), 2) if lat
                                     else None),
        average_edit_latency_ms=(round(sum(ed) / len(ed), 2) if ed else None),
        maximum_dispatch_latency_ms=(round(max(lat), 2) if lat else None),
        failure_percentage=_pct(failed, total),
        duplicate_percentage=_pct(dupes, total))


@dataclass(frozen=True)
class DispatchHealth:
    """A lightweight operational view. **Monitoring only.**"""
    status: str
    dispatches_today: int
    duplicates_today: int
    failures_today: int
    average_latency_ms: Optional[float]
    registry_connected: bool
    telegram_connected: bool
    last_dispatch_time: Optional[str]
    version: str = CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in _fields(self)}


def health(registry: Any, transport: Any = None,
           latencies: Optional[Sequence[float]] = None,
           today: Optional[str] = None) -> DispatchHealth:
    """`OK` · `DEGRADED` · `DOWN` · `IDLE`, from the history alone.

    `DEGRADED` rather than `DOWN` while anything is still getting through: an
    operator needs to tell "the channel is struggling" from "the channel is
    gone", and one number that collapses both is the number nobody acts on.
    """
    day = (today or _now_iso())[:10]
    rows = tuple(getattr(registry, "rows", lambda: ())())
    todays = [r for r in rows if str(r.created_at)[:10] == day]
    sent = sum(1 for r in todays if r.status == DELIVERED)
    failed = sum(1 for r in todays if r.status in (DELIVERY_FAILED, UNKNOWN))
    dupes = sum(1 for r in todays if r.dispatch_state == DUPLICATE)

    registry_ok = bool(getattr(registry, "connected", True))
    if not registry_ok:
        status = "DOWN"
    elif not todays:
        status = "IDLE"
    elif sent == 0 and failed:
        status = "DOWN"
    elif failed:
        status = "DEGRADED"
    else:
        status = "OK"

    lat = [float(x) for x in (latencies or []) if x is not None]
    return DispatchHealth(
        status=status, dispatches_today=len(todays), duplicates_today=dupes,
        failures_today=failed,
        average_latency_ms=(round(sum(lat) / len(lat), 2) if lat else None),
        registry_connected=registry_ok,
        telegram_connected=transport is not None,
        last_dispatch_time=getattr(registry, "last_dispatch_time", None))


# ══════════════════════════════════════════════════════════════════════
#  the output
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DispatchDecision:
    """Whether a decision may leave MIOS, and what happened when it did."""
    dispatch_state: str
    dispatch_reason: str
    telegram_state: str
    duplicate: bool
    should_send: bool
    payload: Mapping[str, Any]
    edits: Optional[str]
    record: Optional[DispatchRecord]
    metadata: Mapping[str, Any]
    id: str = ""
    decision_id: str = ""
    version: str = VERSION
    created_at: str = ""
    hash: str = ""

    def verify(self) -> bool:
        return self.hash == dispatch_hash(self.id, self.decision_id,
                                          self.version, self.dispatch_state,
                                          self.created_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "decision_id": self.decision_id,
            "version": self.version, "created_at": self.created_at,
            "hash": self.hash,
            "dispatch_state": self.dispatch_state,
            "dispatch_reason": self.dispatch_reason,
            "telegram_state": self.telegram_state,
            "duplicate": self.duplicate, "should_send": self.should_send,
            "edits": self.edits,
            "payload": _thaw(self.payload),
            "record": self.record.to_dict() if self.record else None,
            "metadata": _thaw(self.metadata),
        }


class Dispatcher:
    """`Dispatcher(decision, ctx, ...).run()` → `DispatchDecision`."""

    def __init__(self, decision: Optional[EntryDecision] = None,
                 ctx: Optional[TradingContext] = None,
                 lifecycle: Optional[TradeLifecycleDecision] = None,
                 registry: Optional[MemoryRegistry] = None,
                 transport: Optional[Callable[[Mapping[str, Any]], Any]] = None,
                 now: Optional[str] = None) -> None:
        self.decision = decision
        self.ctx = ctx
        self.lifecycle = lifecycle
        self.registry = registry if registry is not None else MemoryRegistry()
        self.transport = transport
        self.now = now or _now_iso()

    # ── the claim protocol, tolerant of a registry that lacks it ──────
    def _reserve(self, decision_hash_: str) -> bool:
        fn = getattr(self.registry, "reserve", None)
        if fn is None:
            return True          # a registry without a claim cannot refuse one
        try:
            return bool(fn(decision_hash_))
        except Exception:
            # A registry that cannot answer must not be read as "go ahead".
            return False

    def _confirm(self, decision_hash_: str) -> None:
        fn = getattr(self.registry, "confirm", None)
        if fn is not None:
            try:
                fn(decision_hash_)
            except Exception:
                pass

    def _release(self, decision_hash_: str) -> None:
        fn = getattr(self.registry, "release", None)
        if fn is not None:
            try:
                fn(decision_hash_)
            except Exception:
                pass

    # ── Phase 1 · validation ──────────────────────────────────────────
    def validate(self) -> Dict[str, Any]:
        """A decision must be complete, intact, of a known version, and fresh.

        The hash check is the one that matters most: a record altered since it
        was made must never be broadcast as though it were current, and it is
        the only failure here that cannot be spotted by reading the message.
        """
        d = self.decision
        if d is None:
            return {"ok": False, "state": BLOCKED,
                    "why": "no entry decision supplied"}
        for attr in ("id", "created_at", "hash", "version", "state"):
            if not getattr(d, attr, None):
                return {"ok": False, "state": BLOCKED,
                        "why": f"decision is missing `{attr}`"}
        if not d.verify():
            return {"ok": False, "state": BLOCKED,
                    "why": "decision hash does not verify — the record was "
                           "altered after it was made"}
        if d.version not in SUPPORTED_DECISION_VERSIONS:
            return {"ok": False, "state": BLOCKED,
                    "why": f"decision version {d.version} is not supported "
                           f"(this dispatcher understands "
                           f"{', '.join(SUPPORTED_DECISION_VERSIONS)})"}

        made, now = _parse_iso(d.created_at), _parse_iso(self.now)
        if made is None or now is None:
            return {"ok": False, "state": BLOCKED,
                    "why": "decision timestamp is unreadable"}
        age = (now - made).total_seconds()
        if age > MAX_AGE_SECONDS:
            return {"ok": False, "state": EXPIRED,
                    "why": f"decision is {age:.0f}s old — the tape has moved"}
        return {"ok": True, "state": READY, "why": "decision is valid",
                "age": age}

    # ── Phase 2 · duplicates ──────────────────────────────────────────
    @property
    def signature(self) -> str:
        """This decision's SIGNAL identity — stable across cycles."""
        return decision_signature(self.decision) if self.decision else ""

    # ── reading signatures from ANY registry ──────────────────────────
    # The registry protocol is three methods — `record`, `rows`, `sent_hashes`
    # — and a Supabase-backed implementation the app injects satisfies exactly
    # those. `sent_signatures()` is a convenience on `MemoryRegistry`, so it
    # must never be *required*: deriving from `rows()` keeps every existing
    # registry working, including one written before signatures existed.
    def _sent_signatures(self) -> Tuple[str, ...]:
        got = getattr(self.registry, "sent_signatures", None)
        if callable(got):
            try:
                return tuple(got())
            except Exception:
                pass
        try:
            return tuple(getattr(r, "signature", "") for r in self.registry.rows()
                         if getattr(r, "status", None) == DELIVERED
                         and getattr(r, "signature", ""))
        except Exception:
            return ()

    def _last_sent_at(self, signature: str) -> Optional[str]:
        got = getattr(self.registry, "last_sent_at", None)
        if callable(got):
            try:
                return got(signature)
            except Exception:
                pass
        try:
            for row in reversed(list(self.registry.rows())):
                if (getattr(row, "signature", "") == signature
                        and getattr(row, "status", None) == DELIVERED):
                    return getattr(row, "created_at", None)
        except Exception:
            pass
        return None

    def duplicate(self) -> Dict[str, Any]:
        """The same SIGNAL never goes out twice.

        ⚠️ This used to compare `decision.hash` only, and that check could never
        fire: the hash covers `id` (a fresh uuid4) and `created_at` (a fresh
        timestamp), so every cycle produced a brand-new hash for an identical
        setup. The signature comparison is the one that actually works; the
        hash checks are kept because they are still correct, just insufficient.
        """
        d = self.decision
        # `getattr` rather than an isinstance check: a caller handing junk gets
        # BLOCKED from `validate()`, and this must still answer rather than
        # raising out of the metadata block three phases later.
        if getattr(d, "hash", None) is None:
            return {"duplicate": False, "why": "nothing to compare"}

        sig = self.signature
        if sig and sig in self._sent_signatures():
            return {"duplicate": True,
                    "why": "this signal has already been sent — same state, "
                           "side, strike, entry, stop and zone"}
        if d.hash in self.registry.sent_hashes():
            return {"duplicate": True,
                    "why": "this exact decision has already been dispatched"}
        if self.registry.last_dispatched_hash == d.hash:
            return {"duplicate": True,
                    "why": "this decision is the last one dispatched"}
        return {"duplicate": False, "why": "not seen before"}

    # ── Phase 2b · the cooldown ───────────────────────────────────────
    def cooldown(self) -> Dict[str, Any]:
        """Not too soon after the last message about this same signal.

        The duplicate gate catches an identical signature. This catches the
        near-identical one — the same side and strike re-arming a few points
        away, which reads as the same idea arriving twice.
        """
        sig = self.signature
        if not sig:
            return {"blocked": False, "why": "no signature to compare"}
        last = self._last_sent_at(sig)
        if not last:
            return {"blocked": False, "why": "this signal has not been sent"}
        then, mine = _parse_iso(last), _parse_iso(self.now)
        if then is None or mine is None:
            return {"blocked": False, "why": "no timestamp to compare"}
        age = (mine - then).total_seconds()
        if age < COOLDOWN_SECONDS:
            return {"blocked": True,
                    "why": f"the same signal went out {age:.0f}s ago — "
                           f"cooling down for {COOLDOWN_SECONDS}s"}
        return {"blocked": False,
                "why": f"last sent {age:.0f}s ago, past the cooldown"}

    # ── Phase 3 · supersession ────────────────────────────────────────
    def superseded(self) -> Dict[str, Any]:
        """Only the newest valid decision survives.

        Compared on the decision's **own** `created_at`, not on dispatch time: a
        decision that was slow to reach this stage is still the older decision,
        and sending it after a newer one would contradict the last message with
        stale reasoning.
        """
        d = self.decision
        if getattr(d, "created_at", None) is None:
            return {"superseded": False, "why": "nothing to compare"}
        mine = _parse_iso(d.created_at)
        if mine is None:
            return {"superseded": False, "why": "no timestamp to compare"}
        for row in self.registry.rows():
            if row.decision_id == d.id or row.status != DELIVERED:
                continue
            theirs = _parse_iso(row.created_at)
            if theirs is not None and theirs > mine:
                return {"superseded": True,
                        "why": f"a newer decision was dispatched at "
                               f"{row.created_at}"}
        return {"superseded": False, "why": "this is the newest decision"}

    # ── Phase 4 · the gates ───────────────────────────────────────────
    def gates(self) -> Dict[str, Any]:
        """The whole product. Everything above feeds one verdict here."""
        valid = self.validate()
        if not valid["ok"]:
            return {"state": valid["state"], "why": valid["why"],
                    "duplicate": False}

        # Supersession is checked BEFORE the duplicate gate. Both block, so the
        # only thing at stake is the reason a reader is given — and "a newer
        # decision already went out" is strictly more informative than "we have
        # seen this before". It also matters more often now: an older decision
        # arriving late usually carries the SAME signature as the newer one that
        # beat it, so a signature-first order would report every one of them as
        # a duplicate and hide the fact that the tape had moved.
        sup = self.superseded()
        if sup["superseded"]:
            return {"state": SUPERSEDED, "why": sup["why"], "duplicate": False}

        dup = self.duplicate()
        if dup["duplicate"]:
            return {"state": DUPLICATE, "why": dup["why"], "duplicate": True}

        cool = self.cooldown()
        if cool["blocked"]:
            return {"state": COOLDOWN, "why": cool["why"], "duplicate": False}

        d = self.decision
        if d.confidence is UNKNOWN or d.confidence == UNKNOWN:
            return {"state": WAIT, "duplicate": False,
                    "why": "decision confidence is UNKNOWN — nothing worth "
                           "broadcasting"}

        action = getattr(self.lifecycle, "action", None)
        if d.state not in SENDABLE_STATES and action not in SENDABLE_ACTIONS:
            return {"state": WAIT, "duplicate": False,
                    "why": f"{d.state} is the engine working correctly — "
                           f"saying so every cycle trains the reader to mute "
                           f"the channel"}
        return {"state": READY, "duplicate": False,
                "why": f"{d.state} is worth sending"}

    # ── Phase 5 · assembly ────────────────────────────────────────────
    def payload(self) -> Mapping[str, Any]:
        """Stage 72's payload, **enriched with identity and nothing else**.

        The wording is not this stage's to change. Where a lifecycle decision is
        present its action is attached alongside — not merged into — the entry
        payload, so a reader can always tell which stage said what.

        Stage 71.85's seven fields arrive already in `decision.telegram` (72.1)
        and travel through the copy below untouched. That is the whole of this
        stage's Stage 71.85 change: a payload extension, carried, with no
        dispatch logic reading or reacting to any of it.
        """
        base = dict(getattr(self.decision, "telegram", {}) or {})
        base.update({
            "dispatch_version": VERSION,
            "dispatched_at": self.now,
            "decision_id": getattr(self.decision, "id", None),
            "decision_hash": getattr(self.decision, "hash", None),
            "decision_version": getattr(self.decision, "version", None),
        })
        if self.lifecycle is not None:
            base["lifecycle"] = MappingProxyType({
                "id": self.lifecycle.id,
                "action": self.lifecycle.action,
                "state": self.lifecycle.state,
                "health": self.lifecycle.health,
                "exit_reason": self.lifecycle.exit_reason,
            })
        return MappingProxyType(base)

    # ── Phase 6 · 7 · delivery ────────────────────────────────────────
    def deliver(self, payload: Mapping[str, Any],
                edits: Optional[str]) -> Dict[str, Any]:
        """Hand the payload to the injected transport and read the result.

        A transport that raises, returns nothing, or returns something this
        stage does not understand yields `UNKNOWN` — **never** `SENT`. A message
        assumed delivered is a duplicate waiting to happen, because the next
        cycle will see the hash recorded and stay quiet.
        """
        if self.transport is None:
            return {"telegram_state": NOT_SENT, "message_id": None,
                    "chat_id": None,
                    "why": "no transport supplied — dispatch decided, nothing "
                           "sent"}
        try:
            result = self.transport(payload, edits) if edits else \
                self.transport(payload)
        except Exception as err:            # a broken transport is not a send
            return {"telegram_state": DELIVERY_FAILED, "message_id": None,
                    "chat_id": None, "why": f"transport raised: {err}"}

        if isinstance(result, Mapping):
            state = str(result.get("status") or result.get("state") or "")
            if state.upper() in (RATE_LIMIT, "RATE_LIMITED", "429"):
                return {"telegram_state": RATE_LIMIT, "message_id": None,
                        "chat_id": result.get("chat_id"),
                        "why": "rate limited — retry later"}
            if state.upper() == RETRY:
                return {"telegram_state": RETRY, "message_id": None,
                        "chat_id": result.get("chat_id"),
                        "why": "transport asked for a retry"}
            if state.lower() in _TRANSPORT_OK or result.get("ok") is True:
                return {"telegram_state": DELIVERED,
                        "message_id": str(result.get("message_id") or "") or None,
                        "chat_id": result.get("chat_id"),
                        "why": "delivered"}
            return {"telegram_state": DELIVERY_FAILED, "message_id": None,
                    "chat_id": result.get("chat_id"),
                    "why": f"transport reported {state or 'a failure'}"}
        if result in _TRANSPORT_OK:
            return {"telegram_state": DELIVERED, "message_id": None,
                    "chat_id": None, "why": "delivered"}
        return {"telegram_state": UNKNOWN, "message_id": None, "chat_id": None,
                "why": "transport returned something this stage cannot read — "
                       "not assuming it went out"}

    # ── run ───────────────────────────────────────────────────────────
    def run(self) -> DispatchDecision:
        """The whole stage. Always returns a decision, never raises."""
        gate = self.gates()
        state = gate["state"]
        should_send = state == READY
        payload = self.payload()

        decision_id = str(getattr(self.decision, "id", "") or "")
        decision_hash_ = str(getattr(self.decision, "hash", "") or "")
        # ⚠️ The claim is keyed on the SIGNATURE, not the decision hash.
        # Keyed on the hash it was decoration: a per-cycle-unique key means
        # every caller wins its own claim and no two callers ever contend, so
        # the protocol that exists to stop two instances sending the same
        # message could not stop anything.
        claim_key = self.signature or decision_hash_

        # An update to a trade already announced EDITS the live message rather
        # than posting a second one that reads like a new signal.
        live = (self.registry.live_message(decision_id)
                if decision_id and self.lifecycle is not None else None)
        edits = live.telegram_message_id if live else None

        delivery = {"telegram_state": NOT_SENT, "message_id": None,
                    "chat_id": None, "why": "gates did not open"}
        latency_ms = None
        claimed = False

        if should_send:
            # ── the claim ─────────────────────────────────────────────
            # Checking "have I sent this?" and then sending is two operations
            # with a gap between them, and two instances starting together both
            # pass the check before either sends. `reserve()` closes the gap;
            # in Supabase it is a unique index doing the work.
            claimed = self._reserve(claim_key)
            if not claimed:
                state, should_send = DUPLICATE, False
                gate = {**gate, "duplicate": True,
                        "why": "another dispatcher holds the claim on this "
                               "decision — one message, not two"}
            else:
                started = _perf()
                delivery = self.deliver(payload, edits)
                latency_ms = round((_perf() - started) * 1000.0, 2)
                if delivery["telegram_state"] == DELIVERED:
                    state = SENT
                    self._confirm(claim_key)
                else:
                    # A failure must not poison the hash — the message never
                    # went out, so a retry has to remain possible.
                    self._release(claim_key)
                    if delivery["telegram_state"] in (DELIVERY_FAILED, UNKNOWN):
                        state = FAILED

        dispatch_id = str(uuid.uuid4())
        digest = dispatch_hash(dispatch_id, decision_id, VERSION, state,
                               self.now)

        # Phase 8 — append. A decision that was READY and then SENT is two
        # rows, so the history says what happened rather than only where it
        # ended.
        record = DispatchRecord(
            decision_id=decision_id, decision_hash=decision_hash_,
            dispatch_state=state, created_at=self.now,
            telegram_message_id=delivery["message_id"],
            chat_id=delivery["chat_id"],
            status=delivery["telegram_state"],
            signature=self.signature)
        self.registry.record(record)

        meta = MappingProxyType({
            "version": VERSION,
            "gate_reason": gate["why"],
            "delivery_reason": delivery["why"],
            "validation": self.validate()["why"],
            "duplicate_check": self.duplicate()["why"],
            "supersession_check": self.superseded()["why"],
            "edited": bool(edits),
            "supported_versions": SUPPORTED_DECISION_VERSIONS,
            "max_age_seconds": MAX_AGE_SECONDS,
            "transport_present": self.transport is not None,
            "cache": MappingProxyType({
                "last_dispatched_hash": self.registry.last_dispatched_hash,
                "last_dispatched_id": self.registry.last_dispatched_id,
                "last_dispatch_time": self.registry.last_dispatch_time,
            }),
            "entry_state": getattr(self.decision, "state", UNKNOWN),
            "lifecycle_action": getattr(self.lifecycle, "action", None),
            "latency_ms": latency_ms,
            "claimed": claimed,
            "contract_version": CONTRACT_VERSION,
            "status": STATUS,
        })

        return DispatchDecision(
            dispatch_state=state, dispatch_reason=gate["why"],
            telegram_state=delivery["telegram_state"],
            duplicate=bool(gate["duplicate"]), should_send=should_send,
            payload=payload, edits=edits, record=record, metadata=meta,
            id=dispatch_id, decision_id=decision_id, created_at=self.now,
            hash=digest)


def run(decision: Optional[EntryDecision] = None,
        ctx: Optional[TradingContext] = None,
        **kwargs: Any) -> DispatchDecision:
    """Convenience: `dispatcher.run(decision, ctx, registry=…, transport=…)`."""
    return Dispatcher(decision, ctx, **kwargs).run()
