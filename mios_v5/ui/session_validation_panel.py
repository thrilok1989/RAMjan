"""MIOS V6 — Stage 70 Session Validation panels.

Every number is rendered with its sample size and, where it exists, its
confidence interval. A win rate without those is an opinion wearing a uniform —
and this screen exists specifically to decide whether to trust Stage 69, so it
has to be harder on itself than a normal panel.
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


def _pct(v, dp=1) -> str:
    x = _f(v)
    return "—" if x is None else f"{x:.{dp}f}%"


def _num(v, suffix="", dp=1) -> str:
    x = _f(v)
    return "—" if x is None else f"{x:.{dp}f}{suffix}"


def _wr_colour(v) -> str:
    x = _f(v)
    if x is None:
        return "#9fb0c4"
    return "#00ff88" if x >= 55 else "#ffd000" if x >= 45 else "#ff6666"


# ── PART 1 · the performance table ──────────────────────────────────────
def performance_html(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    rs = list(rows or [])
    if not rs:
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>No graded trades joined to a session yet — "
                f"run <code>sql/029</code> and <code>sql/030</code>, then let "
                f"a few sessions record.</div></div>")
    head = ("Session", "Sig", "Valid", "Win", "R:R", "Hold", "MFE", "MAE",
            "Conf", "Quality")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>📊 Session performance</div>",
           "<div style='overflow-x:auto'>",
           "<div style='display:flex;font-size:9.5px;letter-spacing:.08em;"
           "color:#b3c2d4;text-transform:uppercase;padding-bottom:2px;"
           "border-bottom:1px solid #1e2836;min-width:640px'>"
           + f"<span style='flex:1;min-width:190px'>{head[0]}</span>"
           + "".join(f"<span style='width:52px;text-align:right'>{h}</span>"
                     for h in head[1:]) + "</div>"]
    for r in rs:
        thin = bool(r.get("thin"))
        iv = r.get("interval") or {}
        band = (f"<div style='font-size:9px;color:#9fb0c4'>"
                f"[{iv.get('low')}–{iv.get('high')}]</div>" if iv else "")
        out.append(
            f"<div style='display:flex;font-size:11.5px;padding:2px 0;"
            f"border-bottom:1px solid #161b22;min-width:640px;"
            f"opacity:{0.55 if thin else 1}'>"
            f"<span style='flex:1;min-width:190px;color:#edf3f9'>"
            f"{r.get('label')}"
            + ("<span style='color:#ffcc33;font-size:9px'> thin</span>"
               if thin else "") + "</span>"
            f"<span style='width:52px;text-align:right;color:#cfd9e6'>"
            f"{r.get('signals', 0)}</span>"
            f"<span style='width:52px;text-align:right;color:#cfd9e6'>"
            f"{r.get('valid', 0)}</span>"
            f"<span style='width:52px;text-align:right;font-weight:800;"
            f"color:{_wr_colour(r.get('win_rate'))}'>"
            f"{_pct(r.get('win_rate'), 0)}{band}</span>"
            f"<span style='width:52px;text-align:right;color:#edf3f9'>"
            f"{_num(r.get('avg_rr'), '', 2)}</span>"
            f"<span style='width:52px;text-align:right;color:#edf3f9'>"
            f"{_num(r.get('avg_holding_min'), 'm', 0)}</span>"
            f"<span style='width:52px;text-align:right;color:#7fe8b0'>"
            f"{_num(r.get('avg_mfe'), '', 0)}</span>"
            f"<span style='width:52px;text-align:right;color:#ff9d9d'>"
            f"{_num(r.get('avg_mae'), '', 0)}</span>"
            f"<span style='width:52px;text-align:right;color:#edf3f9'>"
            f"{_num(r.get('avg_confidence'), '', 0)}</span>"
            f"<span style='width:52px;text-align:right;font-size:10px;"
            f"color:#c9b6ec'>{r.get('avg_market_quality') or '—'}</span>"
            f"</div>")
    out.append("</div><div style='margin-top:6px;font-size:10.5px;"
               "color:#9fb0c4'>Rows with fewer than 10 graded trades are "
               "dimmed — shown, not trusted. Ordered by time of day, not by "
               "win rate: reading the session in order is what makes a bad "
               "hour visible.</div></div>")
    return "".join(out)


# ── PART 2 · the counterfactual ─────────────────────────────────────────
def counterfactual_html(c: Optional[Dict[str, Any]]) -> str:
    d = c or {}
    without, with_ = d.get("without") or {}, d.get("with") or {}
    up = _f(d.get("improvement_pct"))
    col = ("#00ff88" if d.get("promotable") else
           "#ffd000" if (up or 0) > 0 else "#cfd9e6")

    tiles = [
        ("Without Stage 69", _pct(without.get("win_rate"), 0),
         _wr_colour(without.get("win_rate")),
         f"{without.get('n', 0)} trades"),
        ("With Stage 69", _pct(with_.get("win_rate"), 0),
         _wr_colour(with_.get("win_rate")), f"{with_.get('n', 0)} trades"),
        ("Improvement", (f"{up:+.1f} pts" if up is not None else "—"), col, ""),
        ("Losers removed", str(d.get("false_signal_reduction", 0)), "#7fe8b0",
         "false signals avoided"),
        ("Winners removed", str(d.get("winners_lost", 0)), "#ff9d9d",
         "the cost of the filter"),
        ("Avg profit", (f"{_f(d.get('avg_profit_increase')):+.2f} pts"
                        if d.get("avg_profit_increase") is not None else "—"),
         "#9fd3ff", "per trade"),
    ]

    return (
        f"<div style='{_CARD};border-left:3px solid {col}'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff'>"
        f"🔬 Would session adjustment have helped?</div>"
        f"<div style='font-size:11px;color:#b3c2d4;margin-bottom:5px'>"
        f"Counterfactual — Stage 69's modifiers have never been applied; this "
        f"replays what they WOULD have done.</div>"
        "<div style='display:flex;gap:10px;flex-wrap:wrap'>"
        + "".join(
            f"<div style='flex:1;min-width:110px'>"
            f"<div style='font-size:9px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{k}</div>"
            f"<div style='font-size:17px;font-weight:800;color:{c2}'>{v}</div>"
            f"<div style='font-size:9.5px;color:#9fb0c4'>{sub}</div></div>"
            for k, v, c2, sub in tiles)
        + "</div>"
        f"<div style='margin-top:7px;font-size:12.5px;color:{col}'>"
        f"{d.get('verdict', '')}</div>"
        + "".join(f"<div style='margin-top:3px;font-size:11px;color:#ffcc66'>"
                  f"⚠️ {x}</div>" for x in (d.get("caveats") or []))
        + f"<div style='margin-top:5px;font-size:10.5px;color:#9fb0c4'>"
          f"Promotion requires ≥{d.get('sample', 0) and ''}"
          f"{'' if d.get('significant') else 'more '}evidence and a human "
          f"decision — Stage 70 changes nothing.</div>"
        + "</div>")


# ── PART 3 · session profiles ───────────────────────────────────────────
def profiles_html(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    rs = list(rows or [])
    if not rs:
        return ""
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🧬 Session profiles</div>"]
    for p in rs:
        measured = p.get("source") == "measured"
        col = "#7fe8b0" if measured else "#9fb0c4"
        out.append(
            f"<div style='margin-top:5px;padding-left:7px;"
            f"border-left:2px solid {col}'>"
            f"<div style='font-size:12.5px;font-weight:800;color:#ffffff'>"
            f"{p.get('label')}"
            f"<span style='font-size:9.5px;color:{col};margin-left:6px'>"
            f"{'measured' if measured else 'a-priori'}</span>"
            + (f"<span style='margin-left:auto;font-size:12px;color:"
               f"{_wr_colour(p.get('historical_win_rate'))}'> "
               f"{_pct(p.get('historical_win_rate'), 0)}</span>"
               if p.get("historical_win_rate") is not None else "")
            + "</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;font-size:11.5px'>"
                f"<span style='width:132px;color:#cfd9e6'>{k}</span>"
                f"<span style='color:#edf3f9'>{v}</span></div>"
                for k, v in (("Best strategy", p.get("best_strategy") or "—"),
                             ("Avoid", p.get("avoid") or "—"),
                             ("Volatility", p.get("avg_volatility") or "—"),
                             ("Dealer activity", p.get("dealer_activity") or "—"),
                             ("Institutions", p.get("institution_activity") or "—"),
                             ("False breakouts",
                              (p.get("false_breakouts") or "—") +
                              (" (proxied from loss rate)"
                               if p.get("false_breakouts") else ""))))
            + f"<div style='font-size:10.5px;color:#9fb0c4;margin-top:1px'>"
              f"{p.get('note', '')}</div></div>")
    out.append("</div>")
    return "".join(out)


# ── PART 4 · adaptive recommendations ───────────────────────────────────
def recommendations_html(rows: Optional[Sequence[Dict[str, Any]]]) -> str:
    rs = list(rows or [])
    if not rs:
        return ""
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>🎯 Adaptive recommendations</div>"]
    for r in rs:
        sig = bool(r.get("significant"))
        iv = r.get("interval") or {}
        band = (f" <span style='color:#9fb0c4;font-size:9.5px'>"
                f"[{iv.get('low')}–{iv.get('high')}]</span>" if iv else "")
        out.append(
            f"<div style='margin-top:5px;padding-left:7px;border-left:2px "
            f"solid {'#7fe8b0' if sig else '#3a4757'};"
            f"opacity:{1 if sig else 0.6}'>"
            f"<div style='font-size:12.5px;font-weight:800;color:#ffffff'>"
            f"{r.get('label')}"
            f"<span style='font-size:10.5px;color:#cfd9e6;margin-left:6px'>"
            f"n={r.get('sample', 0)}{band}</span></div>"
            + "".join(f"<div style='font-size:12px;color:#7fe8b0'>✔ {x}</div>"
                      for x in (r.get("do") or []))
            + "".join(f"<div style='font-size:12px;color:#ff9d9d'>⚠ {x}</div>"
                      for x in (r.get("avoid") or []))
            + f"<div style='font-size:10px;color:#ffcc33;margin-top:1px'>"
              f"⚑ {r.get('action')} · not applied</div></div>")
    out.append("</div>")
    return "".join(out)


# ── PART 6 · did the recommendations hold? ──────────────────────────────
def scoring_html(s: Optional[Dict[str, Any]]) -> str:
    d = s or {}
    rows = d.get("rows") or []
    body = [f"<div style='font-size:12.5px;color:#edf3f9;margin-bottom:3px'>"
            f"{d.get('summary', '')}</div>"]
    for r in rows[:10]:
        drift = _f(r.get("drift"))
        col = ("#9fb0c4" if not r.get("significant") else
               "#00ff88" if r.get("held") else "#ff6666")
        body.append(
            f"<div style='display:flex;gap:8px;font-size:11.5px;padding:1px 0;"
            f"opacity:{1 if r.get('significant') else 0.55}'>"
            f"<span style='flex:1;min-width:0;color:#edf3f9'>"
            f"{r.get('label')}</span>"
            f"<span style='width:70px;text-align:right;color:#cfd9e6'>"
            f"was {_pct(r.get('claimed_win_rate'), 0)}</span>"
            f"<span style='width:70px;text-align:right;color:#edf3f9'>"
            f"now {_pct(r.get('since_win_rate'), 0)}</span>"
            f"<span style='width:64px;text-align:right;font-weight:700;"
            f"color:{col}'>"
            f"{(f'{drift:+.1f}' if drift is not None else '—')}</span>"
            f"<span style='width:56px;text-align:right;color:#9fb0c4'>"
            f"n={r.get('trades_since', 0)}</span></div>")
    return (f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:3px'>📉 Did the recommendations hold?</div>"
            + "".join(body)
            + f"<div style='margin-top:6px;font-size:10.5px;color:#9fb0c4'>"
              f"Each recommendation is compared to what its session did "
              f"AFTERWARDS — the only way to tell a real session edge from a "
              f"run of luck that has since reverted.</div></div>")


def boundary_html() -> str:
    return (
        f"<div style='{_CARD};border-color:#2f3f2f'>"
        f"<div style='font-size:11.5px;color:#cfd9e6;line-height:1.55'>"
        f"<b style='color:#7fe8b0'>Stage 70 boundary.</b> It <b>logs and "
        f"validates</b>. It cannot change the Decision Engine, a confidence or "
        f"a threshold, is not registered as an engine, and exposes no mutator. "
        f"Promotion of Stage 69's modifiers to live behaviour requires "
        f"statistically significant evidence <i>and</i> a human flipping "
        f"<code>session.SESSION_AWARE</code>."
        f"</div></div>")


def render(st, report: Optional[Dict[str, Any]]) -> None:
    r = report or {}
    st.markdown(counterfactual_html(r.get("counterfactual")),
                unsafe_allow_html=True)
    st.markdown(performance_html(r.get("performance")), unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(profiles_html(r.get("profiles")), unsafe_allow_html=True)
    with c2:
        st.markdown(recommendations_html(r.get("recommendations")),
                    unsafe_allow_html=True)
    st.markdown(scoring_html(r.get("recommendation_scoring")),
                unsafe_allow_html=True)
    st.markdown(boundary_html(), unsafe_allow_html=True)
