"""The execution chain — Stages 72 → 73 → 72.9, on one card.

Pure presentation. Every value was decided by the three stages; this file
decides only where it sits and what colour it is.

## Why the three belong on one card

They are one thought split across three owners. Stage 72 says *should I enter*,
Stage 73 says *what do I do about the position*, Stage 72.9 says *does anyone
get told*. Rendered apart, a trader has to hold three panels in their head to
answer one question; rendered together, the disagreements are visible — and the
disagreements are the interesting part. Stage 72 saying `ENTER` while Stage 73
says `ABORT` is exactly the moment worth seeing.

## ⚠️ Nothing here has been sent

The dispatcher runs with **no transport**, so it prepares a payload, decides
whether it *would* send, and reports `NOT_SENT`. Stage 72.9 is
`VALIDATED_SIMULATED`; `STAGE72_9_VALIDATION_REPORT.md` records
`freeze_ready: False`. The panel says so on every render rather than in a
footnote, because a dispatch state that reads like a delivery is the one
misreading that would cost money.

## Every decision carries its identity

`id`, `version` and the first bytes of `hash` are shown. Not decoration: Stage
73 references Stage 72's id rather than minting its own, and seeing the same id
across all three rows is how a reader confirms the chain is describing one
decision rather than three independent ones.

## ⚠️ It never renders blank

This used to return `""` when Stage 72 had not decided anything, and a quiet
market was indistinguishable from a broken app. Worse, the three ways the chain
can fail to run were all silent:

  1. `_strike_validation` returns early when the ATM ladder is unpublished, and
     the chain used to be nested *inside* it — so the only trace was a caption
     about the strike picker.
  2. That function wraps ~145 lines in one `except`, so a failure anywhere
     before the chain reported as "Strike Validation unavailable".
  3. `_run_execution_chain` returned silently when the context was absent.

Four gates between "the app is running" and "the trader knows why there is no
signal", and none of them said the execution chain had not run. So this file's
rule is now: **something always renders, and it always says which of the two
situations you are in** — the chain ran and decided WAIT, or the chain never
ran. Those look identical from the outside and mean completely different
things.

## The gate block distinguishes gates from weights

Stage 72 has **hard gates** (a frozen tape, an invalid strike — absolute, checked
before any score) and **weighted components** (eleven inputs averaged). Showing
them as one list would be a lie: a component scoring 30 has not "failed a gate",
it has voted low and been outvoted. They are rendered as two blocks that say
which is which, and a component that did not report says so rather than showing
0 — the unknown-excluded rule made visible, since a score over four inputs and a
score over eleven must never look the same.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .theme import (ALERT, BEAR, BULL, BULL_SOFT, FAINT, INK, MICRO,
                    MUTED, WARN, grade_tone)

UNKNOWN = "UNKNOWN"

#: Stage 52's vocabulary, coloured by what it means for a trader.
_STATE_COL = {
    "ENTER": BULL, "ENTRY_READY": BULL_SOFT, "ADD": BULL_SOFT,
    "HOLD": MUTED, "WAIT": MUTED, "TRAIL": WARN,
    "SCALE_OUT": WARN, "EXIT": ALERT, "ABORT": ALERT, "COMPLETE": MICRO,
    "WAIT_ENTRY": MUTED, "ENTERED": BULL_SOFT,
}

#: Dispatch states. `DELIVERED` is deliberately NOT green — nothing in this
#: build delivers, so a green delivery badge would be a lie waiting to happen.
_DISPATCH_COL = {
    "SENT": BULL_SOFT, "DELIVERED": BULL_SOFT, "READY": WARN,
    "NOT_SENT": MICRO, "BLOCKED": ALERT, "DUPLICATE": MICRO,
    "RATE_LIMIT": WARN, "RETRY": WARN, "DELIVERY_FAILED": ALERT,
    "SUPERSEDED": MICRO, "EXPIRED": MICRO, "WAIT": MUTED, "FAILED": ALERT,
    # Not an error — the signal was real and was held back because the same one
    # went out recently. Muted, so it does not read as a fault.
    "COOLDOWN": MICRO,
}

#: The eleven weighted inputs, in the trader's words rather than the context's
#: field paths. Read from the decision's OWN `metadata["weights"]` rather than
#: imported from Stage 72, so a stored decision renders against the weights it
#: was written with instead of today's.
_GATE_LABEL = {
    "strike.validation": "Strike valid",
    "energy.energy": "Premium energy",
    "opportunity.opportunity_score": "Opportunity",
    "premium.premium_score": "Premium structure",
    "premium.behaviour": "Level interaction",
    "opportunity.confidence": "Confidence",
    "strike.liquidity": "Strike liquidity",
    "energy.spike_probability": "Spike probability",
    "risk.validity": "Risk engine",
    "htf.alignment": "HTF alignment",
    "market.stability": "Market regime",
}

#: A component's score → how it read. These are **not** pass/fail gates; see the
#: module docstring. `—` is reserved for "did not report", which is a third
#: outcome and never rendered as a low score.
_STRONG, _MIXED = 60.0, 40.0

#: States in which a decision is worth remembering as "the last real signal".
_VALID_SIGNAL = ("ENTER", "ENTRY_READY", "ADD")



def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if s and s != UNKNOWN else "—"


def _px(v) -> str:
    n = _num(v)
    return "—" if n is None else f"{n:,.1f}"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """A field from a frozen decision or from a stored dict.

    Both shapes render identically, so a replayed decision looks like a live
    one — which is the point of the identity fields below.

    ⚠️ The `isinstance` test is `Mapping`, not `dict`, and that is a bug fix
    rather than a tidy-up. Every stage in MIOS freezes its metadata as a
    `MappingProxyType`, which is **not** a `dict` subclass — so the old check
    fell through to the default for every field on every `metadata` this panel
    ever read. `state_reason` — the one line that explains why Stage 72 said
    WAIT — has been rendering blank since the panel was written. The card
    showed the verdict and silently dropped the reason, which is exactly the
    black box this work exists to open.
    """
    if obj is None:
        return default
    got = getattr(obj, name, None)
    if got is None and isinstance(obj, Mapping):
        got = obj.get(name)
    return default if got is None else got


def _cell(label: str, value: str, tone: str = MUTED) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
            f"{value}</div></div>")


def _identity(obj: Any) -> str:
    """id · version · hash prefix. Seeing the same id on Stage 73's row as on
    Stage 72's is how a reader confirms the chain describes one decision."""
    ident = str(_get(obj, "id", "") or "")
    version = str(_get(obj, "version", "") or "")
    digest = str(_get(obj, "hash", "") or "")
    bits = []
    if ident:
        bits.append(ident[:8])
    if version:
        bits.append(f"v{version}")
    if digest:
        bits.append(digest[:8])
    return " · ".join(bits) or "—"


def _row(stage: str, name: str, headline: str, colour: str,
         cells: str, ident: str, note: str = "") -> str:
    return (
        f"<div style='background:#0b0f16;border:1px solid #1e2836;"
        f"border-radius:8px;padding:8px 9px;margin-top:6px'>"
        f"<div style='display:flex;gap:8px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='color:{MICRO};font-size:9px;letter-spacing:.08em'>"
        f"{stage}</span>"
        f"<span style='color:{MUTED};font-size:10.5px'>{name}</span>"
        f"<span style='color:{colour};font-weight:800;font-size:13px'>"
        f"{headline}</span>"
        f"<span style='color:{MICRO};font-size:9px;margin-left:auto;"
        f"white-space:nowrap;font-family:monospace'>{ident}</span></div>"
        + (f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:5px;"
           f"padding-top:4px;border-top:1px solid #1a2330'>{cells}</div>"
           if cells else "")
        + (f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>{note}"
           f"</div>" if note else "")
        + "</div>")


def _chip(label: str, tone: str) -> str:
    return (f"<span style='display:inline-block;background:#0b0f16;"
            f"border:1px solid #1e2836;border-radius:5px;padding:1px 6px;"
            f"margin:2px 3px 0 0;font-size:9.5px;color:{tone}'>{label}</span>")


def _gates_html(decision: Any) -> str:
    """Hard gates, then the weighted components — labelled as what they are."""
    meta = _get(decision, "metadata", {}) or {}
    out = []

    blocks = tuple(_get(meta, "readiness_blocks", ()) or ())
    unknowns = tuple(_get(meta, "readiness_unknowns", ()) or ())
    readiness = str(_get(decision, "readiness", UNKNOWN))
    tone = (ALERT if blocks else WARN if readiness != "READY" else BULL_SOFT)
    hard = "".join(_chip(f"⛔ {b}", ALERT) for b in blocks) or \
        "".join(_chip(f"◌ {u} did not report", WARN) for u in unknowns) or \
        _chip("✓ no hard gate blocked", BULL_SOFT)
    out.append(
        f"<div style='margin-top:6px'><div style='font-size:8.5px;"
        f"letter-spacing:.08em;color:{MICRO};text-transform:uppercase'>"
        f"Hard gates · absolute, checked before any score — readiness "
        f"<span style='color:{tone}'>{readiness}</span></div>{hard}</div>")

    weights = _get(meta, "weights", {}) or {}
    comps = _get(meta, "components", {}) or {}
    if weights:
        chips = []
        for key in weights:
            label = _GATE_LABEL.get(key, key)
            val = _num(_get(comps, key))
            if val is None:
                chips.append(_chip(f"◌ {label} — not reported", MICRO))
            elif val >= _STRONG:
                chips.append(_chip(f"✓ {label} {val:.0f}", BULL_SOFT))
            elif val >= _MIXED:
                chips.append(_chip(f"~ {label} {val:.0f}", WARN))
            else:
                chips.append(_chip(f"✗ {label} {val:.0f}", ALERT))
        reporting = sum(1 for k in weights if _num(_get(comps, k)) is not None)
        out.append(
            f"<div style='margin-top:6px'><div style='font-size:8.5px;"
            f"letter-spacing:.08em;color:{MICRO};text-transform:uppercase'>"
            f"Weighted inputs · averaged, not gates — {reporting} of "
            f"{len(weights)} reported</div>{''.join(chips)}</div>")
    return "".join(out)


def _why_html(decision: Any, dispatch: Any) -> str:
    """Why there is no signal — the question a blank panel never answered."""
    meta = _get(decision, "metadata", {}) or {}
    lines = []
    for key in ("state_reason", "score_reason", "zone_reason", "risk_reason"):
        val = str(_get(meta, key, "") or "")
        if val and val != UNKNOWN:
            lines.append(val)
    for w in tuple(_get(decision, "warnings", ()) or ())[:3]:
        lines.append(str(w))
    if dispatch is not None and not _get(dispatch, "should_send", False):
        why = str(_get(dispatch, "dispatch_reason", "") or "")
        if why:
            lines.append(f"Telegram: {why}")
    if not lines:
        return ""
    items = "".join(f"<div style='color:{MUTED};font-size:10.5px;"
                    f"margin-top:2px'>• {t}</div>" for t in lines)
    return (f"<div style='margin-top:7px;padding-top:6px;"
            f"border-top:1px solid #1a2330'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>Why no signal?</div>{items}</div>")


def _last_signal_html(last: Any) -> str:
    """The most recent real signal, still on screen while the current read is
    WAIT. A quiet market otherwise looks exactly like a broken app."""
    if not last:
        return ""
    when = str(_get(last, "at", "") or "")
    cells = "".join([
        _cell("State", _txt(_get(last, "state")),
              _STATE_COL.get(str(_get(last, "state")), MUTED)),
        _cell("Side", _txt(_get(last, "side"))),
        _cell("Strike", _px(_get(last, "strike"))),
        _cell("Entry", _px(_get(last, "entry"))),
        _cell("Stop", _px(_get(last, "stop")), ALERT),
        _cell("Score", _txt(_get(last, "score"))),
        _cell("At", when or "—"),
    ])
    return (f"<div style='background:#0b0f16;border:1px dashed #24303f;"
            f"border-radius:8px;padding:7px 9px;margin-top:6px'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>Last valid signal · this session</div>"
            f"<div style='display:flex;flex-wrap:wrap;gap:10px;margin-top:4px'>"
            f"{cells}</div></div>")


def not_run_html(why: str = "") -> str:
    """The chain did not run at all — which is NOT the same as deciding WAIT.

    Rendered as its own card because the two are indistinguishable from a blank
    screen, and a trader reading "no signal" needs to know whether the system
    looked and declined, or never looked.
    """
    detail = why or ("The trading context was not available this cycle.")
    return (
        f"<div style='background:#0d1117;border:1px solid #3a2a1e;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>⚙️ Execution chain "
        f"<span style='color:{WARN};letter-spacing:0'>· did not run</span></div>"
        f"<div style='font-size:10.5px;color:{MUTED};margin-top:4px'>"
        f"Stage 72 was never asked, so there is no verdict — this is <b>not</b> "
        f"a decision to wait. {detail}</div></div>")


def execution_html(decision: Any = None, lifecycle: Any = None,
                   dispatch: Any = None, last_signal: Any = None,
                   not_run_reason: str = "") -> str:
    """The whole card. Never blank — see the module docstring."""
    if decision is None:
        return not_run_html(not_run_reason) + _last_signal_html(last_signal)

    state = str(_get(decision, "state", UNKNOWN))
    meta = _get(decision, "metadata", {}) or {}
    score = _num(_get(decision, "score"))
    quality = str(_get(decision, "quality", UNKNOWN))

    entry_cells = "".join([
        _cell("Score", "—" if score is None else f"{score:.0f}/100",
              BULL if (score or 0) >= 75 else WARN if (score or 0) >= 60
              else MUTED),
        _cell("Quality", _txt(quality), grade_tone(quality, MUTED)),
        _cell("Side", _txt(_get(decision, "side"))),
        _cell("Strike", _px(_get(decision, "strike"))),
        _cell("Zone", _txt(_get(decision, "entry_zone"))),
        _cell("Entry", _px(_get(decision, "entry"))),
        _cell("Stop", _px(_get(decision, "stop")), ALERT),
        _cell("R:R", _txt(_get(decision, "risk_reward"))),
        _cell("Readiness", _txt(_get(decision, "readiness"))),
    ])
    reason = str(_get(meta, "state_reason", "") or "")

    rows = _row("STAGE 72", "Entry Engine", state,
                _STATE_COL.get(state, FAINT), entry_cells,
                _identity(decision), reason)
    rows += _gates_html(decision)

    if lifecycle is not None:
        action = str(_get(lifecycle, "action", UNKNOWN))
        lc_cells = "".join([
            _cell("State", _txt(_get(lifecycle, "state"))),
            _cell("Health", _txt(_get(lifecycle, "health"))),
            _cell("Intent", _txt(_get(lifecycle, "intent"))),
            # Always UNKNOWN by design — no producer publishes the position, and
            # Stage 73 refuses to infer one.
            _cell("Position", _txt(_get(lifecycle, "position_known")), MICRO),
            _cell("Trail", _txt(_get(lifecycle, "trail"))),
            _cell("Exit reason", _txt(_get(lifecycle, "exit_reason"))),
        ])
        same = (str(_get(lifecycle, "decision_id", "")) ==
                str(_get(decision, "id", "")))
        rows += _row(
            "STAGE 73", "Trade Lifecycle", action,
            _STATE_COL.get(action, FAINT), lc_cells, _identity(lifecycle),
            "" if same else "⚠ this lifecycle does not reference the entry "
                            "decision above")

    if dispatch is not None:
        d_state = str(_get(dispatch, "dispatch_state", UNKNOWN))
        tele = str(_get(dispatch, "telegram_state", UNKNOWN))
        # `should_send` is the verdict, `telegram_state` is what happened.
        # Showing both is the point of running the chain unwired: the gap
        # between "would have sent" and "sent" is exactly what is being
        # withheld until Stage 72.9 is validated.
        record = _get(dispatch, "record")
        d_cells = "".join([
            _cell("Would send", _txt(_get(dispatch, "should_send"))),
            _cell("Telegram", _txt(tele), _DISPATCH_COL.get(tele, MICRO)),
            _cell("Duplicate", _txt(_get(dispatch, "duplicate"))),
            _cell("Message id",
                  _txt(_get(record, "telegram_message_id")) if record else "—"),
        ])
        rows += _row("STAGE 72.9", "Dispatcher", d_state,
                     _DISPATCH_COL.get(d_state, FAINT), d_cells,
                     _identity(dispatch),
                     str(_get(dispatch, "dispatch_reason", "") or ""))

    # ── the delivery banner has to track reality ──────────────────────
    # It used to assert "Nothing is sent" unconditionally. That was true when
    # the dispatcher ran with no transport; it stopped being true the moment
    # the sidebar toggle started passing `mios_v6_transport` in, and a panel
    # that swears nothing was sent while a message is arriving on the phone is
    # worse than one that says nothing at all. Derived from the dispatch state
    # now, so it cannot drift from the wiring again.
    sent = str(_get(dispatch, "telegram_state", "")) in ("SENT", "DELIVERED")
    if sent:
        banner = (f"<div style='font-size:10px;color:{BULL_SOFT};margin-top:3px'>"
                  f"📨 <b>Sent.</b> Stage 72.9 delivered this decision through "
                  f"the transport the sidebar toggle supplied. It remains "
                  f"VALIDATED_SIMULATED — <code>freeze_ready: False</code>.</div>")
    else:
        banner = (f"<div style='font-size:10px;color:{WARN};margin-top:3px'>"
                  f"⚠️ <b>Not sent this cycle.</b> The dispatcher prepared the "
                  f"payload and reported what it <i>would</i> do; the reason is "
                  f"on the Stage 72.9 row. Stage 72.9 is VALIDATED_SIMULATED "
                  f"and its report records <code>freeze_ready: False</code>.</div>")

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>⚙️ Execution chain "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stages 72 → 73 → "
        f"72.9 · advisory</span></div>"
        + banner + rows
        + _why_html(decision, dispatch)
        + _last_signal_html(last_signal)
        + "</div>")


def render_execution(st, decision: Any = None, lifecycle: Any = None,
                     dispatch: Any = None, last_signal: Any = None,
                     not_run_reason: str = "") -> None:
    """Draw it. Advisory — it may never take the tab down.

    Unlike before, there is no path where this renders nothing: a chain that
    did not run says so, because silence and WAIT are the two readings a trader
    must never confuse.
    """
    try:
        html = execution_html(decision, lifecycle, dispatch,
                              last_signal=last_signal,
                              not_run_reason=not_run_reason)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Execution chain unavailable: {err}")


def remember_signal(decision: Any) -> Optional[Dict[str, Any]]:
    """A compact snapshot of a decision worth keeping on screen, or None.

    Returns None for WAIT/ABORT so a caller can write it straight into session
    state without clobbering the last real signal with a quiet cycle.
    """
    if decision is None:
        return None
    state = str(_get(decision, "state", ""))
    if state not in _VALID_SIGNAL:
        return None
    return {"state": state, "side": _get(decision, "side"),
            "strike": _get(decision, "strike"), "entry": _get(decision, "entry"),
            "stop": _get(decision, "stop"), "score": _get(decision, "score"),
            "id": _get(decision, "id"),
            "at": str(_get(decision, "created_at", ""))[11:16] or "—"}
