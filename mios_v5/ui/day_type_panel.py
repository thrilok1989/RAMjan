"""MIOS V6.5 — Stage 68 Market Day Classification panels.

Four renderings for four places:

    badge      D2, above the charts — the one thing to keep in view
    card       D1, under the decision — type, expectation, style
    detail     D3, the engine room — every group's vote and signals
    timeline   D3/D5 — how the session's character changed

The card shows **Avoid** as prominently as **Recommended**. On a choppy or a
pin day the useful instruction is what not to do, and a panel listing only
recommendations reads as encouragement on exactly the days that call for
sitting out.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _clock(ts) -> str:
    """HH:MM in IST — never the container's local zone."""
    from ..clock import hhmm
    return hhmm(ts)


def day_type_badge(d: Optional[Dict[str, Any]]) -> str:
    """The compact strip for above the charts and for the Trade Card."""
    c = d or {}
    if not c.get("type"):
        return ""
    col = c.get("colour", "#cfd9e6")
    dur = _f(c.get("duration_min"))
    held = f" · held {dur:.0f} min" if dur else ""
    changes = int(c.get("changes_today") or 0)
    ch = f" · {changes} change{'s' if changes != 1 else ''} today" if changes else ""
    return (f"<div style='display:flex;align-items:baseline;gap:8px;"
            f"padding:6px 10px;background:#0f1622;border:1px solid {col};"
            f"border-radius:9px;margin-bottom:8px;flex-wrap:wrap'>"
            f"<span style='font-size:9.5px;letter-spacing:.11em;color:#b3c2d4;"
            f"text-transform:uppercase'>Today's market</span>"
            f"<span style='font-size:17px;font-weight:900;color:{col}'>"
            f"{c['label']}</span>"
            f"<span style='font-size:13px;font-weight:700;color:#ffffff'>"
            f"{c.get('confidence', 0)}%</span>"
            f"<span style='font-size:11.5px;color:#cfd9e6'>{held}{ch}</span>"
            f"</div>")


def day_type_card(d: Optional[Dict[str, Any]]) -> str:
    """The morning read: what kind of day, why, what to expect, how to trade
    it — and what to avoid."""
    c = d or {}
    if not c.get("type"):
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>Market type not yet classified — the "
                f"evidence groups have not reported.</div></div>")
    col = c.get("colour", "#cfd9e6")
    dur = _f(c.get("duration_min"))

    head = (f"<div style='display:flex;align-items:baseline;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<span style='font-size:9.5px;letter-spacing:.11em;color:#b3c2d4;"
            f"text-transform:uppercase'>Today's market</span>"
            f"<span style='font-size:24px;font-weight:900;color:{col}'>"
            f"{c['label']}</span>"
            f"<span style='font-size:18px;font-weight:800;color:#ffffff'>"
            f"{c.get('confidence', 0)}%</span>"
            + (f"<span style='margin-left:auto;font-size:11.5px;color:#cfd9e6'>"
               f"held {dur:.0f} min</span>" if dur else "")
            + "</div>")

    note = (f"<div style='font-size:11.5px;color:#cfd9e6;margin-top:1px'>"
            f"{c.get('confidence_note', '')}</div>")

    forced = ""
    if c.get("forced"):
        forced = (f"<div style='margin-top:4px;padding:5px 8px;"
                  f"background:#1a1206;border-left:3px solid {col};"
                  f"border-radius:5px;font-size:12px;color:#ffd9a0'>"
                  f"{c.get('forced_reason', '')}"
                  + (f"<br><span style='color:#c4d0de'>The tape itself voted "
                     f"{c.get('voted_label')}.</span>"
                     if c.get("voted_label") else "")
                  + "</div>")

    ev = "".join(
        f"<div style='font-size:12px;color:#7fe8b0;margin-top:2px'>"
        f"✓ {s.get('text')}"
        f"<span style='font-size:10px;color:#9fb0c4'> {s.get('engine')}</span>"
        f"</div>" for s in (c.get("evidence") or [])[:8])

    def _list(title, items, colour, mark):
        if not items:
            return ""
        return (f"<div style='flex:1;min-width:168px'>"
                f"<div style='font-size:10px;letter-spacing:.10em;"
                f"color:#cfd9e6;text-transform:uppercase'>{title}</div>"
                + "".join(f"<div style='font-size:12px;color:{colour};"
                          f"margin-top:2px'>{mark} {i}</div>"
                          for i in items[:4]) + "</div>")

    return (f"<div style='{_CARD};border-left:3px solid {col}'>"
            + head + note + forced
            + (f"<div style='margin-top:6px'>{ev}</div>" if ev else "")
            + "<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:8px'>"
            + _list("Expected", c.get("expected"), "#9fd3ff", "•")
            + _list("Recommended", c.get("recommended"), "#7fe8b0", "✓")
            + _list("Avoid", c.get("avoid"), "#ff9d9d", "✗")
            + "</div>"
            + (f"<div style='margin-top:6px;padding:5px 8px;background:#2a2205;"
               f"border-left:3px solid #ffcc33;border-radius:5px;font-size:12px;"
               f"color:#ffe9a8'>{c['style_caveat']}</div>"
               if c.get("style_caveat") else "")
            + "<div style='margin-top:7px;font-size:10.5px;color:#9fb0c4'>"
              "Context only — this engine casts no vote, changes no "
              "confidence, and cannot override the Decision Engine.</div>"
            + "</div>")


def day_type_detail(d: Optional[Dict[str, Any]]) -> str:
    """Every evidence group: its vote, its signals, and — when it could not
    report — why. The unavailable groups matter: they are the denominator the
    confidence number is scaled by."""
    c = d or {}
    groups = c.get("groups") or []
    if not groups:
        return ""
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
           f"🗓 Day classification — evidence groups</div>",
           f"<div style='font-size:11px;color:#b3c2d4;margin-bottom:4px'>"
           f"{c.get('groups_available', 0)}/{c.get('groups_total', 0)} groups "
           f"reporting · {c.get('groups_backing', 0)} back "
           f"{c.get('label', '')}</div>"]
    for g in groups:
        if not g.get("available"):
            out.append(
                f"<div style='display:flex;gap:8px;font-size:11.5px;"
                f"padding:2px 0;opacity:.55'>"
                f"<span style='width:24px'>⚪</span>"
                f"<span style='width:140px;color:#cfd9e6'>{g['label']}</span>"
                f"<span style='color:#9fb0c4'>{g.get('reason', '')}</span>"
                f"</div>")
            continue
        backs = g.get("top") == c.get("type")
        mark = "✅" if backs else "↔"
        col = "#7fe8b0" if backs else "#cfd9e6"
        out.append(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:2px 0;"
            f"border-top:1px solid #161b22'>"
            f"<span style='width:24px'>{mark}</span>"
            f"<span style='width:140px;font-weight:700;color:#edf3f9'>"
            f"{g['label']}</span>"
            f"<span style='width:150px;font-weight:800;color:{col}'>"
            f"votes {g.get('top')}</span>"
            f"<span style='font-size:10.5px;color:#9fb0c4'>w{g['authority']:.0f}"
            f"</span></div>")
        for s in g.get("signals", [])[:4]:
            out.append(
                f"<div style='font-size:11px;color:#cfd9e6;padding-left:32px'>"
                f"• {s['text']} "
                f"<span style='color:#93a5ba'>({s['engine']} → "
                f"{s['type'].replace('_', ' ').title()})</span></div>")
    if c.get("runners_up"):
        out.append(
            f"<div style='margin-top:6px;font-size:11.5px;color:#cfd9e6'>"
            f"Runners-up: "
            + " · ".join(f"{r['type'].replace('_', ' ').title()} {r['share']}%"
                         for r in c["runners_up"]) + "</div>")
    out.append("</div>")
    return "".join(out)


def day_type_timeline(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    """`09:20 Range → 10:45 Swing → 13:10 Trend` — the session's character
    changes, oldest first."""
    rs = list(rows or [])
    if not rs:
        return ""
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🕘 How today has evolved</div>"]
    for r in rs:
        cur = bool(r.get("current"))
        held = _f(r.get("held_min"))
        out.append(
            f"<div style='display:flex;gap:8px;align-items:baseline;"
            f"font-size:12.5px;padding:2px 0'>"
            f"<span style='width:44px;color:#9fb0c4'>{_clock(r.get('ts'))}</span>"
            + (f"<span style='color:#9fb0c4'>{r['from']} →</span>"
               if r.get("from") else "")
            + f"<span style='font-weight:{800 if cur else 600};color:"
              f"{'#ffffff' if cur else '#dfe7f0'}'>{r.get('to', '')}</span>"
            + (f"<span style='color:#b3c2d4'>{r.get('confidence')}%</span>"
               if r.get("confidence") else "")
            + (f"<span style='margin-left:auto;color:#9fb0c4;font-size:11px'>"
               f"{held:.0f} min</span>" if held else "")
            + "</div>")
    out.append("</div>")
    return "".join(out)


def performance_by_type(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    """Which day types actually produce results — the Learning Dashboard's
    payoff for logging all of this."""
    rs = list(rows or [])
    if not rs:
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>No graded trades joined to a day type yet — "
                f"run <code>sql/028_day_type_log.sql</code> and let a few "
                f"sessions record.</div></div>")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>📅 Performance by market type</div>"]
    for r in rs:
        wr = _f(r.get("win_rate"))
        col = ("#00ff88" if (wr or 0) >= 55 else
               "#ffd000" if (wr or 0) >= 45 else "#ff6666")
        thin = int(r.get("trades") or 0) < 10
        out.append(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:2px 0;"
            f"border-top:1px solid #161b22;opacity:{0.55 if thin else 1}'>"
            f"<span style='width:168px;color:#edf3f9'>{r.get('label')}</span>"
            f"<span style='width:56px;font-weight:800;color:{col}'>"
            f"{'—' if wr is None else f'{wr:g}%'}</span>"
            f"<span style='width:64px;color:#cfd9e6'>{r.get('trades', 0)} tr</span>"
            f"<span style='width:76px;color:#cfd9e6'>"
            f"{r.get('sessions', 0)} sessions</span>"
            + (f"<span style='color:#ffcc33;font-size:10.5px'>thin</span>"
               if thin else "") + "</div>")
    out.append(f"<div style='margin-top:6px;font-size:10.5px;color:#9fb0c4'>"
               f"Types with fewer than 10 graded trades are dimmed — shown, "
               f"not trusted.</div></div>")
    return "".join(out)
