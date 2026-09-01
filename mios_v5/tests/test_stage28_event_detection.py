"""Stage 28 — Event Detection engine: surprise-reaction detector."""

from mios_v5.core.contract import (Bias, EngineResult, MarketState, Status)
from mios_v5.engines.stage28_event_detection import EventDetectionEngine


def _news(bias):
    return EngineResult(engine="stage21_news", status=Status.OK, bias=bias,
                        confidence=60.0, data={}, provenance=None)


def _state(vix_hist=None, gamma_blast=None, cvd_delta=None, news_bias=None):
    st = MarketState(raw={
        "vix": {"history": vix_hist} if vix_hist else {},
        "full_market_read": {"gamma_blast": gamma_blast} if gamma_blast else {},
        "volume_delta": {"summary": {"delta_pct": cvd_delta}} if cvd_delta is not None else {},
    })
    if news_bias is not None:
        st.results["stage21_news"] = _news(news_bias)
    return st


def _run(**kw):
    return EventDetectionEngine().compute(_state(**kw))


def test_shock_detected_selling():
    # VIX spike + gamma blast + CVD collapse → breaking event, reaction down
    r = _run(vix_hist=[12, 12, 13, 15, 16], gamma_blast="HIGH", cvd_delta=-70)
    assert r.data["event_detected"] is True
    assert "down" in r.data["reaction"]
    assert r.bias == Bias.NONE           # detector never votes a direction
    assert r.confidence > 0


def test_relief_rally():
    # VIX crash + CVD surge → reaction up (short covering)
    r = _run(vix_hist=[20, 19, 18, 16, 15], cvd_delta=+65)
    assert r.data["event_detected"] is True
    assert "up" in r.data["reaction"]


def test_quiet_no_event():
    r = _run(vix_hist=[13, 13, 13, 13], cvd_delta=+5)
    assert r.data["event_detected"] is False and r.confidence == 0.0
    assert r.bias == Bias.NONE


def test_single_shock_not_enough():
    # only one signal → below the 2-shock threshold
    r = _run(cvd_delta=-70)
    assert r.data["event_detected"] is False


if __name__ == "__main__":
    for fn in [test_shock_detected_selling, test_relief_rally,
               test_quiet_no_event, test_single_shock_not_enough]:
        fn()
    print("stage28 event-detection tests passed")
