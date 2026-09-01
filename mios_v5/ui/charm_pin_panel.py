"""MIOS V6 — the dealer-magnet strip (Trade Card + Guardian panel).

Two days, two strengths, one strip:

    expiry day   🧲 Expiry charm-pin — dealer hedging DRAGS price toward the
                 magnet. Breakouts likely to fade.
    normal day   🧲 Dealer magnet — price tends to GRAVITATE toward it. A level
                 dealers defend, not a ceiling.

⚠️ The expiry branch is byte-identical to what it always rendered. `mios_v5.charm_pin`
is unchanged and still owns the measurement; `mios_v5.dealer_magnet` adds the
non-expiry wording. A read with no `expiry` key renders as expiry — the old
default — so an older caller cannot change its output by upgrading.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def charm_pin_html(read: Optional[Dict[str, Any]]) -> str:
    """One violet strip. Empty string unless the magnet is actually near
    — a permanently-present "no pin" row would train the eye to ignore it."""
    r = read or {}
    if not r.get("active"):
        return ""
    lbl = f" · {r['pin_label']}" if r.get("pin_label") else ""
    charm = (f" · net charm {r['net_charm']:+.1f}L/day"
             if r.get("net_charm") is not None else "")
    tail = ("<span style='color:#8a7bb0;'> Context only — does NOT change the "
            "Guardian verdict.</span></div>")
    head = (f"<div style='margin:6px 0;padding:8px 12px;background:#241a2e;"
            f"border-left:3px solid #a78bfa;border-radius:6px;font-size:13.5px;"
            f"color:#c9b6ec;text-align:left;'>")

    # ⚠️ Defaults to the expiry wording. `charm_pin.read()` emits no `expiry`
    # key, so a caller still using it directly gets exactly what it always got.
    if r.get("expiry", True):
        return (
            head
            + f"🧲 <b style='color:#d9c9f5;'>Expiry charm-pin</b> — dealer "
              f"hedging drags price toward the magnet "
              f"<b style='color:#e6dbff;'>₹{r['pin']:,.0f}</b> "
              f"({r['drift']}{lbl})"
            + charm
            + f". Breakouts likely to <b>fade</b>; small dips are noise near "
              f"the pin."
            + tail)

    # Normal day — the same numbers, a calmer verb, and a weaker instruction.
    days = r.get("days_to_expiry")
    when = (f" · {float(days):.0f} day{'s' if float(days) >= 2 else ''} to "
            f"expiry" if days is not None else "")
    return (
        head
        + f"🧲 <b style='color:#d9c9f5;'>Dealer magnet</b> — price tends to "
          f"gravitate toward "
          f"<b style='color:#e6dbff;'>₹{r['pin']:,.0f}</b> "
          f"({r['drift']}{lbl})"
        + charm + when
        + f". A level dealers <b>defend</b>, not a ceiling — the pull is "
          f"weaker than on expiry."
        + tail)
