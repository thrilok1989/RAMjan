"""One refresh per cycle, oldest first, nobody starves.

The cross-expiry read needs three option chains. Fetching all three the moment
its cache expired put three requests into an endpoint Dhan caps at one per
three seconds — the burst that tripped the limiter. Rotating refreshes the
single stalest each cycle instead, which is the same work spread out.

Two properties matter and neither is obvious from reading the call site: only
ever one key comes back, and it is always the oldest stale one, so a rotation
cannot leave an entry permanently behind.
"""

from __future__ import annotations

from mios_v5.fetch_rotation import drop_missing, next_to_refresh


EXPIRIES = ["2026-08-27", "2026-09-03", "2026-09-24"]
TTL = 120.0


# ── nothing to do while everything is fresh ────────────────────────────

def test_returns_none_when_all_fresh():
    now = 1_000.0
    fresh = {e: now - 10.0 for e in EXPIRIES}
    assert next_to_refresh(EXPIRIES, fresh, now, TTL) is None


def test_a_key_exactly_at_the_ttl_is_not_yet_stale():
    now = 1_000.0
    fresh = {e: now - TTL for e in EXPIRIES}
    assert next_to_refresh(EXPIRIES, fresh, now, TTL) is None


# ── never fetched beats merely old ─────────────────────────────────────

def test_an_unseen_key_is_picked_first():
    now = 1_000.0
    fresh = {EXPIRIES[0]: now - 500.0, EXPIRIES[1]: now - 400.0}
    # EXPIRIES[2] has never been fetched at all
    assert next_to_refresh(EXPIRIES, fresh, now, TTL) == EXPIRIES[2]


def test_everything_unseen_picks_the_first_listed():
    assert next_to_refresh(EXPIRIES, {}, 1_000.0, TTL) == EXPIRIES[0]


# ── exactly one, and always the oldest ─────────────────────────────────

def test_picks_the_oldest_stale_key():
    now = 1_000.0
    fresh = {EXPIRIES[0]: now - 200.0,
             EXPIRIES[1]: now - 900.0,      # oldest
             EXPIRIES[2]: now - 300.0}
    assert next_to_refresh(EXPIRIES, fresh, now, TTL) == EXPIRIES[1]


def test_only_one_key_is_ever_returned():
    now = 1_000.0
    fresh = {e: now - 999.0 for e in EXPIRIES}   # all three long stale
    got = next_to_refresh(EXPIRIES, fresh, now, TTL)
    assert got in EXPIRIES and not isinstance(got, (list, tuple, set))


def test_rotation_covers_every_key_and_starves_none():
    """Drive it the way the render loop does: one refresh per cycle, 20s
    apart. Every expiry must come round inside its TTL."""
    now = 0.0
    fresh: dict = {}
    picked = []
    for _ in range(9):                       # 9 cycles = 180s
        target = next_to_refresh(EXPIRIES, fresh, now, TTL)
        if target is not None:
            fresh[target] = now
            picked.append(target)
        now += 20.0

    assert set(picked) >= set(EXPIRIES), f"an expiry never refreshed: {picked}"
    for e in EXPIRIES:
        assert now - fresh[e] <= TTL + 20.0, f"{e} went stale beyond its TTL"


def test_one_fetch_per_cycle_is_enough_to_keep_three_fresh():
    """Three keys, 120s TTL, 20s cycles — a full round takes 60s, so the
    rotation keeps up without ever fetching two in one cycle."""
    now, fresh = 0.0, {e: 0.0 for e in EXPIRIES}
    fetches = 0
    for _ in range(30):                      # 600s of running
        target = next_to_refresh(EXPIRIES, fresh, now, TTL)
        if target is not None:
            fresh[target] = now
            fetches += 1
        now += 20.0
    # 600s / 120s TTL x 3 keys = ~15 refreshes; nowhere near one per cycle
    assert fetches <= 18, fetches
    assert max(now - t for t in fresh.values()) <= TTL + 20.0


# ── keys that roll off are forgotten ───────────────────────────────────

def test_drop_missing_forgets_rolled_off_keys():
    store = {"2026-08-20": {"ts": 1.0}, "2026-08-27": {"ts": 2.0}}
    drop_missing(store, ["2026-08-27", "2026-09-03"])
    assert "2026-08-20" not in store, "yesterday's expiry is still counted"
    assert "2026-08-27" in store


def test_drop_missing_mutates_in_place_and_returns_it():
    store = {"a": 1, "b": 2}
    out = drop_missing(store, ["b"])
    assert out is store
    assert store == {"b": 2}
