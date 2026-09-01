"""Stage 34 — Event Explanation engine: the 'why', only after a detector fires."""

from mios_v5.core.contract import Bias, EngineResult, MarketState, Status
from mios_v5.engines.stage34_explain import EventExplanationEngine


def _r(engine, data):
    return EngineResult(engine=engine, status=Status.OK, bias=Bias.NONE,
                        confidence=50.0, data=data, provenance=None)


def _state(prep=None, event=None, cal=None, news=None):
    st = MarketState(raw={"news": news} if news else {})
    if prep is not None:
        st.results["stage24_preparation"] = _r("stage24_preparation", prep)
    if event is not None:
        st.results["stage28_event_detection"] = _r("stage28_event_detection", event)
    if cal is not None:
        st.results["stage30_calendar"] = _r("stage30_calendar", cal)
    return st


def test_no_trigger_no_explanation():
    r = EventExplanationEngine().compute(_state(prep={"level": "NORMAL"}))
    assert r.data["explaining"] is False and r.bias == Bias.NONE


def test_preparation_explained_by_calendar():
    st = _state(prep={"level": "HIGH"},
                cal={"has_event": True, "when": "tomorrow",
                     "next_event": {"name": "RBI Policy", "importance": 5}})
    r = EventExplanationEngine().compute(st)
    assert r.data["explaining"] is True and r.data["trigger"] == "preparation"
    assert r.data["possible_causes"][0]["cause"].startswith("RBI Policy")
    assert r.data["confidence_label"] == "High"


def test_shock_explained_by_news():
    st = _state(event={"event_detected": True},
                news={"rows": [{"title": "Trump announces new tariffs", "score": -1, "age_min": 5}]})
    r = EventExplanationEngine().compute(st)
    assert r.data["explaining"] is True and r.data["trigger"] == "shock"
    assert any("tariff" in c["cause"].lower() for c in r.data["possible_causes"])


def test_trigger_but_no_cause():
    r = EventExplanationEngine().compute(_state(event={"event_detected": True}))
    assert r.data["explaining"] is True and r.data["possible_causes"] == []
    assert "monitoring" in r.evidence[0].lower()


def test_never_votes_direction():
    st = _state(event={"event_detected": True},
                cal={"has_event": True, "when": "today",
                     "next_event": {"name": "Fed", "importance": 5}})
    r = EventExplanationEngine().compute(st)
    assert r.bias == Bias.NONE       # explains, never a directional vote


if __name__ == "__main__":
    for fn in [test_no_trigger_no_explanation, test_preparation_explained_by_calendar,
               test_shock_explained_by_news, test_trigger_but_no_cause,
               test_never_votes_direction]:
        fn()
    print("stage34 explain tests passed")
