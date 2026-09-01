"""Finite-difference verification of the higher-order Greeks.

A Greek formula is only trustworthy if it matches the numerical derivative it
claims to be. Each test perturbs the underlying variable of a *local*
Black–Scholes vega/gamma reference and checks that `higher_greeks` reproduces the
slope:

    vomma ≈ ∂vega/∂σ      speed ≈ ∂gamma/∂S      zomma ≈ ∂gamma/∂σ
    veta  ≈ ∂vega/∂t = -∂vega/∂T
    color ≈ ∂gamma/∂t = -∂gamma/∂T

The references are recomputed here (not imported) so the test is an independent
witness, not a restatement of the module under test.
"""

import math

from mios_v5.higher_greeks import higher_greeks

_SQRT_2PI = math.sqrt(2.0 * math.pi)


def _pdf(x):
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1(S, K, T, r, sigma):
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _vega(S, K, T, r, sigma):
    return S * _pdf(_d1(S, K, T, r, sigma)) * math.sqrt(T)


def _gamma(S, K, T, r, sigma):
    return _pdf(_d1(S, K, T, r, sigma)) / (S * sigma * math.sqrt(T))


# A representative near-the-money weekly, plus an ITM/OTM/high-vol spread so the
# checks are not accidentally passing at one convenient point.
_CASES = [
    (100.0, 100.0, 30.0 / 365, 0.06, 0.20),   # ATM monthly
    (100.0, 100.0, 7.0 / 365, 0.06, 0.18),    # ATM weekly
    (24500.0, 24600.0, 3.0 / 365, 0.07, 0.14),  # NIFTY-like OTM call strike
    (24500.0, 24300.0, 3.0 / 365, 0.07, 0.16),  # ITM
    (100.0, 110.0, 60.0 / 365, 0.05, 0.35),   # far OTM, high vol
]


def _rel_close(a, b, tol=2e-3, floor=1e-9):
    """Relative agreement, with an absolute floor so ~0 references don't blow up."""
    denom = max(abs(a), abs(b), floor)
    return abs(a - b) / denom < tol


def test_vomma_matches_dvega_dsigma():
    for S, K, T, r, sigma in _CASES:
        h = 1e-5
        num = (_vega(S, K, T, r, sigma + h) - _vega(S, K, T, r, sigma - h)) / (2 * h)
        assert _rel_close(higher_greeks(S, K, T, r, sigma)["vomma"], num), (S, K)


def test_speed_matches_dgamma_dS():
    for S, K, T, r, sigma in _CASES:
        h = S * 1e-5
        num = (_gamma(S + h, K, T, r, sigma) - _gamma(S - h, K, T, r, sigma)) / (2 * h)
        assert _rel_close(higher_greeks(S, K, T, r, sigma)["speed"], num), (S, K)


def test_zomma_matches_dgamma_dsigma():
    for S, K, T, r, sigma in _CASES:
        h = 1e-5
        num = (_gamma(S, K, T, r, sigma + h) - _gamma(S, K, T, r, sigma - h)) / (2 * h)
        assert _rel_close(higher_greeks(S, K, T, r, sigma)["zomma"], num), (S, K)


def test_veta_matches_dvega_dt():
    # ∂/∂t = -∂/∂T
    for S, K, T, r, sigma in _CASES:
        h = T * 1e-5
        dvega_dT = (_vega(S, K, T + h, r, sigma) - _vega(S, K, T - h, r, sigma)) / (2 * h)
        assert _rel_close(higher_greeks(S, K, T, r, sigma)["veta"], -dvega_dT), (S, K)


def test_color_matches_dgamma_dt():
    for S, K, T, r, sigma in _CASES:
        h = T * 1e-5
        dgamma_dT = (_gamma(S, K, T + h, r, sigma) - _gamma(S, K, T - h, r, sigma)) / (2 * h)
        assert _rel_close(higher_greeks(S, K, T, r, sigma)["color"], -dgamma_dT), (S, K)


def test_call_put_symmetric_and_strike_independent_sign():
    # q=0 ⇒ these are strike-symmetric in the same sense vanna/charm are: one
    # value per (S,K,T,σ). Just assert the producer is deterministic & finite.
    a = higher_greeks(100.0, 100.0, 0.1, 0.05, 0.2)
    b = higher_greeks(100.0, 100.0, 0.1, 0.05, 0.2)
    assert a == b
    for v in a.values():
        assert math.isfinite(v)


def test_bad_input_returns_zeros_never_raises():
    for bad in [
        (0.0, 100.0, 0.1, 0.05, 0.2),      # S=0
        (100.0, 0.0, 0.1, 0.05, 0.2),      # K=0
        (100.0, 100.0, 0.0, 0.05, 0.2),    # expired
        (100.0, 100.0, -0.1, 0.05, 0.2),   # negative T
        (100.0, 100.0, 0.1, 0.05, 0.0),    # zero vol
        (float("nan"), 100.0, 0.1, 0.05, 0.2),
        (None, 100.0, 0.1, 0.05, 0.2),
    ]:
        out = higher_greeks(*bad)
        assert out == {"vomma": 0.0, "speed": 0.0, "zomma": 0.0,
                       "veta": 0.0, "color": 0.0}


def test_keys_are_exactly_the_five():
    out = higher_greeks(100.0, 100.0, 0.1, 0.05, 0.2)
    assert set(out) == {"vomma", "speed", "zomma", "veta", "color"}
