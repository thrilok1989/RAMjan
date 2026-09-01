"""MIOS V6 — Dashboard 6 Replay: the cycle-by-cycle reconstruction.

The `engine_state` table has been written once per pipeline pass since Stage 18
— every engine's bias, confidence and status, plus a `full_state` JSONB, each
row stamped with a timestamp and a spot price. That is a complete recording of
what MIOS believed, minute by minute, for every session it has ever run. Until
now nothing read it back.

This module turns those rows into a **timeline you can step through**: what the
decision was at 10:42, which engines had flipped by 10:47, when the bias started
decaying, and whether the trade that followed did what MIOS expected.

## Two things it deliberately does not do

**It does not re-run the engines.** Replay shows what MIOS *believed at the
time*, not what today's code would conclude from the same candles. Those are
different questions, and conflating them makes every past session look like it
was analysed by the current version — which would hide every improvement and
every regression alike. `engine_version` is carried on each frame precisely so
a version change is visible rather than silent.

**It does not interpolate.** If the pipeline missed a cycle, the timeline has a
gap and says so. Smoothing over it would invent a belief MIOS never held.

## The comparison that makes it worth building

`compare_to_outcome` puts the reconstruction beside what actually happened: the
decision at entry, how the read evolved while the trade was open, and the
result. That is the only way to answer "was the exit early?" with evidence
rather than memory.

Pure module: rows in, frames out. No IO, no pandas, no Streamlit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: playback speeds offered by the UI, in frames per tick
SPEEDS = (1, 2, 5, 10)

#: engines surfaced on the engine timeline, in reading order
TIMELINE_ENGINES = ("regime", "dealer", "options", "institutional",
                    "orderflow", "intent", "probability", "reaction_zone",
                    "structure")

#: a gap longer than this between consecutive rows is reported as missing data
GAP_SECONDS = 180.0


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _s(v) -> str:
    return str(v or "")


def _epoch(ts: Any) -> Optional[float]:
    """Epoch seconds from an ISO string, a datetime, or a number."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if hasattr(ts, "timestamp"):
        try:
            return float(ts.timestamp())
        except Exception:
            return None
    s = str(ts).replace("Z", "+00:00")
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _clock(ts: Any) -> str:
    """HH:MM in IST.

    Was slicing the ISO string, which rendered whatever offset the row happened
    to carry — a `+00:00` row and a `+05:30` row showed different times for the
    same instant, in the same list.
    """
    from .clock import hhmm
    return hhmm(ts)


def build_timeline(rows: Optional[Sequence[Dict[str, Any]]],
                   signals: Optional[Sequence[Dict[str, Any]]] = None,
                   ) -> List[Dict[str, Any]]:
    """`engine_state` rows → ordered frames, oldest first.

    The DB hands them back newest-first; playback runs forward, so they are
    reversed here rather than at three separate call sites.
    """
    rs = [r for r in (rows or []) if r]
    rs.sort(key=lambda r: _epoch(r.get("ts")) or 0.0)

    marks = _markers(signals)
    frames: List[Dict[str, Any]] = []
    prev_e: Optional[float] = None

    for i, r in enumerate(rs):
        e = _epoch(r.get("ts"))
        full = r.get("full_state")
        if isinstance(full, str):
            try:
                import json
                full = json.loads(full)
            except Exception:
                full = {}
        full = full if isinstance(full, dict) else {}

        engines = {}
        for name in TIMELINE_ENGINES:
            b, c = r.get(f"{name}_bias"), r.get(f"{name}_confidence")
            if b is None and c is None:
                continue
            engines[name] = {"bias": _s(b) or None, "confidence": _f(c),
                             "status": _s((full.get(name) or {}).get("status"))
                                       or None}

        gap = (prev_e is not None and e is not None
               and (e - prev_e) > GAP_SECONDS)
        frames.append({
            "index": i, "ts": r.get("ts"), "time": _clock(r.get("ts")),
            "epoch": e, "trading_day": _s(r.get("trading_day")),
            "spot": _f(r.get("spot")),
            "engine_version": _s(r.get("engine_version")) or None,
            "engines": engines,
            "structure_decision": _s(r.get("structure_decision")) or None,
            "structure_score": _f(r.get("structure_score")),
            "conflict_severity": _s(r.get("conflict_severity")) or None,
            "agreement_pct": _f(r.get("conflict_agreement_pct")),
            # the arbitrated read of the moment
            "bias": _s(r.get("regime_bias")) or None,
            "full_state": full,
            "markers": marks.get(_clock(r.get("ts")), []),
            # honesty about missing cycles — never interpolated away
            "gap_before": bool(gap),
            "gap_seconds": round(e - prev_e, 0) if gap and e and prev_e else None,
        })
        prev_e = e if e is not None else prev_e
    return frames


def _markers(signals: Optional[Sequence[Dict[str, Any]]]
             ) -> Dict[str, List[Dict[str, Any]]]:
    """Entry / exit pins, keyed by HH:MM so a frame can carry its own."""
    out: Dict[str, List[Dict[str, Any]]] = {}
    for s in (signals or []):
        for field, kind, emoji in (("entered_at", "entry", "🟢"),
                                   ("exit_at", "exit", "🔴")):
            t = s.get(field)
            if not t:
                continue
            price = _f(s.get("entered_price" if kind == "entry"
                             else "exit_price"))
            out.setdefault(_clock(t), []).append({
                "kind": kind, "emoji": emoji, "signal_id": s.get("signal_id"),
                "side": s.get("side"), "price": price,
                "outcome": s.get("outcome"),
                "label": f"{emoji} {kind.upper()} {s.get('side', '')} "
                         f"{('₹%.0f' % price) if price is not None else ''}"
                         .strip(),
            })
    return out


def decision_timeline(frames: Optional[Sequence[Dict[str, Any]]]
                      ) -> List[Dict[str, Any]]:
    """Only the cycles where the structural decision or bias CHANGED.

    A timeline with one row per cycle is a log; a timeline with one row per
    change is a story, and only the second is readable at a glance.
    """
    out, prev = [], None
    for fdata in (frames or []):
        cur = (fdata.get("structure_decision"), fdata.get("bias"))
        if cur != prev and any(cur):
            out.append({"index": fdata["index"], "time": fdata["time"],
                        "spot": fdata["spot"],
                        "decision": fdata.get("structure_decision"),
                        "bias": fdata.get("bias"),
                        "from_decision": (prev or (None, None))[0],
                        "from_bias": (prev or (None, None))[1],
                        "agreement_pct": fdata.get("agreement_pct"),
                        "markers": fdata.get("markers") or []})
            prev = cur
    return out


def engine_timeline(frames: Optional[Sequence[Dict[str, Any]]],
                    engine: str) -> List[Dict[str, Any]]:
    """One engine's series, with its flips flagged."""
    out, prev = [], None
    for fdata in (frames or []):
        e = (fdata.get("engines") or {}).get(engine)
        if not e:
            continue
        out.append({"index": fdata["index"], "time": fdata["time"],
                    "bias": e.get("bias"), "confidence": e.get("confidence"),
                    "status": e.get("status"),
                    "flipped": bool(prev and e.get("bias") != prev)})
        prev = e.get("bias")
    return out


def flips(frames: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Every engine bias change in the session, newest last — the fastest way
    to find the moment the read turned."""
    out: List[Dict[str, Any]] = []
    prev: Dict[str, Any] = {}
    for fdata in (frames or []):
        for name, e in (fdata.get("engines") or {}).items():
            b = e.get("bias")
            if b and name in prev and prev[name] != b:
                out.append({"index": fdata["index"], "time": fdata["time"],
                            "engine": name, "from": prev[name], "to": b,
                            "confidence": e.get("confidence")})
            if b:
                prev[name] = b
    return out


def frame_at(frames: Optional[Sequence[Dict[str, Any]]],
             index: int) -> Dict[str, Any]:
    fs = list(frames or [])
    if not fs:
        return {}
    return fs[max(0, min(len(fs) - 1, int(index)))]


def seek(frames: Optional[Sequence[Dict[str, Any]]],
         hhmm: Optional[str]) -> int:
    """Index of the first frame at or after HH:MM — the jump-to-time control."""
    fs = list(frames or [])
    if not fs or not hhmm:
        return 0
    for fdata in fs:
        if str(fdata.get("time") or "") >= str(hhmm):
            return int(fdata["index"])
    return fs[-1]["index"]


def narrate(frames: Optional[Sequence[Dict[str, Any]]],
            upto: Optional[int] = None) -> List[Dict[str, Any]]:
    """The narrator's view of a replay — beats derived from the frames
    themselves, so a session recorded before Stage 65 existed still narrates."""
    fs = list(frames or [])
    if upto is not None:
        fs = [x for x in fs if x["index"] <= upto]
    beats: List[Dict[str, Any]] = []
    for d in decision_timeline(fs):
        if d["from_decision"] or d["from_bias"]:
            beats.append({"time": d["time"], "colour": "#a78bfa",
                          "text": f"{d['from_bias'] or '—'} → "
                                  f"{d['bias'] or '—'}"
                                  + (f" · {d['decision']}" if d["decision"]
                                     else ""),
                          "action": True, "index": d["index"]})
        else:
            beats.append({"time": d["time"], "colour": "#8fa1b3",
                          "text": f"Session opens {d['bias'] or '—'}"
                                  + (f" · {d['decision']}" if d["decision"]
                                     else ""),
                          "action": False, "index": d["index"]})
    for fl in flips(fs):
        beats.append({"time": fl["time"], "colour": "#ffcc33",
                      "text": f"{fl['engine']} {fl['from']} → {fl['to']}",
                      "action": False, "index": fl["index"]})
    for fdata in fs:
        for m in (fdata.get("markers") or []):
            beats.append({"time": fdata["time"],
                          "colour": "#00ff88" if m["kind"] == "entry"
                                    else "#ff4444",
                          "text": m["label"], "action": True,
                          "index": fdata["index"]})
    beats.sort(key=lambda b: (b["index"], not b["action"]))
    return beats


def compare_to_outcome(frames: Optional[Sequence[Dict[str, Any]]],
                       signal: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """What MIOS believed at entry, how it evolved, and what actually happened.

    The only honest way to answer "was that exit early?" — memory of a trade is
    reliably kinder to the exit than the record is.
    """
    fs = list(frames or [])
    sig = dict(signal or {})
    if not fs or not sig:
        return {"available": False,
                "reason": "Need both a replay timeline and a closed signal."}

    e_in, e_out = _epoch(sig.get("entered_at")), _epoch(sig.get("exit_at"))
    if e_in is None:
        return {"available": False,
                "reason": f"{sig.get('signal_id', 'Signal')} never entered — "
                          f"nothing to compare."}

    def _nearest(target):
        cands = [x for x in fs if x.get("epoch") is not None]
        return min(cands, key=lambda x: abs(x["epoch"] - target)) \
            if cands else {}

    at_entry = _nearest(e_in)
    at_exit = _nearest(e_out) if e_out is not None else fs[-1]
    during = [x for x in fs
              if x.get("epoch") is not None and e_in <= x["epoch"]
              <= (e_out if e_out is not None else float("inf"))]

    changed = flips(during)
    pnl = _f(sig.get("pnl_points"))
    outcome = _s(sig.get("outcome")).lower()

    # did the read hold, or did MIOS change its mind while the trade ran?
    held = at_entry.get("bias") == at_exit.get("bias")
    verdict = (
        "The read held from entry to exit." if held and not changed else
        f"The read held, but {len(changed)} engine flips occurred during the "
        f"trade." if held else
        f"MIOS changed its mind mid-trade: {at_entry.get('bias')} → "
        f"{at_exit.get('bias')}.")

    return {
        "available": True,
        "signal_id": sig.get("signal_id"), "side": sig.get("side"),
        "outcome": outcome or None, "pnl_points": pnl,
        "entry_frame": at_entry, "exit_frame": at_exit,
        "entry_index": at_entry.get("index"), "exit_index": at_exit.get("index"),
        "cycles_in_trade": len(during),
        "bias_at_entry": at_entry.get("bias"),
        "bias_at_exit": at_exit.get("bias"),
        "agreement_at_entry": at_entry.get("agreement_pct"),
        "agreement_at_exit": at_exit.get("agreement_pct"),
        "spot_at_entry": at_entry.get("spot"),
        "spot_at_exit": at_exit.get("spot"),
        "flips_during": changed,
        "read_held": held,
        "verdict": verdict,
        "version_changed": (at_entry.get("engine_version")
                            != at_exit.get("engine_version")),
    }


def summary(frames: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, Any]:
    fs = list(frames or [])
    if not fs:
        return {"frames": 0, "note": "No engine-state history for this day."}
    versions = sorted({x.get("engine_version") for x in fs
                       if x.get("engine_version")})
    gaps = [x for x in fs if x.get("gap_before")]
    return {
        "frames": len(fs),
        "day": fs[0].get("trading_day"),
        "from": fs[0].get("time"), "to": fs[-1].get("time"),
        "versions": versions,
        "mixed_versions": len(versions) > 1,
        "gaps": len(gaps),
        "decision_changes": len(decision_timeline(fs)),
        "engine_flips": len(flips(fs)),
        "note": ("Reconstruction of what MIOS believed at the time — the "
                 "engines are NOT re-run."),
    }
