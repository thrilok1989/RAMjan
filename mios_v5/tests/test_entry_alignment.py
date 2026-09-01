"""Confluence entry alignment — the 4-signal reuse layer.

It must fire only when ALL of {NIFTY at level, ATM Strong verdict agreeing with
the level, the trade-side leg at its support, that side's energy the greater} are
true — and never when any one disagrees. It builds no engine; these tests pin the
alignment gate and the app wiring that feeds it from existing session objects.
"""

import ast
import pathlib

from mios_v5.entry_alignment import evaluate, leg_at_support, message

_ROOT = pathlib.Path(__file__).resolve().parents[2]


# ── the full bull / bear confluence ────────────────────────────────────

def test_full_bull_confluence_fires_buy_call():
    sig = evaluate(spot=24398, support=24400, resistance=24500,
                   atm_verdict="Strong Bullish", call_at_support=True,
                   put_at_support=False, call_energy=72, put_energy=40)
    assert sig and sig["side"] == "CALL" and sig["level"] == 24400
    assert sig["level_kind"] == "support"


def test_full_bear_confluence_fires_buy_put():
    sig = evaluate(spot=24502, support=24400, resistance=24500,
                   atm_verdict="Strong Bearish", put_at_support=True,
                   call_at_support=False, call_energy=30, put_energy=66)
    assert sig and sig["side"] == "PUT" and sig["level"] == 24500


# ── every single disagreement blocks it ────────────────────────────────

def test_verdict_must_agree_with_the_level():
    # at support but verdict is bearish → conflict, no fire
    assert evaluate(spot=24398, support=24400, atm_verdict="Strong Bearish",
                    call_at_support=True, call_energy=72, put_energy=40) is None
    # at resistance but bullish → conflict
    assert evaluate(spot=24502, resistance=24500, atm_verdict="Strong Bullish",
                    put_at_support=True, call_energy=40, put_energy=72) is None


def test_only_strong_verdicts_qualify():
    for weak in ("Bullish", "Bearish", "Neutral", "", None):
        assert evaluate(spot=24398, support=24400, atm_verdict=weak,
                        call_at_support=True, call_energy=72, put_energy=40) is None


def test_price_must_be_within_band_of_the_level():
    # 20 pts away from support → not "at" it
    assert evaluate(spot=24380, support=24400, atm_verdict="Strong Bullish",
                    call_at_support=True, call_energy=72, put_energy=40) is None


def test_leg_must_be_at_its_support():
    assert evaluate(spot=24398, support=24400, atm_verdict="Strong Bullish",
                    call_at_support=False, call_energy=72, put_energy=40) is None


def test_trade_side_energy_must_be_the_greater():
    # bull, but PUT has more energy → the momentum is on the wrong side
    assert evaluate(spot=24398, support=24400, atm_verdict="Strong Bullish",
                    call_at_support=True, call_energy=40, put_energy=72) is None
    # missing energy can't be shown to be stronger → no fire
    assert evaluate(spot=24398, support=24400, atm_verdict="Strong Bullish",
                    call_at_support=True, call_energy=None, put_energy=40) is None


# ── war zone takes its direction from the verdict ──────────────────────

def test_war_zone_acts_as_support_for_a_bull_and_resistance_for_a_bear():
    up = evaluate(spot=24401, war_zone=24400, atm_verdict="Strong Bullish",
                  call_at_support=True, call_energy=70, put_energy=30)
    assert up and up["side"] == "CALL" and up["level_kind"] == "war zone"
    dn = evaluate(spot=24399, war_zone=24400, atm_verdict="Strong Bearish",
                  put_at_support=True, call_energy=30, put_energy=70)
    assert dn and dn["side"] == "PUT" and dn["level_kind"] == "war zone"


# ── leg_at_support: VOB support OR session low ─────────────────────────

def test_leg_at_support_from_vob_state_or_session_low():
    assert leg_at_support({"side": "support", "state": "BUILDING"}, 50, 10, 1) is True
    assert leg_at_support({"side": "support", "state": "ACCEPTING"}, 50, 10, 1) is True
    # resistance interaction is NOT support
    assert leg_at_support({"side": "resistance", "state": "REJECTING"}, 50, 10, 1) is False
    # session-low proximity qualifies even with no VOB read
    assert leg_at_support(None, 20.4, 20.0, 1.0) is True
    assert leg_at_support(None, 25.0, 20.0, 1.0) is False       # too far from the low
    assert leg_at_support(None, None, None, 1.0) is False


def test_message_names_the_side_and_is_not_a_guarantee():
    sig = evaluate(spot=24398, support=24400, atm_verdict="Strong Bullish",
                   call_at_support=True, call_energy=72, put_energy=40)
    msg = message(sig, 24398)
    assert "BUY CALL" in msg and "24,400" in msg and "Strong Bullish" in msg
    assert "not a guaranteed" in msg.lower()


# ── the app wiring (reuses existing engine outputs, no new engine) ─────

def test_the_app_feeds_alignment_from_existing_engine_outputs():
    src = (_ROOT / "vob_minimal.py").read_text()
    assert "from mios_v5.entry_alignment import" in src
    assert "_notify_confluence_entry" in src
    # the four inputs come from already-published engine objects
    assert "atm_bias" in src                       # ATM verdict
    assert "_atm_leg_sr_behavior" in src           # leg-at-support
    assert "_premium_energy" in src                # per-side energy
    assert "strong_support" in src or "battle_zone" in src   # NIFTY level
    # latched + cooldown + opt-out, like the other level alerts
    assert "_confluence_alert_state" in src
