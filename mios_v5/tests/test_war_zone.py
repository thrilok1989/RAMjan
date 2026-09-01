"""The war zone — one fight, two renderings, one owner.

The markup used to live inside `dashboard_v6`. The observational card above the
app needs the same fight in one line, and copying it would have given one fight
two wordings that drift. These tests are mostly about the two staying the same
fight, and about what "in short" is allowed to drop.
"""

import ast
import pathlib

from mios_v5.ui import war_zone as W
from mios_v5.ui.theme import BEAR, BULL

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _fr(**over):
    fr = {"battle_zone": {"type": "SUPPORT", "price": 24571},
          "expected_winner": "Sellers (breakdown)",
          "probabilities": {"bounce": 35, "breakdown": 65}}
    fr.update(over)
    return fr


def test_the_short_form_keeps_the_level_and_the_winner():
    html = W.compact_html(_fr())
    assert "SUPPORT" in html and "24,571" in html and "Sellers" in html


def test_the_short_form_drops_words_never_numbers():
    """⭐ `bounce 35% · breakdown 65%` is ONE reading.

    Showing the winning side alone would be shorter, and would also be the one
    edit that turns "the level is likely to give, but it is close" into "the
    level gives".
    """
    html = W.compact_html(_fr())
    assert "bounce 35%" in html and "breakdown 65%" in html
    # the wrapper words are what "in short" removes
    assert "War zone" not in html and "expected winner" not in html


def test_both_renderings_describe_the_same_fight():
    fr = _fr()
    short, full = W.compact_html(fr), W.full_html(fr)
    for probe in ("SUPPORT", "24,571", "Sellers", "35%", "65%"):
        assert probe in short and probe in full, probe


def test_no_battle_zone_draws_nothing():
    """No fight is not a fight nobody can call."""
    for empty in ({}, {"battle_zone": None}, None):
        assert W.compact_html(empty) == ""
        assert W.full_html(empty) == ""


def test_a_probability_that_will_not_parse_is_dropped_not_zeroed():
    """Nobody measured zero."""
    html = W.compact_html(_fr(probabilities={"bounce": "n/a", "breakdown": 65}))
    assert "breakdown 65%" in html
    assert "0%" not in html and "bounce" not in html


def test_the_winner_is_coloured_by_side_and_contested_is_not():
    """"Contested" is a real answer and must not be painted as a direction."""
    assert BEAR in W.compact_html(_fr(expected_winner="Sellers"))
    assert BULL in W.compact_html(_fr(expected_winner="Buyers"))
    contested = W.compact_html(_fr(expected_winner="Contested"))
    assert BULL not in contested and BEAR not in contested


def test_a_missing_winner_drops_the_arrow_rather_than_pointing_at_a_dash():
    html = W.compact_html(_fr(expected_winner=None))
    assert "SUPPORT" in html
    assert "→" not in html


def test_it_never_raises():
    for junk in (None, {}, {"battle_zone": "x"}, {"probabilities": "x"},
                 {"battle_zone": {"price": object()}},
                 _fr(strong_support="n/a", strong_resistance=object())):
        W.compact_html(junk)
        W.full_html(junk)


# ══════════════════════════════════════════════════════════════════════
#  the bracket — both walls, so the whole box is visible
# ══════════════════════════════════════════════════════════════════════

def test_the_strip_shows_both_walls_when_they_are_published():
    """The whole ask: not only the side price is fighting at. Both the ranked
    resistance above and support below appear on the dashboard strip."""
    html = W.full_html(_fr(strong_support=24330, strong_resistance=24498))
    assert "Support" in html and "24,330" in html
    assert "Resistance" in html and "24,498" in html


def test_the_active_side_is_marked_and_the_other_is_muted():
    """The move is on SUPPORT here, so the support wall carries the ⚔️ and the
    bright ink; resistance is present but muted — the picture at a glance."""
    from mios_v5.ui.theme import INK, MUTED
    html = W.full_html(_fr(battle_zone={"type": "SUPPORT", "price": 24330},
                           strong_support=24330, strong_resistance=24498))
    # the active wall is bright and the muted colour is used for the other.
    # rfind, not find: the header "⚔️ War zone" is the first ⚔️; the bracket's
    # mark is the last one. SUPPORT active → mark sits after the support row,
    # which the bracket draws below resistance.
    assert INK in html and MUTED in html
    assert html.index("🧱 Resistance") < html.index("🛡 Support") < html.rfind("⚔️")
    # flipping the fight to the resistance side moves the mark up onto it
    res_html = W.full_html(_fr(battle_zone={"type": "RESISTANCE", "price": 24498},
                               strong_support=24330, strong_resistance=24498))
    assert res_html.index("🧱 Resistance") < res_html.rfind("⚔️") < \
        res_html.index("🛡 Support")


def test_no_walls_means_no_bracket_but_still_a_fight_line():
    """A cycle without the ranked walls falls back to the single fight line — no
    empty bracket, and the active fight still renders."""
    html = W.full_html(_fr())          # _fr has no strong_support/resistance
    assert "SUPPORT" in html and "24,571" in html
    assert "🛡 Support" not in html and "🧱 Resistance" not in html


# ══════════════════════════════════════════════════════════════════════
#  one owner
# ══════════════════════════════════════════════════════════════════════

def test_the_dashboard_delegates_rather_than_keeping_a_copy():
    """Two copies of one fight's wording drift apart. AST, not a text scan:
    the function's own docstring explains the rule and names the module."""
    tree = ast.parse((ROOT / "mios_v5" / "ui" / "dashboard_v6.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_war_zone")
    imported = {(n.module or "") for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom)}
    assert any("war_zone" in m for m in imported)
    # …and no markup left behind
    src = "\n".join((ROOT / "mios_v5" / "ui" / "dashboard_v6.py")
                    .read_text().splitlines()[fn.lineno - 1:fn.end_lineno])
    assert "<div" not in src and "War zone" not in src


def test_the_card_renders_the_short_form_from_the_final_read():
    src = (ROOT / "vob_minimal.py").read_text()
    assert "_wz_html" in src, "the short form is never assembled"
    tree = ast.parse(src)
    names = {getattr(n, "id", "") for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_mios_fr" in names


# ══════════════════════════════════════════════════════════════════════
#  the header form
# ══════════════════════════════════════════════════════════════════════

def test_the_header_form_carries_the_level_and_the_odds():
    """⭐ The first version dropped both, on the reasoning that "the level is
    already on the S/R chips beside it". A live reading disproves it:

        S/R chip   🛡 24,558  brk 44 · rej 56
        war zone   ⚔️ 24,561  bounce 35 · breakdown 65

    Different level, different odds. Stage 42's battle zone is not the ranked
    S/R level next to it, and its probabilities are a separate read — so a
    header showing only the winner asked the trader to infer two numbers from a
    neighbouring chip that does not hold them.
    """
    line = W.micro(_fr(battle_zone={"type": "SUPPORT", "price": 24561}))
    assert "24,561" in line
    assert "bounce 35" in line and "breakdown 65" in line
    assert "Sellers" in line


def test_the_header_form_keeps_what_it_has_when_a_part_is_missing():
    assert W.micro({"battle_zone": {"price": 24561}}) == "⚔️ ₹24,561"
    only_winner = W.micro({"battle_zone": {"type": "SUPPORT"},
                           "expected_winner": "Contested"})
    assert only_winner == "⚔️ Contested"


def test_the_header_form_is_plain_text():
    """The header owns its styling; this owns the wording."""
    line = W.micro(_fr())
    assert "<" not in line and "style=" not in line


def test_no_fight_says_nothing_in_the_header_either():
    for empty in ({}, None, {"battle_zone": None}, {"battle_zone": "x"}):
        assert W.micro(empty) == ""
