"""Stage 4 — Market Context Engine.

Answers the one question the rest of the pipeline needs framed before it can
be read correctly: **what KIND of day is this?** — expiry vs normal, how many
days to expiry (DTE), gap type, and pin/range vs trend. It is *non-directional*
(like the Time Cycle engine): it sets the frame, it does not vote a bias. Its
value is the `day_type` + expiry/DTE flags + the risk/opportunity notes that
flow into the final read, the narrative, and the Trade Card — so on an expiry
day the whole system explicitly KNOWS it and reads the pin/charm dynamics in
the right light instead of treating it as an ordinary trend day.

Inputs (all already stashed by the host app — nothing is recomputed):
  option_data.expiry / .selected_expiry → is_expiry, days-to-expiry (DTE)
  market_memory.prev_close + raw.day_open → gap type / size
  market_picture.oi_pin                  → pin / magnet context
  market_picture.regime                  → trend vs range fallback
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pytz

from ..core.contract import Bias, Engine, EngineResult, MarketState, Status, Tier
from . import _adapters as A

IST = pytz.timezone("Asia/Kolkata")

# a gap of this % of prior close or more counts as a notable opening gap
_GAP_PCT = 0.40


def _parse_expiry(val) -> Optional[date]:
    """Parse the chain's expiry string to a date. Tolerant of the few
    formats Dhan / the app pass through; returns None if unparseable."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # ISO datetime ("2026-07-24T15:30:00" / "2026-07-24 15:30")
    s10 = s[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s10 if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _energy_meter(short_gamma, long_gamma, gamma_known, at_pin, near_pin,
                  left_pin, gamma_blast, is_expiry):
    """The core distinction: quiet-because-DAMPED (long gamma pin → low energy)
    vs quiet-because-LOADED (short gamma spring → high stored energy). Returns
    (energy, compression, breakout_risk), each 0-100.

      • energy        — total stored + kinetic energy in the setup
      • compression   — how coiled it is (potential energy, price contained)
      • breakout_risk — likelihood the energy releases into a fast move
    """
    in_zone = at_pin or near_pin

    # base energy from the gamma × position matrix
    if short_gamma and in_zone:
        energy, compression, breakout = 88, 85, 82      # coiled spring
    elif short_gamma and left_pin:
        energy, compression, breakout = 82, 25, 90      # gamma unwind (kinetic)
    elif short_gamma:
        energy, compression, breakout = 65, 45, 68      # short gamma, mid
    elif long_gamma and in_zone:
        energy, compression, breakout = 20, 50, 18      # damped pin (quiet=safe)
    elif long_gamma and left_pin:
        energy, compression, breakout = 48, 20, 55      # pin break (ambiguous)
    else:
        energy, compression, breakout = 40, 35, 45      # unknown / no pin

    # the app's own gamma-blast read nudges energy/breakout
    gb = {"HIGH": 12, "MEDIUM": 0, "LOW": -12}.get(gamma_blast.upper(), 0)
    energy += gb
    breakout += gb
    # expiry amplifies whatever the gamma state is (hedges unwind fast)
    if is_expiry:
        energy += 6
        breakout += 6
    if not gamma_known:
        # can't confirm the driver → pull toward neutral-uncertain
        energy = (energy + 50) // 2
        breakout = (breakout + 50) // 2

    _c = lambda x: int(max(0, min(100, x)))
    return _c(energy), _c(compression), _c(breakout)


class MarketContextEngine(Engine):
    name = "stage04_context"
    stage = 4
    deps = ["stage00_health"]

    def compute(self, state: MarketState) -> EngineResult:
        raw = state.raw
        opt = raw.get("option_data") or {}
        mp = A.mp(raw)

        # ── expiry / DTE ───────────────────────────────────────────────
        _exp_raw = (opt.get("expiry") or opt.get("selected_expiry")
                    or (raw.get("cached_raw_chain_latest") or {}).get("expiry"))
        exp_date = _parse_expiry(_exp_raw)
        today = datetime.now(IST).date()
        dte: Optional[int] = (exp_date - today).days if exp_date else None
        is_expiry = dte == 0

        # ── gap (today's open vs prior close) ──────────────────────────
        mem = raw.get("market_memory") or {}
        prev_close = mem.get("prev_close")
        day_open = raw.get("day_open")
        gap_pct = None
        gap_type = "—"
        if prev_close and day_open:
            try:
                gap_pct = (float(day_open) - float(prev_close)) / float(prev_close) * 100.0
                if gap_pct >= _GAP_PCT:
                    gap_type = "GAP-UP"
                elif gap_pct <= -_GAP_PCT:
                    gap_type = "GAP-DOWN"
                else:
                    gap_type = "FLAT-OPEN"
            except (TypeError, ValueError, ZeroDivisionError):
                gap_pct = None

        # ── pin / magnet ───────────────────────────────────────────────
        _pin = mp.get("oi_pin")
        pinned = bool(_pin)
        pin_level = float(_pin[0]) if _pin and len(_pin) else None
        regime = mp.get("regime")

        # ── dealer gamma — the real driver. Expiry is a CALENDAR event; the
        # BEHAVIOUR is set by dealer positioning. Long gamma (net GEX ≥ 0) →
        # dealers hedge AGAINST the move → pinning / mean-reversion / failed
        # breakouts. Short gamma (net GEX < 0) → dealers hedge WITH the move →
        # compression that RELEASES violently (coiled spring) or, once price
        # leaves the pin, a self-feeding trend (gamma unwind). Expiry amplifies
        # both because OTM options decay to zero and hedges unwind fast. ──
        gex = mp.get("gex_disp") or {}
        net_gex = gex.get("total")
        if net_gex is None:
            net_gex = gex.get("net_gex")
        gamma_known = isinstance(net_gex, (int, float))
        short_gamma = gamma_known and net_gex < 0
        long_gamma = gamma_known and net_gex >= 0
        gamma_blast = str((A.fmr(raw) or {}).get("gamma_blast", "") or "")

        # spot vs pin — 3 states (at / near / left). A pin only pins while
        # price is AT the magnet; once it leaves, the containment is gone.
        spot = raw.get("spot") or mp.get("spot")
        pin_dist = None
        at_pin = near_pin = False
        left_pin = pinned  # if there's a pin but no spot, treat as unknown→left
        if spot and pin_level:
            try:
                _sp = float(spot)
                pin_dist = abs(_sp - pin_level)
                at_pin = pin_dist <= max(40.0, _sp * 0.0025)     # ~0.25%
                near_pin = (not at_pin) and pin_dist <= max(80.0, _sp * 0.0055)
                left_pin = pin_dist > max(80.0, _sp * 0.0055)
            except (TypeError, ValueError):
                pass
        in_pin_zone = at_pin or near_pin
        _gtxt = (f"net GEX {net_gex:+.0f}" if gamma_known else "GEX warming up")

        # ── Energy Meter — the key distinction between "quiet because DAMPED"
        # (long gamma pin → low energy) and "quiet because LOADED" (short gamma
        # spring → high stored energy). Three 0-100 reads. ──
        energy, compression, breakout_risk = _energy_meter(
            short_gamma, long_gamma, gamma_known, at_pin, near_pin, left_pin,
            gamma_blast, is_expiry)

        # ── day classification ─────────────────────────────────────────
        if exp_date is None:
            # no chain yet → cannot frame the day
            return EngineResult.neutral(
                self.name, "option chain not loaded — day type unknown",
                data_source="session:_cached_option_data")

        risks, opps, evidence = [], [], []
        _pl = f"₹{pin_level:.0f}" if pin_level else "the pin"

        if is_expiry and pinned and short_gamma and in_pin_zone:
            # ⚡ negative gamma + at pin → COILED SPRING (quiet but LOADED)
            day_type = "EXPIRY · COILED SPRING"
            evidence.append(f"Expiry, pinned at {_pl} but dealers SHORT gamma "
                            f"({_gtxt}) — this is compression, NOT a safe range: "
                            "energy is STORED, a break releases violently")
            risks.append("Do NOT fade this like a normal pin — it's a coiled "
                         "spring; the breakout, when it comes, is fast and large")
            opps.append(f"Wait at {_pl}: trade the BREAK with momentum (gamma "
                        "blast), not the fade. Size for a fast move")
        elif is_expiry and pinned and short_gamma and left_pin:
            # 🚀 negative gamma + left pin → GAMMA UNWIND (trend underway)
            day_type = "EXPIRY · GAMMA UNWIND"
            evidence.append(f"Expiry, price has LEFT the pin ({_pl}) with dealers "
                            f"SHORT gamma ({_gtxt}) — dealer hedging now FEEDS the "
                            "move; momentum expansion, the week's big move")
            risks.append("Do NOT fade this — countertrend into a gamma unwind is "
                         "how accounts blow up; the move self-reinforces")
            opps.append("Trade WITH the trend — gamma unwind moves run further "
                        "than they 'should'; trail, don't pick a top/bottom")
        elif is_expiry and pinned and long_gamma and in_pin_zone:
            # 🧲 positive gamma + at pin → true EXPIRY PIN (damped range)
            day_type = "EXPIRY · PIN"
            evidence.append(f"Expiry, pinned at {_pl} with dealers LONG gamma "
                            f"({_gtxt}) — genuine pin: dealers damp the move, "
                            "expect chop, failed breakouts, mean-reversion")
            risks.append("Theta bleeds OTM fast; do NOT chase direction into the "
                         "pin — breakouts here tend to FAIL")
            opps.append(f"Fade the value-area edges back toward {_pl}; range "
                        "tactics, mean-reversion, sell premium into the pin")
        elif is_expiry and pinned and long_gamma and left_pin:
            # ⚠️ positive gamma + left pin → PIN BREAK (genuine or pullback?)
            day_type = "EXPIRY · PIN BREAK"
            evidence.append(f"Expiry, price left the pin ({_pl}) but dealers LONG "
                            f"gamma ({_gtxt}) — dealers still resist; is this a "
                            "genuine breakout or a snap back to the pin?")
            risks.append("Ambiguous: long gamma pulls price BACK to the pin, so a "
                         "breakout can fail and reverse — don't chase blindly")
            opps.append(f"Wait for confirmation: hold beyond the level → real "
                        f"break; stall → the pull back to {_pl} is the trade")
        elif is_expiry and pinned:
            # pinned but gamma unknown (warming up) — stay cautious
            day_type = "EXPIRY · PIN (gamma pending)"
            evidence.append(f"Expiry, pinned at {_pl} but {_gtxt} — cannot confirm "
                            "pin vs spring until GEX loads; treat as unstable")
            risks.append("Gamma unconfirmed — don't assume a safe range yet")
        elif is_expiry:
            # no pin at all → charm-driven expiry chop/whip
            day_type = "EXPIRY · VOLATILE"
            evidence.append(f"Expiry day, no clean pin ({_gtxt}) — sharp "
                            "gamma/charm swings; delta flips quickly near ATM")
            risks.append("Charm accelerates delta decay; OTM premium evaporates; "
                         "wider stops or smaller size")
            opps.append("Fast moves off levels are tradeable but exit quickly — "
                        "premium decay works against holds")
        elif dte == 1:
            day_type = "PRE-EXPIRY"
            evidence.append("Expiry tomorrow — theta accelerating; weekly premium "
                            "starts bleeding into expiry")
            risks.append("Pre-expiry theta — avoid holding far-OTM longs overnight")
        elif gap_type in ("GAP-UP", "GAP-DOWN"):
            day_type = gap_type
            evidence.append(f"{gap_type} open ({gap_pct:+.2f}% vs prior close "
                            f"₹{float(prev_close):.0f}) — watch for gap fill vs "
                            "gap-and-go")
            opps.append("Gap days: the prior close and gap-fill level are magnets — "
                        "trade the reaction there")
        elif pinned and short_gamma:
            # non-expiry coiled spring — elevated vol, smaller theta than expiry
            day_type = "COILED SPRING"
            evidence.append(f"Pinned at {_pl} but dealers SHORT gamma ({_gtxt}) — "
                            "compression with stored energy; break can expand fast "
                            "(theta effects smaller than expiry)")
            risks.append("Quiet here is LOADED, not safe — don't over-fade the range")
            opps.append("Trade the break with momentum; the pin is unstable")
        elif pinned:
            day_type = "PIN / RANGE"
            evidence.append(f"Pinned at {_pl} with dealers long/neutral gamma "
                            "({}) — range-bound day likely".format(_gtxt))
            opps.append("Range day — fade the edges; don't chase the middle")
        elif regime in ("UP", "DOWN"):
            day_type = "TREND"
            evidence.append(f"Trend day frame ({regime}) — no expiry/pin/gap "
                            "distortion; directional reads carry more weight")
        else:
            day_type = "NORMAL / RANGE"
            evidence.append("Ordinary session — no expiry, gap or pin distortion")

        if dte is not None:
            evidence.append(f"DTE {dte} (expiry {exp_date.isoformat()})")
        evidence.append(f"⚡ Energy {energy} · Compression {compression} · "
                        f"Breakout-risk {breakout_risk}")
        if gap_pct is not None and gap_type not in ("GAP-UP", "GAP-DOWN"):
            evidence.append(f"Flat open ({gap_pct:+.2f}% vs prior close)")

        # confidence: we can always frame the day once the chain is in; a
        # little higher when the distinctive (expiry / gap) frames apply.
        conf = 85.0 if (is_expiry or gap_type in ("GAP-UP", "GAP-DOWN")) else 70.0

        return EngineResult(
            engine=self.name, status=Status.OK, bias=Bias.NONE,
            confidence=conf, evidence=evidence, risks=risks, opportunities=opps,
            data={
                "day_type": day_type,
                "is_expiry": is_expiry,
                "dte": dte,
                "expiry_date": exp_date.isoformat() if exp_date else None,
                "gap_type": gap_type,
                "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
                "pinned": pinned,
                "pin_level": pin_level,
                "pin_zone": ("at" if at_pin else "near" if near_pin
                             else "left" if left_pin else "—"),
                "short_gamma": short_gamma,
                "long_gamma": long_gamma,
                "net_gex": net_gex if gamma_known else None,
                "at_pin": at_pin,
                # ── Energy Meter ──
                "energy": energy,
                "compression": compression,
                "breakout_risk": breakout_risk,
            },
            provenance=A.prov("mios:option_chain+memory", Tier.DERIVED),
        )
