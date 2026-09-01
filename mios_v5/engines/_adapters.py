"""MIOS V5 — adapter helpers.

Phase-B engines are thin adapters: the host app already computes the heavy
analytics each cycle and stashes them in session_state
(`_market_picture`, `_full_market_read`, `_leg_bias_cache`, …); the runner
forwards those into MarketState.raw. These helpers translate that output into
the uniform contract (bias enum, 0–100 confidence, provenance tier) so no
analytic is recomputed and there is zero import coupling to vob_minimal.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..core.contract import Bias, Provenance, Tier

# string → Bias mapping (covers regime, sub-bias, and mode label variants)
_BIAS_STRINGS = {
    "up": Bias.BULL, "bull": Bias.BULL, "bullish": Bias.BULL,
    "strong_bull": Bias.STRONG_BULL, "strong bull": Bias.STRONG_BULL,
    "strong bullish": Bias.STRONG_BULL,
    "down": Bias.BEAR, "bear": Bias.BEAR, "bearish": Bias.BEAR,
    "strong_bear": Bias.STRONG_BEAR, "strong bear": Bias.STRONG_BEAR,
    "strong bearish": Bias.STRONG_BEAR,
    "sideways": Bias.SIDEWAYS, "range": Bias.SIDEWAYS, "flat": Bias.SIDEWAYS,
    "neutral": Bias.NEUTRAL, "mixed": Bias.NEUTRAL,
}


def to_bias(value: Any) -> Bias:
    """Map an arbitrary label/emoji-prefixed string to a Bias enum."""
    if value is None:
        return Bias.NONE
    s = str(value).strip().lower()
    for key, b in _BIAS_STRINGS.items():
        if key in s:
            return b
    return Bias.NEUTRAL


def bias_from_net(net: float, strong: float = 4, weak: float = 1) -> Bias:
    """Map a signed net score to a graded bias."""
    if net >= strong:
        return Bias.STRONG_BULL
    if net >= weak:
        return Bias.BULL
    if net <= -strong:
        return Bias.STRONG_BEAR
    if net <= -weak:
        return Bias.BEAR
    return Bias.NEUTRAL


_BIAS_SIGN = {
    Bias.STRONG_BULL: 2, Bias.BULL: 1, Bias.NEUTRAL: 0, Bias.NONE: 0,
    Bias.SIDEWAYS: 0, Bias.BEAR: -1, Bias.STRONG_BEAR: -2,
}


def bias_sign(b: Bias) -> int:
    """+2..-2 signed magnitude for a Bias (SIDEWAYS/NEUTRAL/NONE → 0)."""
    return _BIAS_SIGN.get(b, 0)


def clamp_conf(x: Any, default: float = 0.0) -> float:
    """Coerce to a 0–100 confidence float."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(100.0, v))


def prov(source: str, tier: Tier = Tier.DERIVED,
         freshness_ts: Optional[str] = None, notes: str = "") -> Provenance:
    return Provenance(source=source, tier=tier, freshness_ts=freshness_ts,
                      notes=notes)


def mp(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The cached `_market_picture` dict (or {})."""
    return raw.get("market_picture") or {}


def fmr(raw: Dict[str, Any]) -> Dict[str, Any]:
    """The cached `_full_market_read` dict (or {})."""
    return raw.get("full_market_read") or {}


def leg_overall(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Overall dict from `_leg_bias_cache` (tuple of (rows, overall))."""
    cache = raw.get("leg_bias_cache")
    if isinstance(cache, (list, tuple)) and len(cache) > 1 and cache[1]:
        return cache[1]
    return {}
