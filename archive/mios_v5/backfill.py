"""MIOS V5 — Stage 2 historical backfill.

Replays the already-collected `candles_data` table (self-collecting since
migration 001, independent of this) through PURE, side-effect-free
structure calculations, to backfill `engine_state` for days before Stage 2
existed.

Deliberately does NOT touch compute_market_picture(), the entry gate, or
any Telegram/DB-write live-trading code path — those have real side
effects (alerts, armed-state mutation, entry_gate_signals rows) that must
never fire for historical replay of old price action.

That constraint means this covers only the price-action-pure pieces of
Stage 2: trend (a simplified price-slope heuristic — NOT the live regime
classifier, which needs the full option-chain CE/PE scoring this backfill
deliberately never touches), S/R (swing structure), VWAP, order blocks,
chart/candle patterns. The OI-wall / ΔOI-writer / volume-profile pieces
need a full option-chain reconstruction that isn't safely available yet.
Rows from this backfill are tagged with a distinct engine_version so they
are never silently mixed with full-fidelity live rows in later analysis
(e.g. similarity search) — a backfilled row and a live row answer a
related but not identical question.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

#: distinguishes reduced backfill rows from full-fidelity live rows —
#: never compare/mix these silently
BACKFILL_ENGINE_VERSION = "v5.0-backfill-price-action"

#: bars of lookback each sample point gets (matches the live engine's
#: typical window sizes for swing S/R / order-block detection)
LOOKBACK_BARS = 200
#: sample every Nth bar within a trading day — a full day is ~375 1-min
#: bars; a 15-bar stride gives ~25 samples/day, enough to see the day's
#: structure evolve without one row per engine_state row on every tick
SAMPLE_STRIDE = 15

#: points available without volume-profile (unlike the live scorer, which
#: has an extra 15 pts for POC/VAH/VAL acceptance) — the achieved score is
#: rescaled against this so backfilled Structure Scores stay on the same
#: 0-100 scale as live ones, just computed from fewer inputs
_MAX_AVAILABLE_SCORE = 85.0


def classify_trend_from_price(df) -> Tuple[str, int]:
    """Simplified price-action-only trend read for backfill — short vs.
    long moving-average slope over the window. NOT the live regime
    classifier (that needs the full CE/PE option-chain scoring)."""
    if df is None or len(df) < 20:
        return "Unknown", 0
    closes = df["close"].astype(float)
    short = closes.tail(10).mean()
    long_ = closes.tail(min(len(closes), 50)).mean()
    pct = (short - long_) / long_ * 100 if long_ else 0.0
    if pct >= 0.15:
        return "Strong Uptrend", 5
    if pct >= 0.03:
        return "Weak Uptrend", 3
    if pct <= -0.15:
        return "Strong Downtrend", 5
    if pct <= -0.03:
        return "Weak Downtrend", 3
    return "Range", 2


def iter_backfill_samples(candles_df, stride: int = SAMPLE_STRIDE,
                          lookback: int = LOOKBACK_BARS):
    """Yield (window_df, spot, timestamp) sample points from one day's
    candles, oldest first."""
    n = len(candles_df)
    for i in range(min(lookback, n - 1) if n else 0, n, stride):
        window = candles_df.iloc[max(0, i - lookback):i + 1]
        spot = float(candles_df["close"].iloc[i])
        ts = candles_df["datetime"].iloc[i] if "datetime" in candles_df.columns else None
        yield window, spot, ts


def compute_backfill_structure(
    df_window,
    spot: float,
    swing_sr: Callable[[Any], Tuple[List[float], List[float]]],
    vwap: Callable[[Any], Any],
    order_blocks: Callable[[Any], Dict[str, Any]],
    chart_pattern: Callable[[Any], Optional[Dict[str, Any]]],
    candle_pattern: Callable[[Any], Optional[Dict[str, Any]]],
) -> Dict[str, Any]:
    """One sample point's reduced Stage 2 read. Mirrors the shape of
    vob_minimal.compute_market_structure()'s output, but only the pieces
    reconstructable from candles alone — detector functions are injected
    so this module never imports vob_minimal.py (which has top-level
    Streamlit side effects and isn't safely importable standalone)."""
    trend, stars = classify_trend_from_price(df_window)

    try:
        supports, resistances = swing_sr(df_window)
    except Exception:
        supports, resistances = [], []
    support = max((s for s in supports if s <= spot), default=None)
    resistance = min((r for r in resistances if r >= spot), default=None)
    d_sup = ((spot - support) / spot * 100) if support else None
    d_res = ((resistance - spot) / spot * 100) if resistance else None
    near_support = d_sup is not None and abs(d_sup) <= 0.35
    near_resistance = d_res is not None and abs(d_res) <= 0.35

    vwap_val, vwap_pos = None, "Unknown"
    try:
        vwap_series = vwap(df_window)
        if vwap_series is not None and len(vwap_series) and not vwap_series.empty:
            vwap_val = float(vwap_series.iloc[-1])
            if vwap_val:
                dist_pct = (spot - vwap_val) / vwap_val * 100
                vwap_pos = ("Near" if abs(dist_pct) <= 0.05
                            else ("Above" if dist_pct > 0 else "Below"))
    except Exception:
        pass

    ob_label, ob_freshness = "None", None
    try:
        ob = order_blocks(df_window) or {}
        cand = [(k, v) for k, v in (("Demand", ob.get("bullish_ob")),
                                     ("Supply", ob.get("bearish_ob"))) if v]
        if cand:
            kind, chosen = min(cand, key=lambda kv: abs(spot - kv[1]["avg"]))
            idx = int(chosen["bar_idx"])
            after = df_window.iloc[idx + 1:]
            if after.empty:
                ob_freshness = "fresh"
            else:
                lo, hi = float(chosen["low"]), float(chosen["high"])
                touched = (after["low"] <= hi) & (after["high"] >= lo)
                ob_freshness = "retested" if bool(touched.any()) else "fresh"
            ob_label = f"{ob_freshness.title()} {kind}"
    except Exception:
        pass

    chart_pat = None
    try:
        chart_pat = chart_pattern(df_window)
    except Exception:
        pass
    candle_pat = None
    try:
        candle_pat = candle_pattern(df_window)
    except Exception:
        pass

    score, bull_votes, bear_votes = 0.0, 0, 0
    if near_support:
        score += 25
        bull_votes += 1
    elif near_resistance:
        score += 25
        bear_votes += 1

    if vwap_pos == "Above":
        score += 15
        bull_votes += 1
    elif vwap_pos == "Below":
        score += 15
        bear_votes += 1

    ob_is_demand = ob_label.endswith("Demand")
    if ob_freshness == "fresh":
        score += 20
        if ob_is_demand:
            bull_votes += 1
        else:
            bear_votes += 1
    elif ob_freshness == "retested":
        score += 10
        if ob_is_demand:
            bull_votes += 1
        else:
            bear_votes += 1

    cp_dir = str((chart_pat or {}).get("direction", "")).lower()
    if cp_dir == "bullish":
        score += 10
        bull_votes += 1
    elif cp_dir == "bearish":
        score += 10
        bear_votes += 1

    kp_dir = str((candle_pat or {}).get("direction", "")).lower()
    if kp_dir == "bullish":
        score += 15
        bull_votes += 1
    elif kp_dir == "bearish":
        score += 15
        bear_votes += 1

    score = min(100, round(score / _MAX_AVAILABLE_SCORE * 100))
    if bull_votes > bear_votes and (near_support or bull_votes >= 3):
        demand_supply = "Demand"
    elif bear_votes > bull_votes and (near_resistance or bear_votes >= 3):
        demand_supply = "Supply"
    else:
        demand_supply = "Neutral"

    decision = "TRADE ZONE" if score >= 60 else ("WATCH" if score >= 35 else "NO TRADE")
    if demand_supply != "Neutral" and score >= 75:
        location_label = f"HIGH QUALITY {demand_supply.upper()} ZONE"
    elif demand_supply != "Neutral":
        location_label = f"{demand_supply.upper()} ZONE"
    else:
        location_label = "NO CLEAR ZONE"

    bias = ("STRONG_BULL" if demand_supply == "Demand" and score >= 75 else
            "BULL" if demand_supply == "Demand" else
            "STRONG_BEAR" if demand_supply == "Supply" and score >= 75 else
            "BEAR" if demand_supply == "Supply" else "NEUTRAL")

    return {
        "trend": trend, "trend_stars": stars,
        "price_location": location_label,
        "support": support, "resistance": resistance,
        "vwap": vwap_val, "vwap_position": vwap_pos,
        "order_block": {"label": ob_label, "freshness": ob_freshness},
        "chart_pattern": (chart_pat or {}).get("pattern") if chart_pat else None,
        "candle_pattern": (candle_pat or {}).get("pattern") if candle_pat else None,
        "structure_score": score,
        "demand_supply": demand_supply,
        "decision": decision,
        "bias": bias,
        "volume_profile_available": False,
    }


def build_backfill_engine_state_row(structure: Dict[str, Any], spot: float,
                                    ts, trading_day: str) -> Dict[str, Any]:
    """A structure read -> one engine_state row, reduced-fidelity and
    version-tagged."""
    return {
        "ts": ts.isoformat() if hasattr(ts, "isoformat") else str(ts),
        "trading_day": trading_day,
        "spot": spot,
        "engine_version": BACKFILL_ENGINE_VERSION,
        "structure_bias": structure["bias"],
        "structure_confidence": structure["structure_score"],
        "structure_score": structure["structure_score"],
        "structure_decision": structure["decision"],
        "full_state": {
            "stage02_structure": {
                "status": "OK", "bias": structure["bias"],
                "confidence": structure["structure_score"], "data": structure,
            }
        },
    }
