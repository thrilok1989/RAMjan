"""MIOS — the slim Trade Card for Dashboard 2.

The full Trade Card lives in `vob_minimal.py` and owns the main analyser page.
This is deliberately **not** that card. It carries only what Dashboard 2 does
not already own, so the two surfaces never answer the same question twice.

## The ownership split this implements

| Owned by | |
|---|---|
| **Opportunity Matrix** (§7.7) | horizon ranking · side · quality · timing · risk · energy · rotation · stability |
| **`_sr_intelligence`** | every S/R level as a ranked object |
| **Trade Cockpit** | where in the trade life we are |
| **this card** | market facts · the V5 ‖ V6 divergence |

Three things the full card shows are therefore absent here on purpose:

* **bias, quality and timing** — the Matrix owns them, per horizon, which is
  strictly more information than one blended verdict.
* **S/R zone cards** — `_sr_intelligence` already renders them ranked, further
  down the same tab.
* **the decision row** — the Cockpit owns the Stage 52 ladder.

What is left is the pair Dashboard 2 genuinely lacks: the measurements every
version reads, and the one comparison that is *only* useful when the two
generations disagree.

## Why the divergence earns its place

The Matrix ranks horizons; it never says whether the V5 Conflict Engine and
the V6 four-voter read agree. On the days they disagree that is the most
useful thing on the screen — it is why `v6_bias.compare()` exists and why the
V5‖V6 strip is rendered at the same size on both. Showing it here costs two
lines and is not duplicated anywhere else in the tab.

Pure presentation. `market_facts` reads numbers other layers computed; the
bias strip is `bias_compare_html` unchanged, so the two cards cannot drift
into disagreeing about what V6 said.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .theme import (BEAR, BRIGHT, BULL, CARD_BG, CARD_BORDER, FAINT, INK,
                    MICRO, MINT, MUTED, WARN)

_CARD = (f"background:{CARD_BG};border:1px solid {CARD_BORDER};"
         f"border-radius:10px;padding:9px 12px;margin-bottom:8px")

#: spot's position relative to the value area → (word, colour)
_VALUE_POSITION = {"above": ("above VAH", BULL), "below": ("below VAL", BEAR),
                   "inside": ("inside VA", WARN)}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def value_position(spot, vah, val) -> Optional[tuple]:
    """Where spot sits in the value area, or None when it cannot be told.

    None rather than "inside": with no value area there is no inside, and
    defaulting to it would assert acceptance nobody measured.
    """
    s, h, l = _f(spot), _f(vah), _f(val)
    if s is None or (h is None and l is None):
        return None
    if h is not None and s > h:
        return _VALUE_POSITION["above"]
    if l is not None and s < l:
        return _VALUE_POSITION["below"]
    return _VALUE_POSITION["inside"]


def market_facts_html(spot, money_flow: Optional[Dict[str, Any]] = None,
                      gap: Optional[Dict[str, Any]] = None) -> str:
    """Spot, the value area, and the gap — measurements, not opinions.

    Every field is omitted when unmeasured rather than shown as a zero: a
    `POC ₹0` line is worse than no POC line.
    """
    mf, g = money_flow or {}, gap or {}
    s = _f(spot)
    bits = []

    if s is not None:
        bits.append(f"<span style='font-size:21px;font-weight:900;color:{INK}'>"
                    f"📍 ₹{s:,.1f}</span>")

    poc, vah, val = (_f(mf.get("poc_price")), _f(mf.get("value_area_high")),
                     _f(mf.get("value_area_low")))
    if poc or vah or val:
        parts = []
        if val:
            parts.append(f"<span style='color:{BEAR}'>VAL ₹{val:,.0f}</span>")
        if poc:
            parts.append(f"<span style='color:{WARN}'>POC ₹{poc:,.0f}</span>")
        if vah:
            parts.append(f"<span style='color:{MINT}'>VAH ₹{vah:,.0f}</span>")
        pos = value_position(s, vah, val)
        if pos:
            parts.append(f"<span style='color:{pos[1]}'>({pos[0]})</span>")
        bits.append("<span style='font-size:13px;font-weight:700'>📊 "
                    + " · ".join(parts) + "</span>")

    gt = str(g.get("type") or "")
    if gt in ("GAP-UP", "GAP-DOWN"):
        gc = BULL if gt == "GAP-UP" else BEAR
        pct = _f(g.get("pct"))
        bits.append(
            f"<span style='font-size:12.5px;font-weight:700;color:{gc}'>"
            f"{'🔺' if gt == 'GAP-UP' else '🔻'} {gt}"
            + (f" {pct:+.2f}%" if pct is not None else "") + "</span>")

    if not bits:
        return ""
    return ("<div style='display:flex;align-items:baseline;gap:12px;"
            "flex-wrap:wrap'>" + "".join(bits) + "</div>")


def slim_card_html(final_read: Optional[Dict[str, Any]] = None,
                   spot=None, money_flow: Optional[Dict[str, Any]] = None,
                   gap: Optional[Dict[str, Any]] = None) -> str:
    """Market facts + the V5 ‖ V6 divergence. Empty string when neither has
    anything to say, so the tab shows no hollow card."""
    facts = market_facts_html(spot, money_flow, gap)

    strip = ""
    try:
        from ..v6_bias import compare
        from .bias_compare import bias_compare_html
        cmp_ = compare(final_read)
        # "NO READ ‖ NO READ" is not a divergence — it is two cold engines,
        # and the strip exists to show DISagreement. Rendered on an empty
        # final read it fills a card with the absence of information.
        if any((cmp_.get(k) or {}).get("bias") not in (None, "NONE")
               for k in ("v5", "v6")):
            strip = bias_compare_html(cmp_)
    except Exception:
        strip = ""

    if not facts and not strip:
        return ""
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:4px'>Market facts"
            f"</div>{facts}{strip}</div>")


def render_slim_trade_card(st, final_read: Optional[Dict[str, Any]] = None,
                           spot=None) -> None:
    """Render into Dashboard 2. Advisory — it may never take the tab down.

    Reads the two session caches the app already publishes. It does NOT reach
    for `vob_minimal`: `mios_v5` never imports the app, and the full Trade Card
    lives there.
    """
    try:
        html = slim_card_html(
            final_read, spot,
            st.session_state.get("_money_flow_data"),
            st.session_state.get("_gap_today"))
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Market facts unavailable: {err}")
