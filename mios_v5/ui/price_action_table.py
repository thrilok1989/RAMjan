"""Geometric-pattern tabulation — the patterns from `advanced_price_action`,
shown as a table BELOW the charts (not on them) with each pattern's bias.

Pure: it reads the analysis and returns rows / HTML. No `st`, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

#: pattern type → (bias word, emoji). Reversals flip the prevailing trend;
#: continuation patterns lean the way the flagpole / triangle points.
_BIAS = {
    "HEAD_AND_SHOULDERS": ("Bearish reversal", "🔴"),
    "INVERSE_HEAD_AND_SHOULDERS": ("Bullish reversal", "🟢"),
    "ASCENDING_TRIANGLE": ("Bullish continuation", "🟢"),
    "DESCENDING_TRIANGLE": ("Bearish continuation", "🔴"),
    "SYMMETRICAL_TRIANGLE": ("Neutral / continuation", "⚪"),
    "BULL_FLAG": ("Bullish continuation", "🟢"),
    "BULL_PENNANT": ("Bullish continuation", "🟢"),
    "BEAR_FLAG": ("Bearish continuation", "🔴"),
    "BEAR_PENNANT": ("Bearish continuation", "🔴"),
}
_COLOUR = {"🟢": "#00c853", "🔴": "#ff3b30", "⚪": "#c9a227"}


def pattern_bias(pattern_type: Any) -> Dict[str, str]:
    """`{label, bias, emoji}` for a pattern type (e.g. "BULL_FLAG")."""
    key = str(pattern_type or "").upper()
    bias, emoji = _BIAS.get(key, ("Neutral", "⚪"))
    label = key.replace("_", " ").title()
    return {"label": label, "bias": bias, "emoji": emoji}


def rows_for(analysis: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten one chart's `analyze()['patterns']` into `{type, label, bias,
    emoji, bars}` rows. `bars` is the index span the pattern covers."""
    pats = (analysis or {}).get("patterns") or {}
    out: List[Dict[str, Any]] = []
    for grp in ("head_and_shoulders", "inverse_head_and_shoulders",
                "triangles", "flags_pennants"):
        for p in (pats.get(grp) or []):
            t = p.get("type")
            b = pattern_bias(t)
            if grp in ("head_and_shoulders", "inverse_head_and_shoulders"):
                lo = (p.get("left_shoulder") or {}).get("index")
                hi = (p.get("right_shoulder") or {}).get("index")
            elif grp == "triangles":
                tl = p.get("lower_trendline") or []
                lo = tl[0]["index"] if tl else None
                hi = tl[-1]["index"] if tl else None
            else:
                lo, hi = p.get("flagpole_start"), p.get("flagpole_end")
            out.append({"type": t, **b, "bars": (lo, hi)})
    return out


def table_html(rows_by_chart: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """A compact table: one row per detected pattern, grouped by chart, with its
    bias. `""` when no chart detected any pattern."""
    charts = [(c, list(rows_by_chart.get(c) or []))
              for c in ("NIFTY", "CALL", "PUT")]
    if not any(rows for _c, rows in charts):
        return ""
    head = ("<div style='margin:6px 0 4px;font-weight:800;color:#dbe4ee;font-size:13px;'>"
            "📐 Geometric patterns · what &amp; which way</div>"
            "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;"
            "font-size:12px;'>"
            "<tr style='background:#0e1420;color:#fff;'>"
            "<th style='padding:5px 8px;border:1px solid #223;text-align:left;'>Chart</th>"
            "<th style='padding:5px 8px;border:1px solid #223;text-align:left;'>Pattern</th>"
            "<th style='padding:5px 8px;border:1px solid #223;text-align:left;'>Bias</th>"
            "<th style='padding:5px 8px;border:1px solid #223;text-align:center;'>Bars</th></tr>")
    body = ""
    for chart, rows in charts:
        for r in rows:
            col = _COLOUR.get(r.get("emoji"), "#c9a227")
            lo, hi = r.get("bars") or (None, None)
            span = (f"{lo}–{hi}" if lo is not None and hi is not None else "—")
            body += (
                f"<tr style='background:#141c28;color:#e8eef5;'>"
                f"<td style='padding:5px 8px;border:1px solid #223;'>{chart}</td>"
                f"<td style='padding:5px 8px;border:1px solid #223;'>{r.get('label')}</td>"
                f"<td style='padding:5px 8px;border:1px solid #223;color:{col};font-weight:700;'>"
                f"{r.get('emoji')} {r.get('bias')}</td>"
                f"<td style='padding:5px 8px;border:1px solid #223;text-align:center;"
                f"color:#8a95a3;'>{span}</td></tr>")
    note = ("<div style='color:#8a95a3;font-size:10px;margin-top:3px;'>"
            "Detected on each chart's own candles · reversal flips the trend, "
            "continuation resumes it. Context only.</div>")
    return head + body + "</table></div>" + note


def build_table(nifty_df: Any = None, call_df: Any = None, put_df: Any = None,
                swing_length: int = 5) -> str:
    """Convenience: analyse each frame and return the pattern table HTML.
    Fetches/computes nothing beyond the pattern detection on the given frames."""
    try:
        from ..advanced_price_action import AdvancedPriceAction
    except Exception:
        return ""
    apa = AdvancedPriceAction(swing_length=swing_length)

    def _rows(df):
        try:
            if df is None or getattr(df, "empty", True) or len(df) < (swing_length * 2 + 2):
                return []
            return rows_for(apa.analyze(df))
        except Exception:
            return []

    return table_html({"NIFTY": _rows(nifty_df), "CALL": _rows(call_df),
                       "PUT": _rows(put_df)})
