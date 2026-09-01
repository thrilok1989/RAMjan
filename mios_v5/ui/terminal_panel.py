"""MIOS V6 — Dashboard 2 terminal panels: ribbon · leg cards · comparison ·
intelligence · recommendation banner.

Every value carries the engine that produced it. On a trading screen that
matters more than on an analysis screen: when a number looks wrong mid-session,
the trader needs to know which engine to distrust without leaving the tab.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from .theme import bias_tone

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:9px 11px;margin-bottom:8px")



def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _rs(v, prefix="₹", dp=2) -> str:
    x = _f(v)
    return "—" if x is None else f"{prefix}{x:,.{dp}f}"


# ── the market ribbon that sits above the NIFTY chart ───────────────────
def market_ribbon_html(r: Optional[Dict[str, Any]]) -> str:
    d = r or {}
    conf = int(d.get("confidence") or 0)
    ccol = "#00ff88" if conf >= 70 else "#ffd000" if conf >= 50 else "#cfd9e6"
    cells = [
        ("Market", d.get("state", "—"), "#c9b6ec"),
        ("Bias", str(d.get("bias", "—")).replace("_", " "), "#ffffff"),
        ("Transition", d.get("transition", "—"), "#9fd3ff"),
        ("Quality", d.get("quality", "—"), d.get("quality_colour", "#cfd9e6")),
        ("Confidence", f"{conf}%", ccol),
    ]
    if d.get("day_type"):
        cells.insert(0, ("Today", d["day_type"], "#ffd000"))
    return ("<div style='display:flex;gap:10px;flex-wrap:wrap;"
            "align-items:baseline;padding:5px 9px;background:#0f1622;"
            "border:1px solid #1e2836;border-radius:8px;margin-bottom:6px'>"
            + "".join(
                f"<div><span style='font-size:9px;letter-spacing:.10em;"
                f"color:#b3c2d4;text-transform:uppercase'>{k}</span> "
                f"<span style='font-size:13px;font-weight:800;color:{c}'>{v}"
                f"</span></div>" for k, v, c in cells)
            + "</div>")


# ── one option leg's card ───────────────────────────────────────────────
def leg_card_html(leg: Optional[Dict[str, Any]], title: str) -> str:
    d = leg or {}
    if not d:
        return ""
    col = d.get("bias_colour", "#cfd9e6")
    badges = "".join(
        f"<span style='display:inline-block;font-size:10.5px;font-weight:800;"
        f"padding:1px 6px;margin:1px 3px 1px 0;border-radius:4px;"
        f"border:1px solid {bias_tone(b['tone'], '#cfd9e6')};"
        f"color:{bias_tone(b['tone'], '#cfd9e6')}' title='{b['engine']}'>"
        f"{b['text']}</span>" for b in (d.get("badges") or []))

    strength = _f(d.get("strength"))
    ltp = _f(d.get("ltp"))

    trade = []
    if d.get("entry") is not None:
        trade.append(("Entry", _rs(d["entry"]), "#00ff88"))
    if d.get("stop") is not None:
        trade.append(("Stop", _rs(d["stop"]), "#ff6666"))
    if d.get("trail") is not None:
        trade.append(("Trail", _rs(d["trail"]) +
                      (f" · {d['trail_state']}" if d.get("trail_state") else ""),
                      "#a78bfa"))

    return (
        f"<div style='{_CARD};border-left:3px solid {col}'>"
        f"<div style='display:flex;align-items:baseline;gap:8px;flex-wrap:wrap'>"
        f"<span style='font-size:11px;font-weight:800;color:#cfd9e6'>{title}</span>"
        + (f"<span style='font-size:15px;font-weight:900;color:#ffffff'>"
           f"{_rs(ltp)}</span>" if ltp is not None else "")
        + f"<span style='font-size:15px;font-weight:900;color:{col}'>"
          f"{d.get('bias_label', '—')}</span>"
        + (f"<span style='margin-left:auto;font-size:13px;font-weight:800;"
           f"color:#ffffff'>{strength:g}% "
           f"<span style='color:#ffd000'>{d.get('stars', '')}</span></span>"
           if strength is not None else "")
        + "</div>"
        + (f"<div style='margin-top:3px'>{badges}</div>" if badges else "")
        + (f"<div style='display:flex;gap:12px;margin-top:4px;flex-wrap:wrap'>"
           + "".join(
               f"<div><span style='font-size:9px;letter-spacing:.10em;"
               f"color:#b3c2d4;text-transform:uppercase'>{k}</span> "
               f"<span style='font-size:13px;font-weight:800;color:{c}'>{v}"
               f"</span></div>" for k, v, c in trade) + "</div>"
           if trade else "")
        + (f"<div style='margin-top:3px;font-size:11px;color:#c4d0de'>"
           f"{d['entry_note']}</div>" if d.get("entry_note") else "")
        + f"<div style='margin-top:4px;font-size:12px;color:#edf3f9'>"
          f"{d.get('sentence', '')}</div>"
        + f"<div style='margin-top:2px;font-size:9.5px;color:#9fb0c4'>"
          f"strength: {d.get('strength_source', '')}</div>"
        + "</div>")


# ── the CALL vs PUT ribbon between the two option charts ────────────────
def compare_ribbon_html(c: Optional[Dict[str, Any]]) -> str:
    d = c or {}
    rows = d.get("rows") or []
    if not rows:
        return ""
    win = d.get("winner")
    call_hl = "#0f2018" if win == "CALL" else "transparent"
    put_hl = "#20100f" if win == "PUT" else "transparent"
    head = (f"<div style='display:flex;font-size:10px;letter-spacing:.10em;"
            f"color:#b3c2d4;text-transform:uppercase;padding-bottom:2px;"
            f"border-bottom:1px solid #1e2836'>"
            f"<span style='flex:1'>CALL vs PUT</span>"
            f"<span style='width:82px;text-align:right;background:{call_hl}'>"
            f"Call{' 👑' if win == 'CALL' else ''}</span>"
            f"<span style='width:82px;text-align:right;background:{put_hl}'>"
            f"Put{' 👑' if win == 'PUT' else ''}</span></div>")
    body = "".join(
        f"<div style='display:flex;font-size:11.5px;padding:1px 0'>"
        f"<span style='flex:1;color:#cfd9e6'>{r['metric']}</span>"
        f"<span style='width:82px;text-align:right;color:#edf3f9;"
        f"background:{call_hl}'>{r['call']}</span>"
        f"<span style='width:82px;text-align:right;color:#edf3f9;"
        f"background:{put_hl}'>{r['put']}</span></div>" for r in rows)
    tail = (f"<div style='margin-top:3px;font-size:11px;color:"
            f"{'#00ff88' if win == 'CALL' else '#ff6666' if win == 'PUT' else '#cfd9e6'}'>"
            + (f"{win} side stronger — {d.get('why', '')}" if win
               else f"No side dominant — {d.get('why', '')}") + "</div>")
    return f"<div style='{_CARD}'>{head}{body}{tail}</div>"


# ── the mini intelligence panel ─────────────────────────────────────────
def intelligence_html(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    rs = list(rows or [])
    if not rs:
        return ""
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:12.5px;font-weight:800;color:#ffffff;"
            f"margin-bottom:3px'>🧠 Option intelligence</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;align-items:baseline;"
                f"font-size:12px;padding:1px 0'>"
                f"<span style='width:96px;color:#cfd9e6'>{r['label']}</span>"
                f"<span style='font-weight:700;color:"
                f"{bias_tone(r.get('tone'), '#edf3f9')}'>{r['value']}</span>"
                + (f"<span style='color:#ffd000;font-size:11px'>{r['stars']}"
                   f"</span>" if r.get("stars") else "")
                + f"<span style='margin-left:auto;font-size:9.5px;"
                  f"color:#9fb0c4'>{r.get('engine', '')}</span></div>"
                for r in rs)
            + "</div>")


# ── the recommendation banner ───────────────────────────────────────────
def recommendation_html(r: Optional[Dict[str, Any]]) -> str:
    d = r or {}
    if not d.get("action"):
        return ""
    col = d.get("colour", "#cfd9e6")

    if not d.get("trading"):
        return (
            f"<div style='margin-top:6px;padding:12px 16px;background:#111a26;"
            f"border:2px solid {col};border-radius:11px'>"
            f"<div style='display:flex;align-items:baseline;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<span style='font-size:24px;font-weight:900;color:{col}'>"
            f"{d.get('emoji', '')} {d['action']}</span>"
            f"<span style='font-size:15px;color:#edf3f9'>"
            f"{d.get('headline', '')}</span>"
            + (f"<span style='margin-left:auto;font-size:12px;color:#cfd9e6'>"
               f"readiness <b style='color:#ffcc33'>{d.get('readiness', 0)}%"
               f"</b> · risk {d.get('risk', '—')}</span>")
            + "</div>"
            + "".join(f"<div style='font-size:12.5px;color:#ffcc66;"
                      f"margin-top:2px'>• {x}</div>"
                      for x in (d.get("reasons") or [])[:4])
            + "</div>")

    cells = [("Entry", _rs(d.get("entry"), dp=0), "#00ff88"),
             ("Stop", _rs(d.get("stop"), dp=0), "#ff6666"),
             ("Trail", _rs(d.get("trail"), dp=0), "#a78bfa"),
             ("Target", _rs(d.get("target"), dp=0), "#7fe8b0")]
    leg = []
    if d.get("leg_entry") is not None:
        leg = [("Leg entry", _rs(d["leg_entry"]), "#00ff88"),
               ("Leg stop", _rs(d.get("leg_stop")), "#ff6666"),
               ("Leg trail", _rs(d.get("leg_trail")), "#a78bfa")]

    return (
        f"<div style='margin-top:6px;padding:12px 16px;background:#0a1f16;"
        f"border:2px solid {col};border-radius:11px'>"
        f"<div style='display:flex;align-items:baseline;gap:12px;"
        f"flex-wrap:wrap'>"
        f"<span style='font-size:26px;font-weight:900;color:{col}'>"
        f"{d.get('emoji', '')} {d['action']}</span>"
        f"<span style='font-size:17px;font-weight:800;color:#ffffff'>"
        f"{d.get('confidence', 0)}%</span>"
        + (f"<span style='font-size:13px;color:#c9b6ec'>Quality "
           f"{d['quality']}</span>" if d.get("quality") else "")
        + f"<span style='margin-left:auto;font-size:12px;color:#cfd9e6'>"
          f"risk {d.get('risk', '—')}</span></div>"
        f"<div style='display:flex;gap:16px;margin-top:6px;flex-wrap:wrap'>"
        + "".join(
            f"<div><span style='font-size:9px;letter-spacing:.10em;"
            f"color:#b3c2d4;text-transform:uppercase'>{k}</span>"
            f"<div style='font-size:18px;font-weight:800;color:{c}'>{v}</div>"
            f"</div>" for k, v, c in cells)
        + "</div>"
        + f"<div style='font-size:10px;color:#9fb0c4;margin-top:1px'>"
          f"levels in {d.get('units', 'NIFTY points')}</div>"
        + (f"<div style='display:flex;gap:16px;margin-top:5px;flex-wrap:wrap;"
           f"padding-top:5px;border-top:1px solid #17402e'>"
           + "".join(
               f"<div><span style='font-size:9px;letter-spacing:.10em;"
               f"color:#b3c2d4;text-transform:uppercase'>{k}</span>"
               f"<div style='font-size:15px;font-weight:800;color:{c}'>{v}"
               f"</div></div>" for k, v, c in leg)
           + f"<div style='font-size:10px;color:#9fb0c4;align-self:flex-end'>"
             f"{d.get('leg_tag', '')} — from the leg Entry Gate</div></div>"
           if leg else
           (f"<div style='margin-top:4px;font-size:11px;color:#c4d0de'>"
            f"{d['leg_note']}</div>" if d.get("leg_note") else ""))
        + "".join(f"<div style='font-size:12.5px;color:#7fe8b0;margin-top:2px'>"
                  f"{x}</div>" for x in (d.get("reasons") or [])[:4])
        + "</div>")
