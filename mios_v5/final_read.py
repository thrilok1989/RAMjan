"""MIOS V5 — Stage 41 final-read assembler.

`build_final_read(state)` collapses the whole pipeline into one page of
decision-support data — **no BUY/SELL**, only bias + confidence + evidence +
risks + opportunities + levels + invalidation. Pure (no Streamlit) so it can
be unit-tested and reused by the dashboard, the AI briefing, and the
briefing-channel messages.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .core import MarketState, Status


def _res(state: MarketState, name: str):
    return state.get(name)


def _data(state: MarketState, name: str, key: str, default=None):
    r = state.get(name)
    if r is None:
        return default
    return (r.data or {}).get(key, default)


def build_final_read(state: MarketState) -> Dict[str, Any]:
    """Assemble the one-page institutional read from the pipeline results."""
    conflict = _res(state, "stage27_conflict")
    reaction = _res(state, "stage35_reaction_zone")
    context = _res(state, "stage04_context")
    regime = _res(state, "stage05_regime")
    dealer = _res(state, "stage11_dealer")
    intent = _res(state, "stage25_intent")
    orderflow = _res(state, "stage14_orderflow")
    options = _res(state, "stage12_options")
    tc = _res(state, "stage06_timecycle")
    evo = _res(state, "stage29_evolution")
    health = _res(state, "stage00_health")
    memory = _res(state, "stage03_memory")
    liquidity = _res(state, "stage17_liquidity")
    vix = _res(state, "stage22_vix")
    flows = _res(state, "stage23_flows")
    patterns = _res(state, "stage26_patterns")
    sector = _res(state, "stage18_sector")
    preparation = _res(state, "stage24_preparation")
    event = _res(state, "stage28_event_detection")
    flow_shift = _res(state, "stage44_flow_shift")
    evidence_fam = _res(state, "stage53_evidence")
    acceptance = _res(state, "stage42_acceptance")
    htf = _res(state, "stage45_htf_vpfr")
    validity = _res(state, "stage51_validity")
    transition = _res(state, "stage47_transition")
    ltp = _res(state, "stage50_ltp_behaviour")
    energy_e = _res(state, "stage37_energy")
    mstate = _res(state, "stage48_market_state")
    smem = _res(state, "stage54_memory")
    absorb = _res(state, "stage43_absorption")
    dec2 = _res(state, "stage52_decision")
    day_type = _res(state, "stage68_day_type")
    session = _res(state, "stage69_session")
    calendar = _res(state, "stage30_calendar")
    explain = _res(state, "stage34_explain")
    impact = _res(state, "stage33_event_impact")

    # ── preferred bias + confidence (conflict engine is the arbiter) ──
    if conflict is not None and conflict.ok:
        preferred_bias = conflict.bias.value
        confidence = round(conflict.confidence)
        conflict_severity = (conflict.data or {}).get("severity", "—")
    elif regime is not None and regime.ok:
        preferred_bias = regime.bias.value
        confidence = round(regime.confidence)
        conflict_severity = "—"
    else:
        preferred_bias, confidence, conflict_severity = "NEUTRAL", 0, "—"

    # session-conviction temper: scale confidence by the session phase weight,
    # then by system health (Stage-0 rule: errors reduce confidence) — a
    # degraded pipeline must not report full conviction. health 100 → ×1.0,
    # health 50 → ×0.8, health 0 → ×0.6; unknown health → no adjustment.
    conv = (tc.data.get("conviction") if tc and tc.data else 100) or 100
    _hs = (health.data or {}).get("health_score") if health else None
    _health_factor = 1.0 if _hs is None else (0.6 + 0.4 * float(_hs) / 100.0)
    confidence_tempered = round(confidence * (0.55 + 0.45 * conv / 100)
                                * _health_factor)

    # ── reaction zone (battle) ────────────────────────────────────────
    rz = (reaction.data if reaction and reaction.ok else {}) or {}

    # ── aggregate risks / opportunities / evidence across engines ─────
    risks: List[str] = []
    opportunities: List[str] = []
    evidence: List[str] = []
    for r in state.results.values():
        if r.status in (Status.OK, Status.DEGRADED):
            for x in r.risks:
                if x and x not in risks:
                    risks.append(x)
            for x in r.opportunities:
                if x and x not in opportunities:
                    opportunities.append(x)
    # headline evidence from the highest-signal engines
    for name in ("stage35_reaction_zone", "stage27_conflict", "stage11_dealer",
                 "stage25_intent", "stage14_orderflow"):
        r = state.get(name)
        if r and r.ok and r.evidence:
            evidence.append(r.evidence[0])

    changes = (evo.data.get("changes") if evo and evo.data else []) or []

    return {
        "preferred_bias": preferred_bias,
        "confidence": confidence,
        "confidence_tempered": confidence_tempered,
        "conflict_severity": conflict_severity,
        "regime": (regime.data.get("regime") if regime and regime.data else None),
        # market context — what KIND of day (expiry / gap / pin / trend)
        "day_type": (context.data.get("day_type")
                     if context is not None and context.ok and context.data else None),
        "is_expiry": (bool(context.data.get("is_expiry"))
                      if context is not None and context.ok and context.data else False),
        "dte": (context.data.get("dte")
                if context is not None and context.ok and context.data else None),
        "energy": (context.data.get("energy")
                   if context is not None and context.ok and context.data else None),
        "breakout_risk": (context.data.get("breakout_risk")
                          if context is not None and context.ok and context.data else None),
        "session_phase": (tc.data.get("phase") if tc and tc.data else None),
        "session_conviction": conv,
        # institutional preparation — is the market coiling / positioning ahead of
        # something (event-agnostic, non-directional, cause unknown)?
        "preparation": (preparation.data
                        if preparation is not None and preparation.ok
                        and (preparation.data or {}).get("level") not in (None, "NORMAL")
                        else None),
        # surprise-event reaction — a shock is hitting the tape right now
        # (non-directional detector; reaction direction reported in the data)
        "event": (event.data
                  if event is not None and event.ok
                  and (event.data or {}).get("event_detected") else None),
        # 🧠 Stage 52 — the final decision (proof-gated, never predictive)
        "decision_v2": ((dec2.data or {}) if dec2 is not None and dec2.ok else None),
        # 🏛 Stage 43 — the institutional footprint behind the flow
        "absorption": ((absorb.data or {}) if absorb is not None and absorb.ok
                       else None),
        # 🧠 Stage 54 — market memory: how long, and how committed
        "memory": ((smem.data or {}) if smem is not None and smem.ok else None),
        "memory_read": ((smem.data or {}).get("validity_payload")
                        if smem is not None and smem.ok else None),
        # 🎭 Stage 48 — the single market personality + what comes next
        "market_state": ((mstate.data or {}) if mstate is not None and mstate.ok
                         else None),
        # ⚡ Stage 37 — market energy, promoted to a first-class read
        "energy_read": ((energy_e.data or {})
                        if energy_e is not None and energy_e.ok else None),
        # 📖 Stage 50 — what price is TRYING to do, right now
        "ltp_behaviour": ((ltp.data or {}) if ltp is not None and ltp.ok else None),
        # 🔄 Stage 47 — is the bias strengthening / weakening / reversing?
        # `bias_transition` is the lower-case string Stage 51's filter matches on.
        "bias_transition": (str((transition.data or {}).get("state") or "").lower()
                            if transition is not None and transition.ok else None),
        "transition": ((transition.data or {})
                       if transition is not None and transition.ok else None),
        # 🚦 Stage 51 — the gatekeeper's verdict on the proposed side
        "validity": ((validity.data or {}).get("active")
                     if validity is not None and validity.ok else None),
        "validity_both": ({"CALL": (validity.data or {}).get("CALL"),
                           "PUT": (validity.data or {}).get("PUT")}
                          if validity is not None and validity.ok else None),
        # 🏛 Stage 45 — the institutional big picture (six timeframes)
        "htf": ((htf.data or {}) if htf is not None and htf.ok else None),
        "htf_alignment": ((htf.data or {}).get("alignment")
                          if htf is not None and htf.ok else None),
        # ⭐ Stage 42 — the reaction at the level (acceptance / rejection / trap).
        # This is the TIMING read: it says when the battle at a level resolved.
        "reaction": ((acceptance.data or {}).get("active")
                     if acceptance is not None and acceptance.ok else None),
        "reaction_actionable": (bool((acceptance.data or {}).get("actionable"))
                                if acceptance is not None and acceptance.ok else False),
        # 🧠 Stage 53 — evidence families (de-duplicated). v0 runs ALONGSIDE the
        # Stage-27 tally so the two dominant biases can be compared over weeks;
        # `families_agree` is the comparison the promotion decision rests on.
        # 🗓 Stage 68 — the session's character (Trend / Range / Choppy /
        # Expiry Pin / …). Deliberately NOT keyed `day_type`: Stage 4 already
        # owns that key for its expiry/gap frame, and a silent collision here
        # would have shadowed it for every existing reader.
        "day_classification": ((day_type.data or {}) if day_type is not None
                               and day_type.ok else None),
        # 🕘 Stage 69 — which session, what it is doing, and the contextual
        # modifiers it publishes (published, not applied — see SESSION_AWARE).
        "session_intel": ((session.data or {}) if session is not None
                          and session.ok else None),
        "families": ((evidence_fam.data or {}).get("families")
                     if evidence_fam is not None and evidence_fam.ok else None),
        "families_read": ({"dominant": (evidence_fam.data or {}).get("dominant"),
                           "agreement_pct": (evidence_fam.data or {}).get("agreement_pct"),
                           "severity": (evidence_fam.data or {}).get("severity")}
                          if evidence_fam is not None and evidence_fam.ok else None),
        "families_agree": (
            bool((evidence_fam.data or {}).get("dominant") == preferred_bias)
            if evidence_fam is not None and evidence_fam.ok else None),
        # ⚠️ sudden institutional flow shift + market stability (Stage 44) —
        # the interrupt: non-directional, freezes entries while the tape reprices
        "flow_shift": (flow_shift.data
                       if flow_shift is not None and flow_shift.ok
                       and (flow_shift.data or {}).get("detected") else None),
        "stability": ((flow_shift.data or {}).get("stability")
                      if flow_shift is not None and flow_shift.ok else None),
        # scheduled calendar catalyst nearby (RBI/Fed/CPI/expiry/earnings)
        "calendar": (calendar.data
                     if calendar is not None and calendar.ok
                     and (calendar.data or {}).get("has_event") else None),
        # explain layer — possible cause(s) of a flagged preparation/shock (only
        # runs after a detector fires; explanation only, never drives the signal)
        "explanation": (explain.data
                        if explain is not None and explain.ok
                        and (explain.data or {}).get("explaining") else None),
        # event impact — did the event actually change market structure?
        # (measured only when there's an event context; non-directional)
        "event_impact": (impact.data
                         if impact is not None and impact.ok
                         and (impact.data or {}).get("measuring") else None),
        # auction value migration — today's session value vs the last ~5
        # sessions' weekly value (structural). Forwarded raw from the app.
        "value_migration": (state.raw.get("value_migration")
                            if isinstance(state.raw.get("value_migration"), dict) else None),
        "health_score": (health.data.get("health_score")
                         if health and health.data else None),
        # price map + battle
        "battle_zone": rz.get("battle_zone"),
        "expected_winner": rz.get("expected_winner"),
        "probabilities": rz.get("probabilities"),
        "strong_support": rz.get("strong_support"),
        "support_strength": rz.get("support_strength"),
        "strong_resistance": rz.get("strong_resistance"),
        "resistance_strength": rz.get("resistance_strength"),
        "next_target": rz.get("next_target"),
        "invalidation": rz.get("invalidation"),
        "prev_day": (memory.data if memory is not None and memory.ok
                     and memory.data else None),
        # narrative material
        "risks": risks[:6],
        "opportunities": opportunities[:6],
        "evidence": evidence[:6],
        "changes": changes[:5],
        # per-section biases for the dashboard cards
        "sections": {
            "dealer": _section(dealer),
            "intent": _section(intent),
            "orderflow": _section(orderflow),
            "options": _section(options),
            "regime": _section(regime),
            "liquidity": _section(liquidity),
            "vix": _section(vix),
            "flows": _section(flows),
            "patterns": _section(patterns),
            "sector": _section(sector),
        },
        # ── the levels dealer hedging actually defends ──
        # Stage 11 computes gamma flip, magnet and repeller every cycle. Until
        # now `sections.dealer` carried only {bias, confidence, status,
        # headline}, so the numbers existed and no chart could draw them —
        # the shape principle 12 forbids. Nothing is computed here.
        "dealer_levels": _dealer_levels(dealer),
        # ⭐ Stage 42 — the PRICE the reaction happened at, not just its verdict.
        # A rejection is only actionable if you can see the level it rejected.
        "reaction_level": ((acceptance.data or {}).get("active") or {}).get("price")
                          if acceptance is not None and acceptance.ok else None,
        # ── every engine's read, keyed by the id the orchestrator uses ──
        # `sections` above is a hand-picked ten for the dashboard cards. Stage
        # 71 needs a UNIFORM map: it owns producers by engine id, and an owner
        # missing from the map is indistinguishable from an owner that
        # abstained — which would silently shrink a horizon's evidence base
        # instead of failing loudly.
        #
        # Nothing is computed here. `bias`, `confidence` and `status` are
        # already on every EngineResult by contract; this only exposes them
        # under `Engine.name` so a consumer can look one up without reaching
        # into MarketState (principle 4 — inputs arrive as parameters).
        "engine_bias": {
            name: {"bias": r.bias.value, "confidence": round(r.confidence),
                   "status": r.status.value,
                   "headline": (r.evidence[0] if r.evidence else "")}
            for name, r in (getattr(state, "results", None) or {}).items()
            if r is not None
        },
    }


def _dealer_levels(dealer) -> Dict[str, Any]:
    """Gamma flip, magnet and repeller, or an empty dict.

    Empty rather than zeros: an unmeasured level drawn at 0 would render a
    horizontal line at the bottom of every chart, which is worse than absent.
    """
    if dealer is None or not dealer.ok:
        return {}
    gx = (dealer.data or {}).get("gex") or {}
    out = {}
    for src, key in (("flip", "gamma_flip"), ("magnet", "dealer_wall"),
                     ("repeller", "dealer_repeller")):
        try:
            v = float(gx.get(src))
        except (TypeError, ValueError):
            continue
        if v == v and v > 0:
            out[key] = v
    return out


def section(fr: Dict[str, Any], name: str) -> Dict[str, Any]:
    """One engine's section from a final read.

    Top-level keys win where they exist (Stage 42/43/45 publish their own rich
    payloads); everything else lives under `sections`. Every reader in V6/V6.5
    goes through here — reading `fr["dealer"]` directly returns None, which
    silently degrades a condition to "unknown" instead of failing loudly.
    """
    node = (fr or {}).get(name)
    if isinstance(node, dict) and node:
        return node
    s = ((fr or {}).get("sections") or {}).get(name)
    return s if isinstance(s, dict) else {}


def _section(r) -> Dict[str, Any]:
    if r is None:
        return {"bias": "NONE", "confidence": 0, "status": "MISSING"}
    return {"bias": r.bias.value, "confidence": round(r.confidence),
            "status": r.status.value,
            "headline": (r.evidence[0] if r.evidence else "")}


def final_read_line(fr: Dict[str, Any]) -> str:
    """One-line plain-text summary for briefing-channel messages."""
    bz = fr.get("battle_zone")
    zone = (f"{bz['type']} ₹{bz['price']:.0f} → {fr.get('expected_winner')}"
            if bz else "mid-range")
    # lead with the day frame when it's distinctive (expiry / gap) so the
    # briefing reader knows the context before the bias
    _dt = fr.get("day_type")
    day = f"[{_dt}] " if _dt and _dt not in ("NORMAL / RANGE", "TREND") else ""
    return (f"MIOS: {day}{fr['preferred_bias']} @ {fr['confidence_tempered']}% "
            f"({fr.get('conflict_severity')} conflict) · {zone} · "
            f"{fr.get('session_phase', '')}")
