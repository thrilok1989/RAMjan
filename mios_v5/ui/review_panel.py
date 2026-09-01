"""MIOS V6.5 — Stage 66 Post-Trade Review + Stage 67 Daily Summary panels."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")


def _f(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _num(v, suffix="", dp=1):
    x = _f(v)
    return "—" if x is None else f"{x:.{dp}f}{suffix}"


def _field(title: str, value: str, colour: str = "#ffffff",
           sub: str = "") -> str:
    return (f"<div style='margin-top:5px'>"
            f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{title}</div>"
            f"<div style='font-size:13px;font-weight:700;color:{colour}'>"
            f"{value}</div>"
            + (f"<div style='font-size:11.5px;color:#cfd9e6'>{sub}</div>"
               if sub else "") + "</div>")


# ── Stage 66 ────────────────────────────────────────────────────────────
def review_html(rev: Optional[Dict[str, Any]]) -> str:
    r = rev or {}
    if not r.get("available"):
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>{r.get('reason', 'No review.')}</div></div>")
    won = bool(r.get("won"))
    col = "#00ff88" if won else "#ff6666"
    pnl = _f(r.get("pnl_points"))

    head = (f"<div style='display:flex;align-items:baseline;gap:10px;"
            f"flex-wrap:wrap'>"
            f"<span style='font-size:13px;font-weight:800;color:#ffffff'>"
            f"📋 Trade review</span>"
            f"<span style='font-size:11px;color:#9fb0c4'>"
            f"{r.get('signal_id', '')}</span>"
            f"<span style='margin-left:auto;font-size:17px;font-weight:900;"
            f"color:{col}'>{r.get('outcome')} "
            f"{('%+.0f pts' % pnl) if pnl is not None else ''}</span></div>")

    stats = (f"<div style='font-size:11.5px;color:#cfd9e6;margin-top:2px'>"
             f"MFE {_num(r.get('mfe'), ' pts', 0)} · "
             f"MAE {_num(r.get('mae'), ' pts', 0)} · "
             f"held {_num(r.get('holding_min'), ' min', 0)} · "
             f"exit {r.get('exit_reason', '—')} · "
             f"quality {r.get('trade_quality', '—')}</div>")

    body = [_field("Why", " · ".join((r.get("why") or [])[:4]) or "—")]
    if not won:
        body.append(_field("Primary cause", r.get("primary_cause") or "—",
                           "#ff9d9d", r.get("primary_evidence") or ""))
        if r.get("secondary_cause"):
            body.append(_field("Secondary cause", r["secondary_cause"],
                               "#ffcc66", r.get("secondary_evidence") or ""))
        body.append(_field("False signal type",
                           r.get("false_signal_type") or "—", "#ffcc66"))
        body.append(_field("Better alternative",
                           r.get("better_alternative") or "—", "#9fd3ff"))
    body.append(_field("Best engine", r.get("best_engine") or "—", "#7fe8b0",
                       (f"{r['best_credit']:+.3f} credit"
                        if r.get("best_credit") is not None else "")))
    body.append(_field("Weakest engine", r.get("weakest_engine") or "—",
                       "#ff9d9d",
                       (f"{r['weakest_credit']:+.3f} credit"
                        if r.get("weakest_credit") is not None else "")))
    body.append(_field("Improvement", r.get("improvement") or "—", "#ffd000"))
    if r.get("lessons"):
        body.append(
            f"<div style='margin-top:5px'>"
            f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>Lessons</div>"
            + "".join(f"<div style='font-size:12px;color:#edf3f9;"
                      f"margin-top:2px'>• {l}</div>"
                      for l in r["lessons"][:4]) + "</div>")
    if r.get("evolution"):
        body.append(f"<div style='margin-top:5px;font-size:11.5px;"
                    f"color:#cfd9e6'>How it evolved: {r['evolution']}</div>")

    return (f"<div style='{_CARD};border-left:3px solid {col}'>"
            + head + stats + "".join(body) + "</div>")


def review_list_html(reviews: Optional[Sequence[Dict[str, Any]]],
                     limit: int = 10) -> str:
    rs = [r for r in (reviews or []) if r.get("available")][:limit]
    if not rs:
        return (f"<div style='{_CARD}'><div style='font-size:12.5px;"
                f"color:#cfd9e6'>No graded trades to review yet.</div></div>")
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:4px'>📋 Recent trade reviews</div>"]
    for r in rs:
        col = "#00ff88" if r.get("won") else "#ff6666"
        out.append(
            f"<div style='margin-top:4px;padding-left:7px;border-left:2px "
            f"solid {col}'>"
            f"<div style='font-size:12.5px;font-weight:700;color:{col}'>"
            f"{r.get('headline', '')}</div>"
            f"<div style='font-size:11.5px;color:#cfd9e6'>"
            f"{r.get('improvement', '')}</div></div>")
    out.append("</div>")
    return "".join(out)


# ── Stage 67 ────────────────────────────────────────────────────────────
def daily_summary_html(s: Optional[Dict[str, Any]]) -> str:
    d = s or {}
    wr = _f(d.get("win_rate"))
    wcol = "#00ff88" if (wr or 0) >= 50 else "#ff6666"
    tiles = [
        ("Trades", str(d.get("trades", 0)), "#ffffff"),
        ("Wins", str(d.get("wins", 0)), "#00ff88"),
        ("Losses", str(d.get("losses", 0)), "#ff6666"),
        ("Win rate", _num(wr, "%"), wcol),
        ("Avg R:R", _num(d.get("avg_rr"), "", 2), "#9fd3ff"),
        ("Avg hold", _num(d.get("avg_holding_min"), " min", 0), "#edf3f9"),
    ]
    out = [f"<div style='{_CARD}'>",
           f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
           f"margin-bottom:5px'>🌙 Daily market summary"
           + (f" <span style='font-size:11px;color:#9fb0c4'>"
              f"{d['trading_day']}</span>" if d.get("trading_day") else "")
           + "</div>",
           "<div style='display:flex;gap:8px;flex-wrap:wrap'>"
           + "".join(
               f"<div style='flex:1;min-width:88px'>"
               f"<div style='font-size:9.5px;letter-spacing:.10em;"
               f"color:#cfd9e6;text-transform:uppercase'>{k}</div>"
               f"<div style='font-size:16px;font-weight:800;color:{c}'>{v}"
               f"</div></div>" for k, v, c in tiles)
           + "</div>"]

    out.append(_field("Market personality", d.get("market_personality", "—"),
                      "#c9b6ec", d.get("personality_why", "")))
    out.append(_field("Best engine", d.get("best_engine") or "—", "#7fe8b0",
                      _num(d.get("best_engine_precision"), "% precision")))
    out.append(_field("Weakest engine", d.get("weakest_engine") or "—",
                      "#ff9d9d",
                      _num(d.get("weakest_engine_precision"), "% precision")))
    out.append(_field("Most common WAIT reason",
                      d.get("most_common_wait_reason") or "—", "#ffcc66",
                      f"{d.get('wait_cycles', 0)} WAIT cycles logged"))
    out.append(_field("Most common false signal",
                      d.get("most_common_false_signal") or "—", "#ffcc66"))
    out.append(_field("Institutions", d.get("institution_activity", "—"),
                      "#9fd3ff"))
    out.append(_field("Dealers", d.get("dealer_behaviour", "—"), "#9fd3ff"))

    sup, res = _f(d.get("major_support")), _f(d.get("major_resistance"))
    if sup is not None or res is not None:
        out.append(_field(
            "Major levels",
            (f"🟢 ₹{sup:,.0f}" if sup is not None else "—") + " · "
            + (f"🔴 ₹{res:,.0f}" if res is not None else "—")))

    if d.get("tomorrow_watch"):
        out.append(
            f"<div style='margin-top:6px'>"
            f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>Tomorrow — watch</div>"
            + "".join(
                f"<div style='font-size:12px;color:#edf3f9;margin-top:2px'>"
                f"• <b>{w.get('label')}</b> "
                f"<span style='color:#cfd9e6'>{w.get('means')}</span></div>"
                for w in d["tomorrow_watch"][:5]) + "</div>")
    if d.get("tomorrow_risks"):
        out.append(
            f"<div style='margin-top:5px'>"
            f"<div style='font-size:10px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>Tomorrow — risks</div>"
            + "".join(f"<div style='font-size:12px;color:#ffcc66;"
                      f"margin-top:2px'>• {r}</div>"
                      for r in d["tomorrow_risks"][:5]) + "</div>")
    if d.get("outlook"):
        out.append(f"<div style='margin-top:7px;padding-top:6px;"
                   f"border-top:1px solid #1e2836;font-size:12.5px;"
                   f"color:#dfe7f0'>{d['outlook']}</div>")
    out.append("</div>")
    return "".join(out)
