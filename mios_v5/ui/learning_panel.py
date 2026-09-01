"""MIOS V6 — Dashboard 5: the Learning Dashboard (Stages 55-60).

The one screen that answers *is MIOS actually any good, and which part of it
isn't?*

Every number here is rendered with its **sample size** next to it, and any
figure below the significance floor is drawn dimmed and labelled rather than
omitted. Hiding a weak result is the same failure as hiding a bad one — it just
looks more responsible. Suggestions carry an explicit "human decision required"
badge, because nothing on this screen is applied by the system.
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


def _num(v, suffix: str = "%") -> str:
    x = _f(v)
    return "—" if x is None else f"{x:g}{suffix}"


def _bar(pct: Optional[float], colour: str) -> str:
    p = max(0.0, min(100.0, _f(pct) or 0.0))
    return (f"<span style='display:inline-block;width:56px;height:6px;"
            f"background:#1a2331;border-radius:3px;overflow:hidden;'>"
            f"<span style='display:block;width:{p:.0f}%;height:6px;"
            f"background:{colour};'></span></span>")


# ── overall ─────────────────────────────────────────────────────────────
def overall_html(stats: Optional[Dict[str, Any]]) -> str:
    s = stats or {}
    graded = int(s.get("graded") or 0)
    tiles = [
        ("Graded trades", str(graded), "#ffffff"),
        ("Win rate", _num(s.get("win_rate")),
         "#00ff88" if (_f(s.get("win_rate")) or 0) >= 50 else "#ff6666"),
        ("Profit factor", _num(s.get("profit_factor"), ""), "#9fd3ff"),
        ("Avg MFE", _num(s.get("avg_mfe"), " pts"), "#7fe8b0"),
        ("Avg MAE", _num(s.get("avg_mae"), " pts"), "#ff9d9d"),
        ("Avg hold", _num(s.get("avg_hold_min"), " min"), "#edf3f9"),
    ]
    warm = ("" if graded >= 30 else
            f"<div style='font-size:11.5px;color:#ffcc33;margin-top:5px;'>"
            f"⚠️ {graded} graded trades — everything on this screen is "
            f"provisional until roughly 30.</div>")
    return (
        f"<div style='{_CARD}'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
        f"margin-bottom:5px'>📊 Overall accuracy</div>"
        f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
        + "".join(
            f"<div style='flex:1;min-width:104px'>"
            f"<div style='font-size:9.5px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{k}</div>"
            f"<div style='font-size:16px;font-weight:800;color:{c}'>{v}</div>"
            f"</div>" for k, v, c in tiles)
        + "</div>" + warm + "</div>")


# ── Stage 56 ────────────────────────────────────────────────────────────
def accuracy_html(rank_rows: Optional[Sequence[Dict[str, Any]]],
                  window: str = "last100") -> str:
    rows = list(rank_rows or [])
    if not rows:
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>No per-engine history yet.</div></div>")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🏆 Engine rankings — precision ({window})</div>",
           f"<div style='font-size:10px;color:#b3c2d4;margin-bottom:4px'>"
           f"“when this engine agrees, how often does the trade win?”</div>"]
    for r in rows[:20]:
        val = _f(r.get("value"))
        dim = not r.get("ranked")
        col = ("#b3c2d4" if dim else
               "#00ff88" if (val or 0) >= 65 else
               "#ffd000" if (val or 0) >= 50 else "#ff6666")
        iv = r.get("interval") or {}
        band = (f" <span style='color:#b3c2d4;font-size:10px'>"
                f"[{iv.get('low')}–{iv.get('high')}]</span>" if iv else "")
        tag = ("" if r.get("significant") else
               " <span style='color:#ffcc33;font-size:10px'>thin</span>")
        out.append(
            f"<div style='display:flex;gap:8px;align-items:center;margin-top:3px;"
            f"opacity:{0.5 if dim else 1}'>"
            f"<span style='flex:1;min-width:0;font-size:11.5px;color:#edf3f9;"
            f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>"
            f"{r.get('engine')}</span>"
            + _bar(val, col)
            + f"<span style='width:52px;text-align:right;font-size:12.5px;"
              f"font-weight:800;color:{col}'>{_num(val)}</span>"
              f"<span style='width:44px;text-align:right;font-size:10.5px;"
              f"color:#b3c2d4'>n={r.get('sample', 0)}</span>{band}{tag}</div>")
    out.append("</div>")
    return "".join(out)


# ── Stage 57 ────────────────────────────────────────────────────────────
def calibration_html(suggestions: Optional[Sequence[Dict[str, Any]]],
                     report: Optional[Dict[str, Any]] = None,
                     window: str = "last100") -> str:
    sugg = list(suggestions or [])
    body = []
    if not sugg:
        n = len(report or {})
        body.append(f"<div style='font-size:12.5px;color:#7fe8b0'>"
                    f"✓ No proven miscalibration across {n} engines — every "
                    f"claimed confidence sits inside its own margin of error."
                    f"</div>")
    for s in sugg[:10]:
        gap = _f(s.get("gap")) or 0.0
        col = "#ff9500" if gap < 0 else "#4da6ff"
        body.append(
            f"<div style='margin-top:5px;padding:6px 8px;background:#111a26;"
            f"border-left:3px solid {col};border-radius:5px'>"
            f"<div style='font-size:12px;font-weight:800;color:#ffffff'>"
            f"{s.get('engine')} &nbsp;"
            f"<span style='color:{col}'>{_num(s.get('current'))} → "
            f"{_num(s.get('suggested'))}</span></div>"
            f"<div style='font-size:11px;color:#cfd9e6;margin-top:1px'>"
            f"{s.get('reason', '')}</div>"
            f"<div style='font-size:10px;color:#ffcc33;margin-top:2px'>"
            f"⚑ {s.get('action')} · not applied</div></div>")
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:4px'>🎯 Confidence calibration ({window})</div>"
            + "".join(body) + "</div>")


# ── Stage 58 ────────────────────────────────────────────────────────────
def thresholds_html(opt: Optional[Dict[str, Any]]) -> str:
    o = opt or {}
    sugg = o.get("suggestions") or []
    body = []
    if not sugg:
        body.append(f"<div style='font-size:12.5px;color:#cfd9e6'>"
                    f"No threshold change clears the noise floor on the "
                    f"current history.</div>")
    for s in sugg[:8]:
        body.append(
            f"<div style='margin-top:5px;padding:6px 8px;background:#111a26;"
            f"border-left:3px solid #a78bfa;border-radius:5px'>"
            f"<div style='font-size:12px;font-weight:800;color:#ffffff'>"
            f"{s.get('field')} &nbsp;<span style='color:#c9b6ec'>"
            f"{_num(s.get('from'), '')} → {_num(s.get('to'), '')}</span>"
            f"<span style='color:#7fe8b0'> &nbsp;"
            f"+{_num(s.get('expected_improvement'))} win rate</span></div>"
            f"<div style='font-size:11px;color:#cfd9e6;margin-top:1px'>"
            f"keeps {s.get('kept_sample')} trades at "
            f"{_num(s.get('new_win_rate'))} · avoids "
            f"{s.get('losers_avoided')} losers · "
            f"<span style='color:#ff9d9d'>costs {s.get('winners_lost')} "
            f"winners</span></div>"
            f"<div style='font-size:10px;color:#ffcc33;margin-top:2px'>"
            f"⚑ {s.get('action')} · not deployed</div></div>")
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:4px'>🎚 Threshold suggestions</div>"
            + "".join(body)
            + f"<div style='font-size:10.5px;color:#b3c2d4;margin-top:6px'>"
              f"{o.get('note', '')}</div></div>")


# ── Stage 59 ────────────────────────────────────────────────────────────
def contribution_html(report: Optional[Dict[str, Any]],
                      lines: Optional[Sequence[str]] = None) -> str:
    r = report or {}
    groups = (("Most valuable", r.get("top"), "#00ff88"),
              ("Actively harmful", r.get("weakest"), "#ff6666"),
              ("Most influential", r.get("most_influential"), "#9fd3ff"),
              ("Making no difference", r.get("least_useful"), "#b3c2d4"))
    body = []
    for title, rows, col in groups:
        rows = [x for x in (rows or [])]
        if not rows:
            continue
        body.append(
            f"<div style='margin-top:5px'>"
            f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{title}</div>"
            + "".join(
                f"<div style='font-size:11.5px;color:{col}'>• "
                f"{x.get('engine')} "
                f"<span style='color:#b3c2d4'>"
                f"{x.get('avg_credit', 0):+.3f} credit · "
                f"{x.get('trades', 0)} trades</span></div>" for x in rows[:5])
            + "</div>")
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
            f"🧮 Engine contribution (Shapley)</div>"
            f"<div style='font-size:10px;color:#b3c2d4;margin-bottom:2px'>"
            f"{r.get('note', '')}</div>"
            + "".join(body)
            + "".join(f"<div style='font-size:12px;color:#dfe7f0;margin-top:5px'>"
                      f"{l}</div>" for l in (lines or []))
            + "</div>")


# ── Stage 60 ────────────────────────────────────────────────────────────
def false_signal_html(analysis: Optional[Dict[str, Any]],
                      recent: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    a = analysis or {}
    body = [f"<div style='font-size:12.5px;color:#edf3f9;margin-bottom:4px'>"
            f"{a.get('summary', '')}</div>"]
    for c in (a.get("top_causes") or [])[:6]:
        body.append(
            f"<div style='display:flex;gap:8px;align-items:center;margin-top:3px'>"
            f"<span style='flex:1;min-width:0;font-size:11.5px;color:#edf3f9'>"
            f"{c.get('label')}</span>"
            + _bar(c.get("pct"), "#ff6666")
            + f"<span style='width:60px;text-align:right;font-size:11.5px;"
              f"color:#ff9d9d'>{c.get('count')} ({_num(c.get('pct'))})</span>"
              f"</div>")
    if a.get("outvoted_leaders"):
        names = ", ".join(f"{x['name']} ({x['count']})"
                          for x in a["outvoted_leaders"][:3])
        body.append(f"<div style='margin-top:6px;font-size:11.5px;"
                    f"color:#ffcc33'>⚑ Called it right and was outvoted most "
                    f"often: {names} — a weight that may be too low.</div>")
    if a.get("worst_engines"):
        names = ", ".join(f"{x['engine']} ({x['losses']})"
                          for x in a["worst_engines"][:3])
        body.append(f"<div style='margin-top:3px;font-size:11.5px;"
                    f"color:#ff9d9d'>On the wrong side most often: {names}."
                    f"</div>")
    for inv in (recent or [])[:5]:
        body.append(f"<div style='margin-top:4px;font-size:11px;color:#cfd9e6;"
                    f"border-left:2px solid #2a3646;padding-left:6px'>"
                    f"{inv.get('signal_id', '')} — {inv.get('summary', '')}"
                    f"</div>")
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:4px'>🔍 False-signal analysis</div>"
            + "".join(body) + "</div>")


def governance_html() -> str:
    """The limits, stated on the screen itself so they cannot quietly lapse."""
    return (
        f"<div style='{_CARD};border-color:#2f3f2f'>"
        f"<div style='font-size:11.5px;color:#cfd9e6;line-height:1.55'>"
        f"<b style='color:#7fe8b0'>Learning Engine boundary.</b> This screen "
        f"<b>observes, measures, explains, recommends and validates</b>. It "
        f"never influences a live decision, never moves a threshold or an "
        f"engine weight on its own, and never hides a poor result. Every "
        f"suggestion above requires a human to act on it, and history is "
        f"append-only — nothing here is ever overwritten."
        f"</div></div>")


def render(st, payload: Optional[Dict[str, Any]]) -> None:
    """The whole of Dashboard 5, in order."""
    p = payload or {}
    st.markdown(overall_html(p.get("overall")), unsafe_allow_html=True)
    st.markdown(accuracy_html(p.get("rankings"), p.get("window", "last100")),
                unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(calibration_html(p.get("calibration_suggestions"),
                                     p.get("calibration"),
                                     p.get("window", "last100")),
                    unsafe_allow_html=True)
    with c2:
        st.markdown(thresholds_html(p.get("thresholds")), unsafe_allow_html=True)
    st.markdown(contribution_html(p.get("contribution"),
                                  p.get("contribution_lines")),
                unsafe_allow_html=True)
    st.markdown(false_signal_html(p.get("false_signals"),
                                  p.get("recent_losses")),
                unsafe_allow_html=True)
    st.markdown(governance_html(), unsafe_allow_html=True)
