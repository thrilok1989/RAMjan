"""📍 The NIFTY spot strip — one number, refreshed on its own clock.

## Why this is a separate strip rather than a faster page

The whole app reruns on a 20-second `st_autorefresh`. That cycle fetches the
option chain, runs the MIOS pass and writes to Supabase, so halving it to get a
faster price would double the Dhan calls and the Supabase egress the last round
of work spent itself getting *down*. Spot is the one number worth its own clock,
and it is also the cheapest thing on the page to refresh: `get_index_spot_ltp`
is a single `marketfeed/ltp` call, already 4-second cached and already skipped
during a 429 back-off.

So this strip runs in a `st.fragment(run_every=…)` — Streamlit reruns the
fragment body alone, leaving the rest of the page untouched. One small quote
every 10 seconds instead of an entire cycle.

## What it does NOT claim

⚠️ The strip is 10 seconds fresh. **The panels below it are not.** They redraw
on the 20-second page cycle, so between reruns a panel can be showing a spot up
to one cycle behind the strip. What `mios_v5.spot` fixed is the part that was
actually wrong — panels disagreeing *with each other* at the same instant,
because four different files each had their own idea of which key was "spot".
They now share one precedence, so at every page rerun every panel shows the same
number, and that number is whatever this strip last published.

Which is why the age is rendered, always. A price with no timestamp under a
ticking clock is the misreading this strip exists to remove, not create.

Pure module — data in, HTML out. The fetching and the publishing live in
`vob_minimal.py`, where the Dhan client and session state already are.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .theme import (BEAR, BULL, CARD_BORDER, FAINT, INK, MICRO, MUTED,
                    PANEL_BG, WARN)

#: Age at which the strip stops looking live, in seconds.
#:
#: Deliberately above the 10-second cadence with room to spare: at exactly 10s a
#: quote that arrived a moment late would flicker amber every other tick, and a
#: warning that cries wolf is worse than none. Beyond ~2 missed ticks the fetch
#: is genuinely failing and the trader should know.
WARN_AGE = 25.0

#: What each `spot.read()` source is called on screen. The strip says where the
#: number came from rather than implying every read is a live tick.
#:
#: ⚠️ `"live LTP"` maps to two words, not one — see `_status`. A quote that came
#: from the live endpoint but has since gone cold is not "live", and rendering
#: `🔴 live · 30s ago` (which this did) asks the trader to believe both halves of
#: a contradiction.
SOURCE_LABEL = {
    "live LTP": "live",
    "option chain": "from chain",
    "live LTP (stale)": "last tick",
    "last candle close": "last candle",
}

#: The live source, named so `_status` and `micro` cannot spell it differently.
LIVE_SOURCE = "live LTP"

#: What the live LTP is called once it has gone quiet but is still the best read.
COLD_LABEL = "last tick"


def _f(v: Any) -> Optional[float]:
    """A finite float, or None. Signed — the change may be negative."""
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x or x in (float("inf"), float("-inf")) else x


def _price(v: Any) -> Optional[float]:
    """A POSITIVE float, or None.

    ⚠️ Separate from `_f` on purpose. `spot.read` already refuses a
    non-positive price, but the strip must refuse one too rather than trust its
    caller: `₹0.00` at the top of the page, in the same white 23px as a real
    quote, is the single most misleading thing this module could draw.
    """
    x = _f(v)
    return None if x is None or x <= 0 else x


def _esc(v: Any) -> str:
    """Escape anything that reaches the markup as text."""
    import html

    return html.escape(str(v), quote=True)


def _status(source: str, age: Optional[float], stale: bool):
    """`(dot, label, tone)` — how much to trust this number's freshness.

    Three states, not two, because there are genuinely three situations and
    collapsing them produced both of the misreadings this replaces:

        🟢 live       the live endpoint answered, within `WARN_AGE`
        🟡 from chain a real quote from the OTHER endpoint, on its own slower
                      cadence — so its age is unknown, not zero
        🔴 cold       the live LTP has gone quiet, or all that is left is a
                      candle close

    ⚠️ Amber for the chain rather than green. The chain price is real and freshly
    fetched *by the chain*, but nothing on the strip knows when that was, and a
    green dot claims a freshness it cannot show. `micro()` was already warning
    about exactly this case while the strip beside it drew green — two surfaces
    disagreeing about one number, which is the class of bug this whole change is
    about.
    """
    is_live = source == LIVE_SOURCE
    cold = bool(stale) or (age is not None and age > WARN_AGE)
    if is_live and not cold:
        return "🟢", SOURCE_LABEL[LIVE_SOURCE], BULL
    if is_live:
        # From the live endpoint, but old enough that calling it live would lie.
        return "🔴", COLD_LABEL, WARN
    if source == "option chain":
        return "🟡", SOURCE_LABEL[source], WARN
    return "🔴", SOURCE_LABEL.get(source, source or "—"), WARN


def _age_text(age: Any) -> str:
    """`3s ago` / `1m 12s ago`. Absent when nothing stamped a clock."""
    a = _f(age)
    if a is None or a < 0:
        return ""
    if a < 60:
        return f"{a:.0f}s ago"
    return f"{int(a // 60)}m {int(a % 60):02d}s ago"


def spot_strip_html(read: Any = None, prev_close: Any = None) -> str:
    """The strip. `""` when nothing reported a price.

    `read` is `mios_v5.spot.read()`'s output — price, source, age and the
    candidates. `prev_close` comes from `_gap_today`, the producer that already
    owns it; the change is arithmetic on two given numbers, not a new opinion
    about either.

    Returns an empty string rather than a ₹0 row when there is no price: a strip
    that draws a confident zero is how a trader ends up reading the floor as the
    market.
    """
    r = read if isinstance(read, Mapping) else {}
    price = _price(r.get("price"))
    if price is None:
        return ""

    src = str(r.get("source") or "")
    age = _f(r.get("age_s"))
    dot, word, edge = _status(src, age, bool(r.get("stale")))
    label = _esc(word)

    # ── the change, when there is something to compare against ───────
    change = ""
    pc = _f(prev_close)
    if pc is not None and pc > 0:
        d = price - pc
        tone = BULL if d > 0 else BEAR if d < 0 else MUTED
        change = (f"<span style='font-size:14px;font-weight:700;color:{tone};"
                  f"margin-left:10px'>{d:+,.2f}"
                  f"<span style='font-size:11.5px;font-weight:600;"
                  f"margin-left:5px'>({d / pc * 100:+.2f}%)</span></span>")

    chip_tone = MICRO if edge == BULL else WARN
    at = _age_text(age)
    when = f" · {at}" if at else ""

    return (
        f"<div style='display:flex;align-items:baseline;gap:2px;flex-wrap:wrap;"
        f"margin:2px 0 6px 0;padding:7px 13px;background:{PANEL_BG};"
        f"border:1px solid {CARD_BORDER};border-left:3px solid "
        f"{edge};border-radius:7px'>"
        f"<span style='font-size:9.5px;letter-spacing:.14em;color:{MICRO};"
        f"font-weight:700'>NIFTY</span>"
        f"<span style='font-size:23px;font-weight:800;color:{INK};"
        f"margin-left:9px;letter-spacing:-.01em'>₹{price:,.2f}</span>"
        + change
        + f"<span style='flex:1'></span>"
          f"<span style='font-size:10px;color:{chip_tone}'>"
          f"{dot} {label}{when}</span>"
          f"<span style='font-size:9px;color:{FAINT};margin-left:9px'>"
          f"every 10s · panels below refresh on the 20s cycle</span>"
          f"</div>")


def micro(read: Any = None) -> str:
    """One-line form, for anywhere the full strip does not fit.

    Only says something when the price is NOT live — a header already carries
    spot, so repeating it costs frozen screen space to tell the trader what they
    can already see. An aged quote is the part they cannot see.

    ⚠️ Shares `_status` with the strip rather than testing freshness again. The
    two used to decide separately and were caught disagreeing on a real render:
    the strip drew a green "live" dot on a chain price while this line warned
    about the very same read.
    """
    r = read if isinstance(read, Mapping) else {}
    if _price(r.get("price")) is None:
        return ""
    age = _f(r.get("age_s"))
    dot, word, edge = _status(str(r.get("source") or ""), age,
                              bool(r.get("stale")))
    if edge == BULL:
        return ""
    at = _age_text(age)
    return f"{dot} spot {word}" + (f" · {at}" if at else "")
