"""MIOS V6.5 — Market Day Classification (what kind of day is today?).

Every institutional trader answers this before placing a single order, because
the same setup is a buy on a trend day and a fade on a pin day. MIOS answers it
continuously, from eight independent evidence groups, and re-answers it as the
session changes character.

    09:20  ↔ Range Day     →  10:45  🔄 Swing Day  →  13:10  📈 Trend Day
                                                    →  15:00  🧲 Expiry Pin Day

**It is a context engine.** It generates no BUY/SELL, changes no confidence,
casts no vote in Evidence Correlation, and cannot override the Decision Engine.
It tells you what *kind* of market you are in; the Decision Engine still has to
prove a level before anything is traded.

## Why this is not Stage 48

Stage 48 answers "what is price doing **right now**" — markup, rotation,
compression — on a horizon of minutes. This answers "what kind of **session** is
this" on a horizon of hours, and its output drives *trading style* rather than
direction. They are different questions with different consumers, and this one
**reads** Stage 48 rather than re-deriving it: `market_state` is one signal in
the behaviour group, not a competing calculation.

## Confidence is cross-group agreement, not signal count

This is the mechanic that makes the number mean something. Twelve signals all
from the order-flow group is one opinion repeated twelve times — exactly the
correlated-evidence failure that Stage 53 exists to fix. So the winner's share
of the vote is scaled by **how many independent groups made it their top pick**,
and by how many groups could report at all. A type backed by five of six
available groups outranks one backed by thirty signals from two.

## Two types are facts, not votes

`NEWS_EVENT` and `EXPIRY_PIN` have unambiguous external triggers — Stage 28
detected a live event; it is expiry day and a measurable charm pin is exerting
force. On those days the tape can look like a trend all morning and the correct
classification is still "news day", because that is what determines how it
should be traded. They take precedence, and the reason is stated. The
underlying vote is still computed and shown, so a trader can see what the tape
looked like beneath the override.

Pure module: reads in, classification out. No IO, no pandas, no Streamlit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

TYPES = ("TREND", "SWING", "RANGE", "CHOPPY", "HIGH_VOLATILITY",
         "EXPIRY_PIN", "NEWS_EVENT", "LOW_PARTICIPATION")

LABEL = {
    "TREND": "📈 Trend Day", "SWING": "🔄 Swing Day", "RANGE": "↔ Range Day",
    "CHOPPY": "🔪 Choppy Day", "HIGH_VOLATILITY": "⚡ High Volatility Day",
    "EXPIRY_PIN": "🧲 Expiry Pin Day", "NEWS_EVENT": "💥 News Event Day",
    "LOW_PARTICIPATION": "💤 Low Participation Day", "UNKNOWN": "❔ Unclassified",
}

COLOUR = {
    "TREND": "#00ff88", "SWING": "#4da6ff", "RANGE": "#ffd000",
    "CHOPPY": "#ff9500", "HIGH_VOLATILITY": "#ff4444",
    "EXPIRY_PIN": "#a78bfa", "NEWS_EVENT": "#ff2d55",
    "LOW_PARTICIPATION": "#cfd9e6", "UNKNOWN": "#9fb0c4",
}

#: evidence group → (label, authority). Authority mirrors `evidence.FAMILY_
#: PRIORITY` where the concepts overlap, so the day classifier and the
#: correlation engine do not disagree about which evidence carries weight.
GROUPS: Dict[str, Tuple[str, float]] = {
    "price": ("Price Behaviour", 8.0),
    "levels": ("Support / Resistance", 7.0),
    "orderflow": ("Order Flow", 6.0),
    "dealer": ("Dealer", 6.0),
    "options": ("Option Chain", 5.0),
    "behaviour": ("Behaviour Engines", 5.0),
    "institutions": ("Institutional", 4.0),
    "depth": ("Market Depth", 3.0),
}

GROUP_ORDER = ("price", "levels", "orderflow", "dealer", "options",
               "behaviour", "institutions", "depth")

#: fewer available groups than this and no classification is trustworthy
_MIN_GROUPS = 3

#: confidence ceiling when coverage is below `_MIN_GROUPS`
_THIN_CAP = 45

#: consecutive cycles a challenger must win before it replaces the current
#: type. "Never lock the market type" does not mean "flip on every tick".
_MIN_CONFIRM = 2

#: types whose trigger is an external fact rather than a vote
PRECEDENCE = ("NEWS_EVENT", "EXPIRY_PIN")

EXPECTED = {
    "TREND": ["Trend continuation", "Healthy pullbacks",
              "Breakouts likely to succeed", "Directional pressure sustained"],
    "SWING": ["Rotations that resolve in the trend direction",
              "Pullbacks bought / rallies sold", "Levels tested more than once"],
    "RANGE": ["Mean reversion between the extremes", "Support and resistance hold",
              "Breakouts likely to fail"],
    "CHOPPY": ["Frequent bias flips", "Fake breakouts in both directions",
               "Signals decay quickly"],
    "HIGH_VOLATILITY": ["Fast directional changes", "Wide candles",
                        "Stops hit on noise", "Levels overshoot"],
    "EXPIRY_PIN": ["Price drawn back to the magnet strike",
                   "Breakouts fade", "Small dips are noise near the pin"],
    "NEWS_EVENT": ["Reaction, not structure", "Elevated IV and gaps",
                   "Levels ignored until the flow settles"],
    "LOW_PARTICIPATION": ["Drift rather than direction", "Thin follow-through",
                          "Levels untested"],
}

#: trading style per day type — what to do, and what NOT to
STYLE = {
    "TREND": (["Buy pullbacks / sell rallies with the trend", "Ride winners",
               "Wide trailing stop"],
              ["Fading the trend at resistance", "Small fixed targets"]),
    "SWING": (["Trade the rotation into the trend direction",
               "Two-stage targets", "Trail after the first swing"],
              ["Holding through a full counter-rotation"]),
    "RANGE": (["Buy support, sell resistance", "Smaller targets",
               "Fade the extremes"],
              ["Breakout chasing", "Wide stops"]),
    "CHOPPY": (["Stand aside", "If trading: half size, fast exits"],
               ["Breakout trades", "Holding for extended targets",
                "Adding to losers"]),
    "HIGH_VOLATILITY": (["Half size", "Wider stops sized to ATR",
                         "Wait for the level to be proven, not touched"],
                        ["Normal position size", "Tight stops"]),
    "EXPIRY_PIN": (["Fade extremes toward the pin", "Trade between S/R",
                    "Small targets"],
                   ["Momentum breakout trades", "Holding for extension"]),
    "NEWS_EVENT": (["Wait for the first reaction to complete",
                    "Half size", "Trade the retest, not the spike"],
                   ["Chasing the initial move", "Pre-positioning"]),
    "LOW_PARTICIPATION": (["Stand aside", "If trading: scalp the range only"],
                          ["Expecting follow-through", "Breakout trades"]),
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


class _Group:
    """One evidence group's read: its signals and how it votes."""

    __slots__ = ("key", "label", "authority", "signals", "votes", "reason")

    def __init__(self, key: str):
        self.key = key
        self.label, self.authority = GROUPS[key]
        self.signals: List[Dict[str, str]] = []
        self.votes: Dict[str, float] = {}
        self.reason: Optional[str] = None

    def vote(self, day_type: str, weight: float, text: str, engine: str):
        """A signal and the vote it casts, always recorded together — a vote
        with no visible signal behind it is exactly the generic output the
        explainability layer exists to prevent."""
        self.votes[day_type] = self.votes.get(day_type, 0.0) + float(weight)
        self.signals.append({"text": text, "engine": engine,
                             "type": day_type})

    def unavailable(self, reason: str):
        self.reason = reason

    @property
    def available(self) -> bool:
        return bool(self.votes)

    def top(self) -> Optional[str]:
        return max(self.votes, key=self.votes.get) if self.votes else None

    def as_dict(self) -> Dict[str, Any]:
        return {"group": self.key, "label": self.label,
                "authority": self.authority, "available": self.available,
                "reason": self.reason, "signals": self.signals,
                "votes": dict(self.votes), "top": self.top()}


# ── A · price behaviour ─────────────────────────────────────────────────
def _g_price(price: Dict[str, Any]) -> _Group:
    g = _Group("price")
    p = price or {}
    if not p:
        g.unavailable("no price-behaviour metrics supplied")
        return g

    hh, hl = bool(p.get("higher_highs")), bool(p.get("higher_lows"))
    lh, ll = bool(p.get("lower_highs")), bool(p.get("lower_lows"))
    atr_state = _s(p.get("atr_state"))
    E = "Stage 2 Structure"

    if (hh and hl) or (lh and ll):
        d = "higher highs + higher lows" if hh and hl else "lower highs + lower lows"
        g.vote("TREND", 3.0, f"Structure making {d}", E)
        g.vote("SWING", 1.0, f"Structure making {d}", E)
    elif (hh and ll) or (lh and hl):
        g.vote("CHOPPY", 2.0, "Structure overlapping — no clean swing sequence", E)

    if atr_state == "EXPANDING":
        g.vote("TREND", 1.5, "ATR expanding", E)
        g.vote("HIGH_VOLATILITY", 1.5, "ATR expanding", E)
    elif atr_state == "COMPRESSING":
        g.vote("RANGE", 1.5, "ATR compressing", E)
        g.vote("LOW_PARTICIPATION", 1.0, "ATR compressing", E)

    atr_pct = _f(p.get("atr_pct"))
    if atr_pct is not None:
        if atr_pct >= 1.2:
            g.vote("HIGH_VOLATILITY", 2.5, f"ATR {atr_pct:.2f}% of spot", E)
        elif atr_pct <= 0.25:
            g.vote("LOW_PARTICIPATION", 2.0, f"ATR only {atr_pct:.2f}% of spot", E)

    fails, breaks = _f(p.get("failed_breakouts")), _f(p.get("breakouts"))
    if fails is not None and breaks is not None and (fails + breaks) >= 3:
        fail_rate = fails / max(1.0, fails + breaks)
        if fail_rate >= 0.6:
            g.vote("CHOPPY", 2.5,
                   f"{fails:.0f} of {fails + breaks:.0f} breakouts failed", E)
            g.vote("RANGE", 1.0, "breakouts not holding", E)
        elif fail_rate <= 0.25:
            g.vote("TREND", 2.0,
                   f"{breaks:.0f} of {fails + breaks:.0f} breakouts held", E)

    vwap = _f(p.get("vwap_distance_pct"))
    if vwap is not None:
        if abs(vwap) >= 0.5:
            g.vote("TREND", 1.5, f"{abs(vwap):.2f}% from VWAP — one-sided", E)
        elif abs(vwap) <= 0.1:
            g.vote("RANGE", 1.5, f"pinned to VWAP ({vwap:+.2f}%)", E)

    poc = _f(p.get("poc_distance_pct"))
    if poc is not None and abs(poc) <= 0.1:
        g.vote("RANGE", 1.0, "trading on the POC", "Stage 9 Volume Profile")
        g.vote("EXPIRY_PIN", 0.5, "trading on the POC", "Stage 9 Volume Profile")

    rng = _f(p.get("day_range_pct"))
    if rng is not None:
        if rng >= 1.5:
            g.vote("TREND", 1.0, f"day range {rng:.2f}%", E)
            g.vote("HIGH_VOLATILITY", 1.0, f"day range {rng:.2f}%", E)
        elif rng <= 0.35:
            g.vote("LOW_PARTICIPATION", 2.5, f"day range only {rng:.2f}%", E)

    orb = _s(p.get("opening_range"))
    if orb == "BROKEN":
        g.vote("TREND", 1.0, "opening range broken and held", E)
    elif orb == "HELD":
        g.vote("RANGE", 1.0, "opening range containing price", E)

    if not g.votes:
        g.unavailable("price metrics present but none decisive")
    return g


# ── B · support / resistance behaviour ──────────────────────────────────
_TRAP_STATES = ("BULL_TRAP", "BEAR_TRAP", "FAILED_BREAKOUT",
                "FAILED_BREAKDOWN", "SWEEP_BUY", "SWEEP_SELL")
_BREAK_STATES = ("CONFIRMED_BREAKOUT", "CONFIRMED_BREAKDOWN", "ACCEPTANCE")
_HOLD_STATES = ("REJECTION", "DEFENDED")


def _g_levels(fr: Dict[str, Any]) -> _Group:
    g = _Group("levels")
    rc = fr.get("reaction") or {}
    zone = fr.get("battle_zone") or {}
    state = _s(rc.get("state"))
    E42, E35 = "Stage 42 Acceptance", "Stage 35 Reaction Zone"

    if state and state != "IDLE":
        if state in _TRAP_STATES:
            g.vote("CHOPPY", 2.5, f"{rc.get('label')} at the level", E42)
            g.vote("RANGE", 1.0, "level defended against the break", E42)
        elif state in _BREAK_STATES:
            g.vote("TREND", 2.5, f"{rc.get('label')} — level given up", E42)
        elif state in _HOLD_STATES:
            g.vote("RANGE", 2.0, f"{rc.get('label')} — level held", E42)
            g.vote("SWING", 1.0, f"{rc.get('label')} — level held", E42)

    life = str(zone.get("lifecycle") or "").lower()
    if life == "broken":
        g.vote("TREND", 1.5, "zone broken", E35)
    elif life in ("stable", "building"):
        g.vote("RANGE", 1.5, f"zone {life}", E35)
    elif life == "under-attack":
        g.vote("SWING", 1.0, "zone contested", E35)
        g.vote("CHOPPY", 1.0, "zone contested", E35)

    tests = _f(zone.get("tests"))
    if tests is not None and tests >= 3:
        g.vote("RANGE", 1.5, f"level tested {tests:.0f} times and holding", E35)

    if zone.get("type"):
        g.vote("SWING", 0.5, f"war zone active at {zone.get('type')}", E35)

    if not g.votes:
        g.unavailable("no level reaction recorded yet")
    return g


# ── C · option chain ────────────────────────────────────────────────────
def _g_options(fr: Dict[str, Any], opt: Dict[str, Any]) -> _Group:
    from .final_read import section
    g = _Group("options")
    o = opt or {}
    sec = section(fr, "options")
    E = "Stage 12 Options"

    writing = _s(o.get("writing"))
    if writing == "BOTH":
        g.vote("RANGE", 2.5, "writers on both sides — range being defended", E)
        g.vote("EXPIRY_PIN", 1.5, "two-sided writing", E)
    elif writing in ("CALL", "PUT"):
        g.vote("TREND", 1.5, f"{writing.title()} writing dominant", E)

    unwind = _s(o.get("unwinding"))
    if unwind in ("CALL", "PUT"):
        g.vote("TREND", 1.5, f"{unwind.title()} unwinding — positions covering", E)
    elif unwind == "BOTH":
        g.vote("LOW_PARTICIPATION", 1.5, "both sides unwinding", E)

    iv_chg = _f(o.get("iv_change_pct"))
    if iv_chg is not None:
        if iv_chg >= 8:
            g.vote("NEWS_EVENT", 2.0, f"IV up {iv_chg:.1f}%", E)
            g.vote("HIGH_VOLATILITY", 1.5, f"IV up {iv_chg:.1f}%", E)
        elif iv_chg <= -8:
            g.vote("RANGE", 1.5, f"IV down {abs(iv_chg):.1f}% — crush", E)
            g.vote("EXPIRY_PIN", 1.0, "IV crushing into expiry", E)

    vel = _f(o.get("oi_velocity"))
    if vel is not None and abs(vel) >= 2.0:
        g.vote("TREND", 1.0, f"OI velocity {vel:+.1f}", E)
    elif vel is not None and abs(vel) <= 0.3:
        g.vote("LOW_PARTICIPATION", 1.5, "OI barely moving", E)

    pcr = _f(o.get("pcr"))
    if pcr is not None and 0.9 <= pcr <= 1.1:
        g.vote("RANGE", 1.0, f"PCR {pcr:.2f} — balanced", E)

    if not g.votes and sec.get("headline"):
        g.vote("RANGE", 0.5, sec["headline"], E)
    if not g.votes:
        g.unavailable("no option-chain metrics supplied")
    return g


# ── D · dealer behaviour ────────────────────────────────────────────────
def _g_dealer(fr: Dict[str, Any], dealer: Dict[str, Any],
              charm_pin: Dict[str, Any]) -> _Group:
    from .final_read import section
    g = _Group("dealer")
    d = dict(dealer or {})
    sec = section(fr, "dealer")
    E = "Stage 11 Dealer"

    if charm_pin and charm_pin.get("active"):
        g.vote("EXPIRY_PIN", 4.0,
               f"charm pin at {charm_pin.get('pin', 0):,.0f} "
               f"({charm_pin.get('drift', '')})", "Stage 11 · charm pin")

    state = _s(d.get("state") or d.get("regime"))
    if state == "PINNING":
        g.vote("EXPIRY_PIN", 2.5, "dealers pinning", E)
        g.vote("RANGE", 1.5, "dealers pinning", E)
    elif state == "EXPANSION":
        g.vote("TREND", 2.0, "dealer positioning expansive", E)
        g.vote("HIGH_VOLATILITY", 1.0, "dealer positioning expansive", E)
    elif state == "HEDGING":
        g.vote("SWING", 1.0, "dealers actively hedging", E)

    gex = _f(d.get("gex"))
    if gex is not None:
        if gex > 0:
            g.vote("RANGE", 2.0, f"positive GEX {gex:+.0f} — moves dampened", E)
        else:
            g.vote("HIGH_VOLATILITY", 2.0,
                   f"negative GEX {gex:+.0f} — moves amplified", E)
            g.vote("TREND", 1.0, "short-gamma dealers chase the move", E)

    if d.get("gamma_flip_near"):
        g.vote("HIGH_VOLATILITY", 1.5, "price near the gamma flip", E)

    if not g.votes and sec.get("headline"):
        g.vote("RANGE", 0.5, sec["headline"], E)
    if not g.votes:
        g.unavailable("no dealer metrics supplied")
    return g


# ── E · order flow ──────────────────────────────────────────────────────
def _g_orderflow(fr: Dict[str, Any], flow: Dict[str, Any]) -> _Group:
    from .final_read import section
    g = _Group("orderflow")
    f = dict(flow or {})
    sec = section(fr, "orderflow")
    ltp = fr.get("ltp_behaviour") or {}
    E = "Stage 14 Order Flow"

    cvd = _s(f.get("cvd_state"))
    if cvd in ("RISING", "FALLING"):
        g.vote("TREND", 2.0, f"CVD {cvd.lower()} steadily", E)
    elif cvd == "FLAT":
        g.vote("RANGE", 1.0, "CVD flat", E)
        g.vote("LOW_PARTICIPATION", 1.0, "CVD flat", E)
    elif cvd == "CHOPPY":
        g.vote("CHOPPY", 2.0, "CVD swinging both ways", E)

    vol = _s(f.get("volume_state") or (ltp.get("volume") or {}).get("state"))
    if vol == "EXPLOSIVE":
        g.vote("HIGH_VOLATILITY", 2.0, "volume explosive", E)
        g.vote("TREND", 1.0, "volume expanding with the move", E)
    elif vol == "DRY":
        g.vote("LOW_PARTICIPATION", 2.5, "volume dry", E)
    elif vol == "HEALTHY":
        g.vote("TREND", 1.0, "volume healthy", E)

    mflow = _s(f.get("money_flow_state") or (ltp.get("flow") or {}).get("state"))
    if mflow in ("ENTERING", "LEAVING"):
        g.vote("TREND", 1.5, f"money flow {mflow.lower()}", E)
    elif mflow == "FLAT":
        g.vote("LOW_PARTICIPATION", 1.5, "money flow flat", E)

    imb = _f(f.get("imbalance_pct"))
    if imb is not None:
        if abs(imb) >= 25:
            g.vote("TREND", 1.5, f"order-flow imbalance {imb:+.0f}%", E)
        elif abs(imb) <= 5:
            g.vote("RANGE", 1.0, "order flow balanced", E)

    if not g.votes and sec.get("headline"):
        g.vote("RANGE", 0.5, sec["headline"], E)
    if not g.votes:
        g.unavailable("no order-flow metrics supplied")
    return g


# ── F · market depth (skips gracefully — this feed has no L2) ───────────
def _g_depth(depth: Optional[Dict[str, Any]]) -> _Group:
    g = _Group("depth")
    d = dict(depth or {})
    if not d:
        # Stage 15 is DISABLED for exactly this reason. Fabricating a depth
        # read would put an invented group into the agreement denominator and
        # inflate every confidence number on the screen.
        g.unavailable("no L2 depth in this feed (Stage 15 DISABLED)")
        return g

    E = "Stage 15 Microstructure"
    imb = _f(d.get("bid_ask_imbalance_pct"))
    if imb is not None:
        if abs(imb) >= 30:
            g.vote("TREND", 2.0, f"resting depth skewed {imb:+.0f}%", E)
        elif abs(imb) <= 8:
            g.vote("RANGE", 1.5, "depth balanced", E)
    if d.get("large_resting"):
        g.vote("RANGE", 1.5, "large resting orders defending the level", E)
    if d.get("absorption"):
        g.vote("SWING", 1.0, "depth absorption at the level", E)
    if _f(d.get("total_depth")) is not None and _f(d["total_depth"]) < 0:
        g.vote("LOW_PARTICIPATION", 1.0, "resting liquidity thin", E)

    if not g.votes:
        g.unavailable("depth supplied but not decisive")
    return g


# ── G · institutional behaviour ─────────────────────────────────────────
def _g_institutions(fr: Dict[str, Any]) -> _Group:
    from .final_read import section
    g = _Group("institutions")
    htf = ((fr.get("htf") or {}).get("alignment")) or {}
    flows = section(fr, "flows")
    sector = section(fr, "sector")
    fam = (fr.get("families") or {}).get("institutions") or {}

    score = _f(htf.get("score"))
    if score is not None and _s(htf.get("bias")) in ("BULL", "BEAR"):
        if score >= 70:
            g.vote("TREND", 2.5,
                   f"higher timeframes aligned — {htf.get('label')}",
                   "Stage 45 HTF VPFR")
        elif score <= 40:
            g.vote("CHOPPY", 1.5, "higher timeframes disagree",
                   "Stage 45 HTF VPFR")
    elif _s(htf.get("bias")) == "NEUTRAL":
        g.vote("RANGE", 1.0, "no higher-timeframe consensus",
               "Stage 45 HTF VPFR")

    if _s(flows.get("bias")) in ("BULL", "STRONG_BULL", "BEAR", "STRONG_BEAR"):
        g.vote("TREND", 1.5, flows.get("headline") or "FII/DII one-sided",
               "Stage 23 Flows")
    if _s(sector.get("bias")) in ("BULL", "STRONG_BULL", "BEAR", "STRONG_BEAR"):
        g.vote("TREND", 1.0, sector.get("headline") or "sector breadth aligned",
               "Stage 18 Sector")

    rel = _s(fam.get("reliability"))
    if rel == "LOW":
        g.vote("CHOPPY", 1.0, "institutional evidence internally split",
               "Stage 53 Evidence")
    elif rel == "HIGH" and _s(fam.get("direction")) != "NEUTRAL":
        g.vote("TREND", 1.0,
               f"institutions {fam.get('direction')} at "
               f"{fam.get('strength', 0)}%", "Stage 53 Evidence")

    if not g.votes:
        g.unavailable("no institutional read available")
    return g


# ── H · behaviour engines ───────────────────────────────────────────────
_STATE_VOTES = {
    "TREND_UP": ("TREND", 2.5), "TREND_DOWN": ("TREND", 2.5),
    "MARKUP": ("TREND", 2.0), "MARKDOWN": ("TREND", 2.0),
    "BREAKOUT": ("TREND", 1.5), "BREAKDOWN": ("TREND", 1.5),
    "EXPANSION": ("HIGH_VOLATILITY", 1.5), "COMPRESSION": ("RANGE", 2.0),
    "ROTATION": ("RANGE", 2.0), "ACCUMULATION": ("SWING", 1.5),
    "DISTRIBUTION": ("SWING", 1.5), "WAR_ZONE": ("CHOPPY", 1.5),
    "TRAP_ACTIVE": ("CHOPPY", 2.0), "REVERSAL_BUILDING": ("SWING", 1.5),
}


def _g_behaviour(fr: Dict[str, Any]) -> _Group:
    g = _Group("behaviour")
    ms = fr.get("market_state") or {}
    mem = fr.get("memory_read") or {}
    tr = fr.get("transition") or {}
    ab = fr.get("absorption") or {}
    en = fr.get("energy_read") or {}
    stab = _s(fr.get("stability"))

    st = _s(ms.get("state"))
    if st in _STATE_VOTES:
        t, w = _STATE_VOTES[st]
        g.vote(t, w, f"market state {ms.get('label', st)}",
               "Stage 48 Market State")

    dur = _f(mem.get("state_duration_min"))
    if dur is not None:
        if dur >= 30:
            g.vote("TREND", 1.5, f"state held {dur:.0f} min",
                   "Stage 54 Market Memory")
        elif dur <= 5:
            g.vote("CHOPPY", 1.5, f"state only {dur:.0f} min old",
                   "Stage 54 Market Memory")

    tstate = _s(tr.get("state"))
    if tstate == "STABLE":
        g.vote("TREND", 1.0, "bias stable", "Stage 47 Bias Transition")
    elif tstate in ("REVERSING", "TRANSITION"):
        g.vote("CHOPPY", 2.0, f"bias {tstate.lower()}",
               "Stage 47 Bias Transition")
    elif tstate == "STRENGTHENING":
        g.vote("TREND", 1.5, "bias strengthening", "Stage 47 Bias Transition")

    if stab == "SHOCK":
        g.vote("HIGH_VOLATILITY", 3.0, "flow stability SHOCK",
               "Stage 44 Flow Shift")
        g.vote("NEWS_EVENT", 1.5, "flow stability SHOCK", "Stage 44 Flow Shift")
    elif stab == "UNSTABLE":
        g.vote("HIGH_VOLATILITY", 1.5, "tape unstable", "Stage 44 Flow Shift")
        g.vote("CHOPPY", 1.0, "tape unstable", "Stage 44 Flow Shift")
    elif stab == "STABLE":
        g.vote("TREND", 0.5, "tape stable", "Stage 44 Flow Shift")

    beh = _s(ab.get("behaviour"))
    if beh.startswith("PASSIVE") or beh.endswith("RELOADING"):
        g.vote("SWING", 1.5, ab.get("label", beh), "Stage 43 Absorption")
        g.vote("RANGE", 1.0, ab.get("label", beh), "Stage 43 Absorption")
    elif beh.startswith("AGGRESSIVE"):
        g.vote("TREND", 1.5, ab.get("label", beh), "Stage 43 Absorption")
    elif beh.endswith("EXHAUSTION"):
        g.vote("SWING", 1.0, ab.get("label", beh), "Stage 43 Absorption")

    est = _s(en.get("state"))
    if est == "DEAD":
        g.vote("LOW_PARTICIPATION", 2.5, "market energy DEAD",
               "Stage 37 Energy")
    elif est == "COMPRESSION":
        g.vote("RANGE", 1.5, "energy compressing", "Stage 37 Energy")
    elif est in ("EXPANSION", "RELEASED"):
        g.vote("TREND", 1.5, f"energy {est.lower()}", "Stage 37 Energy")

    if not g.votes:
        g.unavailable("behaviour engines have not reported yet")
    return g


# ── the classification ──────────────────────────────────────────────────
def classify(final_read: Optional[Dict[str, Any]] = None,
             price: Optional[Dict[str, Any]] = None,
             options: Optional[Dict[str, Any]] = None,
             dealer: Optional[Dict[str, Any]] = None,
             flow: Optional[Dict[str, Any]] = None,
             depth: Optional[Dict[str, Any]] = None,
             charm_pin: Optional[Dict[str, Any]] = None,
             is_expiry: bool = False) -> Dict[str, Any]:
    """One dominant day type, with the evidence and the confidence behind it."""
    fr = dict(final_read or {})

    groups = [
        _g_price(price or {}),
        _g_levels(fr),
        _g_orderflow(fr, flow or {}),
        _g_dealer(fr, dealer or {}, charm_pin or {}),
        _g_options(fr, options or {}),
        _g_behaviour(fr),
        _g_institutions(fr),
        _g_depth(depth),
    ]
    live = [g for g in groups if g.available]

    tally: Dict[str, float] = {}
    for g in live:
        for t, w in g.votes.items():
            tally[t] = tally.get(t, 0.0) + w * g.authority

    ranked = sorted(tally.items(), key=lambda kv: -kv[1])
    winner = ranked[0][0] if ranked else "UNKNOWN"
    total = sum(tally.values()) or 1.0

    # ── precedence: two types are facts, not vote winners ──
    forced, forced_reason = None, None
    ev = fr.get("event") or {}
    if ev.get("event_detected"):
        forced = "NEWS_EVENT"
        forced_reason = (f"Stage 28 detected a live event "
                         f"({_f(ev.get('event_score')) or 0:.0f}%) — the tape "
                         f"is reacting, whatever its shape looks like.")
    elif is_expiry and (charm_pin or {}).get("active"):
        cp = charm_pin or {}
        forced = "EXPIRY_PIN"
        forced_reason = (f"Expiry day with a measurable charm pin at "
                         f"{_f(cp.get('pin')) or 0:,.0f} — dealer hedging "
                         f"dominates the session's behaviour.")

    voted_winner = winner
    if forced:
        winner = forced

    confidence, conf_note = _confidence(winner, tally, total, live, len(groups),
                                        forced=bool(forced))

    backing = [g for g in live if g.top() == winner]
    reasons = [s for g in backing for s in g.signals if s["type"] == winner]
    against = [{"type": t, "share": round(100.0 * w / total, 1)}
               for t, w in ranked[:4] if t != winner]

    return {
        "type": winner, "label": LABEL.get(winner, winner),
        "colour": COLOUR.get(winner, COLOUR["UNKNOWN"]),
        "confidence": confidence, "confidence_note": conf_note,
        "share_pct": round(100.0 * tally.get(winner, 0.0) / total, 1),
        "groups": [g.as_dict() for g in groups],
        "groups_available": len(live), "groups_total": len(groups),
        "groups_backing": len(backing),
        "backing_groups": [g.label for g in backing],
        "evidence": reasons[:10],
        "runners_up": against,
        "forced": bool(forced), "forced_reason": forced_reason,
        "voted_type": voted_winner if forced else None,
        "voted_label": LABEL.get(voted_winner) if forced else None,
        "expected": EXPECTED.get(winner, []),
        "recommended": STYLE.get(winner, ([], []))[0],
        "avoid": STYLE.get(winner, ([], []))[1],
        "style_caveat": _style_caveat(fr),
        "tally": {t: round(w, 1) for t, w in ranked},
        # binding: context only. It votes on nothing and gates nothing.
        "advisory_only": True,
    }


def _style_caveat(fr: Dict[str, Any]) -> Optional[str]:
    """Classification and style are different questions.

    A strongly trending tape is still a trend day the moment institutional flow
    shocks — but "ride winners on a wide trail" is dangerous advice right then,
    and the classification alone would not say so. This overrides the style
    guidance without touching the type.
    """
    stab = _s(fr.get("stability"))
    if stab == "SHOCK":
        return ("⚠️ Flow in SHOCK (Stage 44) — halve size and wait for the "
                "tape to settle, whatever the day type recommends.")
    if stab == "UNSTABLE":
        return ("⚠️ Tape UNSTABLE (Stage 44) — reduce size; the style guidance "
                "assumes an orderly market.")
    if stab == "RECOVERY":
        return ("Tape still settling after a shift (Stage 44) — size down "
                "until it stabilises.")
    return None


def _confidence(winner: str, tally: Dict[str, float], total: float,
                live: Sequence[_Group], n_groups: int,
                forced: bool = False) -> Tuple[int, str]:
    """Cross-group agreement, not signal count.

    Twelve signals from one group is one opinion repeated twelve times. The
    winner's share of the vote is therefore scaled by how many *independent*
    groups made it their top pick, and by how many groups could report at all.
    """
    n_live = len(live)
    if not n_live or winner == "UNKNOWN":
        return 0, "No evidence group could report yet."

    backing = sum(1 for g in live if g.top() == winner)
    share = tally.get(winner, 0.0) / total
    agreement = backing / n_live if n_live else 0.0
    coverage = n_live / float(n_groups)

    conf = 100.0 * share * (0.45 + 0.55 * agreement) * (0.70 + 0.30 * coverage)
    if forced:
        # an external fact is not made less true by a disagreeing tape, but a
        # tape that disagrees is worth knowing about — floor, don't max out
        conf = max(conf, 70.0)

    if n_live < _MIN_GROUPS:
        return (min(int(round(conf)), _THIN_CAP),
                f"Only {n_live} evidence group(s) reporting — capped at "
                f"{_THIN_CAP}%. Not enough independent evidence to classify "
                f"a session.")

    note = (f"{backing} of {n_live} independent groups agree "
            f"({round(100 * share)}% of the weighted vote).")
    if backing == 1 and n_live >= 4:
        note += " Single-group support — treat with caution."
    return int(max(0, min(96, round(conf)))), note


# ── live transition tracking ────────────────────────────────────────────
def track(prior: Optional[Dict[str, Any]],
          classification: Optional[Dict[str, Any]],
          now_ts: float = 0.0, keep: int = 24) -> Dict[str, Any]:
    """Advance the day-type record by one cycle. Never locks the type.

    A challenger must win `_MIN_CONFIRM` consecutive cycles before it replaces
    the incumbent — otherwise the classification flips on every noisy cycle and
    the "duration" figure, which is the whole point of tracking it, becomes
    meaningless. Precedence types (news, expiry pin) switch immediately: a live
    event is not something to confirm over two minutes.
    """
    st = dict(prior or {})
    c = dict(classification or {})
    new = c.get("type")
    if not new or new == "UNKNOWN":
        return st

    cur = st.get("type")
    history = list(st.get("history") or [])

    if cur == new:
        st["last_ts"] = now_ts
        st["duration_min"] = round(max(0.0, now_ts - st.get("since_ts", now_ts))
                                   / 60.0, 1)
        st["cycles"] = int(st.get("cycles", 0)) + 1
        st["pending"] = None
        st["pending_cycles"] = 0
    else:
        immediate = bool(c.get("forced")) or cur is None
        pending = st.get("pending")
        cycles = int(st.get("pending_cycles", 0)) + 1 if pending == new else 1

        if immediate or cycles >= _MIN_CONFIRM:
            if cur:
                history.append({
                    "from": cur, "from_label": LABEL.get(cur, cur),
                    "to": new, "to_label": LABEL.get(new, new),
                    "ts": now_ts, "confidence": c.get("confidence"),
                    "duration_min": st.get("duration_min", 0.0),
                    "reason": (c.get("forced_reason")
                               or c.get("confidence_note") or ""),
                })
            st.update({"type": new, "label": c.get("label"),
                       "since_ts": now_ts, "last_ts": now_ts,
                       "duration_min": 0.0, "cycles": 1,
                       "pending": None, "pending_cycles": 0})
        else:
            st["pending"] = new
            st["pending_cycles"] = cycles
            st["last_ts"] = now_ts

    st["history"] = history[-keep:]
    st["confidence"] = c.get("confidence")
    st["colour"] = c.get("colour")
    st["changes_today"] = len(st["history"])
    return st


def timeline(tracked: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The session's character changes, oldest first — `09:20 Range → 10:45
    Swing → 13:10 Trend`."""
    t = dict(tracked or {})
    out = []
    for h in (t.get("history") or []):
        out.append({"ts": h.get("ts"), "from": h.get("from_label"),
                    "to": h.get("to_label"),
                    "confidence": h.get("confidence"),
                    "held_min": h.get("duration_min"),
                    "reason": h.get("reason")})
    if t.get("type"):
        out.append({"ts": t.get("since_ts"), "from": None,
                    "to": t.get("label") or LABEL.get(t["type"]),
                    "confidence": t.get("confidence"),
                    "held_min": t.get("duration_min"), "current": True,
                    "reason": "current"})
    return out


def log_row(tracked: Optional[Dict[str, Any]],
            classification: Optional[Dict[str, Any]],
            trading_day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The append-only row written when the type actually changes — the record
    the Learning Engine later joins to trade outcomes."""
    t, c = dict(tracked or {}), dict(classification or {})
    hist = t.get("history") or []
    if not hist:
        return None
    h = hist[-1]
    return {
        "trading_day": trading_day,
        "previous_type": h.get("from"), "new_type": h.get("to"),
        "confidence": h.get("confidence"),
        "previous_duration_min": h.get("duration_min"),
        "reason": h.get("reason"),
        "evidence": [s["text"] for s in (c.get("evidence") or [])][:10],
        "groups_backing": c.get("groups_backing"),
        "groups_available": c.get("groups_available"),
        "forced": bool(c.get("forced")),
    }


def summary_line(classification: Optional[Dict[str, Any]],
                 tracked: Optional[Dict[str, Any]] = None) -> str:
    c, t = dict(classification or {}), dict(tracked or {})
    if not c.get("type"):
        return "Market type not yet classified."
    dur = _f(t.get("duration_min"))
    held = f" · held {dur:.0f} min" if dur else ""
    return (f"{c['label']} · {c['confidence']}%{held} — "
            f"{c.get('confidence_note', '')}")


# ── the Learning Engine's payoff ────────────────────────────────────────
def performance_by_type(day_log: Optional[Sequence[Dict[str, Any]]],
                        results: Optional[Sequence[Dict[str, Any]]],
                        min_trades: int = 10) -> List[Dict[str, Any]]:
    """Which day types actually produce results.

    A trade is attributed to whichever type was in force when it was taken —
    the last transition on that trading day at or before the trade. Attributing
    by the day's *final* type would credit a trend morning's wins to the pin
    afternoon that followed it.

    Types below `min_trades` are returned with `thin: True` rather than
    filtered out. A market type you have only traded four times is unproven,
    which is different from bad, and hiding it is how a promising read gets
    quietly dropped.
    """
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in (day_log or []):
        d = str(row.get("trading_day") or "")
        if d:
            by_day.setdefault(d, []).append(row)
    for rows in by_day.values():
        rows.sort(key=lambda r: str(r.get("ts") or ""))

    buckets: Dict[str, Dict[str, Any]] = {}
    sessions: Dict[str, set] = {}
    for res in (results or []):
        if res.get("outcome") not in ("win", "loss"):
            continue
        day = str(res.get("trading_day") or "")
        when = str(res.get("exit_at") or res.get("created_at") or "")
        rows = by_day.get(day) or []
        active = None
        for row in rows:
            if not when or str(row.get("ts") or "") <= when:
                active = row.get("new_type")
            else:
                break
        if not active:
            continue
        b = buckets.setdefault(active, {"type": active, "trades": 0, "wins": 0,
                                        "pnl": 0.0})
        b["trades"] += 1
        b["wins"] += 1 if res["outcome"] == "win" else 0
        try:
            b["pnl"] += float(res.get("pnl_points") or 0.0)
        except (TypeError, ValueError):
            pass
        sessions.setdefault(active, set()).add(day)

    out = []
    for t, b in buckets.items():
        n = max(1, b["trades"])
        out.append({
            "type": t, "label": LABEL.get(t, t), "colour": COLOUR.get(t),
            "trades": b["trades"], "wins": b["wins"],
            "losses": b["trades"] - b["wins"],
            "win_rate": round(100.0 * b["wins"] / n, 1),
            "total_pnl": round(b["pnl"], 1),
            "expectancy": round(b["pnl"] / n, 2),
            "sessions": len(sessions.get(t, ())),
            "thin": b["trades"] < min_trades,
        })
    out.sort(key=lambda r: (r["thin"], -r["win_rate"]))
    return out


def occurrence(day_log: Optional[Sequence[Dict[str, Any]]]
               ) -> List[Dict[str, Any]]:
    """How often each type occurs, and how long it typically holds."""
    counts: Dict[str, Dict[str, Any]] = {}
    for row in (day_log or []):
        t = row.get("new_type")
        if not t:
            continue
        c = counts.setdefault(t, {"type": t, "n": 0, "minutes": []})
        c["n"] += 1
        d = _f(row.get("previous_duration_min"))
        if d:
            c["minutes"].append(d)
    total = sum(c["n"] for c in counts.values()) or 1
    out = []
    for c in counts.values():
        mins = c["minutes"]
        out.append({"type": c["type"], "label": LABEL.get(c["type"], c["type"]),
                    "count": c["n"],
                    "pct": round(100.0 * c["n"] / total, 1),
                    "avg_hold_min": (round(sum(mins) / len(mins), 1)
                                     if mins else None)})
    out.sort(key=lambda r: -r["count"])
    return out
