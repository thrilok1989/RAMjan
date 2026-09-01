"""Stage 71.85 — the Premium LTP Behaviour section, drawn below Strike Validation.

Pure presentation. Every value was computed by `mios_v5.premium_behaviour`; this
file decides only where it sits and what colour it is. `None` renders as `—`,
never as `0`.

## Why this panel is not optional ⚠️

Principle 12: *nothing may influence a trading decision unless the trader can
inspect that exact value somewhere in the UI.* Stage 71.85's behaviour is an
eleventh weight in Stage 72's entry score as of contract `72.1`, so it moves
decisions — and a value that moves decisions with nowhere to look at it is the
exact thing that principle forbids.

The evidence ledger is drawn with it, both directions, because a verdict whose
reasoning is folded away is a number to be trusted rather than read. The rows
arguing *against* the verdict are shown too: hiding them would make a 55/45 read
look like a 100/0 one.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..premium_behaviour import (ACCELERATING, ACCEPTANCE, BUILDING, DOWN,
                                 EXHAUSTING, FADING, HOLDING, NEUTRAL,
                                 RESISTANCE_BUILDING, RESISTANCE_FADING,
                                 SUPPORT_BUILDING, SUPPORT_FADING, UNKNOWN, UP)
from .theme import (ALERT, BEAR, BULL, BULL_SOFT, FAINT, INK, MICRO,
                    MUTED, WARN, grade_tone)

_CALL_COL = BULL
_PUT_COL = BEAR

#: Behaviour → the colour it earns. Not a recommendation: the colour reports
#: what the level is doing to the premium, which is what the words already say.
_BEHAVIOUR_COL = {
    SUPPORT_BUILDING: BULL,
    RESISTANCE_FADING: BULL_SOFT,
    ACCEPTANCE: MUTED,
    RESISTANCE_BUILDING: WARN,
    SUPPORT_FADING: ALERT,
    NEUTRAL: FAINT,
}

_MOMENTUM_COL = {ACCELERATING: BULL, BUILDING: BULL_SOFT, HOLDING: MUTED,
                 FADING: WARN, EXHAUSTING: ALERT}


_DIR_GLYPH = {UP: "▲", DOWN: "▼"}
_DIR_COL = {UP: BULL, DOWN: ALERT}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if s and s != UNKNOWN else "—"


def _cell(label: str, value: str, tone: str = MUTED) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
            f"{value}</div></div>")


def _ledger_html(reasons: Any) -> str:
    """The ranked evidence. Agreeing rows lead, dissenting rows follow — and the
    dissenting ones keep their arrow, so a close call reads as a close call."""
    rows: List[str] = []
    for r in (reasons or ())[:5]:
        if not isinstance(r, dict):
            continue
        d = r.get("direction") or ""
        w = _num(r.get("weight")) or 0.0
        rows.append(
            f"<div style='display:flex;gap:6px;align-items:baseline;"
            f"font-size:10.5px;padding:1px 0'>"
            f"<span style='width:12px;color:{_DIR_COL.get(d, FAINT)}'>"
            f"{_DIR_GLYPH.get(d, '·')}</span>"
            f"<span style='color:{MUTED};min-width:0'>"
            f"{_txt(r.get('label'))}</span>"
            f"<span style='color:{MICRO};font-size:9px;margin-left:auto;"
            f"white-space:nowrap'>{w:.2f} · {_txt(r.get('owner'))}</span>"
            f"</div>")
    return "".join(rows)


def _d(v) -> Dict[str, Any]:
    """A dict, whatever arrived. A degraded cycle can leave a session-state
    cache holding a string, and a panel is not allowed to raise on one."""
    return dict(v) if isinstance(v, dict) else {}


def _side_html(read: Optional[Dict[str, Any]], name: str, col: str) -> str:
    d = _d(read)
    beh = d.get("behaviour") or UNKNOWN
    ev = d.get("evidence") or {}
    eng = d.get("engagement") or {}
    conf = d.get("confidence") or UNKNOWN
    brk, fake = _num(d.get("break_probability")), _num(d.get("fakeout_probability"))

    head = (
        f"<div style='display:flex;gap:8px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='color:{col};font-weight:800;font-size:12.5px'>{name}</span>"
        f"<span style='color:{_BEHAVIOUR_COL.get(beh, FAINT)};font-weight:800;"
        f"font-size:12.5px'>{_txt(beh)}</span>"
        f"<span style='color:{BULL_SOFT};font-size:13px;letter-spacing:1px'>"
        f"{_txt(d.get('strength'))}</span>"
        f"<span style='color:{grade_tone(conf, FAINT)};font-weight:800'>"
        f"{_txt(conf)}</span>"
        f"<span style='color:{MICRO};font-size:9.5px'>"
        f"{ev.get('reporting', 0)} signals</span>"
        f"</div>")

    why = (f"<div style='font-size:10px;color:{MICRO};margin-top:2px'>"
           f"{_txt(d.get('why'))}</div>")

    cells = "".join([
        _cell("Momentum", _txt(d.get("momentum")),
              _MOMENTUM_COL.get(d.get("momentum"), MUTED)),
        _cell("Engaged", (f"{eng.get('kind').title()} "
                          f"{eng.get('distance_pct'):.1f}%"
                          if eng.get("kind") and eng.get("distance_pct") is not None
                          else "—")),
        _cell("Acceptance", _txt(d.get("acceptance"))),
        _cell("Structure", _txt(d.get("structure_state"))),
        _cell("S/R strength", _txt(d.get("structure_strength"))),
        # Break and fakeout sit side by side for the same reason they do in
        # Stage 71.8's card: both can be high at once, and that is the case a
        # trader most needs to see.
        _cell("Break", "—" if brk is None else f"{brk:.0f}%", BULL),
        _cell("Fakeout", "—" if fake is None else f"{fake:.0f}%",
              ALERT if (fake or 0) >= 60 else MUTED),
        _cell("Ledger", f"▲{_num(ev.get('up')) or 0:.1f} "
                        f"▼{_num(ev.get('down')) or 0:.1f}"),
    ])

    return (f"<div style='flex:1;min-width:250px;background:#0b0f16;"
            f"border:1px solid #1e2836;border-radius:8px;padding:8px 9px'>"
            f"{head}{why}"
            f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;"
            f"padding-top:5px;border-top:1px solid #1a2330'>{cells}</div>"
            f"<div style='margin-top:5px'>"
            f"{_ledger_html(d.get('top_reasons'))}</div>"
            f"</div>")


def premium_behaviour_html(data: Optional[Dict[str, Any]]) -> str:
    """The whole section, or `""` when Stage 71.85 has nothing to say."""
    d = _d(data)
    if not any(_d(d.get(s)).get("ready") for s in ("CALL", "PUT")):
        return ""

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"

        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>🧭 Premium LTP Behaviour "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stage 71.85 · "
        f"advisory</span></div>"

        f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>"
        f"What each premium is doing at <b>its own</b> support / resistance — "
        f"an interpretation of Stages 71.7 and 71.8, never a second measurement "
        f"of them, and never a recommendation</div>"

        f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px'>"
        f"{_side_html(d.get('CALL'), 'CALL', _CALL_COL)}"
        f"{_side_html(d.get('PUT'), 'PUT', _PUT_COL)}"
        f"</div>"
        "</div>")


def render_premium_behaviour(st, data: Optional[Dict[str, Any]] = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the tab down."""
    try:
        html = premium_behaviour_html(data)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Premium Behaviour unavailable: {err}")
