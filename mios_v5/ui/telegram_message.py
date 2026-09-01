"""Stage 72's payload, rendered as a message a human reads.

**Presentation only.** Every value here was decided by Stage 72 or Stage 73;
this file chooses wording and layout and nothing else. It is in `ui/` for that
reason — the dispatcher is explicit that it *"does not modify the payload's
wording"*, so the wording has to live somewhere that is allowed to have taste.

## It cannot invent a level

The single rule this file exists to enforce: **an `UNKNOWN` never renders as a
number.** Stage 72 publishes `target2` and `target3` as `UNKNOWN` by name
(`MISSING_PRODUCERS`), because Stage 35 publishes one target and a ladder would
be fabricated. A template with three hard-coded target lines renders three
targets whether or not two of them exist — in the one artefact a trader acts on.

So every field goes through `_v()`, absent rows are **dropped entirely** rather
than printed with a dash, and a test asserts no `UNKNOWN` reaches the output.

## Entry and exit are the same object

An entry message comes from the `EntryDecision`; an exit message comes from the
`TradeLifecycleDecision` that references it. They share an id, so a trader can
see that the exit belongs to the entry they were sent twenty minutes ago —
which is the whole reason Stage 73 references rather than mints.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

UNKNOWN = "UNKNOWN"

#: Entry states worth a message. `WAIT` is the engine working correctly, and
#: saying so every cycle trains a reader to mute the channel — the one outcome
#: a signal channel cannot survive. The dispatcher gates on the same tuple.
ENTRY_HEAD = {
    "ENTER": ("🟢", "ENTRY"),
    "ENTRY_READY": ("🟡", "ENTRY READY"),
    "ABORT": ("🛑", "ABORT"),
}

#: Lifecycle actions worth an update to a live message.
EXIT_HEAD = {
    "EXIT": ("🚪", "EXIT"),
    "SCALE_OUT": ("➖", "PARTIAL EXIT"),
    "ADD": ("➕", "ADD"),
    "ABORT": ("🛑", "ABORT"),
    "TRAIL": ("📈", "TRAIL"),
}


def _v(value: Any) -> Optional[str]:
    """A printable value, or `None` when the producer did not report.

    `None` means **drop the line**. A dash would still occupy a row and imply
    the field was expected; a missing row says nothing, which is accurate.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == UNKNOWN:
        return None
    return text


def _num(value: Any, fmt: str = "{:,.2f}") -> Optional[str]:
    try:
        return fmt.format(float(value))
    except (TypeError, ValueError):
        return None


def _row(label: str, value: Optional[str], unit: str = "") -> str:
    return f"{label}: <b>{unit}{value}</b>\n" if value else ""


def _targets(payload: Mapping[str, Any]) -> str:
    """Only the targets that exist.

    Stage 35 publishes one. `target2` and `target3` are `UNKNOWN` by name, and
    a fixed three-line block would print them as levels.
    """
    tg = payload.get("targets") or {}
    if not isinstance(tg, Mapping):
        return ""
    lines = []
    for key in ("target1", "target2", "target3"):
        got = _num(tg.get(key))
        if got:
            lines.append(f"  T{key[-1]}: <b>₹{got}</b>")
    return ("🎯 Targets\n" + "\n".join(lines) + "\n") if lines else ""


def _reasons(payload: Mapping[str, Any], limit: int = 4) -> str:
    items = payload.get("reasons") or ()
    out = [f"  ✓ {r}" for r in list(items)[:limit] if _v(r)]
    return ("\n".join(out) + "\n") if out else ""


def _warnings(payload: Mapping[str, Any], limit: int = 3) -> str:
    items = payload.get("warnings") or ()
    out = [f"  ⚠ {w}" for w in list(items)[:limit] if _v(w)]
    return ("\n".join(out) + "\n") if out else ""


def _identity(payload: Mapping[str, Any]) -> str:
    """The join key, short. A message that cannot be traced back to the
    decision it came from is a message with no record behind it."""
    ident = _v(payload.get("id")) or ""
    ver = _v(payload.get("version")) or ""
    bits = [b for b in (ident[:8], f"v{ver}" if ver else "") if b]
    return ("<code>" + " · ".join(bits) + "</code>") if bits else ""


def market_block(market: Optional[Mapping[str, Any]] = None) -> str:
    """The market read that goes out WITH the signal.

    Six things, all of which already have an owner elsewhere in MIOS and none
    of which is computed here:

    * **spot** — the price everything below is relative to
    * **V5 vs V6 bias** — Stage 27's arbitrated read against Stage 71's, because
      the interesting moment is when they disagree
    * **CALL / PUT energy** — Stage 71.7, scored independently and never by
      subtraction, so both are printed rather than a difference
    * **CALL / PUT LTP with its own support and resistance** — Stage 71.8's
      premium structure. These are PREMIUM levels, not spot levels converted:
      there is no delta-based conversion anywhere in MIOS, and printing a spot
      level against an option's LTP would mark a price that series never trades
    * **S/R behaviour per side** — Stage 71.85, what the premium is doing at
      its own level

    Every one is dropped when its owner did not report, by the same rule as
    everything else here: absent is a missing row, never a zero.
    """
    m = dict(market or {})
    spot = _num(m.get("spot"), "{:,.1f}")
    v5, v6 = _v(m.get("v5")), _v(m.get("v6"))

    head = ""
    if spot:
        head += f"📍 Spot: <b>{spot}</b>\n"
    if v5 or v6:
        # Printed side by side on purpose — one line that agrees is reassuring,
        # one that disagrees is the reason to look at the chart.
        both = " · ".join(x for x in (f"V5 {v5}" if v5 else "",
                                      f"V6 {v6}" if v6 else "") if x)
        head += f"🧭 Bias: <b>{both}</b>"
        head += (" ✓\n" if v5 and v6 and v5 == v6 else
                 " ⚠ diverging\n" if v5 and v6 else "\n")

    # ── spot support / resistance, each with its own odds ────────────
    # `break` and `rejection` are complements from `zone_intel.probabilities()`
    # — rejection IS the bounce, so it is labelled that way rather than
    # invented as 100 − break. `trap` is an INDEPENDENT read (how likely a move
    # through the level is a liquidity grab) and is printed only when it is
    # high enough to change what a trader does.
    zones = ""
    for key, mark in (("support", "🛡"), ("resistance", "🧱")):
        z = m.get(key) or {}
        if not isinstance(z, Mapping):
            continue
        price = _num(z.get("price"), "{:,.0f}")
        if not price:
            continue
        brk = _num(z.get("break"), "{:,.0f}")
        bounce = _num(z.get("bounce"), "{:,.0f}")
        trap = _num(z.get("trap"), "{:,.0f}")
        line = f"{mark} {key.title()}: <b>{price}</b>"
        odds = " · ".join(x for x in (f"bounce {bounce}%" if bounce else "",
                                      f"break {brk}%" if brk else "") if x)
        if odds:
            line += f"  ({odds})"
        if trap and float(z.get("trap") or 0) >= 40:
            line += f" ⚠ trap {trap}%"
        zones += line + "\n"

    legs = ""
    for side in ("CALL", "PUT"):
        leg = m.get(side.lower()) or {}
        if not isinstance(leg, Mapping):
            continue
        ltp = _num(leg.get("ltp"))
        energy = _v(leg.get("energy"))
        sup = _num(leg.get("support"))
        res = _num(leg.get("resistance"))
        beh = _v(leg.get("behaviour"))
        if not any((ltp, energy, sup, res, beh)):
            continue
        emoji = "🟢" if side == "CALL" else "🔴"
        line = f"{emoji} <b>{side}</b>"
        if ltp:
            line += f" ₹{ltp}"
        if energy:
            line += f" · energy {energy}"
        line += "\n"
        if sup or res:
            band = " / ".join(x for x in (f"S ₹{sup}" if sup else "",
                                          f"R ₹{res}" if res else "") if x)
            line += f"    {band}"
            # Stage 71.8's own odds for THIS premium's level. Named `fakeout`
            # rather than folded into break: a fakeout and a break are
            # different outcomes and the trader acts differently on each.
            pb = _num(leg.get("break_probability"), "{:,.0f}")
            pf = _num(leg.get("fakeout_probability"), "{:,.0f}")
            extra = " · ".join(x for x in (f"break {pb}%" if pb else "",
                                           f"fakeout {pf}%" if pf else "")
                               if x)
            line += f"  ({extra})\n" if extra else "\n"
        if beh:
            line += f"    {beh}\n"
        legs += line

    block = head + zones + legs
    return (f"{'─' * 22}\n{block}" if block else "")


def entry_message(payload: Optional[Mapping[str, Any]] = None,
                  market: Optional[Mapping[str, Any]] = None,
                  reasons: bool = True) -> str:
    """The entry signal. `""` when the state is not one worth sending.

    `reasons=False` is the **terse** variant: the same decision, the same
    levels, the same odds — without the ✓ block that explains which components
    scored. Two channels carry the two variants.

    ⚠️ **Warnings are in BOTH.** They are the half that changes what a trader
    does: a `SHOCK` or a frozen tape is not detail, and a "terse" message that
    dropped it would be shorter and more dangerous. Only the explanation of a
    *good* read is optional.
    """
    p = dict(payload or {})
    state = str(p.get("state") or UNKNOWN)
    if state not in ENTRY_HEAD:
        return ""
    emoji, word = ENTRY_HEAD[state]

    side = _v(p.get("side"))
    # A strike is a whole number — "24500.0" reads like a price.
    strike = _num(p.get("strike"), "{:,.0f}") or _v(p.get("strike"))
    head = f"{emoji} <b>MIOS {word}</b>"
    if side:
        head += f" — {side}"
    if strike:
        head += f" {strike}"

    body = (
        _row("Quality", _v(p.get("quality")))
        + _row("Confidence", _v(p.get("confidence")))
        + _row("Zone", _v(p.get("timing")))
        + _row("Entry", _num(p.get("entry")), "₹")
        + _row("Stop", _num(p.get("stop")), "₹")
        + _targets(p)
        + _row("Risk", _v(p.get("risk")))
        + _row("Reward", _v(p.get("reward")))
        + _row("Behaviour", _v(p.get("behaviour")))
        + _row("Horizon", _v(p.get("horizon")))
    )

    why = _reasons(p) if reasons else ""
    warn = _warnings(p)
    return (
        f"{head}\n"
        f"{'─' * 22}\n"
        f"{body}"
        + market_block(market)
        + (f"{'─' * 22}\n{why}" if why else "")
        + (warn if warn else "")
        + f"{'─' * 22}\n{_identity(p)}"
    ).strip()


def exit_message(lifecycle: Optional[Mapping[str, Any]] = None,
                 entry: Optional[Mapping[str, Any]] = None,
                 market: Optional[Mapping[str, Any]] = None,
                 reasons: bool = True) -> str:
    """The exit / management update, carrying the entry's id so a reader can
    join it to the signal they were sent earlier."""
    lc = dict(lifecycle or {})
    action = str(lc.get("action") or UNKNOWN)
    if action not in EXIT_HEAD:
        return ""
    emoji, word = EXIT_HEAD[action]

    side = _v((entry or {}).get("side"))
    strike = (_num((entry or {}).get("strike"), "{:,.0f}")
              or _v((entry or {}).get("strike")))
    head = f"{emoji} <b>MIOS {word}</b>"
    if side:
        head += f" — {side}"
    if strike:
        head += f" {strike}"

    body = (
        _row("State", _v(lc.get("state")))
        + _row("Health", _v(lc.get("health")))
        + _row("Reason", _v(lc.get("exit_reason")))
        + _row("Trail", _v(lc.get("trail")))
        + _row("Scale", _v(lc.get("scale")))
        # ⚠️ Always UNKNOWN today: no producer reports a fill, so
        # `position_known` is named in Stage 73's MISSING_PRODUCERS. It renders
        # only if that ever changes — it must never be implied.
        + _row("Position", _v(lc.get("position_known")))
    )

    body += market_block(market)

    if reasons:
        body += _reasons(lc)

    ref = _v((entry or {}).get("id")) or _v(lc.get("decision_id"))
    tail = f"<code>entry {ref[:8]}</code>" if ref else ""
    return (f"{head}\n{'─' * 22}\n{body}"
            + (f"{'─' * 22}\n{tail}" if tail else "")).strip()


def simple_signal_message(signal: Any = None,
                          market: Optional[Mapping[str, Any]] = None) -> str:
    """The simple entry system's alert — the verdict, the five rules, the read.

    `""` when the gate did not fire. A rule engine that messages on every cycle
    to say "not yet" is a rule engine nobody reads.

    The rules are listed **with their measurements**, not just ticked. "bounce
    beats break" is a claim; "bounce 72% vs break 28%" is the evidence for it,
    and the evidence is what lets a trader disagree.
    """
    side = getattr(signal, "side", None) or (signal or {}).get("side")
    fired = getattr(signal, "fired", None)
    if fired is None:
        fired = (signal or {}).get("fired")
    if not fired or side not in ("CALL", "PUT"):
        return ""

    emoji = "🟢" if side == "CALL" else "🔴"
    kind = (getattr(signal, "level_kind", "") or "").title()
    level = _num(getattr(signal, "level", None), "{:,.0f}")

    head = f"{emoji} <b>MIOS ENTRY — BUY {side}</b>"
    if kind and level:
        head += f"\nat {kind} <b>{level}</b>"

    rules = getattr(signal, "rules", ()) or ()
    ticks = "".join(f"  ✓ {name} — {detail}\n" for name, ok, detail in rules
                    if ok)

    warn = "".join(f"  ⚠ {w}\n"
                   for w in (getattr(signal, "warnings", ()) or ()))

    return (f"{head}\n"
            + market_block(market)
            + f"{'─' * 22}\n{ticks}{warn}").strip()
