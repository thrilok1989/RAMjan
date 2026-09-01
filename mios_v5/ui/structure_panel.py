"""MIOS V5 — Stage 2 Market Structure Dashboard Panel.

Renders the "MARKET STRUCTURE" summary: trend, price location, S/R, VWAP,
volume profile, order block, chart/candle pattern, Structure Score, and
the Trade/No-Trade Zone decision. No BUY/SELL — location only.
"""

from __future__ import annotations

from typing import Any

from ._bright import bright_caption as _bc

_SCORE_COLOR_STEPS = ((75, "#17c98b"), (35, "#f0b429"))


def _score_color(score: float) -> str:
    for threshold, color in _SCORE_COLOR_STEPS:
        if score >= threshold:
            return color
    return "#f0455a"


def _stars(n: Any) -> str:
    try:
        n = max(0, min(5, int(n)))
    except (TypeError, ValueError):
        return "—"
    return "⭐" * n + "☆" * (5 - n)


def render_structure_panel(state=None, db=None, run_backfill=None) -> None:
    """Render the Stage 2 Market Structure panel from the live MarketState,
    plus the historical backfill control (independent of live state — it
    only needs db). run_backfill is injected by the caller (vob_minimal.py)
    rather than imported here — importing that module by name would
    re-execute its top-level Streamlit side effects (page config,
    credential checks) a second time when it's running as __main__."""
    import streamlit as st

    if state is None:
        _bc("🏛️ Market Structure not available (pipeline not running)")
    else:
        s2 = state.get("stage02_structure")
        if s2 is None or not s2.ok:
            _bc("🏛️ Market Structure warming up — needs price data + a few cycles")
        else:
            d = s2.data
            score = float(d.get("structure_score") or 0)
            color = _score_color(score)
            vp = d.get("volume_profile") or {}
            ob = d.get("order_block") or {}

            with st.expander("🏛️ Market Structure — where is the battle happening?", expanded=False):
                st.markdown(
                    f"<div style='background:#111722;border:1px solid {color};border-radius:10px;"
                    f"padding:12px 16px'>"
                    f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
                    f"<span style='font-weight:800;font-size:16px;color:#ffffff'>"
                    f"{d.get('price_location', '—')}</span>"
                    f"<span style='font-weight:800;font-size:20px;color:{color}'>{score:.0f}%</span>"
                    f"</div>"
                    f"<div style='font-size:11px;color:#ffffff;margin-top:2px'>"
                    f"Decision: <b style='color:{color}'>{d.get('decision', '—')}</b></div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                rows = [
                    ("Trend", f"{d.get('trend', '—')} {_stars(d.get('trend_stars'))}"),
                    ("Nearest Support", f"₹{d['support']:.0f}" if d.get('support') else "—"),
                    ("Nearest Resistance", f"₹{d['resistance']:.0f}" if d.get('resistance') else "—"),
                    ("VWAP", d.get('vwap_position') or "—"),
                    ("Volume Profile", f"{vp.get('side') or '—'} · {vp.get('state') or '—'}"),
                    ("Order Block", ob.get('label') or "None"),
                    ("Chart Pattern", d.get('chart_pattern') or "None"),
                    ("Candlestick", d.get('candle_pattern') or "None"),
                    ("Demand / Supply", d.get('demand_supply') or "Neutral"),
                ]
                for label, value in rows:
                    st.markdown(
                        f"<div style='display:flex;justify-content:space-between;"
                        f"font-size:12.5px;padding:3px 0;border-bottom:1px solid #1e2836'>"
                        f"<span style='color:#ffffff'>{label}</span>"
                        f"<span style='color:#ffffff;font-family:monospace'>{value}</span></div>",
                        unsafe_allow_html=True,
                    )
                if s2.risks:
                    _bc("⚠️ " + " · ".join(s2.risks))

    _render_backfill_control(db, run_backfill)


def _render_backfill_control(db, run_backfill) -> None:
    """🗄️ Historical Backfill — one button, resumable. Replays the already-
    collected candles_data through the price-action-pure Stage 2 detectors
    to backfill engine_state for days before Stage 2 existed. Does not
    cover OI-wall/volume-profile (needs a full option-chain replay this
    doesn't attempt) — rows are version-tagged so they're never confused
    with full-fidelity live rows."""
    import streamlit as st

    if db is None or run_backfill is None:
        return
    with st.expander("🗄️ Historical Backfill — Market Structure", expanded=False):
        try:
            prog = db.get_backfill_progress("stage2_structure") or {}
        except Exception:
            prog = {}
        status = prog.get("status", "idle")
        last_day = prog.get("last_completed_day")
        total_rows = prog.get("total_rows_written", 0)
        _bc(f"Status: **{status}** · last day completed: {last_day or '—'} · "
           f"{total_rows} rows written so far")
        _bc("Covers trend, support/resistance, VWAP, order blocks, and chart/"
           "candle patterns from the candles already collected — not the "
           "OI-wall/volume-profile pieces (those need option-chain history "
           "this backfill doesn't touch, to avoid re-triggering live alert "
           "logic on old data). Processes up to 10 days per click; click "
           "again to continue.")
        if status == "error" and prog.get("error_message"):
            _bc(f"⚠️ Last run error: {prog['error_message']}")
        if st.button("▶️ Run backfill (next 10 days)", key="_stage2_backfill_btn"):
            with st.spinner("Backfilling Market Structure from historical candles..."):
                try:
                    result = run_backfill(db)
                except Exception as e:
                    st.error(f"Backfill failed: {type(e).__name__}: {e}")
                    return
            if result.get("error"):
                st.error(result["error"])
            elif result["days_processed"] == 0 and result["done"]:
                st.info("Nothing to backfill — already caught up to the latest "
                       "collected day.")
            else:
                st.success(
                    f"✅ Processed {result['days_processed']} day(s), "
                    f"wrote {result['rows_written']} rows. "
                    + (f"{result['remaining_days']} day(s) remaining — click "
                       "again to continue." if not result["done"]
                       else "Backfill complete."))
