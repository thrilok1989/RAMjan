"""MIOS V5 — the Zone Intelligence card (Phase 1 · Step 10).

One S/R level, everything you need to judge it, in a single glance:

    Resistance ₹23,700   ★★★★★   🟢 Building   Health 84%
    ⚔️ WAR ZONE   Buyer 41% · Seller 59% → Sellers
    Break 39% · Reject 61% · Trap 46%
    HTF  1H ✓  4H ✓  Daily ✓
    AI   Dealer Wall · Heavy Calls · Distribution
    ❌ invalidation 23,715

Pure view over the card produced by `mios_v5.zone_intel.build_zone_card` —
computes nothing, decides nothing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_LIFE_COLOR = {
    "created": "#cfd9e6", "untested": "#cfd9e6", "holding": "#4da6ff",
    "building": "#00ff88", "under-attack": "#ffcc33", "breaking": "#ff9500",
    "broken": "#ff4444", "retest": "#ffcc33", "recovered": "#00ff88",
    "retired": "#666666",
}

_HEALTH_EMOJI = {"building": "🟢", "fading": "🔴", "neutral": "⚪"}
_CAT_LABEL = {"spot": "Spot", "options": "Options", "dealers": "Dealers",
              "institutions": "Instns", "liquidity": "Liquidity"}


def _health_color(pct: float) -> str:
    return "#00ff88" if pct >= 70 else "#ffcc33" if pct >= 45 else "#ff4444"


def zone_card_html(card: Optional[Dict[str, Any]]) -> str:
    """Render one Zone Intelligence card to HTML (no Streamlit dependency, so
    the same markup can be reused by any panel)."""
    if not card:
        return ""
    side = card.get("side", "")
    is_sup = side == "SUPPORT"
    accent = "#00ff88" if is_sup else "#ff4444"
    emoji = "🟢" if is_sup else "🔴"
    life = card.get("lifecycle", "")
    life_col = _LIFE_COLOR.get(life, "#cfd9e6")
    hl = card.get("health") or {}
    hpct = float(hl.get("pct") or 0)
    hcol = _health_color(hpct)
    org = card.get("origin") or {}
    stg = card.get("strength") or {}
    btl = card.get("battle") or {}
    acc = card.get("acceptance") or {}
    probs = card.get("probabilities") or {}
    htf = card.get("htf") or {}
    exp = card.get("explain") or {}

    # ── header: level · origin ★ · lifecycle · health ──
    out = [
        f"<div style='background:#0b0f16;border:2px solid {accent};border-radius:12px;"
        f"padding:10px 12px;margin-bottom:8px;'>",
        f"<div style='font-size:19px;font-weight:900;color:{accent};line-height:1.15;'>"
        f"{emoji} {side.title()} ₹{card.get('price', 0):,.0f}</div>",
        f"<div style='font-size:13px;margin-top:2px;color:#ffffff;font-weight:700;'>"
        f"<span title='origin' style='color:#ffd000;'>{org.get('stars', '')}</span>"
        f" &nbsp;<span style='color:{life_col};'>{card.get('lifecycle_label', '')}</span>"
        f" &nbsp;<span style='color:{hcol};'>Health {hpct:.0f}%</span></div>",
    ]

    # ── strength + touches ──
    out.append(
        f"<div style='font-size:13px;margin-top:4px;color:#edf3f9;font-weight:600;'>"
        f"💪 Strength <b style='color:#fff;'>{stg.get('score', 0)}%</b> "
        f"<span style='color:#ffd000;'>{stg.get('stars', '')}</span> "
        f"<span style='color:#cfd9e6;'>· {stg.get('touches', 0)} touches "
        f"({stg.get('touch_note', '')})</span></div>")

    # ── the four/five defender groups ──
    cats = hl.get("categories") or {}
    if cats:
        _bits = " · ".join(
            f"{_CAT_LABEL.get(k, k)} {_HEALTH_EMOJI.get(v, '⚪')}"
            for k, v in cats.items())
        _warn = (" <span style='color:#ffcc33;font-weight:800;'>⚠️ conflicted</span>"
                 if hl.get("conflicted") else "")
        out.append(f"<div style='font-size:12.5px;margin-top:3px;color:#edf3f9;'>"
                   f"🩺 {_bits}{_warn}</div>")

    # ── battle ──
    if btl:
        _bcol = ("#00ff88" if btl.get("winner") == "Buyers"
                 else "#ff4444" if btl.get("winner") == "Sellers" else "#ffcc33")
        out.append(
            f"<div style='font-size:13.5px;margin-top:5px;font-weight:800;'>"
            f"<span style='color:{_bcol};'>{btl.get('label', '')}</span> "
            f"<span style='color:#00ff88;'>Buyer {btl.get('buyer', 0)}%</span> · "
            f"<span style='color:#ff4444;'>Seller {btl.get('seller', 0)}%</span> "
            f"<span style='color:#edf3f9;'>→ {btl.get('winner', '')} "
            f"({btl.get('confidence', 0)}%)</span></div>")

    # ── acceptance / trap ──
    if acc.get("label") and acc.get("label") != "—":
        _acol = {"trap": "#ffcc33", "accepted": "#ff9500",
                 "rejected": "#00ff88", "defended": "#4da6ff"}.get(acc.get("state"), "#edf3f9")
        out.append(f"<div style='font-size:13px;margin-top:3px;font-weight:700;"
                   f"color:{_acol};'>{acc['label']}</div>")

    # ── probabilities ──
    if probs:
        out.append(
            f"<div style='font-size:13px;margin-top:4px;color:#ffffff;font-weight:700;'>"
            f"<span style='color:#ff4444;'>Break {probs.get('break', 0)}%</span> · "
            f"<span style='color:#00ff88;'>Reject {probs.get('rejection', 0)}%</span> · "
            f"<span style='color:#ffcc33;'>Trap {probs.get('trap', 0)}%</span></div>")

    # ── higher-timeframe confluence ──
    if htf.get("count"):
        out.append(
            f"<div style='font-size:12.5px;margin-top:3px;color:#edf3f9;'>"
            f"🕐 HTF <span style='color:#ffd000;'>{htf.get('stars', '')}</span> "
            + " ".join(f"{m} ✓" for m in htf.get("matches", [])[:4]) + "</div>")

    # ── the short AI explanation ──
    if exp.get("why"):
        out.append(
            f"<div style='font-size:12.5px;margin-top:4px;color:#dfe7f0;'>"
            f"🤖 " + " · ".join(exp["why"][:4]) + "</div>")
    if exp.get("expect"):
        out.append(f"<div style='font-size:12.5px;margin-top:2px;color:#edf3f9;"
                   f"font-weight:700;'>➡️ {exp['expect']}</div>")
    if card.get("invalidation"):
        out.append(f"<div style='font-size:12.5px;margin-top:2px;color:#cfd9e6;'>"
                   f"❌ invalidation ₹{card['invalidation']:,.0f}</div>")

    out.append("</div>")
    return "".join(out)


def render_zone_card(card: Optional[Dict[str, Any]]) -> None:
    """Streamlit wrapper — draws the card if there is one."""
    if not card:
        return
    import streamlit as st
    st.markdown(zone_card_html(card), unsafe_allow_html=True)


def zone_card_line(card: Optional[Dict[str, Any]]) -> str:
    """The COMPACT one-liner for the Trade Card — the same intelligence
    distilled to what fits a phone: level · ★ · lifecycle · health · winner ·
    break/reject/trap. Returns '' when there's no card."""
    if not card:
        return ""
    side = card.get("side", "")
    is_sup = side == "SUPPORT"
    accent = "#00ff88" if is_sup else "#ff4444"
    emoji = "🟢" if is_sup else "🔴"
    hl = card.get("health") or {}
    hpct = float(hl.get("pct") or 0)
    btl = card.get("battle") or {}
    probs = card.get("probabilities") or {}
    life_col = _LIFE_COLOR.get(card.get("lifecycle", ""), "#cfd9e6")
    _bcol = ("#00ff88" if btl.get("winner") == "Buyers"
             else "#ff4444" if btl.get("winner") == "Sellers" else "#ffcc33")
    _trap = (f" · <span style='color:#ffcc33;'>trap {probs.get('trap', 0)}%</span>"
             if probs.get("trap", 0) >= 55 else "")
    _conflict = (" <span style='color:#ffcc33;'>⚠️</span>" if hl.get("conflicted") else "")
    return (
        f"<div style='font-size:14px;margin-top:3px;font-weight:700;'>"
        f"<span style='color:{accent};'>{emoji} {side.title()} "
        f"₹{card.get('price', 0):,.0f}</span> "
        f"<span style='color:#ffd000;'>{(card.get('origin') or {}).get('stars', '')}</span> "
        f"<span style='color:{life_col};'>{card.get('lifecycle_label', '')}</span> "
        f"<span style='color:{_health_color(hpct)};'>{hpct:.0f}%</span>{_conflict} "
        f"<span style='color:{_bcol};'>{btl.get('winner', '')} "
        f"{max(btl.get('buyer', 0), btl.get('seller', 0))}%</span> "
        f"<span style='color:#edf3f9;'>brk {probs.get('break', 0)}% · "
        f"rej {probs.get('rejection', 0)}%</span>{_trap}</div>")


# ── Stage 42 — the reaction block that sits under the zone card ──────────
_REACT_COLOR = {
    "CONFIRMED_BREAKOUT": "#00ff88", "CONFIRMED_BREAKDOWN": "#ff4444",
    "ACCEPTANCE": "#00ff88", "BULL_TRAP": "#ff4444", "BEAR_TRAP": "#00ff88",
    "FAILED_BREAKOUT": "#ff9500", "FAILED_BREAKDOWN": "#ff9500",
    "SWEEP_BUY": "#ffcc33", "SWEEP_SELL": "#ffcc33",
    "REJECTION": "#4da6ff", "ABSORPTION": "#a78bfa",
    "BREAK": "#ffcc33", "WATCHING": "#cfd9e6", "TOUCH": "#cfd9e6",
}


def reaction_block_html(reaction: Optional[Dict[str, Any]]) -> str:
    """The Acceptance/Rejection/Trap verdict for the level price is contesting:
    what happened after price got there, how sure, and what it implies."""
    if not reaction or reaction.get("state") in (None, "IDLE"):
        return ""
    st = reaction["state"]
    col = _REACT_COLOR.get(st, "#edf3f9")
    conf = int(reaction.get("confidence") or 0)
    rows = [
        f"<div style='background:#0b0f16;border:2px solid {col};border-radius:10px;"
        f"padding:9px 12px;margin:6px 0;'>",
        f"<div style='font-size:11px;letter-spacing:.10em;color:#cfd9e6;"
        f"text-transform:uppercase'>Status @ {str(reaction.get('side','')).title()}</div>",
        f"<div style='font-size:18px;font-weight:900;color:{col};line-height:1.2'>"
        f"{reaction.get('label', st)}</div>",
        f"<div style='display:flex;align-items:center;gap:8px;margin-top:4px'>"
        f"<span style='font-size:12px;color:#cfd9e6'>Confidence</span>"
        f"<div style='flex:1;height:8px;background:#1e2836;border-radius:4px;"
        f"overflow:hidden'><div style='width:{max(2, conf)}%;height:100%;"
        f"background:{col}'></div></div>"
        f"<span style='font-size:14px;font-weight:800;color:{col}'>{conf}%</span></div>",
    ]
    if reaction.get("winner"):
        rows.append(f"<div style='font-size:13px;margin-top:3px;color:#edf3f9'>"
                    f"Winner: <b style='color:{col}'>{reaction['winner']}</b></div>")
    for why in (reaction.get("reasons") or [])[:4]:
        rows.append(f"<div style='font-size:12px;color:#dfe7f0;margin-top:1px'>"
                    f"• {why}</div>")
    if reaction.get("action"):
        rows.append(
            f"<div style='margin-top:6px;padding:7px 10px;background:{col}22;"
            f"border:1px solid {col};border-radius:7px;text-align:center;"
            f"font-size:16px;font-weight:900;color:{col}'>"
            f"{reaction['action']}</div>")
    rows.append("</div>")
    return "".join(rows)


def render_reaction_block(reaction: Optional[Dict[str, Any]]) -> None:
    html = reaction_block_html(reaction)
    if not html:
        return
    import streamlit as st
    st.markdown(html, unsafe_allow_html=True)


def reaction_line(reaction: Optional[Dict[str, Any]]) -> str:
    """Compact one-liner for the Trade Card."""
    if not reaction or reaction.get("state") in (None, "IDLE"):
        return ""
    st = reaction["state"]
    col = _REACT_COLOR.get(st, "#edf3f9")
    act = (f" <span style='color:#fff;background:{col};padding:1px 7px;"
           f"border-radius:5px;font-weight:900'>{reaction['action']}</span>"
           if reaction.get("action") else "")
    return (f"<div style='text-align:center;font-size:15px;margin-top:5px;"
            f"font-weight:800;color:{col}'>{reaction.get('label', st)} "
            f"{int(reaction.get('confidence') or 0)}%{act}</div>")


def zone_micro(card: Optional[Dict[str, Any]]) -> str:
    """The S/R level as PLAIN TEXT for the sticky app header.

    A third form, and the shortest: `zone_card_line` already trims the full
    card to one row, and the header has room for a chip. Stars, lifecycle and
    the battle percentage go — the price and the odds are what a glance off a
    frozen strip is for.

    Plain text, not markup: the header owns its own styling, this owns the
    wording. Returns `""` when there is no card.

    ⚠️ Both odds travel. `brk 44 · rej 56` are complements, and printing one is
    the edit that lets a reader supply the other from a wrong prior.
    """
    if not card:
        return ""
    side = str(card.get("side") or "")
    price = card.get("price")
    try:
        px = f"{float(price):,.0f}"
    except (TypeError, ValueError):
        return ""
    probs = card.get("probabilities") or {}
    brk, rej = probs.get("break"), probs.get("rejection")
    emoji = "🛡" if side == "SUPPORT" else "🧱"
    odds = ""
    if brk is not None and rej is not None:
        odds = f" brk {brk:.0f} · rej {rej:.0f}"
    return f"{emoji} {px}{odds}"
