"""Higher-order option Greeks — Vomma, Speed, Zomma, Veta, Color.

Pure Black–Scholes (q=0), on the same d1/d2 the rest of the app uses. These are
the third-order Greeks MIOS never computed; adding them as a producer is what
lets the Greek-behaviour layer stop reporting them as "Not reported". They are
**verified against finite differences** of vega and gamma in
`test_higher_greeks` — the only honest way to ship a Greek formula.

    vomma  = ∂vega/∂σ    convexity of vega to vol
    zomma  = ∂gamma/∂σ   how gamma shifts as IV moves
    speed  = ∂gamma/∂S   how gamma accelerates as spot moves
    veta   = ∂vega/∂t    how vega erodes with time
    color  = ∂gamma/∂t   how gamma changes with time

Raw per-unit values (per 1.0 change in the underlying variable); the app
aggregates them OI-weighted and the behaviour layer buckets the aggregate
magnitude. Nothing here interprets — it only computes. Same value for a call and
a put at one strike and IV (q=0), exactly like vanna/charm.
"""

from __future__ import annotations

import math
from typing import Dict

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_KEYS = ("vomma", "speed", "zomma", "veta", "color")


def _pdf(x: float) -> float:
    """Standard normal density — inlined so the module needs no scipy."""
    return math.exp(-0.5 * x * x) / _SQRT_2PI


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float):
    sqrt_t = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt_t)
    return d1, d1 - sigma * sqrt_t, sqrt_t


def higher_greeks(S, K, T, r, sigma) -> Dict[str, float]:
    """`{vomma, speed, zomma, veta, color}`, raw per-unit. Zeros (never raises)
    on any non-finite or non-positive input — a Greek that cannot be computed is
    not a Greek that is zero, but the caller treats missing columns as absent, so
    a zero here only means "this one strike could not price"."""
    try:
        S, K, T, r, sigma = float(S), float(K), float(T), float(r), float(sigma)
        if not (T > 0 and sigma > 0 and S > 0 and K > 0):
            return {k: 0.0 for k in _KEYS}
        d1, d2, sqrt_t = _d1_d2(S, K, T, r, sigma)
        pdf = _pdf(d1)

        vega = S * pdf * sqrt_t                 # ∂V/∂σ, per 1.0 vol
        gamma = pdf / (S * sigma * sqrt_t)      # ∂²V/∂S²

        vomma = vega * d1 * d2 / sigma          # ∂vega/∂σ
        speed = -gamma / S * (d1 / (sigma * sqrt_t) + 1.0)   # ∂gamma/∂S
        zomma = gamma * (d1 * d2 - 1.0) / sigma              # ∂gamma/∂σ
        # ∂/∂t = -∂/∂T (calendar time runs opposite to time-to-expiry), so the
        # ∂/∂T expressions below are negated to report decay per calendar day —
        # the same convention the app's charm uses.
        veta = vega * (r * d1 / (sigma * sqrt_t)
                       - (1.0 + d1 * d2) / (2.0 * T))        # ∂vega/∂t
        color = pdf / (2.0 * S * T * sigma * sqrt_t) * (
            1.0 + d1 * (2.0 * r * T - d2 * sigma * sqrt_t) / (sigma * sqrt_t)
        )                                                    # ∂gamma/∂t

        out = {"vomma": vomma, "speed": speed, "zomma": zomma,
               "veta": veta, "color": color}
        return {k: (v if v == v and abs(v) != float("inf") else 0.0)
                for k, v in out.items()}
    except Exception:
        return {k: 0.0 for k in _KEYS}
