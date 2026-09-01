"""MIOS V5 Phase-E tests — narrative, learning, temporal engines.

    python -m mios_v5.tests.test_phase_e
"""

from __future__ import annotations

import sys
from datetime import datetime, time as dtime, timedelta

import pytz

from mios_v5.core import Bias, Status
from mios_v5.final_read import build_final_read
from mios_v5.narrative import build_briefing, build_market_story
from mios_v5.runner import build_orchestrator
from mios_v5.tests.test_phase_c import _raw_at_support

IST = pytz.timezone("Asia/Kolkata")


def test_narrative_story_and_briefing():
    st = build_orchestrator().run(_raw_at_support())
    fr = build_final_read(st)
    story = build_market_story(st, fr)
    briefing = build_briefing(st, fr)
    assert isinstance(story, str) and len(story) > 30
    assert "support" in story.lower() and "₹24200" in story
    # no buy/sell language
    for banned in ("buy ", "sell ", "BUY", "SELL"):
        assert banned not in story
    assert "Institutional Market Summary" in briefing and "no buy/sell" in briefing.lower()
    # completeness: the Stage-37 briefing reads as a morning desk note with
    # every major section present
    for section in ("Market State", "Institutional View", "Dealer Position",
                    "Order Flow", "Options Bias", "Key Price Map",
                    "Strong Support", "Strong Resistance", "Battle Zone",
                    "External Influence", "Risk Monitor",
                    "Most Probable Scenarios", "AI Market Story",
                    "Evidence Summary", "Overall Evidence"):
        assert section in briefing, f"briefing missing section: {section}"
    # story engine mirrors it
    se = st.get("stage36_story")
    assert se.status == Status.OK and se.data["story"] == story


def test_timegated_engines_idle_during_session():
    st = build_orchestrator().run({**_raw_at_support(),
                                   "now_ist_time": dtime(11, 0)})
    pm = st.get("stage39_premarket")
    tm = st.get("stage38_tomorrow")
    assert pm.data["active"] is False        # 11:00 → not pre-market
    assert tm.data["active"] is False        # 11:00 → not post-close


def test_premarket_active_before_open():
    raw = _rich_premarket()
    raw["now_ist_time"] = dtime(8, 45)
    st = build_orchestrator().run(raw)
    pm = st.get("stage39_premarket")
    assert pm.data["active"] is True and "Pre-market" in pm.data["brief"]


def test_tomorrow_active_after_close():
    raw = {**_raw_at_support(), "now_ist_time": dtime(15, 40)}
    st = build_orchestrator().run(raw)
    tm = st.get("stage38_tomorrow")
    assert tm.data["active"] is True
    assert "carry support" in tm.data["report"] or tm.data.get("tomorrow_support")


def test_learning_grade_and_accuracy():
    """Fake DB: one open BULL prediction that rose → graded correct; accuracy
    summary reflects it."""
    now = datetime.now(IST)
    made = now - timedelta(minutes=20)
    db = _FakeDB(open_preds=[{
        "id": 1, "spot_at": 24000.0, "preferred_bias": "BULL",
        "due_at": (made + timedelta(minutes=15)).isoformat(),
        "confidence": 75, "resolved_at": None}])
    raw = {**_raw_at_support(), "db": db, "spot": 24120.0,   # +0.5% → BULL correct
           "now_ist_dt": now, "now_ist_time": now.time(),
           "_mios_pred_state": {"last_pred_ts": 9e18}}       # block new logging
    st = build_orchestrator().run(raw)
    le = st.get("stage40_learning")
    assert le.status == Status.OK
    assert le.data["resolved_this_pass"] == 1
    assert db.graded and db.graded[0][1]["correct"] is True
    # after grading, the fake db serves it as resolved → accuracy 100%
    assert le.data["accuracy"]["n"] >= 1


def _rich_premarket():
    return {
        "api_ok": True, "db_ok": True,
        "market_picture": {
            "global_bias": {"label": "BULL", "score": 2.0},
            "commodity_bias": {"regime": "Risk-On"},
            "news_bias": {"label": "BULL", "em": "🟢", "net": 2, "n": 8},
        },
    }


class _FakeDB:
    is_connected = True

    def __init__(self, open_preds):
        self._open = open_preds
        self.graded = []       # (id, fields)

    def get_open_bias_predictions(self, limit=100):
        return [p for p in self._open if not p.get("resolved_at")]

    def update_bias_prediction(self, row_id, fields):
        self.graded.append((row_id, fields))
        for p in self._open:
            if p["id"] == row_id:
                p.update(fields)
        return True

    def insert_bias_prediction(self, row):
        return None

    def get_bias_predictions(self, limit=1000, resolved_only=True):
        rows = [p for p in self._open if p.get("correct") is not None]
        return rows

    def insert_engine_error(self, row):
        return True


def test_pin_leads_story_and_briefing():
    """When price is pinned (same strike = biggest CE + PE wall), the story and
    briefing lead with the pin / no-edge, not a directional bias."""
    from mios_v5.narrative import build_briefing
    raw = _raw_at_support()
    raw["market_picture"]["oi_pin"] = (24200.0, "balanced walls — expect chop, no edge")
    st = build_orchestrator().run(raw)
    fr = build_final_read(st)
    story = build_market_story(st, fr)
    assert "pinned at ₹24200" in story.lower()
    b = build_briefing(st, fr)
    assert "PINNED at ₹24200" in b
    assert "Pin / Range Day" in b
    assert "PIN / Magnet" in b


def test_memory_engine_with_wired_input():
    """Defect fix 1: stage03 reports prev-day levels when market_memory is fed."""
    raw = {**_raw_at_support(),
           "market_memory": {"prev_high": 24280.0, "prev_low": 24080.0,
                             "prev_close": 24150.0}}
    st = build_orchestrator().run(raw)
    mem = st.get("stage03_memory")
    assert mem.status == Status.OK
    assert any("PDH" in e for e in mem.evidence)
    assert any("vs close" in e for e in mem.evidence)   # gap vs prev close


def test_health_tempers_confidence():
    """Defect fix 3: a degraded pipeline reports LOWER headline confidence."""
    from mios_v5.final_read import build_final_read as _bfr
    good = _bfr(build_orchestrator().run(_raw_at_support()))
    bad_raw = {**_raw_at_support(), "token_expired": True, "api_ok": None}
    bad = _bfr(build_orchestrator().run(bad_raw))
    assert bad["confidence_tempered"] < good["confidence_tempered"], \
        f"degraded {bad['confidence_tempered']} !< healthy {good['confidence_tempered']}"


def test_memory_levels_join_price_map():
    """Stage-3 output is now consumed: PDL/PDH join the reaction-zone level
    candidates (nearest wins) and prev-day flows into final read + briefing."""
    from mios_v5.narrative import build_briefing
    raw = _raw_at_support()                    # spot 24205
    raw["market_memory"] = {"prev_high": 24520.0, "prev_low": 24190.0,
                            "prev_close": 24150.0}
    raw["market_picture"]["sup"] = dict(raw["market_picture"]["sup"],
                                        price=24100)   # far → PDL is closer
    st = build_orchestrator().run(raw)
    rz = st.get("stage35_reaction_zone")
    assert rz.data["strong_support"] == 24190.0, rz.data["strong_support"]
    assert rz.data["support_sources"] == ["PDL"]
    assert rz.data["strong_resistance"] == 24500  # res closer than PDH 24520
    fr = build_final_read(st)
    assert fr["prev_day"] and fr["prev_day"]["prev_high"] == 24520.0
    briefing = build_briefing(st, fr)
    assert "PDH" in briefing and "PDL" in briefing


def main() -> int:
    tests = [test_narrative_story_and_briefing,
             test_timegated_engines_idle_during_session,
             test_premarket_active_before_open,
             test_tomorrow_active_after_close,
             test_learning_grade_and_accuracy,
             test_memory_engine_with_wired_input,
             test_health_tempers_confidence,
             test_memory_levels_join_price_map,
             test_pin_leads_story_and_briefing]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:            # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
