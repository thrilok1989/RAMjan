"""Confluence entry alignment — a signal from FOUR existing engine outputs.

It builds NO engine and computes no market fact. It reads what the app already
produced and fires only when all four line up in ONE direction:

  BUY CALL  ← NIFTY at Support        (±band, or the war zone read as support)
            + ATM-strike verdict = Strong Bull
            + the CALL leg's LTP is at its support (or its session low)
            + CALL premium energy > PUT premium energy

  BUY PUT   ← NIFTY at Resistance      (±band, or the war zone read as resistance)
            + ATM-strike verdict = Strong Bear
            + the PUT leg's LTP is at its support (or its session low)
            + PUT premium energy > CALL premium energy

The level says WHERE, the ATM verdict says WHICH WAY (and must AGREE with the
level), the leg-at-support says the option is a clean defined-risk entry, and the
energy comparison says the trade side is the one with the momentum. A verdict
that disagrees with the level (Strong Bear at support) never fires.

Pure module: values in, a signal dict (or None) out. No `st`, no I/O, no network.
The app owns gathering the inputs from session state and the alert latch/cooldown.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

#: how close (index points) counts as NIFTY "at" a level — the ±5 the level-touch
#: alerts already use, so the two agree on "at a level".
BAND = 5.0

#: leg S/R states that mean the LTP is interacting with a SUPPORT (not just NONE).
_AT_SUPPORT_STATES = ("BUILDING", "ACCEPTING", "REJECTING")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _near(spot: Any, level: Any, band: float) -> bool:
    s, lv = _f(spot), _f(level)
    return s is not None and lv is not None and abs(s - lv) <= band


def leg_at_support(leg_sr: Optional[Mapping[str, Any]], ltp: Any,
                   session_low: Any, low_tol: float) -> bool:
    """Is the option leg's LTP at its own support? True when EITHER the leg's
    VOB S/R read shows a support interaction (`side == support`, an active state),
    OR the LTP is within `low_tol` of the leg's session low. Both come from data
    the app already computed for the leg."""
    if leg_sr and str(leg_sr.get("side")) == "support" \
            and str(leg_sr.get("state")) in _AT_SUPPORT_STATES:
        return True
    l, s = _f(ltp), _f(session_low)
    return l is not None and s is not None and abs(l - s) <= low_tol


def evaluate(*, spot: Any, support: Any = None, resistance: Any = None,
             war_zone: Any = None, atm_verdict: Any = None,
             call_at_support: bool = False, put_at_support: bool = False,
             call_energy: Any = None, put_energy: Any = None,
             band: float = BAND) -> Optional[Dict[str, Any]]:
    """The aligned signal, or None. Returns `{side, level, level_kind, verdict,
    call_energy, put_energy, reasons}` when all four conditions agree.

    `atm_verdict` is the ATM-strike verdict string (e.g. "Strong Bullish"); only
    the *strong* readings qualify. Energy must be present on both sides to
    compare — a missing energy never fires (it can't be shown to be the stronger).
    """
    v = str(atm_verdict or "")
    strong_bull = "Strong Bull" in v          # matches "Strong Bullish"
    strong_bear = "Strong Bear" in v
    if not (strong_bull or strong_bear):
        return None
    ce, pe = _f(call_energy), _f(put_energy)

    # the war zone acts as support in a bull setup, resistance in a bear setup
    at_support = _near(spot, support, band) or (strong_bull and _near(spot, war_zone, band))
    at_resistance = _near(spot, resistance, band) or (strong_bear and _near(spot, war_zone, band))

    if strong_bull and at_support and call_at_support \
            and ce is not None and pe is not None and ce > pe:
        level = _f(support) if _near(spot, support, band) else _f(war_zone)
        return {
            "side": "CALL",
            "level": level,
            "level_kind": "support" if _near(spot, support, band) else "war zone",
            "verdict": v, "call_energy": ce, "put_energy": pe,
            "reasons": ["NIFTY at support", "ATM verdict Strong Bull",
                        "CALL LTP at its support / session low",
                        f"CALL energy > PUT ({ce:.0f} > {pe:.0f})"],
        }
    if strong_bear and at_resistance and put_at_support \
            and ce is not None and pe is not None and pe > ce:
        level = _f(resistance) if _near(spot, resistance, band) else _f(war_zone)
        return {
            "side": "PUT",
            "level": level,
            "level_kind": "resistance" if _near(spot, resistance, band) else "war zone",
            "verdict": v, "call_energy": ce, "put_energy": pe,
            "reasons": ["NIFTY at resistance", "ATM verdict Strong Bear",
                        "PUT LTP at its support / session low",
                        f"PUT energy > CALL ({pe:.0f} > {ce:.0f})"],
        }
    return None


def message(sig: Mapping[str, Any], spot: Any = None) -> str:
    """The Telegram body for an aligned signal."""
    side = sig.get("side")
    em = "🟢" if side == "CALL" else "🔴"
    word = "BUY CALL" if side == "CALL" else "BUY PUT"
    lv = _f(sig.get("level"))
    sp = _f(spot)
    lines = [f"{em} <b>CONFLUENCE ENTRY — {word}</b>",
             f"📍 NIFTY at {sig.get('level_kind')} ₹{lv:,.0f}"
             + (f" · spot ₹{sp:,.1f}" if sp is not None else ""),
             f"🧮 ATM verdict: <b>{sig.get('verdict')}</b>"]
    lines += [f"✓ {r}" for r in (sig.get("reasons") or [])]
    lines.append("Observation-only confluence — not a guaranteed trade.")
    return "\n".join(lines)
