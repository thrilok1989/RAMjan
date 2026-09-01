"""The war zone — where the fight is, and who is expected to win it.

Pure presentation. `battle_zone`, `expected_winner`, `probabilities` and the two
ranked walls (`strong_support` / `strong_resistance`) are all published in the
final read; this file decides only how they are worded.

The dashboard strip (`full_html`) shows BOTH walls as a bracket so the whole box
is visible — resistance above, support below — with the side the move is on
marked, rather than only the single level the fight is currently at. The battle
zone is a separate read from the ranked walls (Stage 42 vs the ranked S/R), so
the fight can sit at a price that is neither wall; the strip carries all three.

## Two renderings, one owner

`full_html` is the strip on the V6 dashboard. `compact_html` is the one line on
the observational card above the app. They read the same three fields, so the
card and the dashboard cannot say different things about the same fight — which
is the whole reason this was lifted out of `dashboard_v6` rather than copied
into the card.

## The probabilities travel together

`bounce 35% · breakdown 65%` is one reading, not two. Showing the winning side
alone would be shorter and would also be the one edit that turns "the level is
likely to give, but it is close" into "the level gives" — so the compact form
drops the wrapper words, never a number.

Trap, where the engine publishes it, is a third and **independent** read: it is
not the complement of the other two and must not be presented as though the
three sum to anything.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .theme import BEAR, BULL, INK, MICRO, MUTED, WARN

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")

#: Who the expected winner favours. Anything else is uncoloured — "Contested"
#: is a real answer and must not be painted as a direction.
_WINNER_COL = {"buyers": BULL, "sellers": BEAR}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _fmt(v) -> str:
    n = _num(v)
    return "—" if n is None else f"₹{n:,.0f}"


def _winner_col(winner: Any) -> str:
    return _WINNER_COL.get(str(winner or "").strip().lower(), MUTED)


def _zone(fr: Mapping[str, Any]) -> Dict[str, Any]:
    """The battle zone as a mapping, whatever arrived.

    A degraded cycle can leave a string in `battle_zone`, and a panel is not
    allowed to raise on one — the strip is advisory and must never take the
    screen down with it.
    """
    bz = fr.get("battle_zone")
    return dict(bz) if isinstance(bz, Mapping) else {}


def _probs(fr: Mapping[str, Any]) -> Dict[str, float]:
    """The published odds, numeric ones only. A key whose value will not parse
    is dropped rather than rendered as 0% — nobody measured zero."""
    out: Dict[str, float] = {}
    raw = fr.get("probabilities")
    if not isinstance(raw, Mapping):
        return out
    for k, v in raw.items():
        n = _num(v)
        if n is not None:
            out[str(k)] = n
    return out


def _bracket_html(f: Mapping[str, Any], bz: Mapping[str, Any]) -> str:
    """Both walls at once — resistance above, support below — so the trader sees
    the whole box, not only the side price is currently fighting at.

    ⚠️ These are the RANKED levels (`strong_resistance` / `strong_support`), a
    separate read from Stage 42's `battle_zone`: the fight can be at a price that
    is neither wall. So the bracket is drawn from the ranked levels, and the side
    that matches the battle zone's type is marked ⚔️ and brightened — the one the
    move is on — while the other stays present but muted. `""` when neither wall
    is known, so a cycle without them falls back to the single fight line rather
    than drawing an empty bracket.
    """
    res = _num(f.get("strong_resistance"))
    sup = _num(f.get("strong_support"))
    if res is None and sup is None:
        return ""
    active = str(bz.get("type") or "").strip().upper()

    def _row(icon: str, label: str, price: float, is_active: bool) -> str:
        col = INK if is_active else MUTED
        weight = "800" if is_active else "600"
        mark = f"<span style='color:{WARN}'> ⚔️</span>" if is_active else ""
        return (f"<span style='color:{col};font-weight:{weight}'>"
                f"{icon} {label} ₹{price:,.0f}</span>{mark}")

    rows = []
    if res is not None:
        rows.append(_row("🧱", "Resistance", res, active == "RESISTANCE"))
    if sup is not None:
        rows.append(_row("🛡", "Support", sup, active == "SUPPORT"))
    sep = f"<span style='color:{MICRO};margin:0 8px'>·</span>"
    return (f"<div style='font-size:12.5px;margin-top:4px'>"
            f"{sep.join(rows)}</div>")


def full_html(fr: Optional[Mapping[str, Any]] = None) -> str:
    """The V6 dashboard strip. `""` when there is no fight to report.

    Two parts: the active fight (Stage 42's contested level, its expected winner
    and odds) and — when the ranked walls are published — a bracket showing both
    support and resistance so the whole box is visible at a glance, with the side
    the move is on marked.
    """
    f = fr if isinstance(fr, Mapping) else {}
    bz = _zone(f)
    if not bz:
        return ""
    probs = _probs(f)
    return (
        f"<div style='{_CARD};border-left:3px solid {WARN}'>"
        f"<span style='font-size:15px;font-weight:800;color:{WARN}'>"
        f"⚔️ War zone — {bz.get('type')} {_fmt(bz.get('price'))}</span>"
        f"<span style='font-size:13px;color:#edf3f9'> → expected winner "
        f"<b>{f.get('expected_winner', '—')}</b></span>"
        + "".join(f"<span style='font-size:12px;color:{MUTED};margin-left:10px'>"
                  f"{k} {v:.0f}%</span>" for k, v in probs.items())
        + _bracket_html(f, bz)
        + "</div>")


def compact_html(fr: Optional[Mapping[str, Any]] = None) -> str:
    """One line for the observational card. `""` when there is no fight.

    The wrapper words go — "War zone", "expected winner" — because the ⚔️ and
    the arrow already say both. Every number stays.
    """
    f = fr if isinstance(fr, Mapping) else {}
    bz = _zone(f)
    if not bz:
        return ""

    price = _fmt(bz.get("price"))
    kind = str(bz.get("type") or "").upper()
    if price == "—" and not kind:
        return ""

    winner = f.get("expected_winner")
    win_txt = str(winner) if winner else ""
    probs = _probs(f)
    odds = " · ".join(f"{k} {v:.0f}%" for k, v in probs.items())

    head = " ".join(x for x in (kind, price if price != "—" else "") if x)
    return (
        f"<div style='margin-top:5px;padding:6px 9px;background:#0b0f16;"
        f"border:1px solid #1e2836;border-left:3px solid {WARN};"
        f"border-radius:8px;text-align:center'>"
        f"<div style='font-size:12.5px;font-weight:800;color:{INK}'>"
        f"⚔️ {head}"
        + (f"<span style='color:{MICRO};font-weight:600'> → </span>"
           f"<span style='color:{_winner_col(winner)}'>{win_txt}</span>"
           if win_txt else "")
        + "</div>"
        + (f"<div style='font-size:11px;margin-top:1px;color:{MUTED}'>{odds}"
           f"</div>" if odds else "")
        + "</div>")


def render(st, fr: Optional[Mapping[str, Any]] = None) -> None:
    """Draw the dashboard strip. Advisory — it may never take the tab down."""
    try:
        html = full_html(fr)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"War zone unavailable: {err}")


def micro(fr: Optional[Mapping[str, Any]] = None) -> str:
    """The fight as PLAIN TEXT for the sticky app header.

    ⚠️ This carries the level AND the odds, and the first version did not.

    It dropped both on the reasoning that "the level is already on the S/R
    chips beside it". That was wrong, and a live reading disproves it:

        S/R chip   🛡 24,558  brk 44 · rej 56
        war zone   ⚔️ 24,561  bounce 35 · breakdown 65

    Different level, different odds. Stage 42's battle zone is not the same
    object as the ranked S/R level next to it, and its probabilities are a
    separate read — so a header showing only the winner asked the trader to
    infer two numbers from a neighbouring chip that does not hold them.

    `""` when there is no fight.
    """
    f = fr if isinstance(fr, Mapping) else {}
    bz = _zone(f)
    if not bz:
        return ""

    price = _fmt(bz.get("price"))
    winner = str(f.get("expected_winner") or "").strip()
    odds = " · ".join(f"{k} {v:.0f}" for k, v in _probs(f).items())

    bits = [x for x in (price if price != "—" else "", winner, odds) if x]
    return f"⚔️ {' · '.join(bits)}" if bits else ""
