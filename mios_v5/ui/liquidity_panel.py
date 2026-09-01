"""Stage 74 — the Liquidity Intelligence panel, and the heatmap.

Pure presentation. Every value was computed by `mios_v5.liquidity`; this file
decides only where it sits and what colour it is. `None` renders as `—`, never
as `0`.

## Why this panel is not optional ⚠️

Principle 12: *nothing may influence a trading decision unless the trader can
inspect that exact value somewhere in the UI.* Stage 74 publishes eight facts
that nothing else in the system computes, and the moment any stage reads one,
that rule binds. Rendering it **before** the stage injection is deliberate: a
number that has never been looked at should not become load-bearing in twenty
consumers.

## The heatmap lives here, not in the engine

`docs/AUDIT_LIQUIDITY_INTELLIGENCE.md` §6 put it in a panel on purpose. The
profile rows already carry `ratio` (share of the busiest bin) and
`sentiment_strength`; a heatmap is a **colour mapping over published numbers**,
which is presentation by definition. An engine that returned colours would be
an engine nobody could restyle.

Two heatmaps, because they answer different questions:

* **Liquidity** — *how much* traded here. Blue → yellow → red, cold to hot,
  which is the intensity ramp the specification asked for.
* **Sentiment** — *who* traded here. Green/red by side, opacity by conviction.

Rendering only one would force a trader to choose between "where is the volume"
and "who owns it", and the interesting bins are the ones where those two
disagree.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..liquidity import (BALANCED, BEARS, BULLS, DIV_BEAR, DIV_BULL, DIV_NONE,
                         DYNAMIC, MAJOR, MINOR, POC_FALLING, POC_RISING,
                         POC_STABLE, SHIFT_COMPRESSING, SHIFT_DOWN,
                         SHIFT_EXPANDING, SHIFT_HOLDING, SHIFT_UP, UNKNOWN)
from .theme import (ALERT, BEAR, BULL, BULL_SOFT, FAINT, INK, MICRO, MUTED,
                    WARN)

#: The intensity ramp the specification named: blue (cold) → yellow → red (hot),
#: with a **cyan stop** between the first two. Not decoration — interpolating
#: blue to yellow directly in RGB passes through grey at the quarter mark, and a
#: desaturated bin on a heatmap reads as "no data" rather than "a little". The
#: cyan stop keeps the whole ramp saturated, so intensity is the only thing
#: changing.
#:
#: Not in `theme.py` because nothing else in the app ramps by intensity.
_RAMP: tuple = ("#2962ff", "#00c8c8", "#ffd000", "#f23645")

_DOMINANCE_COL = {BULLS: BULL, BEARS: BEAR, BALANCED: MUTED}

_SHIFT_COL = {
    SHIFT_UP: BULL, SHIFT_DOWN: BEAR, SHIFT_EXPANDING: WARN,
    SHIFT_COMPRESSING: ALERT, SHIFT_HOLDING: MUTED,
}

_POC_COL = {POC_RISING: BULL, POC_FALLING: BEAR, POC_STABLE: MUTED}

#: A divergence is the one reading here that contradicts the rest of the stack,
#: so it is the one that gets the loud colour.
_DIV_COL = {DIV_BULL: BULL, DIV_BEAR: ALERT, DIV_NONE: MUTED}

_RANK_COL = {MAJOR: INK, DYNAMIC: WARN, MINOR: MICRO}


def _num(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _d(v) -> Dict[str, Any]:
    """A dict, whatever arrived. A degraded cycle can leave a session-state
    cache holding a string, and a panel is not allowed to raise on one."""
    return dict(v) if isinstance(v, dict) else {}


def _seq(v) -> List[Any]:
    return list(v) if isinstance(v, (list, tuple)) else []


def _txt(v) -> str:
    s = "" if v is None else str(v).strip()
    return s if s and s != UNKNOWN else "—"


def _px(v) -> str:
    n = _num(v)
    return "—" if n is None else f"{n:,.1f}"


def _conf_col(score: Optional[float]) -> str:
    """Confidence bands. Deliberately coarse — the number is a 0–100 estimate
    built partly from components that have no producer yet, and colouring it in
    ten shades would imply a precision it does not have."""
    if score is None:
        return FAINT
    return (BULL if score >= 80 else BULL_SOFT if score >= 60
            else WARN if score >= 40 else MICRO)


def _cell(label: str, value: str, tone: str = MUTED) -> str:
    return (f"<div style='min-width:0'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase'>{label}</div>"
            f"<div style='font-size:11px;font-weight:700;color:{tone}'>"
            f"{value}</div></div>")


def ramp(intensity: Optional[float]) -> str:
    """Cold → hot over 0–1, across `_RAMP`'s stops.

    `None` is `FAINT`, not the cold end: a bin nobody measured and a bin that
    traded nothing must not render the same colour.

    The ramp is not perceptually uniform and does not need to be — it is read as
    "more or less than the bin next to it", not as an absolute quantity. What it
    does need is to stay saturated the whole way, which is what the cyan stop
    buys, and to be monotonic, which the stops are.
    """
    x = _num(intensity)
    if x is None:
        return FAINT
    x = max(0.0, min(1.0, x))
    spans = len(_RAMP) - 1
    idx = min(int(x * spans), spans - 1)
    return _mix(_RAMP[idx], _RAMP[idx + 1], x * spans - idx)


def _mix(a: str, b: str, t: float) -> str:
    t = max(0.0, min(1.0, t))
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{int(x + (y - x) * t):02x}" for x, y in zip(pa, pb))


# ══════════════════════════════════════════════════════════════════════
#  the heatmaps
# ══════════════════════════════════════════════════════════════════════

def _premium_px(v) -> str:
    """A premium, in rupees and paise.

    Separate from `_px` on purpose. An index bin is `24,650.0` and a premium
    bin is `₹96.20` — printing a premium with the index's one decimal rounds
    away the tick a leg actually moves in, and dropping the ₹ invites reading
    a premium level as a NIFTY level.
    """
    n = _num(v)
    return "—" if n is None else f"₹{n:,.2f}"


#: How many bars a heatmap draws.
#:
#: ⚠️ Display only. The PROFILE keeps its full resolution — `num_rows=25` — and
#: nothing about what the engines read changes. That is not a detail: the NIFTY
#: profile's bins feed `compute_major_sr_zones`, the POC, the value area, Stage
#: 74's clustering and Stage 71.86's shape, so re-binning the stored profile
#: would move S/R levels to make a chart tidier. Twenty-five thin bars are hard
#: to read; twenty-five bins are what the levels were computed from. Both are
#: true, and only one of them is a rendering problem.
MAX_BARS = 10


def _rebin(bins: List[Dict[str, Any]], n: int = MAX_BARS) -> List[Dict[str, Any]]:
    """Merge adjacent price bins into at most `n`, for display.

    Adjacent, never "the biggest `n`" — a profile is a price ladder, and
    dropping the quiet bins would leave gaps at prices that did trade and put
    two non-touching bars next to each other as though they were neighbours.

    Volume adds. Sentiment is re-derived from the summed bull/bear volume, not
    averaged from the constituent labels: three thin bullish bins merged with
    one heavy bearish bin is a **bearish** group, and a majority vote would call
    it bullish. Where bull/bear volumes were not published, the vote falls back
    to volume-weighting the labels, which is the best available answer rather
    than a guess dressed as arithmetic.
    """
    if n < 1 or len(bins) <= n:
        return bins
    ordered = sorted(bins, key=lambda r: _num(r.get("bin_low")) or 0.0)
    out: List[Dict[str, Any]] = []
    total = len(ordered)
    for i in range(n):
        group = ordered[(i * total) // n:((i + 1) * total) // n]
        if not group:
            continue
        vol = sum(_num(b.get("total_volume")) or 0.0 for b in group)
        bull = sum(_num(b.get("bull_volume")) or 0.0 for b in group)
        bear = sum(_num(b.get("bear_volume")) or 0.0 for b in group)
        if bull or bear:
            delta = bull - bear
            strength = (abs(delta) / (bull + bear) * 100.0) if (bull + bear) else 0.0
        else:
            # no per-side volume published — weight the labels by volume
            score = 0.0
            for b in group:
                w = _num(b.get("total_volume")) or 1.0
                s = str(b.get("sentiment") or "")
                score += w if s == "Bullish" else -w if s == "Bearish" else 0.0
            delta = score
            denom = sum(_num(b.get("total_volume")) or 1.0 for b in group)
            strength = (abs(score) / denom * 100.0) if denom else 0.0
        out.append({
            "bin_low": _num(group[0].get("bin_low")),
            "bin_high": _num(group[-1].get("bin_high")),
            "total_volume": vol, "bull_volume": bull, "bear_volume": bear,
            "delta": delta,
            "sentiment": ("Bullish" if delta > 0 else
                          "Bearish" if delta < 0 else "Neutral"),
            "sentiment_strength": strength,
        })
    # `ratio` is a share of the busiest bar, so it is recomputed against the
    # MERGED maximum. Carrying the old ratios forward would leave every bar
    # under-full, because no merged bar is the old busiest one.
    top = max((b["total_volume"] for b in out), default=0.0)
    for b in out:
        b["ratio"] = (b["total_volume"] / top) if top > 0 else 0.0
    return out


def heatmap_html(rows: Optional[Sequence[Any]], mode: str = "liquidity",
                 poc: Any = None, fmt=None, bars: int = MAX_BARS) -> str:
    """One bar per profile bin, highest price at the top — the way a profile is
    read on a chart, not the way the list happens to be ordered.

    `mode='liquidity'` colours by `ratio`, `mode='sentiment'` by side and
    conviction. The point of control is marked, because a heatmap without it is
    a gradient nobody can locate.

    `fmt` formats the price label; it defaults to the index style. A premium
    panel passes `_premium_px` — the bins are rupees, not index points.

    `bars` caps how many bars are DRAWN by merging adjacent bins. The profile
    itself is untouched — see `MAX_BARS`.
    """
    px = fmt or _px
    bins = [_d(r) for r in _seq(rows)]
    bins = [b for b in bins if b]
    if not bins:
        return ""
    bins = _rebin(bins, bars)

    poc_px = _num(poc)
    out = []
    for b in sorted(bins, key=lambda r: -(_num(r.get("bin_low")) or 0.0)):
        lo, hi = _num(b.get("bin_low")), _num(b.get("bin_high"))
        ratio = _num(b.get("ratio")) or 0.0
        if mode == "sentiment":
            side = str(b.get("sentiment") or "")
            base = BULL if side == "Bullish" else BEAR if side == "Bearish" else FAINT
            strength = (_num(b.get("sentiment_strength")) or 0.0) / 100.0
            colour = base
            width = max(4.0, min(100.0, strength * 100.0))
        else:
            colour = ramp(ratio)
            width = max(4.0, min(100.0, ratio * 100.0))

        at_poc = (poc_px is not None and lo is not None and hi is not None
                  and lo <= poc_px <= hi)
        mark = (f"<span style='color:{INK};font-weight:800'>◄ POC</span>"
                if at_poc else "")
        out.append(
            f"<div style='display:flex;align-items:center;gap:5px;"
            f"font-size:9px;padding:0.5px 0'>"
            f"<span style='width:62px;color:{MICRO};text-align:right'>"
            f"{px(hi)}</span>"
            f"<span style='flex:0 0 {width:.0f}%;height:8px;background:{colour};"
            f"border-radius:2px'></span>"
            f"{mark}</div>")
    return "".join(out)


# ══════════════════════════════════════════════════════════════════════
#  the clustered levels
# ══════════════════════════════════════════════════════════════════════

def _levels_html(levels: Dict[str, Any]) -> str:
    """Support below, resistance above, nearest first — and every level says
    how many independent owners put it there.

    The witness count is the whole point of the clustering. One source naming a
    level is a number; four sources naming the same level is a level.
    """
    sup, res = levels.get("support"), levels.get("resistance")
    if sup == UNKNOWN and res == UNKNOWN:
        return (f"<div style='font-size:10px;color:{FAINT};margin-top:4px'>"
                f"No level source reported this cycle.</div>")

    def rows(entries, colour, arrow):
        out = []
        for raw in _seq(entries)[:4]:
            # `Level` is the frozen contract; a plain dict is still accepted so
            # a stored or replayed level renders the same as a live one.
            e = raw.to_dict() if hasattr(raw, "to_dict") else _d(raw)
            if not e:
                continue
            rank = str(e.get("rank") or MINOR)
            conf = _num(e.get("confidence"))
            out.append(
                f"<div style='display:flex;gap:6px;align-items:baseline;"
                f"font-size:10.5px;padding:1px 0'>"
                f"<span style='width:12px;color:{colour}'>{arrow}</span>"
                f"<span style='width:64px;color:{_RANK_COL.get(rank, MICRO)};"
                f"font-weight:700'>{_px(e.get('price'))}</span>"
                # Confidence leads the metadata: it is what a consuming stage
                # gates on, and the witness count is one of its inputs.
                f"<span style='width:34px;font-weight:800;font-size:10px;"
                f"color:{_conf_col(conf)}'>"
                f"{'—' if conf is None else f'{conf:.0f}'}</span>"
                f"<span style='width:48px;color:{MICRO};font-size:9px'>"
                f"{rank}</span>"
                f"<span style='color:{MUTED};font-size:9px;min-width:0'>"
                f"{' · '.join(str(k) for k in _seq(e.get('kinds'))[:3])}</span>"
                f"<span style='color:{MICRO};font-size:9px;margin-left:auto;"
                f"white-space:nowrap'>{e.get('diversity', '—')}e · "
                f"{e.get('reporting', '—')}/{e.get('of', '—')}</span>"
                f"</div>")
        return "".join(out)

    return (rows(res, BEAR, "▲") or "") + (rows(sup, BULL, "▼") or "")


# ══════════════════════════════════════════════════════════════════════
#  the section
# ══════════════════════════════════════════════════════════════════════

def liquidity_html(ctx: Any = None, profile: Any = None) -> str:
    """The whole section, or `""` when Stage 74 has nothing to say.

    Takes the `LiquidityContext` — so what is drawn is exactly what a consuming
    stage would read, not a second computation of it — plus the raw profile,
    which the heatmap needs per-bin and the context deliberately does not carry
    (thirty bins of rows are a chart, not a field).
    """
    if ctx is None:
        return ""
    try:
        get = ctx.value
        levels = {"support": ctx.value("levels.support"),
                  "resistance": ctx.value("levels.resistance")}
    except Exception:
        return ""

    poc = get("index.poc")
    if poc == UNKNOWN and not _seq(_d(profile).get("rows")):
        return ""

    dominance = str(get("index.dominance") or UNKNOWN)
    shift = str(get("index.shift") or UNKNOWN)
    trend = str(get("index.poc_trend") or UNKNOWN)
    div = str(get("index.divergence") or UNKNOWN)
    imb = _num(get("index.imbalance"))
    net = _num(get("index.net_sentiment"))

    head = (
        f"<div style='display:flex;gap:10px;align-items:baseline;flex-wrap:wrap'>"
        f"<span style='color:{INK};font-weight:800;font-size:12.5px'>"
        f"POC {_px(poc)}</span>"
        f"<span style='color:{_POC_COL.get(trend, FAINT)};font-size:11px'>"
        f"{_txt(trend)}</span>"
        f"<span style='color:{_DOMINANCE_COL.get(dominance, FAINT)};"
        f"font-weight:800;font-size:12px'>{_txt(dominance)}</span>"
        f"<span style='color:{_SHIFT_COL.get(shift, FAINT)};font-size:11px'>"
        f"{_txt(shift)}</span>"
        + (f"<span style='color:{_DIV_COL.get(div, FAINT)};font-weight:800;"
           f"font-size:11px'>⚠ {div}</span>" if div in (DIV_BULL, DIV_BEAR)
           else "")
        + "</div>")

    cells = "".join([
        _cell("Value area", f"{_px(get('index.value_area_low'))}–"
                            f"{_px(get('index.value_area_high'))}"),
        _cell("Imbalance", "—" if imb is None else f"{imb:+.0f}%",
              _DOMINANCE_COL.get(dominance, MUTED)),
        _cell("Net sentiment", "—" if net is None else f"{net:+.0f}",
              _DOMINANCE_COL.get(dominance, MUTED)),
        _cell("Sentiment shift", _txt(get("index.sentiment_shift"))),
        _cell("POC velocity", _px(get("index.poc_velocity"))),
        # Stability is the reading that says whether the POC is a level at all.
        # A point of control that moves every bar is nobody's line in the sand.
        _cell("POC stability",
              (lambda s: "—" if s is None else f"{s:.0f}%")(
                  _num(get("index.poc_stability")))),
        _cell("Prev POC", _px(get("index.poc_previous"))),
        # The regime says whether today's POC movement is a lot FOR THIS
        # INSTRUMENT — the reading a fixed threshold could never give.
        _cell("POC regime", _txt(get("index.poc_regime"))),
        _cell("Clusters", _txt(get("levels.clusters"))),
        # The tolerance is volatility-adaptive, so it belongs on screen: two
        # cycles' clusters are only comparable if the band did not move.
        _cell("Cluster band",
              (lambda t: "—" if t is None else f"{t:.3f}%")(
                  _num(get("levels.tolerance_pct")))),
    ])

    rows = _seq(_d(profile).get("rows"))
    maps = ""
    if rows:
        maps = (
            f"<div style='display:flex;gap:12px;flex-wrap:wrap;margin-top:8px'>"
            f"<div style='flex:1;min-width:230px'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:2px'>"
            f"Liquidity — how much traded here</div>"
            f"{heatmap_html(rows, 'liquidity', poc)}</div>"
            f"<div style='flex:1;min-width:230px'>"
            f"<div style='font-size:8.5px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:2px'>"
            f"Sentiment — who traded here</div>"
            f"{heatmap_html(rows, 'sentiment', poc)}</div>"
            f"</div>")

    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"

        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>💧 Liquidity Intelligence "
        f"<span style='color:{MICRO};letter-spacing:0'>· Stage 74 · "
        f"advisory</span></div>"

        f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>"
        f"Where liquidity sits, who owns it, and where it moved since last "
        f"cycle — an interpretation of profiles Stages 71.7/71.8 already "
        f"publish, never a second measurement of them</div>"

        f"<div style='margin-top:7px'>{head}</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:12px;margin-top:6px;"
        f"padding-top:5px;border-top:1px solid #1a2330'>{cells}</div>"
        f"<div style='margin-top:7px;padding-top:5px;"
        f"border-top:1px solid #1a2330'>{_levels_html(levels)}</div>"
        + maps +
        "</div>")


def collection_html(status: Optional[Dict[str, Any]] = None) -> str:
    """Is telemetry actually being written?

    This exists because the failure it catches is invisible. The write is
    per-minute and best-effort, so a missing `sql/036` migration means it fails
    silently every cycle and a week of "collecting" produces **zero rows** —
    discoverable only by going to look, a week later, having lost the week.

    Renders nothing once collection is healthy and has rows. The point is to be
    loud about the broken case and absent otherwise.
    """
    s = _d(status)
    if not s:
        return (f"<div style='background:#0d1117;border:1px solid #3a2a1a;"
                f"border-radius:10px;padding:8px 12px;margin-bottom:8px;"
                f"font-size:10.5px;color:{WARN}'>"
                f"⏸ <b>Stage 74 telemetry has not written yet.</b> "
                f"If this persists past the first minute of a session, apply "
                f"<code>sql/036_liquidity_telemetry.sql</code>.</div>")

    if s.get("ok"):
        wrote = int(_num(s.get("wrote")) or 0)
        return ("" if wrote > 3 else
                f"<div style='background:#0d1117;border:1px solid #1e2836;"
                f"border-radius:10px;padding:8px 12px;margin-bottom:8px;"
                f"font-size:10.5px;color:{BULL}'>"
                f"✅ <b>Collecting.</b> {wrote} sample"
                f"{'' if wrote == 1 else 's'} written this session — one a "
                f"minute. The calibration verdict appears once there is enough "
                f"to judge.</div>")

    error = str(s.get("error") or "")
    missing = ("does not exist" in error or "relation" in error.lower()
               or "42P01" in error)
    return (
        f"<div style='background:#0d1117;border:1px solid #4a1f1f;"
        f"border-radius:10px;padding:9px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;font-weight:800;color:{ALERT}'>"
        f"⛔ Stage 74 telemetry is NOT being collected</div>"
        + (f"<div style='font-size:10.5px;color:{MUTED};margin-top:3px'>"
           f"The <code>liquidity_telemetry</code> table does not exist. Apply "
           f"<code>sql/036_liquidity_telemetry.sql</code> — until then every "
           f"sample is discarded and the calibration week never starts.</div>"
           if missing else
           f"<div style='font-size:10.5px;color:{MUTED};margin-top:3px'>"
           f"Writes are failing, so no calibration evidence is accumulating."
           f"</div>")
        + f"<div style='font-size:9px;color:{MICRO};margin-top:3px'>"
        f"{error[:180]}</div></div>")


def render_collection(st, status: Optional[Dict[str, Any]] = None) -> None:
    """Draw the collection status, or nothing when it is healthy."""
    try:
        html = collection_html(status)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception:
        pass


def calibration_html(summary: Optional[Dict[str, Any]] = None) -> str:
    """The telemetry verdict — is the confidence curve discriminating?

    Drawn separately from the live panel because it answers a different
    question. The live panel says what liquidity is doing right now; this says
    whether the numbers above can be trusted yet.

    It renders the distribution as bars because that is the whole point: a
    verdict word is an opinion, and the shape underneath it is the evidence.
    """
    s = _d(summary)
    if not s or not s.get("samples"):
        return ""

    verdict = str(s.get("verdict") or "INSUFFICIENT")
    colour = {"HEALTHY": BULL, "TOO_FLAT": WARN, "TOO_GENEROUS": ALERT,
              "TOO_HARSH": ALERT}.get(verdict, FAINT)

    conf = _d(s.get("confidence"))
    shares = _d(conf.get("shares"))
    counts = _d(conf.get("counts"))

    bars = []
    for label in ("0-20", "20-40", "40-60", "60-80", "80-100"):
        share = _num(shares.get(label)) or 0.0
        bars.append(
            f"<div style='display:flex;align-items:center;gap:6px;"
            f"font-size:9.5px;padding:0.5px 0'>"
            f"<span style='width:44px;color:{MICRO};text-align:right'>"
            f"{label}</span>"
            f"<span style='flex:0 0 {max(0.5, share * 100):.1f}%;height:9px;"
            f"background:{ramp(share * 2.5)};border-radius:2px'></span>"
            f"<span style='color:{MUTED};font-size:9px'>{share:.0%} "
            f"<span style='color:{MICRO}'>({int(_num(counts.get(label)) or 0):,})"
            f"</span></span></div>")

    eng = _d(s.get("engines"))
    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>🎚 Stage 74 calibration "
        f"<span style='color:{MICRO};letter-spacing:0'>· telemetry · "
        f"advisory</span></div>"
        f"<div style='font-size:10px;color:{MICRO};margin-top:3px'>"
        f"{int(_num(s.get('clusters')) or 0):,} clusters over "
        f"{int(_num(s.get('days')) or 0)} sessions · mean "
        f"{_txt(eng.get('mean'))} engines per cluster</div>"
        f"<div style='margin-top:7px;font-weight:800;font-size:12.5px;"
        f"color:{colour}'>{verdict.replace('_', ' ')}</div>"
        f"<div style='font-size:10px;color:{MUTED};margin-top:2px'>"
        f"{_txt(s.get('advice'))}</div>"
        f"<div style='margin-top:7px;padding-top:5px;"
        f"border-top:1px solid #1a2330'>{''.join(bars)}</div>"
        f"<div style='font-size:9px;color:{MICRO};margin-top:4px'>"
        f"{_txt(s.get('why'))}</div>"
        "</div>")


def render_calibration(st, summary: Optional[Dict[str, Any]] = None) -> None:
    """Draw the calibration verdict, or say nothing."""
    try:
        html = calibration_html(summary)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Calibration telemetry unavailable: {err}")


def render_liquidity(st, ctx: Any = None, profile: Any = None) -> None:
    """Draw it, or say nothing. Advisory — it may never take the tab down."""
    try:
        html = liquidity_html(ctx, profile)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Liquidity Intelligence unavailable: {err}")


# ══════════════════════════════════════════════════════════════════════
#  the same bars, per option leg
# ══════════════════════════════════════════════════════════════════════
#
# A CALL premium and a PUT premium each trade their own book. Where volume
# piled up on the CALL is not derivable from where it piled up on NIFTY, and
# projecting the index profile onto a premium panel would mark a price that
# series can never trade — audit 71.8 settled that, and `_panel_profile`
# already builds a native profile per leg for the chart's band overlay. These
# are the same bins, read as bars instead of bands, so a level can be *read
# off* rather than eyeballed through a candle.
#
# ⚠️ Bars only — NOT a per-leg Liquidity Intelligence context.
#
# The full Stage 74 context carries clustered levels, dealer levels (gamma
# flip, max pain) and liquidity pools. Every one of those is an INDEX fact
# with no per-leg equivalent: there is no gamma flip for a single option's
# premium. Rendering a leg panel that looked like the index one would imply
# six reads where only one exists, so this draws the one thing a leg genuinely
# owns — its own volume-and-sentiment distribution — and says so in the
# header.

def leg_heatmap_html(side: str, profile: Any = None, label: str = "",
                     mode: str = "both") -> str:
    """One leg's profile as bars. `""` when that leg published nothing.

    ⚠️ `mode` defaults to **both**, and it has to.

    The first cut rendered `liquidity` only while the header said "volume &
    sentiment profile" — the panel promised a read it did not draw, which is
    the same defect class as a delivery banner that reports a send that never
    happened. The index panel has always drawn both, for the reason its own
    docstring gives: rendering one forces a trader to choose between "where is
    the volume" and "who owns it", and the interesting bins are exactly the
    ones where those two disagree.

    `'liquidity'` or `'sentiment'` still render a single column, so a caller
    that wants one can ask; nothing defaults to a partial view.
    """
    prof = _d(profile)
    rows = _seq(prof.get("rows"))
    if not rows:
        return ""

    tone = BULL if str(side).upper() == "CALL" else BEAR
    emoji = "🟢" if str(side).upper() == "CALL" else "🔴"
    shape = _d(prof.get("shape"))
    # Stage 71.86's read, when it ran. Absent is absent — no placeholder.
    shape_bits = []
    if shape.get("shape") and shape.get("shape") != UNKNOWN:
        shape_bits.append(str(shape["shape"]))
    conf = _num(shape.get("confidence"))
    if conf is not None:
        shape_bits.append(f"{conf:.0f}%")
    shape_txt = " · ".join(shape_bits)

    poc = prof.get("poc_price")
    wanted = (("liquidity", "sentiment") if str(mode) == "both"
              else (str(mode),))
    cols = []
    for m in wanted:
        bars = heatmap_html(rows, mode=m, poc=poc, fmt=_premium_px)
        if not bars:
            continue
        cols.append(
            f"<div style='flex:1;min-width:0'>"
            f"<div style='font-size:8px;letter-spacing:.08em;color:{MICRO};"
            f"text-transform:uppercase;margin-bottom:2px'>"
            + ("Liquidity — how much" if m == "liquidity"
               else "Sentiment — who") +
            f"</div>{bars}</div>")
    if not cols:
        return ""
    bars = (f"<div style='display:flex;gap:8px;flex-wrap:wrap'>"
            f"{''.join(cols)}</div>")

    head = (f"<div style='display:flex;gap:6px;align-items:baseline;"
            f"flex-wrap:wrap;margin-bottom:3px'>"
            f"<span style='color:{tone};font-weight:800;font-size:11px'>"
            f"{emoji} {str(side).upper()}</span>"
            + (f"<span style='color:{MICRO};font-size:9.5px'>{label}</span>"
               if label else "")
            + (f"<span style='color:{MICRO};font-size:9px;margin-left:auto'>"
               f"{shape_txt}</span>" if shape_txt else "")
            + "</div>")
    foot = ""
    if _num(poc) is not None:
        foot = (f"<div style='color:{MICRO};font-size:9px;margin-top:3px'>"
                f"POC {_premium_px(poc)}</div>")
    return (f"<div style='flex:1 1 340px;min-width:0;background:#0b0f16;"
            f"border:1px solid #1e2836;border-radius:8px;padding:8px 9px'>"
            f"{head}{bars}{foot}</div>")


def leg_heatmaps_html(call_profile: Any = None, put_profile: Any = None,
                      call_label: str = "", put_label: str = "",
                      mode: str = "both") -> str:
    """Both legs side by side, or `""` when neither reported."""
    cards = "".join(x for x in (
        leg_heatmap_html("CALL", call_profile, call_label, mode),
        leg_heatmap_html("PUT", put_profile, put_label, mode)) if x)
    if not cards:
        return ""
    return (
        f"<div style='background:#0d1117;border:1px solid #1e2836;"
        f"border-radius:10px;padding:10px 12px;margin-bottom:8px'>"
        f"<div style='font-size:11px;letter-spacing:.10em;color:{INK};"
        f"text-transform:uppercase'>🪣 Premium liquidity "
        f"<span style='color:{MICRO};letter-spacing:0'>· each leg's own "
        f"volume &amp; sentiment profile</span></div>"
        f"<div style='font-size:9.5px;color:{MICRO};margin-top:2px'>"
        f"Bars only. Clustered levels, dealer levels and liquidity pools are "
        f"index facts with no per-leg equivalent — there is no gamma flip for "
        f"one option's premium.</div>"
        f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:7px'>"
        f"{cards}</div></div>")


def render_leg_heatmaps(st, profiles: Any = None,
                        mode: str = "both") -> None:
    """Draw the two leg profiles. Advisory — it may never take the tab down.

    `profiles` is what `_terminal_chart` published: the same objects it just
    drew as bands, so the bars and the chart cannot disagree.
    """
    try:
        p = _d(profiles)
        html = leg_heatmaps_html(p.get("CALL"), p.get("PUT"),
                                 call_label=str(p.get("call_label") or ""),
                                 put_label=str(p.get("put_label") or ""),
                                 mode=mode)
        if html:
            st.markdown(html, unsafe_allow_html=True)
    except Exception as err:
        st.caption(f"Premium liquidity unavailable: {err}")
