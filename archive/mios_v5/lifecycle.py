"""MIOS V5 — Signal Lifecycle (the trade state machine).

A Decision (from the Decision Engine) is a moment. A *signal* is a life: it is
born WAIT_ENTRY, waits patiently for its entry trigger, becomes ENTERED, then
runs to a terminal fate — TARGET_HIT, STOP_HIT, EXPIRED (never triggered) or
CANCELLED (the thesis broke before entry). Only one signal is alive at a time;
no new one is born until this one dies.

    WAIT_ENTRY ──confirmed──▶ ENTERED ──target──▶ TARGET_HIT
        │  │                    │      ──stop────▶ STOP_HIT
        │  │                    └──eod/open──────▶ EXPIRED (open)
        │  └──flip/lost────────────────────────▶ CANCELLED
        └──timeout/eod─────────────────────────▶ EXPIRED (never_entered)

`advance_lifecycle` is a PURE function of (signal, spot, flags): given where the
signal is and where price is, it returns the next status, which Telegram to send,
and — at exit — the outcome. No I/O, no session, no pandas — so it's testable and
the app just applies its verdict (update Supabase, send the alert). Observation
first: it mirrors the live Entry Gate and records the full lifecycle; it does not
place orders.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

_TERMINAL = ("TARGET_HIT", "STOP_HIT", "EXPIRED", "CANCELLED")


def is_terminal(status: Optional[str]) -> bool:
    return status in _TERMINAL


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def advance_lifecycle(sig: Dict[str, Any], spot: Optional[float],
                      confirmed: bool = False, invalidated: bool = False,
                      expired: bool = False) -> Dict[str, Any]:
    """Compute the next lifecycle step for one signal. Returns a dict:

        status   — the (possibly unchanged) status after this tick
        changed  — did the status transition this tick?
        event    — short transition tag (entered / target / stop / expired / …)
        alert    — 'signal' | 'entry' | None (which Telegram to send)
        outcome  — win / loss / never_entered / cancelled / open  (set at exit)
        exit_price / entered_price — filled at the moment they happen

    Flags are supplied by the app from the Decision Engine + clock:
      confirmed   — the setup got its confirmation (entry trigger fired)
      invalidated — thesis broke before entry (bias flipped / zone lost)
      expired     — WAIT_ENTRY sat too long, or the session is closing
    """
    status = sig.get("status") or "WAIT_ENTRY"
    side = sig.get("side")
    target = _f(sig.get("target"))
    stop = _f(sig.get("stop"))
    up = (side == "CALL")
    out: Dict[str, Any] = {"status": status, "changed": False, "event": None,
                           "alert": None, "outcome": None,
                           "exit_price": None, "entered_price": None}

    if is_terminal(status):
        return out

    if status == "WAIT_ENTRY":
        # cancellation (thesis broke) wins over a late confirmation
        if invalidated:
            out.update(status="CANCELLED", changed=True, event="cancelled",
                       outcome="cancelled")
        elif confirmed:
            out.update(status="ENTERED", changed=True, event="entered",
                       alert="entry", entered_price=spot)
        elif expired:
            out.update(status="EXPIRED", changed=True, event="never_entered",
                       outcome="never_entered")
        return out

    # ── ENTERED (running / managed) — objective price checks ──
    s = _f(spot)
    if s is not None and target is not None and stop is not None:
        hit_t = (s >= target) if up else (s <= target)
        hit_s = (s <= stop) if up else (s >= stop)
        if hit_s:                                   # stop first — conservative
            out.update(status="STOP_HIT", changed=True, event="stop",
                       outcome="loss", exit_price=s)
            return out
        if hit_t:
            out.update(status="TARGET_HIT", changed=True, event="target",
                       outcome="win", exit_price=s)
            return out
    if expired:                                     # session closing while open
        out.update(status="EXPIRED", changed=True, event="expired_open",
                   outcome="open", exit_price=s)
    return out


def signal_pnl(side: str, entry: Optional[float], exit_px: Optional[float]) -> Optional[float]:
    """Signed points the option-direction trade captured (spot proxy): CALL wins
    when spot rises, PUT when it falls. None if either price is missing."""
    e, x = _f(entry), _f(exit_px)
    if e is None or x is None:
        return None
    return round((x - e) if side == "CALL" else (e - x), 2)
