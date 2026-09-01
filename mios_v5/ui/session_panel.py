"""MIOS V6 — Stage 69 Session Intelligence panels.

Three renderings: a compact strip for the header and the Trade Card, the full
card for Dashboard 1, and the modifier table for the engine room.

The modifier table shows what Stage 69 *would* change and states plainly that it
is not changing it. That is the point of shipping it observational: the trader
can watch the adjustment they are not yet getting, and decide from evidence
whether to promote it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:9px 11px;margin-bottom:8px")

_LEVEL_COLOUR = {"Very High": "#00ff88", "High": "#17c98b",
                 "Medium": "#ffd000", "Low": "#ff9500", "None": "#ff4444",
                 "—": "#9fb0c4"}

_BEHAVIOUR_COLOUR = {
    "TRENDING": "#00ff88", "TREND_BUILDING": "#17c98b",
    "EXPANDING": "#4da6ff", "RANGE_BUILDING": "#ffd000",
    "SIDEWAYS": "#ffd000", "COMPRESSING": "#c9b6ec",
    "CHOPPY": "#ff9500", "TREND_EXHAUSTION": "#ff6666",
    "EXPIRY": "#a78bfa", "UNKNOWN": "#9fb0c4",
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def session_strip(d: Optional[Dict[str, Any]]) -> str:
    """The compact strip — current session, time left, mood."""
    s = d or {}
    if not s.get("session"):
        return ""
    col = _BEHAVIOUR_COLOUR.get(s.get("behaviour"), "#cfd9e6")
    rem = s.get("minutes_remaining")
    pct = s.get("pct_through")
    bar = ""
    if pct is not None:
        bar = (f"<span style='display:inline-block;width:52px;height:5px;"
               f"background:#1a2331;border-radius:3px;overflow:hidden;'>"
               f"<span style='display:block;width:{pct}%;height:5px;"
               f"background:{col};'></span></span>")
    return (f"<div style='display:flex;align-items:center;gap:8px;"
            f"flex-wrap:wrap;padding:5px 9px;background:#0f1622;"
            f"border:1px solid #1e2836;border-radius:8px;margin-bottom:6px'>"
            f"<span style='font-size:9px;letter-spacing:.11em;color:#b3c2d4;"
            f"text-transform:uppercase'>Session</span>"
            f"<span style='font-size:14px;font-weight:900;color:#ffffff'>"
            f"{s.get('label')}</span>"
            + (f"<span style='font-size:12px;color:#cfd9e6'>{rem} min left"
               f"</span>{bar}" if rem is not None else "")
            + f"<span style='margin-left:auto;font-size:12.5px;font-weight:700;"
              f"color:{col}'>{s.get('behaviour_label', '')}</span></div>")


def session_card(d: Optional[Dict[str, Any]]) -> str:
    """The full read for Dashboard 1."""
    s = d or {}
    if not s.get("session"):
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>Session not yet classified.</div></div>")
    col = _BEHAVIOUR_COLOUR.get(s.get("behaviour"), "#cfd9e6")
    rem = s.get("minutes_remaining")

    head = (f"<div style='display:flex;align-items:baseline;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<span style='font-size:9.5px;letter-spacing:.11em;color:#b3c2d4;"
            f"text-transform:uppercase'>Current session</span>"
            f"<span style='font-size:20px;font-weight:900;color:#ffffff'>"
            f"{s.get('label')}</span>"
            f"<span style='font-size:14px;font-weight:800;color:{col}'>"
            f"{s.get('behaviour_label', '')}</span>"
            + (f"<span style='margin-left:auto;font-size:12px;color:#cfd9e6'>"
               f"{s.get('start')}–{s.get('end')} · <b style='color:#ffffff'>"
               f"{rem} min left</b></span>" if rem is not None else
               f"<span style='margin-left:auto;font-size:12px;color:#cfd9e6'>"
               f"next: {s.get('next_label', '')}</span>")
            + "</div>")

    measures = s.get("measures") or {}
    grid = "".join(
        f"<div style='flex:1;min-width:104px'>"
        f"<div style='font-size:9px;letter-spacing:.10em;color:#b3c2d4;"
        f"text-transform:uppercase'>{m['label']}</div>"
        f"<div style='font-size:14px;font-weight:800;color:"
        f"{_LEVEL_COLOUR.get(m['level'], '#9fb0c4')}'>{m['level']}</div>"
        f"<div style='font-size:9.5px;color:#9fb0c4'>{m['engine']}</div>"
        f"</div>"
        for m in measures.values() if m.get("available"))

    unavailable = [m["label"] for m in measures.values()
                   if not m.get("available")]

    def _list(title, items, colour, mark):
        if not items:
            return ""
        return (f"<div style='flex:1;min-width:176px'>"
                f"<div style='font-size:10px;letter-spacing:.10em;"
                f"color:#cfd9e6;text-transform:uppercase'>{title}</div>"
                + "".join(f"<div style='font-size:12px;color:{colour};"
                          f"margin-top:2px'>{mark} {i}</div>"
                          for i in items[:4]) + "</div>")

    return (f"<div style='{_CARD};border-left:3px solid {col}'>"
            + head
            + f"<div style='font-size:12px;color:#edf3f9;margin-top:3px'>"
              f"{s.get('sentence', '')}</div>"
            + (f"<div style='display:flex;gap:10px;flex-wrap:wrap;"
               f"margin-top:7px'>{grid}</div>" if grid else "")
            + (f"<div style='margin-top:4px;font-size:10.5px;color:#9fb0c4'>"
               f"⚪ not reporting: {', '.join(unavailable)}</div>"
               if unavailable else "")
            + "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:8px'>"
            + _list("Typical", s.get("purpose"), "#9fd3ff", "•")
            + _list("Recommended", s.get("recommended"), "#7fe8b0", "✓")
            + _list("Avoid", s.get("avoid"), "#ff9d9d", "✗")
            + "</div>"
            + "<div style='margin-top:7px;font-size:10.5px;color:#9fb0c4'>"
              "Context only — this engine emits no direction and cannot "
              "override the Decision Engine.</div>"
            + "</div>")


def modifier_table(d: Optional[Dict[str, Any]]) -> str:
    """What Stage 69 would change in each engine — and whether it is live."""
    s = d or {}
    mods = s.get("modifiers") or {}
    applies = mods.get("applies_to") or {}
    applied = bool(mods.get("applied"))
    banner_col = "#00ff88" if applied else "#ffcc33"

    body = []
    if not applies:
        body.append(f"<div style='font-size:12px;color:#cfd9e6'>"
                    f"No engine modifiers for {s.get('label', 'this session')}"
                    f" — normal thresholds apply.</div>")
    for engine, mod in applies.items():
        bits = " · ".join(f"{k} {v}" for k, v in mod.items() if k != "reason")
        body.append(
            f"<div style='display:flex;gap:8px;align-items:baseline;"
            f"font-size:12px;padding:2px 0;border-top:1px solid #161b22'>"
            f"<span style='width:168px;color:#edf3f9;font-weight:700'>"
            f"{engine}</span>"
            f"<span style='width:210px;color:{banner_col}'>{bits or '—'}</span>"
            f"<span style='flex:1;min-width:0;font-size:11px;color:#cfd9e6'>"
            f"{mod.get('reason', '')}</span></div>")

    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:12.5px;font-weight:800;color:#ffffff;"
            f"margin-bottom:2px'>🎛 Session modifiers</div>"
            f"<div style='font-size:11px;color:{banner_col};margin-bottom:3px'>"
            f"{'✅' if applied else '⚠️'} {mods.get('note', '')}</div>"
            + "".join(body) + "</div>")


def performance_by_session(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Which sessions actually produce results — the Learning Engine's payoff
    for logging every cycle."""
    rs = list(rows or [])
    if not rs:
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>No graded trades joined to a session yet — "
                f"run <code>sql/029_session_log.sql</code> and let a few "
                f"sessions record.</div></div>")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🕘 Performance by session</div>"]
    for r in rs:
        wr = _f(r.get("win_rate"))
        col = ("#00ff88" if (wr or 0) >= 55 else
               "#ffd000" if (wr or 0) >= 45 else "#ff6666")
        thin = bool(r.get("thin"))
        out.append(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:2px 0;"
            f"border-top:1px solid #161b22;opacity:{0.55 if thin else 1}'>"
            f"<span style='width:176px;color:#edf3f9'>{r.get('label')}</span>"
            f"<span style='width:56px;font-weight:800;color:{col}'>"
            f"{'—' if wr is None else f'{wr:g}%'}</span>"
            f"<span style='width:64px;color:#cfd9e6'>{r.get('trades', 0)} tr</span>"
            + (f"<span style='color:#ffcc33;font-size:10.5px'>thin</span>"
               if thin else "") + "</div>")
    out.append(f"<div style='margin-top:6px;font-size:10.5px;color:#9fb0c4'>"
               f"Sessions with fewer than 10 graded trades are dimmed — shown, "
               f"not trusted.</div></div>")
    return "".join(out)
