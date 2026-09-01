"""Stage 72.9 — the Decision Dispatcher & Telegram Orchestrator.

The single gateway. These guard the four things a dispatcher can get wrong in
public: a duplicate storm, a contradictory pair, a stale broadcast, and a
message assumed sent that never went.
"""

import ast
import dataclasses
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from mios_v5 import dispatcher as DP
from mios_v5 import entry_engine as EE
from mios_v5 import trade_lifecycle as TL
from mios_v5 import trading_context as TC
from mios_v5.tests.test_entry_engine import _ctx, _fr, _matrix, _validation


class _Transport:
    """A recording stand-in. The dispatcher never learns what is behind it."""

    def __init__(self, result=None, raises=False):
        self.calls = []
        self.result = result if result is not None else {
            "status": "ok", "message_id": "555", "chat_id": "-100"}
        self.raises = raises

    def __call__(self, payload, edits=None):
        self.calls.append({"payload": payload, "edits": edits})
        if self.raises:
            raise RuntimeError("network down")
        return self.result


def _entry(**over):
    return EE.EntryEngine(_ctx(**over)).run()


def _dispatch(decision=None, transport=None, registry=None, **kw):
    return DP.Dispatcher(decision if decision is not None else _entry(),
                         _ctx(), registry=registry or DP.MemoryRegistry(),
                         transport=transport, **kw).run()


# ══════════════════════════════════════════════════════════════════════
#  1 · exactly one gateway, and it holds no socket
# ══════════════════════════════════════════════════════════════════════

def test_it_imports_no_network_or_database_client():
    """`import requests` inside `mios_v5` is a named forbidden failure mode.
    The transport and the registry are injected instead."""
    tree = ast.parse(pathlib.Path(DP.__file__).read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    banned = {"requests", "httpx", "urllib", "socket", "supabase", "telegram",
              "streamlit", "psycopg2", "numpy", "pandas"}
    assert not (imported & banned), imported & banned


def test_it_imports_only_the_three_upstream_contracts():
    tree = ast.parse(pathlib.Path(DP.__file__).read_text())
    local = {n.module for n in ast.walk(tree)
             if isinstance(n, ast.ImportFrom) and n.level}
    assert local == {"entry_engine", "trade_lifecycle", "trading_context"}


def test_no_other_mios_module_accepts_a_transport():
    """The "exactly one gateway" guarantee, asserted rather than documented.

    Checked on parameter names and attribute assignments, not on the word: the
    context's docstring says values are "transported" and the dashboard has a
    "transport controls" comment, neither of which is a socket. This is the
    fifth guard in this stack to need the distinction."""
    root = pathlib.Path(DP.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "dispatcher.py" or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = {a.arg for a in node.args.args + node.args.kwonlyargs}
                if names & {"transport", "sender", "telegram_client"}:
                    offenders.append(f"{path.name}::{node.name}")
            if isinstance(node, ast.Attribute) and node.attr in (
                    "sendMessage", "send_message", "editMessageText"):
                offenders.append(f"{path.name}::{node.attr}")
    assert not offenders, offenders


def test_stage_72_and_73_cannot_send():
    for module in (EE, TL):
        tree = ast.parse(pathlib.Path(module.__file__).read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert not (imported & {"requests", "telegram", "httpx", "urllib"})


def test_with_no_transport_it_decides_but_sends_nothing():
    d = _dispatch(transport=None)
    assert d.should_send is True
    assert d.telegram_state == DP.NOT_SENT
    assert "no transport" in d.metadata["delivery_reason"]


# ══════════════════════════════════════════════════════════════════════
#  2 · duplicates
# ══════════════════════════════════════════════════════════════════════

def test_the_same_decision_twice_sends_once():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    first = _dispatch(d, tx, reg)
    second = _dispatch(d, tx, reg)
    assert first.dispatch_state == DP.SENT
    assert second.dispatch_state == DP.DUPLICATE
    assert second.duplicate is True and second.should_send is False
    assert len(tx.calls) == 1


def test_a_genuinely_different_signal_sends():
    """"Different" now means a different SIGNAL, not a different object.

    This used to vary `stability` only, and passed — because the gate compared
    `decision.hash`, which is unique every cycle by construction, so *anything*
    counted as new. That is the bug that put the same message on the phone on
    every refresh. Changing the side is what a reader would call a new signal;
    a stability field moving underneath an identical ticket is not.
    """
    reg, tx = DP.MemoryRegistry(), _Transport()
    other = _validation()
    other["selected"] = {"CALL": 24300.0, "PUT": 24300.0}
    other["bridge"]["selected_strike"] = {"CALL": 24300.0, "PUT": 24300.0}
    _dispatch(_entry(), tx, reg)
    _dispatch(_entry(validation=other), tx, reg)
    assert len(tx.calls) == 2


def test_the_same_setup_does_not_resend_every_cycle():
    """⭐ The reported bug, as a test.

    Stage 72 re-runs each cycle and mints a fresh `id` and `created_at` every
    time, so `decision.hash` differs even when nothing about the trade does.
    Ten cycles over one unchanged setup must produce exactly one message."""
    reg, tx = DP.MemoryRegistry(), _Transport()
    states = [_dispatch(_entry(), tx, reg).dispatch_state for _ in range(10)]
    assert len(tx.calls) == 1, f"sent {len(tx.calls)} times: {states}"
    assert states[0] == DP.SENT
    assert set(states[1:]) <= {DP.DUPLICATE, DP.COOLDOWN, DP.SUPERSEDED}


def test_the_signature_ignores_the_fields_that_change_every_cycle():
    """It must not cover `id`, `created_at`, or a score that ticks 80 → 81 —
    each of those would restore the bug, the last one just more slowly."""
    a, b = _entry(), _entry()
    assert a.hash != b.hash, "the premise: the decision hash is per-cycle"
    assert DP.decision_signature(a) == DP.decision_signature(b)
    for field in ("id", "created_at", "score", "confidence"):
        assert field not in DP.SIGNATURE_FIELDS


def test_sent_is_terminal_for_a_hash():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    _dispatch(d, tx, reg)
    for _ in range(5):
        assert _dispatch(d, tx, reg).dispatch_state == DP.DUPLICATE
    assert len(tx.calls) == 1


# ══════════════════════════════════════════════════════════════════════
#  3 · supersession
# ══════════════════════════════════════════════════════════════════════

def test_an_older_decision_after_a_newer_one_is_superseded():
    """Sending it would contradict the last message with stale reasoning."""
    reg, tx = DP.MemoryRegistry(), _Transport()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    older = dataclasses.replace(_entry(),
                                created_at=(now - timedelta(seconds=60)).isoformat())
    newer = dataclasses.replace(_entry(fr=_fr(stability="RECOVERY")),
                                created_at=now.isoformat())
    # re-hash so both still verify
    older = dataclasses.replace(older, hash=EE.decision_hash(
        older.id, older.version, older.state, older.confidence, older.score,
        older.created_at))
    newer = dataclasses.replace(newer, hash=EE.decision_hash(
        newer.id, newer.version, newer.state, newer.confidence, newer.score,
        newer.created_at))

    assert _dispatch(newer, tx, reg, now=now.isoformat()).dispatch_state == DP.SENT
    late = _dispatch(older, tx, reg, now=now.isoformat())
    assert late.dispatch_state == DP.SUPERSEDED
    assert late.should_send is False
    assert len(tx.calls) == 1


def test_supersession_compares_the_decisions_own_timestamp():
    src = pathlib.Path(DP.__file__).read_text()
    assert "created_at" in src
    assert _dispatch().metadata["supersession_check"]


# ══════════════════════════════════════════════════════════════════════
#  4 · validation
# ══════════════════════════════════════════════════════════════════════

def test_a_hash_mismatch_is_blocked():
    """A record altered since it was made must never be broadcast as current."""
    tx = _Transport()
    tampered = dataclasses.replace(_entry(), state="ENTER", confidence=999)
    out = _dispatch(tampered, tx)
    assert out.dispatch_state == DP.BLOCKED
    assert "altered" in out.dispatch_reason
    assert not tx.calls


def test_an_unsupported_version_is_blocked():
    tx = _Transport()
    d = dataclasses.replace(_entry(), version="99.0")
    d = dataclasses.replace(d, hash=EE.decision_hash(
        d.id, d.version, d.state, d.confidence, d.score, d.created_at))
    out = _dispatch(d, tx)
    assert out.dispatch_state == DP.BLOCKED
    assert "not supported" in out.dispatch_reason
    assert not tx.calls


def test_a_missing_decision_is_blocked():
    out = DP.Dispatcher(None, _ctx(), transport=_Transport()).run()
    assert out.dispatch_state == DP.BLOCKED


def test_a_stale_decision_expires():
    tx = _Transport()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    old = dataclasses.replace(_entry(),
                              created_at=(now - timedelta(seconds=600)).isoformat())
    old = dataclasses.replace(old, hash=EE.decision_hash(
        old.id, old.version, old.state, old.confidence, old.score,
        old.created_at))
    out = _dispatch(old, tx, now=now.isoformat())
    assert out.dispatch_state == DP.EXPIRED
    assert not tx.calls


# ══════════════════════════════════════════════════════════════════════
#  5 · gates
# ══════════════════════════════════════════════════════════════════════

def test_a_wait_decision_is_not_broadcast():
    """WAIT is the engine working correctly; saying so every cycle trains the
    reader to mute the channel."""
    tx = _Transport()
    waiting = _entry(matrix=_matrix(intel={"timing": {"timing": "MISSED"}}))
    assert waiting.state == "WAIT"
    out = _dispatch(waiting, tx)
    assert out.dispatch_state == DP.WAIT and not tx.calls


def test_an_abort_is_broadcast():
    tx = _Transport()
    out = _dispatch(_entry(fr=_fr(stability="SHOCK")), tx)
    assert out.dispatch_state == DP.SENT and len(tx.calls) == 1


def test_the_gate_ladder_validates_before_it_deduplicates():
    """A duplicate check that ran first would let an altered record suppress a
    legitimate one."""
    reg, tx = DP.MemoryRegistry(), _Transport()
    good = _entry()
    _dispatch(good, tx, reg)
    tampered = dataclasses.replace(good, confidence=999)
    assert _dispatch(tampered, tx, reg).dispatch_state == DP.BLOCKED


# ══════════════════════════════════════════════════════════════════════
#  6 · delivery results
# ══════════════════════════════════════════════════════════════════════

def test_a_raising_transport_is_failed_not_sent():
    out = _dispatch(transport=_Transport(raises=True))
    assert out.telegram_state == DP.DELIVERY_FAILED
    assert out.dispatch_state == DP.FAILED


def test_an_unreadable_transport_result_is_never_assumed_sent():
    """A message assumed delivered is a duplicate waiting to happen."""
    out = _dispatch(transport=_Transport(result=object()))
    assert out.telegram_state == TC.UNKNOWN
    assert out.dispatch_state == DP.FAILED
    assert "not assuming" in out.metadata["delivery_reason"]


def test_rate_limit_and_retry_are_reported_not_swallowed():
    for status, want in (("RATE_LIMIT", DP.RATE_LIMIT), ("RETRY", DP.RETRY)):
        out = _dispatch(transport=_Transport(result={"status": status}))
        assert out.telegram_state == want


def test_a_failed_send_does_not_suppress_the_next_attempt():
    """A failure must not poison the hash — the message never went out."""
    reg = DP.MemoryRegistry()
    _dispatch(_entry(), _Transport(raises=True), reg)
    good = _Transport()
    assert _dispatch(_entry(), good, reg).dispatch_state == DP.SENT
    assert len(good.calls) == 1


# ══════════════════════════════════════════════════════════════════════
#  7 · payload
# ══════════════════════════════════════════════════════════════════════

def test_the_payload_wording_is_stage_72s_and_is_not_rewritten():
    d = _entry()
    out = _dispatch(d, _Transport())
    for key, value in dict(d.telegram).items():
        assert out.payload[key] == value, key


def test_only_identity_keys_are_added():
    d = _entry()
    added = set(out_keys := set(_dispatch(d, _Transport()).payload)) - set(d.telegram)
    assert added <= {"dispatch_version", "dispatched_at", "decision_id",
                     "decision_hash", "decision_version", "lifecycle"}
    assert "decision_id" in out_keys


def test_a_lifecycle_is_attached_alongside_not_merged_in():
    """A reader must always be able to tell which stage said what."""
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    lc = TL.TradeLifecycle(d, ctx).run()
    out = DP.Dispatcher(d, ctx, lifecycle=lc, transport=_Transport()).run()
    assert out.payload["lifecycle"]["action"] == lc.action
    assert out.payload["state"] == d.telegram["state"]


# ══════════════════════════════════════════════════════════════════════
#  8 · editing beats re-sending
# ══════════════════════════════════════════════════════════════════════

def test_a_lifecycle_update_edits_the_live_message():
    """ENTER → EXIT updates one message instead of posting two signals."""
    reg, tx = DP.MemoryRegistry(), _Transport()
    ctx = _ctx()
    d = EE.EntryEngine(ctx).run()
    DP.Dispatcher(d, ctx, registry=reg, transport=tx).run()
    assert tx.calls[0]["edits"] is None

    lc = TL.TradeLifecycle(d, _ctx(validation=_validation(liquidity="Disagree"))).run()
    newer = dataclasses.replace(d, confidence=(d.confidence or 0))
    out = DP.Dispatcher(newer, ctx, lifecycle=lc, registry=reg,
                        transport=tx).run()
    assert out.edits == "555"
    assert out.metadata["edited"] is True


def test_without_a_lifecycle_there_is_nothing_to_edit():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run()
    assert DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run().edits is None


# ══════════════════════════════════════════════════════════════════════
#  9 · history and cache
# ══════════════════════════════════════════════════════════════════════

def test_history_is_appended_never_overwritten():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    _dispatch(d, tx, reg)
    _dispatch(d, tx, reg)
    rows = reg.rows()
    assert len(rows) == 2
    assert rows[0].dispatch_state == DP.SENT
    assert rows[1].dispatch_state == DP.DUPLICATE


def test_every_dispatch_writes_a_row_even_when_blocked():
    reg = DP.MemoryRegistry()
    _dispatch(dataclasses.replace(_entry(), confidence=999), _Transport(), reg)
    assert len(reg.rows()) == 1
    assert reg.rows()[0].dispatch_state == DP.BLOCKED


def test_the_record_carries_the_message_id_for_a_later_edit():
    reg, tx = DP.MemoryRegistry(), _Transport()
    out = _dispatch(_entry(), tx, reg)
    assert out.record.telegram_message_id == "555"
    assert out.record.chat_id == "-100"
    assert reg.live_message(out.decision_id).telegram_message_id == "555"


def test_the_cache_tracks_the_last_dispatch():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    out = _dispatch(d, tx, reg)
    cache = dict(out.metadata["cache"])
    assert cache["last_dispatched_hash"] == d.hash
    assert cache["last_dispatched_id"] == d.id
    assert cache["last_dispatch_time"]


def test_the_cache_is_empty_before_anything_is_sent():
    reg = DP.MemoryRegistry()
    assert reg.last_dispatched_hash is None
    assert reg.last_dispatched_id is None


def test_the_migration_exists_and_guarantees_one_send_per_hash():
    sql = (pathlib.Path(DP.__file__).resolve().parents[1] / "sql" /
           "031_dispatch_history.sql").read_text()
    for col in ("decision_id", "decision_hash", "telegram_message_id",
                "chat_id", "status", "created_at", "updated_at"):
        assert col in sql, col
    assert "UNIQUE INDEX" in sql and "status = 'SENT'" in sql


# ══════════════════════════════════════════════════════════════════════
#  10 · identity, immutability, contracts
# ══════════════════════════════════════════════════════════════════════

def test_the_dispatch_decision_is_immutable():
    out = _dispatch()
    assert out.__dataclass_params__.frozen is True
    for attr in ("dispatch_state", "id", "hash", "created_at"):
        with pytest.raises(Exception):
            setattr(out, attr, "x")
    with pytest.raises(Exception):
        out.payload["state"] = "ENTER"


def test_identity_and_hash():
    out = _dispatch()
    assert out.id and out.created_at and out.hash
    assert out.version == "72.9"
    assert out.verify() is True
    assert dataclasses.replace(out, dispatch_state=DP.WAIT).verify() is False


def test_the_hash_is_deterministic():
    args = ("d-1", "e-1", "72.9", "SENT", "2026-07-30T10:00:00+00:00")
    assert DP.dispatch_hash(*args) == DP.dispatch_hash(*args)


def test_every_dispatch_state_is_declared():
    for over in ({}, {"fr": _fr(stability="SHOCK")},
                 {"matrix": _matrix(intel={"timing": {"timing": "MISSED"}})}):
        assert _dispatch(_entry(**over), _Transport()).dispatch_state \
            in DP.DISPATCH_STATES


def test_it_serialises_cleanly():
    back = json.loads(json.dumps(_dispatch(transport=_Transport()).to_dict(),
                                 default=str))
    assert back["version"] == "72.9"
    assert back["record"]["decision_hash"]


def test_it_never_raises_on_junk():
    for junk in (None, "nonsense", 7):
        out = DP.Dispatcher(junk, None, transport=_Transport()).run()
        assert out.dispatch_state in DP.DISPATCH_STATES


def test_the_docs_exist():
    docs = pathlib.Path(DP.__file__).resolve().parents[1] / "docs"
    for name in ("AUDIT_STAGE_72_9_DISPATCHER.md",
                 "STAGE72_9_OUTPUT_CONTRACT.md",
                 "STAGE72_9_FROZEN_PLAN.md"):
        assert (docs / name).exists(), name


# ══════════════════════════════════════════════════════════════════════
#  11 · the claim protocol — Phase 1 · 2
# ══════════════════════════════════════════════════════════════════════

def test_reserve_is_won_by_exactly_one_caller():
    """Checking "have I sent this?" then sending is two operations with a gap.
    Two instances starting together both pass the check before either sends."""
    reg = DP.MemoryRegistry()
    assert reg.reserve("h1") is True
    assert reg.reserve("h1") is False
    reg.release("h1")
    assert reg.reserve("h1") is True


def test_concurrent_instances_produce_one_message():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    outs = [DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run()
            for _ in range(8)]
    assert len(tx.calls) == 1
    assert sum(1 for o in outs if o.dispatch_state == DP.SENT) == 1
    assert all(o.dispatch_state in (DP.SENT, DP.DUPLICATE) for o in outs)


def test_a_failed_send_releases_the_claim():
    """A failure must not poison the hash — the message never went out."""
    reg = DP.MemoryRegistry()
    d = _entry()
    DP.Dispatcher(d, _ctx(), registry=reg, transport=_Transport(raises=True)).run()
    good = _Transport()
    assert DP.Dispatcher(d, _ctx(), registry=reg,
                         transport=good).run().dispatch_state == DP.SENT
    assert len(good.calls) == 1


def test_a_registry_that_cannot_answer_never_sends():
    """A registry that raises must not be read as "go ahead"."""
    class _Broken(DP.MemoryRegistry):
        def reserve(self, decision_hash):
            raise RuntimeError("unreachable")

    tx = _Transport()
    out = DP.Dispatcher(_entry(), _ctx(), registry=_Broken(),
                        transport=tx).run()
    assert out.dispatch_state != DP.SENT
    assert not tx.calls


def test_a_registry_without_the_claim_protocol_still_works():
    """Backward compatible: a registry that cannot refuse a claim is trusted."""
    class _Old:
        def __init__(self):
            self._rows = []
        def record(self, row): self._rows.append(row)
        def rows(self): return tuple(self._rows)
        def sent_hashes(self): return ()
        last_dispatched_hash = None
        last_dispatched_id = None
        last_dispatch_time = None
        def live_message(self, did): return None

    tx = _Transport()
    assert DP.Dispatcher(_entry(), _ctx(), registry=_Old(),
                         transport=tx).run().dispatch_state == DP.SENT


def test_a_restart_re_reads_the_registry_rather_than_a_cache():
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run()
    # a "new process" — fresh Dispatcher objects, same registry
    for _ in range(5):
        assert DP.Dispatcher(d, _ctx(), registry=reg,
                             transport=tx).run().dispatch_state == DP.DUPLICATE
    assert len(tx.calls) == 1


def test_the_dispatcher_reads_no_cache_of_its_own():
    """The registry is the single source of truth — never memory, never
    session_state, never a cached hash held on the instance."""
    code = ast.parse(pathlib.Path(DP.__file__).read_text())
    for node in ast.walk(code):
        if isinstance(node, ast.Attribute) and node.attr in (
                "_cached_hash", "_last_hash", "session_state"):
            raise AssertionError(node.attr)


# ══════════════════════════════════════════════════════════════════════
#  12 · metrics and health — monitoring only
# ══════════════════════════════════════════════════════════════════════

def test_metrics_are_derived_from_the_registry():
    """A counter incremented alongside the rows is a second source of truth
    that drifts the first time a write fails halfway."""
    reg, tx = DP.MemoryRegistry(), _Transport()
    d = _entry()
    DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run()
    DP.Dispatcher(d, _ctx(), registry=reg, transport=tx).run()
    m = DP.metrics(reg, latencies=[12.0, 30.0])
    assert m.dispatch_count == 2 and m.success_count == 1
    assert m.duplicate_block_count == 1
    assert m.average_dispatch_latency_ms == 21.0
    assert m.maximum_dispatch_latency_ms == 30.0
    assert m.duplicate_percentage == 50.0


def test_metrics_on_an_empty_registry_are_none_not_zero():
    m = DP.metrics(DP.MemoryRegistry())
    assert m.dispatch_count == 0
    assert m.failure_percentage is None
    assert m.average_dispatch_latency_ms is None


def test_health_distinguishes_degraded_from_down():
    """An operator needs to tell "struggling" from "gone"; one number that
    collapses both is the number nobody acts on."""
    reg = DP.MemoryRegistry()
    now = DP._now_iso()
    assert DP.health(reg).status == "IDLE"

    reg.record(DP.DispatchRecord("d", "h", DP.SENT, now, "1", "-100",
                                 DP.DELIVERED))
    assert DP.health(reg).status == "OK"

    reg.record(DP.DispatchRecord("d2", "h2", DP.FAILED, now, None, None,
                                 DP.DELIVERY_FAILED))
    assert DP.health(reg).status == "DEGRADED"

    only_bad = DP.MemoryRegistry()
    only_bad.record(DP.DispatchRecord("d3", "h3", DP.FAILED, now, None, None,
                                      DP.DELIVERY_FAILED))
    assert DP.health(only_bad).status == "DOWN"


def test_health_reports_the_connections():
    reg = DP.MemoryRegistry()
    assert DP.health(reg, transport=None).telegram_connected is False
    assert DP.health(reg, transport=_Transport()).telegram_connected is True
    assert DP.health(reg).registry_connected is True


def test_the_dispatcher_never_reads_its_own_metrics():
    """A dispatch layer that throttled itself because its failure rate looked
    high would turn an outage into a silence — the worse of the two."""
    code = _code_only_dp()
    run_src = code[code.index("def run("):]
    for banned in ("metrics(", "health(", "failure_percentage"):
        assert banned not in run_src, banned


def _code_only_dp() -> str:
    tree = ast.parse(pathlib.Path(DP.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def test_latency_is_recorded_per_dispatch():
    out = _dispatch(transport=_Transport())
    assert out.metadata["latency_ms"] is not None
    assert out.metadata["latency_ms"] >= 0


# ══════════════════════════════════════════════════════════════════════
#  13 · version, status and the validation report
# ══════════════════════════════════════════════════════════════════════

def test_the_contract_version_and_status_are_declared():
    assert DP.CONTRACT_VERSION == "72.9.0"
    assert DP.STATUS in ("VALIDATED_SIMULATED", "FROZEN")
    assert _dispatch().metadata["contract_version"] == "72.9.0"


def test_the_status_is_not_frozen_until_live_validation_passes():
    """The freeze is gated on evidence, not on green tests. If STATUS is
    FROZEN, the report must say the live run passed."""
    from mios_v5.dispatch_validation import run_all
    if DP.STATUS == "FROZEN":
        assert run_all()["live"]["passed"] is True
    else:
        assert DP.STATUS == "VALIDATED_SIMULATED"


def test_the_validation_harness_passes_every_simulated_scenario():
    from mios_v5.dispatch_validation import run_all
    out = run_all()
    failed = [s["name"] for s in out["simulated"]["scenarios"]
              if not s["passed"]]
    assert not failed, failed
    assert out["simulated"]["passed"] is True


def test_the_harness_does_not_claim_live_validation():
    """A simulation cannot satisfy a live criterion, and the report must not
    imply it did."""
    from mios_v5.dispatch_validation import run_all
    out = run_all()
    assert out["live"]["passed"] is False
    assert out["live"]["dispatches"] == 0
    assert out["freeze_ready"] is False


def test_the_frozen_and_report_docs_exist():
    docs = pathlib.Path(DP.__file__).resolve().parents[1] / "docs"
    for name in ("STAGE72_9_FROZEN.md", "STAGE72_9_VALIDATION_REPORT.md"):
        assert (docs / name).exists(), name
    frozen = (docs / "STAGE72_9_FROZEN.md").read_text()
    for section in ("Purpose", "Architecture", "Registry Flow",
                    "Duplicate Protection", "Transport Rules",
                    "Failure Handling", "Operational Metrics",
                    "Acceptance Criteria", "Known Limitations",
                    "Extension Points", "Freezing Rules", "Version"):
        assert section in frozen, section


def _registry_source() -> ast.Module:
    """Parsed, not imported: `db/__init__` pulls in the Supabase SDK, which is
    a runtime dependency and not one the test suite should require. What is
    being asserted is structural anyway."""
    path = (pathlib.Path(DP.__file__).resolve().parents[1] / "db" /
            "dispatch_registry.py")
    assert path.exists(), path
    return ast.parse(path.read_text())


def test_the_supabase_registry_satisfies_the_protocol():
    """It must be droppable in where MemoryRegistry sits."""
    tree = _registry_source()
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)
               and n.name == "SupabaseDispatchRegistry")
    defined = {n.name for n in cls.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for name in ("reserve", "confirm", "release", "record", "rows",
                 "sent_hashes", "live_message", "last_dispatched_hash",
                 "last_dispatched_id", "last_dispatch_time"):
        assert name in defined, name
    # the three cache reads must be properties, matching MemoryRegistry
    props = {n.name for n in cls.body
             if isinstance(n, ast.FunctionDef)
             and any(getattr(d, "id", "") == "property"
                     for d in n.decorator_list)}
    assert {"last_dispatched_hash", "last_dispatched_id",
            "last_dispatch_time"} <= props


def test_the_registry_lives_outside_mios_v5_and_the_dispatcher_ignores_it():
    """`mios_v5` may not import a database client — the same rule that keeps
    the transport out. The dependency points one way only."""
    tree = ast.parse(pathlib.Path(DP.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", "") or ""
            names = {a.name for a in node.names}
            assert "dispatch_registry" not in mod
            assert not any("db" == n.split(".")[0] for n in names)


def test_the_supabase_registry_reserves_before_it_sends():
    """Send-then-record leaves a window where a crash produces a delivered
    message with no history row, and the next cycle sends it again."""
    src = (pathlib.Path(DP.__file__).resolve().parents[1] / "db" /
           "dispatch_registry.py").read_text()
    reserve = src[src.index("def reserve("):src.index("def confirm(")]
    assert "insert" in reserve and "SENT" in reserve or "DELIVERED" in reserve
