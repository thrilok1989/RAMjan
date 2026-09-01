"""MIOS V6 — the Top Command Center, rendered.

Six cards across the top of Dashboard 2, sticky so they stay on screen while
the charts scroll underneath. Colour follows the house convention:

    green bullish · red bearish · orange building/watch · blue neutral/info
    purple dealer/gamma/charm · grey inactive

A card with nothing to say prints `—`. It never prints a stale value: a header
tile is exactly where an old number does the most damage, because it is the one
thing a trader reads without checking.

Renders values. Calculates nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..command_center import TONE

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:8px 10px;height:100%")
_LABEL = "font-size:9px;letter-spacing:.09em;color:#9fb0c4;text-transform:uppercase"
_BIG = "font-size:19px;font-weight:900;line-height:1.15"
_MID = "font-size:13px;font-weight:800"


def _c(tone: str) -> str:
    return TONE.get(tone, TONE["neutral"])


def _kv(label: str, value: Any, tone: str = "neutral") -> str:
    v = "—" if value is None or value == "" else value
    return (f"<div style='display:flex;justify-content:space-between;"
            f"align-items:baseline;margin-top:2px'>"
            f"<span style='{_LABEL}'>{label}</span>"
            f"<span style='font-size:12px;font-weight:800;color:{_c(tone)}'>"
            f"{v}</span></div>")


def _wrap(inner: str) -> str:
    return f"<div style='{_CARD}'>{inner}</div>"


def decision_html(d: Dict[str, Any]) -> str:
    conf = d.get("confidence")
    trail = d.get("trail")
    return _wrap(
        f"<div style='{_LABEL}'>{d.get('title', 'MIOS V6')}</div>"
        f"<div style='{_BIG};color:{_c(d.get('tone', 'neutral'))};"
        f"margin-top:2px'>{d.get('state', 'WAIT').replace('_', ' ')}</div>"
        + _kv("Confidence", f"{conf:.0f}%" if conf is not None else None,
              d.get("tone", "neutral"))
        + _kv("Quality", d.get("quality"), d.get("quality_tone", "neutral"))
        + _kv("Risk", d.get("risk"), d.get("risk_tone", "neutral"))
        # an unarmed trail is not a number — printing the last one would read
        # as a live level
        + _kv("Trail", (f"{trail:,.0f}" if (trail is not None and d.get("armed"))
                        else None), "dealer"))


def bias_html(b: Dict[str, Any]) -> str:
    rev = b.get("reversal_pct")
    return _wrap(
        f"<div style='{_LABEL}'>{b.get('title', 'Overall Bias')}</div>"
        f"<div style='{_BIG};color:{_c(b.get('tone', 'neutral'))};"
        f"margin-top:2px'>{b.get('bias', '—')}</div>"
        + _kv("Strength", b.get("strength"), b.get("tone", "neutral"))
        + _kv("Velocity", b.get("velocity"))
        + _kv("Transition", b.get("transition"), "watch")
        + (_kv("Reversal", f"{rev:.0f}%", "bear" if rev >= 40 else "neutral")
           if rev is not None else ""))


def state_html(s: Dict[str, Any]) -> str:
    nxt, pct = s.get("next"), s.get("next_pct")
    return _wrap(
        f"<div style='{_LABEL}'>{s.get('title', 'Market State')}</div>"
        f"<div style='{_BIG};color:{_c(s.get('tone', 'info'))};"
        f"margin-top:2px'>{s.get('state', '—')}</div>"
        + _kv("Duration", s.get("duration"))
        + (_kv("Next", f"{nxt} {pct:.0f}%", "watch")
           if nxt and pct is not None else ""))


def sr_html(sr: Dict[str, Any]) -> str:
    if sr.get("empty"):
        return _wrap(f"<div style='{_LABEL}'>{sr.get('title')}</div>"
                     f"<div style='font-size:12px;color:#9fb0c4;margin-top:4px'>"
                     f"No priced level yet.</div>")
    rows = []
    for r in sr.get("rows", [])[:9]:
        dist = f"<span style='color:#9fb0c4;font-size:10px'> {r['distance']}</span>" \
            if r.get("distance") else ""
        rows.append(
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:baseline;margin-top:1px'>"
            f"<span style='{_LABEL}'>{r['label']}</span>"
            f"<span style='font-size:11.5px;font-weight:800;"
            f"color:{_c(r['tone'])}'>{r['value']:,.0f}{dist}</span></div>")
    war = (f"<div style='margin-top:3px;font-size:11px;color:{_c('watch')}'>"
           f"War Zone {sr['war_zone']}</div>" if sr.get("war_zone") else "")
    return _wrap(f"<div style='{_LABEL}'>{sr.get('title')}</div>"
                 + "".join(rows) + war)


def controller_html(c: Dict[str, Any]) -> str:
    if c.get("empty"):
        return _wrap(f"<div style='{_LABEL}'>{c.get('title')}</div>"
                     f"<div style='font-size:12px;color:#9fb0c4;margin-top:4px'>"
                     f"No family has reported yet.</div>")
    rows = []
    for g in c.get("groups", []):
        rows.append(
            f"<div style='display:flex;justify-content:space-between;"
            f"align-items:baseline;margin-top:1px'>"
            f"<span style='{_LABEL}'>{g['name']}</span>"
            f"<span style='font-size:11px;color:{_c(g['tone'])}'>"
            f"{g['stars']}</span></div>")
    return _wrap(
        f"<div style='{_LABEL}'>{c.get('title')}</div>"
        + "".join(rows)
        + f"<div style='margin-top:4px;border-top:1px solid #1e2836;"
          f"padding-top:3px'><span style='{_LABEL}'>Winner</span> "
          f"<span style='{_MID};color:#ffffff'>{c.get('winner', '—')}</span>"
          f"</div>")


def thesis_html(t: Dict[str, Any]) -> str:
    if t.get("empty"):
        return _wrap(f"<div style='{_LABEL}'>{t.get('title')}</div>"
                     f"<div style='font-size:12px;color:#9fb0c4;margin-top:4px'>"
                     f"No thesis yet — MIOS has not formed a read.</div>")

    def block(label, items, tone):
        if not items:
            return ""
        lines = "".join(
            f"<div style='font-size:11px;color:{_c(tone)};margin-top:1px'>"
            f"• {i}</div>" for i in items)
        return f"<div style='margin-top:3px'><span style='{_LABEL}'>" \
               f"{label}</span>{lines}</div>"

    return _wrap(
        f"<div style='{_LABEL}'>{t.get('title')}</div>"
        + block("Why", t.get("why"), "info")
        + block("Expect", t.get("expect"), "bull" if t.get("has_edge") else "neutral")
        # invalidation last and always shown — the line a trader most needs
        # and least wants
        + block("Invalidation", t.get("invalidation"), "bear"))


def render_command_center(st, cc: Optional[Dict[str, Any]]) -> None:
    """The six cards, in two rows of three so they stay readable on a laptop."""
    if not cc:
        st.caption("Command Center warming up — no engine has reported yet.")
        return
    # sticky so the header stays on screen while the charts scroll under it
    st.markdown(
        "<div style='position:sticky;top:0;z-index:50;background:#0b0f16;"
        "padding-bottom:4px'></div>", unsafe_allow_html=True)

    top = st.columns(3)
    for col, html in zip(top, (decision_html(cc["decision"]),
                               bias_html(cc["bias"]),
                               state_html(cc["state"]))):
        with col:
            st.markdown(html, unsafe_allow_html=True)

    bottom = st.columns(3)
    for col, html in zip(bottom, (sr_html(cc["sr"]),
                                  controller_html(cc["controller"]),
                                  thesis_html(cc["thesis"]))):
        with col:
            st.markdown(html, unsafe_allow_html=True)
