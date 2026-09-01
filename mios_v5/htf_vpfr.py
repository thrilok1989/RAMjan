"""MIOS V6 — Stage 45 Higher-Timeframe VPFR (the institutional big picture).

The app knows what *today* is doing. This knows whether today's move is happening
**inside or against the larger structure** — the difference between a rally and a
bounce inside a downtrend.

Six independent institutional references: **1H · 4H · Daily · Weekly · Monthly ·
Yearly**. Each one computes its own value area (VAH/POC/VAL), volume nodes
(HVN/LVN), market structure (HH/HL/LH/LL → trend/range/rotation), value migration
and a bias with confidence. Then they are compared.

It generates no buy/sell. It is the bridge between intraday execution and
higher-timeframe context — the thing that turns Stage 41's confluence stars from
"three intraday windows agreed" into "the Daily VAH and Weekly LVN are here", and
gives Stage 51 something real to validate a signal against.

Pure module: plain lists of floats in, dicts out. No pandas, no session, no I/O —
so every timeframe is testable and the profiles can be cached by the caller and
recomputed only when the relevant bar closes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: the six institutional references, fastest → slowest
TIMEFRAMES = ("1H", "4H", "Daily", "Weekly", "Monthly", "Yearly")

#: how much a slower timeframe outweighs a faster one in the alignment score
TF_WEIGHT = {"1H": 1.0, "4H": 1.5, "Daily": 2.0,
             "Weekly": 2.5, "Monthly": 3.0, "Yearly": 3.5}

_HVN_FRAC = 0.70      # bin ≥ this × peak volume → high-volume node (acceptance)
_LVN_FRAC = 0.25      # bin ≤ this × peak volume → low-volume node (rejection)
_MIGRATE_PCT = 0.10   # POC must move this % to count as migrated


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


# ── 1-2 · VALUE AREA + VOLUME NODES ─────────────────────────────────────
def build_profile(highs: Sequence[float], lows: Sequence[float],
                  volumes: Optional[Sequence[float]] = None,
                  n_rows: int = 24, va_pct: float = 70.0) -> Optional[Dict[str, Any]]:
    """Volume profile for one timeframe: VAH · POC · VAL · HVN · LVN.

    Each bar's volume is spread across the price bins it spans (by overlap), so a
    wide bar doesn't dump all its volume into one bin. Returns None when there
    isn't enough data — an empty profile is never invented.
    """
    hs = [_f(h) for h in (highs or [])]
    ls = [_f(l) for l in (lows or [])]
    n = min(len(hs), len(ls))
    if n < 3:
        return None
    vs = list(volumes or [])
    top = max(h for h in hs[:n] if h is not None)
    bot = min(l for l in ls[:n] if l is not None)
    if top is None or bot is None:
        return None
    if top == bot:
        return {"poc": round(top, 2), "vah": round(top, 2), "val": round(bot, 2),
                "hvn": [round(top, 2)], "lvn": [], "bins": [], "n_bars": n}

    step = (top - bot) / n_rows
    lo_edges = [bot + i * step for i in range(n_rows)]
    hi_edges = [bot + (i + 1) * step for i in range(n_rows)]
    vol = [0.0] * n_rows
    for i in range(n):
        h, l = hs[i], ls[i]
        if h is None or l is None or h < l:
            continue
        v = _f(vs[i]) if i < len(vs) else None
        v = v if v is not None and v > 0 else 1.0
        rng = h - l
        if rng <= 0:                      # doji — put it all in its own bin
            idx = min(n_rows - 1, max(0, int((h - bot) / step)))
            vol[idx] += v
            continue
        for b in range(n_rows):
            overlap = min(h, hi_edges[b]) - max(l, lo_edges[b])
            if overlap > 0:
                vol[b] += v * (overlap / rng)

    peak = max(vol)
    if peak <= 0:
        return None
    poc_i = vol.index(peak)
    poc = (lo_edges[poc_i] + hi_edges[poc_i]) / 2.0

    # expand out from the POC until va_pct of volume is captured
    total, target = sum(vol), sum(vol) * va_pct / 100.0
    cum, lo_i, hi_i = vol[poc_i], poc_i, poc_i
    while cum < target:
        can_lo, can_hi = lo_i - 1 >= 0, hi_i + 1 < n_rows
        if not can_lo and not can_hi:
            break
        v_lo = vol[lo_i - 1] if can_lo else -1.0
        v_hi = vol[hi_i + 1] if can_hi else -1.0
        if v_hi >= v_lo:
            hi_i += 1
            cum += vol[hi_i]
        else:
            lo_i -= 1
            cum += vol[lo_i]

    mids = [(lo_edges[b] + hi_edges[b]) / 2.0 for b in range(n_rows)]
    hvn = [round(mids[b], 2) for b in range(n_rows) if vol[b] >= peak * _HVN_FRAC]
    lvn = [round(mids[b], 2) for b in range(n_rows)
           if 0 < vol[b] <= peak * _LVN_FRAC]
    return {"poc": round(poc, 2), "vah": round(hi_edges[hi_i], 2),
            "val": round(lo_edges[lo_i], 2), "hvn": hvn, "lvn": lvn,
            "bins": [round(v, 2) for v in vol], "n_bars": n,
            "total_volume": round(total, 2)}


# ── 3 · VALUE MIGRATION ─────────────────────────────────────────────────
def value_migration(cur_poc: Optional[float], prev_poc: Optional[float],
                    tol_pct: float = _MIGRATE_PCT) -> Dict[str, Any]:
    """Has value SHIFTED? A market whose POC is climbing is being repriced
    upward — different from price merely being high within an unchanged value."""
    c, p = _f(cur_poc), _f(prev_poc)
    if c is None or p is None or p == 0:
        return {"direction": "unknown", "pct": None, "arrow": "?", "label": "unknown"}
    pct = (c - p) / abs(p) * 100.0
    if pct > tol_pct:
        d, arrow, label = "up", "↑", ("strong shift higher" if pct > tol_pct * 5
                                      else "shifted higher")
    elif pct < -tol_pct:
        d, arrow, label = "down", "↓", ("strong shift lower" if pct < -tol_pct * 5
                                        else "shifted lower")
    else:
        d, arrow, label = "flat", "→", "stable"
    return {"direction": d, "pct": round(pct, 3), "arrow": arrow, "label": label}


# ── 4 · MARKET STRUCTURE ────────────────────────────────────────────────
def market_structure(highs: Sequence[float], lows: Sequence[float],
                     swing: int = 3) -> Dict[str, Any]:
    """HH / HL / LH / LL → trend · range · rotation, from swing pivots."""
    hs = [_f(h) for h in (highs or [])]
    ls = [_f(l) for l in (lows or [])]
    n = min(len(hs), len(ls))
    if n < swing * 2 + 2:
        return {"trend": "unknown", "pattern": [], "hh": 0, "hl": 0,
                "lh": 0, "ll": 0, "label": "insufficient history"}

    ph, pl = [], []
    for i in range(swing, n - swing):
        h = hs[i]
        if h is not None and all(h >= hs[i - j] and h >= hs[i + j]
                                 for j in range(1, swing + 1)
                                 if hs[i - j] is not None and hs[i + j] is not None):
            ph.append(h)
        l = ls[i]
        if l is not None and all(l <= ls[i - j] and l <= ls[i + j]
                                 for j in range(1, swing + 1)
                                 if ls[i - j] is not None and ls[i + j] is not None):
            pl.append(l)

    hh = sum(1 for a, b in zip(ph, ph[1:]) if b > a)
    lh = sum(1 for a, b in zip(ph, ph[1:]) if b < a)
    hl = sum(1 for a, b in zip(pl, pl[1:]) if b > a)
    ll = sum(1 for a, b in zip(pl, pl[1:]) if b < a)

    up, down = hh + hl, lh + ll
    if up == 0 and down == 0:
        # A trend with no pullbacks has no pivots to compare — pivot logic goes
        # blind exactly when the trend is cleanest. Fall back to net displacement
        # measured against the range, so a straight run still reads as a trend.
        first_l = next((x for x in ls[:n] if x is not None), None)
        last_h = next((x for x in reversed(hs[:n]) if x is not None), None)
        first_h = next((x for x in hs[:n] if x is not None), None)
        last_l = next((x for x in reversed(ls[:n]) if x is not None), None)
        if None not in (first_l, last_h, first_h, last_l):
            span = max(hs[:n]) - min(ls[:n])
            if span > 0:
                if (last_l - first_h) / span > 0.5:
                    return {"trend": "uptrend", "pattern": ["displacement↑"],
                            "hh": 0, "hl": 0, "lh": 0, "ll": 0,
                            "label": "sustained advance (no pullbacks)"}
                if (first_l - last_h) / span > 0.5:
                    return {"trend": "downtrend", "pattern": ["displacement↓"],
                            "hh": 0, "hl": 0, "lh": 0, "ll": 0,
                            "label": "sustained decline (no pullbacks)"}
        trend, label = "unknown", "no clear swings"
    elif up >= down * 2 and up >= 2:
        trend, label = "uptrend", "higher highs & higher lows"
    elif down >= up * 2 and down >= 2:
        trend, label = "downtrend", "lower highs & lower lows"
    elif abs(up - down) <= 1:
        trend, label = "range", "balanced swings — rotation"
    else:
        trend, label = "rotation", "mixed structure"
    pattern = []
    if hh:
        pattern.append(f"HH×{hh}")
    if hl:
        pattern.append(f"HL×{hl}")
    if lh:
        pattern.append(f"LH×{lh}")
    if ll:
        pattern.append(f"LL×{ll}")
    return {"trend": trend, "pattern": pattern, "hh": hh, "hl": hl,
            "lh": lh, "ll": ll, "label": label}


# ── 5 · PER-TIMEFRAME INSTITUTIONAL BIAS ────────────────────────────────
def tf_read(name: str, spot: Optional[float], profile: Optional[Dict[str, Any]],
            structure: Optional[Dict[str, Any]] = None,
            migration: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One timeframe's institutional read: where is price vs ITS value area, what
    is ITS structure doing, and is ITS value migrating."""
    s = _f(spot)
    if not profile or s is None:
        return {"tf": name, "bias": "NEUTRAL", "confidence": 0, "location": None,
                "status": "MISSING", "profile": profile, "structure": structure,
                "migration": migration}

    vah, val, poc = _f(profile.get("vah")), _f(profile.get("val")), _f(profile.get("poc"))
    if vah is None or val is None:
        location = None
        score = 0.0
    elif s > vah:
        location, score = "above VAH", 1.0
    elif s < val:
        location, score = "below VAL", -1.0
    elif poc is not None and s > poc:
        location, score = "upper value", 0.35
    elif poc is not None and s < poc:
        location, score = "lower value", -0.35
    else:
        location, score = "at POC", 0.0

    st = (structure or {}).get("trend")
    score += {"uptrend": 0.6, "downtrend": -0.6}.get(st, 0.0)
    mg = (migration or {}).get("direction")
    score += {"up": 0.4, "down": -0.4}.get(mg, 0.0)

    bias = "BULL" if score > 0.35 else "BEAR" if score < -0.35 else "NEUTRAL"
    confidence = int(min(100, abs(score) / 2.0 * 100))
    return {"tf": name, "bias": bias, "confidence": confidence,
            "location": location, "status": "OK", "score": round(score, 2),
            "profile": profile, "structure": structure, "migration": migration}


# ── ALIGNMENT ACROSS THE SIX ────────────────────────────────────────────
def _stars(pct: float) -> str:
    n = max(1, min(5, int(round(pct / 20.0))))
    return "★" * n + "☆" * (5 - n)


def alignment(reads: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Compare all six. Slower timeframes carry more weight — a Yearly
    disagreement matters more than a 1H one."""
    r = {k: v for k, v in (reads or {}).items()
         if v and v.get("status") == "OK"}
    if not r:
        return {"bias": "NEUTRAL", "score": 0, "stars": _stars(0), "n": 0,
                "n_bull": 0, "n_bear": 0, "label": "no higher-timeframe data",
                "disagree": []}

    bull_w = bear_w = total_w = 0.0
    n_bull = n_bear = 0
    for tf, v in r.items():
        w = TF_WEIGHT.get(tf, 1.0) * (v.get("confidence", 0) / 100.0 or 0.4)
        total_w += w
        if v["bias"] == "BULL":
            bull_w += w
            n_bull += 1
        elif v["bias"] == "BEAR":
            bear_w += w
            n_bear += 1

    net = bull_w - bear_w
    bias = ("BULL" if net > 0 and bull_w > bear_w else
            "BEAR" if net < 0 and bear_w > bull_w else "NEUTRAL")
    dominant = max(bull_w, bear_w)
    pct = (dominant / total_w * 100.0) if total_w else 0.0
    agree = n_bull if bias == "BULL" else n_bear if bias == "BEAR" else 0
    disagree = [tf for tf, v in r.items()
                if v["bias"] != bias and v["bias"] != "NEUTRAL"]
    return {"bias": bias, "score": round(pct), "stars": _stars(pct),
            "n": len(r), "n_bull": n_bull, "n_bear": n_bear, "agree": agree,
            "disagree": sorted(disagree, key=lambda t: -TF_WEIGHT.get(t, 0)),
            "label": (f"{agree}/{len(r)} {bias.title()}" if bias != "NEUTRAL"
                      else "no higher-timeframe consensus")}


def migration_summary(reads: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, str]:
    """Short / Medium / Long value migration — 'short-term rally inside a longer
    bearish market' at a glance."""
    def _grp(tfs):
        # ⚠️ `or {}` on the migration node, NOT `.get("migration", {})`.
        #
        # `tf_read` stores `"migration": migration` verbatim and its parameter
        # defaults to `None`, so a timeframe whose migration was never computed
        # holds the key with a `None` VALUE — and `.get(k, default)` returns that
        # `None`, never the default. The chained `.get("direction")` then raised
        # `AttributeError: 'NoneType' object has no attribute 'get'` and took the
        # WHOLE of Stage 45 to ERROR with it, which in turn degrades Stage 51
        # (validity) and Stage 68 (day type) that depend on it.
        #
        # `tf_read` itself gets this right at line ~242 — `(migration or {})` —
        # so this was the one place in the module that trusted the default.
        dirs = [(((reads or {}).get(t) or {}).get("migration") or {}).get("direction")
                for t in tfs]
        dirs = [d for d in dirs if d and d != "unknown"]
        if not dirs:
            return "?"
        up, dn = dirs.count("up"), dirs.count("down")
        return "↑" if up > dn else "↓" if dn > up else "→"
    return {"short": _grp(("1H", "4H")), "medium": _grp(("Daily", "Weekly")),
            "long": _grp(("Monthly", "Yearly"))}


# ── STAGE 51 PRIMITIVE · SIGNAL VALIDITY ────────────────────────────────
def signal_validity(side: Optional[str],
                    reads: Optional[Dict[str, Dict[str, Any]]],
                    min_pct: float = 60.0) -> Dict[str, Any]:
    """Would the higher timeframes support this trade? Weighted agreement with
    the proposed side. This is the primitive Stage 51 will gate entries on."""
    want = "BULL" if str(side).upper() in ("CALL", "BUY", "BULL") else \
           "BEAR" if str(side).upper() in ("PUT", "SELL", "BEAR") else None
    r = {k: v for k, v in (reads or {}).items() if v and v.get("status") == "OK"}
    if want is None or not r:
        return {"pct": 0, "verdict": "UNKNOWN", "approved": False,
                "for": [], "against": []}
    got = total = 0.0
    for_, against = [], []
    for tf, v in r.items():
        w = TF_WEIGHT.get(tf, 1.0)
        total += w
        if v["bias"] == want:
            got += w
            for_.append(tf)
        elif v["bias"] != "NEUTRAL":
            against.append(tf)
        else:
            got += w * 0.5          # neutral neither helps nor blocks
    pct = round(got / total * 100) if total else 0
    return {"pct": pct, "verdict": "APPROVED" if pct >= min_pct else "REJECT",
            "approved": pct >= min_pct,
            "for": sorted(for_, key=lambda t: -TF_WEIGHT.get(t, 0)),
            "against": sorted(against, key=lambda t: -TF_WEIGHT.get(t, 0))}


def htf_levels(reads: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, float]:
    """Every higher-timeframe level as {label: price} — the map Stage 41 scores
    a zone's confluence against ('Daily VAH', 'Weekly LVN', 'Monthly POC')."""
    out: Dict[str, float] = {}
    for tf, v in (reads or {}).items():
        prof = (v or {}).get("profile") or {}
        for key, nm in (("vah", "VAH"), ("poc", "POC"), ("val", "VAL")):
            p = _f(prof.get(key))
            if p:
                out[f"{tf} {nm}"] = p
        for i, p in enumerate((prof.get("hvn") or [])[:2]):
            if _f(p):
                out[f"{tf} HVN{i + 1}"] = float(p)
        for i, p in enumerate((prof.get("lvn") or [])[:2]):
            if _f(p):
                out[f"{tf} LVN{i + 1}"] = float(p)
    return out
