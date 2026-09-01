"""MIOS V5 — Stage 41 Human Decision Dashboard.

The one-page decision-support interface. Consumes the pipeline via
build_final_read() and renders every section from the spec — Market Overview,
Institutional View, Price Map, Reaction Zone, External Factors, AI Summary,
My Analysis, System Monitor. **No BUY/SELL** — bias + evidence + levels +
invalidation; the trader decides.
"""

from __future__ import annotations

from typing import Any, Dict

from ..final_read import build_final_read
from ..layer_scores import build_layer_scores
from ._bright import bright_caption as _bc
from .health_panel import render_health_panel
from .my_analysis import render_my_analysis
from .story_panel import render_story_panel
from .structure_panel import render_structure_panel
from .family_panel import render_family_panel
from .htf_panel import render_htf_panel
from .absorption_panel import render_absorption_panel
from .decision_panel import render_decision_panel
from .energy_panel import render_energy_panel
from .memory_panel import render_memory_panel
from .state_panel import render_state_panel
from .ltp_panel import render_ltp_panel
from .transition_panel import render_transition_panel
from .validity_panel import render_validity_panel
from .zone_card import render_reaction_block, render_zone_card
from .theme import grade_tone

_LEAN_COLOR = {"BULL": "#17c98b", "BEAR": "#f0455a",
               "NEUTRAL": "#ffffff", "N/A": "#555"}

_BIAS_COLOR = {
    "STRONG_BULL": "#00ff88", "BULL": "#17c98b", "NEUTRAL": "#ffffff",
    "SIDEWAYS": "#f0b429", "BEAR": "#f0455a", "STRONG_BEAR": "#ff4444",
    "NONE": "#ffffff", "MISSING": "#555",
}


def _chip(label: str, sec: Dict[str, Any]) -> str:
    col = _BIAS_COLOR.get(sec.get("bias", "NONE"), "#ffffff")
    return (f"<div style='background:#0d1117;border:1px solid #1e2836;"
            f"border-radius:9px;padding:7px 11px'>"
            f"<div style='font-size:9px;letter-spacing:.10em;color:#ffffff;"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-weight:800;font-size:14px;color:{col}'>"
            f"{sec.get('bias', '—')}</div>"
            f"<div style='font-family:monospace;font-size:10px;color:#ffffff'>"
            f"{sec.get('confidence', 0)}%</div></div>")


def render_dashboard(state=None, db=None, run_backfill=None) -> None:
    import streamlit as st

    st.markdown("## 🧭 MIOS V5 — Analysis & Audit")
    _bc("🗺️ **Your decision cockpit is the Market Picture** (top of the app) — "
               "Entry Gate, Position Guardian, Trade Quality and data-integrity live "
               "there. **This page is the deep layer**: *why* the read looks the way it "
               "does, engine detail, learning logs and validation. **No buy/sell** — "
               "bias, evidence, levels and invalidation; the final decision is yours.")

    if state is None or not getattr(state, "results", None):
        st.info("MIOS pipeline warming up — first pass pending.")
        return

    fr = build_final_read(state)
    col = _BIAS_COLOR.get(fr["preferred_bias"], "#ffffff")

    # ── Day-frame badge (Stage 4 Market Context) — expiry / gap / pin ──
    # Distinctive frames get a bright badge so it's unmistakable that MIOS
    # is reading the day in the right light (esp. expiry days).
    _day_badge = ""
    _dt = fr.get("day_type")
    if _dt:
        _exp = fr.get("is_expiry")
        _dte = fr.get("dte")
        # per-state: (emoji, accent colour, one-line meaning)
        _DAY_STYLE = {
            "EXPIRY · COILED SPRING": ("⚡", "#ff2d55",
                "quiet but LOADED — short gamma at the pin; a break RELEASES violently, don't fade"),
            "EXPIRY · GAMMA UNWIND": ("🚀", "#ff2d55",
                "trend underway — dealer hedging FEEDS the move; trade WITH it, never fade"),
            "EXPIRY · PIN BREAK": ("⚠️", "#ffcc33",
                "price left the pin under long gamma — genuine breakout OR snap back? wait for confirmation"),
            "EXPIRY · PIN": ("🧲", "#4da6ff",
                "long gamma at the pin — dealers damp it; chop, failed breakouts, mean-reversion"),
            "EXPIRY · VOLATILE": ("🌀", "#ffcc33",
                "no clean pin — sharp gamma/charm swings, wider stops"),
            "EXPIRY · PIN (gamma pending)": ("⏳", "#ffcc33",
                "pinned but GEX still loading — treat as unstable until gamma confirms"),
            "COILED SPRING": ("⚡", "#ffcc33",
                "short gamma at the pin — loaded, not safe; break can expand fast"),
            "PRE-EXPIRY": ("📆", "#ffcc33", "expiry tomorrow — theta accelerating"),
            "GAP-UP": ("⬆️", "#ffcc33", "gap open — watch fill vs gap-and-go"),
            "GAP-DOWN": ("⬇️", "#ffcc33", "gap open — watch fill vs gap-and-go"),
            "PIN / RANGE": ("🧲", "#4da6ff", "pinned, long/neutral gamma — range day"),
            "TREND": ("📈", "#4da6ff", "trend frame — directional reads carry more weight"),
            "NORMAL / RANGE": ("•", "#4da6ff", "ordinary session"),
        }
        _emj, _dbg_col, _note = _DAY_STYLE.get(_dt, ("📅", "#4da6ff", ""))
        _dte_txt = (f" · DTE {_dte}" if isinstance(_dte, int) else "")

        # Energy Meter — quiet-because-damped vs quiet-because-loaded
        _sec = state.get("stage04_context")
        _cd = (_sec.data if _sec is not None and _sec.ok and _sec.data else {}) or {}
        _energy = _cd.get("energy")
        _meter = ""
        if isinstance(_energy, int):
            _comp = _cd.get("compression", 0)
            _brk = _cd.get("breakout_risk", 0)

            def _bar(lbl, val):
                _bc = ("#ff2d55" if val >= 75 else
                       "#ffcc33" if val >= 45 else "#4da6ff")
                return (f"<div style='display:flex;align-items:center;gap:6px;margin-top:3px'>"
                        f"<span style='width:96px;color:#aab6c6;font-size:10px'>{lbl}</span>"
                        f"<div style='flex:1;height:7px;background:#1e2836;border-radius:4px;"
                        f"overflow:hidden'><div style='width:{val}%;height:100%;background:{_bc}'>"
                        f"</div></div>"
                        f"<span style='width:34px;text-align:right;font-family:monospace;"
                        f"font-size:10px;color:{_bc}'>{val}%</span></div>")
            _meter = (_bar("⚡ Energy", _energy) + _bar("🪤 Compression", _comp)
                      + _bar("💥 Breakout risk", _brk))

        _day_badge = (
            f"<div style='margin-bottom:8px;padding:9px 14px;background:#12161d;"
            f"border-left:4px solid {_dbg_col};border-radius:8px;'>"
            f"<span style='font-size:15px;font-weight:800;color:{_dbg_col};'>"
            f"{_emj} {_dt}</span>"
            f"<span style='color:#ffffff;font-size:12px;'>{_dte_txt}"
            + (f"  —  {_note}" if _note else "") + "</span>"
            + _meter
            + "</div>")
    if _day_badge:
        st.markdown(_day_badge, unsafe_allow_html=True)

    # ── Market Overview headline ─────────────────────────────────────
    st.markdown(
        f"<div style='background:#0c1a15;border:2px solid {col};border-radius:12px;"
        f"padding:12px 16px;margin-bottom:8px'>"
        f"<span style='font-size:22px;font-weight:800;color:{col}'>"
        f"{fr['preferred_bias'].replace('_', ' ')}</span>"
        f"<span style='color:#ffffff;font-size:13px'> · confidence "
        f"<b style='color:#e6edf3'>{fr['confidence_tempered']}%</b>"
        f" · {fr['conflict_severity']} conflict"
        + (f" · regime {fr['regime']}" if fr.get("regime") else "")
        + (f" · {fr['session_phase']}" if fr.get("session_phase") else "")
        + "</span></div>",
        unsafe_allow_html=True)

    # ── Institutional View chips ─────────────────────────────────────
    st.markdown("**🏛 Institutional View**")
    secs = fr["sections"]
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:8px'>"
        + _chip("Dealer", secs["dealer"]) + _chip("Intent", secs["intent"])
        + _chip("Order Flow", secs["orderflow"]) + _chip("Options", secs["options"])
        + _chip("Regime", secs["regime"]) + "</div>",
        unsafe_allow_html=True)

    # ── Liquidity + Environment + Patterns chips (Stages 17/22/23/26) ──
    st.markdown("**💧 Liquidity · 🌡 Environment · 🔀 Patterns**")
    st.markdown(
        "<div style='display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px'>"
        + _chip("Liquidity", secs.get("liquidity", {}))
        + _chip("VIX", secs.get("vix", {}))
        + _chip("FII/DII", secs.get("flows", {}))
        + _chip("Patterns", secs.get("patterns", {})) + "</div>",
        unsafe_allow_html=True)

    # ── 🎯 7-Layer Scorecard + Trade-Quality grade (read-only synthesis) ─
    try:
        ls = build_layer_scores(state, health_score=fr.get("health_score"))
        _gc = grade_tone(ls["grade"], "#ffffff")
        _dc = _LEAN_COLOR.get(ls["direction"], "#ffffff")
        st.markdown(
            f"<div style='background:#0d1117;border:2px solid {_gc};border-radius:10px;"
            f"padding:10px 14px;margin-bottom:8px'>"
            f"<span style='font-size:20px;font-weight:900;color:{_gc}'>"
            f"🎯 Trade Quality {ls['grade']}</span>"
            f"<span style='color:{_dc};font-weight:800;font-size:14px'> · {ls['direction']}</span>"
            f"<span style='color:#ffffff;font-size:13px'> · composite "
            f"<b style='color:#e6edf3'>{ls['composite']}/100</b> · alignment "
            f"{ls['alignment']}% · {ls['available']}/{ls['total_layers']} layers</span>"
            f"<div style='color:#ffffff;font-size:10px;margin-top:2px'>"
            f"{ls['disclaimer']}</div></div>",
            unsafe_allow_html=True)
        # per-layer bars
        _rows = ""
        for ly in ls["layers"]:
            _lc = _LEAN_COLOR.get(ly["lean"], "#555")
            _sc = ly["score"]
            _bar = (f"<div style='flex:1;height:7px;background:#1e2836;border-radius:4px;"
                    f"overflow:hidden'><div style='width:{_sc}%;height:100%;"
                    f"background:{_lc}'></div></div>" if _sc is not None
                    else "<div style='flex:1;color:#555;font-size:10px'>N/A</div>")
            _val = (f"<span style='font-family:monospace;font-size:11px;color:{_lc};"
                    f"width:58px;text-align:right'>{_sc if _sc is not None else '—'}"
                    f" {ly['lean']}</span>")
            _rows += (f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0'>"
                      f"<span style='width:130px;font-size:11px;color:#ffffff'>{ly['label']}</span>"
                      f"{_bar}{_val}</div>")
        with st.expander("🎯 7-Layer Scorecard — how the read breaks down", expanded=False):
            st.markdown(_rows, unsafe_allow_html=True)
            _bc("Weights (priority): Structure 22 · Positioning 20 · Order Flow 18 · "
                       "Liquidity 15 · Options 12 · Environment 8 · Psychology 5. "
                       "Patterns/psychology are confirmation only.")
            for _n in ls["notes"]:
                _bc("• " + _n)
    except Exception as _e:  # never break the dashboard for a synthesis panel
        _bc(f"🎯 Scorecard unavailable: {type(_e).__name__}")

    # ── 🎭 Market State (Stage 48) — the single personality, first, because
    # it frames everything below it.
    try:
        _ms = state.get("stage48_market_state")
        if _ms is not None and _ms.ok and _ms.data:
            render_state_panel(_ms.data)
    except Exception:
        pass

    # ── 🧠 Market Memory (Stage 54) — how long, and how committed
    try:
        _mm = state.get("stage54_memory")
        if _mm is not None and _mm.ok and _mm.data:
            render_memory_panel(_mm.data)
    except Exception:
        pass

    # ── ⚡ Market Energy (Stage 37) — is anything actually coming?
    try:
        _en = state.get("stage37_energy")
        if _en is not None and _en.ok and _en.data:
            render_energy_panel(_en.data)
    except Exception:
        pass

    # ── 🏛 Institutional Participation (Stage 43) — WHY the flow looks
    # the way Stage 50 says it does.
    try:
        _ab = state.get("stage43_absorption")
        if _ab is not None and _ab.ok and _ab.data:
            render_absorption_panel(_ab.data)
    except Exception:
        pass

    # ── 📖 LTP Behaviour (Stage 50) — what price is trying to do now
    try:
        _lb = state.get("stage50_ltp_behaviour")
        if _lb is not None and _lb.ok and _lb.data:
            render_ltp_panel(_lb.data)
    except Exception:
        pass

    # ── 🔄 Bias Transition (Stage 47) — is the headline bias changing?
    try:
        _tr = state.get("stage47_transition")
        if _tr is not None and _tr.ok and _tr.data:
            render_transition_panel(_tr.data)
    except Exception:
        pass

    # ── 🧠 DECISION (Stage 52) — the hero panel, above everything, because
    # it is the only engine that issues an action.
    try:
        _dc = state.get("stage52_decision")
        if _dc is not None and _dc.ok and _dc.data:
            render_decision_panel(_dc.data)
    except Exception:
        pass

    # ── 🚦 Signal Validity (Stage 51) — the gatekeeper's verdict, first,
    # because it decides whether anything below is even tradeable.
    try:
        _vg = state.get("stage51_validity")
        if _vg is not None and _vg.ok and _vg.data:
            render_validity_panel(_vg.data)
    except Exception:
        pass

    # ── 🏛 Higher-Timeframe Structure (Stage 45) — the institutional big
    # picture: is today's move inside or against the larger structure?
    try:
        _htf = state.get("stage45_htf_vpfr")
        if _htf is not None and _htf.ok and _htf.data:
            render_htf_panel(_htf.data)
    except Exception:
        pass

    # ── 🧠 Evidence Families (Stage 53) — 7 de-duplicated families instead
    # of a 34-engine dump. Runs alongside Stage 27 while it's being validated.
    try:
        _ev = state.get("stage53_evidence")
        if _ev is not None and _ev.ok and _ev.data:
            render_family_panel(_ev.data)
            _fa = fr.get("families_agree")
            if _fa is False:
                _bc("⚖️ Families disagree with the Stage-27 read — logged for "
                    "comparison; Stage 27 still drives the decision.")
    except Exception:
        pass

    # ── Reaction Zone ⭐ + Price Map ─────────────────────────────────
    bz = fr.get("battle_zone")
    if bz:
        probs = fr.get("probabilities", {})
        _p = " · ".join(f"{k} {v}%" for k, v in probs.items())
        st.markdown(
            f"<div style='background:#0d1117;border:2px solid {col};border-radius:10px;"
            f"padding:10px 14px;margin-bottom:8px'>"
            f"<b style='color:{col};font-size:15px'>⚔️ {bz['type']} ₹{bz['price']:.0f} "
            f"→ {fr.get('expected_winner')}</b>"
            f"<div style='font-family:monospace;font-size:12px;color:#ffffff'>{_p}</div>"
            + (f"<div style='font-size:12px;color:#ffffff'>🎯 target "
               f"₹{fr['next_target']:.0f} · ❌ invalidation ₹{fr['invalidation']:.0f}</div>"
               if fr.get("next_target") and fr.get("invalidation") else "")
            + "</div>", unsafe_allow_html=True)
    else:
        _bc("⚔️ Reaction Zone: spot mid-range — no active battle.")

    # ── 🧠 Zone Intelligence — the full S/R card (Phase 1): origin, strength,
    # lifecycle, 5-group health, the battle, acceptance/trap, probabilities,
    # higher-timeframe confluence and the short explanation. Falls back to the
    # thin strength line while the enriched object is still warming up.
    _rsr = {}
    try:
        _rsr = st.session_state.get("_reaction_sr") or {}
    except Exception:
        _rsr = {}
    _cards = [(_s, (_rsr.get(_s) or {}).get("intel"))
              for _s in ("support", "resistance")]
    if any(c for _, c in _cards):
        zcols = st.columns(2)
        for _i, (_side, _card) in enumerate(_cards):
            with zcols[_i]:
                if _card:
                    render_zone_card(_card)
                    # ⭐ Stage 42 — what actually happened when price got here
                    try:
                        _ac = state.get("stage42_acceptance")
                        if _ac is not None and _ac.ok and _ac.data:
                            render_reaction_block((_ac.data or {}).get(_side))
                    except Exception:
                        pass
                else:
                    _bc(f"{'🟢 Support' if _side == 'support' else '🔴 Resistance'}: "
                        "warming up…")
    else:
        cols = st.columns(2)
        with cols[0]:
            if fr.get("strong_support"):
                _bc(f"🟢 Support ₹{fr['strong_support']:.0f} "
                           f"(strength {fr.get('support_strength')}%)")
        with cols[1]:
            if fr.get("strong_resistance"):
                _bc(f"🔴 Resistance ₹{fr['strong_resistance']:.0f} "
                           f"(strength {fr.get('resistance_strength')}%)")
    _pd = fr.get("prev_day") or {}
    if _pd.get("prev_high") and _pd.get("prev_low"):
        _bc(f"📅 Prev day: PDH ₹{_pd['prev_high']:.0f} · "
                   f"PDL ₹{_pd['prev_low']:.0f}"
                   + (f" · close ₹{_pd['prev_close']:.0f}"
                      if _pd.get("prev_close") else ""))

    # ── AI Market Story (Stage 36) ───────────────────────────────────
    story = state.get("stage36_story")
    if story and story.data.get("story"):
        st.markdown(
            f"<div style='background:#0d1117;border-left:3px solid {col};"
            f"padding:8px 12px;margin-bottom:8px;font-size:13px;color:#ffffff'>"
            f"📖 {story.data['story']}</div>", unsafe_allow_html=True)
    # ── One-page institutional briefing (Stage 37) ───────────────────
    if story and story.data.get("briefing"):
        with st.expander("📋 One-Page Institutional Briefing", expanded=False):
            st.text(story.data["briefing"])

    # ── MIOS accuracy (Stage 40 learning) ────────────────────────────
    learn = state.get("stage40_learning")
    if learn and learn.data.get("accuracy"):
        acc = learn.data["accuracy"]
        if acc.get("n", 0) >= 5:
            _bc(f"🎯 MIOS self-accuracy: **{acc['pct']}%** over {acc['n']} "
                       f"graded reads"
                       + (f" · high-conf {acc['hi_conf_pct']}% ({acc['hi_conf_n']})"
                          if acc.get("hi_conf_n", 0) >= 5 else ""))
        else:
            _bc(f"🎯 Learning: {acc.get('n', 0)} graded reads "
                       "(need ≥5 for accuracy — run sql/011_bias_predictions.sql)")

    # ── 📊 Validation Dashboard (evaluates the SYSTEM, not the market) ──────
    if db is not None:
        try:
            from ..validation import build_validation_report
            from ..layer_learning import build_shadow_weights
            _vrows = (db.get_resolved_entry_gate_signals()
                      if hasattr(db, "get_resolved_entry_gate_signals") else [])
            _shadow = (build_shadow_weights(db.get_layer_outcomes())
                       if hasattr(db, "get_layer_outcomes") else None)
            vr = build_validation_report(_vrows, _shadow)
            _h = vr["headline"]
            with st.expander(f"📊 Validation Dashboard — L{vr['level']} · "
                             f"{vr['n']} closed trades", expanded=False):
                _bc(vr["disclaimer"])
                for nt in vr["notes"]:
                    _bc("• " + nt)
                if _h:
                    st.markdown(
                        f"**Win-rate {_h['win_rate']}%** · expectancy "
                        f"{('%+.2fR' % _h['avg_R']) if _h.get('avg_R') is not None else '—'} "
                        f"· avg {_h['avg_pts']:+} pts · n={_h['n']}")

                def _wr_rows(title, items, gk):
                    if not items:
                        return
                    st.markdown(f"**{title}**")
                    for it in items:
                        if it.get("win_rate") is None or it.get("n", 0) == 0:
                            continue
                        _bc(f"• {it.get(gk)}: {it['win_rate']}% "
                                   f"({it['n']}n"
                                   + (f", {it['avg_R']:+.2f}R" if it.get('avg_R') is not None else "")
                                   + ")")

                # Level 2 breakdowns
                _wr_rows("By Trade-Quality grade", vr["by_grade"], "group")
                _wr_rows("By zone", vr["by_zone"], "group")
                _wr_rows("By regime", vr["by_regime"], "group")
                _wr_rows("By zone strength", vr["by_strength"], "bucket")
                _wr_rows("By R:R", vr["by_rr"], "bucket")

                _q = vr.get("quality_quadrant")
                if _q:
                    st.markdown("**Process vs outcome** (grade × result)")
                    _bc(f"• ✅ good process, bad result (keep taking): "
                               f"{_q['good_process_bad_result']}  ·  "
                               f"🎲 low-grade winners (luck, don't reinforce): "
                               f"{_q['lucky_wins']}")
                    _bc(f"• A/A+ wins {_q['hi_win']} · A/A+ losses {_q['hi_loss']} "
                               f"· B/C wins {_q['lo_win']} · B/C losses {_q['lo_loss']}")

                # always-on system health
                if vr["exit_mix"]:
                    st.markdown("**Exit reasons**")
                    _bc(" · ".join(f"{k} {v}" for k, v in vr["exit_mix"].items()))
                _extra = []
                if vr["guardian_save_rate"] is not None:
                    _extra.append(f"Guardian save-rate {vr['guardian_save_rate']}%")
                if vr["false_gate_rate"] is not None:
                    _extra.append(f"False-gate rate {vr['false_gate_rate']}%")
                if vr.get("winner_mae"):
                    _m = vr["winner_mae"]
                    _extra.append(f"Winner MAE median {_m['median']} / max {_m['max']} pts")
                if _extra:
                    _bc(" · ".join(_extra))

                # Level 3 layer-contribution
                _lc = vr.get("layer_contribution")
                if _lc:
                    st.markdown("**Layer contribution** (WR when it agreed vs against)")
                    for it in _lc:
                        _c = it.get("contribution")
                        _cs = (f"{_c:+d}%" if _c is not None else "—")
                        _bc(f"• {it['layer']}: agree {it['agree_wr']}% "
                                   f"({it['agree_n']}n) vs against "
                                   f"{it['against_wr'] if it['against_wr'] is not None else '—'}% "
                                   f"→ contribution {_cs}")
        except Exception as _e:
            _bc(f"📊 Validation unavailable: {type(_e).__name__}")

    # ── 🔬 SHADOW layer-weight learning (parallel — never drives live read) ─
    if db is not None:
        try:
            from ..layer_learning import build_shadow_weights, weight_delta_table
            _rows = db.get_layer_outcomes() if hasattr(db, "get_layer_outcomes") else []
            sw = build_shadow_weights(_rows)
            with st.expander(f"🔬 Shadow Layer-Weight Learning ({sw['n']} graded)",
                             expanded=False):
                _bc(sw["disclaimer"])
                if not sw["sufficient"]:
                    for n in sw["notes"]:
                        _bc("• " + n)
                else:
                    st.markdown("**Base vs learned weight** (largest change first)")
                    for row in weight_delta_table(sw):
                        _acc = (f"{row['accuracy']}% acc / {row['samples']}n"
                                if row["accuracy"] is not None else "—")
                        _d = row["delta"]
                        _arrow = "▲" if _d > 0 else ("▼" if _d < 0 else "•")
                        _col = "#17c98b" if _d > 0 else ("#f0455a" if _d < 0 else "#ffffff")
                        st.markdown(
                            f"<div style='font-size:12px;color:#ffffff'>"
                            f"{row['layer']} — base {row['base']} → "
                            f"<b style='color:{_col}'>{row['shadow']} {_arrow}{abs(_d)}</b> "
                            f"<span style='color:#ffffff'>({_acc})</span></div>",
                            unsafe_allow_html=True)
                    _bc("When you trust these, we can promote them to the live "
                               "scorecard — until then this is compare-only.")
        except Exception as _e:
            _bc(f"🔬 Shadow learning unavailable: {type(_e).__name__}")

    # ── Pre-market / Tomorrow (time-gated) ───────────────────────────
    for eng_name, icon in (("stage39_premarket", "🌅"), ("stage38_tomorrow", "🌆")):
        r = state.get(eng_name)
        if r and (r.data or {}).get("active"):
            txt = r.data.get("brief") or r.data.get("report")
            if txt:
                _bc(f"{icon} {txt}")

    # ── AI Summary: evidence / risks / opportunities / changes ───────
    with st.expander("📖 AI Summary — evidence · risks · opportunities", expanded=True):
        if fr["evidence"]:
            st.markdown("**Evidence**")
            for e in fr["evidence"]:
                _bc("• " + e)
        if fr["risks"]:
            st.markdown("**⚠️ Risks**")
            for r in fr["risks"]:
                _bc("• " + r)
        if fr["opportunities"]:
            st.markdown("**💡 Opportunities**")
            for o in fr["opportunities"]:
                _bc("• " + o)
        if fr["changes"]:
            st.markdown("**🔀 What changed this pass**")
            for c in fr["changes"]:
                _bc("• " + c)

    # ── External factors ─────────────────────────────────────────────
    ext = []
    for name, lbl in (("stage19_global", "🌍 Global"),
                      ("stage20_macro", "🛢 Macro"),
                      ("stage21_news", "📰 News")):
        r = state.get(name)
        if r and r.evidence:
            ext.append(f"{lbl}: {r.bias.value}")
    if ext:
        _bc("External — " + " · ".join(ext))

    # ── 🏛️ Market Structure (Stage 2) ────────────────────────────────
    try:
        render_structure_panel(state=state, db=db, run_backfill=run_backfill)
    except Exception as _e:
        _bc(f"🏛️ Structure panel unavailable: {type(_e).__name__}")

    # ── 📖 Market Story Engine ───────────────────────────────────────
    if db is not None:
        try:
            render_story_panel(db=db)
        except Exception as _e:
            _bc(f"📖 Story panel unavailable: {type(_e).__name__}")

    # ── My Analysis + System Monitor ─────────────────────────────────
    with st.expander("📝 My Analysis", expanded=False):
        render_my_analysis(db=db, final_read=fr)
    with st.expander("⚙️ System Health & Error Monitor", expanded=False):
        render_health_panel(state=state, db=db)
