"""Chart chrome that follows the viewer's theme.

The terminal's background, grid, text and spike colours were hard-coded to the
dark palette. Streamlit lets a viewer pick Light in Settings → Theme, and the
page around the charts changed while the charts themselves stayed near-black —
dark rectangles pasted onto a white page.

Only the *chrome* lives here. The semantic colours — a bullish candle, a
support line, the HTF dashes — carry meaning and stay the same in both themes;
they are chosen to read on either background.

`st.context.theme` reports what the viewer actually has applied, which is not
the same as `config.toml`'s `base`: the config is only the starting point, and
the Settings menu overrides it per viewer. Reading the context means a viewer
on Light gets light charts even though the repo ships a dark default.
"""

from __future__ import annotations

from typing import Any, Dict


#: Near-black page, the palette the terminal has always used.
DARK: Dict[str, str] = {
    "paper": "#0b0f16",
    "plot": "#0b0f16",
    "font": "#edf3f9",
    "grid": "#161b22",
    "spike": "#3a4757",
    "title": "#cfd9e6",
    "htf": "#9fb0c4",
    "marker_edge": "#0b0f16",
}

#: The light mirror. Grid and spike are deliberately low-contrast greys rather
#: than the dark palette inverted — a pure inversion puts near-black gridlines
#: on white, which reads louder than the candles they sit behind.
LIGHT: Dict[str, str] = {
    "paper": "#ffffff",
    "plot": "#ffffff",
    "font": "#1c2530",
    "grid": "#e6eaef",
    "spike": "#8c9bad",
    "title": "#2b3644",
    "htf": "#5a6b7d",
    "marker_edge": "#ffffff",
}

DEFAULT = "dark"


def palette(theme: Any = None) -> Dict[str, str]:
    """The chrome palette for `theme` — "light", "dark", or something falsy.

    Anything unrecognised falls back to dark, which is what the app shipped
    with, so a surprise value degrades to the status quo rather than to an
    unreadable half-applied theme.
    """
    return LIGHT if str(theme or DEFAULT).strip().lower() == "light" else DARK


def active_theme(st) -> str:
    """Which theme the viewer has applied: "light" or "dark".

    Prefers `st.context.theme`, which reflects the viewer's own Settings
    choice. Falls back to the configured base, then to dark. Every lookup is
    guarded — a chart must never fail to draw because a theme probe raised.
    """
    try:
        ctx = getattr(st, "context", None)
        theme = getattr(ctx, "theme", None)
        kind = getattr(theme, "type", None)
        if kind:
            return "light" if str(kind).lower() == "light" else "dark"
    except Exception:
        pass
    try:
        base = st.get_option("theme.base")
        if base:
            return "light" if str(base).lower() == "light" else "dark"
    except Exception:
        pass
    return DEFAULT
