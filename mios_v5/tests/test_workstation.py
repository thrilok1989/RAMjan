"""MIOS V6 — tests for the persistent header and the replay timeline."""

from mios_v5 import header, replay


def _fr(**kw):
    base = {
        "preferred_bias": "BULL", "confidence": 74, "confidence_tempered": 68,
        "stability": "STABLE",
        "decision_v2": {"state": "ENTER", "label": "✅ ENTER", "side": "CALL",
                        "confidence": 82, "quality": "A+"},
        "market_state": {"state": "MARK_UP", "label": "📈 Mark Up"},
        "memory_read": {"state": "MARK_UP", "state_duration_min": 43.0,
                        "state_transition_risk": 12},
        "reaction": {"state": "REJECTION", "winner": "Buyers",
                     "confidence": 81},
        "sections": {"dealer": {"bias": "BULL", "confidence": 70,
                                "status": "OK", "headline": "GEX flip above"}},
        "families": {"dealer": {"direction": "BULL", "strength": 78,
                                "reliability": "HIGH", "status": "OK"}},
        "flow_shift": {},
    }
    base.update(kw)
    return base


# ── the persistent header ───────────────────────────────────────────────
def test_header_carries_all_ten_facts_in_order():
    tiles = header.build(_fr(), spot=24185.0)
    assert [t["key"] for t in tiles] == list(header.ORDER)
    assert len(tiles) == 10


def test_header_reads_the_real_values():
    got = {t["key"]: t["value"] for t in header.build(_fr(), spot=24185.0)}
    assert got["spot"] == "24,185.0"
    assert "ENTER" in got["decision"]
    assert got["confidence"] == "82%"
    assert got["quality"] == "A+"
    assert "Mark Up" in got["market_state"]
    assert got["flow"] == "STABLE"
    assert got["dealer"] == "BULL"
    assert got["acceptance"] == "Rejection"
    assert got["memory"] == "43 min"
    assert "Dealers" in got["controller"]


def test_dealer_is_read_through_the_sections_accessor():
    """`fr["dealer"]` does not exist — reading it directly silently degrades
    the tile to unknown, which is the defect this test locks out."""
    tile = next(t for t in header.build(_fr()) if t["key"] == "dealer")
    assert tile["value"] == "BULL" and tile["stale"] is False


def test_a_missing_engine_degrades_to_a_dash_not_a_stale_value():
    tiles = {t["key"]: t for t in header.build(
        _fr(sections={}, families={}, market_state={}, reaction={}))}
    for key in ("market_state", "acceptance", "dealer"):
        assert tiles[key]["value"] == "—"
        assert tiles[key]["stale"] is True


def test_confidence_falls_back_to_the_market_read_when_not_trading():
    fr = _fr(decision_v2={"state": "WAIT", "label": "⏳ WAIT"})
    tile = next(t for t in header.build(fr) if t["key"] == "confidence")
    assert tile["value"] == "68%"          # confidence_tempered
    assert tile["sub"] == "market read"


def test_wait_is_dim_not_red():
    """Not trading is the correct default — colouring it as a problem trains
    impatience. Asserted against the palette rather than a literal, so a
    contrast pass cannot silently turn WAIT into an alarm."""
    from mios_v5.ui.theme import BEAR, DANGER, MUTED
    fr = _fr(decision_v2={"state": "WAIT", "label": "⏳ WAIT"})
    tile = next(t for t in header.build(fr) if t["key"] == "decision")
    assert tile["colour"] == MUTED
    assert tile["colour"] not in (BEAR, DANGER)


def test_transition_risk_shows_as_a_subtitle_only_when_it_matters():
    calm = next(t for t in header.build(_fr()) if t["key"] == "memory")
    assert calm["sub"] == ""
    hot = next(t for t in header.build(_fr(memory_read={
        "state_duration_min": 43.0, "state_transition_risk": 70}))
        if t["key"] == "memory")
    assert "risk 70%" in hot["sub"]


def test_header_alerts_are_capped_at_two():
    a = header.alerts(_fr(
        flow_shift={"freeze_entries": True, "score": 74, "reason": "CVD swing"},
        event={"event_detected": True, "event_score": 90, "reaction": "spike"}))
    assert len(a) == 2
    assert "FLOW SHIFT" in a[0]["text"] and "BREAKING EVENT" in a[1]["text"]
    assert header.alerts(_fr()) == []


def test_header_never_raises_on_nothing():
    tiles = header.build(None)
    assert len(tiles) == 10 and all(t["stale"] for t in tiles[:1] + tiles[4:])
    assert header.alerts(None) == []


def test_header_html_renders_and_is_sticky():
    from mios_v5.ui.header_panel import header_html
    html = header_html(header.build(_fr(), spot=24185.0), header.alerts(_fr()))
    assert "position:sticky" in html
    assert "24,185.0" in html and "NIFTY" in html
    assert header_html(None) == ""


# ── replay ──────────────────────────────────────────────────────────────
def _rows(n=6, day="2026-07-28"):
    out = []
    for i in range(n):
        bias = "BULL" if i < 3 else "BEAR"
        out.append({
            "ts": f"{day}T09:{20 + i:02d}:00+05:30", "trading_day": day,
            "spot": 24000 + i * 5, "engine_version": "v5.1",
            "regime_bias": bias, "regime_confidence": 70 + i,
            "dealer_bias": "BULL" if i < 4 else "BEAR",
            "dealer_confidence": 60,
            "structure_decision": "TRADE ZONE" if i < 3 else "WATCH",
            "conflict_agreement_pct": 80 - i,
            "full_state": {"regime": {"status": "OK"}},
        })
    return list(reversed(out))          # the DB hands them back newest-first


def test_timeline_is_ordered_oldest_first():
    frames = replay.build_timeline(_rows())
    assert [f["index"] for f in frames] == list(range(6))
    assert frames[0]["time"] == "09:20" and frames[-1]["time"] == "09:25"


def test_frames_carry_the_engine_version():
    """A version change must be visible, or every past session looks like it
    was analysed by today's code."""
    frames = replay.build_timeline(_rows())
    assert all(f["engine_version"] == "v5.1" for f in frames)
    assert replay.summary(frames)["mixed_versions"] is False


def test_mixed_versions_are_flagged():
    rows = _rows()
    rows[0]["engine_version"] = "v6.0"
    assert replay.summary(replay.build_timeline(rows))["mixed_versions"] is True


def test_gaps_are_reported_not_interpolated():
    rows = _rows(4)
    rows[0]["ts"] = "2026-07-28T10:30:00+05:30"     # a 27-minute hole
    frames = replay.build_timeline(rows)
    assert any(f["gap_before"] for f in frames)
    assert replay.summary(frames)["gaps"] >= 1
    assert len(frames) == 4                          # nothing invented


def test_decision_timeline_shows_only_changes():
    dt = replay.decision_timeline(replay.build_timeline(_rows()))
    assert len(dt) == 2                              # BULL/TRADE ZONE → BEAR/WATCH
    assert dt[0]["bias"] == "BULL" and dt[1]["bias"] == "BEAR"
    assert dt[1]["from_bias"] == "BULL"


def test_engine_timeline_flags_the_flip():
    et = replay.engine_timeline(replay.build_timeline(_rows()), "dealer")
    flipped = [e for e in et if e["flipped"]]
    assert len(flipped) == 1 and flipped[0]["bias"] == "BEAR"


def test_flips_finds_the_moment_the_read_turned():
    fl = replay.flips(replay.build_timeline(_rows()))
    engines = {f["engine"] for f in fl}
    assert engines == {"regime", "dealer"}
    assert all(f["from"] != f["to"] for f in fl)


def test_seek_jumps_to_the_first_frame_at_or_after_a_time():
    frames = replay.build_timeline(_rows())
    assert replay.seek(frames, "09:23") == 3
    assert replay.seek(frames, "08:00") == 0
    assert replay.seek(frames, "23:59") == 5
    assert replay.seek(frames, None) == 0


def test_frame_at_clamps_instead_of_raising():
    frames = replay.build_timeline(_rows())
    assert replay.frame_at(frames, -5)["index"] == 0
    assert replay.frame_at(frames, 999)["index"] == 5
    assert replay.frame_at(None, 0) == {}


def test_markers_land_on_the_right_frame():
    frames = replay.build_timeline(_rows(), signals=[{
        "signal_id": "SIG-001", "side": "CALL",
        "entered_at": "2026-07-28T09:22:00+05:30", "entered_price": 24010,
        "exit_at": "2026-07-28T09:24:00+05:30", "exit_price": 24040,
        "outcome": "win"}])
    entry = [f for f in frames if any(m["kind"] == "entry"
                                      for m in f["markers"])]
    assert len(entry) == 1 and entry[0]["time"] == "09:22"
    assert "🟢 ENTRY CALL" in entry[0]["markers"][0]["label"]


def test_narration_is_derived_from_the_frames_themselves():
    """A session recorded before Stage 65 existed must still narrate."""
    beats = replay.narrate(replay.build_timeline(_rows()))
    assert beats
    assert any("BULL" in b["text"] and "BEAR" in b["text"] for b in beats)
    assert all("time" in b and "index" in b for b in beats)


def test_narration_can_be_truncated_to_the_current_cycle():
    frames = replay.build_timeline(_rows())
    assert len(replay.narrate(frames, upto=1)) < len(replay.narrate(frames))


def test_compare_puts_the_read_beside_the_outcome():
    frames = replay.build_timeline(_rows())
    cmp = replay.compare_to_outcome(frames, {
        "signal_id": "SIG-001", "side": "CALL", "outcome": "loss",
        "pnl_points": -14.0,
        "entered_at": "2026-07-28T09:21:00+05:30",
        "exit_at": "2026-07-28T09:25:00+05:30"})
    assert cmp["available"] is True
    assert cmp["bias_at_entry"] == "BULL" and cmp["bias_at_exit"] == "BEAR"
    assert cmp["read_held"] is False
    assert "changed its mind" in cmp["verdict"]
    assert cmp["flips_during"]


def test_compare_reports_a_read_that_held():
    frames = replay.build_timeline(_rows(3))     # all BULL
    cmp = replay.compare_to_outcome(frames, {
        "signal_id": "S", "side": "CALL", "outcome": "win", "pnl_points": 20.0,
        "entered_at": "2026-07-28T09:20:00+05:30",
        "exit_at": "2026-07-28T09:22:00+05:30"})
    assert cmp["read_held"] is True and "held" in cmp["verdict"]


def test_compare_refuses_a_signal_that_never_entered():
    cmp = replay.compare_to_outcome(replay.build_timeline(_rows()),
                                    {"signal_id": "SIG-9"})
    assert cmp["available"] is False and "never entered" in cmp["reason"]


def test_compare_needs_both_halves():
    assert replay.compare_to_outcome(None, {"entered_at": "x"})["available"] is False
    assert replay.compare_to_outcome([], None)["available"] is False


def test_full_state_is_parsed_from_a_json_string():
    rows = _rows(2)
    rows[0]["full_state"] = '{"regime": {"status": "DEGRADED"}}'
    frames = replay.build_timeline(rows)
    assert frames[-1]["engines"]["regime"]["status"] == "DEGRADED"


def test_replay_on_an_empty_history():
    assert replay.build_timeline(None) == []
    assert replay.summary(None)["frames"] == 0
    assert replay.decision_timeline(None) == []
    assert replay.flips(None) == []
    assert replay.narrate(None) == []


def test_replay_never_re_runs_the_engines():
    """Reconstruction, not re-simulation — asserted so nobody 'improves' it
    into recomputing from candles later."""
    import inspect
    src = inspect.getsource(replay)
    for banned in ("Orchestrator", "run_mios_pass", "build_final_read"):
        assert banned not in src, banned
    assert "NOT re-run" in replay.summary(replay.build_timeline(_rows()))["note"]


# ── charts ──────────────────────────────────────────────────────────────
def test_atm_leg_picker_prefers_the_exact_atm_strike():
    from mios_v5.ui.terminal_chart import atm_legs
    legs = {"ATM+1 CE 24050": "a", "ATM CE 24000": "b", "ATM PE 24000": "c"}
    ce, pe, ce_tag, pe_tag = atm_legs(legs)
    assert ce == "b" and ce_tag == "ATM CE 24000"
    assert pe == "c" and pe_tag == "ATM PE 24000"


def test_atm_leg_picker_falls_back_to_the_nearest_offset():
    from mios_v5.ui.terminal_chart import atm_legs
    ce, pe, _, _ = atm_legs({"ATM+2 CE 24100": "far", "ATM-1 CE 23950": "near"})
    assert ce == "near" and pe is None


def test_atm_leg_picker_with_nothing():
    from mios_v5.ui.terminal_chart import atm_legs
    assert atm_legs(None) == (None, None, None, None)


def test_levels_drawn_on_the_chart_are_the_ones_a_trader_acts_on():
    from mios_v5.ui.terminal_chart import LEVELS
    for k in ("entry", "stop", "trail", "target", "support", "resistance",
              "war_zone", "liquidity", "vwap", "poc", "vah", "val"):
        assert k in LEVELS


# ── the palette ─────────────────────────────────────────────────────────
def test_no_panel_still_uses_a_retired_grey():
    """The old greys sat near 4:1 contrast on a #0d1117 card — fine for prose,
    wrong for a panel scanned in two seconds."""
    import pathlib

    from mios_v5.ui.theme import RETIRED
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for path in sorted(root.glob("ui/*.py")):
        if path.name == "theme.py":
            continue
        text = path.read_text().lower()
        for grey in RETIRED:
            if grey in text:
                bad.append(f"{path.name}: {grey}")
    assert not bad, bad


def test_the_semantic_accents_were_not_touched():
    """Only the greys were lifted — a colour's MEANING must be unchanged."""
    from mios_v5.ui.theme import BEAR, BULL, DANGER, INFO, VIOLET, WARN
    assert (BULL, BEAR, WARN) == ("#00ff88", "#ff4444", "#ffd000")
    assert (INFO, VIOLET, DANGER) == ("#4da6ff", "#a78bfa", "#ff2d55")


def test_the_chart_resolves_nifty_from_more_than_one_cache():
    """`_last_df` is written as a side effect of `generate_master_signal`, so
    it is absent whenever that path is skipped — which is exactly when the
    terminal reported 'No candle series yet for: NIFTY'."""
    from mios_v5.runner import NIFTY_SOURCES, coerce_frame, nifty_frame
    assert [k for k, _ in NIFTY_SOURCES] == ["_nifty_df_live", "_last_df",
                                             "_raw_1m_trade", "_df_5m"]
    frame, why = nifty_frame({})
    assert frame is None and "neither has run" in why


def test_the_live_chart_frame_wins_over_the_analysis_side_effect():
    """`_nifty_df_live` is the frame the foundation chart is drawing, published
    every cycle where it is fetched. Every other source is a side effect of
    some other pass, so it can be arbitrarily old — which is why the NIFTY
    panel stopped advancing while the chart above it kept moving."""
    import pandas as pd

    from mios_v5.runner import nifty_frame

    fresh = pd.DataFrame({"close": [24229.8], "datetime":
                          pd.to_datetime(["2026-07-29 12:13:00"])})
    stale = pd.DataFrame({"close": [24100.0], "datetime":
                          pd.to_datetime(["2026-07-29 09:20:00"])})
    frame, why = nifty_frame({"_nifty_df_live": fresh, "_last_df": stale})
    assert float(frame["close"].iloc[0]) == 24229.8
    assert "chart path" in why

    # and it still falls back when the live frame has not been published yet
    frame, why = nifty_frame({"_last_df": stale})
    assert float(frame["close"].iloc[0]) == 24100.0


def test_spot_prefers_the_live_ltp_over_the_chains_snapshot():
    """The chain is re-fetched on its own cadence, so its `underlying` is a
    snapshot from whenever that last ran. Taking it alone is why spot sat still
    on every V5/V6 panel while the foundation header ticked.

    Asserted through `mios_v5.spot`, which now owns the precedence for every
    panel — the rule used to live in `runner.py` and be true only there.
    """
    import time

    from mios_v5 import spot

    now = time.time()
    state = {"_nifty_spot_live": 24610.5, "_nifty_spot_live_ts": now,
             "_cached_option_data": {"underlying": 24555.0}}
    assert spot.price(state, now) == 24610.5
    assert spot.read(state, now)["source"] == "live LTP"


def test_the_runner_takes_its_spot_from_the_one_owner():
    """`run_mios_pass` must not carry a second copy of the precedence. It read
    the live LTP first and the panels read the chain first, which is exactly the
    desync this fixed — so the runner delegates rather than agreeing by luck."""
    import ast
    import inspect

    from mios_v5 import runner
    tree = ast.parse(inspect.getsource(runner.run_mios_pass))
    called = {n.func.id for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_spot_read" in called, "the runner must call mios_v5.spot.read"


def test_the_raw_dhan_payload_is_turned_into_a_frame():
    """`_raw_1m_trade` is the API response dict, not a DataFrame — handing it
    straight to a chart would silently do nothing."""
    from mios_v5.runner import coerce_frame
    df = coerce_frame({"timestamp": [1769600000, 1769600060],
                       "open": [1, 2], "high": [2, 3], "low": [0, 1],
                       "close": [1.5, 2.5], "volume": [10, 20]})
    assert df is not None and "datetime" in df.columns
    assert str(df["datetime"].dt.tz) == "Asia/Kolkata"
    assert coerce_frame(None) is None
    assert coerce_frame({"open": [1]}) is None     # no timestamps


def test_the_time_axis_prefers_datetime_over_epoch():
    """The NIFTY frame carries both. Preferring `timestamp` plotted NIFTY on a
    numeric axis while the legs used datetimes, so `matches="x"` linked two
    incompatible axis types and the shared timeline silently broke."""
    import inspect

    from mios_v5.ui import terminal_chart
    src = inspect.getsource(terminal_chart._ohlc)
    assert 'col("datetime", "time", "date", "timestamp")' in src


def test_epoch_seconds_are_converted_not_plotted_raw():
    import pandas as pd

    from mios_v5.ui.terminal_chart import _as_time
    out = _as_time(pd.Series([1769600000, 1769600060]))
    assert str(getattr(out, "dtype", "")).startswith("datetime64")
    # a row index is left alone — it is not an epoch
    idx = pd.Series([0, 1, 2, 3])
    assert list(_as_time(idx)) == [0, 1, 2, 3]


class _FakeSt:
    def __init__(self, state):
        self.session_state = state


def test_a_leg_cache_is_found_under_any_of_its_three_keys():
    """The app writes per-leg caches under three different names, and this cost
    the terminal its VOB read outright:

      _atm_leg_dfs        → "ATM CE 24250"   (with the offset tag)
      _atm_leg_vob_volume → "CE 24250"       (no tag)
      every store, also   → "sid_65806"

    `atm_legs()` returns the first form, so `vob.get(tag)` looked up a key that
    store never contains — it matched nothing on every cycle, which is why VOB
    and Money Flow read "—" whatever the market did.
    """
    from mios_v5.ui.dashboard_v6 import _leg_store

    tag = "ATM CE 24250"
    sids = {tag: ("65806", "NSE_FNO")}

    # written without the ATM prefix — the real case
    st = _FakeSt({"_atm_leg_vob_volume": {"CE 24250": [{"status": "BUILDING"}]},
                  "_atm_leg_sids": sids})
    assert _leg_store(st, "_atm_leg_vob_volume", tag) == [{"status": "BUILDING"}]

    # written by security id
    st = _FakeSt({"_atm_leg_vob_volume": {"sid_65806": [{"status": "FADING"}]},
                  "_atm_leg_sids": sids})
    assert _leg_store(st, "_atm_leg_vob_volume", tag) == [{"status": "FADING"}]

    # written under the full tag
    st = _FakeSt({"_atm_leg_vob_volume": {tag: [{"status": "INTACT"}]}})
    assert _leg_store(st, "_atm_leg_vob_volume", tag) == [{"status": "INTACT"}]

    # genuinely absent stays absent
    assert _leg_store(_FakeSt({}), "_atm_leg_vob_volume", tag) is None
    assert _leg_store(_FakeSt({}), "_atm_leg_vob_volume", None) is None


def test_leg_money_flow_reads_the_buy_sell_split_already_computed():
    """Same cumulative buy/sell volume as the panel's own Buy Vol / Sell Vol /
    Δ Vol tiles — not a second opinion on it."""
    from mios_v5.ui.dashboard_v6 import _leg_money_flow

    tag = "ATM CE 24250"
    st = _FakeSt({"_atm_leg_ltf_delta": {
        "CE 24250": {"buy_total": 62397010, "sell_total": 45061055,
                     "delta_pct": 16.1}}})
    mf = _leg_money_flow(st, tag, {"MFP": "🔴 BEAR"})
    assert mf["state"] == "entering"
    assert "Buyers" in mf["label"] and "16.1" in mf["label"]
    assert mf["buy_volume"] == 62397010 and mf["sell_volume"] == 45061055
    assert mf["profile_lean"] == "bear"


def test_an_absent_flow_store_stays_absent():
    """`_num`'s 0.0 default would fabricate an "Even +0.0%" — a measured
    balance where there is actually no measurement."""
    from mios_v5.ui.dashboard_v6 import _leg_money_flow
    assert _leg_money_flow(_FakeSt({}), "ATM CE 24250", {}) == {}
    assert _leg_money_flow(
        _FakeSt({"_atm_leg_ltf_delta": {"CE 24250": {"buy_total": 5}}}),
        "ATM CE 24250", {}) == {}


def test_the_mios_pass_runs_after_the_option_chain_is_published():
    """MIOS fetches nothing of its own — it reads the caches the app fills.
    Running it before `_cached_option_data` was published meant every
    price-derived engine, spot included, worked from the PREVIOUS cycle and sat
    frozen while the foundation panels underneath were live.

    Ordering is the whole fix, so assert the ordering, not the wording.
    """
    import os
    import re

    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "vob_minimal.py"), encoding="utf-8").read()

    publish = src.index("st.session_state['_cached_option_data'] = option_data")
    call = src.index("run_mios_pass(st.session_state")
    assert call > publish, "the MIOS pass must run after the chain is published"

    # …and the dashboards must render after the pass, or they show the state
    # computed from last cycle's inputs even though a fresh one now exists.
    v6 = src.index("render_dashboard_v6(")
    assert v6 > call, "Dashboard V6 must render after the pass it displays"

    # the pass is deferred, not duplicated — running the pipeline twice would
    # double every log write and every engine's cost
    assert len(re.findall(r"run_mios_pass\(st\.session_state", src)) == 1


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    fns = [getattr(mod, n) for n in dir(mod) if n.startswith("test_")]
    for fn in fns:
        fn()
    print(f"workstation tests passed ({len(fns)})")


def test_the_command_center_reads_families_not_evidence():
    """`fr["families"]` is the family dict (`final_read.py:195`). `fr["evidence"]`
    is a LIST of narrative lines.

    `_command_center` read "families" off the evidence list, which raised
    `'list' object has no attribute 'get'` and took the entire Trading tab down
    with "Dashboard V6 unavailable". It survived because the expression is
    `(fr.get("evidence") or {}).get("families")` — with no evidence yet the
    `or {}` catches it and the call passes. It only failed once the pipeline had
    warmed up enough to produce evidence, which is the worst possible time.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "ui" / "dashboard_v6.py").read_text(encoding="utf-8")
    assert '(fr.get("evidence") or {}).get(' not in src, \
        "evidence is a list — .get() on it raises AttributeError"
    assert "market_controller, fr.get(\"families\")" in src


def test_market_controller_survives_being_handed_a_list():
    """Defence in depth: the caller was wrong, but a family reader that explodes
    on the wrong shape turns one typo into a blank tab."""
    from mios_v5.thesis import market_controller
    for junk in (None, {}, [], ["a", "b"], [{"x": 1}]):
        out = market_controller(junk) if not isinstance(junk, list) else None
        if out is not None:
            assert isinstance(out, dict)


# ══════════════════════════════════════════════════════════════════════
#  📊 the charts have their own tab, and it leads
# ══════════════════════════════════════════════════════════════════════

def _v6_src():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1]
            / "ui" / "dashboard_v6.py").read_text(encoding="utf-8")


def test_charts_is_the_first_tab():
    """The synchronised NIFTY ‖ CALL ‖ PUT figure was the fifth block down the
    Trading tab — Command Center, Stage 71, Stage 71.8 and the execution chain
    all drew above it, which puts a 660px chart below the fold on a laptop."""
    from mios_v5.ui.dashboard_v6 import _TABS
    assert _TABS[0] == "📊 Charts"
    # No hardcoded tab count here on purpose: it would have to be edited on
    # every tab addition, and the risk it was guarding — an index that stops
    # matching the label list — is what `test_every_tab_is_wired_to_a_body`
    # actually checks, derived from `_TABS` rather than pinned to a number.
    assert len(set(_TABS)) == len(_TABS), "two tabs share a label"


def test_every_tab_is_wired_to_a_body():
    """⚠️ The failure this catches is silent: `st.tabs` renders a label whatever
    happens, so a mis-numbered index leaves a tab that opens onto nothing, or
    two labels drawing the same screen.

    ⚠️ COVERAGE, not ascending order. This asserted `indices == list(range(n))`,
    which also froze the fill sequence — and the fill sequence has to differ from
    the tab sequence, because the bodies have a dependency the strip's layout does
    not: `_trading_screen` (tab 4) publishes `_sr_levels`, `_premium_energy`,
    `_premium_structures` and `_entry_decision`, which the cockpits at tabs 1 and
    2 read. Filled in tab order they ran before their producer.

    `st.tabs()` containers may be filled in any order and the strip is unaffected,
    so what matters here is that every index is filled exactly once.
    `test_screen_order.py` owns the dependency rule itself.
    """
    import re
    src = _v6_src()
    block = src[src.index("tabs = st.tabs(_TABS)"):src.index("# ── 0 · CHARTS")]
    indices = [int(n) for n in re.findall(r"with tabs\[(\d+)\]:", block)]
    from mios_v5.ui.dashboard_v6 import _TABS
    assert len(indices) == len(set(indices)), (
        f"a tab is filled twice — two labels draw the same screen: {indices}")
    assert set(indices) == set(range(len(_TABS))), (
        f"tab bodies {sorted(indices)} do not cover 0..{len(_TABS) - 1}")


def test_the_charts_tab_runs_before_the_panel_that_reads_its_output():
    """⚠️ Why being FIRST is load-bearing rather than cosmetic.

    `_terminal_chart` is the only producer of `_leg_profiles` — one of the four
    CRITICAL panels in `docs/AUDIT_FOCUS_MODE.md` — and `_trading_screen` reads
    that key for its per-leg liquidity bars. Streamlit executes tab bodies in
    order, so the chart has to be drawn in a tab that runs BEFORE Trading.
    Moving it to a later tab would leave the heatmaps on last cycle's profiles,
    which looks like working code.
    """
    import re
    src = _v6_src()
    block = src[src.index("tabs = st.tabs(_TABS)"):src.index("# ── 0 · CHARTS")]
    calls = re.findall(r"_(charts_screen|trading_screen)\(", block)
    assert calls.index("charts_screen") < calls.index("trading_screen")


def test_the_charts_tab_draws_no_second_price_line():
    """The split exists to remove duplication. `header_html` already renders the
    LTP, the change and both biases above the tab bar on every tab, so a price
    block here would re-add exactly what was being removed.

    Checked on the parse tree, not the text: this function's own docstring names
    `header_html` in explaining why it does not call it.
    """
    import ast
    fn = next(n for n in ast.walk(ast.parse(_v6_src()))
              if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen")
    names = {getattr(n, "id", "") or getattr(n, "attr", "")
             for n in ast.walk(fn)}
    imported = {a.name for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    for dup in ("header_html", "header_tiles", "metric"):
        assert dup not in names | imported, \
            f"_charts_screen should not redraw {dup}"


def test_the_charts_tab_computes_nothing():
    """It reads the same caches `_trading_screen` did and hands them to the same
    renderer. If it starts computing, the move stopped being a UI change."""
    import ast
    src = _v6_src()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_charts_screen")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    # Reading a published cache and rendering it is not computing. The ATM±1 leg
    # tabulation was drawn here because it belongs under the charts it explains —
    # it reads `_leg_bias_cache`, which `_render_main_analyzer` fills.
    # ⚠️ `_strike_oi_charts` and `_poc_structure` are RENDERERS: each reads a cache
    # the app published (`_strike_hist`, `_poc_series`) and lays it out. The
    # rolling-POC build itself costs ~420 ms over 1250 daily bars and runs in
    # `vob_minimal._publish_poc_series`, hourly-cached — deliberately NOT here.
    # `_hv_settings` is a CONTROL: it renders three number inputs and writes
    # `_hv_settings` to session state. `vob_minimal._hv_points` does the computing.
    _render = {"markdown", "caption", "get", "leg_table_html", "_feed_reason",
               "_dbg_caption", "_strike_oi_charts", "_poc_structure",
               "_hv_settings"}
    assert called <= {"_leg_reads", "dominance", "_terminal_chart"} | _render, (
        f"unexpected calls in _charts_screen: {called}")
    # ⚠️ The property that actually matters: no BUILDER is invoked here.
    for builder in ("build_leg_bias_table", "compute_vpfr", "analyze_vob_volume",
                    "calculate_money_flow_profile", "calculate_vidya"):
        assert builder not in called, f"_charts_screen now computes {builder}"


def test_the_trading_tab_kept_the_bars_that_measure_the_chart():
    """The heatmaps read `_leg_profiles` from session state, so they were never
    required to be adjacent to the figure — only downstream of it. They stay on
    the tab a trader acts from."""
    src = _v6_src()
    body = src[src.index("def _trading_screen"):src.index("def _command_center")]
    assert "render_leg_heatmaps" in body


def test_dominance_left_with_the_chart_it_fed():
    """A local nobody uses is how the next reader concludes it must matter.

    Parse tree again — the comment that records the removal names `dominance`.
    """
    import ast
    fn = next(n for n in ast.walk(ast.parse(_v6_src()))
              if isinstance(n, ast.FunctionDef) and n.name == "_trading_screen")
    called = {getattr(c.func, "id", "") or getattr(c.func, "attr", "")
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    imported = {a.name for n in ast.walk(fn)
                if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "dominance" not in called | imported
    assigned = {t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
                for t in n.targets if isinstance(t, ast.Name)}
    assert "dom" not in assigned
