"""MIOS V6 — the overlay toggle panel.

One checkbox per overlay family. Hiding is a filter over the collected list —
nothing is recomputed when a group is switched off, and switching it back on
costs nothing but a redraw.

Each toggle shows how many overlays that group actually contributed. A group
with nothing to draw says `0` rather than looking available, which is the
difference between "off" and "empty" — and a trader who cannot tell them apart
will keep toggling a group that was never going to draw anything.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..overlays import GROUPS

_KEY = "_overlay_toggles"


def overlay_controls(st, counts: Optional[Dict[str, int]] = None
                     ) -> Dict[str, bool]:
    """Render the toggles and return the enabled map.

    State lives in `session_state` so a choice survives the rerun — a toggle
    that resets every cycle is worse than no toggle at all.
    """
    counts = dict(counts or {})
    state: Dict[str, bool] = st.session_state.setdefault(
        _KEY, {g: on for g, (_l, on) in GROUPS.items()})

    with st.expander("🎚 Overlays", expanded=False):
        cols = st.columns(4)
        for i, (group, (label, default)) in enumerate(GROUPS.items()):
            n = counts.get(group)
            suffix = "" if n is None else f" ({n})"
            with cols[i % 4]:
                state[group] = st.checkbox(
                    f"{label}{suffix}",
                    value=bool(state.get(group, default)),
                    key=f"_ov_{group}",
                    help=("Nothing to draw for this group right now"
                          if n == 0 else None),
                    disabled=(n == 0))
        st.caption("Hiding an overlay filters what is drawn — nothing is "
                   "recalculated, and no engine stops running.")

    st.session_state[_KEY] = state
    return state


def legend_html(items) -> str:
    """A compact legend naming the engine behind each overlay family.

    A level on screen should always be traceable to the thing that claimed it —
    otherwise a trader is asked to trust a line with no author.
    """
    seen: Dict[str, str] = {}
    for i in (items or []):
        seen.setdefault(i.get("label", ""), i.get("source", ""))
    if not seen:
        return ""
    chips = "".join(
        f"<span style='display:inline-block;margin:1px 5px 1px 0;"
        f"font-size:10px;color:#9fb0c4'>{lab} "
        f"<span style='color:#6f7d8f'>· {src}</span></span>"
        for lab, src in list(seen.items())[:14])
    return (f"<div style='margin-top:2px;line-height:1.5'>{chips}</div>")
