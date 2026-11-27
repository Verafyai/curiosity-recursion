"""UCB1 allocation: minimum per lane in round 1, proportional blocks after, dry lanes close, never above B."""
from cr.allocator import DRY_ROUNDS, MIN_FIRST_ROUND, Allocator, LaneStats


def alloc(n=4):
    return Allocator(lanes={f"l{i}": LaneStats(prior=0.5 + i * 0.1) for i in range(n)})


def test_round_one_minimum_and_budget():
    a = alloc()
    out = a.allocate(100, 12, list(a.lanes))
    assert all(v == MIN_FIRST_ROUND for v in out.values()) and len(out) == 4
    out = a.allocate(5, 12, list(a.lanes))
    assert sum(out.values()) == 5


def test_ucb_prefers_rewarding_lane_and_never_exceeds_left():
    a = alloc()
    a.round = 1
    for l in a.lanes:
        a.update(l, 3, 0.0, 0, 3)
    a.update("l0", 3, 3.0, 3, 0)
    out = a.allocate(100, 12, list(a.lanes))
    assert sum(out.values()) == 12 and out["l0"] == max(out.values())
    out = a.allocate(7, 12, list(a.lanes))
    assert sum(out.values()) == 7


def test_dry_lanes_close_and_reopen():
    a = alloc(2)
    for _ in range(DRY_ROUNDS):
        a.update("l1", 2, 0.0, 0, 2)
    assert a.lanes["l1"].closed
    a.round = 1
    assert "l1" not in a.allocate(50, 12, list(a.lanes))
    a.reopen("l1")
    assert not a.lanes["l1"].closed
