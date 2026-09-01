"""MIOS — Greek Behaviour Interpretation Layer.

Translates the Greek and dealer-positioning numbers MIOS **already produces**
into one compact behavioural read: where price is being pulled, whether dealers
are damping or amplifying movement, whether volatility is reinforcing the move,
and whether time/expiry is raising the pressure.

## What this is NOT

Not an engine, not a stage, not a pricing model, not a Greek calculator. It
computes **no Greek** and owns **no market fact**. Every number arrives as a
parameter, sourced by the caller from the existing producers:

* gamma / GEX ....... `vob_minimal.calculate_dealer_gex` → `total_gex`, `gamma_flip`
* net charm / vanna .. `vob_minimal.calculate_vanna_charm_exposure` (`vc_exp`)
* the magnet level ... the OI pin / max-pain / GEX magnet the app already ranks
* dealer delta ....... `vob_minimal.calculate_dealer_dex`

It never emits BUY/SELL, never invents a level, and never touches the Guardian
verdict, confidence, risk gates or execution — **`context_only` is always True**.
A Greek that was not handed in reads `Not reported` (never `0` — an unmeasured
force is not a balanced one). Data older than `STALE_AFTER_S` is flagged `stale`.

## Sign conventions (reused, not invented)

* **Gamma:** dealers *long* gamma (`total_gex > 0`) hedge *against* the move —
  the mean-reverting CHOP / PIN regime; *short* gamma (`< 0`) hedges *with* it —
  the EXPANSION regime. This is the standard GEX reading and matches the bands
  `calculate_dealer_gex` already uses (±50, ±200).
* **Charm:** negative net charm drags the hedge *down*, positive *up* — the same
  pairing the Dealer-Magnet strip shows ("net charm -36.2L/day · downward drag").
* **Vanna:** positive net vanna means a *rise* in IV pushes dealer delta hedging
  *up*, negative pushes it *down*. Stated only as a "may reinforce" tendency,
  never as a trade.

Pure module: numbers in, a dict out. No pandas, no plotly, no session, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

#: what a missing Greek reads as — never 0 (rule 9: an unmeasured force is not a
#: balanced one).
NOT_REPORTED = "Not reported"

#: seconds after which the dealer snapshot is called stale rather than current.
STALE_AFTER_S = 180.0

# ── interpretation thresholds (tunable; they classify, they do not compute) ──
#: |total_gex| bands — the same figures `calculate_dealer_gex` interprets with.
GEX_STRONG = 200.0
GEX_MODERATE = 50.0
#: |total_gex| below this is too flat to call a regime either way.
GEX_FLAT = 10.0
#: net charm (L/day) that counts as a real time-drift, and the elevated band.
CHARM_MILD = 15.0
CHARM_ELEVATED = 60.0
#: |net vanna| (L) bands for volatility pressure.
VANNA_MODERATE = 50.0
VANNA_HIGH = 200.0
#: |net vega| (L) bands for volatility SENSITIVITY (magnitude of the book's vega).
#: ⚠️ Provisional — net vega runs far larger than vanna/charm because vega per
#: option is orders of magnitude bigger, so these are one-line-tunable once the
#: live scale is observed. Getting the label wrong only mislabels a magnitude; it
#: never changes a direction (Vega is non-directional here).
VEGA_MODERATE = 5000.0
VEGA_HIGH = 20000.0
#: |net charm| (L/day) bands for how strong the magnet's pull reads.
PULL_MODERATE = 25.0
PULL_STRONG = 100.0

#: (MODERATE, HIGH) magnitude bands for the third-order net exposures.
#: ⚠️ Provisional & one-line-tunable, exactly like VEGA above. The third-order
#: net exposures use the SAME OI-weighted /1e5 scale as vanna/charm/vega, but
#: their per-option magnitudes differ by orders of magnitude between greeks, so
#: these are placeholders until the live scale is seen. They gate a MAGNITUDE
#: only — never a direction — and the panel shows a row only at MODERATE/HIGH, so
#: a band set too high fails *safe* (the row stays silent) rather than noisy.
CONTEXTUAL_BANDS = {
    "vomma": (5000.0, 20000.0),   # ∂vega/∂σ — scales like vega
    "speed": (50.0, 200.0),       # ∂gamma/∂S
    "zomma": (50.0, 200.0),       # ∂gamma/∂σ
    "veta": (5000.0, 20000.0),    # ∂vega/∂t — scales like vega
    "color": (50.0, 200.0),       # ∂gamma/∂t
}

#: (label, behavioural phrase) per third-order net exposure — non-directional.
#: Each describes how the *other* Greeks behave, so none of these ever implies a
#: price direction; they read as a magnitude only, like vol_sensitivity.
CONTEXTUAL_READS = {
    "vomma": ("Vol curvature",
              "vega itself accelerates as IV moves — vol sensitivity is unstable"),
    "speed": ("Gamma acceleration",
              "gamma shifts quickly as spot moves — pin/expansion behaviour can flip fast"),
    "zomma": ("Gamma-vol interaction",
              "gamma shifts as IV moves — the gamma regime is IV-sensitive"),
    "veta": ("Vega time pressure",
             "vega is eroding with time — vol sensitivity fades toward expiry"),
    "color": ("Gamma time effect",
              "gamma is shifting with time — pinning strength changes toward expiry"),
}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _reported(v: Any) -> Any:
    """The value, or `NOT_REPORTED` when it is absent. Zero is a real reading and
    is kept; only None/NaN/non-numeric become 'Not reported'."""
    return NOT_REPORTED if _f(v) is None else _f(v)


# ── the individual reads ───────────────────────────────────────────────

def pull(spot: Any, level: Any, source: Optional[str] = None,
         net_charm: Any = None) -> Dict[str, Any]:
    """Where dealer positioning is pulling price — direction and strength.

    `level` is a magnet the app already ranks (OI pin, max pain, GEX magnet);
    this NEVER invents one. Direction is level-vs-spot; strength reads off the
    magnitude of net charm (the hedging force behind the pull). Always a pull,
    never a support/resistance claim.
    """
    lv, sp = _f(level), _f(spot)
    if lv is None:
        return {"level": NOT_REPORTED, "direction": NOT_REPORTED,
                "strength": NOT_REPORTED, "source": source,
                "text": NOT_REPORTED}
    direction = ("upward" if sp is not None and lv > sp else
                 "downward" if sp is not None and lv < sp else "at spot")
    chm = _f(net_charm)
    if chm is None:
        strength = NOT_REPORTED
    else:
        a = abs(chm)
        strength = ("strong" if a >= PULL_STRONG else
                    "moderate" if a >= PULL_MODERATE else "weak")
    pull_word = (f"{strength} pull" if strength != NOT_REPORTED
                 else "pull") if direction != "at spot" else "at spot"
    text = f"₹{lv:,.0f} · {direction} {pull_word}"
    if source:
        text += f" · {source}"
    if chm is not None:
        text += f" · charm {chm:+.1f}L/day"
    return {"level": lv, "direction": direction, "strength": strength,
            "source": source, "text": text}


def gamma_regime(total_gex: Any) -> Dict[str, Any]:
    """CHOP / PIN (dealers long gamma, mean-reverting) vs EXPANSION (short gamma,
    directional). Probabilistic — a regime, not a guarantee."""
    g = _f(total_gex)
    if g is None:
        return {"regime": NOT_REPORTED, "strength": NOT_REPORTED,
                "text": NOT_REPORTED}
    a = abs(g)
    strength = ("strong" if a >= GEX_STRONG else
                "moderate" if a >= GEX_MODERATE else "weak")
    if a < GEX_FLAT:
        return {"regime": "BALANCED", "strength": "weak", "total_gex": g,
                "text": "BALANCED · gamma near flat, no clear hedging bias"}
    if g > 0:
        return {"regime": "CHOP / PIN", "strength": strength, "total_gex": g,
                "text": (f"CHOP / PIN · positive gamma ({strength}) · dealer "
                         f"hedging favours mean reversion; directional moves "
                         f"may be dampened")}
    return {"regime": "EXPANSION", "strength": strength, "total_gex": g,
            "text": (f"EXPANSION · negative gamma ({strength}) · dealer hedging "
                     f"may reinforce direction; breakouts can travel farther")}


def time_pressure(net_charm: Any, is_expiry: bool = False,
                  minutes_to_expiry: Any = None) -> Dict[str, Any]:
    """The directional hedge drift that comes simply from time passing (charm),
    and whether expiry proximity is raising it."""
    chm = _f(net_charm)
    if chm is None:
        return {"strength": NOT_REPORTED, "direction": NOT_REPORTED,
                "text": NOT_REPORTED}
    direction = ("downward" if chm < 0 else "upward" if chm > 0 else "flat")
    mins = _f(minutes_to_expiry)
    near = bool(is_expiry) or (mins is not None and mins <= 120)
    elevated = near and abs(chm) >= CHARM_ELEVATED
    if abs(chm) < CHARM_MILD and not elevated:
        return {"strength": "low", "direction": direction,
                "text": ("LOW · time-decay hedging is not a material drift right "
                         "now")}
    strength = "ELEVATED" if elevated else "mild"
    if direction == "flat":
        text = f"{strength} · charm near flat"
    else:
        text = f"{strength} {direction} hedge drift · charm {chm:+.1f}L/day"
        if elevated:
            text += " · expiry proximity raising charm's influence"
    return {"strength": strength, "direction": direction, "text": text}


def vol_pressure(net_vanna: Any) -> Dict[str, Any]:
    """How dealer directional hedging may shift when IV changes (vanna). Reported
    as a magnitude with a 'may reinforce' tendency — never a trade."""
    nv = _f(net_vanna)
    if nv is None:
        return {"strength": NOT_REPORTED, "direction": NOT_REPORTED,
                "text": NOT_REPORTED}
    a = abs(nv)
    if a < VANNA_MODERATE:
        return {"strength": "LOW", "direction": "none",
                "text": ("LOW · IV changes are unlikely to materially alter the "
                         "current directional hedge")}
    strength = "HIGH" if a >= VANNA_HIGH else "MODERATE"
    # positive net vanna: an IV rise pushes dealer hedging up; negative: down.
    side = "upside" if nv > 0 else "downside"
    return {"strength": strength, "direction": side,
            "text": (f"{strength} · a rise in IV may reinforce {side} hedging "
                     f"(net vanna {nv:+.1f}L)")}


def vol_sensitivity(net_vega: Any) -> Dict[str, Any]:
    """How much an IV change can move the option book, from net vega — a
    MAGNITUDE, never a direction. High vega means IV changes materially alter
    positioning; it says nothing about which way price goes (rule: do not
    interpret vega as bullish or bearish by itself)."""
    nv = _f(net_vega)
    if nv is None:
        return {"strength": NOT_REPORTED, "text": NOT_REPORTED}
    a = abs(nv)
    if a < VEGA_MODERATE:
        return {"strength": "LOW",
                "text": ("LOW · IV changes are unlikely to materially move the "
                         "book")}
    strength = "HIGH" if a >= VEGA_HIGH else "MODERATE"
    return {"strength": strength,
            "text": (f"{strength} · IV changes can materially alter option "
                     f"positioning (net vega {nv:+,.0f}L)")}


def expansion_risk(total_gex: Any, speed: Any = None) -> Dict[str, Any]:
    """Potential for moves to accelerate. Driven by negative gamma; positive
    gamma absorbs directional movement, so the risk reads LOW."""
    g = _f(total_gex)
    if g is None:
        return {"level": NOT_REPORTED, "text": NOT_REPORTED}
    if g > GEX_FLAT:
        return {"level": "LOW",
                "text": "LOW · positive gamma is absorbing directional movement"}
    if abs(g) <= GEX_FLAT:
        return {"level": "MODERATE",
                "text": "MODERATE · gamma near flat, little absorption either way"}
    level = "HIGH" if abs(g) >= GEX_STRONG else "MODERATE"
    return {"level": level,
            "text": (f"{level} · negative gamma — hedging can amplify a "
                     f"breakout")}


def contextual_read(name: str, value: Any,
                    history: Any = None) -> Dict[str, Any]:
    """Magnitude-only behavioural read for a third-order net exposure
    (`vomma`/`speed`/`zomma`/`veta`/`color`). `NOT_REPORTED` when no producer
    handed a value in. Never a direction — these describe how the *other* Greeks
    behave, not which way price goes, so the strength alone carries the read.

    Bucketing:

    * `history` given → **self-calibrating**: the value is bucketed against its
      OWN recent magnitudes (`rolling_baseline.classify`), so HIGH means large
      for this Greek right now, not against a guessed constant. The MODERATE band
      is reused as the noise floor and the HIGH band as the warm-up fallback.
    * `history` absent → the absolute `CONTEXTUAL_BANDS` (the #92 behaviour), so
      callers with no window (and the tests) keep working unchanged.
    """
    label, phrase = CONTEXTUAL_READS[name]
    v = _f(value)
    if v is None:
        return {"label": label, "strength": NOT_REPORTED, "text": NOT_REPORTED}
    mod, high = CONTEXTUAL_BANDS[name]
    a = abs(v)
    if history is not None:
        from .rolling_baseline import classify as _classify
        strength = _classify(a, history, floor=mod, high_band=high)
    else:
        strength = ("HIGH" if a >= high else "MODERATE" if a >= mod else "LOW")
    if strength == "LOW":
        return {"label": label, "strength": "LOW",
                "text": f"LOW · {label.lower()} not material right now"}
    return {"label": label, "strength": strength,
            "text": f"{strength} · {phrase} (net {name} {v:+,.0f})"}


def synthesise(pull_read: Dict[str, Any], gamma: Dict[str, Any]) -> str:
    """One headline from the pull direction and the gamma regime."""
    direction = (pull_read or {}).get("direction")
    regime = (gamma or {}).get("regime")
    dir_word = {"downward": "DOWNWARD DRIFT", "upward": "UPWARD DRIFT",
                "at spot": "PINNED"}.get(direction)
    reg_word = {"CHOP / PIN": "CHOP", "EXPANSION": "EXPANSION RISK",
                "BALANCED": "BALANCED"}.get(regime)
    parts = [w for w in (dir_word, reg_word) if w]
    return " + ".join(parts) if parts else NOT_REPORTED


# ── the whole read ─────────────────────────────────────────────────────

#: the third-order Greeks the layer surfaces as their own magnitude reads. Each
#: has a producer now (`net_vomma`/`net_speed`/`net_zomma`/`net_veta`/`net_color`
#: from `calculate_vanna_charm_exposure`); a name still reads "Not reported" only
#: when that column is absent from the chain. Vega is separate again — it has
#: `vol_sensitivity`. Nothing in this tuple is inherently "unreported" any more.
CONTEXTUAL_GREEKS = ("vomma", "speed", "zomma", "veta", "color")


def interpret(*, spot: Any = None, pull_level: Any = None,
              pull_source: Optional[str] = None,
              net_charm: Any = None, net_vanna: Any = None,
              net_vega: Any = None,
              total_gex: Any = None, gamma_flip: Any = None,
              is_expiry: bool = False, minutes_to_expiry: Any = None,
              as_of: Any = None, now: Any = None,
              stale_after_s: float = STALE_AFTER_S,
              contextual_history: Optional[Dict[str, Any]] = None,
              **contextual: Any) -> Dict[str, Any]:
    """The compact behavioural read, from data the app already computed.

    Every input is optional; a section whose inputs are absent reads
    `Not reported`. `contextual` accepts the higher-order Greeks by name
    (`vomma`, `speed`, `zomma`, `veta`, `color`); each now has a producer
    (`net_*` from `calculate_vanna_charm_exposure`) and becomes its own
    magnitude read under `contextual`, `Not reported` only when its column is
    absent. Vega has its own `vol_sensitivity` read from `net_vega`. Pass
    `contextual_history` (`{greek: [recent |net| …]}`) to bucket each of the five
    against its own recent magnitudes instead of a fixed band.

    Returns a dict with `pull`, `gamma`, `time`, `vol`, `vol_sensitivity`,
    `expansion`, a `synthesis` headline, a `greeks` availability map, a
    `contextual` map of the five third-order reads, `stale`, and `context_only`
    (always True — this never votes).
    """
    _pull = pull(spot, pull_level, pull_source, net_charm)
    _gamma = gamma_regime(total_gex)
    _time = time_pressure(net_charm, is_expiry, minutes_to_expiry)
    _vol = vol_pressure(net_vanna)
    _vsens = vol_sensitivity(net_vega)
    _exp = expansion_risk(total_gex, contextual.get("speed"))

    a, n = _f(as_of), _f(now)
    stale = bool(a is not None and n is not None and (n - a) > stale_after_s)

    greeks = {name: _reported(contextual.get(name))
              for name in CONTEXTUAL_GREEKS}
    #: per-greek magnitude reads (the "other 5") — surfaced by the panel only
    #: when MODERATE/HIGH, so a LOW/absent one adds no row. When the caller
    #: passes a rolling `contextual_history`, each bucket self-calibrates against
    #: that Greek's own recent magnitudes instead of a fixed band.
    _hist = contextual_history or {}
    contextual_reads = {name: contextual_read(name, contextual.get(name),
                                              history=_hist.get(name))
                        for name in CONTEXTUAL_GREEKS}

    return {
        "pull": _pull,
        "gamma": _gamma,
        "time": _time,
        "vol": _vol,
        "vol_sensitivity": _vsens,
        "expansion": _exp,
        "synthesis": synthesise(_pull, _gamma),
        "gamma_flip": _reported(gamma_flip),
        "greeks": greeks,
        "contextual": contextual_reads,
        "stale": stale,
        # ⚠️ non-negotiable: this layer is context, never a vote.
        "context_only": True,
    }
