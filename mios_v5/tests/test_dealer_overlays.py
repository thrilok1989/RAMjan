"""Priority 2 — the dealer-hedging and reaction overlays.

Stage 11 computed gamma flip and the magnet wall on every cycle, and nothing
could draw them: `sections.dealer` carried only {bias, confidence, status,
headline}, so the numbers existed and no chart could reach them. That is the
shape principle 12 forbids — an engine influencing the read while invisible.

These tests guard the whole path: the app must stop dropping the wall, the
levels must arrive on `final_read`, and the chart must be able to draw them.
"""

import pandas as pd
import pytest

from mios_v5.final_read import _dealer_levels
from mios_v5.ui import terminal_chart as TC


class _R:
    """A stand-in EngineResult — only `ok` and `data` are read."""
    def __init__(self, data, ok=True):
        self.data, self.ok = data, ok


def _dealer(**gex):
    return _R({"gex": gex})


# ── the app stops dropping the wall ─────────────────────────────────────

def test_market_picture_carries_magnet_and_repeller():
    """`calculate_dealer_gex` produced both and `gex_disp` threw them away, so
    nothing downstream could ever draw the level dealers defend."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2] / "vob_minimal.py"
           ).read_text(encoding="utf-8")
    block = src[src.index("gex_disp = {"):]
    block = block[:block.index("}") + 1]
    assert "'magnet'" in block and "'repeller'" in block


# ── final_read exposes them ─────────────────────────────────────────────

def test_dealer_levels_are_extracted_and_renamed():
    out = _dealer_levels(_dealer(flip=24200, magnet=24300, repeller=24100))
    assert out == {"gamma_flip": 24200.0, "dealer_wall": 24300.0,
                   "dealer_repeller": 24100.0}


def test_a_missing_level_is_absent_not_zero():
    """A level drawn at 0 renders a line along the bottom of every chart,
    which is worse than absent (principle 9)."""
    out = _dealer_levels(_dealer(flip=24200))
    assert out == {"gamma_flip": 24200.0}
    assert "dealer_wall" not in out


def test_zero_and_none_and_nan_are_all_rejected():
    for bad in (0, None, float("nan"), "", "abc"):
        assert _dealer_levels(_dealer(flip=bad)) == {}


def test_no_dealer_read_yields_no_levels():
    assert _dealer_levels(None) == {}
    assert _dealer_levels(_R({}, ok=False)) == {}
    assert _dealer_levels(_R({})) == {}


def test_final_read_publishes_dealer_levels_and_reaction_level():
    import inspect
    from mios_v5 import final_read as FR
    src = inspect.getsource(FR.build_final_read)
    assert '"dealer_levels"' in src
    assert '"reaction_level"' in src


# ── the chart can draw them ─────────────────────────────────────────────

@pytest.mark.parametrize("key", ["gamma_flip", "dealer_wall", "charm_pin",
                                 "reaction"])
def test_every_new_overlay_is_drawable(key):
    assert key in TC.LEVELS, f"{key} has no style"
    assert key in TC.LEVEL_LABEL, f"{key} has no label"


def test_every_level_style_has_a_label_and_vice_versa():
    """A style without a label raises a KeyError mid-draw and takes the whole
    chart down — the annotation is built from LEVEL_LABEL unconditionally."""
    assert set(TC.LEVELS) == set(TC.LEVEL_LABEL)


def test_dealer_levels_share_the_house_violet():
    """Violet is the dealer/gamma/charm family, so they read as one group and
    never compete with entry/stop, which are the trader's own levels."""
    for key in ("gamma_flip", "dealer_wall", "charm_pin"):
        colour = TC.LEVELS[key][0].lower()
        r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
        assert b > r > g, f"{key} {colour} is not a violet"


def test_dealer_levels_are_visually_distinct_from_each_other():
    dashes = {k: TC.LEVELS[k][1] for k in
              ("gamma_flip", "dealer_wall", "charm_pin")}
    assert len(set(dashes.values())) == 3, dashes


# ── they survive a real figure build ────────────────────────────────────

def _frame(n=30, base=24200):
    closes = [base + i for i in range(n)]
    return pd.DataFrame({
        "datetime": pd.date_range("2026-07-29 09:15", periods=n, freq="1min"),
        "open": closes, "high": [c + 3 for c in closes],
        "low": [c - 3 for c in closes], "close": closes,
        "volume": [1000] * n})


def test_the_chart_draws_with_every_new_overlay():
    fig, notes = TC.terminal_chart(
        _frame(), _frame(base=120), _frame(base=140),
        levels={"gamma_flip": 24210, "dealer_wall": 24240,
                "charm_pin": 24225, "reaction": 24205,
                "entry": 24215, "stop": 24195})
    assert not notes
    texts = [a.text for a in fig.layout.annotations if a.text]
    for want in ("Gamma Flip", "Dealer Wall", "Charm Pin", "Reaction"):
        assert any(want in t for t in texts), f"{want} not drawn"


def test_a_none_level_draws_nothing_rather_than_a_line_at_zero():
    fig, _ = TC.terminal_chart(_frame(), None, None,
                               levels={"gamma_flip": None, "dealer_wall": 0})
    texts = [a.text for a in fig.layout.annotations if a.text]
    assert not any("Gamma Flip" in t for t in texts)


def test_unknown_level_keys_are_ignored_not_crashed():
    fig, _ = TC.terminal_chart(_frame(), None, None,
                               levels={"not_a_real_level": 24200})
    assert fig is not None


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        if not hasattr(fn, "pytestmark"):
            fn()
    print(f"dealer overlay tests passed ({len(fns)})")
