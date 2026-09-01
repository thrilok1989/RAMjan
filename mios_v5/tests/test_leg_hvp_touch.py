"""Option LTP → HVP-line touch alert (±5, with a cooldown sleep).

The alert reuses `level_touch` (latch + cooldown) and the HVP lines the terminal
already publishes (`_leg_profiles[side].hv_points`); nothing is recomputed. These
tests pin the reuse behaviour and the app wiring (source-scanned, since
vob_minimal can't be imported under test).
"""

import ast
import pathlib

from mios_v5 import bias_ball as BB
from mios_v5 import level_touch as LT

_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_bias_ball_reads_nifty_direction_with_the_leg_inversion():
    # HIGH pivot = resistance, LOW = support; PUT inverts.
    assert BB.hvp_bias("CALL", "LOW") == BB.BULL     # call support → NIFTY 🟢
    assert BB.hvp_bias("CALL", "HIGH") == BB.BEAR    # call resistance → 🔴
    assert BB.hvp_bias("PUT", "LOW") == BB.BEAR      # put support → NIFTY 🔴
    assert BB.hvp_bias("PUT", "HIGH") == BB.BULL     # put resistance → 🟢


def test_latch_and_cooldown_are_the_touch_semantics_asked_for():
    # LTP nearing an HVP at 100, ±5 band, 10 re-arm, 900s cooldown
    s = None
    a, s = LT.evaluate(100, 88, s, band=5, rearm=10, cooldown_s=900, now=0)
    assert a is False                                    # far → nothing
    a, s = LT.evaluate(100, 103, s, band=5, rearm=10, cooldown_s=900, now=10)
    assert a is True                                     # entered ±5 → alert once
    a, s = LT.evaluate(100, 101, s, band=5, rearm=10, cooldown_s=900, now=20)
    assert a is False                                    # loitering → latched, quiet
    # leaves past the re-arm, returns WITHIN the cooldown → suppressed (sleeping)
    a, s = LT.evaluate(100, 115, s, band=5, rearm=10, cooldown_s=900, now=30)
    a, s = LT.evaluate(100, 102, s, band=5, rearm=10, cooldown_s=900, now=40)
    assert a is False
    # returns AFTER the cooldown → alerts again
    a, s = LT.evaluate(100, 115, s, band=5, rearm=10, cooldown_s=900, now=1000)
    a, s = LT.evaluate(100, 102, s, band=5, rearm=10, cooldown_s=900, now=1001)
    assert a is True


def test_the_app_wires_the_hvp_touch_from_existing_data():
    src = (_ROOT / "vob_minimal.py").read_text()
    # a dedicated notifier, reusing level_touch and the published HVP lines
    assert "_notify_leg_hvp_touch" in src
    assert "from mios_v5 import level_touch" in src
    assert "hv_points" in src and "_leg_profiles" in src
    # ±5 band + a cooldown (sleep), and an opt-out toggle
    assert "LEG_HVP_BAND = 5.0" in src
    assert "LEG_HVP_COOLDOWN_S" in src
    assert "_leg_hvp_touch_on" in src
    assert "_leg_hvp_touch_state" in src
    # the NIFTY-bias ball is prepended (leg inversion via bias_ball.hvp_bias)
    assert "bias_ball" in src and "hvp_bias" in src
    # it is actually called in the render loop, and computes no candles itself
    assert "_notify_leg_hvp_touch()" in src
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_notify_leg_hvp_touch")
    seg = ast.get_source_segment(src, fn) or ""
    assert "get_intraday_data" not in seg               # no new fetch
    assert "level_touch" in seg and "hv_points" in seg
