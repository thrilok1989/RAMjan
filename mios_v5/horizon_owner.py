"""MIOS Stage 71 — the Horizon Ownership Registry.

**Pure data. No logic, no IO, no imports from the app.** This module answers
exactly one question, for every producer in the system:

    which trading horizon is allowed to count this read — and only which one?

## Why a registry rather than a rule

Stage 53 exists because CVD, Money Flow, Delta and VOB were the same evidence
counted four times, and the V5 tally was loudest exactly where it was most
correlated. A multi-horizon matrix re-creates that failure one level up: feed
one CVD read into scalp *and* midday *and* intraday, and "three horizons agree"
is one signal repeated three times.

A rule in someone's head does not survive a year. A table does, because the
tests in `test_horizon_owner.py` fail the build the moment a producer is added
without a home, or appears in two.

## Identity: IDs, never labels

Producers are keyed by **immutable id**, never by the string shown on screen:

* MIOS engines use `Engine.name` — `stage42_acceptance`. This is already the
  key in `MarketState.results`, so it cannot drift from the pipeline.
* Native `vob_minimal` signals use a `native_*` id, mapped to their current
  `_BIAS_CATEGORY` label in `NATIVE_LABEL`. When someone renames a label the
  test breaks and the registry must be updated deliberately — which is the
  point. A silent rename is how ownership rots.
* Higher-timeframe reads use `htf_*`, one per timeframe in
  `htf_vpfr.TIMEFRAMES`.

## The five categories

| Category | Votes? | Shown? | Meaning |
|---|---|---|---|
| `OWNED` | ✅ once | ✅ | a leaf directional read, owned by exactly one horizon |
| `STABILITY` | ❌ | ✅ | non-directional; shapes Stability and the per-horizon veto |
| `AGGREGATE` | ❌ | ✅ reference | a composite of other producers — voting would double-count |
| `EXCLUDED` | ❌ | ✅ excluded | unstable, or superseded by a better producer |
| `NON_DIRECTIONAL` | ❌ | ❌ | infrastructure that produces no bias at all |

`STABILITY` holds Stages 44, 47 and 54 — and that is not a new judgement.
`v6_bias.py` already reached it: *"Stage 47's own bias is derived from Stage
53's families. Letting it vote would count the family read twice... Stage 54
and 44 return `Bias.NONE` by design for the same reason."* The Stability axis
is that modifier tier, given a name and a display.

Stage 48 stays in `OWNED` because unlike its three neighbours it genuinely has
a direction (`EXPANSION → TREND UP`).

## Supersession

Where a native signal and a MIOS stage measure the same fact, the stage wins
and the native id goes to `EXCLUDED` with `superseded by ...`. That is
principle 1 (single source of truth) applied across the two generations, and
it is why `native_atm_pcr` does not vote alongside `stage12_options`.

## Honest limit

This registry enforces **name-level** uniqueness — one id, one home. It cannot
detect that two differently-named producers measure the same underlying fact.
Supersession handles the cases we know about; the next one has to be caught by
a human reading the table. That is the same limit `ARCHITECTURE_PRINCIPLES.md`
states about its own guard tests, and it is stated here rather than implied.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict


class Horizon(str, Enum):
    """The five trading horizons, fastest first."""
    SCALP = "scalp"            # seconds → minutes
    MIDDAY = "midday"          # 1 → 3 hours
    INTRADAY = "intraday"      # the session
    POSITIONAL = "positional"  # days
    SWING = "swing"            # weeks


#: display order, fastest first
HORIZONS = (Horizon.SCALP, Horizon.MIDDAY, Horizon.INTRADAY,
            Horizon.POSITIONAL, Horizon.SWING)

#: expected hold, shown beside each row
HOLD = {
    Horizon.SCALP: "5–15 min",
    Horizon.MIDDAY: "1–3 hours",
    Horizon.INTRADAY: "today",
    Horizon.POSITIONAL: "several days",
    Horizon.SWING: "weeks",
}

#: ⚠️ Swing never yields an option side. The option chain is current-expiry
#: intelligence; a CALL/PUT recommendation held for weeks would be backed by
#: positioning that expires before the horizon does. Swing reports structure,
#: bias and levels. Asserted by `test_swing_never_recommends_a_side`.
NO_OPTION_SIDE = frozenset({Horizon.SWING})

#: Positional reaches ~3 expiries via `compute_cross_expiry_bias` — weeks, not
#: months. It gets a side, carrying this reach note.
DEGRADED = {
    Horizon.POSITIONAL: "uses current + next expiries — reliable to several "
                        "days, not multi-week positioning",
}


# ══════════════════════════════════════════════════════════════════════
#  OWNED — leaf directional reads. Exactly one horizon each.
# ══════════════════════════════════════════════════════════════════════

OWNED: Dict[str, Horizon] = {

    # ── SCALP ─ event-driven, low-lag: what is happening right now ──────
    "native_cie_signal":            Horizon.SCALP,
    "native_spot_stop_hunt":        Horizon.SCALP,
    "native_spot_vs_dynamic_poc":   Horizon.SCALP,
    "native_atm_ce_candle":         Horizon.SCALP,
    "native_atm_pe_candle":         Horizon.SCALP,
    "native_spot_candle":           Horizon.SCALP,
    "native_vwap_relation":         Horizon.SCALP,
    "native_futures_basis":         Horizon.SCALP,
    "native_price_oi_classifier":   Horizon.SCALP,
    "native_sr_behavior":           Horizon.SCALP,
    "native_leg_sr_behavior":       Horizon.SCALP,
    "native_spot_divergence":       Horizon.SCALP,
    "native_leg_divergence":        Horizon.SCALP,
    "native_spot_ignition":         Horizon.SCALP,
    "native_leg_ignition":          Horizon.SCALP,
    "native_leg_vwap":              Horizon.SCALP,
    "native_greek_absorption":      Horizon.SCALP,
    "native_market_depth_atm":      Horizon.SCALP,
    "native_leg_vob_build_break":   Horizon.SCALP,
    "stage42_acceptance":           Horizon.SCALP,
    "stage43_absorption":           Horizon.SCALP,
    "stage50_ltp_behaviour":        Horizon.SCALP,

    # ── MIDDAY ─ smoothed reads that turn over in hours ─────────────────
    "native_reversal_detector":     Horizon.MIDDAY,
    "native_leg_vidya":             Horizon.MIDDAY,
    "native_spot_geometric":        Horizon.MIDDAY,
    "native_spot_chart_pattern":    Horizon.MIDDAY,
    "native_multi_instrument":      Horizon.MIDDAY,
    "stage48_market_state":         Horizon.MIDDAY,
    "stage69_session":              Horizon.MIDDAY,
    "stage37_energy":               Horizon.MIDDAY,
    "htf_1h":                       Horizon.MIDDAY,

    # ── INTRADAY ─ the session's own structure and positioning ──────────
    "stage02_structure":            Horizon.INTRADAY,
    "stage11_dealer":               Horizon.INTRADAY,
    "stage12_options":              Horizon.INTRADAY,
    "stage13_institutional":        Horizon.INTRADAY,
    "stage14_orderflow":            Horizon.INTRADAY,
    "stage17_liquidity":            Horizon.INTRADAY,
    "stage22_vix":                  Horizon.INTRADAY,
    "stage51_validity":             Horizon.INTRADAY,
    "stage68_day_type":             Horizon.INTRADAY,
    "htf_4h":                       Horizon.INTRADAY,

    # ── POSITIONAL ─ days: flows, calendar, daily/weekly value ──────────
    "stage18_sector":               Horizon.POSITIONAL,
    "stage23_flows":                Horizon.POSITIONAL,
    "stage30_calendar":             Horizon.POSITIONAL,
    "native_cross_expiry_bias":     Horizon.POSITIONAL,
    "htf_daily":                    Horizon.POSITIONAL,
    "htf_weekly":                   Horizon.POSITIONAL,

    # ── SWING ─ weeks: structure, macro, monthly/yearly value ───────────
    "stage03_memory":               Horizon.SWING,
    "stage19_global":               Horizon.SWING,
    "stage20_macro":                Horizon.SWING,
    "htf_monthly":                  Horizon.SWING,
    "htf_yearly":                   Horizon.SWING,
}


# ══════════════════════════════════════════════════════════════════════
#  STABILITY — non-directional. Shapes Stability + the per-horizon veto.
# ══════════════════════════════════════════════════════════════════════

STABILITY: Dict[str, str] = {
    "stage44_flow_shift":
        "Bias.NONE by design — it vetoes, never leans. Supplies STABLE / "
        "UNSTABLE / SHOCK / RECOVERY and the freeze flag.",
    "stage47_transition":
        "its bias derives from Stage 53's families — v6_bias already refuses "
        "to let it vote. Supplies STRENGTHENING / WEAKENING / REVERSING.",
    "stage54_memory":
        "Bias.NONE by design. Supplies state duration, maturity and "
        "transition risk.",
}

#: Stage 44 applies per horizon, not globally. A flow shift destroys a scalp
#: setup; it can be the swing thesis. `None` = no effect.
FLOW_SHIFT_EFFECT = {
    Horizon.SCALP: "veto",
    Horizon.MIDDAY: "veto",
    Horizon.INTRADAY: "discount",
    Horizon.POSITIONAL: None,
    Horizon.SWING: None,
}

#: confidence multiplier applied where FLOW_SHIFT_EFFECT is "discount"
FLOW_SHIFT_DISCOUNT = 0.80


# ══════════════════════════════════════════════════════════════════════
#  AGGREGATE — composites. Shown as Reference. May never own a horizon.
# ══════════════════════════════════════════════════════════════════════

AGGREGATE: Dict[str, str] = {
    "stage27_conflict":
        "arbitrates ~34 engines — owning a horizon would smuggle the whole "
        "population into it",
    "stage53_evidence":
        "collapses correlated evidence into families; already an aggregate "
        "by construction",
    "stage25_intent":
        "full-market-read + institution score combined",
    "stage26_patterns":
        "alignment across pattern engines",
    "stage31_probability":
        "derived from the engines beneath it",
    "stage35_reaction_zone":
        "consumes stages 7-11, 25 and 31-34",
    "stage05_regime":
        "adapter over the native Market Picture, itself a composite vote",
    "stage52_decision":
        "a decision over the pipeline, not evidence within it",
    "v6_bias":
        "four-voter re-derivation of the same engines — the matrix shows it "
        "beside the horizons, never inside them",
    "native_master_signal":         "composite of the native signal set",
    "native_bull_bear_meter":       "Tier-1 composite",
    "native_composite_bias":        "composite by name and construction",
    "native_leg_fast_verdict":      "verdict over the leg's fast signals",
    "native_leg_lagging_verdict":   "verdict over the leg's lagging signals",
    "native_leg_misguiding_verdict": "verdict over the leg's unstable signals",
}


# ══════════════════════════════════════════════════════════════════════
#  EXCLUDED — never votes, always displayed with the reason.
# ══════════════════════════════════════════════════════════════════════

EXCLUDED: Dict[str, str] = {
    # the `mis` tier — vob_minimal's own words: "flips on single bars /
    # accumulated noise". The codebase already judged these unreliable;
    # dropping them silently would lose that judgement.
    "native_vpfr_s_poc":    "unstable — flips on single bars (mis tier)",
    "native_mfp_poc_bin":   "unstable — flips on single bars (mis tier)",
    "native_news_bias":     "unstable — keyword sentiment, accumulated noise",

    # superseded: a MIOS stage measures the same fact better (principle 1)
    "native_atm_pcr":       "superseded by stage12_options",
    "native_global_bias":   "superseded by stage19_global",
    "native_commodity_risk": "superseded by stage20_macro",
    "native_sector_rotation": "superseded by stage18_sector",
    "native_smart_money":   "superseded by stage13_institutional",
}


# ══════════════════════════════════════════════════════════════════════
#  NON_DIRECTIONAL — infrastructure. No bias, nothing to show.
# ══════════════════════════════════════════════════════════════════════

NON_DIRECTIONAL: Dict[str, str] = {
    "stage00_health":           "system health, not a market read",
    "stage04_context":          "context provider consumed by other stages",
    "stage06_timecycle":        "clock; supplies the conviction weight",
    "stage15_microstructure":   "DISABLED — needs L2 depth we do not receive",
    "stage21_news":             "narrative input; the directional read is excluded as noise",
    "stage24_preparation":      "coiling detector — non-directional by design",
    "stage28_event_detection":  "shock detector — non-directional by design",
    "stage29_evolution":        "what-changed timeline",
    "stage33_event_impact":     "measures effect, not direction",
    "stage34_explain":          "explanation layer — never a signal",
    "stage36_story":            "narrative render",
    "stage38_tomorrow":         "post-close planning",
    "stage39_premarket":        "pre-open briefing",
    "stage40_learning":         "validation; may never influence a decision",
    "stage45_htf_vpfr":         "publishes the htf_* reads, which own horizons individually",
}


# ══════════════════════════════════════════════════════════════════════
#  NATIVE_LABEL — id → the current `_BIAS_CATEGORY` display string.
# ══════════════════════════════════════════════════════════════════════
#: The bridge between immutable ids and vob_minimal's display names. A label
#: rename breaks `test_every_native_label_still_exists`, forcing a deliberate
#: registry update instead of silent drift.

NATIVE_LABEL: Dict[str, str] = {
    "native_cie_signal":            "CIE (latest signal)",
    "native_spot_stop_hunt":        "Spot Stop-Hunt (latest)",
    "native_spot_vs_dynamic_poc":   "Spot vs Dynamic PoC",
    "native_atm_ce_candle":         "ATM CE candle pattern",
    "native_atm_pe_candle":         "ATM PE candle pattern (reversed)",
    "native_spot_candle":           "Spot Candle Pattern",
    "native_vwap_relation":         "VWAP relation",
    "native_futures_basis":         "NIFTY Futures Basis",
    "native_price_oi_classifier":   "Price × OI Classifier",
    "native_sr_behavior":           "S/R Behavior",
    "native_leg_sr_behavior":       "Cross-strike leg S/R Behavior",
    "native_spot_divergence":       "Spot Divergence (OBV/Δ)",
    "native_leg_divergence":        "Cross-strike leg Divergence",
    "native_spot_ignition":         "Spot Ignition (tank-full)",
    "native_leg_ignition":          "Cross-strike leg Ignition",
    "native_leg_vwap":              "Cross-strike leg VWAP",
    "native_leg_fast_verdict":      "Leg Fast Verdict",
    "native_greek_absorption":      "Greek Absorption (capping)",
    "native_market_depth_atm":      "Market Depth (ATM)",
    "native_leg_vob_build_break":   "Cross-strike VOB BUILD/BREAK",
    "native_master_signal":         "Master Signal (AI)",
    "native_bull_bear_meter":       "Bull/Bear Meter (Tier-1)",
    "native_smart_money":           "Smart Money / Accum-Dist",
    "native_global_bias":           "Global NIFTY Bias",
    "native_commodity_risk":        "Commodity Risk Regime",
    "native_sector_rotation":       "Sector Rotation",
    "native_multi_instrument":      "Multi-Instrument Monitor",
    "native_reversal_detector":     "Reversal Detector",
    "native_leg_vidya":             "Cross-strike VIDYA",
    "native_atm_pcr":               "ATM PCR",
    "native_spot_geometric":        "Spot Geometric Pattern",
    "native_spot_chart_pattern":    "Spot Chart Pattern",
    "native_composite_bias":        "COMPOSITE BIAS Engine",
    "native_leg_lagging_verdict":   "Leg Lagging Verdict",
    "native_vpfr_s_poc":            "Spot vs VPFR-S POC",
    "native_mfp_poc_bin":           "Spot MFP POC bin",
    "native_leg_misguiding_verdict": "Leg Misguiding Verdict",
    "native_news_bias":             "News Bias",
}

#: ids with no `_BIAS_CATEGORY` row — read from their own cache, not the
#: leg-bias table. Listed so the coverage test can tell "not a native signal"
#: apart from "native signal we forgot to map".
NON_BIAS_CATEGORY_NATIVE = frozenset({"native_cross_expiry_bias"})

#: htf id → the `htf_vpfr.TIMEFRAMES` member it reads
HTF_TIMEFRAME: Dict[str, str] = {
    "htf_1h": "1H", "htf_4h": "4H", "htf_daily": "Daily",
    "htf_weekly": "Weekly", "htf_monthly": "Monthly", "htf_yearly": "Yearly",
}


# ══════════════════════════════════════════════════════════════════════
#  Lookup helpers — the only logic in this module.
# ══════════════════════════════════════════════════════════════════════

#: every category, keyed by name, for the tests and the Excluded panel
CATEGORIES = {
    "OWNED": OWNED, "STABILITY": STABILITY, "AGGREGATE": AGGREGATE,
    "EXCLUDED": EXCLUDED, "NON_DIRECTIONAL": NON_DIRECTIONAL,
}


def category_of(producer_id: str) -> str:
    """Which category a producer belongs to, or '' when unregistered.

    An unregistered producer is a build failure, not a runtime fallback —
    `test_every_producer_has_exactly_one_home` is what catches it.
    """
    for name, table in CATEGORIES.items():
        if producer_id in table:
            return name
    return ""


def owners_of(horizon: Horizon) -> tuple:
    """Every producer id owned by `horizon`, sorted for stable display."""
    return tuple(sorted(k for k, v in OWNED.items() if v == horizon))


def horizon_of(producer_id: str):
    """The horizon owning `producer_id`, or None when it does not vote."""
    return OWNED.get(producer_id)


def may_vote(producer_id: str) -> bool:
    """True only for leaf directional reads. Everything else is shown, or
    hidden, but never counted."""
    return producer_id in OWNED
