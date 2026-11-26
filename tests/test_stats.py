from eval.stats import bootstrap_ci, cohen_kappa, holm, mcnemar


def test_holm_orders_and_adjusts():
    out = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert abs(out["a"][0] - 0.03) < 1e-9 and out["a"][1]
    assert abs(out["c"][0] - 0.06) < 1e-9 and not out["c"][1]
    assert abs(out["b"][0] - 0.06) < 1e-9


def test_mcnemar_exact():
    b01, b10, p = mcnemar([False] * 8 + [True] * 2, [True] * 8 + [True] * 2)
    assert (b01, b10) == (8, 0) and p < 0.01


def test_kappa_and_bootstrap():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    m, lo, hi = bootstrap_ci([1, 1, 1, 1])
    assert m == lo == hi == 1
