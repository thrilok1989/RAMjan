"""MIOS V6 — Stage 70 Session Intelligence Validation & Adaptive Behaviour.

Stage 69 publishes contextual modifiers and applies none of them. This is the
apparatus that decides whether they should ever be applied — by measuring what
actually happened in each session, and what *would* have happened had the
modifiers been live.

**No new engine, no new signal.** Stage 70 is not registered in `ALL_ENGINES`,
exposes no mutator, and cannot touch the Decision Engine, a confidence or a
threshold. Like Stages 55-60 it may only observe, measure, explain, recommend
and validate.

## The counterfactual, and its honest limits

We have no live "with Session Intelligence" arm — `SESSION_AWARE` has never been
True. But every `session_log` row carries the modifiers that *were published* at
that moment, so for each graded trade we can ask: **would the session-adjusted
stack have taken this trade?** That is a real A/B without ever having risked
money on the unproven arm.

Two limits, stated rather than buried:

1. **It is a backtest on the data the modifiers were designed from.** The
   thresholds in Stage 69 were written from reasoning about NSE sessions, then
   evaluated against the sessions that followed. That is suggestive, not
   conclusive, and `in_sample` says so on every result.
2. **It can only remove trades, never add them.** A modifier that says WAIT
   filters an entry MIOS actually took; a modifier that would have *permitted*
   an entry MIOS declined leaves no record, because a trade not taken has no
   outcome. So the measured improvement is a **lower bound on the harm avoided
   and says nothing about opportunity missed** — which is exactly the direction
   a validation should err.

## The session key

Stage 69 owns eight time windows; the request also lists ORB, Reversal, Gap Up,
Gap Down, Event, Expiry and Holiday. Those are not all the same kind of thing —
some are windows, some are day conditions, one is a market closure. Rather than
invent a tenth classifier, the bucket is a **composite**:

    window (Stage 69) × condition (Stage 68 / Stage 28 / gap)

so "Opening Drive · Gap Up" and "Opening Drive · Expiry" are distinguishable
without a new engine deciding anything. `HOLIDAY` is deliberately absent: the
market is closed, no signals exist, and an always-empty bucket is clutter.

Pure module.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from .engine_accuracy import wilson
from .session import BEHAVIOUR_LABEL, CLOSED, WINDOWS

#: graded trades a bucket needs before any of its numbers are trusted
MIN_TRADES = 10

#: graded trades the counterfactual needs before it may recommend promotion
MIN_PROMOTE = 40

#: win-rate improvement below which the counterfactual is called noise
MIN_UPLIFT = 5.0

#: conditions that qualify a window, in precedence order — the first that
#: applies wins, so an expiry gap-up day is filed under EXPIRY
CONDITIONS = ("EVENT", "EXPIRY", "GAP_UP", "GAP_DOWN", "NORMAL")

CONDITION_LABEL = {"EVENT": "Event", "EXPIRY": "Expiry", "GAP_UP": "Gap Up",
                   "GAP_DOWN": "Gap Down", "NORMAL": ""}

#: Stage 69 behaviours that read as their own session character
BEHAVIOUR_ALIAS = {"TRENDING": "Trend", "TREND_BUILDING": "Trend",
                   "TREND_EXHAUSTION": "Reversal", "CHOPPY": "Choppy",
                   "SIDEWAYS": "Balance", "COMPRESSING": "Compression",
                   "EXPANDING": "Expansion", "RANGE_BUILDING": "Range"}

_WINDOW_LABEL = {k: lbl for k, _, _, lbl in WINDOWS}
_WINDOW_LABEL[CLOSED[0]] = CLOSED[1]
_WINDOW_ORDER = {k: i for i, (k, _, _, _) in enumerate(WINDOWS)}

#: stances that would have blocked or downgraded a trade
_BLOCKING = ("WAIT", "NO_TRADE")
_GATING = ("HIGH_CONFIDENCE_ONLY",)


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "").upper()


def _rec_window(rec: Dict[str, Any]) -> Optional[str]:
    """The session window off a recommendation, in either shape.

    In memory the field is `window`. In Postgres it cannot be — WINDOW is a
    reserved word — so the column is `session_window` and rows read back
    carrying that name instead. Both arrive here, so accept both rather than
    letting a round-trip through the database silently unmatch every row in
    `score_recommendations`.
    """
    return rec.get("window") or rec.get("session_window")


def _mean(vals) -> Optional[float]:
    xs = [x for x in (_f(v) for v in vals) if x is not None]
    return round(sum(xs) / len(xs), 2) if xs else None


def _mode(vals) -> Optional[str]:
    c: Dict[str, int] = {}
    for v in vals:
        if v:
            c[str(v)] = c.get(str(v), 0) + 1
    return max(c, key=c.get) if c else None


# ── the bucket key ──────────────────────────────────────────────────────
def session_key(row: Optional[Dict[str, Any]],
                trade: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Composite bucket: Stage 69's window × the day's qualifying condition.

    Neither engine is asked to decide anything new — the window is Stage 69's,
    the condition is read from Stage 68 / Stage 28 / the gap flag already on
    the attribution row.
    """
    r, t = dict(row or {}), dict(trade or {})
    window = _s(r.get("session")) or "UNKNOWN"

    day_type = _s(t.get("day_classification") or t.get("day_type"))
    cond = "NORMAL"
    if "NEWS" in day_type or _s(t.get("event")) in ("TRUE", "1", "YES"):
        cond = "EVENT"
    elif "EXPIRY" in day_type or _s(t.get("is_expiry")) in ("TRUE", "1", "YES"):
        cond = "EXPIRY"
    elif _s(t.get("gap")) == "GAP-UP":
        cond = "GAP_UP"
    elif _s(t.get("gap")) == "GAP-DOWN":
        cond = "GAP_DOWN"

    behaviour = _s(r.get("behaviour"))
    alias = BEHAVIOUR_ALIAS.get(behaviour)
    label = _WINDOW_LABEL.get(window, window.replace("_", " ").title())
    suffix = " · ".join(x for x in (alias, CONDITION_LABEL.get(cond)) if x)

    return {"key": f"{window}|{cond}", "window": window, "condition": cond,
            "behaviour": behaviour,
            "label": f"{label}{' · ' + suffix if suffix else ''}",
            "window_label": label,
            "behaviour_label": BEHAVIOUR_LABEL.get(behaviour, "")}


# ── PART 1 · the performance logger ─────────────────────────────────────
def performance(session_log: Optional[Sequence[Dict[str, Any]]],
                results: Optional[Sequence[Dict[str, Any]]],
                trades: Optional[Sequence[Dict[str, Any]]] = None,
                min_trades: int = MIN_TRADES) -> List[Dict[str, Any]]:
    """Per-session performance, from the graded history.

    A trade is attributed to the session in force **when it was taken** — the
    last logged row on that day at or before the trade. Attributing by the
    day's final session would credit every morning trade to the close.
    """
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in (session_log or []):
        d = str(row.get("trading_day") or "")
        if d:
            by_day.setdefault(d, []).append(row)
    for rows in by_day.values():
        rows.sort(key=lambda r: str(r.get("ts") or ""))

    by_sig = {str(t.get("signal_id")): t for t in (trades or [])}
    buckets: Dict[str, Dict[str, Any]] = {}

    for res in (results or []):
        sid = str(res.get("signal_id"))
        row = _active_row(by_day, res)
        if row is None:
            continue
        trade = by_sig.get(sid) or {}
        k = session_key(row, trade)
        b = buckets.setdefault(k["key"], {**k, "signals": 0, "valid": 0,
                                          "wins": 0, "losses": 0,
                                          "_rr": [], "_hold": [], "_mfe": [],
                                          "_mae": [], "_conf": [], "_pnl": [],
                                          "_quality": [], "_state": []})
        b["signals"] += 1
        graded = res.get("outcome") in ("win", "loss")
        if not graded:
            continue
        b["valid"] += 1
        b["wins" if res["outcome"] == "win" else "losses"] += 1
        b["_rr"].append(trade.get("rr"))
        b["_hold"].append(res.get("holding_secs"))
        b["_mfe"].append(res.get("mfe"))
        b["_mae"].append(res.get("mae"))
        b["_conf"].append(trade.get("confidence"))
        b["_pnl"].append(res.get("pnl_points"))
        b["_quality"].append(trade.get("market_quality"))
        b["_state"].append(trade.get("market_state"))

    out = []
    for b in buckets.values():
        n = b["valid"]
        hold = _mean(b["_hold"])
        row = {k: v for k, v in b.items() if not k.startswith("_")}
        row.update({
            "win_rate": round(100.0 * b["wins"] / n, 1) if n else None,
            "loss_rate": round(100.0 * b["losses"] / n, 1) if n else None,
            "avg_rr": _mean(b["_rr"]),
            "avg_holding_min": round(hold / 60.0, 1) if hold is not None else None,
            "avg_mfe": _mean(b["_mfe"]), "avg_mae": _mean(b["_mae"]),
            "avg_confidence": _mean(b["_conf"]),
            "avg_market_quality": _mode(b["_quality"]),
            "avg_market_state": _mode(b["_state"]),
            "expectancy": _mean(b["_pnl"]),
            "total_pnl": round(sum(x for x in (_f(p) for p in b["_pnl"])
                                   if x is not None), 1),
            "interval": wilson(b["wins"], n),
            "thin": n < min_trades,
        })
        out.append(row)
    # chronological — reading the day in order is what makes "we lose money at
    # midday" visible; sorting by win rate hides the shape of the session
    out.sort(key=lambda r: (_WINDOW_ORDER.get(r["window"], 99), r["condition"]))
    return out


def _active_row(by_day: Dict[str, List[Dict[str, Any]]],
                res: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    day = str(res.get("trading_day") or "")
    when = str(res.get("exit_at") or res.get("created_at") or "")
    active = None
    for row in by_day.get(day) or []:
        if not when or str(row.get("ts") or "") <= when:
            active = row
        else:
            break
    return active


# ── PART 2 · behaviour validation (the counterfactual) ──────────────────
def counterfactual(session_log: Optional[Sequence[Dict[str, Any]]],
                   results: Optional[Sequence[Dict[str, Any]]],
                   trades: Optional[Sequence[Dict[str, Any]]] = None
                   ) -> Dict[str, Any]:
    """What the session-adjusted stack WOULD have done, versus what happened.

    Every logged row carries the modifiers published at that moment. A trade
    taken while the session's `stage52_decision.stance` was WAIT or NO_TRADE
    would not have been taken; one taken under HIGH_CONFIDENCE_ONLY would have
    needed to clear a higher bar.

    **This can only remove trades, never add them.** A modifier that would have
    permitted an entry MIOS declined leaves no outcome to measure. So the
    result is a lower bound on harm avoided and says nothing about opportunity
    missed — the direction a validation should err in.
    """
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in (session_log or []):
        d = str(row.get("trading_day") or "")
        if d:
            by_day.setdefault(d, []).append(row)
    for rows in by_day.values():
        rows.sort(key=lambda r: str(r.get("ts") or ""))

    by_sig = {str(t.get("signal_id")): t for t in (trades or [])}
    kept, blocked, gated = [], [], []

    for res in (results or []):
        if res.get("outcome") not in ("win", "loss"):
            continue
        row = _active_row(by_day, res)
        if row is None:
            continue
        stance = _stance(row)
        trade = by_sig.get(str(res.get("signal_id"))) or {}
        rec = {"result": res, "trade": trade, "stance": stance,
               "session": _s(row.get("session"))}
        if stance in _BLOCKING:
            blocked.append(rec)
        elif stance in _GATING and (_f(trade.get("confidence")) or 0) < 80:
            gated.append(rec)
        else:
            kept.append(rec)

    actual = _arm([{"result": r} for r in (results or [])
                   if r.get("outcome") in ("win", "loss")])
    adjusted = _arm(kept)
    removed = _arm(blocked + gated)

    uplift = (round(adjusted["win_rate"] - actual["win_rate"], 1)
              if (adjusted["win_rate"] is not None
                  and actual["win_rate"] is not None) else None)
    dd = (round(actual["avg_mae"] - adjusted["avg_mae"], 2)
          if (adjusted["avg_mae"] is not None
              and actual["avg_mae"] is not None) else None)
    profit = (round(adjusted["expectancy"] - actual["expectancy"], 2)
              if (adjusted["expectancy"] is not None
                  and actual["expectancy"] is not None) else None)

    enough = actual["n"] >= MIN_PROMOTE
    proven = bool(enough and uplift is not None and uplift >= MIN_UPLIFT
                  and adjusted["n"] >= MIN_TRADES)

    return {
        "without": actual, "with": adjusted, "removed": removed,
        "blocked": len(blocked), "gated": len(gated),
        "improvement_pct": uplift,
        "false_signal_reduction": removed["losses"],
        "winners_lost": removed["wins"],
        "avg_profit_increase": profit,
        "avg_drawdown_reduction": dd,
        "sample": actual["n"], "kept_sample": adjusted["n"],
        "significant": enough,
        "promotable": proven,
        # binding: this is a backtest on the data the modifiers were designed
        # from, and it can only ever remove trades
        "in_sample": True,
        "verdict": _cf_verdict(actual, adjusted, uplift, removed, enough,
                               proven),
        "caveats": [
            "In-sample: the modifiers were written before this history, then "
            "evaluated against it. Suggestive, not conclusive.",
            "Removal-only: a modifier that would have PERMITTED a declined "
            "entry leaves no outcome, so opportunity missed is unmeasured.",
        ],
    }


def _stance(row: Dict[str, Any]) -> str:
    mods = row.get("modifiers")
    if isinstance(mods, str):
        try:
            import json
            mods = json.loads(mods)
        except Exception:
            mods = {}
    dec = ((mods or {}).get("stage52_decision") or {}) if isinstance(mods, dict) else {}
    return _s(dec.get("stance")) or "NORMAL"


def _arm(recs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    res = [r["result"] for r in recs]
    n = len(res)
    wins = sum(1 for r in res if r.get("outcome") == "win")
    return {
        "n": n, "wins": wins, "losses": n - wins,
        "win_rate": round(100.0 * wins / n, 1) if n else None,
        "expectancy": _mean(r.get("pnl_points") for r in res),
        "avg_mae": _mean(r.get("mae") for r in res),
        "avg_mfe": _mean(r.get("mfe") for r in res),
        "total_pnl": round(sum(x for x in (_f(r.get("pnl_points")) for r in res)
                               if x is not None), 1),
        "interval": wilson(wins, n),
    }


def _cf_verdict(actual, adjusted, uplift, removed, enough, proven) -> str:
    if not actual["n"]:
        return "No graded trades yet — nothing to validate."
    if not enough:
        return (f"Only {actual['n']} graded trades — {MIN_PROMOTE} needed "
                f"before the comparison means anything. Reported, not trusted.")
    if uplift is None:
        return "The adjusted arm has no trades left to compare."
    cost = (f" It would have cost {removed['wins']} winner"
            f"{'s' if removed['wins'] != 1 else ''}." if removed["wins"] else "")
    if proven:
        return (f"Session adjustment would have lifted the win rate "
                f"{uplift:+.1f} pts ({actual['win_rate']}% → "
                f"{adjusted['win_rate']}%), removing {removed['losses']} "
                f"losers.{cost} Above the {MIN_UPLIFT}-point floor — worth "
                f"promoting, in sample.")
    return (f"Session adjustment moves the win rate {uplift:+.1f} pts — below "
            f"the {MIN_UPLIFT}-point noise floor.{cost} No change recommended.")


# ── PART 3 · the session profile ────────────────────────────────────────
def profile(perf_row: Optional[Dict[str, Any]],
            session_rows: Optional[Sequence[Dict[str, Any]]] = None
            ) -> Dict[str, Any]:
    """A measured profile for one session bucket.

    Falls back to Stage 69's a-priori style table when history is thin — and
    **labels which it is**. A profile built from six trades presented in the
    same voice as one built from two hundred is how a system talks itself into
    a bad habit.
    """
    from .session import STYLE

    p = dict(perf_row or {})
    window = p.get("window") or "UNKNOWN"
    rows = list(session_rows or [])
    n = int(p.get("valid") or 0)

    vol = _mode([(r.get("measures") or {}).get("volatility") and
                 _band((r.get("measures") or {}).get("volatility"))
                 for r in rows])
    dealer = _mode([_band((r.get("measures") or {}).get("dealer"))
                    for r in rows])
    inst = _mode([_band((r.get("measures") or {}).get("institutional"))
                  for r in rows])

    wr = _f(p.get("win_rate"))
    rr = _f(p.get("avg_rr"))
    measured = n >= MIN_TRADES

    best = avoid = None
    if measured and wr is not None:
        if wr >= 55 and (rr or 0) >= 1.5:
            best, avoid = "Breakout / continuation", "Counter-trend fades"
        elif wr >= 55:
            best, avoid = "Quick scalps", "Holding for extension"
        elif wr <= 40:
            best, avoid = "Stand aside", "Any discretionary entry"
        else:
            best, avoid = "Mean reversion at the extremes", "Breakout chasing"

    apriori_rec, apriori_avoid = STYLE.get(window, ([], []))

    return {
        "key": p.get("key"), "label": p.get("label"), "window": window,
        "source": "measured" if measured else "a-priori",
        "trades": n,
        "best_strategy": best or (apriori_rec[0] if apriori_rec else None),
        "avoid": avoid or (apriori_avoid[0] if apriori_avoid else None),
        "avg_volatility": vol, "dealer_activity": dealer,
        "institution_activity": inst,
        "false_breakouts": _false_breakout_rate(p),
        "historical_win_rate": wr,
        "interval": p.get("interval"),
        "note": ("Measured from this session's own graded history."
                 if measured else
                 f"Only {n} graded trade{'s' if n != 1 else ''} — showing "
                 f"Stage 69's a-priori profile until there is real history."),
    }


def _band(v) -> Optional[str]:
    x = _f(v)
    if x is None:
        return None
    return ("Very High" if x >= 75 else "High" if x >= 50 else
            "Medium" if x >= 25 else "Low")


def _false_breakout_rate(p: Dict[str, Any]) -> Optional[str]:
    """Proxied from the loss rate on this bucket — MIOS does not tag a loss as
    a false breakout, so this is labelled as a proxy rather than dressed up as
    a measurement."""
    lr = _f(p.get("loss_rate"))
    if lr is None or int(p.get("valid") or 0) < MIN_TRADES:
        return None
    return "High" if lr >= 55 else "Medium" if lr >= 40 else "Low"


def profiles(perf: Optional[Sequence[Dict[str, Any]]],
             session_log: Optional[Sequence[Dict[str, Any]]] = None
             ) -> List[Dict[str, Any]]:
    by_window: Dict[str, List[Dict[str, Any]]] = {}
    for r in (session_log or []):
        by_window.setdefault(_s(r.get("session")), []).append(r)
    return [profile(p, by_window.get(p.get("window"))) for p in (perf or [])]


# ── PART 4 · adaptive recommendations ───────────────────────────────────
def recommendations(perf: Optional[Sequence[Dict[str, Any]]],
                    profs: Optional[Sequence[Dict[str, Any]]] = None
                    ) -> List[Dict[str, Any]]:
    """Evidence-driven guidance per session — and an explicit "not enough
    evidence" where that is the truth.

    Every recommendation carries its sample size and its confidence interval.
    A recommendation without those is an opinion wearing a uniform.
    """
    by_key = {p.get("key"): p for p in (profs or [])}
    out = []
    for p in (perf or []):
        pr = by_key.get(p.get("key")) or {}
        n = int(p.get("valid") or 0)
        wr = _f(p.get("win_rate"))
        iv = p.get("interval") or {}
        do, dont = [], []

        if n < MIN_TRADES or wr is None:
            do.append("Not enough graded trades to recommend anything yet")
            dont.append("Reading a pattern into a handful of trades")
        else:
            if wr >= 60:
                do.append(f"Trade this session — {wr}% over {n} trades")
            elif wr <= 40:
                dont.append(f"Trading this session — {wr}% over {n} trades")
                do.append("Stand aside or halve size")
            else:
                do.append(f"Normal size — {wr}% is unremarkable")
            if pr.get("best_strategy"):
                do.append(pr["best_strategy"])
            if pr.get("avoid"):
                dont.append(pr["avoid"])
            rr = _f(p.get("avg_rr"))
            if rr is not None and rr < 1.5:
                dont.append(f"Wide targets — average R:R here is only {rr}")
            mae = _f(p.get("avg_mae"))
            if mae is not None and mae <= -20:
                do.append(f"Wider stops — average heat is {mae:.0f} pts")

        out.append({
            "key": p.get("key"), "label": p.get("label"),
            "window": p.get("window"),
            "do": do[:4], "avoid": dont[:3],
            "sample": n, "win_rate": wr, "interval": iv or None,
            "source": pr.get("source", "a-priori"),
            "significant": n >= MIN_TRADES,
            # binding: nothing here is applied by anything
            "action": "REVIEW — human decision required",
            "auto_applied": False,
        })
    return out


# ── PART 6 · recommendation vs outcome ──────────────────────────────────
def score_recommendations(stored: Optional[Sequence[Dict[str, Any]]],
                          results: Optional[Sequence[Dict[str, Any]]],
                          session_log: Optional[Sequence[Dict[str, Any]]] = None
                          ) -> Dict[str, Any]:
    """Did the recommendation hold up?

    Each stored recommendation carries the win rate it was made at and the
    session it was made for. Comparing that to what the session did *after*
    the recommendation is the only way to tell a genuine session edge from a
    run of luck that has since reverted.
    """
    recs = [dict(r) for r in (stored or []) if r.get("key")]
    if not recs:
        return {"scored": 0, "rows": [],
                "summary": "No stored recommendations yet."}

    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for row in (session_log or []):
        d = str(row.get("trading_day") or "")
        if d:
            by_day.setdefault(d, []).append(row)
    for rows in by_day.values():
        rows.sort(key=lambda r: str(r.get("ts") or ""))

    rows_out = []
    for rec in recs:
        made_at = str(rec.get("created_at") or "")
        after = [r for r in (results or [])
                 if r.get("outcome") in ("win", "loss")
                 and str(r.get("exit_at") or "") > made_at
                 and _s((_active_row(by_day, r) or {}).get("session"))
                 == _s(_rec_window(rec))]
        n = len(after)
        wins = sum(1 for r in after if r["outcome"] == "win")
        after_wr = round(100.0 * wins / n, 1) if n else None
        claimed = _f(rec.get("win_rate"))
        drift = (round(after_wr - claimed, 1)
                 if (after_wr is not None and claimed is not None) else None)
        rows_out.append({
            "key": rec.get("key"), "label": rec.get("label"),
            "window": _rec_window(rec),
            "claimed_win_rate": claimed, "since_win_rate": after_wr,
            "drift": drift, "trades_since": n,
            "interval": wilson(wins, n),
            "held": (drift is not None and drift >= -MIN_UPLIFT),
            "significant": n >= MIN_TRADES,
        })

    tested = [r for r in rows_out if r["significant"]]
    held = [r for r in tested if r["held"]]
    return {
        "scored": len(rows_out), "tested": len(tested), "held": len(held),
        "rows": rows_out,
        "summary": (f"{len(held)}/{len(tested)} recommendations held up on "
                    f"subsequent trades." if tested else
                    f"{len(rows_out)} recommendations stored; none has "
                    f"{MIN_TRADES} subsequent trades yet."),
    }


# ── the whole report ────────────────────────────────────────────────────
def build(session_log: Optional[Sequence[Dict[str, Any]]] = None,
          results: Optional[Sequence[Dict[str, Any]]] = None,
          trades: Optional[Sequence[Dict[str, Any]]] = None,
          stored_recommendations: Optional[Sequence[Dict[str, Any]]] = None
          ) -> Dict[str, Any]:
    """Everything Stage 70 knows, in one payload."""
    perf = performance(session_log, results, trades)
    profs = profiles(perf, session_log)
    return {
        "performance": perf,
        "profiles": profs,
        "counterfactual": counterfactual(session_log, results, trades),
        "recommendations": recommendations(perf, profs),
        "recommendation_scoring": score_recommendations(
            stored_recommendations, results, session_log),
        # binding: Stage 70 logs and validates. It changes nothing.
        "advisory_only": True,
        "applied": False,
    }


def snapshot_rows(report: Optional[Dict[str, Any]],
                  trading_day: Optional[str] = None) -> List[Dict[str, Any]]:
    """Append-only rows for `session_recommendations` — every recommendation
    stored so Part 6 can score it later against what actually followed."""
    r = dict(report or {})
    out = []
    for rec in (r.get("recommendations") or []):
        if not rec.get("significant"):
            continue
        out.append({
            "trading_day": trading_day, "key": rec.get("key"),
            # `session_window`, not `window`: WINDOW is reserved in Postgres.
            "session_window": _rec_window(rec), "label": rec.get("label"),
            "win_rate": rec.get("win_rate"), "sample": rec.get("sample"),
            "recommend": rec.get("do"), "avoid": rec.get("avoid"),
            "source": rec.get("source"), "applied": False,
        })
    return out
