"""Stage 33 — Event Impact engine: measures the effect, never votes."""

from mios_v5.core.contract import Bias, EngineResult, MarketState, Status
from mios_v5.engines.stage33_event_impact import EventImpactEngine


def _r(engine, data, bias=Bias.NONE, conf=50.0):
    return EngineResult(engine=engine, status=Status.OK, bias=bias,
                        confidence=conf, data=data, provenance=None)


def _state(shock=False, prep=None, cal=None, day_type=None, cvd=None,
           dealer_sig=None, intent_conf=0, conflict_conf=0, conflict_bias=Bias.NEUTRAL):
    raw = {}
    if cvd is not None:
        raw["volume_delta"] = {"summary": {"delta_pct": cvd}}
    st = MarketState(raw=raw)
    st.results["stage28_event_detection"] = _r("stage28_event_detection",
        {"event_detected": shock, "reaction": "down (aggressive selling)"})
    st.results["stage24_preparation"] = _r("stage24_preparation", {"level": prep or "NORMAL"})
    st.results["stage30_calendar"] = _r("stage30_calendar", cal or {"has_event": False})
    st.results["stage04_context"] = _r("stage04_context", {"day_type": day_type or "NORMAL"})
    st.results["stage11_dealer"] = _r("stage11_dealer",
        {"gex": {"signal": dealer_sig or ""}},
        bias=Bias.STRONG_BEAR if dealer_sig else Bias.NEUTRAL)
    st.results["stage25_intent"] = _r("stage25_intent", {},
        bias=Bias.BEAR if intent_conf else Bias.NEUTRAL, conf=intent_conf)
    st.results["stage29_evolution"] = _r("stage29_evolution", {"changes": []})
    st.results["stage27_conflict"] = _r("stage27_conflict", {},
        bias=conflict_bias, conf=conflict_conf)
    return st


def _run(**kw):
    return EventImpactEngine().compute(_state(**kw))


def test_no_context_not_measuring():
    r = _run()      # no shock, no HIGH prep, no calendar event
    assert r.data["measuring"] is False and r.bias == Bias.NONE


def test_shock_high_impact():
    r = _run(shock=True, day_type="GAP-DOWN", cvd=-70, dealer_sig="gamma flip",
             intent_conf=70, conflict_conf=65, conflict_bias=Bias.BEAR)
    assert r.data["measuring"] is True
    assert r.data["impact"] in ("HIGH", "VERY HIGH")
    assert r.bias == Bias.NONE               # measures effect, never votes


def test_event_but_no_structure_change_low():
    # a scheduled event today but nothing actually moved → LOW
    r = _run(cal={"has_event": True, "next_event": {"name": "RBI Policy", "days_away": 0}})
    assert r.data["measuring"] is True
    assert r.data["impact"] == "LOW"
    assert r.data["signal_count"] == 0


def test_event_label_prefers_calendar_name():
    r = _run(cal={"has_event": True, "next_event": {"name": "US FOMC", "days_away": 1}},
             cvd=50)
    assert r.data["event"] == "US FOMC"


if __name__ == "__main__":
    for fn in [test_no_context_not_measuring, test_shock_high_impact,
               test_event_but_no_structure_change_low, test_event_label_prefers_calendar_name]:
        fn()
    print("stage33 event-impact tests passed")
