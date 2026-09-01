"""🟢🔴🟡 One ball per alert — the NIFTY-direction reading.

Every alert in the stream leads with a coloured ball, and it always speaks in
NIFTY terms even when the alert is about a CALL or PUT leg. The rule that earns
its own tests is the leg inversion: PUT premium points the opposite way to the
index, so a support forming on a PUT is bearish for NIFTY.
"""

from __future__ import annotations

import ast
import pathlib

from mios_v5 import bias_ball as BB
from mios_v5 import formation_alerts as FA

_ROOT = pathlib.Path(__file__).resolve().parents[2]

GREEN, RED, YELLOW = "🟢", "🔴", "🟡"


def test_the_ball_and_prefix():
    assert BB.ball(BB.BULL) == GREEN
    assert BB.ball(BB.BEAR) == RED
    assert BB.ball(BB.NEUTRAL) == YELLOW
    assert BB.ball("nonsense") == YELLOW
    assert BB.prefix(BB.BULL, "hi").startswith(f"{GREEN} ")
    assert BB.prefix(BB.BEAR, "") == ""          # empty stays empty


# ── the leg inversion, the thing that must be right ────────────────────

def test_a_level_reads_straight_on_nifty_and_call_and_flips_on_put():
    assert BB.leg_level_bias("NIFTY", "support") == BB.BULL
    assert BB.leg_level_bias("NIFTY", "resistance") == BB.BEAR
    assert BB.leg_level_bias("CALL", "support") == BB.BULL
    assert BB.leg_level_bias("CALL", "resistance") == BB.BEAR
    # PUT inverts: a supported put = puts bid = NIFTY down
    assert BB.leg_level_bias("PUT", "support") == BB.BEAR
    assert BB.leg_level_bias("PUT", "resistance") == BB.BULL
    # bullish/bearish VOB roles map onto support/resistance
    assert BB.leg_level_bias("PUT", "bullish") == BB.BEAR


def test_hvp_high_is_resistance_low_is_support_then_the_leg_rule():
    assert BB.hvp_bias("NIFTY", "LOW") == BB.BULL
    assert BB.hvp_bias("NIFTY", "HIGH") == BB.BEAR
    assert BB.hvp_bias("CALL", "LOW") == BB.BULL
    assert BB.hvp_bias("CALL", "HIGH") == BB.BEAR
    assert BB.hvp_bias("PUT", "LOW") == BB.BEAR      # confirmed: PUT low → 🔴
    assert BB.hvp_bias("PUT", "HIGH") == BB.BULL     # confirmed: PUT high → 🟢


def test_vob_follows_the_same_rule():
    assert BB.vob_bias("CALL", "support") == BB.BULL
    assert BB.vob_bias("CALL", "resistance") == BB.BEAR
    assert BB.vob_bias("PUT", "support") == BB.BEAR
    assert BB.vob_bias("PUT", "resistance") == BB.BULL


def test_poc_step_up_is_bullish_except_on_the_put_leg():
    assert BB.poc_bias("NIFTY", "UP") == BB.BULL
    assert BB.poc_bias("NIFTY", "DOWN") == BB.BEAR
    assert BB.poc_bias("CALL", "UP") == BB.BULL
    assert BB.poc_bias("PUT", "UP") == BB.BEAR       # confirmed: PUT up → 🔴
    assert BB.poc_bias("PUT", "DOWN") == BB.BULL


def test_writing_and_winner():
    assert BB.writing_bias("CALL") == BB.BEAR        # capping upside
    assert BB.writing_bias("PUT") == BB.BULL         # support building
    assert BB.winner_bias("Sellers (breakdown)") == BB.BEAR
    assert BB.winner_bias("Buyers") == BB.BULL
    assert BB.winner_bias("Contested") == BB.NEUTRAL


# ── the ball actually reaches the message ──────────────────────────────

def test_formation_messages_lead_with_the_nifty_ball():
    # a support VOB on a PUT leg is bearish for NIFTY → 🔴, not 🟢
    put_sup = FA.vob_message("PUT", "ATM PE 24350",
                             {"role": "support", "lower": 85.0, "upper": 88.1,
                              "status": "INTACT"})
    assert put_sup.startswith(f"{RED} ")
    call_sup = FA.vob_message("CALL", "ATM CE 24350",
                              {"role": "support", "lower": 121.0, "upper": 122.8})
    assert call_sup.startswith(f"{GREEN} ")
    # a swing low on a PUT leg is bearish for NIFTY → 🔴
    put_low = FA.hvp_message("PUT", "ATM PE 24350",
                             {"side": "LOW", "price": 85.0, "confirmed_at": 9},
                             decimals=2)
    assert put_low.startswith(f"{RED} ")
    nifty_low = FA.hvp_message("NIFTY", "NIFTY",
                               {"side": "LOW", "price": 24300, "confirmed_at": 9})
    assert nifty_low.startswith(f"{GREEN} ")


# ── purity & wiring ────────────────────────────────────────────────────

def test_the_module_is_pure():
    tree = ast.parse((_ROOT / "mios_v5" / "bias_ball.py").read_text())
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported |= {a.name for a in n.names}
    assert not any("vob_minimal" in m or "streamlit" in m for m in imported)
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "session_state" not in attrs


def test_every_alert_site_uses_the_ball():
    """The Telegram/Discord alert helpers and the two message builders all route
    their text through `bias_ball`, so no alert ships without its NIFTY ball."""
    src = (_ROOT / "vob_minimal.py").read_text()
    tree = ast.parse(src)
    for name in ("_notify_writing_telegram", "_notify_poc_shifts",
                 "_notify_level_touches"):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == name)
        seg = ast.get_source_segment(src, fn) or ""
        assert "bias_ball" in seg, f"{name} sends without a ball"
    # ZONE REVERSAL (built inline) and the two formation builders
    assert "bias_ball" in src            # ZONE REVERSAL site
    fa = (_ROOT / "mios_v5" / "formation_alerts.py").read_text()
    assert fa.count("bias_ball") >= 2    # hvp_message and vob_message
