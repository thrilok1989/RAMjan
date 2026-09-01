"""The app's own header, footer and browser-tab title.

Pure presentation. Spot, the biases and the market clock all arrive as
parameters — this file decides where they sit and what colour they are, and
computes nothing.

## This is not the V6 header

`header_panel.py` draws the tile strip *inside* the MIOS V6 dashboard: eight
engine readings for one screen. This draws the strip *above the whole app*, and
it carries exactly three things — where price is, what the two engines think,
and whether the market is open. A trader on the commodity tab or the news tab
can still see those; that is the entire reason it exists.

Deliberately narrow. If it grew a fourth and fifth reading it would become a
second V6 header rendered twice on the V6 tab, which is the duplication the
repo has been removing all week.

## Colour in a browser tab is one emoji

A tab renders plain text. There is no styling, no markup and no colour — so the
bias travels as 🟢 / 🔴 / ⚪, which is the only coloured glyph a tab can show.
The header carries the real colour, because it can.

## Why the title needs JavaScript

`st.set_page_config(page_title=…)` must be the first Streamlit call of the
script and may only run **once**, so it can never carry a live price: at the
moment it runs, the cycle has not fetched anything. The tab title is therefore
set by assigning `parent.document.title` from a zero-height component, which is
the only way to change it after the page exists.

## Nothing is invented

A spot that has not arrived leaves the price out of the title rather than
printing a zero, and a bias nobody reported is `⚪` — the neutral glyph, not a
guess at a direction.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

from .theme import (BEAR, BULL, FAINT, GRID, INK, MICRO, MUTED, PANEL_BG,
                    bias_emoji, bias_tone)

UNKNOWN = "UNKNOWN"

#: The app's name, in one place. The `st.title` it replaces hard-coded it.
APP_NAME = "Nifty Trading & Options Analyzer"

#: Shown in the footer so a screenshot says which build produced it.
CHROME_VERSION = "chrome.2"

#: Marker classes. The CSS below cannot target the strip directly — see
#: `chrome_css` for why it has to reach the wrapper Streamlit puts around it.
HEADER_CLASS = "mios-chrome-header"
FOOTER_CLASS = "mios-chrome-footer"

#: How far below the top of the viewport the header parks. Streamlit draws its
#: own toolbar there; sticking at 0 slides the strip underneath it.
HEADER_TOP = "3.2rem"


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.upper() in ("", UNKNOWN, "NONE") else s


def _esc(v) -> str:
    return _html.escape(_txt(v))


# ══════════════════════════════════════════════════════════════════════
#  the browser tab
# ══════════════════════════════════════════════════════════════════════

def tab_title(spot: Any = None, bias: Any = None,
              name: str = APP_NAME) -> str:
    """`🟢 24,650.30 · NIFTY` — price first, because that is what a glance at a
    background tab is for.

    The app name comes last and is dropped entirely once there is a price: a
    tab is ~20 characters wide, and a name that pushes the number out of view
    defeats the point of putting it there.
    """
    px = _num(spot)
    emoji = bias_emoji(bias)
    if px is None:
        return f"{emoji} {name}" if _txt(bias) else name
    return f"{emoji} {px:,.2f} · NIFTY"


def tab_title_script(title: str) -> str:
    """The zero-height component that applies it.

    `parent.document` because a Streamlit component renders inside an iframe;
    setting `document.title` here would rename the iframe nobody can see.
    Wrapped in a try so a browser that refuses the cross-frame write leaves the
    page working rather than throwing on every rerun.
    """
    safe = title.replace("\\", "\\\\").replace('"', '\\"')
    return (f'<script>try{{parent.document.title="{safe}";}}'
            f'catch(e){{}}</script>')


def render_tab_title(st, spot: Any = None, bias: Any = None,
                     name: str = APP_NAME) -> None:
    """Set the tab title for this cycle. Never raises.

    ⚠️ `st.components.v1.html` is deprecated with a stated removal date of
    2026-06-01, already past; Streamlit 1.60.0 still ships it but prints a
    deprecation line on every rerun.

    The replacement is **`st.html(..., unsafe_allow_javascript=True)`**, not
    `st.iframe` — Streamlit's own warning points at `st.iframe`, but that takes
    a `src` URL and cannot render markup at all, so following the warning
    literally silently does nothing. `st.html` is preferred here and the
    deprecated component is the fallback, for a Streamlit old enough to lack
    the flag.
    """
    markup = tab_title_script(tab_title(spot, bias, name))
    render = getattr(st, "html", None)
    if callable(render):
        try:
            render(markup, unsafe_allow_javascript=True)
            return
        except Exception:
            pass
    try:
        from streamlit.components.v1 import html as _component
        _component(markup, height=0)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  the header
# ══════════════════════════════════════════════════════════════════════

def _bias_chip(label: str, value: Any) -> str:
    v = _txt(value)
    tone = bias_tone(v, FAINT)
    shown = v or "—"
    return (f"<span style='display:inline-flex;align-items:center;gap:4px;"
            f"background:{PANEL_BG};border:1px solid {GRID};border-radius:6px;"
            f"padding:2px 7px;white-space:nowrap'>"
            f"<span style='font-size:8.5px;letter-spacing:.09em;color:{MICRO};"
            f"text-transform:uppercase'>{_esc(label)}</span>"
            f"<span style='font-size:11.5px;font-weight:800;color:{tone}'>"
            f"{bias_emoji(v)} {_esc(shown)}</span></span>")


def header_html(spot: Any = None, prev_close: Any = None,
                v5: Any = None, v6: Any = None,
                market: str = "", updated: str = "",
                name: str = APP_NAME, extras: Any = None) -> str:
    """The strip above every tab.

    `prev_close` is what the change is measured against. Absent, no change is
    shown — a move of unknown size is not a flat one, and `+0.00` would say the
    market had not moved.

    `extras` is a sequence of short PLAIN-TEXT readings — the S/R odds, the war
    zone winner, premium energy — each rendered as a chip on a second row.
    Text, not markup: this file owns the styling and each engine's own panel
    owns its wording, which is why the strings arrive already worded.

    ⚠️ The strip is **frozen at the top of the page**, so every row it grows
    costs vertical space on every screen for the whole session. That is the
    constraint the `micro` forms exist to satisfy, and the reason the extras
    are one wrapped line rather than a block. An empty or blank entry is
    dropped rather than drawn as a hollow chip.
    """
    px = _num(spot)
    prev = _num(prev_close)

    if px is None:
        price = (f"<span style='font-size:20px;font-weight:800;color:{FAINT}'>"
                 f"—</span>")
    else:
        change = None if prev is None or prev == 0 else px - prev
        # ── the price takes the BIAS's colour, the change takes the MOVE's ──
        #
        # Both used to follow the move, which meant a down day painted the
        # number red however bullish the engines were — the owner asked for the
        # bias instead, and the bias is the reading a glance off a frozen strip
        # is actually for.
        #
        # ⚠️ The change keeps the move's colour, deliberately. Colouring BOTH by
        # bias would leave a bullish read with nothing on the strip saying price
        # is falling, and green on a −70 is a contradiction a trader should see
        # rather than one the strip resolves for them. A missing bias falls back
        # to the move, so the number is never uncoloured.
        move_tone = INK if change is None else BULL if change >= 0 else BEAR
        tone = bias_tone(v6 or v5, move_tone)
        price = (f"<span style='font-size:20px;font-weight:800;color:{tone};"
                 f"line-height:1'>{px:,.2f}</span>")
        if change is not None:
            price += (f"<span style='font-size:11px;font-weight:700;"
                      f"color:{move_tone};margin-left:5px'>"
                      f"{change:+,.2f} ({change / prev * 100:+.2f}%)</span>")

    right = "".join(x for x in (
        _bias_chip("V5", v5) if _txt(v5) else "",
        _bias_chip("V6", v6) if _txt(v6) else "") if x)

    meta = " · ".join(x for x in (_esc(market), _esc(updated)) if x)

    chips = "".join(
        f"<span style='display:inline-block;background:{PANEL_BG};"
        f"border:1px solid {GRID};border-radius:5px;padding:1px 6px;"
        f"margin:2px 4px 0 0;font-size:10.5px;color:{MUTED};"
        f"white-space:nowrap'>{_esc(x)}</span>"
        for x in (extras or []) if _txt(x))
    extras_row = (f"<div style='flex-basis:100%;line-height:1.5'>{chips}</div>"
                  if chips else "")

    return (
        f"<div class='{HEADER_CLASS}' "
        f"style='background:{PANEL_BG};border:1px solid {GRID};"
        f"border-radius:10px;padding:8px 12px;margin-bottom:10px;"
        f"display:flex;align-items:center;gap:12px;flex-wrap:wrap'>"
        f"<div style='min-width:0'>"
        f"<div style='font-size:9px;letter-spacing:.12em;color:{MICRO};"
        f"text-transform:uppercase;white-space:nowrap'>📈 {_esc(name)}</div>"
        f"<div style='margin-top:1px;white-space:nowrap'>{price}</div></div>"
        f"<div style='display:flex;gap:6px;flex-wrap:wrap;margin-left:auto'>"
        f"{right}</div>"
        + (f"<div style='font-size:9.5px;color:{MICRO};white-space:nowrap'>"
           f"{meta}</div>" if meta else "")
        + extras_row
        + "</div>")


def render_header(st, slot: Any = None, spot: Any = None,
                  prev_close: Any = None, v5: Any = None, v6: Any = None,
                  market: str = "", updated: str = "",
                  name: str = APP_NAME, extras: Any = None) -> None:
    """Draw the header into `slot`, or inline when there is none.

    A slot exists because the header sits at the TOP of the page and its values
    arrive at the BOTTOM of the cycle. Writing it directly at the top would show
    the previous cycle's price under a live timestamp, which is worse than a
    blank strip for the second it takes to fill.
    """
    try:
        target = slot if slot is not None else st
        target.markdown(
            header_html(spot, prev_close, v5, v6, market, updated, name,
                        extras),
            unsafe_allow_html=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  the footer
# ══════════════════════════════════════════════════════════════════════

def footer_html(updated: str = "", market: str = "",
                version: str = "", notes: Any = None) -> str:
    """The closing strip. Small, quiet, and it says the one thing that matters
    legally and practically: **nothing here is advice, and nothing auto-trades
    from this screen.**"""
    bits = [x for x in (_esc(version), _esc(market), _esc(updated)) if x]
    for n in (notes or []):
        t = _esc(n)
        if t:
            bits.append(t)
    line = " · ".join(bits)
    return (
        f"<div class='{FOOTER_CLASS}' "
        f"style='margin-top:14px;padding:8px 12px;border-top:1px solid "
        f"{GRID};display:flex;gap:10px;flex-wrap:wrap;align-items:baseline'>"
        f"<span style='font-size:9.5px;color:{MUTED}'>"
        f"⚠️ Advisory only — every reading on this screen is an observation, "
        f"not a recommendation, and no order is placed from here.</span>"
        + (f"<span style='font-size:9px;color:{MICRO};margin-left:auto;"
           f"white-space:nowrap'>{line}</span>" if line else "")
        + "</div>")


def render_footer(st, slot: Any = None, updated: str = "", market: str = "",
                  version: str = "", notes: Any = None) -> None:
    """Draw it into `slot`, or inline when there is none.

    A slot for the same reason the header has one: the footer is written at the
    end of the cycle, and a rerun rebuilds the page from the top, so without a
    placeholder to reserve its position it is simply absent for the whole
    render. Never raises — a footer may not take the app down.
    """
    try:
        target = slot if slot is not None else st
        target.markdown(footer_html(updated, market, version, notes),
                        unsafe_allow_html=True)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════
#  making them stay put
# ══════════════════════════════════════════════════════════════════════

def chrome_css() -> str:
    """Freeze the header to the top and the footer to the bottom, Word-style.

    ## Why the strip cannot make itself sticky

    `position: sticky` moves an element **within its containing block**, and
    Streamlit wraps every `st.markdown` in an `.element-container` sized to
    exactly the height of what it holds. A sticky div inside a box its own
    height has nowhere to travel, so it never sticks — the inline style is
    accepted and does nothing, which is the confusing kind of broken.

    So the rule has to reach the *wrapper*, and the only way to select a
    wrapper by what it contains is `:has()`.

    ## Browser support, and what happens without it

    `:has()` is Chrome 105+, Safari 15.4+, Firefox 121+. Anywhere older the
    selector simply does not match, the wrapper stays static, and the strips
    scroll with the page exactly as they did before. **Degrading to the old
    behaviour is the reason this is CSS rather than a fixed-position layout** —
    `position: fixed` would work everywhere but takes the strips out of flow,
    where they overlay the sidebar and need the page padded to compensate, and
    a miscalculated pad hides content permanently rather than briefly.

    ## `top` is not zero

    Streamlit draws its own toolbar across the top of the viewport. Parking the
    header at `0` slides it underneath, so it sits at `HEADER_TOP`.

    Sticky also needs an opaque background — a transparent bar lets the content
    scroll visibly through it — which both strips already have, and a `z-index`
    above the page but below Streamlit's own overlays.
    """
    return f"""<style>
/* the wrapper, not the strip — see chrome_css.__doc__ */
[data-testid="stVerticalBlock"] > div:has(> .stMarkdown .{HEADER_CLASS}),
.element-container:has(.{HEADER_CLASS}) {{
    position: sticky;
    top: {HEADER_TOP};
    z-index: 90;
    background: transparent;
}}
[data-testid="stVerticalBlock"] > div:has(> .stMarkdown .{FOOTER_CLASS}),
.element-container:has(.{FOOTER_CLASS}) {{
    position: sticky;
    bottom: 0;
    z-index: 90;
}}
/* Opaque, or the page scrolls visibly through them. */
.{HEADER_CLASS}, .{FOOTER_CLASS} {{
    backdrop-filter: blur(6px);
    box-shadow: 0 2px 10px rgba(0,0,0,.45);
}}
.{FOOTER_CLASS} {{
    background: #0e1117;
    margin-top: 8px !important;
    border-radius: 8px 8px 0 0;
}}
/* On a phone the two strips would eat most of a short viewport, so the
   header stays and the footer returns to the flow. */
@media (max-width: 640px) {{
    [data-testid="stVerticalBlock"] > div:has(> .stMarkdown .{FOOTER_CLASS}),
    .element-container:has(.{FOOTER_CLASS}) {{ position: static; }}
}}
</style>"""


def render_chrome_css(st) -> None:
    """Inject the sticky rules once per rerun. Never raises."""
    try:
        st.markdown(chrome_css(), unsafe_allow_html=True)
    except Exception:
        pass
