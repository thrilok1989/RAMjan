"""Signal Lifecycle — the pure trade state machine (advance_lifecycle)."""

from mios_v5.lifecycle import advance_lifecycle, signal_pnl, is_terminal


def _sig(**kw):
    base = {"signal_id": "SIG-20260723-001", "side": "CALL", "status": "WAIT_ENTRY",
            "entry_price": 23900, "target": 24000, "stop": 23860}
    base.update(kw)
    return base


def test_wait_then_enter():
    s = advance_lifecycle(_sig(), 23905, confirmed=True)
    assert s["changed"] and s["status"] == "ENTERED"
    assert s["alert"] == "entry" and s["entered_price"] == 23905


def test_wait_cancel_beats_confirm():
    # thesis flipped the same tick it would have confirmed → cancel wins
    s = advance_lifecycle(_sig(), 23905, confirmed=True, invalidated=True)
    assert s["status"] == "CANCELLED" and s["outcome"] == "cancelled"


def test_wait_expires_never_entered():
    s = advance_lifecycle(_sig(), 23905, expired=True)
    assert s["status"] == "EXPIRED" and s["outcome"] == "never_entered"
    assert s["alert"] is None


def test_wait_holds_when_nothing_happens():
    s = advance_lifecycle(_sig(), 23905)
    assert not s["changed"] and s["status"] == "WAIT_ENTRY"


def test_running_hits_target():
    s = advance_lifecycle(_sig(status="ENTERED"), 24010)
    assert s["status"] == "TARGET_HIT" and s["outcome"] == "win"
    assert s["exit_price"] == 24010


def test_running_hits_stop():
    s = advance_lifecycle(_sig(status="ENTERED"), 23850)
    assert s["status"] == "STOP_HIT" and s["outcome"] == "loss"


def test_running_both_hit_is_conservative_loss():
    # a wick that spans both — resolve to stop (loss) conservatively
    s = advance_lifecycle(_sig(status="ENTERED"), 23850)
    assert s["outcome"] == "loss"


def test_put_direction():
    p = _sig(side="PUT", entry_price=24050, target=23950, stop=24090, status="ENTERED")
    assert advance_lifecycle(p, 23940)["outcome"] == "win"     # fell to target
    assert advance_lifecycle(p, 24100)["outcome"] == "loss"    # rose to stop


def test_running_expires_open():
    s = advance_lifecycle(_sig(status="ENTERED"), 23950, expired=True)
    assert s["status"] == "EXPIRED" and s["outcome"] == "open" and s["exit_price"] == 23950


def test_terminal_is_frozen():
    for term in ("TARGET_HIT", "STOP_HIT", "EXPIRED", "CANCELLED"):
        s = advance_lifecycle(_sig(status=term), 24010, confirmed=True)
        assert not s["changed"] and s["status"] == term
        assert is_terminal(term)


def test_pnl_signed_by_side():
    assert signal_pnl("CALL", 23900, 24000) == 100.0
    assert signal_pnl("PUT", 24050, 23950) == 100.0
    assert signal_pnl("CALL", 23900, 23860) == -40.0
    assert signal_pnl("CALL", None, 24000) is None


if __name__ == "__main__":
    for fn in [test_wait_then_enter, test_wait_cancel_beats_confirm,
               test_wait_expires_never_entered, test_wait_holds_when_nothing_happens,
               test_running_hits_target, test_running_hits_stop,
               test_running_both_hit_is_conservative_loss, test_put_direction,
               test_running_expires_open, test_terminal_is_frozen,
               test_pnl_signed_by_side]:
        fn()
    print("signal lifecycle tests passed")
