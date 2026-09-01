"""MIOS V5 — Stage 36/37 narrative.

Turns the pipeline + final read into plain language:
  • build_market_story()  — a short paragraph (Stage 36)
  • build_briefing()      — a one-page structured institutional summary (37)

Template-based (no LLM dependency) so it is deterministic, testable, and never
fabricates. **No BUY/SELL** — it describes bias, evidence, levels and where the
read fails.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .core import MarketState

_BIAS_WORD = {
    "STRONG_BULL": "strongly bullish", "BULL": "bullish",
    "NEUTRAL": "balanced", "SIDEWAYS": "range-bound",
    "BEAR": "bearish", "STRONG_BEAR": "strongly bearish", "NONE": "unclear",
}


def _phrase(state: MarketState, name: str, tmpl_bull, tmpl_bear, tmpl_neutral):
    r = state.get(name)
    if r is None or not r.ok:
        return None
    b = r.bias.value
    if b in ("STRONG_BULL", "BULL"):
        return tmpl_bull
    if b in ("STRONG_BEAR", "BEAR"):
        return tmpl_bear
    return tmpl_neutral


def build_market_story(state: MarketState, fr: Dict[str, Any]) -> str:
    """Compose a plain-language market story from the final read + engines."""
    # 🧲 Pin takes precedence — if price is pinned at a magnet strike there is
    # no directional edge, so the story leads with that instead of a bias.
    _pin = (state.raw.get("market_picture") or {}).get("oi_pin")
    if _pin:
        parts: List[str] = [
            f"Price is pinned at ₹{_pin[0]:.0f} — the heaviest call and put walls "
            f"sit on the same strike ({_pin[1]}). Expect range-bound chop around "
            f"this magnet with no directional edge until one side's wall clears."]
        of = _phrase(state, "stage14_orderflow",
                     "Order flow leans to buyers, but it is being absorbed at the pin.",
                     "Order flow leans to sellers, but it is being absorbed at the pin.",
                     "Order flow is balanced.")
        if of:
            parts.append(of)
        if fr.get("session_phase"):
            parts.append(f"Session: {fr['session_phase']}.")
        return " ".join(parts)

    # a live shock leads the story above everything else; otherwise institutional
    # preparation leads when the market is coiling ahead of something. Both are
    # observations of positioning / reaction — never a claim about the cause.
    lead: List[str] = []
    ev = state.get("stage28_event_detection")
    if ev is not None and ev.ok and (ev.data or {}).get("event_detected"):
        _ed = ev.data
        lead.append(
            f"🚨 Breaking event reaction ({_ed.get('event_score')}%, {_ed.get('shocks')} shocks): "
            f"{', '.join(_ed.get('signals', [])[:3])}. Market is reacting {_ed.get('reaction')} — "
            "cause unknown; wait for the dust to settle, don't chase the spike.")
    prep = state.get("stage24_preparation")
    if prep is not None and prep.ok and (prep.data or {}).get("level") == "HIGH":
        _pd = prep.data
        _cal = state.get("stage30_calendar")
        _cd = (_cal.data if _cal is not None and _cal.ok else {}) or {}
        if _cd.get("coiling_ahead_of_event"):
            _ne = _cd.get("next_event") or {}
            lead.append(
                f"⚠️ The market is coiling ({_pd.get('preparation_score')}% preparation) with "
                f"{_ne.get('name')} {_cd.get('when')} — this looks like positioning ahead of a "
                "known event; expect a large move on/after it.")
        else:
            lead.append(
                f"⚠️ Unusual positioning ({_pd.get('preparation_score')}% preparation, "
                f"{_pd.get('signals_fired')} signals): {', '.join(_pd.get('signals', [])[:3])}. "
                "The market looks like it is preparing for a significant event — cause "
                "unknown; trust flow over any headline and size down.")
    elif True:
        # no coiling, but flag a nearby scheduled catalyst on its own
        _cal = state.get("stage30_calendar")
        _cd = (_cal.data if _cal is not None and _cal.ok else {}) or {}
        _ne = _cd.get("next_event") or {}
        if _cd.get("has_event") and _ne.get("importance", 0) >= 4 and _ne.get("days_away", 9) <= 1:
            lead.append(f"📅 {_ne.get('name')} {_cd.get('when')} ({_cd.get('stars','')}) — a "
                        "scheduled catalyst is near; size down into it.")

    # explain layer — a possible CAUSE for the flagged preparation/shock (never
    # a signal). Only appended when a detector already led the story above.
    if lead:
        _ex = state.get("stage34_explain")
        _exd = (_ex.data if _ex is not None and _ex.ok else {}) or {}
        _causes = _exd.get("possible_causes") or []
        if _exd.get("explaining") and _causes:
            _top = " · ".join(c["cause"] for c in _causes[:2])
            lead.append(f"Possible cause ({_exd.get('confidence_label','?')} confidence): "
                        f"{_top}. The market moved first — this only explains why.")
        # impact — did it actually change structure?
        _im = state.get("stage33_event_impact")
        _imd = (_im.data if _im is not None and _im.ok else {}) or {}
        if _imd.get("measuring") and _imd.get("impact"):
            if _imd.get("signal_count", 0) == 0:
                lead.append("Actual market impact: LOW — structure barely moved; the event "
                            "did not change the tape.")
            else:
                lead.append(f"Actual market impact: {_imd['impact']} — "
                            f"{', '.join(_imd.get('signals', [])[:3])}.")

    bias_w = _BIAS_WORD.get(fr.get("preferred_bias", "NONE"), "unclear")
    parts: List[str] = lead + [f"Market reads {bias_w}"]

    # institutional intent
    intent = state.get("stage25_intent")
    if intent and intent.ok and intent.data.get("label"):
        parts[-1] += f" as {intent.data['label'].lower()}"
    parts[-1] += "."

    # dealer
    dealer = state.get("stage11_dealer")
    if dealer and dealer.ok:
        gx = (dealer.data or {}).get("gex") or {}
        if gx.get("signal"):
            sig = str(gx["signal"]).lower()
            damp = ("limiting downside volatility" if "pin" in sig or "range" in sig
                    else "so moves can accelerate" if "trend" in sig or "breakout" in sig
                    else "")
            parts.append(f"Dealers are in a {gx['signal']} gamma regime"
                         + (f", {damp}" if damp else "") + ".")

    # order flow
    of = _phrase(state, "stage14_orderflow",
                 "Order flow confirms buyer control.",
                 "Order flow shows seller control.",
                 "Order flow is mixed.")
    if of:
        parts.append(of)

    # reaction zone
    bz = fr.get("battle_zone")
    if bz:
        parts.append(
            f"Price is contesting {bz['type'].lower()} ₹{bz['price']:.0f}; "
            f"expected winner: {fr.get('expected_winner')}.")
        if fr.get("next_target") and fr.get("invalidation"):
            parts.append(f"Target ₹{fr['next_target']:.0f}, "
                         f"the read fails below/above ₹{fr['invalidation']:.0f}.")
    else:
        parts.append("Price is mid-range with no active battle zone.")

    # value migration — today's session value vs the last ~5 sessions' value
    vm = fr.get("value_migration")
    if isinstance(vm, dict) and vm.get("label"):
        if vm["label"] == "shifted lower":
            parts.append(
                f"Value has migrated lower — today's session POC ₹{vm.get('session_poc',0):.0f} "
                f"sits {vm.get('location','below weekly value')} (weekly POC ₹{vm.get('weekly_poc',0):.0f}); "
                f"read this as fresh selling, not a dip inside old value.")
        elif vm["label"] == "shifted higher":
            parts.append(
                f"Value has migrated higher — today's session POC ₹{vm.get('session_poc',0):.0f} "
                f"sits {vm.get('location','above weekly value')} (weekly POC ₹{vm.get('weekly_poc',0):.0f}); "
                f"read this as fresh buying, not an overshoot to fade.")
        else:
            parts.append(
                f"Value is balanced — today's session POC ₹{vm.get('session_poc',0):.0f} is holding "
                f"inside the weekly value area (weekly POC ₹{vm.get('weekly_poc',0):.0f}).")

    # value alignment across VPFR timeframes (short/medium/long)
    va = state.raw.get("value_alignment") if isinstance(state.raw.get("value_alignment"), dict) else None
    if va and va.get("overall"):
        ov = va["overall"]
        if ov == "aligned bullish":
            parts.append("All value timeframes (short/medium/long) sit below price — the "
                         "auction is accepting higher prices across the board.")
        elif ov == "aligned bearish":
            parts.append("All value timeframes (short/medium/long) sit above price — "
                         "institutional acceptance continues below prior value, strengthening "
                         "the bearish structure.")
        elif ov == "mixed rotation":
            parts.append("Value is mixed across timeframes — today's auction is accepting one "
                         "way while longer-term value still sits the other side; the market is "
                         "transitioning, not trending cleanly.")

    # sector rotation — slow institutional context (only when the engine votes)
    sec = state.get("stage18_sector")
    if sec is not None and sec.ok and (sec.data or {}).get("voting"):
        _lead = ", ".join((sec.data.get("leaders") or [])[:3]) or "leaders"
        if sec.bias.value in ("BULL", "STRONG_BULL"):
            parts.append(f"Money is rotating into {_lead}; {sec.data.get('breadth_pct')}% "
                         "sector breadth supports the bullish backdrop — a slow institutional "
                         "context, not an intraday trigger.")
        elif sec.bias.value in ("BEAR", "STRONG_BEAR"):
            parts.append(f"Defensive sectors ({_lead}) are leading while cyclicals lag — "
                         "institutions look defensive, though real-time order flow remains the "
                         "stronger signal.")

    # conflict + session caveat
    if fr.get("conflict_severity") == "HIGH":
        parts.append("Signals conflict sharply — treat with caution.")
    if fr.get("session_phase"):
        parts.append(f"Session: {fr['session_phase']}.")
    return " ".join(parts)


def _engine_line(state: MarketState, name: str) -> str:
    """One briefing line from an engine: its bias + headline evidence."""
    r = state.get(name)
    if r is None or not r.ok or not r.evidence:
        return ""
    return f"{r.evidence[0]}"


_BIAS_EMOJI = {
    "STRONG_BULL": "🟢", "BULL": "🟢", "NEUTRAL": "⚪", "SIDEWAYS": "⚪",
    "BEAR": "🔴", "STRONG_BEAR": "🔴", "NONE": "⚪",
}


def _energy(state: MarketState) -> str:
    of = state.get("stage14_orderflow")
    pr = state.get("stage31_probability")
    conf = of.confidence if of and of.ok else 0.0
    edge = abs((pr.data.get("breakout", 50) or 50) - 50) * 2 if pr and pr.ok else 0.0
    e = (conf + edge) / 2
    return "Strong" if e >= 55 else ("Moderate" if e >= 28 else "Weak")


def _day_type(fr: Dict[str, Any]) -> str:
    reg, sev = fr.get("regime"), fr.get("conflict_severity")
    if reg in ("UP", "DOWN") and sev in ("LOW", "MEDIUM"):
        return "Trend Day"
    if reg == "SIDEWAYS":
        return "Range Day"
    return "Mixed / Choppy Day"


def _dealer_gamma(state: MarketState) -> str:
    d = state.get("stage11_dealer")
    gx = (d.data.get("gex") if d and d.data else {}) or {}
    sig = str(gx.get("signal", "")).lower()
    if "pin" in sig or "range" in sig:
        return "Long Gamma (dealers dampen moves)"
    if "trend" in sig or "breakout" in sig:
        return "Short Gamma (dealers amplify moves)"
    return "Neutral gamma"


def _liquidity_line(mp: Dict[str, Any]) -> str:
    lp = mp.get("liq_pools") or {}
    above = [p for p in (lp.get("above") or []) if not p.get("touched")]
    below = [p for p in (lp.get("below") or []) if not p.get("touched")]
    parts = []
    if above:
        parts.append(f"Buy-side liquidity ₹{above[0]['price']:.0f} "
                     f"({above[0]['kind']}) above")
    if below:
        parts.append(f"Sell-side liquidity ₹{below[0]['price']:.0f} "
                     f"({below[0]['kind']}) below")
    return " · ".join(parts) if parts else "No untouched liquidity pools nearby"


def _sector_line(state: MarketState) -> str:
    sr = state.raw.get("sector_rotation")
    rows = sr if isinstance(sr, list) else (
        (sr.get("rows") or sr.get("sectors")) if isinstance(sr, dict) else None)
    if not rows:
        return ""
    try:
        leaders = []
        for r in rows:
            name = r.get("name") or r.get("sector") or r.get("Symbol")
            chg = r.get("change") or r.get("pct") or r.get("day_change") or 0
            if name is not None:
                leaders.append((str(name), float(chg or 0)))
        leaders.sort(key=lambda x: -x[1])
        top = [n for n, c in leaders[:2] if c > 0]
        return ("Leading: " + ", ".join(top)) if top else ""
    except Exception:
        return ""


def _risk_monitor(state: MarketState, fr: Dict[str, Any],
                  mp: Dict[str, Any]) -> List[str]:
    out = []
    # news risk
    nb = mp.get("news_bias") or {}
    _nn = abs(int(nb.get("net", 0) or 0))
    out.append(f"News Risk: {'High' if _nn >= 5 else ('Medium' if _nn >= 3 else 'Low')}")
    # volatility risk (gamma-blast / short gamma)
    f = state.get("stage31_probability")
    gb = (f.data.get("gamma_blast") if f and f.data else None)
    out.append(f"Volatility Risk: {'High' if gb == 'HIGH' else ('Medium' if gb == 'MEDIUM' else 'Low')}")
    # dealer flip risk — spot near the gamma flip
    d = state.get("stage11_dealer")
    gx = (d.data.get("gex") if d and d.data else {}) or {}
    flip = gx.get("flip")
    spot = state.raw.get("spot")
    if flip and spot:
        _dist = abs(float(spot) - float(flip))
        out.append(f"Dealer Flip Risk: {'High' if _dist <= 15 else ('Medium' if _dist <= 40 else 'Low')}")
    # liquidity trap risk — high signal conflict
    out.append(f"Liquidity Trap Risk: {'High' if fr.get('conflict_severity') == 'HIGH' else 'Low'}")
    return out


def _evidence_tally(state: MarketState, fr: Dict[str, Any]):
    """✅ bullish / ⚠️ caution / ❌ bearish list against the preferred bias."""
    from . import engines as _e  # noqa: F401 (keep import graph explicit)
    from .core import Bias
    pref = fr.get("preferred_bias", "NEUTRAL")
    pref_bull = pref in ("BULL", "STRONG_BULL")
    pref_bear = pref in ("BEAR", "STRONG_BEAR")
    items, nb, nc, nx = [], 0, 0, 0
    labels = {
        "stage05_regime": "Market Regime", "stage11_dealer": "Dealer Position",
        "stage12_options": "Options Positioning",
        "stage13_institutional": "Institutional Positioning",
        "stage14_orderflow": "Order Flow", "stage25_intent": "Institutional Intent",
        "stage19_global": "Global Markets", "stage21_news": "News Sentiment",
    }
    for name, label in labels.items():
        r = state.get(name)
        if r is None or not r.ok or r.bias == Bias.NONE:
            continue
        b = r.bias.value
        is_bull = b in ("BULL", "STRONG_BULL")
        is_bear = b in ("BEAR", "STRONG_BEAR")
        if (pref_bull and is_bull) or (pref_bear and is_bear):
            items.append(f"✅ {label}: {b.replace('_', ' ').title()}")
            nb += 1
        elif (pref_bull and is_bear) or (pref_bear and is_bull):
            items.append(f"❌ {label}: {b.replace('_', ' ').title()}")
            nx += 1
        else:
            items.append(f"⚠️ {label}: {b.replace('_', ' ').title()}")
            nc += 1
    # dealer gamma caveat
    _dg = _dealer_gamma(state)
    if "Short Gamma" in _dg:
        items.append("⚠️ Short-gamma: sharp two-way moves possible")
        nc += 1
    elif "Long Gamma" in _dg:
        items.append("⚠️ Long-gamma may cap momentum")
        nc += 1
    return items, nb, nc, nx


def build_briefing(state: MarketState, fr: Dict[str, Any]) -> str:
    """📊 MIOS Institutional Market Summary (Stage 37) — reads like a morning
    desk briefing, not an indicator dump: market state, institutional view,
    price map, battle zone, external influence, risk monitor, probable
    scenarios, AI story, evidence tally. No buy/sell."""
    mp = state.raw.get("market_picture") or {}
    mfd = state.raw.get("money_flow") or {}
    L: List[str] = []
    _bias = fr.get("preferred_bias", "NEUTRAL")
    _be = _BIAS_EMOJI.get(_bias, "⚪")

    L.append("📊 MIOS Institutional Market Summary")
    L.append("")

    # ── 🌍 Market State ──────────────────────────────────────────────
    _pin = mp.get("oi_pin")
    L.append("🌍 Market State")
    if _pin:
        L.append(f"• Current Bias: 🧲 PINNED at ₹{_pin[0]:.0f} — no directional edge")
        L.append(f"• Market Regime: Pin / Range Day ({_pin[1]})")
    else:
        L.append(f"• Current Bias: {_be} {_bias.replace('_', ' ').title()}")
        L.append(f"• Market Regime: {_day_type(fr)}"
                 + (f" ({fr['regime']})" if fr.get("regime") else ""))
    L.append(f"• Confidence: {fr.get('confidence_tempered', 0)}% "
             f"({fr.get('conflict_severity', '—')} conflict)")
    L.append(f"• Market Energy: {_energy(state)}")
    if fr.get("health_score") is not None:
        L.append(f"• System Health: {fr['health_score']:.0f}%")
    if fr.get("session_phase"):
        L.append(f"• Session: {fr['session_phase']}")
    L.append("")

    # ── 🏛 Institutional View ────────────────────────────────────────
    L.append("🏛 Institutional View")
    intent = state.get("stage25_intent")
    _intent_lbl = (intent.data.get("label") if intent and intent.data else None) or "—"
    of = state.get("stage14_orderflow")
    _of = "—"
    if of and of.ok:
        _of = ("Buyers in control" if of.bias.value in ("BULL", "STRONG_BULL")
               else "Sellers in control" if of.bias.value in ("BEAR", "STRONG_BEAR")
               else "Balanced")
    opt = state.get("stage12_options")
    _opt = opt.bias.value.replace("_", " ").title() if opt and opt.ok else "—"
    L.append(f"• Institutional Intent: {_intent_lbl}")
    L.append(f"• Dealer Position: {_dealer_gamma(state)}")
    L.append(f"• Options Bias: {_opt}")
    L.append(f"• Order Flow: {_of}")
    L.append(f"• Liquidity: {_liquidity_line(mp)}")
    _concl = ("Institutions supporting higher prices" if _bias in ("BULL", "STRONG_BULL")
              else "Institutions pressing lower" if _bias in ("BEAR", "STRONG_BEAR")
              else "Institutions balanced / no clear intent")
    if "Long Gamma" in _dealer_gamma(state):
        _concl += ", but long gamma may slow sharp moves"
    elif "Short Gamma" in _dealer_gamma(state):
        _concl += ", and short gamma can amplify the move"
    L.append(f"→ {_concl}.")
    L.append("")

    # ── 📍 Key Price Map ─────────────────────────────────────────────
    L.append("📍 Key Price Map")
    if _pin:
        L.append(f"• 🧲 PIN / Magnet: {_pin[0]:.0f} (price gravitates here)")
    if fr.get("strong_support"):
        L.append(f"• Strong Support: {fr['strong_support']:.0f} "
                 f"(str {fr.get('support_strength')}%)")
    _mfp = mp.get("fut_mfp") or {}
    _poc = mfd.get("poc_price") or _mfp.get("poc")
    _vah = mfd.get("value_area_high") or _mfp.get("vah")
    _val = mfd.get("value_area_low") or _mfp.get("val")
    if _val:
        L.append(f"• Demand/Value Low (VAL): {_val:.0f}")
    if mp.get("vwap"):
        L.append(f"• VWAP: {mp['vwap']:.0f}")
    if _poc:
        L.append(f"• POC: {_poc:.0f}")
    if _vah:
        L.append(f"• Supply/Value High (VAH): {_vah:.0f}")
    _vm = fr.get("value_migration")
    if isinstance(_vm, dict) and _vm.get("label"):
        L.append(f"• Value Migration: {_vm['label']} vs weekly "
                 f"(session POC {_vm.get('session_poc',0):.0f} / weekly POC "
                 f"{_vm.get('weekly_poc',0):.0f}, {_vm.get('location','')})")
    if fr.get("strong_resistance"):
        L.append(f"• Strong Resistance: {fr['strong_resistance']:.0f} "
                 f"(str {fr.get('resistance_strength')}%)")
    _lp = mp.get("liq_pools") or {}
    _tgt_pool = next((p for p in (_lp.get("above") if _bias in ("BULL", "STRONG_BULL")
                                  else _lp.get("below")) or [] if not p.get("touched")), None)
    if _tgt_pool:
        L.append(f"• Liquidity Target: {_tgt_pool['price']:.0f} ({_tgt_pool['kind']})")
    _pd = fr.get("prev_day") or {}
    if _pd.get("prev_high"):
        L.append(f"• PDH {_pd['prev_high']:.0f} · PDL {_pd.get('prev_low', 0):.0f}")
    L.append("")

    # ── ⚔️ Current Battle Zone ───────────────────────────────────────
    bz = fr.get("battle_zone")
    L.append("⚔️ Current Battle Zone")
    if bz:
        _probs = fr.get("probabilities") or {}
        L.append(f"• Location: Near {bz['type'].title()} ({bz['price']:.0f})")
        L.append(f"• Expected Winner: {fr.get('expected_winner', '—')}")
        for k in ("bounce", "rejection", "breakout", "breakdown"):
            if k in _probs:
                L.append(f"• {k.title()} Probability: {_probs[k]}%")
        if fr.get("next_target") and fr.get("invalidation"):
            L.append(f"• Target {fr['next_target']:.0f} · Invalidation {fr['invalidation']:.0f}")
    else:
        L.append("• Location: Mid-range — no active battle zone")
    L.append("")

    # ── 🌍 External Influence ────────────────────────────────────────
    L.append("🌍 External Influence")
    gb = mp.get("global_bias") or {}
    if gb:
        L.append(f"• 🌏 Global Markets: {gb.get('label', '—')} ({gb.get('score', 0):+.1f})")
    _sec = _sector_line(state)
    if _sec:
        L.append(f"• 📊 Sector Rotation: {_sec}")
    cb = mp.get("commodity_bias") or {}
    if cb:
        L.append(f"• 🛢 Commodity/Macro: {cb.get('regime', '—')}")
    nb = mp.get("news_bias") or {}
    if nb:
        L.append(f"• 📰 News: {nb.get('em', '')} {nb.get('label', '—')} "
                 f"({nb.get('n', 0)} headlines)")
    L.append("")

    # ── ⚠️ Risk Monitor ──────────────────────────────────────────────
    L.append("⚠️ Risk Monitor")
    for r in _risk_monitor(state, fr, mp):
        L.append(f"• {r}")
    L.append("")

    # ── 📈 Most Probable Scenarios ───────────────────────────────────
    L.append("📈 Most Probable Scenarios")
    _pu = int(mp.get("p_up", 0) or 0)
    _pd2 = int(mp.get("p_down", 0) or 0)
    _ps = int(mp.get("p_side", 0) or 0)
    _sup = fr.get("strong_support")
    _res = fr.get("strong_resistance")
    _tgt = fr.get("next_target")
    L.append(f"• Bull Case ({_pu}%): support holds → toward "
             f"{(_res or _tgt or 0):.0f}" if (_res or _tgt) else f"• Bull Case ({_pu}%)")
    L.append(f"• Bear Case ({_pd2}%): support breaks → toward "
             f"{(_sup - 40):.0f}" if _sup else f"• Bear Case ({_pd2}%)")
    L.append(f"• Range Case ({_ps}%): chops between "
             f"{(_sup or 0):.0f}–{(_res or 0):.0f}" if (_sup and _res)
             else f"• Range Case ({_ps}%)")
    L.append("")

    # ── 🧠 AI Market Story ───────────────────────────────────────────
    L.append("🧠 AI Market Story")
    L.append(build_market_story(state, fr))
    L.append("")

    # ── 🎯 Evidence Summary ──────────────────────────────────────────
    items, nb2, nc, nx = _evidence_tally(state, fr)
    L.append("🎯 Evidence Summary")
    for it in items:
        L.append(it)
    L.append(f"Overall Evidence: {nb2} Bullish | {nc} Caution | {nx} Bearish")
    L.append("")
    L.append("— MIOS is decision-support only; no buy/sell. You decide.")
    return "\n".join(L)
