"""One meaning, one colour.

Seven panels defined their own bias map and three defined their own grade map.
Bull and bear agreed everywhere — **neutral did not**: `MUTED` grey in two
panels, `WARN` amber in five. Two panels called the same reading "nothing is
happening" while five called it "be careful", on the same screen.

These tests keep the maps from fragmenting again. They are AST-based, because
a source-text guard trips on the comment explaining the rule — the lesson this
repo has now learned six times.
"""

import ast
import pathlib

import pytest

from mios_v5.ui import theme as T

UI = pathlib.Path(__file__).resolve().parents[1] / "ui"

#: Maps whose keys mean a bias or a trade grade. A panel defining one of these
#: locally is the fragmentation this replaced.
BIAS_KEYS = ({"bull", "bear", "neutral"},)
GRADE_KEYS = ({"a+", "a", "b", "c"},)


def _dict_assignments(path):
    """(name, {lowercased string keys}) for every module-level dict literal."""
    out = []
    try:
        tree = ast.parse(path.read_text())
    except Exception:
        return out
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            keys = {k.value.lower() for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            name = (node.targets[0].id
                    if isinstance(node.targets[0], ast.Name) else "?")
            out.append((name, keys))
    return out


@pytest.mark.parametrize("path", sorted(UI.glob("*.py")), ids=lambda p: p.name)
def test_no_panel_redefines_the_bias_or_grade_map(path):
    if path.name == "theme.py":
        return
    for name, keys in _dict_assignments(path):
        assert keys not in BIAS_KEYS, (
            f"{path.name}:{name} redefines the bias map — use "
            f"theme.bias_tone() so neutral means one thing")
        assert keys not in GRADE_KEYS, (
            f"{path.name}:{name} redefines the grade map — use "
            f"theme.grade_tone() so a B is a B on every screen")


def test_the_shared_maps_use_the_semantic_constants():
    """Not raw hexes. A literal here would drift from the palette silently."""
    assert T.BIAS_TONE == {"BULL": T.BULL, "BEAR": T.BEAR, "NEUTRAL": T.WARN}
    assert T.GRADE_TONE == {"A+": T.BULL, "A": T.BULL_SOFT,
                            "B": T.WARN, "C": T.ALERT}


def test_lookup_is_case_insensitive():
    """Half the panels wrote `BULL` and half wrote `bull`. That is how one map
    became seven, so the helper accepts both."""
    assert T.bias_tone("bull") == T.bias_tone("BULL") == T.BULL
    assert T.bias_tone("Neutral") == T.WARN
    assert T.grade_tone("a+") == T.grade_tone("A+") == T.BULL


def test_an_unknown_value_falls_back_rather_than_raising():
    assert T.bias_tone(None) == T.INK
    assert T.bias_tone("SIDEWAYS", default=T.MUTED) == T.MUTED
    assert T.grade_tone("Z") == T.MUTED
    assert T.bias_emoji("") == "⚪"


def test_the_semantic_accents_are_unchanged():
    """This change may unify where a colour is defined; it may not redefine
    what the colours mean."""
    assert (T.BULL, T.BEAR, T.WARN) == ("#00ff88", "#ff4444", "#ffd000")
    assert (T.BULL_SOFT, T.ALERT) == ("#17c98b", "#ff9500")


def test_no_shared_map_uses_a_retired_grey():
    assert not (set(T.BIAS_TONE.values()) & set(T.RETIRED))
    assert not (set(T.GRADE_TONE.values()) & set(T.RETIRED))


# ══════════════════════════════════════════════════════════════════════
#  the vocabulary the engines actually publish
# ══════════════════════════════════════════════════════════════════════

def test_the_labels_the_engines_really_emit_get_a_colour():
    """⭐ Exact lookup silently broke the colour code.

    Stage 27 and Stage 71 publish `BULLISH`, `STRONG BULLISH`, `BEARISH` — the
    wording that reaches the header and the Telegram message. The maps are
    keyed `BULL`/`BEAR`/`NEUTRAL`, so every real label fell through to the
    default: white text and a ⚪ on a strongly bullish read.
    """
    for label in ("BULLISH", "STRONG BULLISH", "Bullish", "bullish"):
        assert T.bias_tone(label) == T.BULL, label
        assert T.bias_emoji(label) == "🟢", label
    for label in ("BEARISH", "STRONG BEARISH", "Bearish"):
        assert T.bias_tone(label) == T.BEAR, label
        assert T.bias_emoji(label) == "🔴", label


def test_the_short_vocabulary_still_resolves():
    assert T.bias_tone("BULL") == T.BULL and T.bias_tone("BEAR") == T.BEAR
    assert T.bias_tone("NEUTRAL") == T.WARN


def test_a_word_that_is_not_a_bias_still_takes_the_default():
    """Widening the match must not turn every string into a direction."""
    for junk in ("SIDEWAYS", "CHOP", "UNKNOWN", "", None, "  "):
        assert T.bias_tone(junk, default=T.MUTED) == T.MUTED, junk
        assert T.bias_emoji(junk) == "⚪", junk


def test_the_match_order_is_fixed_not_dict_order():
    """A colour that depends on insertion order is a bug waiting for an
    alphabetised refactor."""
    assert T._BIAS_KEYS == ("NEUTRAL", "BEAR", "BULL")
