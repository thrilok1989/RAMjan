"""📨 Flow-at-level alerts: a leg's OWN volume BURST at the matching level, to the
alternate bot. Pure-logic tests — the spike detector, the band, the rising-edge
latch. No put-vs-call comparison (that was the corrected mistake).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from mios_v5 import flow_level_alerts as F

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _steady(rate, n=60, step=20.0, start_t=1000.0, start_v=0.0):
    """A cumulative-activity series accumulating at `rate` per second."""
    return [(start_t + i * step, start_v + rate * (i * step)) for i in range(n)]


# ── activity = buy + sell ─────────────────────────────────────────────

def test_activity_is_buy_plus_sell():
    assert F.activity(100, 40) == 140.0
    assert F.activity(100, None) == 100.0
    assert F.activity(None, None) is None


# ── the band is a fraction of spot ────────────────────────────────────

def test_at_level_uses_a_percentage_band():
    assert F.at_level(24000, 24050) is True          # 0.21%
    assert F.at_level(24000, 24100) is False         # 0.42%
    assert F.at_level(77700, 77850) is True          # 0.19%
    assert F.at_level(77700, 78100) is False         # 0.51%


# ── the spike detector: a leg vs ITS OWN normal ───────────────────────

def test_a_steady_leg_is_not_spiking():
    """Constant accumulation rate → recent rate == baseline → no spike."""
    s = _steady(rate=100.0, n=80)          # ~26 min of steady flow
    r = F.activity_spike(s, now=s[-1][0])
    assert r["spiking"] is False
    assert r["ratio"] is not None and r["ratio"] < F.SPIKE_MULT


def test_a_burst_in_the_recent_window_spikes():
    """Slow baseline, then a fast recent window → spike."""
    base = _steady(rate=50.0, n=60)                    # ~20 min slow
    t0, v0 = base[-1]
    burst = [(t0 + i * 20.0, v0 + 400.0 * (i * 20.0)) for i in range(1, 8)]  # 8× faster
    r = F.activity_spike(base + burst, now=(base + burst)[-1][0])
    assert r["spiking"] is True
    assert r["ratio"] >= F.SPIKE_MULT


def test_too_little_history_is_not_a_spike():
    """A burst needs a normal to stand out from."""
    assert F.activity_spike([(1000, 0), (1020, 500)])["spiking"] is False
    assert "history" in F.activity_spike([(1000, 0), (1020, 500)])["reason"]


def test_a_cumulative_reset_is_not_read_as_a_spike():
    """⚠️ When the ATM strike rolls, the aggregate cumulative can drop. A negative
    delta is clamped to zero, so a contract change never looks like a burst."""
    s = _steady(rate=100.0, n=60)
    t0, _v = s[-1]
    # cumulative collapses to near zero (new contract) then ticks up slowly
    reset = [(t0 + i * 20.0, 10.0 * (i * 20.0)) for i in range(1, 8)]
    r = F.activity_spike(s + reset, now=(s + reset)[-1][0])
    assert r["spiking"] is False


# ── the decision: burst AND on the matching level ─────────────────────

def _bursting(n_base=60):
    base = _steady(rate=50.0, n=n_base)
    t0, v0 = base[-1]
    burst = [(t0 + i * 20.0, v0 + 400.0 * (i * 20.0)) for i in range(1, 8)]
    return base + burst


def test_put_bursts_at_resistance_fires_that_event_only():
    put = _bursting()
    call = _steady(rate=50.0, n=67)          # steady, not bursting
    ev = F.assess(call, put, spot=24000, support=23500, resistance=24040,
                  now=put[-1][0])
    assert ev["put_at_resistance"]["active"] is True
    assert ev["call_at_support"]["active"] is False


def test_call_bursts_at_support_fires_that_event_only():
    call = _bursting()
    put = _steady(rate=50.0, n=67)
    ev = F.assess(call, put, spot=24000, support=24030, resistance=24600,
                  now=call[-1][0])
    assert ev["call_at_support"]["active"] is True
    assert ev["put_at_resistance"]["active"] is False


def test_a_burst_away_from_the_level_does_not_fire():
    put = _bursting()
    call = _steady(rate=50.0, n=67)
    ev = F.assess(call, put, spot=24000, support=23500, resistance=24500,
                  now=put[-1][0])                       # resistance far off
    assert ev["put_at_resistance"]["active"] is False
    assert ev["put_at_resistance"]["spiking"] is True
    assert ev["put_at_resistance"]["on_level"] is False


def test_on_the_level_but_steady_does_not_fire():
    steady = _steady(rate=80.0, n=67)
    ev = F.assess(steady, steady, spot=24000, support=23500, resistance=24030,
                  now=steady[-1][0])
    assert ev["put_at_resistance"]["active"] is False


def test_no_cross_leg_comparison_is_made():
    """⚠️ The corrected mistake. A call bursting must NOT make the put event fire,
    and a quiet other-leg must not suppress a real burst."""
    put = _bursting()
    call = _bursting()                        # both bursting
    ev = F.assess(call, put, spot=24000, support=23500, resistance=24040,
                  now=put[-1][0])
    # put at resistance fires on the PUT's own burst regardless of the call
    assert ev["put_at_resistance"]["active"] is True


# ── the rising-edge latch: anti-flood ─────────────────────────────────

def test_the_latch_fires_once_then_holds():
    st = None
    fired = []
    for i in range(5):
        f, st = F.latch(True, st, now=1000 + i, cooldown_s=0)
        fired.append(f)
    assert fired == [True, False, False, False, False]


def test_the_latch_rearms_after_the_condition_clears():
    st = None
    f, st = F.latch(True, st, now=1000, cooldown_s=0)
    assert f is True
    f, st = F.latch(False, st, now=1001, cooldown_s=0)
    f, st = F.latch(True, st, now=1002, cooldown_s=0)
    assert f is True


def test_the_cooldown_suppresses_a_chattering_edge():
    st = None
    f, st = F.latch(True, st, now=1000, cooldown_s=300)
    assert f is True
    f, st = F.latch(False, st, now=1010, cooldown_s=300)
    f, st = F.latch(True, st, now=1020, cooldown_s=300)     # within cooldown
    assert f is False
    f, st = F.latch(False, st, now=1330, cooldown_s=300)
    f, st = F.latch(True, st, now=1340, cooldown_s=300)     # cooldown elapsed
    assert f is True


# ── the message ───────────────────────────────────────────────────────

def test_the_message_names_the_leg_the_level_and_the_burst():
    info = {"spot": 77700, "level": 77820, "ratio": 3.4}
    msg = F.message("put_at_resistance", info,
                    call_label="ATM CE 77700", put_label="ATM PE 77700")
    assert "resistance" in msg and "ATM PE 77700" in msg
    assert "🔴" in msg and "🧱" in msg and "3.4×" in msg
    assert "spiking" in msg or "spik" in msg

    info2 = {"spot": 77700, "level": 77650, "ratio": 2.1}
    msg2 = F.message("call_at_support", info2,
                     call_label="ATM CE 77700", put_label="ATM PE 77700")
    assert "support" in msg2 and "ATM CE 77700" in msg2
    assert "🟢" in msg2 and "🛡" in msg2


# ── purity and wiring ─────────────────────────────────────────────────

def test_the_module_is_pure():
    src = (_ROOT / "mios_v5" / "flow_level_alerts.py").read_text()
    names = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            names |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            names.add(n.module.split(".")[0])
    assert not names & {"streamlit", "vob_minimal", "pandas", "requests"}


def test_junk_never_raises():
    for a in (None, "x", [], {}):
        F.assess(a, a, a, a, a)
        F.activity_spike(a)
        F.activity(a, a)
        F.at_level(a, a)
        F.latch(bool(a), a if isinstance(a, dict) else None, now=0.0)
        F.message("put_at_resistance", a if isinstance(a, dict) else {})


def test_it_goes_to_the_alternate_bot_reads_the_history_and_latches():
    src = (_ROOT / "vob_minimal.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_notify_flow_at_level")
    calls = {getattr(c.func, "attr", "") or getattr(c.func, "id", "")
             for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "send_telegram_alert_bot" in calls, "must use the alternate bot"
    assert "send_telegram_message_sync" not in calls, "not the main stream"
    consts = {n.value for n in ast.walk(fn)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_atm_flow_hist" in consts and "_flow_level_state" in consts
    assert "latch" in calls and "assess" in calls


def test_the_graph_stashes_the_history_and_the_dispatch_calls_the_alert():
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    graph = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "render_atm_cvd_graphs")
    gconsts = {n.value for n in ast.walk(graph)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "_atm_flow_hist" in gconsts, "the graph must publish the history"
    called = {c.func.id for c in ast.walk(tree)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_notify_flow_at_level" in called
