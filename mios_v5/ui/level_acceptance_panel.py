"""⚔️ The Level Acceptance / Rejection strip.

Compact, one row per contested level (or battle zone): the observed state, the
confirmations that fired, and — for a cluster — the levels it merged. Pure
presentation of what `mios_v5.level_acceptance.observe_levels` decided; it adds
no number and renders `""` when nothing is being contested, so a permanent empty
strip never trains the eye to ignore it.

Deliberately separate from the predictive breakout/rejection %: this reports what
price ACTUALLY did, and the footer says so.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..level_acceptance import (ACCEPTED_ABOVE, ACCEPTED_BELOW, BREAK_ATTEMPT,
                                FAILED_BREAK_WAIT, REJECTED, TESTING)

#: observed state → (icon, wording, accent colour)
_DISPLAY = {
    TESTING: ("⚔️", "TESTING", "#9aa5b1"),
    BREAK_ATTEMPT: ("🟡", "BREAK ATTEMPT", "#e0a030"),
    ACCEPTED_ABOVE: ("🟢", "ACCEPTED ABOVE", "#00c853"),
    ACCEPTED_BELOW: ("🟢", "ACCEPTED BELOW", "#00c853"),
    FAILED_BREAK_WAIT: ("🟠", "FAILED BREAK — WAIT", "#ff8c00"),
    REJECTED: ("🔴", "REJECTED", "#ff3b30"),
}
_ARROW = {"ABOVE": " ↑", "BELOW": " ↓"}

_WRAP = ("margin:6px 0;padding:8px 12px;background:#1a2230;"
         "border-left:3px solid #4a5568;border-radius:6px;"
         "font-size:12.5px;color:#c5d0dc;text-align:left;")
_ROW = "margin-top:3px;"
_SUB = "color:#8a95a3;font-size:11px;"


def _retest_chip(retest: Optional[Dict[str, Any]]) -> str:
    """`Retest ✓/✗/…` when a retest was detected, else nothing."""
    r = retest or {}
    if not r.get("detected"):
        return ""
    mark = "✓" if r.get("passed") else "✗" if r.get("failed") else "…"
    return f"Retest {mark}"


def _checks_line(checks: Dict[str, bool], passed: int, known: int,
                 retest: Optional[Dict[str, Any]] = None) -> str:
    parts = [f"{lbl} {'✓' if ok else '✗'}" for lbl, ok in checks.items()]
    chip = _retest_chip(retest)
    if chip:
        parts.append(chip)
    if not parts:
        return ""
    tail = f" &nbsp;<b>{passed}/{known}</b>" if checks else ""
    return f"<div style='{_ROW}{_SUB}'>{' · '.join(parts)}{tail}</div>"


def _zone_html(z: Dict[str, Any]) -> str:
    observed = z.get("observed")
    icon, word, colour = _DISPLAY.get(observed, ("⚔️", str(observed or "—"), "#9aa5b1"))
    arrow = _ARROW.get(z.get("direction") or "", "")
    price = z.get("price")
    is_zone = z.get("is_battle_zone")
    name = "BATTLE ZONE" if is_zone else (z.get("labels") or ["level"])[0]
    head = (f"<div style='{_ROW}'>{icon} "
            f"<b style='color:{colour};'>₹{price:,.0f} · {word}{arrow}</b>"
            f" <span style='{_SUB}'>{name}</span></div>")
    lines = [head]
    if is_zone:
        lines.append(f"<div style='{_SUB}'>{' · '.join(z.get('labels') or [])}</div>")
    ck = _checks_line(z.get("checks") or {}, z.get("passed", 0), z.get("known", 0),
                      z.get("retest"))
    if ck:
        lines.append(ck)
    return "".join(lines)


def acceptance_oneliner(read: Optional[Dict[str, Any]]) -> str:
    """The COMPACT Trade-Card form — one line per contested zone, state only, no
    evidence rows. `""` when nothing is contested. The detailed evidence lives in
    `acceptance_html` (rendered in the Market Picture), never both."""
    zones: List[Dict[str, Any]] = (read or {}).get("zones") or []
    if not zones:
        return ""
    out = []
    for z in zones:
        observed = z.get("observed")
        icon, word, colour = _DISPLAY.get(observed, ("⚔️", str(observed or "—"), "#9aa5b1"))
        arrow = _ARROW.get(z.get("direction") or "", "")
        out.append(
            f"<div style='margin-top:3px;text-align:center;font-size:13px;'>{icon} "
            f"<b style='color:{colour};'>₹{z.get('price'):,.0f} · {word}{arrow}</b>"
            f"</div>")
    return "".join(out)


def acceptance_html(read: Optional[Dict[str, Any]]) -> str:
    """The strip. `""` when nothing is being contested."""
    r = read or {}
    zones: List[Dict[str, Any]] = r.get("zones") or []
    if not zones:
        return ""
    head = ("<div><span style='color:#dbe4ee;font-weight:800;'>⚔️ Level "
            "acceptance</span> <span style='" + _SUB + "'>· what price did</span></div>")
    body = "".join(_zone_html(z) for z in zones)
    footer = ("<div style='margin-top:5px;color:#8a95a3;font-size:11px;'>"
              "Observed, not predicted — separate from breakout/rejection %. "
              "Context only.</div>")
    return f"<div style='{_WRAP}'>{head}{body}{footer}</div>"
