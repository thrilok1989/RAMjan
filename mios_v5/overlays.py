"""MIOS V6 — Dashboard 2's overlay collector.

Turns engine outputs into a flat list of things the chart can draw. It does
**not** compute anything: every price here was produced by an engine, and each
item carries the `source` that produced it, so a level on screen can always be
traced back to the thing that claimed it.

    Market data → Engine → Validated output → THIS → Dashboard

Never the other way round. If an overlay has no producing engine, it does not
appear — there are no placeholders and no chart-side derivations. An invented
level looks exactly like a real one at a glance, which makes it worse than a
missing one.

Groups exist so the toggle panel can hide a whole family at once without any
code change. Hiding is a filter over this list; nothing is recomputed.

Pure module: dicts in, list out.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: toggle group → (label, default-on). Order is the order of the toggles.
GROUPS: Dict[str, tuple] = {
    "sr":        ("Support & Resistance", True),
    "poc":       ("POCs", True),
    "trade":     ("Entry / Stop / Trail", True),
    "targets":   ("Targets", True),
    "dealer":    ("Dealer Walls", True),
    "gamma":     ("Gamma Flip", True),
    "charm":     ("Charm Pin", True),
    "orderblk":  ("Order Blocks", False),
    "liquidity": ("Liquidity Pools", False),
    "vob":       ("VOB Zones", True),
    "vwap":      ("VWAP", True),
}

#: overlay kind → (colour, dash, width). Follows the house convention:
#: green bullish · red bearish · orange building/watch · blue info
#: purple dealer/gamma/charm · grey inactive
STYLE: Dict[str, tuple] = {
    "support":      ("#17c98b", "dot", 1.2),
    "resistance":   ("#ff8c8c", "dot", 1.2),
    "entry":        ("#00ff88", "solid", 1.6),
    "stop":         ("#ff4444", "dash", 1.5),
    "trail":        ("#a78bfa", "dot", 1.5),
    "target":       ("#7fe8b0", "dashdot", 1.3),
    "war_zone":     ("#ffcc33", "dash", 1.4),
    "liquidity":    ("#4da6ff", "dot", 1.1),
    "vwap":         ("#c9b6ec", "solid", 1.2),
    "poc":          ("#ffe066", "dash", 1.3),
    "vah":          ("#7dffb0", "dot", 1.1),
    "val":          ("#ff8c8c", "dot", 1.1),
    "htf_poc":      ("#9fb0c4", "dot", 1.0),
    "call_wall":    ("#a78bfa", "dash", 1.4),
    "put_wall":     ("#a78bfa", "dash", 1.4),
    "gamma_flip":   ("#a78bfa", "solid", 1.5),
    "charm_pin":    ("#a78bfa", "dashdot", 1.4),
    "order_block":  ("#4da6ff", "dot", 1.0),
    "liq_pool":     ("#4da6ff", "dot", 1.0),
}


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _item(group: str, kind: str, label: str, price, source: str,
          spot=None, note: Optional[str] = None) -> Optional[Dict[str, Any]]:
    p = _f(price)
    if p is None:
        return None
    colour, dash, width = STYLE.get(kind, ("#9fb0c4", "dot", 1.0))
    s = _f(spot)
    return {
        "group": group, "kind": kind, "label": label, "price": p,
        "colour": colour, "dash": dash, "width": width,
        "source": source,
        "distance": (round(p - s, 1) if s is not None else None),
        "note": note,
    }


def collect(fr: Optional[Dict[str, Any]] = None,
            spot: Optional[float] = None,
            market_picture: Optional[Dict[str, Any]] = None,
            gex: Optional[Dict[str, Any]] = None,
            money_flow: Optional[Dict[str, Any]] = None,
            master: Optional[Dict[str, Any]] = None,
            charm: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Every overlay with a producing engine, each tagged with its source."""
    f = dict(fr or {})
    mp = dict(market_picture or {})
    gx = dict(gex or {})
    mf = dict(money_flow or {})
    ms = dict(master or {})
    ch = dict(charm or {})
    dec = f.get("decision_v2") or {}
    bz = f.get("battle_zone") or {}

    out: List[Optional[Dict[str, Any]]] = []
    add = out.append

    # ── support & resistance ──
    add(_item("sr", "support", "Support", f.get("strong_support"),
              "Stage 35 Reaction Zone", spot))
    add(_item("sr", "resistance", "Resistance", f.get("strong_resistance"),
              "Stage 35 Reaction Zone", spot))
    add(_item("sr", "support", "Major Support", f.get("major_support"),
              "Stage 35 Reaction Zone", spot))
    add(_item("sr", "resistance", "Major Resistance", f.get("major_resistance"),
              "Stage 35 Reaction Zone", spot))
    add(_item("sr", "war_zone", "War Zone", bz.get("price"),
              "Battle Zone", spot))

    # ── volume profile ──
    add(_item("poc", "poc", "POC", mf.get("poc_price"),
              "Money Flow Profile", spot))
    add(_item("poc", "vah", "VAH", mf.get("value_area_high"),
              "Money Flow Profile", spot))
    add(_item("poc", "val", "VAL", mf.get("value_area_low"),
              "Money Flow Profile", spot))
    for name, price in ((f.get("htf") or {}).get("levels") or {}).items():
        add(_item("poc", "htf_poc", f"{name} POC", price,
                  "Stage 45 HTF Profiles", spot))

    # ── the trade ──
    add(_item("trade", "entry", "Entry", dec.get("entry"),
              "Stage 52 Decision Engine", spot))
    add(_item("trade", "stop", "Stop", dec.get("stop"),
              "Stage 52 Decision Engine", spot))
    add(_item("trade", "trail", "Trail", (dec.get("trail") or {}).get("stop"),
              "Dynamic Trail", spot))
    add(_item("targets", "target", "Target", f.get("next_target"),
              "Stage 35 Reaction Zone", spot))

    # ── dealer walls. `oi_ceiling` / `oi_floor` ARE the call and put walls —
    # the strikes where open interest is heavy enough to cap or floor price.
    # Naming them "wall" on the chart says what they do rather than how they
    # were derived.
    add(_item("dealer", "call_wall", "Call Wall", mp.get("oi_ceiling"),
              "Market Picture · OI ceiling", spot))
    add(_item("dealer", "put_wall", "Put Wall", mp.get("oi_floor"),
              "Market Picture · OI floor", spot))
    add(_item("dealer", "call_wall", "OI Pin", mp.get("oi_pin"),
              "Market Picture · OI pin", spot))

    # ── gamma flip ──
    add(_item("gamma", "gamma_flip", "Gamma Flip",
              gx.get("gamma_flip_level") or gx.get("gamma_flip"),
              "GEX · gamma flip level", spot))

    # ── charm pin: only when the engine says it is active ──
    if ch.get("active"):
        add(_item("charm", "charm_pin", "Charm Pin", ch.get("pin"),
                  "Charm Pin engine", spot,
                  note=ch.get("drag") or ch.get("label")))

    # ── vwap ──
    add(_item("vwap", "vwap", "VWAP", mp.get("vwap"), "Market Picture", spot))

    # ── liquidity pools, both sides ──
    for side in ("above", "below"):
        for i, pool in enumerate((mp.get("liq_pools") or {}).get(side) or []):
            price = pool.get("price") if isinstance(pool, dict) else pool
            add(_item("liquidity", "liq_pool",
                      f"Liquidity {side} {i + 1}", price,
                      "Liquidity Pool detector", spot))

    # ── order blocks ──
    for i, ob in enumerate(_iter_blocks(ms.get("order_blocks"))):
        price = ob.get("mid") or ob.get("price") or ob.get("upper")
        kind = str(ob.get("type") or "").lower()
        add(_item("orderblk", "order_block",
                  f"OB {kind or i + 1}".strip(), price,
                  "Order Block detector", spot))

    return [o for o in out if o]


def _iter_blocks(blocks) -> Iterable[Dict[str, Any]]:
    if isinstance(blocks, dict):
        for v in blocks.values():
            if isinstance(v, list):
                for b in v:
                    if isinstance(b, dict):
                        yield b
            elif isinstance(v, dict):
                yield v
    elif isinstance(blocks, list):
        for b in blocks:
            if isinstance(b, dict):
                yield b


def visible(items: Optional[Iterable[Dict[str, Any]]],
            enabled: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    """Filter by toggle state. Hiding is a filter, never a recompute."""
    en = dict(enabled or {})
    return [i for i in (items or [])
            if en.get(i.get("group"), GROUPS.get(i.get("group"), ("", True))[1])]


def defaults() -> Dict[str, bool]:
    return {g: on for g, (_label, on) in GROUPS.items()}


def as_levels(items: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, Any]:
    """`{label: price}` for the chart's line drawer.

    Keyed by label rather than kind so two walls, three liquidity pools and six
    HTF POCs all survive — keying by kind would silently keep only the last of
    each.
    """
    return {i["label"]: i["price"] for i in (items or [])}


def summary(items: Optional[Iterable[Dict[str, Any]]]) -> Dict[str, int]:
    """How many overlays each group contributed — the honest count for the
    toggle panel, so a group with nothing to draw says so."""
    counts = {g: 0 for g in GROUPS}
    for i in (items or []):
        if i.get("group") in counts:
            counts[i["group"]] += 1
    return counts
