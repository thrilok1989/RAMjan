"""Stage 24 — Institutional Preparation engine: non-directional coiling detector."""

from mios_v5.core.contract import (Bias, EngineResult, MarketState, Status, Tier)
from mios_v5.engines.stage24_preparation import PreparationEngine


def _mk(engine, ok=True, bias=Bias.NONE, data=None):
    return EngineResult(engine=engine, status=Status.OK if ok else Status.MISSING,
                        bias=bias, confidence=50.0, data=data or {},
                        provenance=None)


def _state(compression=None, breakout=None, vix_dir=None, gex_sig=None,
           skew=None, doi_label=None):
    st = MarketState(raw={})
    st.results["stage04_context"] = _mk("stage04_context",
        data={"compression": compression, "breakout_risk": breakout})
    st.results["stage22_vix"] = _mk("stage22_vix", data={"direction": vix_dir})
    st.results["stage11_dealer"] = _mk("stage11_dealer",
        data={"gex": {"signal": gex_sig or ""}, "skew": skew or {}})
    st.results["stage12_options"] = _mk("stage12_options",
        data={"doi_bias": {"label": doi_label or ""}})
    return st


def _run(**kw):
    return PreparationEngine().compute(_state(**kw))


def test_non_directional_always():
    # even with strong coiling it never emits a direction
    r = _run(compression=85, breakout=82, vix_dir="Rising",
             gex_sig="coiled spring / trend", doi_label="writers building")
    assert r.bias == Bias.NONE


def test_high_preparation_detected():
    r = _run(compression=85, breakout=82, vix_dir="Rising",
             gex_sig="gamma flip", doi_label="PE writers building support")
    assert r.data["level"] == "HIGH"
    assert r.data["signals_fired"] >= 3
    assert r.data["cause"] == "unknown"
    assert r.confidence > 0


def test_quiet_market_normal():
    r = _run(compression=20, breakout=15, vix_dir="Falling")
    assert r.data["level"] == "NORMAL"
    assert r.confidence == 0.0


def test_partial_is_elevated_or_normal():
    r = _run(compression=70, vix_dir="Rising")     # 2 signals
    assert r.data["level"] in ("ELEVATED", "NORMAL")


if __name__ == "__main__":
    for fn in [test_non_directional_always, test_high_preparation_detected,
               test_quiet_market_normal, test_partial_is_elevated_or_normal]:
        fn()
    print("stage24 preparation tests passed")
