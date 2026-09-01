"""MIOS V6 — Stage 53 Evidence Correlation (the brain).

34 engines do not produce 34 independent opinions. When price falls, CVD, delta,
money flow, VOB and volume all turn down — that is **one** observation seen five
ways, not five confirmations. Counting them separately inflates confidence
exactly when the market is most one-sided, which is when overconfidence is most
expensive.

So evidence is grouped into SEVEN families, each collapsing to a single weighted
vote:

    Market Structure · Order Flow · Options · Dealer · Institutions ·
    Liquidity · Macro

Each family reports more than a direction:

    direction   BULL / BEAR / NEUTRAL
    strength    0-100  — how hard this family leans
    confidence  0-100  — how sure its members are
    agreement   0-100  — do its members agree with EACH OTHER
    reliability HIGH / MEDIUM / LOW  — derived from agreement × coverage × freshness
    freshness   LIVE / RECENT / OLD  — how current the underlying data is

`agreement` matters as much as direction: a family whose members contradict each
other (OI bullish, IV bearish) should not speak with one confident voice. That
internal split is signal, so it degrades `reliability` rather than being averaged
away.

⚠️ Honest limit: the seven families are **not** mutually independent either.
Dealer gamma drives order flow; liquidity pools are structure. Grouping cuts the
worst double-counting (5 views of one tape → 1 vote) but does not eliminate
correlation. It is a large improvement, not a proof of independence — and this
docstring exists so nobody later mistakes it for one.

Pure module: plain dicts in, verdict out. No engine imports, no session, so the
families can be unit-tested and re-weighted from logged data.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ── the seven families ───────────────────────────────────────────────────
# engine → weight WITHIN its family. Family authority is set separately
# (_FAMILY_PRIORITY) so a family can never out-rank another merely by owning
# more engines — the bug that let Institutions (10.0) outweigh Dealer (8.0).
FAMILIES: Dict[str, Dict[str, float]] = {
    "structure": {
        "stage02_structure": 2.0,
        "stage05_regime": 2.0,
        "stage35_reaction_zone": 1.5,
        "stage26_patterns": 1.0,
    },
    "orderflow": {
        "stage14_orderflow": 3.0,      # already merges CVD/delta/absorption
        "stage15_microstructure": 1.0,  # DISABLED by design; skipped when absent
    },
    "options": {
        "stage12_options": 3.0,
        "stage22_vix": 1.0,            # IV belongs with options positioning
    },
    "dealer": {
        "stage11_dealer": 3.0,
    },
    "institutions": {
        "stage13_institutional": 2.0,  # was computed but never voted
        "stage25_intent": 2.0,
        "stage23_flows": 1.0,          # FII/DII, EOD
        "stage18_sector": 1.0,         # slow, delayed
    },
    "liquidity": {
        "stage17_liquidity": 3.0,
    },
    "macro": {
        "stage19_global": 1.5,
        "stage20_macro": 1.5,          # was computed but never voted
        "stage21_news": 1.0,
    },
}

#: family → authority. Mirrors the spec ladder; independent of member count.
FAMILY_PRIORITY: Dict[str, float] = {
    "dealer": 8.0,
    "institutions": 7.0,
    "orderflow": 6.0,
    "liquidity": 5.0,
    "structure": 4.0,
    "options": 3.0,
    "macro": 2.0,
}

#: Engines deliberately excluded from the vote, and why.
EXCLUDED: Dict[str, str] = {
    # derived FROM the same OI/gamma/structure that Dealer, Options and
    # Structure already vote on — including it counts that evidence twice
    "stage31_probability": "meta: derived from other families' inputs",
    "stage27_conflict": "meta: consumes this output",
    "stage29_evolution": "non-directional: reports change",
    "stage44_flow_shift": "non-directional: interrupt/veto only",
    # reads every other family to describe the SESSION; voting would count
    # each of them a second time, through it
    "stage68_day_type": "context: describes the day, does not lean",
    # describes WHEN, not which way — a session engine that voted would be
    # casting a ballot on the clock
    "stage69_session": "context: describes the session, does not lean",
}

_LABEL = {
    "structure": "Market Structure", "orderflow": "Order Flow",
    "options": "Options", "dealer": "Dealer", "institutions": "Institutions",
    "liquidity": "Liquidity", "macro": "Macro",
}

#: engines whose data is inherently delayed → freshness cap
_SLOW = {"stage23_flows": "OLD", "stage18_sector": "RECENT",
         "stage21_news": "RECENT", "stage19_global": "RECENT",
         "stage20_macro": "OLD"}

_FRESH_RANK = {"LIVE": 0, "RECENT": 1, "OLD": 2}
_TIER_FRESH = {1: "LIVE", 2: "RECENT", 3: "OLD"}      # EXECUTED / DERIVED / RESTING

_SIGN = {"STRONG_BULL": 2, "BULL": 1, "NEUTRAL": 0, "SIDEWAYS": 0,
         "NONE": 0, "BEAR": -1, "STRONG_BEAR": -2}


def bias_sign(bias: Optional[str]) -> int:
    return _SIGN.get(str(bias or "").upper(), 0)


def _direction(net: float) -> str:
    if net > 0.15:
        return "BULL"
    if net < -0.15:
        return "BEAR"
    return "NEUTRAL"


def collapse_family(name: str,
                    members: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Collapse one family's engine results into a single vote.

    `members`: engine → {bias, confidence, ok, tier}. Absent/failed engines are
    simply not counted — a family speaks only for the evidence it actually has,
    and `coverage` records how much of it reported.
    """
    weights = FAMILIES.get(name, {})
    signed = 0.0          # Σ weight × sign × confidence  (direction + strength)
    abs_w = 0.0           # Σ weight × confidence          (how much evidence)
    bull_w = bear_w = 0.0
    conf_num = conf_den = 0.0
    present: List[str] = []
    freshness = "LIVE"

    for eng, w in weights.items():
        r = (members or {}).get(eng)
        if not r or not r.get("ok", True):
            continue
        present.append(eng)
        conf = float(r.get("confidence") or 0)
        sign = bias_sign(r.get("bias"))
        conf_num += w * conf
        conf_den += w
        # freshness = the STALEST contributing member (a family is only as
        # current as its laggards)
        f = _SLOW.get(eng) or _TIER_FRESH.get(r.get("tier"), "RECENT")
        if _FRESH_RANK[f] > _FRESH_RANK[freshness]:
            freshness = f
        if sign == 0:
            continue
        eff = w * (conf / 100.0 if conf else 0.5)
        signed += eff * (sign / 2.0)
        abs_w += eff
        if sign > 0:
            bull_w += eff
        else:
            bear_w += eff

    if not present:
        return {"family": name, "label": _LABEL.get(name, name),
                "direction": "NEUTRAL", "strength": 0, "confidence": 0,
                "agreement": 0, "reliability": "LOW", "freshness": "OLD",
                "members": [], "coverage": 0, "n": 0, "status": "MISSING"}

    # direction / strength from the net signed lean
    net = signed / abs_w if abs_w else 0.0
    direction = _direction(net)
    strength = round(min(100.0, abs(net) * 100.0))
    confidence = round(conf_den and conf_num / conf_den or 0.0)

    # ── agreement: do the members agree with EACH OTHER? ──
    # This is the read that a naive average destroys — OI bullish + IV bearish
    # must not become "confidently neutral".
    directional = bull_w + bear_w
    if directional <= 0:
        agreement = 50                      # all neutral: no conflict, no signal
    else:
        agreement = round(max(bull_w, bear_w) / directional * 100)

    coverage = round(len(present) / max(1, len(weights)) * 100)

    # ── reliability = agreement × coverage × freshness ──
    if agreement >= 80 and coverage >= 50 and freshness != "OLD":
        reliability = "HIGH"
    elif agreement >= 60 and freshness != "OLD":
        reliability = "MEDIUM"
    elif agreement < 60:
        reliability = "LOW"                 # members fighting → distrust it
    else:
        reliability = "MEDIUM" if coverage >= 50 else "LOW"

    return {"family": name, "label": _LABEL.get(name, name),
            "direction": direction, "strength": strength,
            "confidence": confidence, "agreement": agreement,
            "reliability": reliability, "freshness": freshness,
            "members": present, "coverage": coverage, "n": len(present),
            "status": "OK"}


def correlate(results: Optional[Dict[str, Dict[str, Any]]]) -> Dict[str, Any]:
    """Group every engine result into its family and collapse each to one vote.

    Returns {families, order, dominant, agreement_pct, severity, excluded,
    unmapped} — a drop-in replacement for the 34-engine tally that the Conflict
    Engine can consume.
    """
    fams = {name: collapse_family(name, results) for name in FAMILIES}

    bull_w = bear_w = total_w = 0.0
    for name, f in fams.items():
        if f["status"] != "OK" or f["direction"] == "NEUTRAL":
            continue
        # family authority × its own confidence × a reliability haircut —
        # an internally-split family speaks more quietly
        rel = {"HIGH": 1.0, "MEDIUM": 0.75, "LOW": 0.45}[f["reliability"]]
        eff = (FAMILY_PRIORITY.get(name, 1.0)
               * (f["confidence"] / 100.0 if f["confidence"] else 0.5) * rel)
        total_w += eff
        if f["direction"] == "BULL":
            bull_w += eff
        else:
            bear_w += eff

    net = bull_w - bear_w
    if total_w <= 0:
        dominant, agreement, severity = "NEUTRAL", 0, "LOW"
    else:
        ratio = net / total_w
        dominant = ("STRONG_BULL" if ratio >= 0.6 else "BULL" if ratio > 0.15 else
                    "STRONG_BEAR" if ratio <= -0.6 else "BEAR" if ratio < -0.15
                    else "NEUTRAL")
        opposing = (bear_w if net >= 0 else bull_w) / total_w
        agreement = round((1 - opposing) * 100)
        severity = ("LOW" if opposing < 0.15 else
                    "MEDIUM" if opposing < 0.35 else "HIGH")

    unmapped = sorted(
        e for e in (results or {})
        if e not in EXCLUDED and not any(e in m for m in FAMILIES.values()))

    order = sorted(fams.values(),
                   key=lambda f: -(FAMILY_PRIORITY.get(f["family"], 0)))
    return {"families": fams, "order": order, "dominant": dominant,
            "agreement_pct": agreement, "severity": severity,
            "bull_weight": round(bull_w, 2), "bear_weight": round(bear_w, 2),
            "excluded": dict(EXCLUDED), "unmapped": unmapped}


def family_lines(corr: Optional[Dict[str, Any]]) -> List[str]:
    """The seven-line dashboard read — what a trader can absorb in seconds."""
    out = []
    for f in (corr or {}).get("order", []):
        if f["status"] != "OK":
            continue
        em = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}[f["direction"]]
        flag = "" if f["reliability"] == "HIGH" else (
            " ⚠️" if f["reliability"] == "LOW" else "")
        out.append(f"{f['label']:<18}{em} {f['strength']}%{flag}")
    return out
