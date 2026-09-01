"""Stage 71.7 — the Premium Energy section, drawn below Market Energy.

Pure presentation. Every number here was computed by `mios_v5.premium_energy`;
this file decides only where it sits and what colour it is. If a value is
`None` it renders as `—`, never as `0%` — a bar at zero asserts a measurement
nobody took.

The two rows are deliberately the same size. Energy and Spike answer different
questions ("who is participating" vs "what could explode"), and drawing one
larger than the other tells the trader which to believe, which is not this
panel's call to make.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .theme import (ALERT, BEAR, BULL, BULL_SOFT, DANGER, FAINT, INK, MICRO,
                    MUTED, VIOLET, WARN)

_CALL_COL = BULL
_PUT_COL = BEAR

#: spike band → colour. Extreme is the only one that gets an alarm colour.
_BAND_COL = {"Very Low": MUTED, "Low": MUTED, "Moderate": WARN,
             "High": ALERT, "Extreme": DANGER, "Unknown": FAINT}

#: the six measured Shift states, plus Holding and UNKNOWN. Building and
#: Distributing are Stage 50's words and get Stage 50's reading, not a direction
#: colour — "Distributing" is not a fall, it is writers selling into the move.
_SHIFT_COL = {"Exploding": DANGER, "Increasing": BULL, "Decreasing": WARN,
              "Building": BULL_SOFT, "Distributing": ALERT,
              "Compressing": VIOLET, "Holding": MUTED, "UNKNOWN": FAINT}


def _pct(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _bar(label: str, value, col: str, *, width_label: int = 62) -> str:
    """One labelled bar. `None` draws an empty track and the word `—`."""
    p = _pct(value)
    fill = "" if p is None else (
        f"<div style='width:{max(2.0, min(100.0, p))}%;height:100%;"
        f"background:{col}'></div>")
    shown = "—" if p is None else f"{p:.0f}%"
    return (f"<div style='display:flex;align-items:center;gap:7px;margin-top:3px'>"
            f"<span style='width:{width_label}px;color:{INK};font-size:11px;"
            f"font-weight:700'>{label}</span>"
            f"<div style='flex:1;min-width:0;height:8px;background:#1e2836;"
            f"border-radius:4px;overflow:hidden'>{fill}</div>"
            f"<span style='width:38px;text-align:right;font-size:11.5px;"
            f"font-weight:800;color:{col if p is not None else FAINT}'>"
            f"{shown}</span></div>")


def _chip(label: str, value: str, col: str) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:9px;letter-spacing:.1em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:12.5px;font-weight:800;color:{col}'>"
            f"{value}</div></div>")


def _trigger_html(trigger: Optional[str]) -> str:
    """**One** trigger, because the engine now reports one.

    The old row said "Top trigger" and then printed three, which reads as three
    findings when the priority order exists precisely to say which one is
    carrying the setup.
    """
    if not trigger:
        return ""
    return (f"<div style='font-size:11.5px;margin-top:5px;color:{MUTED}'>"
            f"Top trigger <b style='color:{VIOLET}'>{trigger}</b></div>")


def _reasons_html(reasons: Optional[List[Dict[str, Any]]]) -> str:
    """Up to five contributors, each tagged with the side it came from.

    The engine publishes these as codes; the panel is the only place they become
    words, so a downstream stage never has to parse a sentence.
    """
    if not reasons:
        return ""
    items = []
    for r in reasons[:5]:
        side = r.get("side")
        tag = ("" if not side else
               f"<span style='color:{_CALL_COL if side == 'CALL' else _PUT_COL};"
               f"font-size:9.5px'> {side}</span>")
        items.append(f"<span style='color:{INK}'>{r.get('label') or '—'}</span>{tag}")
    return (f"<div style='font-size:11px;margin-top:4px;color:{MUTED}'>"
            f"Why · " + " <span style='color:#2a3546'>|</span> ".join(items)
            + "</div>")


#: agreement → (glyph, colour). CONTRADICTED is the one that must catch the eye:
#: a horizon ranking high while its premium is dead is the expensive case.
_AGREE = {"CONFIRMED_HOT": ("🚀", DANGER), "CONFIRMED": ("✅", BULL),
          "CONTRADICTED": ("⚠️", ALERT), "NO_SIDE": ("·", FAINT),
          "N/A": ("—", FAINT), "UNKNOWN": ("⚪", FAINT)}


def _horizons_html(rows: Optional[List[Dict[str, Any]]]) -> str:
    """Per-horizon cross-check: scalp / midday / intraday / positional / swing
    against the premium each one names.

    Stage 71 ranks the horizons; this column says whether the premium behind the
    recommendation is actually being traded. A row reading
    `intraday CALL ⚠️ 18%` is a horizon whose evidence is directional but whose
    option has no participation — the case worth stopping on.
    """
    if not rows:
        return ""
    out = []
    for r in rows:
        glyph, col = _AGREE.get(str(r.get("agreement") or "UNKNOWN"),
                                _AGREE["UNKNOWN"])
        side = r.get("side") or "—"
        en, sp = _pct(r.get("energy")), _pct(r.get("spike"))
        nums = ("" if en is None else
                f" <b style='color:{col}'>{en:.0f}%</b>"
                + ("" if sp is None else
                   f"<span style='color:{MICRO}'> / {sp:.0f}%</span>"))
        out.append(
            f"<div style='display:flex;gap:6px;align-items:baseline;"
            f"font-size:11px;padding:1px 0'>"
            f"<span style='width:66px;color:{MUTED};text-transform:capitalize'>"
            f"{r.get('horizon') or '—'}</span>"
            f"<span style='width:34px;color:{INK};font-weight:700'>{side}</span>"
            f"<span>{glyph}{nums}</span>"
            f"<span style='color:{FAINT};min-width:0'>{r.get('note') or ''}</span>"
            f"</div>")
    return (f"<div style='margin-top:8px;border-top:1px solid #1e2836;"
            f"padding-top:6px'>"
            f"<div style='font-size:10px;letter-spacing:.12em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:3px'>"
            f"Horizon × premium — energy / spike</div>"
            + "".join(out) + "</div>")


def premium_energy_html(data: Optional[Dict[str, Any]]) -> str:
    """The whole section, or `""` when Stage 71.7 has nothing to say.

    An empty string rather than a hollow card: the Validation expander already
    carries four panels, and a fifth reading "—" everywhere is noise.
    """
    d = data or {}
    if not d.get("ready"):
        return ""

    call = d.get("call") or {}
    put = d.get("put") or {}
    bal = d.get("balance") or {}
    shift = d.get("shift") or {}
    rot = d.get("rotation") or {}
    stab = d.get("stability") or {}

    dom = d.get("dominance")
    dom_col = (_CALL_COL if dom == "CALL Dominant" else
               _PUT_COL if dom == "PUT Dominant" else
               FAINT if dom == "No Energy" else MUTED)

    energy_rows = (_bar("CALL", call.get("energy"), _CALL_COL)
                   + _bar("PUT", put.get("energy"), _PUT_COL))
    spike_rows = (_bar("CALL", call.get("spike"), _CALL_COL)
                  + _bar("PUT", put.get("spike"), _PUT_COL))

    def _shift_txt(side: str) -> str:
        """The state word with its acceleration, because either alone misleads.

        "Increasing" says nothing about whether the rise is 6 points or 26;
        "+18" says nothing about whether writers or buyers produced it. A `↑`
        beside the number marks the change speeding up — that reading needs a
        third cycle, so it stays absent rather than showing a neutral glyph."""
        s = shift.get(side) or {}
        label = s.get("label") or "—"
        acc = _pct(s.get("acceleration"))
        if acc is None:
            return label
        speed = {"UP": " ↑", "DOWN": " ↓"}.get(
            str((s.get("accelerating") or {}).get("state")), "")
        return f"{label} <span style='font-weight:600'>{acc:+.0f}{speed}</span>"

    def _shift_col(side: str) -> str:
        s = shift.get(side) or {}
        return _SHIFT_COL.get(str(s.get("state") or "UNKNOWN"), FAINT)

    bal_txt = ("—" if bal.get("CALL") is None
               else f"CALL {bal['CALL']}% · PUT {bal['PUT']}%")
    rot_txt = rot.get("label") or "—"
    # Stage 44's own word, with Stage 71's band beside it rather than instead of
    # it — the band ranks, the word is what Stage 44 actually published.
    stab_word = stab.get("word")
    stab_txt = (f"{stab.get('emoji') or ''} {stab_word or stab.get('band') or '—'}"
                .strip())

    pref = d.get("preferred") or {}
    pref_txt = pref.get("preferred") or "—"
    pref_side = pref.get("side")
    pref_col = (_CALL_COL if pref_side == "CALL" else
                _PUT_COL if pref_side == "PUT" else MUTED)

    conf = d.get("confidence") or {}
    grade = conf.get("grade") or "UNKNOWN"
    conf_col = {"A+": BULL, "A": BULL, "B": WARN,
                "C": ALERT}.get(grade, FAINT)

    chips = "".join([
        # Preferred and Confidence lead: they are the two answers a trader looks
        # for, and burying them behind Balance made the panel read as telemetry.
        _chip("Preferred", pref_txt, pref_col),
        _chip("Confidence", grade, conf_col),
        _chip("Dominance", dom or "—", dom_col),
        _chip("CALL shift", _shift_txt("CALL"), _shift_col("CALL")),
        _chip("PUT shift", _shift_txt("PUT"), _shift_col("PUT")),
        _chip("Rotation", rot_txt, VIOLET),
        _chip("Balance", bal_txt, INK),
        _chip("Stability", stab_txt, BULL_SOFT),
    ])

    def _vol(v) -> str:
        """Volumes in the units a trader reads them in — 18.4M, not 18400000."""
        n = _pct(v)
        if n is None:
            return "—"
        a = abs(n)
        for cut, suf in ((1e7, "Cr"), (1e5, "L"), (1e3, "K")):
            if a >= cut:
                return f"{n / cut:.1f}{suf}"
        return f"{n:.0f}"

    def _flow_line(side_d: Dict[str, Any], name: str, col: str) -> str:
        """CBV · CSV · CVD, shown because they are the mandatory input.

        A score whose largest contributor is invisible cannot be checked. These
        are the raw sums from `indicators/order_flow.totals`, per side, so a
        trader can see that CALL took 18.4Cr of buying against 8.6Cr of selling
        rather than being asked to trust an 84.
        """
        if side_d.get("cbv") is None:
            return (f"<span style='color:{col};font-weight:800'>{name}</span> "
                    f"<span style='color:{FAINT}'>flow not reported</span>")
        share = _pct(side_d.get("buy_share"))
        return (f"<span style='color:{col};font-weight:800'>{name}</span> "
                f"<span style='color:{MUTED}'>CBV </span>"
                f"<span style='color:{BULL}'>{_vol(side_d.get('cbv'))}</span>"
                f"<span style='color:{MUTED}'> · CSV </span>"
                f"<span style='color:{BEAR}'>{_vol(side_d.get('csv'))}</span>"
                f"<span style='color:{MUTED}'> · CVD </span>"
                f"<span style='color:{INK}'>{_vol(side_d.get('cvd'))}</span>"
                + ("" if share is None else
                   f"<span style='color:{MICRO}'> ({share:.0f}% bid)</span>"))

    def _band_line(side_d: Dict[str, Any], name: str, col: str) -> str:
        band = side_d.get("spike_band") or "Unknown"
        return (f"<span style='color:{col};font-weight:800'>{name}</span> "
                f"<span style='color:{MUTED}'>{side_d.get('strength') or '—'}"
                f" energy · </span>"
                f"<span style='color:{_BAND_COL.get(band, FAINT)};"
                f"font-weight:800'>{band} spike</span>")

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
        f"text-transform:uppercase'>⚡ Premium Energy "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stage 71.7 · "
        f"advisory</span></div>"

        f"<div style='font-size:10px;letter-spacing:.12em;color:{MICRO};"
        f"text-transform:uppercase;margin-top:6px'>Energy — participation now"
        f"</div>{energy_rows}"

        f"<div style='font-size:10px;letter-spacing:.12em;color:{MICRO};"
        f"text-transform:uppercase;margin-top:8px'>🚀 Spike probability — "
        f"expansion odds</div>{spike_rows}"

        f"<div style='display:flex;flex-wrap:wrap;gap:14px;margin-top:9px'>"
        f"{chips}</div>"

        f"<div style='font-size:11.5px;margin-top:7px'>"
        f"{_band_line(call, 'CALL', _CALL_COL)}"
        f"<span style='color:{FAINT}'> | </span>"
        f"{_band_line(put, 'PUT', _PUT_COL)}</div>"

        f"<div style='font-size:11px;margin-top:4px'>"
        f"{_flow_line(call, 'CALL', _CALL_COL)}</div>"
        f"<div style='font-size:11px'>"
        f"{_flow_line(put, 'PUT', _PUT_COL)}</div>"

        + _trigger_html(d.get("top_trigger"))
        + _reasons_html(d.get("top_reasons"))
        + _horizons_html(d.get("horizons")) +

        f"<div style='font-size:13px;font-weight:800;margin-top:7px;"
        f"color:{INK}'>{d.get('conclusion') or ''}</div>"

        + missing_html +
        "</div>")


def render_premium_energy(st, data: Optional[Dict[str, Any]] = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the tab down."""
    try:
        html = premium_energy_html(data)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Premium Energy unavailable: {err}")


# ══════════════════════════════════════════════════════════════════════
#  the compact form, for the MIOS V6 trade card
# ══════════════════════════════════════════════════════════════════════

def compact_html(data: Optional[Dict[str, Any]]) -> str:
    """Stage 71.7 in three lines, for the observational card above the app.

    Same data, same colours, same owner — `premium_energy_html` draws the full
    section further down the page and this is the glance version. Nothing is
    recomputed and no number appears here that is not already in that section,
    so the two can never disagree.

    ## Both rows, always

    Energy and Spike answer different questions — *who is participating* versus
    *what could expand* — and they routinely point opposite ways. A live read of
    CALL 27 / PUT 46 energy against CALL 39 / PUT 34 spike is exactly that: the
    side with the participation is not the side with the expansion odds.

    A compact view is where that gets quietly dropped, because showing one row
    is half the space. Both are here for the same reason the full panel draws
    them the same size: choosing one for the trader is not this panel's call.

    ⚠️ The disagreement is *shown*, never *scored*. Deriving an "energy vs spike
    conflict" verdict would be new computation in a presentation file, and Stage
    71.7 has not published one.
    """
    d = data or {}
    if not d.get("ready"):
        return ""

    call, put = d.get("call") or {}, d.get("put") or {}

    def _pair(key: str) -> str:
        c, p = _pct(call.get(key)), _pct(put.get(key))
        c_txt = "—" if c is None else f"{c:.0f}%"
        p_txt = "—" if p is None else f"{p:.0f}%"
        return (f"<span style='color:{_CALL_COL};font-weight:800'>C {c_txt}</span>"
                f"<span style='color:{MICRO}'> · </span>"
                f"<span style='color:{_PUT_COL};font-weight:800'>P {p_txt}</span>")

    if all(_pct(x.get(k)) is None for x in (call, put) for k in ("energy", "spike")):
        return ""

    dom = d.get("dominance")
    dom_col = (_CALL_COL if dom == "CALL Dominant" else
               _PUT_COL if dom == "PUT Dominant" else
               FAINT if dom == "No Energy" else MUTED)

    pref = (d.get("preferred") or {}).get("label") or d.get("preferred_label")
    grade = (d.get("confidence") or {}).get("grade") if isinstance(
        d.get("confidence"), dict) else d.get("confidence")

    # Absent is absent: a missing preference draws no chip rather than "—".
    tail = " · ".join(x for x in (
        str(pref) if pref else "",
        f"conf {grade}" if grade else "",
        str(dom) if dom else "") if x)

    return (
        f"<div style='margin-top:5px;padding:6px 9px;background:#0b0f16;"
        f"border:1px solid #1e2836;border-radius:8px;text-align:center'>"
        f"<div style='font-size:9px;letter-spacing:.09em;color:{MICRO};"
        f"text-transform:uppercase'>⚡ Premium energy · 71.7</div>"
        f"<div style='font-size:12.5px;margin-top:2px'>"
        f"<span style='color:{MICRO};font-size:10px'>energy </span>{_pair('energy')}"
        f"<span style='color:{MICRO}'>&nbsp;&nbsp;|&nbsp;&nbsp;</span>"
        f"<span style='color:{MICRO};font-size:10px'>spike </span>{_pair('spike')}"
        f"</div>"
        + (f"<div style='font-size:11px;margin-top:1px;color:{dom_col};"
           f"font-weight:700'>{tail}</div>" if tail else "")
        + "</div>")


def micro(data: Optional[Dict[str, Any]]) -> str:
    """Stage 71.7 as PLAIN TEXT for the sticky app header.

    Both rows still, in the tightest form that keeps them apart — `C46 P41`
    for participation and `spk C65 P61` for expansion. They routinely point
    opposite ways, which is exactly why the second one is not the thing to cut
    when space runs out.

    `""` when the stage is not ready or reported no numbers.
    """
    d = data or {}
    if not d.get("ready"):
        return ""
    call, put = d.get("call") or {}, d.get("put") or {}

    def _two(key: str) -> str:
        c, p = _pct(call.get(key)), _pct(put.get(key))
        if c is None and p is None:
            return ""
        c_txt = "—" if c is None else f"{c:.0f}"
        p_txt = "—" if p is None else f"{p:.0f}"
        return f"C{c_txt} P{p_txt}"

    energy, spike = _two("energy"), _two("spike")
    if not energy and not spike:
        return ""
    bits = [x for x in (f"⚡ {energy}" if energy else "",
                        f"spk {spike}" if spike else "") if x]
    return " · ".join(bits)
