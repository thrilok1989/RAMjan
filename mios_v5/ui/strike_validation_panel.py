"""Stage 71.8 — the Strike Validation section, drawn below Premium Energy.

Pure presentation. Every value was computed by `mios_v5.strike_validation`;
this file decides only where it sits and what colour it is. `None` renders as
`—`, never as `0` — a zero on a validation row asserts a check that failed,
where the truth is that it never ran.

The eleven checks are always visible. They are the whole product: a score with
its reasoning folded away is a number to be trusted rather than read, and this
stage exists so a trader can see *why* a strike graded the way it did.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..strike_validation import AGREE, AVOID, DISAGREE, PARTIAL, WEIGHTS
from .theme import (ALERT, BEAR, BULL, BULL_SOFT, FAINT, INK, MICRO,
                    MUTED, WARN)

_CALL_COL = BULL
_PUT_COL = BEAR

_STATE_COL = {AGREE: BULL, PARTIAL: WARN, DISAGREE: ALERT}
_STATE_GLYPH = {AGREE: "✅", PARTIAL: "🟡", DISAGREE: "❌"}

_VALID_COL = {"VALID": BULL, "WEAK": WARN, "INVALID": ALERT}

#: check key → the label a trader reads. Ordered by weight, so the row that
#: moved the score most is the row nearest the score.
_LABELS = {
    "premium_liquidity": "Liquidity",
    "premium_health": "Premium health",
    "premium_sr_strength": "Premium S/R",
    "most_traded_agreement": "Most-traded",
    "dealer_agreement": "Dealer",
    "premium_behaviour": "Behaviour",
    "acceptance_agreement": "Acceptance",
    "htf_agreement": "HTF",
    "reaction_zone_agreement": "Reaction zone",
    "absorption_agreement": "Absorption",
}
_ORDER = sorted(_LABELS, key=lambda k: -WEIGHTS.get(k, 0.0))


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _checks_html(checks: Dict[str, Any]) -> str:
    """The eleven rows. An unknown check is drawn greyed and *kept* — hiding it
    would make a thin read look like a complete one."""
    out = []
    for key in _ORDER:
        c = (checks or {}).get(key) or {}
        state = c.get("state")
        glyph = _STATE_GLYPH.get(state, "⚪")
        col = _STATE_COL.get(state, FAINT)
        out.append(
            f"<div style='display:flex;gap:6px;align-items:baseline;"
            f"font-size:10.5px;padding:1px 0'>"
            f"<span style='width:14px'>{glyph}</span>"
            f"<span style='width:92px;color:{MUTED}'>{_LABELS[key]}</span>"
            f"<span style='color:{col};min-width:0'>{c.get('why') or '—'}</span>"
            f"<span style='color:{MICRO};font-size:9px;margin-left:auto;"
            f"white-space:nowrap'>{c.get('source') or ''}</span>"
            f"</div>")
    return "".join(out)


def _px(v) -> str:
    n = _num(v)
    return "—" if n is None else f"₹{n:,.1f}"


def _structure_html(st: Dict[str, Any], col: str) -> str:
    """The premium's own structure, above the checks.

    This is the CALL/PUT summary block — score · support · resistance ·
    acceptance · momentum · absorption · top reason. It sits in the per-side
    card rather than in the six-card Command Center for an ordering reason, not
    a design one: the Command Center renders before the strike picker, so the
    structure does not exist yet when those cards are built. Putting it here
    keeps one render of one object; putting it there would need either a
    reorder or last cycle's numbers.
    """
    if not st:
        return ""
    score = _num(st.get("structure_score"))
    conf = st.get("confidence") or "—"
    acc = st.get("acceptance_read") or {}
    state = acc.get("state") or "—"
    mom = _num(st.get("momentum"))
    ab = (st.get("absorption") or {}).get("label")
    rvol = _num(st.get("rvol"))
    brk = _num(st.get("break_probability"))
    fake = _num(st.get("fakeout_probability"))
    top = (st.get("top_reasons") or [{}])[0].get("label")

    def _cell(label: str, value: str, tone: str = MUTED) -> str:
        return (f"<div style='min-width:0'>"
                f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
                f"text-transform:uppercase'>{label}</div>"
                f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
                f"{value}</div></div>")

    cells = "".join([
        _cell("Structure", "—" if score is None else f"{score:.0f}/100",
              INK if score is None else
              (BULL if score >= 65 else WARN if score >= 40 else ALERT)),
        _cell("Confidence", conf, MUTED if conf != "LOW" else WARN),
        _cell("Support", _px(st.get("support")), BULL),
        _cell("Resistance", _px(st.get("resistance")), BEAR),
        _cell("POC", _px((st.get("profile") or {}).get("vp_poc"))),
        _cell("Acceptance", str(state).title()),
        _cell("Momentum", "—" if mom is None else f"{mom:+.0f}%",
              BULL if (mom or 0) > 0 else WARN if mom is not None else MUTED),
        _cell("RVOL", "—" if rvol is None else f"{rvol:.1f}×"),
        _cell("Absorption", (ab or "—").title()),
        # Break and fakeout are shown side by side because they are scored from
        # different evidence and can both be high — the case a trader most needs
        # to see, and the one a single blended number would hide.
        _cell("Break", "—" if brk is None else f"{brk:.0f}%", BULL),
        _cell("Fakeout", "—" if fake is None else f"{fake:.0f}%",
              ALERT if (fake or 0) >= 60 else MUTED),
    ])
    reason = ("" if not top else
              f"<div style='font-size:10px;color:{MUTED};margin-top:3px'>"
              f"Top reason <b style='color:{col}'>{top}</b></div>")
    return (f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:6px;"
            f"padding-top:5px;border-top:1px solid #1a2330'>{cells}</div>"
            f"{reason}")


def _side_html(row: Dict[str, Any], name: str, col: str) -> str:
    stars = row.get("stars") or "—"
    score = _num(row.get("overall_strike_score"))
    strike = _num(row.get("strike"))
    valid = row.get("premium_validation") or "UNKNOWN"
    star_col = ALERT if stars == AVOID else BULL_SOFT

    head = (
        f"<div style='display:flex;gap:8px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='color:{col};font-weight:800;font-size:12.5px'>{name}</span>"
        f"<span style='color:{INK};font-weight:800;font-size:12.5px'>"
        f"{'—' if strike is None else f'{strike:.0f}'}</span>"
        f"<span style='color:{star_col};font-size:13px;letter-spacing:1px'>"
        f"{stars}</span>"
        f"<span style='color:{INK};font-weight:800'>"
        f"{'—' if score is None else f'{score:.0f}/100'}</span>"
        f"<span style='color:{_VALID_COL.get(valid, FAINT)};font-size:10px;"
        f"letter-spacing:.08em'>{valid}</span>"
        f"<span style='color:{MICRO};font-size:9.5px'>"
        f"{row.get('reporting')}/{row.get('of')} checks</span>"
        f"</div>")

    why = ""
    if stars == AVOID and row.get("stars_reason"):
        why = (f"<div style='font-size:10.5px;color:{ALERT};margin-top:2px'>"
               f"⚠ {row['stars_reason']}</div>")

    return (f"<div style='flex:1;min-width:250px;background:#0b0f16;"
            f"border:1px solid #1e2836;border-radius:8px;padding:8px 9px'>"
            f"{head}{why}"
            f"{_structure_html(row.get('structure') or {}, col)}"
            f"<div style='margin-top:5px'>{_checks_html(row.get('checks'))}</div>"
            f"</div>")


def strike_validation_html(data: Optional[Dict[str, Any]]) -> str:
    """The whole section, or `""` when Stage 71.8 has nothing to say."""
    d = data or {}
    if not d.get("ready"):
        return ""

    mt = d.get("most_traded") or {}
    mt_txt = " · ".join(
        f"{s} {mt[s]:.0f}" for s in ("CALL", "PUT")
        if _num(mt.get(s)) is not None) or "—"
    basis = mt.get("source") or "—"

    missing = d.get("missing_inputs") or []
    missing_html = ""
    if missing:
        missing_html = (
            f"<div style='font-size:10px;margin-top:5px;color:{FAINT}'>"
            f"⚪ Not measured: {', '.join(missing)} "
            f"(no producer — reported, not zeroed)</div>")

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"

        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>🎯 Strike Validation "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stage 71.8 · "
        f"advisory</span></div>"

        f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>"
        f"Busiest by {basis}: <span style='color:{MUTED}'>{mt_txt}</span>"
        f" · the trader's strike is never changed, only reported on</div>"

        f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:8px'>"
        f"{_side_html(d.get('call') or {}, 'CALL', _CALL_COL)}"
        f"{_side_html(d.get('put') or {}, 'PUT', _PUT_COL)}"
        f"</div>"

        f"<div style='font-size:12.5px;font-weight:800;margin-top:8px;"
        f"color:{INK}'>{d.get('headline') or ''}</div>"

        + missing_html +
        "</div>")


def render_strike_validation(st, data: Optional[Dict[str, Any]] = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the tab down."""
    try:
        html = strike_validation_html(data)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Strike Validation unavailable: {err}")
