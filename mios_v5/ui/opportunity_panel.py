"""MIOS Stage 71 — the Trade Opportunity panel for Dashboard 2.

**Presentation only.** Every value here was produced by `opportunity.py` or
`opportunity_intel.py`. This module computes no score, no grade and no
direction; where it appears to derive something — the Stability word, the
energy bar width — it is mapping a value that already exists onto a display
form, and the mapping tables are right here to be read.

## The layout constraint that shapes it

Dashboard 2 is the execution workstation, and its charts must stay above the
fold on a laptop. `_trading_screen` already renders three strips before the
660px terminal chart, so this panel gets a hard budget: **one compact row per
horizon plus a two-line header**. Everything else — the reasoning, the
confidence breakdown, the excluded list — lives inside expanders that are
closed by default.

A trader who wants the whole story opens a row. A trader who wants the answer
reads two lines and looks at the chart.

## Vocabulary mapping

Stage 71.5's Stability is a *trust* band (High/Medium/Low). The workstation
wants a *direction of change* word (Stable / Increasing / Weakening /
Explosive / Collapsing). Both describe the same underlying Stage 44 and 47
reads, so the word is looked up from the parts that engine already published
rather than recomputed — `_stability_word` below is the whole of it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .theme import (ALERT, BEAR, BEAR_SOFT, BRIGHT, BULL, BULL_SOFT,
                    CARD_BG, CARD_BORDER, DANGER, FAINT, INFO, INK, MICRO,
                    MUTED, VIOLET, WARN)

_CARD = (f"background:{CARD_BG};border:1px solid {CARD_BORDER};"
         f"border-radius:10px;padding:9px 12px;margin-bottom:8px")

#: verdict → (colour, background tint). Green CALL · red PUT · grey WAIT ·
#: blue bias-only, exactly as specified.
_SIDE_COLOUR = {
    "CALL": (BULL, "rgba(0,255,136,.07)"),
    "PUT": (BEAR, "rgba(255,68,68,.07)"),
    "WAIT": (MICRO, "rgba(140,150,170,.05)"),
    "BIAS": (INFO, "rgba(77,166,255,.07)"),
}

_QUALITY_COLOUR = {"A+": BULL, "A": BULL_SOFT, "B": WARN,
                   "C": ALERT, "AVOID": DANGER, "UNKNOWN": FAINT}

_RISK_COLOUR = {"LOW": BULL, "MEDIUM": WARN, "HIGH": ALERT,
                "EXTREME": DANGER, "UNKNOWN": FAINT}

_TIMING_COLOUR = {"NOW": BULL, "PREPARE": WARN, "WAIT": MICRO,
                  "LATE": ALERT, "MISSED": DANGER}

#: Stage 44 flow word → the workstation's Stability word. Checked first,
#: because a repriced tape overrides whatever the bias was doing.
_FLOW_WORD = {"shifted": ("Explosive", DANGER),
              "shock": ("Explosive", DANGER),
              "unstable": ("Explosive", ALERT),
              "settling": ("Weakening", WARN)}

#: Stage 47 transition word → the same vocabulary
_TRANSITION_WORD = {"strengthening": ("Increasing", BULL),
                    "stable": ("Stable", BULL_SOFT),
                    "weakening": ("Weakening", WARN),
                    "in transition": ("Weakening", ALERT),
                    "reversing": ("Collapsing", DANGER)}

_ROTATION_ARROW = {"CONTINUATION": "→", "ROTATION": "⇄", "BUILDING": "↑",
                   "FADING": "↓", "NONE": "·", "UNKNOWN": "·"}


def _num(v, d=0.0):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return d if x != x else x


def _verdict_kind(row: Dict[str, Any]) -> str:
    if row.get("side") in ("CALL", "PUT"):
        return row["side"]
    if "bias" in row:
        return "BIAS"
    return "WAIT"


def _stability_word(stab: Optional[Dict[str, Any]]) -> tuple:
    """The workstation's Stability word, looked up from Stage 44/47's own
    published parts. No recomputation — see the module docstring."""
    parts = {p.get("label"): str(p.get("value") or "").lower()
             for p in ((stab or {}).get("parts") or [])}
    flow = _FLOW_WORD.get(parts.get("Flow", ""))
    if flow:
        return flow
    return _TRANSITION_WORD.get(parts.get("Bias", ""), ("Stable", BULL_SOFT))


# ══════════════════════════════════════════════════════════════════════
#  1-2 · the header: best and second opportunity
# ══════════════════════════════════════════════════════════════════════

def header_html(matrix: Optional[Dict[str, Any]]) -> str:
    """BEST OPPORTUNITY + Second, always both. The market always has another
    possibility, and hiding it is how a screen creates tunnel vision."""
    m = matrix or {}
    best = m.get("best_trade")
    stab_word, stab_col = _stability_word(m.get("stability"))

    if not best:
        return _no_trade_html(m.get("no_trade"), stab_word, stab_col)

    i = best.get("intel") or {}
    side = best.get("side") or "—"
    col, tint = _SIDE_COLOUR.get(side, _SIDE_COLOUR["WAIT"])
    q = (i.get("quality") or {}).get("grade", "—")
    rk = (i.get("risk") or {}).get("level", "—")
    tm = (i.get("timing") or {}).get("timing", "—")
    lf = (i.get("lifetime") or {}).get("label", "—")
    typ = (i.get("type") or {}).get("label", "—")
    rot = i.get("rotation") or {}

    cells = [
        ("Quality", q, _QUALITY_COLOUR.get(q, "#cfd9e6")),
        ("Confidence", f"{_num(best.get('confidence')):.0f}%", "#ffffff"),
        ("Risk", rk, _RISK_COLOUR.get(rk, "#cfd9e6")),
        ("Timing", tm, _TIMING_COLOUR.get(tm, "#cfd9e6")),
        ("Lifetime", lf, "#cfd9e6"),
        ("Rotation", f"{_ROTATION_ARROW.get(rot.get('rotation'), '·')} "
                     f"{rot.get('label', '—')}", VIOLET),
        ("Energy", _energy_label(m.get("energy")), _energy_colour(m.get("energy"))),
        ("Stability", stab_word, stab_col),
    ]
    grid = "".join(
        f"<div><div style='font-size:9px;letter-spacing:.1em;color:{MICRO};"
        f"text-transform:uppercase'>{lbl}</div>"
        f"<div style='font-size:13.5px;font-weight:800;color:{c}'>{val}</div>"
        f"</div>" for lbl, val, c in cells)

    second = _second_html(m.get("second_choice"))
    return (
        f"<div style='{_CARD};border:2px solid {col};background:{tint}'>"
        f"<div style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"text-transform:uppercase;margin-bottom:3px'>Best opportunity"
        f" · {best.get('horizon', '')}</div>"
        f"<div style='display:flex;align-items:baseline;gap:10px;"
        f"flex-wrap:wrap'>"
        f"<span style='font-size:26px;font-weight:900;color:{col}'>{side}</span>"
        f"<span style='font-size:15px;font-weight:700;color:{BRIGHT}'>{typ}</span>"
        f"<span style='font-size:14px;color:{WARN}'>{_stars_for(best)}</span>"
        f"<span style='margin-left:auto;font-size:12px;color:{MICRO}'>"
        f"score {_num(best.get('score')):.0f} · {best.get('evidence', '')}</span>"
        f"</div>"
        f"<div style='display:grid;grid-template-columns:repeat(auto-fit,"
        f"minmax(88px,1fr));gap:7px;margin-top:8px'>{grid}</div>"
        f"</div>" + second)


#: Stage 37 state → (word, colour). The engine already labels itself; this
#: only shortens the label for a header cell.
_ENERGY_TONE = {"COMPRESSION": ("Coiling", WARN),
                "EXPANSION": ("Releasing", BULL),
                "RELEASE": ("Releasing", BULL),
                "EXHAUSTION": ("Fading", ALERT),
                "NEUTRAL": ("Flat", MUTED)}


def _energy_label(en: Optional[Dict[str, Any]]) -> str:
    """Stage 37's market energy — the real one.

    Two other things on this panel were once called "energy": the rotation
    cell (now labelled Rotation, which is what it always was) and the
    bull/bear vote bar (now Balance). Stage 37's actual read — is the market
    coiling or releasing, and how ready is it to go — was computed every cycle
    and shown nowhere.
    """
    d = en or {}
    state = str(d.get("state") or "").upper()
    if not state:
        return "—"
    word = _ENERGY_TONE.get(state, (state.title(), MUTED))[0]
    rel = d.get("release_probability")
    return f"{word} {rel:.0f}%" if isinstance(rel, (int, float)) and rel else word


def _energy_colour(en: Optional[Dict[str, Any]]) -> str:
    state = str((en or {}).get("state") or "").upper()
    return _ENERGY_TONE.get(state, ("", FAINT))[1]


def _stars_for(row: Dict[str, Any]) -> str:
    n = max(0, min(5, int(round(_num(row.get("score")) / 20.0))))
    return "★" * n + "☆" * (5 - n)


def _second_html(second: Optional[Dict[str, Any]]) -> str:
    """Never hidden — the market always has another possibility."""
    if not second:
        return (f"<div style='{_CARD};border-left:3px solid {CARD_BORDER}'>"
                f"<span style='font-size:9.5px;letter-spacing:.14em;"
                f"color:{MICRO};text-transform:uppercase'>Second best</span>"
                f"<div style='font-size:13px;color:{MICRO};margin-top:2px'>"
                f"Only one horizon qualified this cycle.</div></div>")
    i = second.get("intel") or {}
    side = second.get("side") or "—"
    col, _ = _SIDE_COLOUR.get(side, _SIDE_COLOUR["WAIT"])
    tm = (i.get("timing") or {}).get("timing", "—")
    q = (i.get("quality") or {}).get("grade", "—")
    rot = (i.get("rotation") or {}).get("label", "—")
    return (
        f"<div style='{_CARD};border-left:3px solid {col}'>"
        f"<div style='display:flex;align-items:baseline;gap:9px;"
        f"flex-wrap:wrap'>"
        f"<span style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"text-transform:uppercase'>Second best</span>"
        f"<span style='font-size:17px;font-weight:900;color:{col}'>{side}</span>"
        f"<span style='font-size:12.5px;color:{WARN}'>{_stars_for(second)}</span>"
        f"<span style='font-size:12.5px;font-weight:800;"
        f"color:{_TIMING_COLOUR.get(tm, '#cfd9e6')}'>{tm}</span>"
        f"<span style='font-size:12.5px;color:{MUTED}'>Quality {q}</span>"
        f"<span style='font-size:12px;color:{VIOLET}'>{rot}</span>"
        f"<span style='margin-left:auto;font-size:12px;color:{MICRO}'>"
        f"{second.get('horizon', '')}</span></div></div>")


def _no_trade_html(nt: Optional[Dict[str, Any]], word: str, col: str) -> str:
    """Never a bare WAIT — Stage 67's rule, at the panel level."""
    d = nt or {}
    reasons = "".join(
        f"<li style='margin:1px 0'>{r}</li>" for r in (d.get("reasons") or []))
    return (
        f"<div style='{_CARD};border:2px solid {MICRO}'>"
        f"<div style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"text-transform:uppercase'>Best opportunity</div>"
        f"<div style='font-size:20px;font-weight:900;color:{MUTED};"
        f"margin-top:2px'>{d.get('headline', 'No high-quality opportunity')}"
        f"</div>"
        + (f"<ul style='margin:6px 0 0 16px;padding:0;font-size:12.5px;"
           f"color:{MICRO}'>{reasons}</ul>" if reasons else "")
        + f"<div style='margin-top:6px;font-size:13px;font-weight:800;"
          f"color:#ffcc33'>{d.get('recommendation', 'Stay flat')}</div>"
          f"<div style='margin-top:3px;font-size:11.5px;color:{MICRO}'>"
          f"Stability {word}</div></div>")


# ══════════════════════════════════════════════════════════════════════
#  3-7 · the compact five-row matrix
# ══════════════════════════════════════════════════════════════════════

#: Stage 71.7 agreement → (glyph, colour). CONTRADICTED must catch the eye: a
#: horizon ranking high while its premium is untraded is the expensive case.
_PREMIUM_AGREE = {"CONFIRMED_HOT": ("🚀", "#ff2d55"), "CONFIRMED": ("✅", BULL),
                  "CONTRADICTED": ("⚠️", "#ff9500"), "NO_SIDE": ("·", FAINT),
                  "N/A": ("—", FAINT), "UNKNOWN": ("⚪", FAINT)}


def _premium_cell(pr: Optional[Dict[str, Any]]) -> str:
    """Stage 71.7's read of the premium THIS horizon names.

    Stage 71 says which horizon and which side; 71.7 says whether that premium
    is actually being traded. Joining them in the row is the point — a ⚠️ here
    means the evidence is directional but the option is dead, which no other
    column on this table can express.
    """
    if not pr:
        return f"<td style='padding:4px 6px;color:{FAINT}'>—</td>"
    glyph, col = _PREMIUM_AGREE.get(str(pr.get("agreement") or "UNKNOWN"),
                                    _PREMIUM_AGREE["UNKNOWN"])
    en, sp = _num(pr.get("energy"), -1), _num(pr.get("spike"), -1)
    nums = ("" if en < 0 else
            f"<div style='font-size:9.5px;color:{MICRO};font-weight:600'>"
            f"{en:.0f}%" + ("" if sp < 0 else f" / {sp:.0f}%") + "</div>")
    return (f"<td style='padding:4px 6px;color:{col};font-weight:800'>"
            f"{glyph}{nums}</td>")


def matrix_html(matrix: Optional[Dict[str, Any]] = None,
                premium: Optional[Dict[str, Any]] = None) -> str:
    """One row per horizon. This is the whole always-visible budget — the
    charts have to survive underneath it.

    `premium` is Stage 71.7's output. Optional: the table renders identically
    without it, so 71.7 failing can never blank the matrix.
    """
    m = matrix or {}
    rows = {r["horizon"]: r for r in (m.get("rows") or [])}
    order = m.get("display_order") or list(rows)
    if not rows:
        return ""
    prem = {str(p.get("horizon")): p
            for p in ((premium or {}).get("horizons") or [])}

    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    head = (f"<tr style='font-size:9px;letter-spacing:.09em;color:{MICRO};"
            "text-transform:uppercase;text-align:left'>"
            "<th style='padding:3px 6px'></th><th style='padding:3px 6px'>Horizon</th>"
            "<th style='padding:3px 6px'>Side</th><th style='padding:3px 6px'>Type</th>"
            "<th style='padding:3px 6px'>Q</th><th style='padding:3px 6px'>Timing</th>"
            "<th style='padding:3px 6px'>Risk</th>"
            "<th style='padding:3px 6px'>Rotation</th>"
            "<th style='padding:3px 6px'>Premium</th>"
            "<th style='padding:3px 6px'>Balance</th>"
            "<th style='padding:3px 6px'>Evidence</th>"
            "<th style='padding:3px 6px;text-align:right'>Score</th></tr>")

    body = []
    for h in order:
        r = rows.get(h)
        if not r:
            continue
        i = r.get("intel") or {}
        kind = _verdict_kind(r)
        col, tint = _SIDE_COLOUR[kind]
        verdict = r.get("side") or r.get("verdict") or "—"
        q = (i.get("quality") or {}).get("grade", "—")
        tm = (i.get("timing") or {}).get("timing", "—")
        rk = (i.get("risk") or {}).get("level", "—")
        rot = i.get("rotation") or {}
        body.append(
            f"<tr style='background:{tint}'>"
            f"<td style='padding:4px 6px'>{medal.get(r.get('rank'), '')}</td>"
            f"<td style='padding:4px 6px;font-weight:800;color:{BRIGHT}'>"
            f"{h}<div style='font-size:9.5px;color:{MICRO};font-weight:600'>"
            f"{(i.get('lifetime') or {}).get('base', '')}</div></td>"
            f"<td style='padding:4px 6px;font-weight:900;color:{col}'>{verdict}"
            f"<div style='font-size:9.5px;color:{WARN};font-weight:600'>"
            f"{_stars_for(r)}</div></td>"
            f"<td style='padding:4px 6px;color:{MUTED}'>"
            f"{(i.get('type') or {}).get('label', '—')}</td>"
            f"<td style='padding:4px 6px;font-weight:800;"
            f"color:{_QUALITY_COLOUR.get(q, '#cfd9e6')}'>{q}</td>"
            f"<td style='padding:4px 6px;font-weight:800;"
            f"color:{_TIMING_COLOUR.get(tm, '#cfd9e6')}'>{tm}</td>"
            f"<td style='padding:4px 6px;font-weight:700;"
            f"color:{_RISK_COLOUR.get(rk, '#cfd9e6')}'>{rk}</td>"
            f"<td style='padding:4px 6px;color:{VIOLET};font-size:11.5px'>"
            f"{_ROTATION_ARROW.get(rot.get('rotation'), '·')} "
            f"{rot.get('label', '—')}</td>"
            + _premium_cell(prem.get(str(h))) +
            f"<td style='padding:4px 6px'>{_energy_bar(r)}</td>"
            f"<td style='padding:4px 6px;color:{MUTED};font-size:11.5px'>"
            f"{r.get('evidence', '—')}</td>"
            f"<td style='padding:4px 6px;text-align:right;font-weight:900;"
            f"color:{BRIGHT}'>{_num(r.get('score')):.0f}</td></tr>")

    return (f"<div style='{_CARD};overflow-x:auto'>"
            f"<table style='width:100%;border-collapse:collapse;"
            f"font-size:12.5px'>{head}{''.join(body)}</table></div>")


def _energy_bar(row: Dict[str, Any]) -> str:
    """Bull vs bear producers for THIS horizon — the counts Stage 71 already
    published. Not a global CALL/PUT energy score: no engine produces one, and
    inventing it here would be exactly the fabrication this panel exists to
    avoid displaying."""
    bull, bear = int(row.get("bull") or 0), int(row.get("bear") or 0)
    total = bull + bear
    if not total:
        return f"<span style='color:{FAINT};font-size:11px'>—</span>"
    bp = 100.0 * bull / total
    return (f"<div style='display:flex;align-items:center;gap:5px'>"
            f"<span style='display:inline-block;width:46px;height:6px;"
            f"background:{BEAR};border-radius:3px;overflow:hidden'>"
            f"<span style='display:block;width:{bp:.0f}%;height:6px;"
            f"background:{BULL}'></span></span>"
            f"<span style='font-size:10.5px;color:{MICRO}'>{bull}/{bear}</span>"
            f"</div>")


# ══════════════════════════════════════════════════════════════════════
#  8-10, 13 · the detail, behind expanders
# ══════════════════════════════════════════════════════════════════════

def detail_html(row: Optional[Dict[str, Any]]) -> str:
    """One horizon's full reasoning — rendered inside an expander so it costs
    the charts nothing."""
    r = row or {}
    i = r.get("intel") or {}
    q = i.get("quality") or {}
    rk = i.get("risk") or {}

    def _block(title, items, colour="#cfd9e6"):
        if not items:
            return ""
        li = "".join(f"<li style='margin:1px 0'>{x}</li>" for x in items)
        return (f"<div style='margin-top:6px'><div style='font-size:9.5px;"
                f"letter-spacing:.11em;color:{MICRO};text-transform:uppercase'>"
                f"{title}</div><ul style='margin:2px 0 0 16px;padding:0;"
                f"font-size:12.5px;color:{colour}'>{li}</ul></div>")

    facts = [
        ("Type", (i.get("type") or {}).get("label"),
         (i.get("type") or {}).get("source")),
        ("Quality", q.get("grade"), q.get("reason")),
        ("Risk", rk.get("level"), rk.get("reason") or ""),
        ("Timing", (i.get("timing") or {}).get("timing"),
         (i.get("timing") or {}).get("source")),
        ("Lifetime", (i.get("lifetime") or {}).get("label"),
         " · ".join((i.get("lifetime") or {}).get("notes") or [])),
        ("Maturity", (i.get("maturity") or {}).get("maturity"),
         (i.get("maturity") or {}).get("source")),
        ("Rotation", (i.get("rotation") or {}).get("label"),
         (i.get("rotation") or {}).get("source")),
    ]
    fact_html = "".join(
        f"<div style='display:flex;gap:8px;font-size:12.5px;margin:2px 0;"
        f"flex-wrap:wrap'>"
        f"<span style='min-width:70px;color:{MICRO}'>{k}</span>"
        f"<b style='color:{BRIGHT}'>{v or '—'}</b>"
        f"<span style='color:{FAINT};font-size:11.5px'>{why or ''}</span></div>"
        for k, v, why in facts)

    # 9 · Why — the confidence breakdown, this horizon's own producers
    bd = i.get("breakdown") or []
    why_html = ""
    if bd:
        why_html = ("<div style='margin-top:7px'><div style='font-size:9.5px;"
                    f"letter-spacing:.11em;color:{MICRO};text-transform:"
                    "uppercase'>Why</div><div style='display:grid;"
                    "grid-template-columns:repeat(auto-fit,minmax(150px,1fr));"
                    "gap:2px 10px;margin-top:2px'>"
                    + "".join(
                        f"<div style='font-size:12px;display:flex;gap:6px'>"
                        f"<span style='color:{MUTED};overflow:hidden;"
                        f"text-overflow:ellipsis;white-space:nowrap'>"
                        f"{b.get('label')}</span>"
                        f"<span style='margin-left:auto;color:{WARN}'>"
                        f"{b.get('stars')}</span></div>" for b in bd[:12])
                    + "</div></div>")

    # the quality components, each naming its stage
    comp = q.get("components") or []
    comp_html = ""
    if comp:
        comp_html = ("<div style='margin-top:6px'><div style='font-size:9.5px;"
                     f"letter-spacing:.11em;color:{MICRO};text-transform:"
                     "uppercase'>Quality components</div>"
                     + "".join(
                         f"<div style='font-size:12px;display:flex;gap:8px'>"
                         f"<span style='color:{MUTED}'>{c.get('label')}</span>"
                         f"<span style='margin-left:auto;color:{WARN}'>"
                         f"{c.get('stars')}</span></div>" for c in comp)
                     + "</div>")

    return (f"<div>{fact_html}{why_html}{comp_html}"
            + _block("Weakness", i.get("weakness"), "#ff9d9d")
            + _block("Why not ranked higher", r.get("lost_because"), "#ffcc66")
            + "</div>")


def reference_html(matrix: Optional[Dict[str, Any]]) -> str:
    """The aggregates and everything excluded, with reasons. Debugging a
    matrix that looks wrong starts here."""
    m = matrix or {}
    ref = m.get("reference") or []
    exc = m.get("excluded") or []
    ref_rows = "".join(
        f"<div style='font-size:12.5px;display:flex;gap:8px;margin:1px 0;"
        f"flex-wrap:wrap'>"
        f"<span style='color:{MUTED};flex:1 1 150px'>{x.get('id')}</span>"
        f"<b style='color:{BRIGHT}'>{x.get('bias')}</b>"
        f"<span style='color:{MICRO}'>{x.get('confidence')}</span>"
        f"<span style='margin-left:auto;color:{FAINT};font-size:11px'>"
        f"non-voting</span></div>" for x in ref)
    exc_rows = "".join(
        f"<div style='font-size:11.5px;display:flex;gap:8px;margin:1px 0;"
        f"flex-wrap:wrap'>"
        f"<span style='color:{MICRO};flex:1 1 150px'>{x.get('id')}</span>"
        f"<span style='color:{FAINT}'>{x.get('reason')}</span></div>"
        for x in exc)
    return (
        f"<div style='font-size:9.5px;letter-spacing:.11em;color:{MICRO};"
        f"text-transform:uppercase'>Reference — shown, never counted</div>"
        f"{ref_rows or '<div style=font-size:12px;color:{FAINT}>none</div>'}"
        f"<div style='font-size:9.5px;letter-spacing:.11em;color:{MICRO};"
        f"text-transform:uppercase;margin-top:8px'>Excluded — {len(exc)} "
        f"producers</div>{exc_rows}")


# ══════════════════════════════════════════════════════════════════════
#  The panel
# ══════════════════════════════════════════════════════════════════════

def render_opportunity_panel(st, matrix: Optional[Dict[str, Any]],
                             premium: Optional[Dict[str, Any]] = None) -> None:
    """Header + second + compact matrix always visible; everything else in
    expanders so the terminal chart keeps its space.

    `premium` is Stage 71.7 (Premium Energy & Spike). It belongs HERE rather
    than in its own section: Stage 71 says which horizon and which side, and
    71.7 says whether that premium is actually being traded. Split across two
    places, a trader reads the ranking without the confirmation. Optional
    throughout — 71.7 failing must never blank the matrix.
    """
    if not matrix or not matrix.get("rows"):
        st.caption("Trade Opportunity Matrix warming up — it renders once the "
                   "MIOS pass has published a final read.")
        return

    st.markdown(header_html(matrix), unsafe_allow_html=True)
    st.markdown(matrix_html(matrix, premium), unsafe_allow_html=True)
    if premium:
        try:
            from .premium_energy_panel import premium_energy_html
            _pe_html = premium_energy_html(premium)
            if _pe_html:
                st.markdown(_pe_html, unsafe_allow_html=True)
        except Exception as err:
            st.caption(f"Premium Energy unavailable: {err}")

    rows = {r["horizon"]: r for r in matrix["rows"]}
    with st.expander("🔍 Horizon detail — type · quality · risk · why · weakness",
                     expanded=False):
        for h in (matrix.get("display_order") or list(rows)):
            r = rows.get(h)
            if not r:
                continue
            st.markdown(
                f"<div style='font-size:13px;font-weight:900;color:{BRIGHT};"
                f"border-top:1px solid #1e2836;padding-top:6px;margin-top:4px'>"
                f"{h.upper()}</div>", unsafe_allow_html=True)
            st.markdown(detail_html(r), unsafe_allow_html=True)

    with st.expander("📋 Reference & excluded producers", expanded=False):
        st.markdown(reference_html(matrix), unsafe_allow_html=True)
        st.caption(
            "Aggregates are shown because a matrix that disagrees with the V5 "
            "headline is the most useful thing on this panel — and they never "
            "vote because a composite voting would re-count its own members.")