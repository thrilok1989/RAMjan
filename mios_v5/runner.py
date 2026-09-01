"""MIOS V5 — host-app glue.

`run_mios_pass()` is the single call the existing Streamlit app makes each
refresh cycle: it assembles raw inputs from the host, runs the orchestrator
pass, and returns the MarketState. Cheap by design — Phase A runs only
Stage 0; each later phase registers more engines here.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

import pytz

from .core import MarketState, Orchestrator
from .engines import ALL_ENGINES

IST = pytz.timezone("Asia/Kolkata")


def build_orchestrator() -> Orchestrator:
    """Registry of all active MIOS V5 engines (grows phase by phase)."""
    orch = Orchestrator()
    orch.register_all([cls() for cls in ALL_ENGINES])
    return orch


def run_mios_pass(session_state, db=None,
                  extra_raw: Optional[Dict[str, Any]] = None) -> MarketState:
    """Run one MIOS pipeline pass using the host app's live context.

    session_state — st.session_state (read for API/data flags; the previous
                    pass's RunReport and error-log throttle cache persist here)
    db            — SupabaseDB handle (error persistence)
    """
    # ── assemble raw inputs from host state ──────────────────────────
    raw: Dict[str, Any] = {
        "db": db,
        "db_ok": getattr(db, "is_connected", None) if db is not None else None,
        "token_expired": bool(session_state.get("_dhan_token_expired")),
        "rate_limited": False,
        "api_ok": None,
        "last_data_ts": None,
        "prev_report": session_state.get("_mios_prev_report"),
        # previous-pass snapshot for the Evolution engine (Stage 29)
        "prev_snapshot": session_state.get("_mios_prev_snapshot"),
        # ⚠️ Stage 33's gap signal, which had never once fired.
        #
        # `stage33_event_impact` tests
        #     (raw.get("gap_today") or {}).get("type") in ("GAP-UP", "GAP-DOWN")
        # and nothing ever put `gap_today` into `raw`. The data was there the
        # whole time: `capture_day_open_and_gap` publishes `_gap_today` as
        # `{'type', 'pct', 'open', 'prev_close'}` — the exact `type` key the
        # engine checks — and the app header reads it for the previous close.
        # Forwarded, not recomputed; the producer stays the only owner.
        "gap_today": session_state.get("_gap_today"),
        # Stage 4's expiry fallback, for the cycle where `option_data` has no
        # `expiry` but the raw chain payload does.
        "cached_raw_chain_latest": session_state.get("_cached_raw_chain_latest"),
        # Stage 52's position state — see `_open_position` for the contract and
        # why this is a rename rather than an adapter.
        "open_position": _open_position(session_state),
        # persist the per-error throttle cache across passes
        "_err_log_seen": session_state.setdefault("_mios_err_seen", {}),
        # Stage-40 prediction-log throttle state (persists across passes)
        "_mios_pred_state": session_state.setdefault("_mios_pred_state", {}),
    }
    try:
        back = session_state.get("_dhan_429_until")
        if back is not None:
            raw["rate_limited"] = datetime.now(IST) < back
    except Exception:
        pass
    # freshest market data timestamp: option-chain cache time if present
    try:
        ts = session_state.get("_opt_data_ts") or session_state.get("_last_cycle_ts")
        if ts:
            raw["last_data_ts"] = ts if isinstance(ts, str) else str(ts)
    except Exception:
        pass
    # API considered OK if we have a cached chain and no expiry/backoff flags
    try:
        if session_state.get("_cached_option_data") is not None:
            raw["api_ok"] = not raw["token_expired"]
    except Exception:
        pass
    # ── forward the app's already-computed caches (adapter inputs) ───
    # Phase-B engines read these instead of recomputing. They may be one
    # cycle old (this pass runs before the cycle's compute) — engines return
    # NEUTRAL ("warming up") when a cache is absent, which is correct.
    try:
        opt = session_state.get("_cached_option_data")
        raw["option_data"] = opt
        raw["market_picture"] = session_state.get("_market_picture")
        raw["full_market_read"] = session_state.get("_full_market_read")
        raw["market_structure"] = session_state.get("_market_structure")
        raw["leg_bias_cache"] = session_state.get("_leg_bias_cache")
        raw["gex_data"] = session_state.get("_gex_data")
        raw["volume_delta"] = session_state.get("_volume_delta_data")
        raw["money_flow"] = session_state.get("_money_flow_data")
        raw["composite_profile"] = session_state.get("_composite_profile")
        raw["value_migration"] = session_state.get("_value_migration")
        raw["value_alignment"] = session_state.get("_value_alignment")
        raw["sector_rotation"] = session_state.get("_sector_rotation")
        raw["news"] = session_state.get("_news_bias")   # headlines for the explain layer
        # ── Environment engines (Stage 22 VIX, Stage 23 flows) ──
        # India VIX: the app keeps a rolling value list in vix_history; the
        # engine reads latest value + direction.
        try:
            _vh = session_state.get("vix_history") or []
            if _vh:
                _vlast = float(_vh[-1])
                _vdir = ("Rising" if len(_vh) >= 2 and _vlast > float(_vh[0])
                         else "Falling" if len(_vh) >= 2 and _vlast < float(_vh[0])
                         else "Unknown")
                raw["vix"] = {"value": _vlast, "direction": _vdir,
                              "history": list(_vh)}
        except Exception:
            pass
        # FII/DII cash (end-of-day) — already fetched + cached by the app
        raw["fii_dii"] = session_state.get("_fii_dii_cash")
        raw["fii_deriv"] = session_state.get("_fii_deriv_stats")
        # ── spot: the live LTP first, the chain's `underlying` second ──
        # The chain is re-fetched on its own cadence, so its `underlying` is a
        # snapshot from whenever that fetch last ran. `_nifty_spot_live` is the
        # LTP the chart header is showing, published every cycle. Taking the
        # chain's value alone is why spot sat still on every V5/V6 panel while
        # the foundation header ticked.
        # ⚠️ Delegated to `mios_v5.spot`, the one owner. This block used to
        # carry its own live-then-chain precedence and it was the only correct
        # one in the app — three other sites had their own, two of them
        # backwards. Keeping a fourth copy here, even a correct one, is how they
        # drifted apart in the first place.
        from .spot import read as _spot_read
        _sp = _spot_read(session_state)
        _spot = _sp["price"]
        if _spot is not None:
            raw["spot"] = _spot
        raw["spot_source"] = _sp["source"]
    except Exception:
        pass

    # ── Stage-3 market memory: previous-session H/L/C derived once per day
    # from the intraday candle cache (_df_5m is fetched with days_back > 1,
    # so the prior session's bars are present). Cached per trading day.
    try:
        _today = datetime.now(IST).date()
        _mem = session_state.get("_mios_market_memory")
        if not (_mem and _mem.get("day") == str(_today)):
            df5 = session_state.get("_df_5m")
            if df5 is not None and not getattr(df5, "empty", True) \
                    and "datetime" in getattr(df5, "columns", []):
                _dates = df5["datetime"].dt.date
                _prev_days = sorted({d for d in _dates if d < _today})
                if _prev_days:
                    _pd_df = df5[_dates == _prev_days[-1]]
                    _mem = {"day": str(_today),
                            "prev_day": str(_prev_days[-1]),
                            "prev_high": float(_pd_df["high"].max()),
                            "prev_low": float(_pd_df["low"].min()),
                            "prev_close": float(_pd_df["close"].iloc[-1])}
                    session_state["_mios_market_memory"] = _mem
        if _mem and _mem.get("prev_close"):
            raw["market_memory"] = _mem
    except Exception:
        pass

    # ── Stage-4 gap input: today's opening print (first bar of the current
    # session), for the Market Context engine's gap classification. Cheap,
    # each cycle, fully guarded — absent → the engine just skips gap. ──
    try:
        df5 = session_state.get("_df_5m")
        if df5 is not None and not getattr(df5, "empty", True) \
                and "datetime" in getattr(df5, "columns", []):
            _today_o = datetime.now(IST).date()
            _tdf = df5[df5["datetime"].dt.date == _today_o]
            if not getattr(_tdf, "empty", True):
                raw["day_open"] = float(_tdf["open"].iloc[0])
    except Exception:
        pass
    # Before today's first candle exists (~09:06–09:15), fall back to the
    # captured opening spot so Stage 4 can classify the gap from the open.
    if "day_open" not in raw:
        try:
            _dos = session_state.get("_day_open_spot") or {}
            if _dos.get("spot") and _dos.get("day") == datetime.now(IST).date().isoformat():
                raw["day_open"] = float(_dos["spot"])
        except Exception:
            pass

    # ── Stage 44 (Flow Shift) needs the DERIVATIVE, so it needs history: the
    # rolling metric trace plus the previous stability state and how long the
    # tape has been calm (so RECOVERY has to be earned back, not assumed).
    # Stage 42 reads the canonical S/R and needs each level's reaction memory
    # (state, cycles beyond, the break-moment reference) to judge follow-through.
    # Stage 47 measures the DERIVATIVE of the family strengths, so it needs
    # the per-cycle history of those strengths.
    # Stage 50 reads intent-in-progress, which needs the per-cycle trace
    # Stage 54 is market MEMORY — it must survive across cycles
    # Stage 68 classifies the SESSION, so it needs the day's own metrics and
    # its own memory (a day type that reset every cycle could never report how
    # long it had held, which is half the point of classifying it).
    raw["day_type_memory"] = session_state.get("_day_type_memory") or {}
    raw["now_ts"] = datetime.now(IST).timestamp()
    raw["trading_day"] = datetime.now(IST).date().isoformat()
    try:
        raw["day_metrics"] = _day_metrics(session_state, raw)
    except Exception:
        raw["day_metrics"] = {}
    raw["absorption_trace"] = session_state.get("_absorption_trace") or []
    raw["state_memory"] = session_state.get("_state_memory") or {}
    raw["energy_memory"] = session_state.get("_energy_memory") or {}
    raw["ltp_trace"] = session_state.get("_ltp_trace") or []
    raw["bias_trace"] = session_state.get("_bias_trace") or []
    raw["htf_profiles"] = session_state.get("_htf_profiles") or {}
    raw["reaction_sr"] = session_state.get("_reaction_sr")
    raw["acceptance_memory"] = session_state.get("_acceptance_memory") or {}
    raw["flow_trace"] = session_state.get("_flow_trace") or []
    raw["flow_stability_prev"] = session_state.get("_flow_stability")
    raw["flow_cycles_since_shock"] = session_state.get("_flow_calm_cycles", 99)

    if extra_raw:
        raw.update(extra_raw)

    # ── run ──────────────────────────────────────────────────────────
    orch = session_state.get("_mios_orchestrator")
    if orch is None:
        orch = build_orchestrator()
        session_state["_mios_orchestrator"] = orch
    state = orch.run(raw)
    session_state["_mios_prev_report"] = state.raw.get("_run_report")
    # roll the flow trace forward + remember the stability state so the next
    # pass can measure velocity against it
    # roll Stage 43's behaviour trace (reloading needs the absorb→pause→absorb
    # pattern, which only exists across cycles)
    try:
        _ab = state.get("stage43_absorption")
        if _ab is not None and _ab.data and _ab.data.get("trace") is not None:
            session_state["_absorption_trace"] = _ab.data["trace"]
    except Exception:
        pass
    # persist the day-type memory (Stage 68) — duration and transition history
    try:
        _dt = state.get("stage68_day_type")
        if _dt is not None and _dt.data and _dt.data.get("memory"):
            session_state["_day_type_memory"] = _dt.data["memory"]
    except Exception:
        pass
    # persist market memory (Stage 54)
    try:
        _mm = state.get("stage54_memory")
        if _mm is not None and _mm.data and _mm.data.get("memory"):
            session_state["_state_memory"] = _mm.data["memory"]
    except Exception:
        pass
    # remember the energy state so Stage 37 can measure how long it has held
    try:
        _en = state.get("stage37_energy")
        if _en is not None and _en.data and _en.data.get("state"):
            session_state["_energy_memory"] = {
                "state": _en.data["state"],
                "compression": _en.data.get("compression"),
                "duration_cycles": _en.data.get("duration_cycles", 0)}
    except Exception:
        pass
    # roll the LTP-behaviour trace forward for Stage 50
    try:
        from .ltp_behaviour import trace_push as _lt_push
        _lb = state.get("stage50_ltp_behaviour")
        if _lb is not None and _lb.data and _lb.data.get("metrics"):
            session_state["_ltp_trace"] = _lt_push(
                session_state.get("_ltp_trace"), _lb.data["metrics"])
    except Exception:
        pass
    # roll the bias-strength trace forward for Stage 47
    try:
        from .transition import trace_push as _bt_push
        _bt = state.get("stage47_transition")
        if _bt is not None and _bt.data and _bt.data.get("snapshot"):
            session_state["_bias_trace"] = _bt_push(
                session_state.get("_bias_trace"), _bt.data["snapshot"])
    except Exception:
        pass
    # persist Stage 42's per-level reaction memory across cycles
    try:
        _ac = state.get("stage42_acceptance")
        if _ac is not None and _ac.data and _ac.data.get("memory"):
            session_state["_acceptance_memory"] = _ac.data["memory"]
    except Exception:
        pass
    try:
        from .flow_shift import trace_push
        _fs = state.get("stage44_flow_shift")
        if _fs is not None and _fs.data:
            session_state["_flow_trace"] = trace_push(
                session_state.get("_flow_trace"), _fs.data.get("metrics") or {})
            _stab = _fs.data.get("stability")
            session_state["_flow_stability"] = _stab
            session_state["_flow_calm_cycles"] = (
                0 if _stab in ("SHOCK", "UNSTABLE")
                else int(session_state.get("_flow_calm_cycles", 0)) + 1)
    except Exception:
        pass
    # capture this pass's snapshot so next pass's Evolution engine can diff it
    try:
        from .engines.stage29_evolution import snapshot_of
        session_state["_mios_prev_snapshot"] = snapshot_of(state)
    except Exception:
        pass
    # persist the derived Engine State snapshot (throttled — a script rerun
    # can happen far more often than a real new market cycle; ~20s keeps the
    # table at roughly one row per cycle instead of one per Streamlit rerun)
    try:
        if db is not None:
            _last_es = session_state.get("_mios_last_engine_state_ts", 0)
            if time.time() - _last_es >= 20:
                from .engine_state import build_engine_state_row
                db.insert_engine_state(build_engine_state_row(state, spot=raw.get("spot")))
                session_state["_mios_last_engine_state_ts"] = time.time()
    except Exception:
        pass
    session_state["_mios_state"] = state
    return state


# ══════════════════════════════════════════════════════════════════════════
#  Stage 68 · day metrics adapter.
#
#  The classifier computes nothing about price itself — it reads finished
#  metrics. This is the one place they are derived from the app's candle and
#  chain caches, so the engine stays pure and testable and there is exactly one
#  definition of "ATR expanding" in the system.
#
#  Every block is independently guarded: a missing input drops one metric, not
#  the whole group, and a group that ends up empty is reported as unavailable
#  rather than filled with a default. A fabricated metric would put an invented
#  group into the agreement denominator and inflate every confidence number.
# ══════════════════════════════════════════════════════════════════════════
def _fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


#: Stage 52's `position` contract, derived from what `decision_v2` actually reads
#: — not from what a position dict could plausibly contain.
#:
#: `decide()` and `_manage()` between them read exactly THREE fields, and nothing
#: else. Enumerated from the AST, then verified against the arithmetic:
#:
#:     side    "CALL" | "PUT". Its PRESENCE is the in-a-position flag —
#:             `if pos.get("side"): return _manage(...)` (decision_v2:143).
#:             There is no `is_open` field and adding one would do nothing.
#:     entry   a SPOT/INDEX level, not an option premium. Proven by the
#:             arithmetic: `gain = (spot - entry) if side == "CALL" else
#:             (entry - spot)` (decision_v2:187).
#:     target  a SPOT level too — compared directly against spot
#:             (decision_v2:199).
#:
#: `strike`, `quantity`, `entry_time`, `signal_id` and `source` are NOT read by
#: anything. They are not part of this contract.
_POSITION_FIELDS = ("side", "entry", "target")


def _open_position(session_state) -> Dict[str, Any]:
    """Stage 52's `open_position`, from the app's own live-trade state.

    ## Why `_entry_gate_active` and not `_entry_signal_open`

    `_entry_signal_open` is keyed by leg tag and its `entry` is an OPTION PREMIUM
    — `_leg_levels` draws it as an overlay line on the leg's own price chart.
    Feeding a premium into `decide()` would compute `gain = 24,500 - 120` and
    drive TRAIL / SCALE_IN off a meaningless number. That is the shape-matched
    adapter this deliberately is not.

    `_entry_gate_active` is the app's position-level state, and its arithmetic is
    already **identical** to `_manage`'s:

        vob_minimal.py:8266   (spot_price - _act['entry_spot']) if side == 'CALL'
                              else (_act['entry_spot'] - spot_price)
        decision_v2.py:187    (st - entry) if up else (entry - st)

    So this is a boundary rename of ONE field — `entry_spot` → `entry` — of the
    same kind `_mios_market_read` already does, not a new interpretation.

    ## The lifecycle is real, which is what makes this safe

    A position dict that is never cleared would trap Stage 52 in `_manage`
    forever — worse than the flat-forever bug it replaces. `_entry_gate_active`
    is set only under `if _st_a in ('CALL', 'PUT')` (vob_minimal.py:8091),
    superseded when a new entry arms (:8155), and **popped on exit** (:8374 and
    :8600).

    ⚠️ Returns `{}` — never a partial dict — when `side` is missing or is not one
    of CALL/PUT. `side`'s presence IS the in-a-position flag, so a dict carrying
    `entry` but no `side` would put Stage 52 in a state the engine has no branch
    for.
    """
    try:
        act = session_state.get("_entry_gate_active")
    except Exception:
        return {}
    if not isinstance(act, Mapping):
        return {}
    side = str(act.get("side") or "").strip().upper()
    if side not in ("CALL", "PUT"):
        return {}
    out: Dict[str, Any] = {"side": side}
    # `entry_spot` → `entry`: the rename this whole function exists for.
    entry = _fnum(act.get("entry_spot"))
    if entry is not None:
        out["entry"] = entry
    target = _fnum(act.get("target"))
    if target is not None:
        out["target"] = target
    return out


def _day_metrics(session_state, raw: Dict[str, Any]) -> Dict[str, Any]:
    spot = _fnum(raw.get("spot"))
    mp = raw.get("market_picture") or {}
    opt = raw.get("option_data") or {}
    mf = raw.get("money_flow") or {}

    out: Dict[str, Any] = {
        "price": _price_metrics(session_state, spot, mp, mf),
        "options": _option_metrics(session_state, opt, mp),
        "dealer": _dealer_metrics(raw, mp),
        "flow": _flow_metrics(raw, mp),
        # No L2 depth in this feed — Stage 15 is DISABLED for the same reason.
        # `None` makes the depth group report unavailable, which is correct;
        # an empty dict of zeros would look like a balanced book.
        "depth": None,
        "is_expiry": bool(session_state.get("_is_expiry_today")),
    }
    try:
        from .charm_pin import from_market_picture
        out["charm_pin"] = from_market_picture(
            out["is_expiry"], spot, mp, opt.get("max_pain_strike"))
    except Exception:
        out["charm_pin"] = {}
    return out


def _price_metrics(session_state, spot, mp, mf) -> Dict[str, Any]:
    """ATR · structure · range · VWAP/POC distance — from the 1-minute series."""
    out: Dict[str, Any] = {}
    # TODAY's bars only. The frame arrives with a `days_back` window, so a day
    # range computed over it would report a two-day range as today's, and the
    # "opening range" would be the PREVIOUS session's first fifteen minutes.
    from .clock import today_slice
    df = today_slice(nifty_frame(session_state)[0])
    try:
        if df is not None and not getattr(df, "empty", True) and len(df) >= 30:
            hi, lo, cl = df["high"], df["low"], df["close"]
            prev = cl.shift(1)
            tr = (hi - lo).combine((hi - prev).abs(), max).combine(
                (lo - prev).abs(), max)
            atr = float(tr.tail(14).mean())
            base = float(tr.tail(60).mean()) if len(tr) >= 60 else atr
            out["atr"] = round(atr, 2)
            if spot:
                out["atr_pct"] = round(100.0 * atr / spot, 3)
            if base > 0:
                ratio = atr / base
                out["atr_state"] = ("EXPANDING" if ratio >= 1.25 else
                                    "COMPRESSING" if ratio <= 0.8 else "STEADY")
            # Published so consumers outside the pipeline can read the ONE ATR
            # rather than computing a second one. Stage 74's cluster tolerance
            # is volatility-adaptive and needs this; `day_metrics` lives on the
            # runner's internal `raw` and is not reachable from the app.
            try:
                session_state["_atr"] = {
                    "atr": out["atr"], "atr_pct": out.get("atr_pct"),
                    "atr_state": out.get("atr_state"), "period": 14,
                    "source": "Stage 00 — runner._price_metrics",
                }
            except Exception:
                pass
            day_hi, day_lo = float(hi.max()), float(lo.min())
            if spot and day_hi > day_lo:
                out["day_range_pct"] = round(100.0 * (day_hi - day_lo) / spot, 3)
            # swing structure from the last three 10-bar blocks — cheap, and
            # enough to say whether highs and lows are stepping the same way
            if len(df) >= 30:
                blocks = [(float(hi.iloc[-30:-20].max()), float(lo.iloc[-30:-20].min())),
                          (float(hi.iloc[-20:-10].max()), float(lo.iloc[-20:-10].min())),
                          (float(hi.iloc[-10:].max()), float(lo.iloc[-10:].min()))]
                highs = [b[0] for b in blocks]
                lows = [b[1] for b in blocks]
                out["higher_highs"] = highs[2] > highs[1] > highs[0]
                out["higher_lows"] = lows[2] > lows[1] > lows[0]
                out["lower_highs"] = highs[2] < highs[1] < highs[0]
                out["lower_lows"] = lows[2] < lows[1] < lows[0]
            # opening range: first 15 bars, broken or holding
            if len(df) >= 45:
                orb_hi = float(hi.iloc[:15].max())
                orb_lo = float(lo.iloc[:15].min())
                if spot:
                    out["opening_range"] = ("BROKEN"
                                            if spot > orb_hi or spot < orb_lo
                                            else "HELD")
    except Exception:
        pass

    vwap = _fnum(mp.get("vwap"))
    if vwap and spot:
        out["vwap_distance_pct"] = round(100.0 * (spot - vwap) / spot, 3)
    poc = _fnum(mf.get("poc_price"))
    if poc and spot:
        out["poc_distance_pct"] = round(100.0 * (spot - poc) / spot, 3)

    # breakout success rate, from Stage 42's own per-level memory — the
    # acceptance engine already decides what a failed breakout is, so reading
    # its verdict keeps one definition instead of two
    try:
        mem = session_state.get("_acceptance_memory") or {}
        good = bad = 0
        for lvl in mem.values():
            st = str((lvl or {}).get("state") or "").upper()
            if st in ("CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN", "ACCEPTANCE"):
                good += 1
            elif st in ("FAILED_BREAKOUT", "FAILED_BREAKDOWN", "BULL_TRAP",
                        "BEAR_TRAP", "SWEEP_BUY", "SWEEP_SELL"):
                bad += 1
        hist = session_state.get("_day_break_tally") or {"good": 0, "bad": 0}
        hist = {"good": max(hist["good"], good), "bad": max(hist["bad"], bad)}
        session_state["_day_break_tally"] = hist
        if hist["good"] or hist["bad"]:
            out["breakouts"] = hist["good"]
            out["failed_breakouts"] = hist["bad"]
    except Exception:
        pass
    return out


def _option_metrics(session_state, opt, mp) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    pcr = _fnum(opt.get("pcr"))
    if pcr is not None:
        out["pcr"] = pcr
    ce, pe = _fnum(opt.get("total_ce_change")), _fnum(opt.get("total_pe_change"))
    if ce is not None and pe is not None:
        # positive ΔOI = writing, negative = unwinding. Both sides writing is
        # a defended range; both unwinding is participants leaving.
        if ce > 0 and pe > 0:
            out["writing"] = "BOTH"
        elif ce > 0:
            out["writing"] = "CALL"
        elif pe > 0:
            out["writing"] = "PUT"
        if ce < 0 and pe < 0:
            out["unwinding"] = "BOTH"
        elif ce < 0:
            out["unwinding"] = "CALL"
        elif pe < 0:
            out["unwinding"] = "PUT"
        scale = abs(ce) + abs(pe)
        if scale:
            out["oi_velocity"] = round((ce + pe) / 1e5, 2)
    try:
        ivh = session_state.get("_iv_history") or []
        if len(ivh) >= 2:
            first = _fnum((ivh[0] or {}).get("atm_iv"))
            last = _fnum((ivh[-1] or {}).get("atm_iv"))
            if first and last:
                out["iv_change_pct"] = round(100.0 * (last - first) / first, 2)
    except Exception:
        pass
    return out


def _dealer_metrics(raw, mp) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    gex = raw.get("gex_data") or {}
    total = _fnum(gex.get("total_gex"))
    if total is None:
        total = _fnum(mp.get("gex_disp"))
    if total is not None:
        out["gex"] = total
    flip = _fnum(gex.get("gamma_flip"))
    spot = _fnum(raw.get("spot"))
    if flip and spot:
        out["gamma_flip_near"] = abs(spot - flip) <= max(25.0, spot * 0.001)
    return out


def _flow_metrics(raw, mp) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    imb = _fnum(mp.get("oflow_imb"))
    if imb is not None:
        out["imbalance_pct"] = imb
    vd = raw.get("volume_delta") or {}
    cvd = _fnum(vd.get("cvd_slope"))
    if cvd is not None:
        out["cvd_state"] = ("RISING" if cvd > 0.15 else
                            "FALLING" if cvd < -0.15 else "FLAT")
    return out


#: NIFTY candle caches, in preference order. `_last_df` is written as a SIDE
#: EFFECT of `generate_master_signal`, so it is absent whenever that analysis
#: path is skipped — which is exactly when the terminal reported "No candle
#: series yet for: NIFTY" while both option legs drew fine, and when Stage 68's
#: price group silently vanished.
#: in preference order. `_nifty_df_live` is FIRST because it is the frame the
#: foundation chart itself is drawing, published every cycle right where it is
#: fetched. The others are all written as side effects of some other pass —
#: `_last_df` in particular only exists when `generate_master_signal` ran, which
#: is gated on the seller analysis returning something. When it did not, the
#: whole V5/V6 layer charted and priced a stale frame with no way to tell.
NIFTY_SOURCES = (
    ("_nifty_df_live", "live NIFTY frame (chart path)"),
    ("_last_df", "1-minute NIFTY frame (analysis path)"),
    ("_raw_1m_trade", "1-minute NIFTY payload (trade path)"),
    ("_df_5m", "5-minute NIFTY frame"),
)


def nifty_frame(session_state):
    """Resolve the NIFTY candle frame from whichever cache has it.

    Returns `(frame, reason)`. `reason` labels the source that answered, or —
    when nothing did — says where to look, so a caller can report the absence
    rather than just naming the series.
    """
    for key, label in NIFTY_SOURCES:
        frame = coerce_frame(session_state.get(key))
        if frame is not None and not getattr(frame, "empty", True):
            return frame, label
    return None, ("no NIFTY candles cached yet — `_last_df` is written by the "
                  "analysis pass and `_raw_1m_trade` by the 1-minute fetch; "
                  "neither has run")


def coerce_frame(raw):
    """A DataFrame, or the raw Dhan payload turned into one.

    `_raw_1m_trade` is the API response dict (epoch `timestamp` + OHLCV lists),
    not a frame — handing it straight to a chart would silently do nothing.
    """
    if raw is None:
        return None
    if hasattr(raw, "empty"):
        return raw
    if isinstance(raw, dict) and raw.get("open") and raw.get("timestamp"):
        try:
            import pandas as pd
            df = pd.DataFrame({
                "timestamp": raw["timestamp"], "open": raw["open"],
                "high": raw["high"], "low": raw["low"], "close": raw["close"],
                "volume": raw.get("volume", [0] * len(raw["open"]))})
            df["datetime"] = (pd.to_datetime(df["timestamp"], unit="s",
                                             utc=True)
                              .dt.tz_convert(IST))
            return df
        except Exception:
            return None
    return None
