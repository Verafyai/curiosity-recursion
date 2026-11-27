"""Value score components, UCT selection order, reward backup."""
from cr.leads import WEIGHTS, LeadTree, value_score
from cr.ledger import Decision, QuerySpec


def sp(**kw):
    return QuerySpec(**{"tool": "ia_fts", "terms": "x", "lane": "l", **kw})


def test_value_components():
    v_new, c = value_score(sp(), None, 0.5, "missing")
    assert c["novelty"] == 1.0 and c["gap_fill"] == 1.0 and c["reachability"] == 1.0
    wn, wy, wr, wg, wc = WEIGHTS
    assert abs(v_new - (wn + wy * 0.5 + wr + wg - wc)) < 1e-9
    v_rev, c2 = value_score(sp(), Decision(decision="revisit", canonical_id="a", key_type="result_offset"), 0.5, "missing")
    assert c2["novelty"] == 0.4 and v_rev < v_new
    v_cov, _ = value_score(sp(), None, 0.5, "covered")
    assert v_cov < v_new
    v_blk, c3 = value_score(sp(), Decision(decision="blocked_repeat", canonical_id="a"), 0.5, "missing")
    assert c3["novelty"] == 0.0
    _, c4 = value_score(sp(tool="stub"), None, 0.5, "missing")
    assert c4["reachability"] == 0.5


def test_uct_order_and_backup():
    t = LeadTree()
    a = t.add("l", sp(terms="a"), None, 0.6, {})
    b = t.add("l", sp(terms="b"), None, 0.5, {})
    assert t.select("l").id == a.id  # higher value first when nothing is tried
    a.status = "done"
    t.backup(a.id, 0.0)
    c = t.add("l", sp(terms="c"), a.id, 0.55, {})
    t.backup(b.id, 1.0)
    b.status = "done"
    assert t.select("l").id == c.id
    t.backup(c.id, 1.0)
    assert t.nodes[a.id].n == 2 and t.nodes[a.id].reward_sum == 1.0  # backed up to the ancestor
    assert t.nodes[c.id].n == 1


def test_floor_and_lane_ids():
    t = LeadTree()
    t.add("x", sp(), None, 0.01, {})
    assert t.select("x") is None
    y = t.add("y", sp(), None, 0.9, {})
    assert y.id == "y.1" and t.select("x") is None and t.select("y").id == "y.1"
