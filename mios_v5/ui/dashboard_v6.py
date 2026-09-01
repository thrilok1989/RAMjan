"""MIOS V6 — Dashboard V6: the Market Intelligence Workstation.

Not a charting app. A **persistent header** plus six screens, each answering ONE
question:

    1 Decision      should I trade right now?          — the action panel
    2 Trading       where exactly?                     — the cockpit
    3 Intelligence  why does MIOS think that?          — the engine room
    4 History       what happened, and why?            — case studies
    5 Learning      is MIOS actually any good?         — analytics
    6 Replay        can I verify it, cycle by cycle?   — the recording

The split that makes it usable is **2 vs 3**: Dashboard 2 is where a trader
lives during the session and must carry only what you act on; Dashboard 3 is
diagnostics and can be as dense as it likes because you go there deliberately.
Mixing them produces a screen that is too noisy to trade from and too shallow to
debug with.

The header is sticky and identical on every tab. A trader reading a post-trade
review on Dashboard 4 is exactly the one most likely to have stopped watching
the tape — the header is what stops a flow shift happening off-screen.

Highlight CHANGES, not static values: a panel that repeats the same number every
cycle trains the eye to skip it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..final_read import build_final_read, section
from ..sr_intel import build_level_intel, rank_levels
from ..thesis import build_thesis, market_controller, recent_changes

#: 📊 Charts leads, so the synchronised NIFTY ‖ CALL ‖ PUT figure sits directly
#: under the price header instead of four blocks down the Trading tab.
#:
#: ⚠️ This list is the STRIP's layout only — it does not decide what runs first.
#:
#: Streamlit executes each tab body when its container is FILLED, and
#: `render_dashboard_v6` fills them in dependency order, not in this order. So
#: moving a label here is safe; what matters is the fill sequence, and
#: `test_screen_order.py` checks that against the real producer/consumer graph.
#:
#: Charts still has to execute before Trading — `_terminal_chart` is the only
#: producer of `_leg_profiles` (one of the four CRITICAL panels, see
#: `docs/AUDIT_FOCUS_MODE.md`) and `_trading_screen` reads it for the per-leg
#: liquidity bars — but that is enforced by the fill order, not by this list.
_TABS = ["📊 Charts", "🧭 NIFTY", "📈 OPTIONS", "🎯 Decision", "📈 Trading",
         "🧭 Intelligence", "📒 History", "🎓 Learning", "⏪ Replay",
         "🔧 Debug"]

#: One limit per table, shared by every panel that reads it.
#:
#: ⚠️ The read cache keys on the arguments, so `get_session_log(4000)` and
#: `get_session_log(8000)` were two entries and two round-trips for the same
#: rows — and Streamlit runs every tab body on every rerun, so both panels
#: asked whether or not anyone opened them. A panel that wants fewer rows
#: slices the shared result; it must not ask a different question.
SESSION_LOG_LIMIT = 8000
TRADE_SIGNAL_LIMIT = 300

#: The Plotly config every chart on the Charts tab shares: a modebar stripped to the
#: single Fullscreen button Streamlit injects, with scroll-zoom off.
#:
#: ⚠️ The terminal chart passed `displayModeBar: False`, which removed the whole
#: modebar — and with it the Fullscreen button Streamlit adds to the modebar. So the
#: one chart a trader most wants to enlarge was the only one with no way to. The OI
#: and POC charts used the default config, which DID carry the button, but only in a
#: hover-only modebar top-right — discoverable enough to be reported missing.
#:
#: `scrollZoom: False` is kept from the terminal's old config: the wheel zoomed the
#: chart out from under anyone scrolling the page past it. Every pan/zoom/select/reset
#: button is removed, so what remains is exactly the one Fullscreen control — verified
#: on screen, not assumed, since `modeBarButtonsToRemove` only names Plotly's own
#: buttons and the Fullscreen one is Streamlit's.
FS_CHART_CONFIG = {
    "displayModeBar": True,
    "scrollZoom": False,
    "displaylogo": False,
    "modeBarButtonsToRemove": ["zoom2d", "pan2d", "select2d", "lasso2d",
                               "zoomIn2d", "zoomOut2d", "autoScale2d",
                               "resetScale2d", "toImage"],
}

#: Force the modebar visible instead of hover-only, so the Fullscreen button reads as
#: an actual button. Injected once at the top of the Charts tab.
FS_CHART_CSS = ('<style>[data-testid="stFullScreenFrame"] .modebar'
                '{opacity:1 !important}</style>')

#: The four learning reads, under the same rule — and they are the heaviest
#: in the app.
#:
#: ⚠️ Round 3 applied the one-limit rule to the two tables above and missed
#: these, which were being asked at **three** limits each from three panels:
#:
#:     get_engine_attribution   2,000 · 8,000 · 3,000   → 13,000 rows
#:     get_trade_events         1,000 · 4,000 · 1,500   →  6,500 rows
#:     get_trade_results           40 ·   500 ·    60   →    600 rows
#:     get_trade_attribution       40 ·   500 ·    60   →    600 rows
#:
#: Three cache entries, three round-trips, overlapping rows — and all three
#: panels run on every rerun whether or not their tab is open, so every
#: invalidation and every cold start paid for all three.
#:
#: Each limit below is the **widest** of the three, so no panel loses a row.
#: `_learning_rows` returns newest-first, which is what makes a slice
#: equivalent to a narrower query: `rows[:60]` is the same sixty rows
#: `limit=60` would have returned.
ENGINE_ATTRIBUTION_LIMIT = 8000
TRADE_EVENT_LIMIT = 4000
TRADE_RESULT_LIMIT = 500
TRADE_ATTRIBUTION_LIMIT = 500

_CARD = ("background:#0d1117;border:1px solid #1e2836;border-radius:10px;"
         "padding:10px 12px;margin-bottom:8px")


def _dbg_caption(st, source: str, message) -> None:
    """A panel-could-not-draw line, routed through the debug gate.

    ⚠️ NOT deleted and NOT silenced — collected. "A swallowed failure looks
    exactly like the feature was never built" is the report that produced this
    repo's loud-chrome rule, and turning ten captions into ten silences would
    reintroduce it one layer up. With the switch on they print exactly where
    they used to.

    Two failures are deliberately NOT routed here: `Strike Validation` and the
    execution chain's own "did not run" panel. Those are CRITICAL producers, and
    a trader who cannot see that the alert chain is down needs it on the screen
    they are looking at rather than on a tab they are not.
    """
    try:
        from .debug_gate import caption as _c
        _c(st, source, message)
    except Exception:
        try:
            st.caption(str(message))
        except Exception:
            pass


def _strike_oi_charts(st) -> None:
    """📊 Five ATM±2 strikes × (OI · ΔOI), CE against PE, with each strike's read.

    ⚠️ The history is ACCUMULATED by `vob_minimal.strike_store()`, not fetched —
    the reference layout read `session_state.oi_history`, which does not exist in
    this app.

    ⚠️ **Drawn from the FIRST snapshot, not the second.** The first version waited
    for two, and since the store starts empty at every app restart, opening the app
    showed one line of caption where ten charts were expected — reported as "not
    visible", which is exactly what it was. One snapshot is a real observation:
    it gives the current CE-vs-PE level at each strike, which is most of the value.
    Only the BUILD DIRECTION needs two points, and `side_read` already withholds
    that on its own rather than being gated from out here.

    Nothing is recomputed here: `strike_oi_series` builds the figures and the
    per-strike verdicts from the stored series, and this only lays them out.
    """
    try:
        from .. import strike_history as SH
        from . import strike_oi_series as SC
    except Exception as err:
        _dbg_caption(st, "strike_oi_series", f"unavailable: {err}")
        return
    try:
        # ⚠️ Read from session state, NOT by importing `vob_minimal` — `mios_v5`
        # may not import the app, and `test_no_mios_module_imports_the_app`
        # caught the attempt. `strike_store()` publishes the same mutable dict
        # under `_strike_hist`, so this is the identical object.
        store = st.session_state.get("_strike_hist") or {"snaps": []}
        # ⚠️ The basis line is UNCONDITIONAL, and it comes before the conclusions.
        # Tucking it inside the drawing loop meant that if `figures()` returned
        # nothing the whole panel vanished with no explanation — the swallowed
        # failure this repo's loud-chrome rule exists to prevent, reintroduced by
        # the fix that moved the caption up.
        st.caption(f"📊 Per-strike OI / ΔOI (ATM±{SH.WINGS}) · "
                   + SC.caption(store))
        if not SH.read(store)["n"]:
            return
        drew = False
        for measure, title in (("oi", "Per-Strike Call vs Put OI"),
                               ("chg", "Per-Strike Change in Call vs Put OI")):
            figs = SC.figures(store, measure)
            if not figs:
                continue
            st.markdown(f"**📊 {title} · ATM±{SH.WINGS}**")
            cols = st.columns(len(figs))
            for col, (strike, _label, fig) in zip(cols, figs):
                with col:
                    st.plotly_chart(fig, use_container_width=True,
                                    key=f"soi_{measure}_{strike}",
                                    config=FS_CHART_CONFIG)
                    if measure == "oi":
                        _strike_verdict(st, SC.strike_read(store, strike))
            drew = True
        if not drew:
            # Snapshots stored but nothing plottable — say so instead of
            # leaving a heading-less gap that reads as "never built".
            st.caption("📊 …the snapshots carry no OI columns to plot — "
                       "the chain arrived without them.")
    except Exception as err:
        _dbg_caption(st, "strike_oi_series", f"charts unavailable: {err}")


def _strike_verdict(st, r) -> None:
    """One strike's read, in the words `strike_oi_series` produced.

    Support/resistance strength first — it is the level statement — then what each
    side's OI is doing, which is what makes the level credible or fading.
    """
    if not isinstance(r, dict):
        return
    if r.get("balanced"):
        # ⚠️ Equal CE and PE OI is NOT a level. The render showed "WEAK RESISTANCE
        # · 1.0×" on a strike sitting at 9.0L against 9.0L.
        st.markdown("<div style='font-size:11px;font-weight:700;color:#8f9bab'>"
                    "BALANCED · neither side heavier</div>",
                    unsafe_allow_html=True)
    level, strength = r.get("level"), r.get("strength")
    if level and strength:
        tone = {"STRONG": "#00ff88", "MODERATE": "#00cc66",
                "WEAK": "#88aa44"}.get(strength, "#cfd9e6")
        if level == "resistance":
            tone = {"STRONG": "#ff4444", "MODERATE": "#cc4444",
                    "WEAK": "#aa6644"}.get(strength, "#cfd9e6")
        st.markdown(f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
                    f"{strength} {level.upper()} · {r.get('ratio', 0):.1f}×</div>",
                    unsafe_allow_html=True)
        # The caveat rides with the claim it qualifies, not in a footnote.
        if r.get("level_note"):
            st.markdown(f"<div style='font-size:10px;color:#ffb000'>⚠️ "
                        f"{r['level_note']}</div>", unsafe_allow_html=True)
    for side in ("ce", "pe"):
        d = r.get(side) or {}
        if not d.get("state"):
            continue
        bits = [f"{side.upper()}: {d['state']}"]
        if d.get("means"):
            bits.append(d["means"])
        st.markdown(f"<div style='font-size:10px;color:#b3c2d4'>"
                    f"{' · '.join(bits)}</div>", unsafe_allow_html=True)


def _hv_settings(st) -> None:
    """⚙️ The three knobs the reference indicator exposes, behind an Apply button.

    ⚠️ It WRITES `_hv_settings` **only when Apply is clicked**, and computes
    nothing. `vob_minimal._hv_points` reads the same key and fills anything
    absent from `volume_points.defaults()`, so the control and the computation
    cannot disagree about a default.

    Why the button. The number inputs are *staged*: without a gate, every
    intermediate value a trader dials through — 15 → 16 → … → 22 — would commit
    on the next 20-second autorefresh and redraw all three charts, so the pivots
    would flicker while the number was still being chosen. Apply is the single
    moment the staged values become the live setting, and it is where the stale
    per-panel profiles are dropped so the new threshold lands on every chart at
    once, this rerun rather than at the next bar close.

    Collapsed by default: a settings row permanently open above the leg
    tabulation costs that space on every screen to say nothing most days.
    """
    try:
        from ..volume_points import defaults
    except Exception:
        return
    try:
        d = defaults()
        # What is CURRENTLY applied — defaults, overlaid with whatever the last
        # Apply committed to `_hv_settings`. The inputs seed from this, and it is
        # the baseline the staged values are compared against to detect changes.
        applied = dict(d)
        applied.update({k: v for k, v in
                        (st.session_state.get("_hv_settings") or {}).items()
                        if k in d})
        with st.expander("⚙️ High-volume pivots — settings", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                left = st.number_input(
                    "Left bars", min_value=2, max_value=60,
                    value=int(applied["left"]), step=1, key="hv_left",
                    help="Bars before a candidate that must not exceed it. "
                         "On a 1-minute chart, 15 is a quarter-hour.")
            with c2:
                right = st.number_input(
                    "Right bars", min_value=2, max_value=60,
                    value=int(applied["right"]), step=1, key="hv_right",
                    help="Bars after it. A pivot is only confirmed once these "
                         "have printed, so a larger value means fewer, later "
                         "pivots — never earlier ones.")
            with c3:
                filt = st.number_input(
                    "Volume filter", min_value=0.0, max_value=6.0,
                    value=float(applied["filter_vol"]), step=0.1, key="hv_filter",
                    help="On the normalised scale: the pivot's rolling volume "
                         "÷ the session's 95th percentile × 5. Lower keeps more "
                         "pivots. It is relative, so one value works on NIFTY "
                         "and on a ₹90 leg alike.")
            staged = {"left": int(left), "right": int(right),
                      "filter_vol": float(filt)}
            live = {"left": int(applied["left"]), "right": int(applied["right"]),
                    "filter_vol": float(applied["filter_vol"])}
            dirty = staged != live
            b1, b2 = st.columns([1, 3])
            with b1:
                # Disabled when nothing changed, so the button reads as "there is
                # something to apply" rather than a control that does nothing.
                apply_clicked = st.button(
                    "Apply", key="hv_apply", type="primary", disabled=not dirty,
                    help="Apply these pivots to the NIFTY, Call and Put charts "
                         "at once.")
            with b2:
                st.caption("⚠️ Staged — click **Apply** to update every chart."
                           if dirty else "✅ Applied to all charts.")
            if apply_clicked:
                st.session_state["_hv_settings"] = staged
                # ⚠️ The cached per-panel profiles carry the OLD pivots, and they
                # key on bar count — which does not change when a setting does.
                # Dropped here so the new threshold recomputes on every panel;
                # `st.rerun` redraws the charts (already drawn above this control
                # with the old setting) in the same interaction.
                st.session_state.pop("_panel_profiles", None)
                st.rerun()
            st.caption(
                f"defaults {d['left']}/{d['right']} bars · filter "
                f"{d['filter_vol']}. A strongly trending series has no swing "
                f"pivots at any setting — the window's extreme sits at its edge.")
    except Exception as err:
        _dbg_caption(st, "hv_settings", f"settings unavailable: {err}")


def _poc_structure(st) -> None:
    """🏛 Four rolling POCs on a daily axis, then the layered read as a table.

    ⚠️ Everything here is READ. `vob_minimal._publish_poc_series` builds the curves
    off the 5-year daily history Stage 45 already fetches (cached hourly — 1250 bars
    costs ~420 ms, which is not a per-rerun expense), and this lays them out.

    ⚠️ No candles and no close line. With bars drawn the eye follows the bars and
    the POCs become decoration; a close line would make this a second price chart,
    which `terminal_chart` already is. Spot is one horizontal marker, which is all
    the reference price these curves need.
    """
    try:
        from . import poc_structure as PC
    except Exception as err:
        _dbg_caption(st, "poc_structure", f"unavailable: {err}")
        return
    try:
        d = st.session_state.get("_poc_series") or {}
        # ⚠️ NO heading and NO provenance caption when the curves draw. The chart
        # legend names all four windows and the table below carries its own column
        # headers, so both lines were restating what the picture already said —
        # asked for and removed. The warning below is the one text that stays,
        # because when there is nothing to draw it is the only thing on screen.
        if not d.get("series"):
            # ⚠️ Name the SOURCE that failed, not just the absence. "daily history
            # not fetched yet" was reported as the panel not being displayed — and
            # it was the honest truth about the data while telling the reader
            # nothing they could act on. The daily frame has two sources now and
            # `_htf_daily_error` records what each one said.
            why = (st.session_state.get("_htf_daily_error")
                   or d.get("error")
                   or "daily history not fetched yet — it arrives with Stage 45's "
                      "hourly refresh")
            st.warning(f"🏛 Multi-window POC — no daily bars, so no curves. "
                       f"Tried: {why}. Stage 45's Daily/Weekly/Monthly/Yearly "
                       f"profiles need the same frame.")
            return
        fig = PC.figure(d.get("dates") or [], d.get("series") or {},
                        d.get("spot"), d.get("subdaily"))
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key="poc_structure",
                            config=FS_CHART_CONFIG)
        html = PC.table_html(d.get("rows") or [], d.get("align"))
        if html:
            st.markdown(html, unsafe_allow_html=True)
        # The 1H / 4H POCs as a sentence — see poc_structure.figure for why they
        # are not lines on this axis.
        sub = PC.subdaily_line(d.get("subdaily"), d.get("spot"))
        if sub:
            st.markdown(sub, unsafe_allow_html=True)
    except Exception as err:
        _dbg_caption(st, "poc_structure", f"unavailable: {err}")


def _feed_reason(st) -> str:
    """Why there is no data, in `feed_status`' words.

    ⚠️ One owner for the answer. Three panels stand by on a missing chain and each
    used to explain it differently — none of them mentioning that before 09:15
    there simply is no chain to fetch, which made a healthy morning look broken.
    """
    try:
        from datetime import datetime

        import pytz

        from ..feed_status import sentence
        return sentence(st.session_state,
                        datetime.now(pytz.timezone("Asia/Kolkata")))
    except Exception:
        return "the option chain has not arrived yet."


def _spot_price(state):
    """NIFTY spot from the one owner — `mios_v5.spot`.

    A thin adapter so the import lives in one place and every panel in this file
    resolves spot the same way. Falls back to the chain only if the module cannot
    be imported, which keeps a broken import from blanking every price on screen.
    """
    try:
        from ..spot import price as _p
        return _p(state)
    except Exception:
        try:
            return (state.get("_cached_option_data") or {}).get("underlying")
        except Exception:
            return None


def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _fmt(v) -> str:
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def render_dashboard_v6(state=None, db=None) -> None:
    import streamlit as st

    if state is None or not getattr(state, "results", None):
        st.info("MIOS pipeline warming up — Dashboard V6 pending first pass.")
        return
    fr = build_final_read(state) or {}

    # ── the persistent header: identical on every tab, above the tab bar ──
    from .header_panel import header_html
    from ..header import alerts as header_alerts
    from ..header import build as header_tiles
    spot = None
    try:
        # The strip every tab sits under. Chain-only here was the most visible
        # desync in the app: this header and the app chrome above it read two
        # different numbers and both called them spot.
        spot = _spot_price(st.session_state)
    except Exception:
        spot = None
    st.markdown(header_html(header_tiles(fr, spot), header_alerts(fr)),
                unsafe_allow_html=True)

    tabs = st.tabs(_TABS)

    # ⚠️ FILLED IN DEPENDENCY ORDER, NOT TAB ORDER.
    #
    # `st.tabs()` returns containers that may be filled in any sequence — the
    # strip's left-to-right order is fixed by `_TABS` and does not change here.
    # What changes is the order the bodies EXECUTE in during one rerun, and that
    # is a real dependency:
    #
    #     _charts_screen      writes  _leg_profiles
    #     _trading_screen     reads   _leg_profiles
    #                         writes  _sr_levels · _premium_energy
    #                                 _premium_structures · _entry_decision
    #     _nifty_cockpit      reads   _sr_levels · _entry_decision
    #     _options_cockpit    reads   _premium_energy · _premium_structures
    #
    # Filled in tab order the three cockpits ran BEFORE their producer, so:
    #   · on the first render of a session those keys did not exist and the
    #     blocks drew nothing — the "⚪ Not reporting yet: sr table / premium
    #     energy / premium structure / option flow" captions;
    #   · on every render after, they silently showed the PREVIOUS cycle's data,
    #     20 seconds behind the panels beside them.
    #
    # This is a consequence of moving the new dashboards to the front of the
    # strip: the layout moved, the producers did not. Nothing is recomputed here
    # and no engine is touched — only the sequence the tab bodies run in.
    with tabs[0]:
        _charts_screen(st, fr)
    with tabs[4]:
        _trading_screen(st, fr, state)
    with tabs[1]:
        _nifty_cockpit(st, fr)
    with tabs[2]:
        _options_cockpit(st, fr)
    with tabs[3]:
        _decision_center(st, fr)
    with tabs[5]:
        _intelligence(st, fr, state)
    with tabs[6]:
        _history(st, db)
    with tabs[7]:
        _learning(st, db, fr)
    with tabs[8]:
        _replay(st, db)
    with tabs[9]:
        # ⚠️ Presentation only. Nothing on this tab switches an engine off — see
        # `debug_gate.PROTECTED` and docs/AUDIT_FOCUS_MODE.md.
        from .debug_gate import render_panel as _debug_panel
        _debug_panel(st, db)


# ── 0b · NIFTY INDEX COCKPIT ────────────────────────────────────────────
def _nifty_cockpit(st, fr: Dict[str, Any]) -> None:
    """🧭 Dashboard 1 — the index, in five blocks and nothing else.

    Where is NIFTY · where are the OI walls · is it pinned · where are S/R · who
    is winning. Option-leg behaviour is Dashboard 2's; engine telemetry is the
    audit expander's.

    **This function only reads.** Every value below has an owner that already
    published it, and `nifty_cockpit.py` formats without re-deriving:

        POC · VAH · VAL        calculate_money_flow_profile → _money_flow_data
        VWAP · walls · pin     compute_market_picture       → _market_picture
        gamma flip             calculate_dealer_gex         → _gex_data
        prev day H/L/C         runner Stage 3               → _mios_market_memory
        S/R ranking            sr_intel.rank_levels         → _sr_levels
        battle zone            Stage 35                     → final_read

    ⚠️ FIXED — this note used to describe the bug as expected behaviour, and was
    wrong about where the producer lives.

    `_sr_levels` is published by `_sr_intelligence`, which `_trading_screen`
    calls — NOT the Intelligence tab, as this said. Because the tab bodies were
    filled in tab order, this cockpit (tab 1) ran before that producer (tab 4):
    the table was empty on the first rerun of a session and showed the PREVIOUS
    cycle's levels on every rerun after.

    The old note concluded that fixing it would mean moving a CRITICAL producer.
    It would not: `st.tabs()` containers may be filled in any sequence and the
    strip's layout is unaffected, so `render_dashboard_v6` now fills Trading
    before the cockpits and nothing moved on screen. See `test_screen_order.py`.
    """
    from .nifty_cockpit import BLOCK_ORDER, cockpit_blocks

    ss = st.session_state
    mp = ss.get("_market_picture") or {}
    opt = ss.get("_cached_option_data") or {}
    # ⚠️ One owner. This line used to read `opt.get("underlying") or
    # ss.get("_nifty_spot_live")` — chain FIRST — and the chain almost always has
    # a value, so the live LTP was never reached. The panel showed a price moving
    # on the chain's cadence while the header beside it ticked.
    spot = _spot_price(ss)

    day = None
    try:
        df = ss.get("_nifty_df_live")
        if df is not None and not getattr(df, "empty", True):
            day = {"high": float(df["high"].max()),
                   "low": float(df["low"].min())}
    except Exception:
        day = None

    atm = None
    try:
        atm = (ss.get("_atm_pm1_vpfr") or {}).get("atm_strike")
    except Exception:
        atm = None

    blocks = cockpit_blocks({
        "spot": spot,
        "profile": ss.get("_money_flow_data"),
        "vwap": mp.get("vwap"),
        "day": day,
        "prev_day": ss.get("_mios_market_memory"),
        "oi_ceiling": mp.get("oi_ceiling"),
        "oi_floor": mp.get("oi_floor"),
        "oi_pin": mp.get("oi_pin"),
        "gate": mp.get("entry_gate"),
        "gamma_flip": (mp.get("gex_disp") or {}).get("flip"),
        "ladder": _oi_ladder(opt.get("df_summary"), atm),
        "pcr": _total_pcr(opt.get("df_summary")),
        "atm": atm,
        "sr_levels": ss.get("_sr_levels"),
        "battle_zone": fr.get("battle_zone"),
        "winner": fr.get("expected_winner"),
        "probabilities": fr.get("probabilities"),
        # ── who controls the market ──────────────────────────────────
        # Each label is the Market Picture's own wording for that vote, and
        # `overall` is its own regime with that regime's own probability.
        # ⚠️ Averaging these rows here would mint a SECOND overall bias — same
        # inputs, different method, same screen — which is the disagreement the
        # architecture principles open by forbidding.
        "bias_rows": _bias_rows(mp),
        "overall": mp.get("regime"),
        "confidence": _regime_confidence(mp),
        # ── liquidity ────────────────────────────────────────────────
        "liq_pools": mp.get("liq_pools"),
        "poc_regime": _liq_read(ss.get("_liquidity_context"), "poc_regime"),
        "poc_stability": _liq_read(ss.get("_liquidity_context"),
                                   "poc_stability"),
        # ── higher timeframes · Stage 45 ─────────────────────────────
        "htf": ss.get("_htf_profiles"),
        # ── the outside world ────────────────────────────────────────
        "external_rows": _external_rows(mp, ss),
        # ── 🏛 institutional flows · Stage 23 ─────────────────────────
        # Fetched every cycle into `_fii_dii_cash` / `_fii_deriv_stats` and,
        # until now, drawn nowhere — the one display site read the wrong key
        # shape, so the row was permanently a dash.
        #
        # The verdict is Stage 23's, passed through: it owns the ₹-crore
        # thresholds and the absorption-battle test, and re-deciding them here
        # would put two answers to one question on one screen.
        "fii_dii_cash": ss.get("_fii_dii_cash"),
        "fii_deriv": ss.get("_fii_deriv_stats"),
        **{f"flows_{k}": v for k, v in _flows_read(ss).items()},
        # ── so what ──────────────────────────────────────────────────
        "regime": mp.get("regime"),
        "need": _gate_needs(mp.get("entry_gate")),
    })

    if not blocks:
        st.info("🧭 NIFTY cockpit standing by — " + _feed_reason(st)
                + " It reads the Market Picture, the volume profile and the "
                  "chain.")
        return

    left, right = st.columns(2)
    # price map and the walls are the two a trader reads first, so they take the
    # top row together rather than stacking a 9-row table above a 5-row one.
    with left:
        st.markdown(blocks.get("price_map", ""), unsafe_allow_html=True)
        st.markdown(blocks.get("market_pin", ""), unsafe_allow_html=True)
    with right:
        st.markdown(blocks.get("oi_walls", ""), unsafe_allow_html=True)
        st.markdown(blocks.get("battle_zone", ""), unsafe_allow_html=True)
    st.markdown(blocks.get("sr_table", ""), unsafe_allow_html=True)

    # Second row: who controls it, and where the liquidity is.
    lo, ro = st.columns(2)
    with lo:
        st.markdown(blocks.get("bias_stack", ""), unsafe_allow_html=True)
    with ro:
        st.markdown(blocks.get("liquidity", ""), unsafe_allow_html=True)
        st.markdown(blocks.get("external", ""), unsafe_allow_html=True)
        # 🏛 Under the external context, because it is the same kind of reading:
        # slow, outside the chain, and daily. Deliberately NOT beside the live
        # intraday panels on the left, where a ₹-crore figure from yesterday
        # sits among ticking numbers and reads as current.
        st.markdown(blocks.get("fii_dii", ""), unsafe_allow_html=True)
    st.markdown(blocks.get("htf", ""), unsafe_allow_html=True)
    # The state closes the dashboard, because it is the only line that is worth
    # anything after reading the nine above it.
    st.markdown(blocks.get("market_state", ""), unsafe_allow_html=True)

    # ── ⚙️ Dealer & volatility context — the Adaptive Greeks read ────────
    # Built HERE, once, and published to `_adaptive_greeks`. Three other
    # surfaces read that key — the header chip, the Market Picture line and the
    # Trade Card line — so this call is what makes all four work. Without it
    # they each read an absent key and silently draw nothing, which is exactly
    # what happened when this block failed to apply the first time.
    try:
        from .greeks_panel import greeks_card_html
        _ag = _adaptive_greeks(st, fr)
        if _ag:
            _gw, _gc = _guardian_read(st, fr)
            st.markdown(greeks_card_html(_ag, _gw, _gc),
                        unsafe_allow_html=True)
    except Exception as err:
        _dbg_caption(st, "greeks_panel", f"Greeks context unavailable: {err}")

    missing = [b for b in BLOCK_ORDER if b not in blocks]
    if missing:
        st.caption("⚪ Not reporting yet: "
                   + " · ".join(b.replace("_", " ") for b in missing)
                   + ". Each fills once its producer has run this session.")


# ── 0c · OPTIONS / LTP INTELLIGENCE ─────────────────────────────────────
def _options_cockpit(st, fr: Dict[str, Any]) -> None:
    """📈 Dashboard 2 — what the PREMIUMS are doing, and nothing about the index.

    The NIFTY read is Dashboard 1's. Repeating it here is the duplication the
    split exists to remove, so this tab draws no spot, no regime and no index
    levels.

    **Reads only.** Every field has a stage that published it:

        Stage 71.8 `_premium_structures`  ltp · support · resistance · vp_poc ·
                                          acceptance · momentum · rvol ·
                                          cbv/csv/cvd · break/fakeout · score
        Stage 71.7 `_premium_energy`      energy · spike · strength · preferred
        the chain  `df_summary`           LTP · OI · ΔOI · volume · bid/ask

    `_premium_structures` is keyed by `(side, strike)` TUPLES. Re-keying is done
    here rather than asking the pure module to understand a tuple key, which is
    the same boundary rename `_mios_market_read` does.

    ⚠️ FIXED — this note used to end "So on the first rerun of a session the
    structure and flow blocks are empty and fill on the next", which recorded a
    real bug as accepted behaviour. Stage 71.8 publishes `_premium_structures`
    from `_strike_validation` on the Trading tab, and filling the tabs in tab
    order ran this cockpit first, so those blocks showed nothing on the first
    rerun and the PREVIOUS cycle's data on every one after.
    `render_dashboard_v6` now fills Trading before the cockpits — the strip is
    unchanged, since `st.tabs()` containers may be filled in any sequence. See
    `test_screen_order.py`.
    """
    from .options_cockpit import (BLOCK_ORDER, cockpit_blocks,
                                 greeks_table_html)

    ss = st.session_state
    opt = ss.get("_cached_option_data") or {}
    ds = opt.get("df_summary")
    # ⚠️ One owner. This line used to read `opt.get("underlying") or
    # ss.get("_nifty_spot_live")` — chain FIRST — and the chain almost always has
    # a value, so the live LTP was never reached. The panel showed a price moving
    # on the chain's cadence while the header beside it ticked.
    spot = _spot_price(ss)
    atm = None
    try:
        atm = (ss.get("_atm_pm1_vpfr") or {}).get("atm_strike")
    except Exception:
        atm = None

    structures = _by_side(ss.get("_premium_structures"))
    blocks = cockpit_blocks({
        "expiry": opt.get("expiry") or opt.get("selected_expiry"),
        "atm": atm,
        "spot": spot,
        "legs": _leg_quotes(ds, atm, structures),
        "ladder": _premium_ladder(ds, atm, structures),
        "energy": ss.get("_premium_energy"),
        "structures": structures,
        "flows": structures,
        # Read, not derived: comparing the two CVDs here would be a second
        # opinion on the question Stage 71.7 answers with `preferred`.
        "flow_verdict": (ss.get("_premium_energy") or {}).get("preferred"),
    })

    if not blocks:
        # ⚠️ The old text named the two stages and left the trader to guess
        # whether the app was broken. At 08:25 it appears on a healthy app,
        # because there is no option chain before 09:15 — and everything here
        # hangs off the chain. `feed_status` gives the same answer the Trade Card
        # gives, so one silence cannot get two explanations.
        st.info("📈 Options cockpit standing by — " + _feed_reason(st)
                + " Premium energy (71.7) and premium structure (71.8) both "
                  "need the chain and the ATM legs.")
        return

    st.markdown(blocks.get("option_header", ""), unsafe_allow_html=True)
    st.markdown(blocks.get("leg_cards", ""), unsafe_allow_html=True)
    st.markdown(blocks.get("premium_ladder", ""), unsafe_allow_html=True)

    # ⚠️ Behind an expander, per the spec: no Greeks on the default screen. Kept
    # available rather than deleted — a trader who wants delta on expiry day
    # should not have to read the chain on another tab.
    _greeks = greeks_table_html(_greek_rows(ds, atm))
    if _greeks:
        with st.expander("🔬 Advanced Greeks — ATM ±2", expanded=False):
            st.markdown(_greeks, unsafe_allow_html=True)

    lo, ro = st.columns(2)
    with lo:
        st.markdown(blocks.get("premium_energy", ""), unsafe_allow_html=True)
    with ro:
        st.markdown(blocks.get("option_flow", ""), unsafe_allow_html=True)
    st.markdown(blocks.get("premium_structure", ""), unsafe_allow_html=True)

    st.caption("📊 The synchronised NIFTY ‖ CALL ‖ PUT charts are on the "
               "**Charts** tab — one figure, not a second copy here.")

    missing = [b for b in BLOCK_ORDER if b not in blocks]
    if missing:
        st.caption("⚪ Not reporting yet: "
                   + " · ".join(b.replace("_", " ") for b in missing)
                   + ". Each fills once its stage has run this session.")


def _by_side(structures) -> Dict[str, Dict[str, Any]]:
    """`{(side, strike): {...}}` → `{side: {...}}`, ATM-nearest kept.

    ⚠️ The exact re-keying `_mios_market_read` already needed. Handing the tuple
    keys straight to a consumer that reads `{side}` yields nothing for every
    field — present, wrong shape, no error — which is how both legs once rendered
    the same raw dict into a Telegram message.
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(structures, dict):
        return out
    for key, val in structures.items():
        side = key[0] if isinstance(key, tuple) and key else key
        if side in ("CALL", "PUT") and isinstance(val, dict):
            # First wins: the picker publishes the chosen strike first, and a
            # later wing strike must not overwrite the leg being traded.
            out.setdefault(side, dict(val))
            if isinstance(key, tuple) and len(key) > 1:
                out[side].setdefault("strike", key[1])
    return out


def _chain_row(ds, strike):
    """One strike's chain row, or None. A lookup, never a search for a maximum."""
    if ds is None or getattr(ds, "empty", True) or strike is None:
        return None
    try:
        hit = ds[(ds["Strike"] - float(strike)).abs() < 0.5]
        return None if hit.empty else hit.iloc[0]
    except Exception:
        return None


def _row_num(row, *names):
    for n in names:
        try:
            if row is not None and n in row.index and row.get(n) is not None:
                return float(row.get(n))
        except Exception:
            continue
    return None


def _leg_quotes(ds, atm, structures) -> Dict[str, Dict[str, Any]]:
    """Per-side quote + flow, assembled from the chain row and Stage 71.8.

    The chain owns LTP, OI, ΔOI, volume and the book; Stage 71.8 owns the flow
    totals and RVOL. Neither is recomputed — this is a join, and the two sources
    are kept distinct so a missing stage leaves a hole rather than a guess.
    """
    row = _chain_row(ds, atm)
    out: Dict[str, Dict[str, Any]] = {}
    for side, sfx in (("CALL", "CE"), ("PUT", "PE")):
        st_node = (structures or {}).get(side) or {}
        bid = _row_num(row, f"bidQty_{sfx}", f"top_bid_quantity_{sfx}")
        ask = _row_num(row, f"askQty_{sfx}", f"top_ask_quantity_{sfx}")
        node = {
            "strike": atm,
            "ltp": (_row_num(row, f"lastPrice_{sfx}", f"last_price_{sfx}")
                    or st_node.get("ltp")),
            "volume": _row_num(row, f"totalTradedVolume_{sfx}", f"volume_{sfx}"),
            "oi": _row_num(row, f"openInterest_{sfx}", f"{sfx}_OI"),
            "doi": _row_num(row, f"changeinOpenInterest_{sfx}"),
            "rvol": st_node.get("rvol"),
            "cbv": st_node.get("cbv"), "csv": st_node.get("csv"),
            "cvd": st_node.get("cvd"),
            "buy_share": (st_node.get("flow") or {}).get("buy_share")
            if isinstance(st_node.get("flow"), dict) else None,
            "bid_ask": (f"{bid:,.0f} / {ask:,.0f}"
                        if bid is not None and ask is not None else None),
            # The same published CVD sign the ladder uses, so the card and the
            # row for this strike cannot say different things about one leg.
            "money_flow": _flow_of(st_node),
        }
        if any(v is not None for v in node.values()):
            out[side] = node
    return out


def _premium_ladder(ds, atm, structures) -> Optional[List[Dict[str, Any]]]:
    """ATM±2 premium rows. A projection of the chain, with no maximum taken.

    CVD and the flow word come from Stage 71.8 for the strikes it published and
    are simply absent for the wings — an honest hole rather than a zero.
    """
    if ds is None or getattr(ds, "empty", True):
        return None
    try:
        strikes = sorted(ds["Strike"].dropna().unique().tolist())
        if not strikes:
            return None
        centre = float(atm) if atm is not None else strikes[len(strikes) // 2]
        near = sorted(strikes, key=lambda s: abs(s - centre))[:5]
        rows = []
        for k in near:
            row = _chain_row(ds, k)
            if row is None:
                continue
            at_atm = atm is not None and abs(float(k) - float(atm)) < 0.5
            call = (structures or {}).get("CALL") or {} if at_atm else {}
            put = (structures or {}).get("PUT") or {} if at_atm else {}
            rows.append({
                "strike": float(k),
                "ce_ltp": _row_num(row, "lastPrice_CE", "last_price_CE"),
                "pe_ltp": _row_num(row, "lastPrice_PE", "last_price_PE"),
                "ce_doi": _row_num(row, "changeinOpenInterest_CE"),
                "pe_doi": _row_num(row, "changeinOpenInterest_PE"),
                "ce_cvd": call.get("cvd"), "pe_cvd": put.get("cvd"),
                "ce_flow": _flow_of(call), "pe_flow": _flow_of(put),
            })
        return rows or None
    except Exception:
        return None


def _flow_of(node) -> Optional[str]:
    """BULL / BEAR from a published CVD sign — the sign IS the reading.

    Not a threshold and not a classification: a positive cumulative delta means
    buyers were adding, which is what the word says. Anything with a threshold
    in it would belong to Stage 71.7, not here.
    """
    try:
        v = node.get("cvd") if isinstance(node, dict) else None
        if v is None:
            return None
        f = float(v)
        return "BULL" if f > 0 else "BEAR" if f < 0 else "FLAT"
    except (TypeError, ValueError):
        return None


def _greek_rows(ds, atm) -> Optional[List[Dict[str, Any]]]:
    """ATM±2 Greeks, for the expander only."""
    if ds is None or getattr(ds, "empty", True):
        return None
    try:
        strikes = sorted(ds["Strike"].dropna().unique().tolist())
        if not strikes:
            return None
        centre = float(atm) if atm is not None else strikes[len(strikes) // 2]
        rows = []
        for k in sorted(strikes, key=lambda s: abs(s - centre))[:5]:
            row = _chain_row(ds, k)
            if row is None:
                continue
            rows.append({
                "strike": float(k),
                "ce_delta": _row_num(row, "Delta_CE"), "pe_delta": _row_num(row, "Delta_PE"),
                "ce_gamma": _row_num(row, "Gamma_CE"), "pe_gamma": _row_num(row, "Gamma_PE"),
                "ce_vega": _row_num(row, "Vega_CE"), "pe_vega": _row_num(row, "Vega_PE"),
                "ce_theta": _row_num(row, "Theta_CE"), "pe_theta": _row_num(row, "Theta_PE"),
            })
        return rows or None
    except Exception:
        return None


def _adaptive_greeks(st, fr: Dict[str, Any]):
    """Build the Adaptive Greeks read once per cycle and publish it.

    ⚠️ Published to `_adaptive_greeks` because FOUR surfaces show it — this tab,
    the header chip, the Market Picture and the Trade Card. Building it four
    times would be four chances to disagree about one cycle, which is the drift
    principle 3 exists to stop: one calculation, published once, many consumers.

    Every input is read from an owner. The expiry pin comes from `charm_pin`,
    which already owns that rule and its wording.
    """
    try:
        from ..adaptive_greeks import read as _greeks_read
        # ⚠️ `dealer_magnet`, not `charm_pin`: the pin gate used to mean the
        # PINNED regime could never be detected off expiry, so a normal day with
        # price sat on the max-OI strike read as RANGE. `charm_pin` still owns
        # the measurement; this only lifts the calendar gate.
        from ..dealer_magnet import read as _pin_read
    except Exception:
        return None
    ss = st.session_state
    mp = ss.get("_market_picture") or {}
    opt = ss.get("_cached_option_data") or {}
    # ⚠️ One owner. This line used to read `opt.get("underlying") or
    # ss.get("_nifty_spot_live")` — chain FIRST — and the chain almost always has
    # a value, so the live LTP was never reached. The panel showed a price moving
    # on the chain's cadence while the header beside it ticked.
    spot = _spot_price(ss)
    gex = mp.get("gex_disp") or {}
    is_expiry = bool(ss.get("_is_expiry_today"))
    try:
        pin = _pin_read(is_expiry, spot,
                        pin=(mp.get("oi_pin") or (None,))[0]
                        if isinstance(mp.get("oi_pin"), (list, tuple))
                        else None,
                        net_charm=(mp.get("vc_exp") or {}).get("net_charm"))
    except Exception:
        pin = None
    try:
        out = _greeks_read(
            flow={"regime": mp.get("regime"),
                  "order_flow": (mp.get("oflow_imb") or {}).get("label"),
                  "cvd": (mp.get("oflow_imb") or {}).get("tilt")},
            doi=mp.get("doi_bias"),
            gex=gex, dex=mp.get("dex_bias"), vc=mp.get("vc_exp"),
            skew=mp.get("skew_bias"), iv_series=ss.get("_iv_history"),
            spot=spot, magnet=gex.get("magnet"), is_expiry=is_expiry,
            pin=pin, market_picture=mp, reaction=fr.get("reaction"))
    except Exception as err:
        _dbg_caption(st, "adaptive_greeks", f"Adaptive Greeks unavailable: {err}")
        return None
    ss["_adaptive_greeks"] = out
    return out


def _guardian_read(st, fr: Dict[str, Any]):
    """The existing verdict and its confidence — READ, never produced.

    `adaptive_greeks` emits no side, so the Guardian line on every surface has to
    come from whatever already decided it: the entry gate's state, or Stage 72's
    decision when it has one. The greeks layer's `confidence_delta` is applied
    through `apply_to`, so the arithmetic lives in one place.
    """
    ss = st.session_state
    word = conf = None
    try:
        dec = ss.get("_entry_decision")
        word = getattr(dec, "state", None) or (
            dec.get("state") if isinstance(dec, dict) else None)
        conf = getattr(dec, "confidence", None) or (
            dec.get("confidence") if isinstance(dec, dict) else None)
    except Exception:
        word = conf = None
    if not word:
        gate = (ss.get("_market_picture") or {}).get("entry_gate") or {}
        word = gate.get("state")
    if conf is None:
        d2 = fr.get("decision_v2") or {}
        conf = d2.get("confidence") if isinstance(d2, dict) else None
    try:
        from ..adaptive_greeks import apply_to
        conf = apply_to(conf, ss.get("_adaptive_greeks") or {})
    except Exception:
        pass
    # 🌉 ONE bridge, not a second read. The header wants the same pair, and
    # `_chrome_extras` runs in `vob_minimal` after the cycle — which may not import
    # this module. Publishing the resolved pair means the strip and the card cannot
    # show different verdicts for the same cycle, which is the whole reason this
    # function exists rather than each surface resolving the gate itself.
    try:
        ss["_entry_verdict"] = (word, conf)
    except Exception:
        pass
    return word, conf


def _oi_ladder(df_summary, atm) -> Optional[List[Dict[str, Any]]]:
    """ATM±2 rows off the chain — a projection, not a calculation.

    No maximum is taken and no wall is chosen here: those belong to
    `compute_market_picture`, and picking them again is how two panels come to
    disagree about which strike the wall is on.
    """
    if df_summary is None or getattr(df_summary, "empty", True):
        return None
    try:
        cols = df_summary.columns
        ce_oi = "openInterest_CE" if "openInterest_CE" in cols else "CE_OI"
        pe_oi = "openInterest_PE" if "openInterest_PE" in cols else "PE_OI"
        if ce_oi not in cols or pe_oi not in cols:
            return None
        ce_d = ("changeinOpenInterest_CE"
                if "changeinOpenInterest_CE" in cols else None)
        pe_d = ("changeinOpenInterest_PE"
                if "changeinOpenInterest_PE" in cols else None)
        strikes = sorted(df_summary["Strike"].dropna().unique().tolist())
        if not strikes:
            return None
        centre = float(atm) if atm is not None else strikes[len(strikes) // 2]
        near = sorted(strikes, key=lambda s: abs(s - centre))[:5]
        out = []
        for k in near:
            row = df_summary[df_summary["Strike"] == k]
            if row.empty:
                continue
            r = row.iloc[0]
            out.append({
                "strike": float(k),
                "ce_oi": float(r.get(ce_oi) or 0) or None,
                "pe_oi": float(r.get(pe_oi) or 0) or None,
                "ce_doi": (float(r.get(ce_d)) if ce_d
                           and r.get(ce_d) is not None else None),
                "pe_doi": (float(r.get(pe_d)) if pe_d
                           and r.get(pe_d) is not None else None),
            })
        return out or None
    except Exception:
        return None


def _bias_rows(mp: Dict[str, Any]) -> List[Tuple[str, Any]]:
    """`(name, label)` for every input the Market Picture voted on.

    Each label is **that vote's own wording**, pulled from the field
    `compute_market_picture` published. Nothing is classified here: a row whose
    owner said nothing arrives blank and `bias_stack_html` lists it as silent,
    which is the honest answer and not the same as neutral.
    """
    def lab(node, *keys):
        if not isinstance(node, dict):
            return node if isinstance(node, str) else None
        for k in keys:
            v = node.get(k)
            if v not in (None, ""):
                return v
        return None

    def direction(node, *keys):
        """The owner's OWN direction word, when it published one.

        ⚠️ This is why the rows are 3-tuples. Without it the chip's colour comes
        from keyword-matching the owner's prose — and `'Bullish (PE writers
        building support)'` only reads as bullish while the word "Bullish"
        survives a rewording. `dex_bias` and `skew_bias` publish `bias` as
        BULL/BEAR outright, so those never need guessing at all.
        """
        if not isinstance(node, dict):
            return None
        for k in keys:
            v = node.get(k)
            if v not in (None, ""):
                return v
        return None

    return [
        ("Price structure", mp.get("regime"), mp.get("regime")),
        ("ATM chain", lab(mp.get("atm_bias"), "verdict", "oi"), None),
        ("ΔOI", lab(mp.get("doi_bias"), "label"), None),
        ("Dealer GEX", lab(mp.get("gex_disp"), "signal"), None),
        ("Dealer DEX", lab(mp.get("dex_bias"), "label", "bias"),
         direction(mp.get("dex_bias"), "bias")),
        ("IV skew", lab(mp.get("skew_bias"), "label", "bias"),
         direction(mp.get("skew_bias"), "bias")),
        ("Order flow", lab(mp.get("oflow_imb"), "label"), None),
        ("Global", lab(mp.get("global_bias"), "label"), None),
        ("News", lab(mp.get("news_bias"), "label"), None),
    ]


def _regime_confidence(mp: Dict[str, Any]) -> Optional[float]:
    """The published probability OF THE REGIME the Market Picture reported.

    ⚠️ Selection, not calculation. `p_up`, `p_down` and `p_side` are all
    published; this picks the one that matches `regime` so the number under the
    verdict is that verdict's own confidence. Taking a max independently of the
    regime would let the two disagree — a SIDEWAYS call carrying `p_up`.
    """
    key = {"UP": "p_up", "DOWN": "p_down",
           "SIDEWAYS": "p_side"}.get(str(mp.get("regime") or "").upper())
    if not key:
        return None
    try:
        v = mp.get(key)
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _liq_read(ctx, field: str):
    """One Stage 74 field, through the context's own accessor.

    `TradingContext.value` returns the sentinel `UNKNOWN` for a field with no
    live producer, which must not reach the screen as a reading — so it is
    converted to `None` here and the block simply omits the row.
    """
    try:
        if ctx is None:
            return None
        v = ctx.value(field)
        return None if v is None or str(v).upper() == "UNKNOWN" else v
    except Exception:
        return None


def _external_rows(mp: Dict[str, Any], ss) -> List[Tuple[str, Any]]:
    """The outside world, each line already worded by the panel that fetched it.

    VIX is the one that needs care: `vix_history` is a list of values, so the
    REGIME is `Stage 22`'s to name and there is no published label to read. Rather
    than inventing a threshold here, the raw level is shown — a number a trader
    reads directly, with no classification pretending to be one.
    """
    rows: List[Tuple[str, Any]] = [
        ("Global", (mp.get("global_bias") or {}).get("label")
         if isinstance(mp.get("global_bias"), dict) else None),
        ("News", (mp.get("news_bias") or {}).get("label")
         if isinstance(mp.get("news_bias"), dict) else None),
        ("Commodity", (mp.get("commodity_bias") or {}).get("regime")
         if isinstance(mp.get("commodity_bias"), dict) else None),
        ("Sector rotation", (mp.get("sector_bias") or {}).get("rotation")
         if isinstance(mp.get("sector_bias"), dict) else None),
    ]
    try:
        vh = ss.get("vix_history") or []
        if vh:
            rows.append(("India VIX", f"{float(vh[-1]):.2f}"))
        else:
            rows.append(("India VIX", None))
    except Exception:
        rows.append(("India VIX", None))
    # 🏛 FII / DII — ⚠️ this row read `fd.get("fii_net")`, which is
    # `stage23_flows`' OUTPUT shape, not the raw NSE payload's. `_fii_dii_cash`
    # is `{"FII": {buy, sell, net, date}, "DII": {...}}`, so the lookup always
    # missed and the row has shown a dash since the day it was written — fetched
    # every cycle, published, and never once displayed.
    #
    # Both sides, not just FII: `FII −4,200` is a rout or a non-event depending
    # entirely on what DII did against it, and one number invites the first
    # reading.
    try:
        from .fii_dii_panel import micro as _fii_micro
        _fl = _flows_read(ss)
        rows.append(("FII / DII (EOD)",
                     _fii_micro(ss.get("_fii_dii_cash"),
                                _fl.get("conflict")) or None))
    except Exception:
        rows.append(("FII / DII (EOD)", None))
    return rows


def _flows_read(state) -> Dict[str, Any]:
    """Stage 23's verdict on the institutional flows, or an empty read.

    ⚠️ READ, not re-derived. `stage23_flows` owns the ₹-crore thresholds
    (`_STRONG = 2500`, `_MILD = 800`), the bias and the absorption-battle
    detection. Answering "is ₹2,500cr a lot?" a second time in the display layer
    would put two answers to one question on the same screen.
    """
    out: Dict[str, Any] = {}
    try:
        res = (state.get("_mios_state") or {}).get("stage23_flows")
        if res is None:
            return out
        out["bias"] = getattr(getattr(res, "bias", None), "name", None) or \
            getattr(res, "bias", None)
        out["confidence"] = getattr(res, "confidence", None)
        out["evidence"] = list(getattr(res, "evidence", None) or ())
        out["conflict"] = bool((getattr(res, "data", None) or {})
                               .get("conflict"))
    except Exception:
        return {}
    return out


def _gate_needs(gate) -> List[str]:
    """What the gate is waiting on, in its own words.

    Read from the gate's `needs`/`missing` list when it publishes one. It is NOT
    inferred from the state: guessing that a WAIT needs "acceptance" would put a
    condition on screen that no engine ever asked for, and the trader would wait
    for the wrong thing.
    """
    if not isinstance(gate, dict):
        return []
    for key in ("needs", "missing", "blockers"):
        v = gate.get(key)
        if isinstance(v, (list, tuple)):
            return [str(x) for x in v if str(x).strip()]
    return []


def _total_pcr(df_summary) -> Optional[float]:
    """Total PE OI ÷ total CE OI, over the strikes the chain published.

    The chain already carries a PER-STRIKE `PCR` column; this is the aggregate,
    which nothing else publishes. It is a definition rather than a judgement —
    there is no threshold, weighting or interpretation in it — which is why
    summing here does not create a second owner of anything.
    """
    if df_summary is None or getattr(df_summary, "empty", True):
        return None
    try:
        cols = df_summary.columns
        ce = "openInterest_CE" if "openInterest_CE" in cols else "CE_OI"
        pe = "openInterest_PE" if "openInterest_PE" in cols else "PE_OI"
        if ce not in cols or pe not in cols:
            return None
        c = float(df_summary[ce].sum())
        p = float(df_summary[pe].sum())
        return round(p / c, 2) if c > 0 else None
    except Exception:
        return None


# ── 0 · CHARTS ──────────────────────────────────────────────────────────
def _charts_screen(st, fr: Dict[str, Any]) -> None:
    """📊 The price screen — NIFTY ‖ ATM Call ‖ ATM Put, and nothing else.

    Its own tab, first, so the figure sits directly under the price header. On
    the Trading tab it was the fifth block down — Command Center, Stage 71,
    Stage 71.8 and the execution chain all drew above it — which put a 660px
    chart below the fold on a laptop.

    **No price line of its own.** `header_html` renders the LTP, the change and
    both biases above the tab bar on every tab, so a second copy here would be
    the duplication this split exists to remove.

    Deliberately thin: it reads the same two things `_trading_screen` did and
    hands them to the same renderer. `_leg_reads` and `dominance` compute
    nothing — they assemble from caches the app already filled — so calling
    them here instead of there moves no work.
    """
    from ..terminal import dominance

    # ⛶ Make the Fullscreen button visible on every chart below. Once per rerun.
    st.markdown(FS_CHART_CSS, unsafe_allow_html=True)

    call, put, call_tag, put_tag = _leg_reads(st, fr)
    _terminal_chart(st, fr, call_tag, put_tag, dominance(call, put))

    # ⚙️ The high-volume-pivot settings, under the chart they change.
    _hv_settings(st)

    # 🧮 The ATM±1 leg tabulation, directly under the charts it explains.
    #
    # ⚠️ `build_leg_bias_table` has computed these 19 per-signal columns every
    # cycle and NOTHING ever drew them. The rows reached `_leg_bias_cache`, whose
    # consumers — Stage 14, three alert paths, a gate check — all take the
    # VERDICTS and discard the detail, so the trader was told "Leg Fast Verdict:
    # BEARISH" with no way to see which signal voted that way.
    #
    # Read from the published cache, not rebuilt: `_render_main_analyzer` owns the
    # call and re-running it here would be a second set of 6 leg computations per
    # cycle, and two answers to one question.
    try:
        from .leg_table_panel import leg_table_html
        _lt = st.session_state.get("_leg_bias_cache") or (None, None)
        _html = leg_table_html(_lt[0], _lt[1])
        if _html:
            st.markdown(_html, unsafe_allow_html=True)
        else:
            st.caption("🧮 ATM±1 leg tabulation — " + _feed_reason(st)
                       + " It needs the six ATM±1 leg candle series.")
    except Exception as err:
        _dbg_caption(st, "leg_table_panel", f"Leg tabulation unavailable: {err}")

    # 📊 Per-strike Call vs Put OI and ΔOI, ATM±2 — below the tabulation.
    _strike_oi_charts(st)

    # 🏛 The layered POC picture on a daily axis — no candles, POC only.
    _poc_structure(st)


# ── 1 · DECISION ────────────────────────────────────────────────────────
def _run_execution_chain(st) -> None:
    """Stages 72 → 73 → 72.9, run once per cycle from the assembled context.

    Each stage takes the previous one's output and adds one thing:

    * **72** reads the `TradingContext` and nothing else, and returns a frozen
      `EntryDecision` carrying its own id, version, created_at and hash.
    * **73** takes that decision and the same context and returns a lifecycle
      action — it never mints its own id, it carries 72's forward.
    * **72.9** takes both and prepares a dispatch.

    ⚠️ **It sends only when a human has switched sending on.** The transport
    is read from `session_state["_mios_transport"]`, which the app sets *only*
    while the "MIOS V6 Telegram signals" toggle is on. With the toggle off the
    key is absent, the dispatcher receives `None`, builds the payload, decides
    whether it *would* send, and reports `NOT_SENT` — exactly as before.

    Stage 72.9 is still `VALIDATED_SIMULATED` with `freeze_ready: False`: five
    hundred live dispatches have not happened. The toggle is the human decision
    that report asks for, not a replacement for it, and the panel says so.

    The transport is a **callable taken from the app**. This module still
    imports no network client — `import requests` inside `mios_v5` is a named
    forbidden failure mode, and reading a function somebody else built is how
    that rule and a live send coexist.

    A registry is still used, because the claim protocol is what makes the
    dispatch decision meaningful at all: without one, "would this be a
    duplicate?" has no answer. `MemoryRegistry` lasts a session, which is the
    right scope for a stage that sends nothing.

    Advisory throughout, and every stage already promises never to raise — the
    guard here is for the wiring, not for them.
    """
    ctx = st.session_state.get("_trading_context")
    if ctx is None:
        # ⚠️ This used to `return` silently, and it was one of FOUR ways the
        # execution chain could fail to run without saying so. The trader saw
        # an empty space, which reads exactly like "no trade" — the one
        # misreading that makes a working system look broken. Say it instead.
        st.session_state["_entry_decision"] = None
        _render_chain_panel(
            st, "Stage 71.95 did not publish a trading context this cycle, so "
                "Stage 72 had nothing to read. Common causes: the option chain "
                "has not arrived yet, or the strike picker found no ATM ladder.")
        return
    try:
        from ..dispatcher import MemoryRegistry
        from ..dispatcher import run as _dispatch
        from ..entry_engine import run as _entry
        from ..trade_lifecycle import run as _lifecycle

        decision = _entry(ctx)
        st.session_state["_entry_decision"] = decision

        lifecycle = _lifecycle(decision, ctx)
        st.session_state["_lifecycle_decision"] = lifecycle

        # One registry for the session, so a decision already "dispatched" this
        # session is recognised as a duplicate rather than re-prepared.
        registry = st.session_state.get("_dispatch_registry")
        if registry is None:
            registry = MemoryRegistry()
            st.session_state["_dispatch_registry"] = registry

        # Absent unless the human toggle is on → `None` → prepares only.
        transport = st.session_state.get("_mios_transport")
        st.session_state["_dispatch_decision"] = _dispatch(
            decision, ctx, lifecycle=lifecycle, registry=registry,
            transport=transport)
        # The last decision worth keeping on screen while the current read is
        # WAIT. Written only when there IS one, so a quiet cycle cannot erase
        # the morning's signal — a blank panel in a slow market is precisely
        # what makes a working system feel broken.
        from .execution_panel import remember_signal
        _last = remember_signal(decision)
        if _last:
            st.session_state["_last_valid_signal"] = _last
    except Exception as err:
        st.session_state["_entry_decision"] = None
        _render_chain_panel(st, f"The chain raised on this cycle: {err}")
        return

    _render_chain_panel(st)


def _render_chain_panel(st, not_run_reason: str = "") -> None:
    """Draw the execution panel from whatever session state holds.

    Split out so the three failure paths above render the SAME panel the happy
    path does, rather than a bare caption. A caption reading "Strike Validation
    unavailable" while the real casualty was Stage 72 is how this stayed
    invisible.
    """
    try:
        from .execution_panel import render_execution
        render_execution(st, st.session_state.get("_entry_decision"),
                         st.session_state.get("_lifecycle_decision"),
                         st.session_state.get("_dispatch_decision"),
                         last_signal=st.session_state.get("_last_valid_signal"),
                         not_run_reason=not_run_reason)
    except Exception as err:
        _dbg_caption(st, "execution_panel", f"Execution panel unavailable: {err}")


def _decision_center(st, fr: Dict[str, Any]) -> None:
    """Should I trade right now? — answerable in 3-5 seconds.

    Nothing else is allowed to compete here. The checklist, the risk breakdown
    and the V6 voter table all moved to Dashboard 3; this screen carries the
    verdict, the ticket, the two biases and the three questions, and stops.
    """
    from .decision_panel import render_decision_panel
    from .explain_panel import decision_explanation_html
    from ..checklist import build as _build_checklist
    from ..explain_decision import explain as _explain

    # ── 🗓 Stage 68 — what KIND of day this is. First, because every read
    # below has to be interpreted against it: the same rejection at support is
    # a buy on a trend day and a fade on a pin day.
    from .day_type_panel import day_type_card
    from .session_panel import session_card
    st.markdown(day_type_card(fr.get("day_classification")),
                unsafe_allow_html=True)
    # 🕘 Stage 69 — WHERE in the day. A 09:20 breakout is not a 13:00
    # breakout, and the day type alone does not say which one this is.
    st.markdown(session_card(fr.get("session_intel")), unsafe_allow_html=True)

    dec = fr.get("decision_v2") or {}
    render_decision_panel(dec)

    cl = _build_checklist(fr)
    st.markdown(decision_explanation_html(_explain(fr, cl)),
                unsafe_allow_html=True)

    _ticket(st, fr, dec)

    from .bias_compare import bias_compare_html
    from ..v6_bias import compare as _v6_compare
    st.markdown(bias_compare_html(_v6_compare(fr)), unsafe_allow_html=True)

    t = build_thesis(fr)
    c1, c2, c3 = st.columns(3)
    for col, title, items, colour in (
            (c1, "WHY", t["why"], "#7fe8b0"),
            (c2, "EXPECT", t["expect"], "#9fd3ff"),
            (c3, "INVALIDATION", t["invalidation"], "#ffcc66")):
        with col:
            col.markdown(
                f"<div style='{_CARD};min-height:132px'>"
                f"<div style='font-size:10.5px;letter-spacing:.12em;"
                f"color:#cfd9e6;text-transform:uppercase'>{title}</div>"
                + "".join(f"<div style='font-size:12.5px;margin-top:3px;"
                          f"color:{colour}'>• {i}</div>" for i in items)
                + "</div>", unsafe_allow_html=True)


def _ticket(st, fr: Dict[str, Any], dec: Dict[str, Any]) -> None:
    """Market quality · entry · stop · trail · R:R — the trade in six numbers."""
    from ..explain_decision import market_quality
    from ..risk_explain import analyse as _risk
    ra = _risk(fr)
    trail = dec.get("trail") or {}
    rr = (ra.get("rr") or {}) if ra.get("available") else {}
    mq = market_quality(fr)
    cells = [
        ("Market Quality",
         f"{mq['grade']}" + (f" {mq['score']}%" if mq.get("score") is not None
                             else ""), mq["colour"]),
        ("Entry", _fmt(dec.get("entry")), "#00ff88"),
        ("Stop", _fmt(dec.get("stop")), "#ff6666"),
        ("Trail", (_fmt(trail.get("stop")) if trail.get("stop")
                   else (trail.get("mode") or "—")), "#a78bfa"),
        ("Target", (ra.get("target") or {}).get("display", "—")
         if ra.get("available") else "—", "#7fe8b0"),
        ("R:R", rr.get("display", "—"),
         "#00ff88" if rr.get("acceptable") else "#ffd000"),
    ]
    st.markdown(
        "<div style='display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px'>"
        + "".join(
            f"<div style='flex:1;min-width:104px;{_CARD};margin-bottom:0'>"
            f"<div style='font-size:9.5px;letter-spacing:.10em;color:#cfd9e6;"
            f"text-transform:uppercase'>{k}</div>"
            f"<div style='font-size:17px;font-weight:800;color:{c}'>{v}</div>"
            f"</div>" for k, v, c in cells)
        + "</div>", unsafe_allow_html=True)


# ── 2 · TRADING TERMINAL ────────────────────────────────────────────────
def _trading_screen(st, fr: Dict[str, Any], state) -> None:
    """The execution screen — index, ATM call and ATM put evolving together.

    Layout: NIFTY large on the left, the two option legs stacked on the right,
    a CALL-vs-PUT ribbon between them, and the trade banner underneath. This is
    for execution, not analysis: everything here is something you act on, and
    the diagnostics live on Dashboard 3.
    """
    from .day_type_panel import day_type_badge
    from .session_panel import session_strip
    from .terminal_panel import (compare_ribbon_html, intelligence_html,
                                 leg_card_html, market_ribbon_html,
                                 recommendation_html)
    from ..terminal import (compare_ribbon, market_ribbon,
                            option_intelligence, recommendation)

    call, put, call_tag, put_tag = _leg_reads(st, fr)
    cmp_ = compare_ribbon(call, put)
    # `dominance` went with the chart — it was read by nothing else here, and a
    # local nobody uses is how the next reader concludes it must matter.

    # ── the header stack, in the order a trader reads it ──
    # Command Center answers "what is the market doing", Stage 71 answers
    # "where is the opportunity". Everything else moved below (see the note on
    # the context strips further down).
    _command_center(st, fr)

    # ── Stage 71 — the opportunity read, directly above the charts ──
    # A trader opening this tab should read WHERE the opportunity is before
    # looking at price. Everything else that used to sit here (day type,
    # session, market ribbon) has moved BELOW the charts rather than being
    # deleted: four blocks before a 660px chart puts execution below the fold
    # on a laptop, and this screen exists to execute on.
    _opportunity(st, fr)

    # ── Stage 71.8 — is the strike the trader picked worth trading? ──
    # Directly under 71.7, because the two are one question asked twice: 71.7
    # names a side, 71.8 grades the strike on it. Reading the side without the
    # strike grade is how a correct direction gets traded through an illiquid
    # option.
    _strike_validation(st, fr)

    # ── the execution chain · Stages 72 → 73 → 72.9 ────────────────────
    # Called HERE, at the top level, not from inside `_strike_validation`.
    #
    # It used to live in that function's body, and that placement is what made
    # the whole chain invisible. `_strike_validation` returns early when the ATM
    # ladder has not been published, and it wraps ~145 lines in a single
    # `except` — so whenever either fired, Stage 72 never ran, `_entry_decision`
    # was never written, the panel rendered `""`, and the only thing on screen
    # was a caption about the strike picker. Three unrelated failures all
    # presenting as "no signal", none of them saying the execution chain had not
    # run.
    #
    # It reads `_trading_context` out of session state, which `_strike_validation`
    # publishes before it returns, so nothing about the data flow depends on the
    # nesting — only the failure behaviour did. Out here, a strike-picker
    # problem can no longer take the trade verdict down with it.
    _run_execution_chain(st)

    # ── the charts moved to their own tab ─────────────────────────────
    # `_terminal_chart` is now drawn by `_charts_screen`, the FIRST tab, so the
    # figure sits under the price header rather than five blocks down here.
    #
    # ⚠️ It still runs before this function does. Streamlit executes tab bodies
    # in order and Charts is tab 0, so `_leg_profiles` — which only
    # `_terminal_chart` publishes, and which the heatmaps below read — is
    # already written by the time Trading draws. That ordering is what makes the
    # move safe, and it is asserted by
    # `test_the_charts_tab_runs_before_the_panel_that_reads_its_output`.

    # ── the same liquidity bars, per leg ──────────────────────────────
    # The chart draws each leg's profile as a translucent band behind the
    # candles, which shows WHERE the volume sits but cannot be read off. These
    # are the identical bins as bars, so a level can be measured rather than
    # eyeballed through a candle.
    #
    # Kept HERE rather than following the chart to its own tab: the bars are a
    # measuring tool for a level you are about to act on, and this is the tab
    # you act from. They read `_leg_profiles` from session state, so they never
    # needed to be adjacent to the figure — only downstream of it.
    try:
        from .liquidity_panel import render_leg_heatmaps
        render_leg_heatmaps(st, st.session_state.get("_leg_profiles"))
    except Exception as err:
        _dbg_caption(st, "liquidity_panel", f"Premium liquidity unavailable: {err}")

    # ── market facts + the V5 ‖ V6 divergence ──
    # The slim Trade Card: ONLY what this tab does not already own. Bias,
    # quality and timing belong to the Opportunity Matrix (per horizon, which
    # is more than one blended verdict), S/R to `_sr_intelligence` below, and
    # the Stage 52 ladder to the Cockpit. What is left is the measurements
    # every version reads, and the one comparison that matters exactly when
    # the two generations disagree.
    from .trade_card_panel import render_slim_trade_card
    render_slim_trade_card(st, fr, _spot_now(st, fr))

    # context strips, relocated from above the chart — same content, same
    # order, no longer competing with the execution surface for the fold
    st.markdown(day_type_badge(fr.get("day_classification")),
                unsafe_allow_html=True)
    st.markdown(session_strip(fr.get("session_intel")), unsafe_allow_html=True)
    st.markdown(market_ribbon_html(market_ribbon(fr)), unsafe_allow_html=True)

    # the leg reads sit under the charts they describe, in the same order
    lc, rc = st.columns([0.60, 0.40])
    with lc:
        _war_zone(st, fr)
        _price_map(st, fr)
    with rc:
        st.markdown(leg_card_html(call, "ATM CALL"), unsafe_allow_html=True)
        st.markdown(compare_ribbon_html(cmp_), unsafe_allow_html=True)
        st.markdown(leg_card_html(put, "ATM PUT"), unsafe_allow_html=True)

    # ── the execution layer: where in the trade life are we? ──
    # Stage 52 runs the whole ladder every cycle and was shown as one badge.
    # A badge says where you are; a checklist says how far along, what is
    # satisfied, and what is left. Placed under the charts because it is trade
    # MANAGEMENT — you reach it after deciding, not before.
    from .cockpit_panel import render_cockpit
    render_cockpit(st, fr)

    st.markdown(intelligence_html(option_intelligence(fr, call, put)),
                unsafe_allow_html=True)
    st.markdown(recommendation_html(recommendation(fr, call, put)),
                unsafe_allow_html=True)

    st.markdown("---")
    _sr_intelligence(st, fr, state)

    from .narrator_panel import narrator_html
    st.markdown(narrator_html(st.session_state.get("_mios_beats"),
                              title="🎙 Live narration"),
                unsafe_allow_html=True)


def _opportunity(st, fr: Dict[str, Any]) -> None:
    """Stage 71 · 71.5 — the Trade Opportunity Matrix.

    The whole pipeline in one call, and every input arrives as a parameter:

        final_read  ──┐
                      ├─► build_matrix ─► enrich ─► render
        native_reads ─┘

    `_all_bias_rows` is the app's own published signal table — the same rows
    the All-Bias dashboard renders. It is read HERE, in the panel, and passed
    down, because `opportunity.py` may not reach into session_state.

    The previous cycle is kept for Stage 71.5's rotation read. It is stored
    after enrichment so a rotation is always measured against a matrix that
    actually rendered, never against a half-built one.
    """
    try:
        from ..opportunity import build_matrix, native_reads_from_rows
        from ..opportunity import _producer_reads
        from ..opportunity_intel import enrich
        from .opportunity_panel import render_opportunity_panel

        native = native_reads_from_rows(st.session_state.get("_all_bias_rows"))
        matrix = build_matrix(fr, native)
        matrix = enrich(matrix, fr, _producer_reads(fr, native),
                        previous=st.session_state.get("_opportunity_prev"))

        # ⚡ Stage 71.7 — Premium Energy & Spike, folded into Stage 71 rather
        # than sitting in its own section. 71 ranks the horizons and names a
        # side; 71.7 says whether that premium is actually being traded. Split
        # apart, the ranking gets read without the confirmation.
        #
        # `leg_rows` and `leg_totals` are passed in: `premium_energy` may not
        # touch session_state, the same rule this module already follows for
        # `native_reads`. The glyph rows carry DIRECTION; `_atm_leg_ltf_delta`
        # carries the CBV/CSV/CVD volumes the spec makes mandatory, and the two
        # are different questions about the same legs. Stability is read off
        # `matrix` so it is not computed twice.
        premium = None
        try:
            from ..premium_energy import build as _pe_build
            _legs = (st.session_state.get("_leg_bias_cache") or (None, None))[0]
            # `sid_…` duplicates of every leg live in the same store so the
            # render loop can find an entry by either key; summing both would
            # count each leg's volume twice.
            _totals = [(tag, tot) for tag, tot
                       in (st.session_state.get("_atm_leg_ltf_delta") or {}).items()
                       if not str(tag).startswith("sid_")]
            premium = _pe_build(fr, leg_rows=_legs, matrix=matrix,
                                leg_totals=_totals,
                                previous=st.session_state.get("_premium_energy_prev"))
        except Exception as _pe_err:
            _dbg_caption(st, "premium_energy", f"Premium Energy unavailable: {_pe_err}")

        render_opportunity_panel(st, matrix, premium)
        # this cycle's matrix, for Stage 71.95. `_prev` is next cycle's
        # rotation baseline — the same object in two roles, named apart.
        st.session_state["_opportunity_matrix"] = matrix
        st.session_state["_opportunity_prev"] = matrix
        if premium is not None:
            # `_premium_energy` is THIS cycle's, which Stage 71.8 reads.
            # `_premium_energy_prev` is the rotation/shift baseline for the
            # NEXT cycle. One object, two roles, and naming them the same made
            # 71.8 look like it was validating against a stale read.
            st.session_state["_premium_energy"] = premium
            st.session_state["_premium_energy_prev"] = premium
    except Exception as err:
        # advisory panel — it may never take the execution screen down with it
        _dbg_caption(st, "opportunity", f"Trade Opportunity Matrix unavailable: {err}")


def _leg_reads(st, fr: Dict[str, Any]):
    """Assemble both legs from the caches the app already fills.

    Nothing is computed here — Stage 50 supplies the LTP × OI state, the
    leg-bias table supplies the signal tally, the VOB store supplies the zones
    and the leg Entry Gate supplies premium levels when it has armed one.
    """
    from ..terminal import leg_read

    ltp = fr.get("ltp_behaviour") or {}
    rows, _ = (st.session_state.get("_leg_bias_cache") or ([], None))
    setups = st.session_state.get("_entry_armed_setups") or {}
    live = st.session_state.get("_entry_signal_open") or {}
    absorb = fr.get("absorption") or {}

    _, _, call_tag, put_tag = _atm_tags(st)

    def _row(tag):
        return next((r for r in (rows or []) if r.get("Leg") == tag), {})

    def _one(side, tag):
        return leg_read(
            side, tag=tag,
            ltp_side=ltp.get("calls" if side == "CE" else "puts"),
            bias_row=_row(tag),
            vob_zones=_leg_store(st, "_atm_leg_vob_volume", tag),
            setup=setups.get(tag), open_sig=live.get(tag),
            absorption=absorb,
            money_flow=_leg_money_flow(st, tag, _row(tag)))

    return _one("CE", call_tag), _one("PE", put_tag), call_tag, put_tag


def _strike_ladder(st, fr: Dict[str, Any]) -> Tuple[List[float], Optional[float]]:
    """The ATM±3 strikes the picker offers, and the ATM itself.

    Taken from `_cockpit_ctx`, which `_publish_atm_legs` fills with security ids
    for exactly this range. Using the ids rather than the raw chain means the
    picker can only offer strikes the app can actually fetch candles for — a
    dropdown entry with no leg behind it would validate against nothing.
    """
    ctx = st.session_state.get("_cockpit_ctx") or {}
    atm, gap = _num(ctx.get("atm"), None), _num(ctx.get("gap"), None)
    if atm is None:
        return [], None
    step = gap or 50.0
    return [atm + k * step for k in (-3, -2, -1, 0, 1, 2, 3)], atm


def _strike_selection(st, fr: Dict[str, Any]) -> Dict[str, Any]:
    """The trader's chosen CALL and PUT strike, defaulting to ATM.

    Held in `session_state` so it survives every rerun — a picker that reset to
    ATM on each 20-second refresh would be unusable. The ATM itself drifts
    through the day, so a stored strike that has fallen outside the ±3 window is
    dropped back to ATM rather than kept: validating a strike the app no longer
    fetches would report on stale candles.

    ⚪ Not persisted to Supabase. `sql/022_vob_app_state.sql` exists and its
    writer was removed in the V6 reduction, so a selection survives reruns but
    not a restart. Declared rather than half-built.
    """
    ladder, atm = _strike_ladder(st, fr)
    if not ladder:
        return {}
    store = st.session_state.setdefault("_selected_strikes", {})
    picked: Dict[str, Any] = {}
    cols = st.columns([1, 1, 3])
    for col, side in ((cols[0], "CALL"), (cols[1], "PUT")):
        cur = _num(store.get(side), None)
        if cur is None or not any(abs(cur - s) < 0.5 for s in ladder):
            cur = atm
        idx = min(range(len(ladder)), key=lambda i: abs(ladder[i] - cur))
        with col:
            choice = st.selectbox(
                f"{side} strike", ladder, index=idx,
                format_func=lambda v: (f"{v:.0f}" if abs(v - atm) < 0.5
                                       else f"{v:.0f}  ({v - atm:+.0f})"),
                key=f"_strike_pick_{side}")
        store[side] = float(choice)
        picked[side] = float(choice)
    return picked


def _leg_frame(st, tag):
    """The selected leg's own candles, or `None`.

    RVOL and Volume Climax are the only two Premium Structure reads that need a
    raw series — the audit found `avg_vol_1m` computed and discarded in two
    places, and nothing published it.
    """
    dfs = st.session_state.get("_atm_leg_dfs") or {}
    for key in _leg_key_variants(st, tag):
        frame = dfs.get(key)
        if frame is not None and not getattr(frame, "empty", True):
            return frame
    # `_atm_leg_dfs` is keyed by the offset form only, so a caller holding just
    # side and strike reaches it here or not at all — and without the frame
    # there is no LTP, no candles, and therefore no RVOL, no profile, no POC
    # and no break/fakeout probability.
    frame = _leg_suffix_match(dfs, tag)
    if frame is not None and not getattr(frame, "empty", True):
        return frame
    return None


def _leg_reads_for(st, selected: Dict[str, Any]) -> Dict[Any, Dict[str, Any]]:
    """Each selected strike's Premium Structure, keyed `(side, strike)`.

    This function is the *extraction* half of the contract: it pulls finished
    engine output out of session_state and hands it to
    `premium_structure.analyse`, which may touch neither. Stage 71.8 then reads
    the structure rather than deriving one — one owner for the premium's
    structure, which is why Premium Structure exists.

    A wing strike outside the ATM±1 fetch has no leg entry, so its structure
    reports `UNKNOWN` rather than borrowing the ATM's. Substituting a
    neighbour's levels would grade the wrong option with nothing on screen to
    say so.
    """
    from ..premium_structure import analyse as _ps_analyse

    out: Dict[Any, Dict[str, Any]] = {}
    for side, strike in (selected or {}).items():
        s = _num(strike, None)
        if s is None:
            continue
        code = "CE" if side == "CALL" else "PE"
        tag = f"{code} {s:.0f}"
        frame = _leg_frame(st, tag)
        ltp = None
        candles = None
        vpfr = mfp = ignition = None
        if frame is not None:
            try:
                ltp = float(frame["close"].iloc[-1])
                candles = frame.tail(60).to_dict("records")
            except Exception:
                candles = None
            # VPFR is published for ATM±1 only, so a wing strike needs it built
            # here — from the app's own `compute_vpfr`, the one POC owner the
            # audit chose. `premium_structure` receives the result and computes
            # no profile of its own.
            builders = st.session_state.get("_premium_builders") or {}
            for key, target in (("vpfr", "vpfr"), ("mfp", "mfp"),
                                ("ignition", "ignition")):
                fn = builders.get(key)
                if not fn:
                    continue
                try:
                    val = fn(frame)
                except Exception:
                    val = None
                if target == "vpfr":
                    vpfr = val
                elif target == "mfp":
                    mfp = val
                else:
                    ignition = val

        row = next((r for r in ((st.session_state.get("_leg_bias_cache")
                                 or ([], None))[0] or [])
                    if str(r.get("Leg", "")).endswith(f"{code} {s:.0f}")), {})
        absorb = {"🟢": "bull", "🔴": "bear"}.get(
            str(row.get("Absorb") or "").strip()[:1])

        out[(side, s)] = {
            "structure": _ps_analyse(
                sr=_leg_store(st, "_atm_leg_sr_behavior", tag) or {},
                vob=_leg_store(st, "_atm_leg_vob_volume", tag) or [],
                vidya=_leg_store(st, "_atm_leg_vidya", tag) or {},
                flow=_leg_store(st, "_atm_leg_ltf_delta", tag) or {},
                vpfr=vpfr, mfp=mfp, ignition=ignition,
                candles=candles, absorb=absorb, ltp=ltp),
        }
    return out


def _strike_validation(st, fr: Dict[str, Any]) -> None:
    """Stage 71.8 — the strike picker and its validation.

    Every input arrives as a parameter, the rule `opportunity.py` and
    `premium_energy.py` already follow: the panel extracts from session_state,
    the stage interprets. Stage 71.7's finished output is passed straight in so
    71.8 re-derives none of it.
    """
    try:
        from ..strike_validation import build as _sv_build
        from .strike_validation_panel import render_strike_validation

        selected = _strike_selection(st, fr)
        if not selected:
            st.caption("Strike picker unavailable — the ATM ladder has not "
                       "been published yet.")
            return

        summary = ((st.session_state.get("_cached_option_data") or {})
                   .get("df_summary"))
        rows = (summary.to_dict("records")
                if summary is not None and not getattr(summary, "empty", True)
                else [])

        # built once and consumed twice — by the validation below and by the
        # chart overlay. Analysing the same leg in two places would be the
        # duplication Premium Structure exists to end.
        leg_reads = _leg_reads_for(st, selected)

        data = _sv_build(
            fr,
            premium=st.session_state.get("_premium_energy"),
            chain_rows=rows,
            selected=selected,
            leg_reads=leg_reads,
            spot=_spot_now(st, fr))
        render_strike_validation(st, data)
        st.session_state["_strike_validation"] = data

        # Built once and consumed three times — by Stage 71.85 below, by the
        # context, and by the chart overlay.
        _structures = {s: v["structure"]
                       for (s, _k), v in (leg_reads or {}).items()
                       if isinstance(v, dict) and v.get("structure")}

        # ── Stage 71.85 — Premium LTP Behaviour ────────────────────────
        # Runs between 71.8 and the context, which is the only place it can:
        # it consumes the structures built immediately above and its output is
        # a context root. Each side is analysed alone — the call takes one
        # premium and never sees the other.
        try:
            from ..premium_behaviour import build as _pb_build
            _behaviour = _pb_build(
                structure=_structures,
                energy=st.session_state.get("_premium_energy"),
                fr=fr, validation=data)
        except Exception as _pb_err:
            _behaviour = None
            _dbg_caption(st, "premium_behaviour", f"Premium Behaviour unavailable: {_pb_err}")
        st.session_state["_premium_behaviour"] = _behaviour

        # ── Stage 71.95 — the Unified Trading Context ──────────────────
        # Assembled here because this is the last point in the cycle where all
        # six roots exist: `final_read` from the pass, the matrix and 71.7 from
        # `_opportunity`, 71.8 plus the structures from just above, and 71.85
        # from immediately here. Building it earlier would freeze a context
        # missing half its fields.
        #
        # Nothing renders it. It exists so Stage 72 reads one object instead of
        # thirty, and every value in it names the stage that produced it.
        try:
            from ..trading_context import build as _ctx_build
            st.session_state["_trading_context"] = _ctx_build(
                fr=fr, matrix=st.session_state.get("_opportunity_matrix"),
                premium=st.session_state.get("_premium_energy"),
                validation=data,
                structure=_structures,
                behaviour=_behaviour,
                cycle=st.session_state.get("_render_seq"))
        except Exception as _ctx_err:
            st.session_state["_trading_context"] = None
            _dbg_caption(st, "trading_context", f"Trading Context unavailable: {_ctx_err}")
        # the chart overlay reads these; published here so the structure is
        # built once per cycle and consumed by the validation, Stage 71.85 and
        # the chart, rather than analysed three times
        st.session_state["_premium_structures"] = {
            k: v["structure"] for k, v in (leg_reads or {}).items()
            if isinstance(v, dict) and v.get("structure")}
        # Principle 12: `premium.behaviour` is an eleventh weight in Stage 72's
        # entry score, so it moves decisions — and a value that moves decisions
        # must be inspectable somewhere.
        from .premium_behaviour_panel import render_premium_behaviour
        render_premium_behaviour(st, _behaviour)

        # ── Stage 74 — Liquidity Intelligence ──────────────────────────
        # Principle 12 again, and pre-emptively: Stage 74 publishes eight facts
        # nothing else computes, and the moment a stage reads one the rule
        # binds. Rendering it before the stage injection is deliberate — a
        # number nobody has looked at should not become load-bearing in twenty
        # consumers.
        #
        # The context is what a consuming stage would read; the raw profile is
        # passed alongside because the heatmap needs per-bin rows, which the
        # context deliberately does not carry (thirty bins are a chart, not a
        # field).
        from .liquidity_panel import (render_calibration, render_collection,
                                      render_liquidity)
        render_liquidity(st, st.session_state.get("_liquidity_context"),
                         st.session_state.get("_money_flow_data"))

        # Whether telemetry is actually being written. Silent when healthy;
        # loud when the migration is missing, because that failure is otherwise
        # invisible for a week.
        render_collection(st, st.session_state.get("_liq_telemetry_status"))

        # ── Stage 74 calibration verdict ───────────────────────────────
        # A different question from the panel above: that one says what
        # liquidity is doing, this says whether those numbers can be trusted
        # yet. Read from a week of telemetry, and it must stay on screen until
        # the verdict is HEALTHY — injecting Stage 42 on an untested curve is
        # the expensive mistake this whole exercise exists to avoid.
        try:
            from ..liquidity_telemetry import summarise as _liq_summary
            _telemetry = (db.get_liquidity_telemetry(days=7)
                          if db is not None
                          and hasattr(db, "get_liquidity_telemetry") else None)
            if _telemetry:
                render_calibration(st, _liq_summary(_telemetry))
        except Exception:
            pass
    except Exception as err:
        # advisory panel — it may never take the execution screen down with it
        st.caption(f"Strike Validation unavailable: {err}")


def _command_center(st, fr: Dict[str, Any]) -> None:
    """The six header cards, assembled from engines that already ran.

    Each source is fetched independently and guarded: a thesis that fails must
    cost one card, not the whole header. A header that vanishes takes the
    decision off the screen with it.
    """
    from ..command_center import build
    from .command_center_panel import render_command_center

    def _try(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None

    quality = _try(lambda: __import__(
        "mios_v5.explain_decision", fromlist=["market_quality"]
    ).market_quality(fr))
    risk = _try(lambda: __import__(
        "mios_v5.risk_explain", fromlist=["analyse"]).analyse(fr))
    # `fr["families"]` is the family dict (final_read.py:195). `fr["evidence"]`
    # is a LIST of narrative lines — reading "families" off it raised
    # `'list' object has no attribute 'get'` and took the whole Trading tab
    # down, but only once evidence had content. Empty evidence hit the `or {}`
    # and passed, which is why this survived. `order_flow_families` below has
    # always read the right key.
    controller = _try(market_controller, fr.get("families"))
    thesis = _try(build_thesis, fr)

    try:
        cc = build(fr, spot=_spot_now(st, fr), quality=quality, risk=risk,
                   controller=controller, thesis=thesis)
        render_command_center(st, cc)
    except Exception as err:
        _dbg_caption(st, "command_center", f"Command Center unavailable: {err}")


def order_flow_families(st, fr: Optional[Dict[str, Any]] = None
                        ) -> List[Dict[str, Any]]:
    """The Order Flow Family for NIFTY, the ATM Call and the ATM Put.

    Every value is read from a cache V5 already filled. Nothing here computes
    money flow, delta, CVD, CSV, CBV, volume or VOB — those have exactly one
    implementation each, and it is not in V6.
    """
    from ..order_flow import family

    fr = fr or {}
    _, _, ce, pe = _atm_tags(st)

    mf = st.session_state.get("_money_flow_data") or {}
    vd = (st.session_state.get("_volume_delta_data") or {}).get("summary") or {}
    nifty = {
        "money_flow": mf.get("sentiment") or mf.get("top_sentiment"),
        "candle_delta": vd.get("bias") or vd.get("total_delta"),
        "cvd": vd.get("total_delta"),
        "cbv": vd.get("total_buy_volume"),
        "csv": (-_num(vd.get("total_sell_volume"), 0.0)
                if vd.get("total_sell_volume") is not None else None),
        "volume": vd.get("delta_ratio"),
        "vob": (fr.get("ltp_behaviour") or {}).get("vob"),
    }

    out = [{"instrument": "NIFTY", "family": family(nifty)}]
    for label, tag in (("ATM Call", ce), ("ATM Put", pe)):
        out.append({"instrument": label or "ATM leg", "tag": tag,
                    "family": family(_leg_flow_readings(st, tag))})
    return out


def _leg_flow_readings(st, tag) -> Dict[str, Any]:
    """One leg's seven order-flow members, from the leg caches as they stand."""
    if not tag:
        return {}
    row = next((r for r in ((st.session_state.get("_leg_bias_cache")
                             or ([], None))[0] or [])
                if r.get("Leg") == tag), {})
    dv = _leg_store(st, "_atm_leg_ltf_delta", tag) or {}
    zones = _leg_store(st, "_atm_leg_vob_volume", tag) or []

    buy = _num(dv.get("buy_total"), None)
    sell = _num(dv.get("sell_total"), None)
    building = sum(1 for z in zones
                   if str(z.get("status") or "").upper() == "BUILDING")
    fading = sum(1 for z in zones
                 if str(z.get("status") or "").upper() == "FADING")
    return {
        "money_flow": row.get("MFP"),
        "candle_delta": row.get("Div") or _num(dv.get("delta"), None),
        "cvd": row.get("CVD"),
        "cbv": buy,
        # CSV is sell pressure — negated so "more selling" reads bearish
        # rather than the family treating a big positive number as a bid
        "csv": (-sell if sell is not None else None),
        "volume": _num(dv.get("delta_pct"), None),
        "vob": (building - fading) if zones else None,
    }


def _spot_now(st, fr: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """The freshest spot available, live LTP first.

    Ordered the same way the runner orders it, so a level is sided against the
    same price the rest of the screen is quoting.
    """
    for src in (_spot_price(st.session_state),
                (fr or {}).get("spot")):
        v = _num(src, None)
        if v is not None and v > 0:
            return v
    return None


def _leg_key_variants(st, tag) -> List[str]:
    """Every key the same leg is stored under.

    The app writes its per-leg caches under two forms:

      * `"ATM CE 24550"` / `"ATM-1 PE 24500"` — the offset tag plus side and
        strike, which is what `atm_legs()` hands back
      * `"sid_65806"` — the security id, written alongside by most stores

    A caller holding the long form finds the short one by dropping the prefix.
    A caller holding only side and strike — which is all
    `_leg_reads_for` has, because it is given a strike, not a leg — cannot go
    the other way by rebuilding the name, because the prefix depends on where
    the strike sits relative to the ATM and the caller does not know that.
    `_leg_suffix_match` closes that direction.
    """
    if not tag:
        return []
    out = [str(tag)]
    parts = str(tag).split()
    if len(parts) >= 3:
        out.append(" ".join(parts[1:]))          # drop the "ATM±n" prefix
    try:
        entry = (st.session_state.get("_atm_leg_sids") or {}).get(tag)
        sid = entry[0] if isinstance(entry, (list, tuple)) else entry
        if sid:
            out.append(f"sid_{sid}")
    except Exception:
        pass
    return out


def _leg_suffix_match(store: Any, tag) -> Any:
    """The stored leg whose key **ends** with this `SIDE STRIKE`.

    ⚠️ The half of the lookup that was missing, and it emptied the whole of
    Premium Structure.

    Every per-leg store is written under the offset form — `"ATM CE 24550"`.
    `_leg_reads_for` builds its tag from the selected strike alone, so it asks
    for `"CE 24550"`: two tokens, no prefix to drop, and `_atm_leg_sids` is
    keyed by the long form so the `sid_` variant misses too. Every lookup
    returned `None`, so `analyse()` was handed no S/R, no VOB, no VIDYA, no
    flow and no frame — and reported `UNKNOWN` with every field `—` while the
    engines behind it were all producing normally.

    Matching on the last two tokens rather than rebuilding the name is what
    makes this robust: `"ATM"`, `"ATM-3"`, or any prefix a later layout
    introduces resolves without this function knowing the offset scheme. Side
    and strike together identify one contract, so at most one key can match.
    """
    if not tag or not store:
        return None
    parts = str(tag).split()
    if len(parts) < 2:
        return None
    want = tuple(parts[-2:])
    try:
        items = list(store.items())
    except Exception:
        return None
    for key, val in items:
        got = str(key).split()
        if len(got) < 2 or tuple(got[-2:]) != want:
            continue
        # ⚠️ `if not val` would raise here. `_atm_leg_dfs` holds DataFrames, and
        # a DataFrame refuses to answer `bool()` — "The truth value of a
        # DataFrame is ambiguous". Emptiness is asked for by name instead, the
        # same way `_leg_frame` already asks it.
        if val is None or getattr(val, "empty", False):
            continue
        if not hasattr(val, "empty") and not val:
            continue
        return val
    return None


def _leg_store(st, name: str, tag) -> Any:
    """A per-leg cache entry, found under whichever key it was written with."""
    store = st.session_state.get(name) or {}
    for key in _leg_key_variants(st, tag):
        val = store.get(key)
        if val:
            return val
    return _leg_suffix_match(store, tag)


def _leg_levels(st, tag) -> Dict[str, Any]:
    """One leg's own levels, in premium — never spot-derived.

    A stop computed in NIFTY points drawn on a premium series marks a price
    that series can never trade. Everything here comes from the leg's own
    engines: its VWAP, its S/R behaviour level, and the premium the leg Entry
    Gate actually armed, if it armed one.
    """
    if not tag:
        return {}
    out: Dict[str, Any] = {}

    sr = _leg_store(st, "_atm_leg_sr_behavior", tag) or {}
    lvl = _num(sr.get("level"), None)
    if lvl is not None and lvl > 0:
        # the leg's own S/R behaviour level, labelled by which side it is
        out["support" if str(sr.get("side") or "").lower() == "support"
            else "resistance"] = lvl

    # VWAP off the leg frame itself — the same column the leg panel prints
    try:
        frame = (st.session_state.get("_atm_leg_dfs") or {}).get(tag)
        if frame is not None and "vwap" in getattr(frame, "columns", []):
            v = _num(frame["vwap"].iloc[-1], None)
            if v is not None and v > 0:
                out["vwap"] = v
    except Exception:
        pass

    setup = ((st.session_state.get("_entry_armed_setups") or {}).get(tag)
             or (st.session_state.get("_entry_signal_open") or {}).get(tag)
             or {})
    for src, key in ((setup.get("entry"), "entry"), (setup.get("sl"), "stop"),
                     (setup.get("trail"), "trail"),
                     (setup.get("target"), "target")):
        v = _num(src, None)
        if v is not None and v > 0:
            out[key] = v

    # ── Premium Structure overlays, on the chart that already exists ──
    # POC / HVN / LVN and the structure's own support and resistance, drawn on
    # the leg panel by the renderer that already draws the leg's levels. No
    # second chart, and nothing computed here — the values come from
    # `premium_structure.analyse`, which the strike validation pass already ran.
    #
    # Structure levels do not overwrite the S/R behaviour level above: where
    # both exist the behaviour level is the one price is reacting to *now*, and
    # the structure's is where the zone sits.
    for (_side, _strike), read in (st.session_state.get("_premium_structures")
                                   or {}).items():
        if not str(tag).endswith(f"{'CE' if _side == 'CALL' else 'PE'} "
                                 f"{_strike:.0f}"):
            continue
        for key, val in (("poc", (read.get("profile") or {}).get("vp_poc")),
                         ("support", read.get("support")),
                         ("resistance", read.get("resistance"))):
            v = _num(val, None)
            if v is not None and v > 0:
                out.setdefault(key, v)
        # one node each — the strongest HVN and the emptiest LVN. Drawing four
        # of each turns the panel into a ladder and hides the price.
        for key in ("hvn", "lvn"):
            nodes = read.get(key) or []
            v = _num((nodes[0] or {}).get("price"), None) if nodes else None
            if v is not None and v > 0:
                out[key] = v
        break
    return out


def _leg_projected(st, tag, nifty_df, spot_levels) -> Dict[str, Any]:
    """NIFTY's levels read off this leg's own axis — the ⇢ lines.

    The war zone, the gamma flip and the liquidity pool exist only in index
    points, so the terminal has never drawn them on a premium panel and was
    right not to: 24,558 on an axis running ₹60–₹180 is a line at a price the
    series can never trade.

    The question behind the request is still a fair one — *what was this leg
    worth the last time NIFTY was at the war zone?* — and it has a measured
    answer, because all three panels share one timeline. `leg_projection`
    reads it off today's bars. Nothing is priced; a level the session has not
    reached returns nothing and draws nothing.
    """
    if not tag or nifty_df is None or not spot_levels:
        return {}
    try:
        from .leg_projection import project_levels
        leg = (st.session_state.get("_atm_leg_dfs") or {}).get(tag)
        return project_levels(nifty_df, leg, spot_levels)
    except Exception:
        return {}


def _leg_money_flow(st, tag, row: Dict[str, Any]) -> Dict[str, Any]:
    """The leg's money flow, read from what the app already computed.

    `_atm_leg_ltf_delta` is the intrabar buyer/seller split behind the panel's
    own Buy Vol / Sell Vol / Δ Vol tiles — the same cumulative buy and sell
    volume, not a second opinion on it. The MFP column from the leg-bias table
    supplies the direction the profile is leaning.
    """
    dv = _leg_store(st, "_atm_leg_ltf_delta", tag) or {}
    # `None`, not `_num`'s 0.0 default: an absent store must stay absent. A
    # fabricated "Even +0.0%" reads as a measured balance rather than a gap.
    buy = _num(dv.get("buy_total"), None)
    sell = _num(dv.get("sell_total"), None)
    pct = _num(dv.get("delta_pct"), None)
    if buy is None or sell is None:
        return {}

    if pct is None:
        total = buy + sell
        pct = ((buy - sell) / total * 100.0) if total else 0.0
    state = ("entering" if pct >= 5 else "leaving" if pct <= -5 else "flat")
    lean = {"🟢": "bull", "🔴": "bear"}.get(str(row.get("MFP") or "")[:1])
    return {
        "label": (f"{'Buyers' if pct > 0 else 'Sellers' if pct < 0 else 'Even'} "
                  f"{pct:+.1f}%"),
        "state": state,
        "buy_volume": buy, "sell_volume": sell, "delta_pct": round(pct, 1),
        "profile_lean": lean,
    }


def _atm_tags(st):
    from .terminal_chart import atm_legs
    return atm_legs(st.session_state.get("_atm_leg_dfs"))


_ZOOM_KEY = "_terminal_zoom"


def _zoom_controls(st) -> Optional[int]:
    """Expand / contract buttons, returning the minutes of session to show.

    Buttons rather than the scroll wheel: the wheel zoomed the chart whenever
    anyone scrolled the page past it, which is not a thing you can ask for on
    purpose. These are, and the current level is on screen so you always know
    what you are looking at.
    """
    from .terminal_chart import zoom_label, zoom_step

    cur = st.session_state.get(_ZOOM_KEY, None)
    c1, c2, c3, c4 = st.columns([1, 1, 1, 6])
    if c1.button("➖", key="_zoom_out", help="Contract — show more of the day",
                 use_container_width=True):
        cur = zoom_step(cur, -1)
        st.session_state[_ZOOM_KEY] = cur
    if c2.button("➕", key="_zoom_in", help="Expand — zoom in on the last bars",
                 use_container_width=True):
        cur = zoom_step(cur, +1)
        st.session_state[_ZOOM_KEY] = cur
    if c3.button("⟲", key="_zoom_reset", help="Back to the full session",
                 use_container_width=True):
        cur = None
        st.session_state[_ZOOM_KEY] = None
    c4.markdown(
        f"<div style='padding-top:7px;font-size:12px;color:#cfd9e6'>"
        f"🔍 {zoom_label(cur)} — the window is anchored at the newest bar, so "
        f"zooming in keeps live price on screen.</div>",
        unsafe_allow_html=True)
    return cur


def _panel_profile(st, tag, df=None, ready: Optional[Dict[str, Any]] = None):
    """One panel's liquidity & sentiment profile, plus Stage 71.86's shape.

    Each panel gets its **own** profile. The index profile is never projected
    onto a premium panel — audit 71.8 settled that a premium profile is
    computed natively per leg, and an index POC drawn on a premium series marks
    a price that series can never trade.

    `ready` is the profile the app already built (NIFTY's lives in
    `_money_flow_data`). When there is none, one is built here **through the
    existing owner** — `calculate_money_flow_profile`, never a second
    implementation — because the app is what owns the candle series, exactly as
    Stage 45 already works.

    ⚠️ Cached on the bar count. The terminal reruns every ~20 seconds and a
    profile only changes when a bar closes; recomputing 25 bins per leg per
    rerun is the shape of the problem that made egress 0.59 GB/day.
    """
    if not tag:
        return None
    if ready:
        profile = dict(ready)
    else:
        if df is None or getattr(df, "empty", True) or len(df) < 5:
            return None
        cache = st.session_state.setdefault("_panel_profiles", {})
        hit = cache.get(tag)
        if hit and hit.get("_bars") == len(df):
            return hit
        # The app registers `_premium_builders["mfp"]` for exactly this — the
        # money-flow profile of a leg frame. Calling the indicator directly
        # instead would build a SECOND premium profile with different
        # parameters (`source="Volume"` against the builder's "Money Flow"),
        # so the same leg would carry two profiles that disagree. One fact,
        # one owner: use the registered builder and only fall back when the
        # app has not published one.
        builder = (st.session_state.get("_premium_builders") or {}).get("mfp")
        try:
            if builder is not None:
                profile = builder(df) or {}
            else:
                from indicators.money_flow_profile import \
                    calculate_money_flow_profile
                profile = calculate_money_flow_profile(
                    df, num_rows=25, source="Money Flow") or {}
        except Exception:
            return None
        if not profile:
            return None
        profile = dict(profile)
        profile["_bars"] = len(df)

    try:
        from ..profile_shape import run as _shape
        profile["shape"] = _shape(profile.get("rows") or (),
                                  poc=profile.get("poc_price"),
                                  vah=profile.get("value_area_high"),
                                  val=profile.get("value_area_low"),
                                  source=str(tag))
    except Exception:
        pass

    # 📈 The dynamic PoC for THIS panel, on this panel's own series.
    #
    # ⚠️ `profile_overlay` has drawn `dynamic_poc` since it was written and nothing
    # ever set the key, so the line has never appeared — on NIFTY or on either leg.
    # Set here, through the `_premium_builders` bridge the app publishes, because
    # `mios_v5` may not import the app and `compute_dynamic_poc` must stay the one
    # implementation.
    #
    # Per panel, never copied across: an index PoC on a premium axis marks a price
    # that leg cannot trade — the same rule the money-flow profile above follows.
    if df is not None and not getattr(df, "empty", True) and len(df) >= 3:
        try:
            _dyn = (st.session_state.get("_premium_builders") or {}).get(
                "dynamic_poc")
            if _dyn is not None:
                _line = _dyn(df)
                # A list of None is not a PoC — leave the keys absent so the
                # overlay draws nothing rather than an empty trace.
                if _line and any(v is not None for v in _line):
                    # ⚠️ TWO keys, because they are two different reads and the
                    # existing branch wanted the first one. `profile_overlay.levels`
                    # runs `_f()` over `dynamic_poc`, and `_f(a_list)` is None — so
                    # even had anything set the key, handing it the series would have
                    # drawn nothing. The scalar is the current level it labels; the
                    # series is the curve that makes it DYNAMIC, which is the whole
                    # point of the indicator.
                    profile["dynamic_poc"] = next(
                        (v for v in reversed(_line) if v is not None), None)
                    profile["dynamic_poc_series"] = _line
        except Exception:
            pass
        # 📍 High-volume pivots for this panel, on this panel's own volume
        # distribution — see `_hv_points`.
        try:
            _hv = (st.session_state.get("_premium_builders") or {}).get(
                "hv_points")
            if _hv is not None:
                _pts = _hv(df)
                if _pts:
                    profile["hv_points"] = _pts
                else:
                    # ⚠️ The REASON, not just the absence. A strongly trending leg has
                    # no swing pivots at all, which is exactly what a put looks like
                    # while the index falls — and an empty panel is indistinguishable
                    # from a broken one.
                    from ..volume_points import read as _hvread
                    profile["hv_why"] = _hvread([]).get("why")
        except Exception:
            pass

    if not ready:
        st.session_state.setdefault("_panel_profiles", {})[tag] = profile
    return profile


def _terminal_chart(st, fr: Dict[str, Any], call_tag, put_tag, dom) -> None:
    """NIFTY ‖ ATM Call ‖ ATM Put — three figures, each with its own Fullscreen
    button, kept on one shared timeline and one zoom window so they still line
    up. The trade a per-chart fullscreen makes is the live cross-panel
    crosshair, which only a single figure can carry."""
    from .terminal_chart import atm_legs, terminal_charts_split

    from ..runner import nifty_frame
    nifty, nifty_src = nifty_frame(st.session_state)
    call_df, put_df, ce, pe = atm_legs(st.session_state.get("_atm_leg_dfs"))
    if nifty is None and call_df is None and put_df is None:
        st.caption("Candle data warming up — the terminal draws once the "
                   "1-minute series and the ATM legs have loaded.")
        return

    dec = fr.get("decision_v2") or {}
    mf = st.session_state.get("_money_flow_data") or {}
    mp = st.session_state.get("_market_picture") or {}
    bz = fr.get("battle_zone") or {}
    pools = (mp.get("liq_pools") or {})
    liq = None
    for side in ("above", "below"):
        lst = pools.get(side) or []
        if lst:
            liq = _num((lst[0] or {}).get("price") if isinstance(lst[0], dict)
                       else lst[0]) or None
            break

    levels = {
        "entry": dec.get("entry"), "stop": dec.get("stop"),
        "trail": (dec.get("trail") or {}).get("stop"),
        "target": fr.get("next_target"),
        "support": fr.get("strong_support"),
        "resistance": fr.get("strong_resistance"),
        "war_zone": bz.get("price"), "liquidity": liq,
        "vwap": mp.get("vwap"), "poc": mf.get("poc_price"),
        "vah": mf.get("value_area_high"), "val": mf.get("value_area_low"),
    }
    # ── dealer hedging + the reaction price ──
    # Stage 11 computes gamma flip and the magnet wall every cycle, and Stage
    # 42 knows the price its verdict happened at. All three now arrive on
    # `final_read`, so the chart takes them as inputs rather than reaching for
    # them (principle 4) and the trader can see the levels that are moving the
    # decision (principle 12).
    levels.update(fr.get("dealer_levels") or {})
    levels["reaction"] = fr.get("reaction_level")
    # the expiry-day magnet, from the one shared rule the Trade Card uses
    try:
        from ..charm_pin import from_market_picture as _cpin
        _pin = _cpin(bool(fr.get("is_expiry")), _spot_now(st, fr), mp,
                     (st.session_state.get("_cached_option_data")
                      or {}).get("max_pain_strike"))
        levels["charm_pin"] = (_pin or {}).get("pin")
    except Exception:
        pass
    htf = (fr.get("htf") or {}).get("levels") or {}

    window = _zoom_controls(st)

    # Built once, used twice — by the chart's band overlay and by the liquidity
    # bars rendered underneath it. Building them here rather than again in the
    # panel is the same rule Stage 71.8 settled for the leg reads: one profile
    # per leg, one owner, two readers.
    _nifty_prof = _panel_profile(st, "NIFTY", nifty, mf)
    _call_prof = _panel_profile(st, ce, call_df)
    _put_prof = _panel_profile(st, pe, put_df)
    # Published for the bars below. Same cycle, so no lag — the panel reads what
    # this chart just drew, not last pass's copy.
    st.session_state["_leg_profiles"] = {
        "NIFTY": _nifty_prof, "CALL": _call_prof, "PUT": _put_prof,
        "call_label": ce, "put_label": pe}

    # ── ⇢ the index's levels, read off each leg's own axis ──
    # Requested so the LTP panels carry the same picture as NIFTY. They are not
    # copied across — a spot number on a premium axis is meaningless — but
    # measured: what the leg actually traded at the last few times NIFTY was
    # near each level. Levels the session has not reached simply do not appear.
    _call_levels = _leg_levels(st, ce)
    _put_levels = _leg_levels(st, pe)
    _call_proj = _leg_projected(st, ce, nifty, levels)
    _put_proj = _leg_projected(st, pe, nifty, levels)
    _call_levels.update(_call_proj)
    _put_levels.update(_put_proj)

    try:
        # ⛶ Three figures, not one — so each chart carries its OWN Streamlit
        # Fullscreen button and NIFTY, Call and Put can each be enlarged alone.
        # They are still reindexed onto one timeline and pinned to one zoom
        # window inside `terminal_charts_split`, so they line up; what a split
        # gives up is the live cross-panel crosshair, which a single figure is
        # the only way to keep.
        figs, notes = terminal_charts_split(
            nifty, call_df, put_df, levels, htf_levels=htf,
            call_label=ce or "ATM Call", put_label=pe or "ATM Put",
            tint=dom.get("tint"), dominance=dom.get("side", "neutral"),
            signal=dec, window_minutes=window,
            call_levels=_call_levels, put_levels=_put_levels,
            call_zones=_leg_store(st, "_atm_leg_vob_volume", ce),
            put_zones=_leg_store(st, "_atm_leg_vob_volume", pe),
            nifty_profile=_nifty_prof,
            call_profile=_call_prof,
            put_profile=_put_prof,
            price_action=bool(st.session_state.get("_apa_on", False)))
        # NIFTY wide on the left, the two legs stacked on the right — the same
        # 60/40 proportions the combined terminal used, so the page still reads
        # as the terminal it replaces. Each `plotly_chart` gets the shared
        # config (a modebar stripped to the one Fullscreen button) and its own
        # key, so Streamlit gives each its own fullscreen frame.
        _left, _right = st.columns([0.6, 0.4], gap="small")
        with _left:
            if figs.get("NIFTY") is not None:
                st.plotly_chart(figs["NIFTY"], use_container_width=True,
                                key="terminal_nifty", config=FS_CHART_CONFIG)
        with _right:
            if figs.get("CALL") is not None:
                st.plotly_chart(figs["CALL"], use_container_width=True,
                                key="terminal_call", config=FS_CHART_CONFIG)
            if figs.get("PUT") is not None:
                st.plotly_chart(figs["PUT"], use_container_width=True,
                                key="terminal_put", config=FS_CHART_CONFIG)
        # 📐 Geometric patterns as a TABLE below the charts (not drawn on them),
        # each with its bias — only when the Advanced Price Action toggle is on.
        if st.session_state.get("_apa_on", False):
            try:
                from .price_action_table import build_table as _pa_table
                _pah = _pa_table(nifty, call_df, put_df)
                if _pah:
                    st.markdown(_pah, unsafe_allow_html=True)
            except Exception:
                pass
        if notes:
            # name the series AND why — "No candle series yet for: NIFTY" on a
            # screen where the two option legs drew fine tells you nothing
            # about where to look
            why = []
            if "NIFTY" in notes:
                why.append(nifty_src)
            if ce and ce in notes or pe and pe in notes:
                why.append("ATM leg frames come from `_atm_leg_dfs`, filled "
                           "by the ATM±3 leg fetch")
            st.caption("No candle series yet for: " + ", ".join(notes)
                       + (" — " + "; ".join(x for x in why if x) if why else ""))
        st.caption(
            "⛶ **Each chart has its own Fullscreen button** — click it to "
            "enlarge NIFTY, Call or Put on its own. All three share one clock "
            "and one zoom window, so 10:48 is 10:48 on every panel and the ➕/➖ "
            "buttons move each to the same span; hovering one no longer lights "
            "the others, which is the trade a per-chart fullscreen makes.  \n"
            "🟢🔴 **Option bar colour is who was buying that minute**; bar "
            "height is still volume. The violet line is CVD — rising means "
            "buyers are still adding, falling means they have stopped. Its "
            "shape is the signal; it is scaled into the panel, so its height "
            "carries no price meaning.")
        # Principle 12: a line a trader reads the panel by has to say where its
        # number came from. Silent when nothing projected — a legend for lines
        # that are not on the chart is noise.
        try:
            from .leg_projection import caption as _proj_caption
            _line = _proj_caption({**_call_proj, **_put_proj})
            if _line:
                st.caption(_line)
        except Exception:
            pass
    except Exception as err:
        _dbg_caption(st, "terminal_chart", f"Terminal chart unavailable: {err}")


def _war_zone(st, fr: Dict[str, Any]) -> None:
    """Delegated to `war_zone.py`.

    The markup used to live here, and the observational card above the app
    needs the same fight in one line. Copying it would have given one fight two
    wordings that drift apart; lifting it out gives both renderings one owner
    and one source for `battle_zone`, `expected_winner` and `probabilities`.
    """
    from .war_zone import render as _render
    _render(st, fr)


def _price_map(st, fr: Dict[str, Any]) -> None:
    """Every level the chart drew, as numbers — including the HTF POCs the
    confluence score is computed against."""
    dec = fr.get("decision_v2") or {}
    trail = dec.get("trail") or {}
    mf = st.session_state.get("_money_flow_data") or {}
    rows: List[Any] = []
    for lbl, price, colr in (
            ("Entry (proven)", dec.get("entry"), "#00ff88"),
            ("Stop", dec.get("stop"), "#ff4444"),
            ("Trail", trail.get("stop"), "#a78bfa"),
            ("Target", fr.get("next_target"), "#7fe8b0"),
            ("Support", fr.get("strong_support"), "#17c98b"),
            ("Resistance", fr.get("strong_resistance"), "#ff8c8c"),
            ("VAH", mf.get("value_area_high"), "#7dffb0"),
            ("POC", mf.get("poc_price"), "#ffe066"),
            ("VAL", mf.get("value_area_low"), "#ff8c8c")):
        if price:
            rows.append((lbl, price, colr))
    for lbl, price in sorted((fr.get("htf") or {}).get("levels", {}).items(),
                             key=lambda kv: -_num(kv[1]))[:10]:
        rows.append((lbl, price, "#cfd9e6"))

    st.markdown("**📍 Price map**")
    if not rows:
        st.caption("Levels warming up.")
        return
    st.markdown("".join(
        f"<div style='display:flex;justify-content:space-between;"
        f"font-size:12.5px;padding:2px 0;border-bottom:1px solid #161b22'>"
        f"<span style='color:{c}'>{l}</span>"
        f"<span style='color:#ffffff;font-weight:700'>{_num(p):,.0f}</span>"
        f"</div>" for l, p, c in rows), unsafe_allow_html=True)


def _sr_intelligence(st, fr: Dict[str, Any], state) -> None:
    """Each S/R level as an intelligent object, ranked."""
    from .sr_panel import render_sr_panel

    try:
        rsr = st.session_state.get("_reaction_sr") or {}
    except Exception:
        rsr = {}
    dec = fr.get("decision_v2") or {}
    ab = fr.get("absorption") or {}
    tr = fr.get("transition") or {}
    react_all = {}
    try:
        _ac = state.get("stage42_acceptance")
        if _ac is not None and _ac.ok and _ac.data:
            react_all = {"SUPPORT": _ac.data.get("support") or {},
                         "RESISTANCE": _ac.data.get("resistance") or {}}
    except Exception:
        react_all = {}

    # the next target the Reaction-Zone engine already computed
    tgt, tgt_lbl = fr.get("next_target"), None
    if tgt:
        for lbl, price in ((fr.get("htf") or {}).get("levels") or {}).items():
            try:
                if abs(float(price) - float(tgt)) <= max(8.0, float(tgt) * 0.0004):
                    tgt_lbl = lbl
                    break
            except (TypeError, ValueError):
                continue

    # ── the three states this panel can be in, told apart. They used to look
    # identical on screen ("still warming up"), so a real failure was
    # indistinguishable from a cold start and stayed there indefinitely.
    from ..sr_intel import card_from_zone
    levels, unenriched = [], 0
    for key, side in (("support", "SUPPORT"), ("resistance", "RESISTANCE")):
        z = rsr.get(key) or {}
        card = z.get("intel")
        if not card:
            # enrichment missing or failed — a level with a price and a
            # strength is still worth seeing
            card = card_from_zone(z, side)
            if card:
                unenriched += 1
        if not card:
            continue
        mem = {}
        try:
            mem = (st.session_state.get("_zone_memory") or {})
            mem = next((v for k, v in mem.items() if k.startswith(key)), {})
        except Exception:
            mem = {}
        levels.append(build_level_intel(
            card, reaction=react_all.get(side), absorption=ab, transition=tr,
            decision=dec, next_target=tgt, target_label=tgt_lbl,
            age_min=(float(mem.get("age", 0)) if mem.get("age") else None),
            # so a level the market has crossed is re-sided rather than kept
            # under the name it was given when it formed
            spot=_spot_now(st, fr)))

    if not levels:
        st.markdown(_sr_status(st, rsr), unsafe_allow_html=True)
        return

    _ranked = rank_levels(levels)
    # Published so the Telegram signal reads the SAME assembled levels the
    # panel draws — a second assembly here would be a second owner, and the
    # message and the screen could then disagree about the same level.
    st.session_state["_sr_levels"] = _ranked
    render_sr_panel(_ranked)
    if unenriched:
        st.caption(f"⚠️ {unenriched} level(s) shown WITHOUT Zone Intelligence — "
                   f"price and strength only. `enrich_zone_intel` did not "
                   f"attach a card; the origin ★, lifecycle, health and "
                   f"probabilities are missing, not zero."
                   + (f" Last error: {st.session_state.get('_reaction_sr_error')}"
                      if st.session_state.get("_reaction_sr_error") else ""))


def _sr_status(st, rsr: Dict[str, Any]) -> str:
    """Why there are no levels — never just "warming up".

    The canonical object is written near the END of the analyser pass, after
    this dashboard renders, so the FIRST pass legitimately has nothing. Every
    pass after that, silence means something failed.
    """
    err = st.session_state.get("_reaction_sr_error")
    ts = st.session_state.get("_reaction_sr_ts")
    age = None
    if ts:
        try:
            import time as _t
            age = int(_t.time() - float(ts))
        except Exception:
            age = None

    if err:
        body = (f"<b style='color:#ff9d9d'>Reaction-Zone build failed.</b><br>"
                f"<code style='color:#ffd9a0'>{err}</code><br>"
                f"<span style='color:#cfd9e6'>This is an error, not a warm-up "
                f"— it will not clear on its own.</span>")
    elif rsr:
        body = ("<b style='color:#ffcc33'>The canonical S/R object exists but "
                "carries no priced level.</b><br>"
                "<span style='color:#cfd9e6'>`build_reaction_sr` found no "
                "support or resistance in the confluence clusters — usually "
                "spot sitting outside every scored zone.</span>")
    elif age is not None:
        body = (f"<b style='color:#ffcc33'>No S/R written for {age}s.</b><br>"
                f"<span style='color:#cfd9e6'>The last successful build was "
                f"{age}s ago; the analyser pass may be exiting before it "
                f"reaches the zone step.</span>")
    else:
        body = ("<b style='color:#cfd9e6'>Waiting for the first "
                "Reaction-Zone build.</b><br>"
                "<span style='color:#b3c2d4'>It is written near the end of the "
                "analyser pass, so the first render always precedes it. If "
                "this persists past one refresh, the zone step is not "
                "running.</span>")
    return (f"<div style='{_CARD};border-left:3px solid #ff9500'>"
            f"<div style='font-size:12.5px;color:#edf3f9;line-height:1.6'>"
            f"{body}</div></div>")


# ── 3 · INTELLIGENCE (the engine room) ──────────────────────────────────
#: group → the engine sections it owns. Grouping beats a flat list because a
#: trader debugging a bearish read wants "what do the institutions say",
#: not the twenty-third row of an alphabetical table.
_GROUPS = (
    ("🏗 Market Structure", ("regime", "patterns")),
    ("🏛 Institutions", ("dealer", "flows", "intent")),
    ("📊 Options", ("options", "vix")),
    ("⚡ Order Flow", ("orderflow", "liquidity")),
    ("✅ Validation", ("sector",)),
)

_BIAS_COLOUR = {"STRONG_BULL": "#00ff88", "BULL": "#17c98b",
                "NEUTRAL": "#cfd9e6", "BEAR": "#ff6666",
                "STRONG_BEAR": "#ff4444", "NONE": "#9fb0c4"}


def _intelligence(st, fr: Dict[str, Any], state) -> None:
    """Why does MIOS think that? — grouped, collapsible, deliberately dense."""
    from .debug_gate import enabled
    from .explain_panel import checklist_html, risk_html
    from ..checklist import build as _build_checklist
    from ..risk_explain import analyse as _risk

    ctl = market_controller(fr.get("families"))
    st.markdown(f"**🎮 Market controller:** {ctl.get('label', '—')} "
                f"<span style='color:#cfd9e6;font-size:12px'>"
                f"{ctl.get('reason', '')}</span>", unsafe_allow_html=True)

    _evo = state.get("stage29_evolution")
    changes = recent_changes(
        fr, (_evo.data.get("changes") if _evo is not None and _evo.data else None))
    st.markdown("**🔄 Recent changes** "
                "<span style='color:#b3c2d4;font-size:11px'>(only what moved)"
                "</span>", unsafe_allow_html=True)
    if changes:
        st.markdown("".join(f"<div style='font-size:12.5px;color:#edf3f9'>"
                            f"• {c}</div>" for c in changes),
                    unsafe_allow_html=True)
    else:
        st.caption("Nothing has changed materially this cycle.")

    with st.expander("🕘 Session Intelligence — measures · modifiers",
                     expanded=enabled(st)):
        from .session_panel import modifier_table, session_card
        si = fr.get("session_intel") or {}
        st.markdown(session_card(si), unsafe_allow_html=True)
        st.markdown(modifier_table(si), unsafe_allow_html=True)

    with st.expander("🗓 Day Classification — groups · evidence · transitions",
                     expanded=enabled(st)):
        from .day_type_panel import day_type_detail, day_type_timeline
        from ..day_type import timeline as _dt_timeline
        dc = fr.get("day_classification") or {}
        st.markdown(day_type_detail(dc), unsafe_allow_html=True)
        st.markdown(day_type_timeline(_dt_timeline(dc.get("memory"))),
                    unsafe_allow_html=True)

    with st.expander("🏗 Market Structure — state · transition · memory",
                     expanded=enabled(st)):
        from .memory_panel import memory_panel_html
        from .state_panel import state_line
        from .transition_panel import render_transition_panel
        ms = fr.get("market_state") or {}
        if ms:
            st.markdown(state_line(ms), unsafe_allow_html=True)
        render_transition_panel(fr.get("transition"))
        st.markdown(memory_panel_html(fr.get("memory")), unsafe_allow_html=True)
        _sections(st, ("regime", "patterns"), fr)

    with st.expander("🏛 Institutions — dealer · FII/DII · absorption · flow",
                     expanded=False):
        from .absorption_panel import absorption_panel_html
        st.markdown(absorption_panel_html(fr.get("absorption")),
                    unsafe_allow_html=True)
        _flow_shift(st, fr)
        _sections(st, ("dealer", "flows", "intent"), fr)

    with st.expander("📊 Options — OI · gamma · charm · vanna · PCR · VIX",
                     expanded=False):
        _sections(st, ("options", "vix"), fr)
        st.caption("Per-strike OI, gamma and vanna/charm exposure charts live "
                   "on the main app page — this is the engine's read of them.")

    with st.expander("⚡ Order Flow — CVD · money flow · delta · VOB · liquidity",
                     expanded=False):
        from .ltp_panel import ltp_panel_html
        st.markdown(ltp_panel_html(fr.get("ltp_behaviour")),
                    unsafe_allow_html=True)
        _sections(st, ("orderflow", "liquidity"), fr)

    with st.expander("✅ Validation — acceptance · validity · evidence · energy",
                     expanded=enabled(st)):
        from .energy_panel import energy_panel_html
        from .family_panel import render_family_panel
        from .validity_panel import validity_panel_html
        from .zone_card import reaction_line
        st.markdown(reaction_line(fr.get("reaction")), unsafe_allow_html=True)
        st.markdown(validity_panel_html({**(fr.get("validity_both") or {}),
                                         "active": fr.get("validity")}),
                    unsafe_allow_html=True)
        st.markdown(energy_panel_html(fr.get("energy_read")),
                    unsafe_allow_html=True)
        # Stage 71.7 (Premium Energy) used to render here, below Market Energy.
        # It now lives inside the Stage 71 panel on the Trading tab, because the
        # horizon ranking and the premium confirmation have to be read together.
        # Rendering it in both places would give the workstation two copies of
        # the same numbers — the drift the Stage 71 stack exists to prevent.
        ev = state.get("stage53_evidence")
        if ev is not None and ev.ok:
            render_family_panel(ev.data)
        _sections(st, ("sector",), fr)

    with st.expander("🧬 Decision diagnostics — checklist · risk · V6 voters",
                     expanded=False):
        cl = _build_checklist(fr)
        st.markdown(checklist_html(cl), unsafe_allow_html=True)
        st.markdown(risk_html(_risk(fr)), unsafe_allow_html=True)
        from .bias_compare import v6_detail_html
        from ..v6_bias import compute as _v6
        st.markdown(v6_detail_html(_v6(fr)), unsafe_allow_html=True)


def _sections(st, keys, fr: Dict[str, Any]) -> None:
    """Raw engine sections — bias · confidence · status · headline."""
    rows = [(k, section(fr, k)) for k in keys]
    rows = [(k, s) for k, s in rows if s]
    if not rows:
        return
    st.markdown("".join(
        f"<div style='display:flex;gap:8px;align-items:baseline;"
        f"font-size:12px;padding:2px 0;border-bottom:1px solid #161b22'>"
        f"<span style='width:96px;color:#cfd9e6'>{k.title()}</span>"
        f"<span style='width:88px;font-weight:800;"
        f"color:{_BIAS_COLOUR.get(str(s.get('bias', '')).upper(), '#cfd9e6')}'>"
        f"{s.get('bias', '—')}</span>"
        f"<span style='width:44px;color:#edf3f9'>{_num(s.get('confidence')):.0f}%"
        f"</span>"
        f"<span style='width:66px;font-size:10px;color:#9fb0c4'>"
        f"{s.get('status', '')}</span>"
        f"<span style='flex:1;min-width:0;color:#cfd9e6;overflow:hidden;"
        f"text-overflow:ellipsis;white-space:nowrap'>{s.get('headline', '')}"
        f"</span></div>" for k, s in rows), unsafe_allow_html=True)


def _flow_shift(st, fr: Dict[str, Any]) -> None:
    fs = fr.get("flow_shift") or {}
    if not fs:
        return
    col = "#ff9500" if fs.get("freeze_entries") else "#cfd9e6"
    st.markdown(f"<div style='font-size:12.5px;color:{col}'>"
                f"🌊 <b>Flow</b> {fr.get('stability', '—')} · "
                f"score {_num(fs.get('score')):.0f}% · "
                f"{fs.get('reason', 'no shift detected')}</div>",
                unsafe_allow_html=True)


# ── 4 · HISTORY (case studies) ──────────────────────────────────────────
def _history(st, db) -> None:
    """What happened, and why? — every trade as a case study."""
    if db is None:
        st.caption("No database connection.")
        return
    try:
        df = db.get_trade_signals(limit=TRADE_SIGNAL_LIMIT)
    except Exception:
        df = None
    if df is None or getattr(df, "empty", True):
        st.caption("No signals recorded yet — run sql/026_trade_signals.sql and "
                   "let the Decision Engine generate A/A+ setups.")
        return

    cols = [c for c in ["signal_id", "trading_day", "side", "quality", "status",
                        "entry_price", "entered_price", "exit_price",
                        "pnl_points", "rr", "outcome", "confidence"]
            if c in df.columns]
    st.dataframe(df[cols] if cols else df, use_container_width=True,
                 hide_index=True)

    if not hasattr(db, "get_trade_results"):
        return
    try:
        # Shared limits, sliced to what this panel shows — see the constants.
        res = db.get_trade_results(limit=TRADE_RESULT_LIMIT)[:40]
        att = db.get_trade_attribution(limit=TRADE_ATTRIBUTION_LIMIT)[:40]
        eng = db.get_engine_attribution(limit=ENGINE_ATTRIBUTION_LIMIT)[:2000]
        evs = db.get_trade_events(limit=TRADE_EVENT_LIMIT)[:1000]
    except Exception:
        res = att = eng = evs = None

    from .review_panel import review_html, review_list_html
    from ..trade_review import review_many
    reviews = review_many(att, res, eng, evs, limit=20)
    if not reviews:
        st.caption("No graded trades to review yet — Stage 66 needs "
                   "`sql/027_learning.sql` and a closed trade.")
        return

    st.markdown("---")
    ids = [r["signal_id"] for r in reviews]
    picked = st.selectbox("Case study", ids, index=0, key="_v6_case_study")
    rev = next((r for r in reviews if r["signal_id"] == picked), reviews[0])
    trade = next((t for t in (att or [])
                  if str(t.get("signal_id")) == str(picked)), {})

    st.markdown(review_html(rev), unsafe_allow_html=True)
    _case_context(st, trade, rev)

    if st.button("⏪ Replay this trade", key="_v6_replay_btn"):
        st.session_state["_v6_replay_signal"] = picked
        st.session_state["_v6_replay_day"] = trade.get("trading_day")
        st.info(f"Loaded {picked} — open the ⏪ Replay tab to step through it.")

    st.markdown(review_list_html([r for r in reviews
                                  if r["signal_id"] != picked]),
                unsafe_allow_html=True)


def _case_context(st, trade: Dict[str, Any], rev: Dict[str, Any]) -> None:
    """Market state at entry vs at exit, the AI thesis, and the raw engine
    snapshot — the three things that turn a row into a case study."""
    if not trade:
        return
    at_entry = [("Market state", trade.get("market_state")),
                ("Bias", trade.get("market_bias")),
                ("Acceptance", trade.get("acceptance")),
                ("Absorption", trade.get("absorption")),
                ("Dealer", trade.get("dealer_state")),
                ("Flow", trade.get("flow_shift")),
                ("HTF", trade.get("htf_alignment")),
                ("Controller", trade.get("market_controller"))]
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<div style='font-size:12px;font-weight:800;color:#ffffff;"
        f"margin-bottom:3px'>📌 Market state at ENTRY</div>"
        + "".join(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
            f"<span style='width:104px;color:#cfd9e6'>{k}</span>"
            f"<span style='color:#edf3f9'>{v or '—'}</span></div>"
            for k, v in at_entry)
        + f"<div style='margin-top:6px;font-size:12px;font-weight:800;"
          f"color:#ffffff'>📌 At EXIT</div>"
          f"<div style='font-size:12px;color:#edf3f9'>"
          f"{rev.get('exit_reason', '—')} · quality "
          f"{rev.get('trade_quality', '—')} · {rev.get('evolution', '')}</div>"
        + (f"<div style='margin-top:6px;font-size:12px;color:#9fd3ff'>"
           f"🤖 {trade.get('ai_thesis')}</div>" if trade.get("ai_thesis") else "")
        + "</div>", unsafe_allow_html=True)

    with st.expander("🔬 Engine snapshot at signal time", expanded=False):
        st.json(trade.get("snapshot") or trade.get("decision_reason") or {})

    st.caption("Entry/exit **screenshots are not captured** — no screenshot "
               "infrastructure exists in this app, and a fabricated one would "
               "be worse than none. The engine snapshot plus the replay "
               "timeline are the audit trail instead.")


# ── 5 · LEARNING (analytics centre) ─────────────────────────────────────
def _learning(st, db, fr: Optional[Dict[str, Any]] = None) -> None:
    """Is MIOS actually any good? — four sections, in order of usefulness."""
    _daily_summary(st, db, fr or {})

    if db is None or not hasattr(db, "get_engine_attribution"):
        st.info("Learning tables not available on this DB client.", icon="ℹ️")
        return
    try:
        eng = db.get_engine_attribution(limit=ENGINE_ATTRIBUTION_LIMIT)
        res = db.get_trade_results(limit=TRADE_RESULT_LIMIT)
        att = db.get_trade_attribution(limit=TRADE_ATTRIBUTION_LIMIT)
        evs = db.get_trade_events(limit=TRADE_EVENT_LIMIT)
    except Exception:
        eng = res = att = evs = None

    if not eng or not res:
        st.warning(
            "No per-engine attribution rows yet — the Learning Engine has "
            "nothing to measure.\n\n"
            "Run **`sql/027_learning.sql`** in Supabase, then let the app take "
            "graded trades. Every signal writes one `trade_attribution` row, "
            "one `engine_attribution` row per engine, an append-only "
            "`trade_events` trail, and one `trade_results` row at exit.\n\n"
            "I'd rather say this than show invented numbers.", icon="⚠️")
        return

    from .learning_panel import (accuracy_html, calibration_html,
                                 contribution_html, false_signal_html,
                                 governance_html, overall_html,
                                 thresholds_html)
    from ..learning_report import build as _build_learning

    win = st.selectbox("Window", ["last30", "last100", "last500", "lifetime"],
                       index=1, key="_v6_learn_window")
    p = _build_learning(eng, res, att, evs, window=win)

    s1, s2, s3, s4 = st.tabs(["📊 Performance", "🏆 Engine Accuracy",
                              "🎚 Optimisation", "🔍 Failure Analysis"])
    with s1:
        st.markdown(overall_html(p.get("overall")), unsafe_allow_html=True)
        _performance_by_day_type(st, db, res)
        _performance_by_session(st, db, res)
        _session_validation(st, db, res, att)
    with s2:
        st.markdown(accuracy_html(p.get("rankings"), win),
                    unsafe_allow_html=True)
        st.markdown(contribution_html(p.get("contribution"),
                                      p.get("contribution_lines")),
                    unsafe_allow_html=True)
    with s3:
        st.markdown(calibration_html(p.get("calibration_suggestions"),
                                     p.get("calibration"), win),
                    unsafe_allow_html=True)
        st.markdown(thresholds_html(p.get("thresholds")), unsafe_allow_html=True)
    with s4:
        st.markdown(false_signal_html(p.get("false_signals"),
                                      p.get("recent_losses")),
                    unsafe_allow_html=True)
        _wait_reasons(st)
    st.markdown(governance_html(), unsafe_allow_html=True)


def _wait_reasons(st) -> None:
    """What MIOS spent the session refusing — the other half of the record."""
    log = st.session_state.get("_mios_wait_log") or []
    if not log:
        st.caption("No WAIT cycles logged yet this session.")
        return
    counts: Dict[str, int] = {}
    for r in log:
        counts[str(r)] = counts.get(str(r), 0) + 1
    rows = sorted(counts.items(), key=lambda kv: -kv[1])
    n = len(log)
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
        f"margin-bottom:4px'>⏳ Most common WAIT reasons "
        f"<span style='font-size:11px;color:#b3c2d4'>({n} cycles)</span></div>"
        + "".join(
            f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
            f"<span style='flex:1;color:#edf3f9'>{k}</span>"
            f"<span style='color:#ffcc66'>{v} ({100.0 * v / n:.0f}%)</span>"
            f"</div>" for k, v in rows[:8])
        + "</div>", unsafe_allow_html=True)


def _daily_summary(st, db, fr: Dict[str, Any]) -> None:
    """Stage 67 — today's report."""
    from .review_panel import daily_summary_html
    from ..daily_summary import summarise as _summarise

    day = None
    res = trades = eng = evs = None
    if db is not None and hasattr(db, "get_trade_results"):
        try:
            # Shared limits, sliced — see the constants at the top of the file.
            res = db.get_trade_results(limit=TRADE_RESULT_LIMIT)[:60]
            trades = db.get_trade_attribution(limit=TRADE_ATTRIBUTION_LIMIT)[:60]
            eng = db.get_engine_attribution(limit=ENGINE_ATTRIBUTION_LIMIT)[:3000]
            evs = db.get_trade_events(limit=TRADE_EVENT_LIMIT)[:1500]
        except Exception:
            res = trades = eng = evs = None
    if trades:
        day = (trades[0] or {}).get("trading_day")
    if res and day:
        res = [r for r in res if r.get("trading_day") == day]
        trades = [t for t in (trades or []) if t.get("trading_day") == day]

    st.markdown(daily_summary_html(_summarise(
        results=res, trades=trades, engine_rows=eng, events=evs,
        wait_log=st.session_state.get("_mios_wait_log"),
        state_log=st.session_state.get("_mios_state_log"),
        final_read=fr,
        levels={"support": fr.get("strong_support"),
                "resistance": fr.get("strong_resistance")},
        trading_day=day)), unsafe_allow_html=True)
    st.markdown("---")


# ── 6 · REPLAY ──────────────────────────────────────────────────────────
def _replay(st, db) -> None:
    """Can I verify it, cycle by cycle?

    Reconstruction, not re-simulation: this shows what MIOS believed at the
    time, from the `engine_state` rows the runner has been writing since
    Stage 18. The engines are not re-run — replaying a January session with
    today's code would hide every improvement and every regression alike.
    """
    from ..replay import (SPEEDS, compare_to_outcome, decision_timeline,
                          engine_timeline, flips, frame_at, narrate, seek,
                          summary)

    _reference(st)
    if db is None:
        st.caption("No database connection.")
        return

    try:
        rows = db.get_engine_state(limit=800) if hasattr(db, "get_engine_state") else None
        signals = db.get_trade_signals(limit=TRADE_SIGNAL_LIMIT)
        signals = (signals.to_dict("records")
                   if hasattr(signals, "to_dict") else list(signals or []))
    except Exception:
        rows, signals = None, []

    if not rows:
        st.info("No engine-state history yet. The runner persists one row per "
                "pipeline pass during live sessions — replay becomes available "
                "once a session has run.")
        return

    from ..replay import build_timeline
    frames = build_timeline(rows, signals)
    if not frames:
        st.info("Engine-state rows found but none could be parsed.")
        return

    meta = summary(frames)
    st.markdown(
        f"<div style='{_CARD}'>"
        f"<span style='font-size:13px;font-weight:800;color:#ffffff'>"
        f"⏪ {meta.get('day') or 'session'} · {meta['from']}–{meta['to']}</span>"
        f"<span style='font-size:12px;color:#cfd9e6'> · {meta['frames']} cycles"
        f" · {meta['decision_changes']} decision changes"
        f" · {meta['engine_flips']} engine flips</span>"
        + (f"<div style='font-size:11.5px;color:#ffcc33'>⚠️ "
           f"{meta['gaps']} gap(s) in the recording — not interpolated.</div>"
           if meta.get("gaps") else "")
        + (f"<div style='font-size:11.5px;color:#ffcc33'>⚠️ mixed engine "
           f"versions ({', '.join(meta['versions'])}) — rows from different "
           f"scoring logic must not be compared as if they were the same."
           f"</div>" if meta.get("mixed_versions") else "")
        + f"<div style='font-size:10.5px;color:#9fb0c4;margin-top:3px'>"
          f"{meta['note']}</div></div>", unsafe_allow_html=True)

    # ── transport controls ──
    c1, c2, c3, c4 = st.columns([3, 1, 1, 1])
    last = frames[-1]["index"]
    with c1:
        idx = st.slider("Cycle", 0, last, min(last, int(
            st.session_state.get("_v6_replay_idx", last))), key="_v6_replay_idx")
    with c2:
        jump = st.text_input("Jump to", value="", placeholder="10:42",
                             key="_v6_replay_jump")
    with c3:
        speed = st.selectbox("Speed", SPEEDS, index=1, key="_v6_replay_speed")
    with c4:
        step = st.button("▶ Step", key="_v6_replay_step")

    if jump:
        idx = seek(frames, jump.strip())
    if step:
        idx = min(last, idx + int(speed))

    f = frame_at(frames, idx)
    st.markdown(
        f"<div style='{_CARD};border-left:3px solid #a78bfa'>"
        f"<span style='font-size:19px;font-weight:900;color:#ffffff'>"
        f"{f.get('time')} · {_fmt(f.get('spot'))}</span>"
        f"<span style='font-size:13px;color:#c9b6ec'> · "
        f"{f.get('bias') or '—'} · {f.get('structure_decision') or '—'}"
        f" · agreement {_num(f.get('agreement_pct')):.0f}%</span>"
        + "".join(f"<div style='font-size:12.5px;color:#ffd000'>{m['label']}"
                  f"</div>" for m in (f.get("markers") or []))
        + "</div>", unsafe_allow_html=True)

    # ── engine state at this candle ──
    engines = f.get("engines") or {}
    if engines:
        st.markdown(
            f"<div style='{_CARD}'>"
            f"<div style='font-size:12px;font-weight:800;color:#ffffff;"
            f"margin-bottom:3px'>🔬 Engine state at {f.get('time')}</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:112px;color:#cfd9e6'>{k}</span>"
                f"<span style='width:92px;font-weight:800;color:"
                f"{_BIAS_COLOUR.get(str(v.get('bias', '')).upper(), '#cfd9e6')}'>"
                f"{v.get('bias') or '—'}</span>"
                f"<span style='color:#edf3f9'>{_num(v.get('confidence')):.0f}%"
                f"</span></div>" for k, v in engines.items())
            + "</div>", unsafe_allow_html=True)

    t1, t2, t3 = st.tabs(["🗓 Decision timeline", "🔬 Engine timeline",
                          "🎙 Narration"])
    with t1:
        dt = decision_timeline(frames)
        st.markdown("".join(
            f"<div style='display:flex;gap:8px;font-size:12.5px;padding:2px 0;"
            f"border-bottom:1px solid #161b22;"
            f"{'background:#151d2b' if d['index'] == idx else ''}'>"
            f"<span style='width:44px;color:#9fb0c4'>{d['time']}</span>"
            f"<span style='width:70px;color:#ffffff'>{_num(d['spot']):,.0f}</span>"
            f"<span style='color:#c9b6ec'>{d['from_bias'] or '—'} → "
            f"<b>{d['bias'] or '—'}</b></span>"
            f"<span style='margin-left:auto;color:#cfd9e6'>"
            f"{d['decision'] or ''}</span></div>" for d in dt),
            unsafe_allow_html=True)
    with t2:
        names = sorted({k for x in frames for k in (x.get("engines") or {})})
        if names:
            pick = st.selectbox("Engine", names, key="_v6_replay_engine")
            et = engine_timeline(frames, pick)
            st.markdown("".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:44px;color:#9fb0c4'>{e['time']}</span>"
                f"<span style='width:92px;font-weight:{800 if e['flipped'] else 600};"
                f"color:{_BIAS_COLOUR.get(str(e['bias']).upper(), '#cfd9e6')}'>"
                f"{e['bias'] or '—'}</span>"
                f"<span style='color:#edf3f9'>{_num(e['confidence']):.0f}%</span>"
                + ("<span style='color:#ffcc33'> ⟲ flip</span>"
                   if e["flipped"] else "")
                + "</div>" for e in et[-80:]), unsafe_allow_html=True)
        st.caption(f"{len(flips(frames))} engine flips in this session.")
    with t3:
        from .narrator_panel import narrator_html
        st.markdown(narrator_html(narrate(frames, upto=idx),
                                  title="🎙 Replay narration"),
                    unsafe_allow_html=True)

    # ── replay vs actual outcome ──
    closed = [s for s in signals if s.get("entered_at")]
    if closed:
        st.markdown("---")
        pre = st.session_state.get("_v6_replay_signal")
        ids = [s.get("signal_id") for s in closed]
        i0 = ids.index(pre) if pre in ids else 0
        sid = st.selectbox("Compare replay vs actual outcome", ids, index=i0,
                           key="_v6_replay_compare")
        sig = next((s for s in closed if s.get("signal_id") == sid), None)
        cmp = compare_to_outcome(frames, sig)
        if not cmp.get("available"):
            st.caption(cmp.get("reason", ""))
        else:
            pnl = cmp.get("pnl_points")
            col = "#00ff88" if (pnl or 0) > 0 else "#ff6666"
            st.markdown(
                f"<div style='{_CARD};border-left:3px solid {col}'>"
                f"<div style='font-size:13px;font-weight:800;color:{col}'>"
                f"{cmp['signal_id']} {cmp.get('side', '')} · "
                f"{cmp.get('outcome', '—')}"
                f"{(' %+.0f pts' % pnl) if pnl is not None else ''}</div>"
                f"<div style='font-size:12.5px;color:#edf3f9;margin-top:2px'>"
                f"Entry {cmp['entry_frame'].get('time')} · bias "
                f"{cmp.get('bias_at_entry') or '—'} · agreement "
                f"{_num(cmp.get('agreement_at_entry')):.0f}%<br>"
                f"Exit {cmp['exit_frame'].get('time')} · bias "
                f"{cmp.get('bias_at_exit') or '—'} · agreement "
                f"{_num(cmp.get('agreement_at_exit')):.0f}%<br>"
                f"{cmp['cycles_in_trade']} cycles in trade · "
                f"{len(cmp['flips_during'])} engine flips while open</div>"
                f"<div style='font-size:12.5px;color:#ffcc66;margin-top:3px'>"
                f"{cmp['verdict']}</div>"
                + (f"<div style='font-size:11.5px;color:#ff9500;margin-top:2px'>"
                   f"⚠️ engine_version changed between entry and exit — these "
                   f"rows were not produced by the same scoring logic.</div>"
                   if cmp.get("version_changed") else "")
                + "</div>", unsafe_allow_html=True)


def _reference(st) -> None:
    """What each checklist condition means and which engine owns it."""
    from .explain_panel import boundary_html
    from ..checklist import CONDITIONS, ORDER

    with st.expander("📚 Reference — what each condition means", expanded=False):
        st.markdown(
            f"<div style='{_CARD}'>"
            + "".join(
                f"<div style='display:flex;gap:8px;align-items:baseline;"
                f"margin-top:3px'>"
                f"<span style='width:172px;font-size:12px;font-weight:700;"
                f"color:#edf3f9'>{CONDITIONS[k][0]}</span>"
                f"<span style='width:44px;font-size:11px;color:#cfd9e6'>"
                f"w{CONDITIONS[k][1]}</span>"
                f"<span style='font-size:11.5px;color:#cfd9e6'>"
                f"{CONDITIONS[k][2]}</span></div>" for k in ORDER)
            + "<div style='margin-top:7px;font-size:11px;color:#9fb0c4'>"
              "✅ met · ❌ not met · ⚪ the engine could not report. Unknown "
              "conditions are excluded from readiness rather than guessed — "
              "guessing either way would be a lie in one direction."
              "</div></div>", unsafe_allow_html=True)
        st.markdown(boundary_html(), unsafe_allow_html=True)


def _performance_by_day_type(st, db, results) -> None:
    """Which market types actually produce results — Stage 68's payoff."""
    from .day_type_panel import day_type_timeline, performance_by_type
    from ..day_type import occurrence, performance_by_type as _perf

    if db is None or not hasattr(db, "get_day_type_log"):
        return
    try:
        log = db.get_day_type_log(limit=1000)
    except Exception:
        log = None
    if not log:
        st.caption("No day-type history yet — run `sql/028_day_type_log.sql` "
                   "and let a few sessions record.")
        return
    st.markdown(performance_by_type(_perf(log, results)), unsafe_allow_html=True)

    occ = occurrence(log)
    if occ:
        st.markdown(
            f"<div style='{_CARD}'>"
            f"<div style='font-size:13px;font-weight:800;color:#ffffff;"
            f"margin-bottom:4px'>📊 How often each market type occurs</div>"
            + "".join(
                f"<div style='display:flex;gap:8px;font-size:12px;padding:1px 0'>"
                f"<span style='width:180px;color:#edf3f9'>{o['label']}</span>"
                f"<span style='width:56px;color:#cfd9e6'>{o['count']}×</span>"
                f"<span style='width:52px;color:#cfd9e6'>{o['pct']}%</span>"
                f"<span style='color:#9fb0c4'>"
                f"{('avg %.0f min' % o['avg_hold_min']) if o.get('avg_hold_min') else ''}"
                f"</span></div>" for o in occ)
            + "</div>", unsafe_allow_html=True)


def _performance_by_session(st, db, results) -> None:
    """Which sessions actually produce results — Stage 69's payoff."""
    from .session_panel import performance_by_session
    from ..session import performance_by_session as _perf

    if db is None or not hasattr(db, "get_session_log"):
        return
    try:
        log = db.get_session_log(limit=SESSION_LOG_LIMIT)
    except Exception:
        log = None
    if not log:
        st.caption("No session history yet — run `sql/029_session_log.sql` "
                   "and let a few sessions record.")
        return
    st.markdown(performance_by_session(_perf(log, results)),
                unsafe_allow_html=True)


def _session_validation(st, db, results, trades) -> None:
    """Stage 70 — is Stage 69 actually worth applying?

    The counterfactual is the point: Stage 69's modifiers have never been
    live, so this replays what they WOULD have done against the graded
    history. It changes nothing; it decides whether a human should.
    """
    from .session_validation_panel import render as _render_validation
    from ..session_validation import build as _build_validation

    if db is None or not hasattr(db, "get_session_log"):
        return
    try:
        log = db.get_session_log(limit=SESSION_LOG_LIMIT)
        recs = (db.get_session_recommendations(limit=500)
                if hasattr(db, "get_session_recommendations") else [])
    except Exception:
        log, recs = None, []
    if not log:
        st.caption("Stage 70 needs `sql/029_session_log.sql` and "
                   "`sql/030_session_validation.sql`, plus a few graded "
                   "sessions.")
        return
    with st.expander("🔬 Stage 70 — Session validation", expanded=False):
        _render_validation(st, _build_validation(log, results, trades, recs))
