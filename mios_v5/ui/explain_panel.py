"""MIOS V6.5 — Stages 61-64 panels: decision explanation · WAIT analysis ·
entry checklist · risk analysis.

Every ✓ and ✗ renders with the engine that produced it. That is deliberately
noisier than a clean tick list: the noise is the evidence, and a checklist that
hides which engine said what is a status light rather than an explanation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")

_RISK_COLOUR = {"Low": "#00ff88", "Moderate": "#ffd000",
                "Elevated": "#ff9500", "High": "#ff4444"}


def _rows(items: Sequence[Dict[str, Any]], colour: str) -> str:
    return "".join(
        f"<div style='display:flex;gap:6px;align-items:baseline;margin-top:2px'>"
        f"<span style='color:{colour};font-size:12px'>{i.get('mark', '•')}</span>"
        f"<span style='font-size:12.5px;color:#ffffff;font-weight:600'>"
        f"{i.get('label')}</span>"
        f"<span style='font-size:12px;color:#dfe7f0'>— {i.get('actual')}</span>"
        + (f"<span style='font-size:10px;color:#9fb0c4;margin-left:auto;"
           f"white-space:nowrap'>{i.get('engine')}</span>"
           if i.get("engine") else "")
        + "</div>" for i in items)


# ── Stage 61 + 62 ───────────────────────────────────────────────────────
def decision_explanation_html(e: Optional[Dict[str, Any]]) -> str:
    x = e or {}
    if not x.get("action"):
        return ""
    col = x.get("colour", "#cfd9e6")
    conf = (f"<span style='font-size:20px;color:#ffffff'> "
            f"{x['confidence']}%</span>" if x.get("confidence") else "")
    risk = x.get("risk")
    rcol = _RISK_COLOUR.get(risk, "#cfd9e6")

    head = (f"<div style='display:flex;align-items:baseline;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<span style='font-size:26px;font-weight:900;color:{col}'>"
            f"{x.get('emoji')} {x.get('action')}"
            f"{(' ' + x['side']) if x.get('side') else ''}</span>{conf}"
            + (f"<span style='margin-left:auto;font-size:11.5px;color:#cfd9e6'>"
               f"Risk <b style='color:{rcol}'>{risk}</b></span>" if risk else "")
            + "</div>")

    what = (f"<div style='font-size:12.5px;color:#9fd3ff;margin-top:3px'>"
            f"What happened: {x['what_happened']}</div>"
            if x.get("what_happened") else "")

    body = []
    if x.get("reasons"):
        body.append(f"<div style='margin-top:6px;font-size:10px;"
                    f"letter-spacing:.10em;color:#cfd9e6;"
                    f"text-transform:uppercase'>Reason</div>"
                    + _rows(x["reasons"], "#00ff88"))
    if x.get("opposed"):
        body.append(f"<div style='margin-top:6px;font-size:10px;"
                    f"letter-spacing:.10em;color:#cfd9e6;"
                    f"text-transform:uppercase'>Against</div>"
                    + _rows(x["opposed"], "#ff6666"))
    if x.get("needs"):
        body.append(
            f"<div style='margin-top:6px;font-size:10px;letter-spacing:.10em;"
            f"color:#cfd9e6;text-transform:uppercase'>Need</div>"
            + "".join(
                f"<div style='font-size:12.5px;color:#ffcc33;margin-top:2px'>"
                f"✓ {n.get('label')} "
                f"<span style='color:#c4d0de'>— have: {n.get('have')}</span>"
                f"</div>" for n in x["needs"][:6]))
        body.append(
            f"<div style='margin-top:6px;font-size:13px;color:#ffffff'>"
            f"Estimated readiness <b style='color:#ffcc33'>"
            f"{x.get('readiness', 0)}%</b>"
            f"<div style='font-size:11.5px;color:#cfd9e6'>"
            f"{x.get('readiness_label', '')}</div></div>")
    if x.get("unmeasured"):
        body.append(f"<div style='margin-top:5px;font-size:11px;color:#9fb0c4'>"
                    f"⚪ Not measurable this cycle: "
                    f"{', '.join(x['unmeasured'])}</div>")
    if x.get("risk_reasons"):
        body.append(f"<div style='margin-top:5px;font-size:11px;color:{rcol}'>"
                    f"Risk drivers: {' · '.join(x['risk_reasons'][:3])}</div>")
    if x.get("expect"):
        body.append(f"<div style='margin-top:5px;font-size:11.5px;"
                    f"color:#9fd3ff'>Expect: {' · '.join(x['expect'][:2])}</div>")
    if x.get("invalidates"):
        body.append(f"<div style='margin-top:2px;font-size:11.5px;"
                    f"color:#ffcc66'>Invalidated by: "
                    f"{' · '.join(x['invalidates'][:2])}</div>")

    return (f"<div style='{_CARD};border-left:3px solid {col}'>"
            + head + what + "".join(body) + "</div>")


# ── Stage 63 ────────────────────────────────────────────────────────────
def checklist_html(cl: Optional[Dict[str, Any]], compact: bool = False) -> str:
    c = cl or {}
    rows = c.get("rows") or []
    if not rows:
        return ""
    ready = int(c.get("readiness") or 0)
    rcol = "#00ff88" if ready >= 80 else "#ffd000" if ready >= 50 else "#ff6666"
    out = [f"<div style='{_CARD}'>",
           f"<div style='display:flex;align-items:baseline;gap:8px'>"
           f"<span style='font-size:13px;font-weight:800;color:#ffffff'>"
           f"✅ Entry checklist</span>"
           f"<span style='font-size:11px;color:#cfd9e6'>"
           f"{c.get('side') or 'no side proposed'}</span>"
           f"<span style='margin-left:auto;font-size:13px;font-weight:800;"
           f"color:{rcol}'>{ready}%</span></div>"]
    for r in rows:
        col = ("#00ff88" if r["state"] is True else
               "#ff6666" if r["state"] is False else "#9fb0c4")
        out.append(
            f"<div style='display:flex;gap:6px;align-items:baseline;"
            f"margin-top:2px'>"
            f"<span style='width:18px'>{r['icon']}</span>"
            f"<span style='width:150px;font-size:12px;font-weight:600;"
            f"color:#edf3f9'>{r['label']}</span>"
            f"<span style='flex:1;min-width:0;font-size:11.5px;color:{col};"
            f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
            f"{r['actual']}</span>"
            + ("" if compact else
               f"<span style='font-size:10px;color:#9fb0c4;white-space:nowrap'>"
               f"{r['engine']}</span>")
            + "</div>")
    dec = c.get("decision_label") or c.get("decision")
    out.append(f"<div style='margin-top:6px;padding-top:5px;border-top:1px "
               f"solid #1e2836;font-size:12.5px;color:#ffffff'>"
               f"Decision <b>{dec}</b>"
               f"<span style='color:#b3c2d4'> · coverage "
               f"{c.get('coverage', 0)}%</span></div></div>")
    return "".join(out)


def checklist_line(cl: Optional[Dict[str, Any]]) -> str:
    """The single compact strip for the Trade Card."""
    c = cl or {}
    rows = c.get("rows") or []
    if not rows:
        return ""
    ready = int(c.get("readiness") or 0)
    rcol = "#00ff88" if ready >= 80 else "#ffd000" if ready >= 50 else "#ff6666"
    icons = "".join(
        f"<span title='{r['label']}: {r['actual']}' style='font-size:13px'>"
        f"{r['icon']}</span>" for r in rows)
    blocking = c.get("blocking")
    tail = (f"<div style='font-size:12px;color:#ff9d9d;margin-top:1px'>"
            f"blocked on {blocking['label']} — {blocking['actual']}</div>"
            if blocking else "")
    return (f"<div style='text-align:center;margin-top:5px'>"
            f"<div style='letter-spacing:.18em'>{icons}</div>"
            f"<div style='font-size:12.5px;color:#cfd9e6;margin-top:1px'>"
            f"checklist <b style='color:{rcol}'>{ready}%</b> ready</div>"
            f"{tail}</div>")


# ── Stage 64 ────────────────────────────────────────────────────────────
def risk_html(ra: Optional[Dict[str, Any]]) -> str:
    r = ra or {}
    if not r.get("available"):
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>{r.get('reason', 'No risk analysis.')}"
                f"</div></div>")

    def block(title, node, colour):
        n = node or {}
        basis = n.get("basis")
        tag = ("" if basis in (None, "proven") else
               f" <span style='font-size:9.5px;color:#7a6a3a;"
               f"border:1px solid #4a3f22;border-radius:3px;padding:0 3px'>"
               f"{basis}</span>")
        return (f"<div style='margin-top:5px'>"
                f"<div style='font-size:10px;letter-spacing:.10em;"
                f"color:#cfd9e6;text-transform:uppercase'>{title}{tag}</div>"
                f"<div style='font-size:15px;font-weight:800;color:{colour}'>"
                f"{n.get('display', n.get('mode', '—'))}</div>"
                f"<div style='font-size:11.5px;color:#dfe7f0'>"
                f"{n.get('why', '')}</div></div>")

    rr = r.get("rr") or {}
    rrcol = "#00ff88" if rr.get("acceptable") else "#ff9500"
    return (
        f"<div style='{_CARD}'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
        f"🧮 Risk analysis — {r.get('side')}</div>"
        + block("Entry", r.get("entry"), "#ffffff")
        + block("Stop", r.get("stop"), "#ff9d9d")
        + block("Target", r.get("target"), "#7fe8b0")
        + block("Trail", r.get("trail"), "#c9b6ec")
        + f"<div style='margin-top:5px'>"
          f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
          f"text-transform:uppercase'>Reward : Risk</div>"
          f"<div style='font-size:15px;font-weight:800;color:{rrcol}'>"
          f"{rr.get('display', '—')}</div>"
          f"<div style='font-size:11.5px;color:#dfe7f0'>{rr.get('why', '')}"
          f"</div></div>"
        + f"<div style='margin-top:6px;padding-top:5px;border-top:1px solid "
          f"#1e2836'>"
          f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
          f"text-transform:uppercase'>Invalidation</div>"
        + "".join(
            f"<div style='font-size:12px;color:#ffcc66;margin-top:2px'>"
            f"• {i.get('what')} "
            f"<span style='color:#c4d0de'>({i.get('detail')})</span>"
            f"<span style='font-size:10px;color:#9fb0c4'> "
            f"{i.get('engine')}</span></div>"
            for i in (r.get("invalidation") or []))
        + "</div></div>")


def boundary_html() -> str:
    """Stated on screen so it cannot quietly lapse."""
    return (
        f"<div style='{_CARD};border-color:#2f3f2f'>"
        f"<div style='font-size:11.5px;color:#cfd9e6;line-height:1.55'>"
        f"<b style='color:#7fe8b0'>Explainability boundary.</b> This layer "
        f"<b>explains, narrates, summarises, justifies and reviews</b>. It "
        f"generates no signal, changes no confidence, moves no threshold or "
        f"engine weight, and never influences the Decision Engine. Every line "
        f"above is quoted from an engine that actually reported."
        f"</div></div>")
