"""Advanced price-action overlay for the terminal charts.

Draws the `mios_v5.advanced_price_action` read onto a plotly figure: swing
highs/lows, the recent BOS / CHOCH breaks, and the Fibonacci retracement band.
Geometric patterns are NOT drawn here — they read as clutter on the chart, so
they are tabulated below the charts with their bias (`price_action_table`).
Opt-in — the caller only calls
this when the trader has enabled the indicator, and it is silent on any failure
(same rule as `profile_overlay` / `volume_points_overlay`): a chart that cannot
draw the overlay still draws the candles.
"""

from __future__ import annotations

from typing import Any, Optional

# markers/lines kept muted so the overlay reads UNDER the candles, not over them
_SWING_HI = "#ff6b81"
_SWING_LO = "#4dd0a0"
_BOS = "#f0c040"
_CHOCH = "#a78bfa"
_FIB = "#c9a227"
#: only the meaningful retracement levels are drawn, to avoid seven lines of clutter
_FIB_KEYS = ("0.382", "0.5", "0.618")
#: cap how many swing markers show, newest wins — a full session can have dozens
_MAX_SWINGS = 12
_MAX_BREAKS = 3


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def draw(fig, df, row: int = 1, col: int = 1, swing_length: int = 5) -> None:
    """Overlay the price-action read onto `fig` for the OHLC `df`. No-op on any
    error or when there is too little data to analyse."""
    try:
        if df is None or getattr(df, "empty", True) or len(df) < (swing_length * 2 + 2):
            return
        import plotly.graph_objects as go

        from ..advanced_price_action import AdvancedPriceAction
        a = AdvancedPriceAction(swing_length=swing_length).analyze(df)
        if not a or not a.get("success"):
            return

        # ── swing highs / lows (newest _MAX_SWINGS) ──
        for pts, colour, sym, name in (
                (a.get("swing_highs"), _SWING_HI, "triangle-down", "Swing H"),
                (a.get("swing_lows"), _SWING_LO, "triangle-up", "Swing L")):
            pts = (pts or [])[-_MAX_SWINGS:]
            if not pts:
                continue
            fig.add_trace(go.Scatter(
                x=[p["time"] for p in pts], y=[p["price"] for p in pts],
                mode="markers", name=name, showlegend=False, hoverinfo="skip",
                marker=dict(symbol=sym, size=7, color=colour,
                            line=dict(width=0))), row=row, col=col)

        # ── Fibonacci retracement band (the 0.382/0.5/0.618 pocket) ──
        fib = a.get("fibonacci") or {}
        if fib.get("success"):
            rl = fib.get("retracement_levels") or {}
            for k in _FIB_KEYS:
                v = _f(rl.get(k))
                if v is None:
                    continue
                fig.add_hline(y=v, row=row, col=col, line_width=1,
                              line_dash="dot", line_color=_FIB,
                              annotation_text=f"Fib {k}",
                              annotation_position="left",
                              annotation_font=dict(size=8, color=_FIB))

        # ── recent BOS / CHOCH breaks ──
        for evs, colour, tag in ((a.get("bos_events"), _BOS, "BOS"),
                                 (a.get("choch_events"), _CHOCH, "CHoCH")):
            for e in (evs or [])[-_MAX_BREAKS:]:
                y = _f(e.get("price"))
                if y is None:
                    continue
                up = e.get("type") == "BULLISH"
                fig.add_trace(go.Scatter(
                    x=[e.get("time")], y=[y], mode="markers+text",
                    text=[f"{tag}{'▲' if up else '▼'}"], textposition="top center",
                    textfont=dict(size=8, color=colour), showlegend=False,
                    hoverinfo="skip",
                    marker=dict(symbol="x-thin", size=7, color=colour,
                                line=dict(width=1, color=colour))), row=row, col=col)
        # Geometric patterns are NOT drawn on the chart (too cluttered); they are
        # tabulated below the charts with their bias — see `price_action_table`.
    except Exception:
        return  # silent by design — the candles still draw
