"""Statistics from the preregistration: paired Wilcoxon, McNemar, bootstrap CIs, Holm.

Every function takes plain lists so it can be checked by hand. Deterministic given a seed.
"""
from __future__ import annotations

import math
import random
from typing import Sequence

from scipy import stats as st


def bootstrap_ci(values: Sequence[float], n: int = 10_000, alpha: float = 0.05, seed: int = 0) -> tuple[float, float, float]:
    """Mean and percentile bootstrap CI."""
    v = list(values)
    if not v:
        return (math.nan, math.nan, math.nan)
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(v) for _ in v) / len(v) for _ in range(n))
    return (sum(v) / len(v), means[int(n * alpha / 2)], means[int(n * (1 - alpha / 2)) - 1])


def paired_diff_ci(a: Sequence[float], b: Sequence[float], **kw) -> tuple[float, float, float]:
    return bootstrap_ci([x - y for x, y in zip(a, b)], **kw)


def wilcoxon(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Paired Wilcoxon signed-rank (two-sided). Returns (statistic, p)."""
    d = [x - y for x, y in zip(a, b)]
    if all(x == 0 for x in d):
        return (0.0, 1.0)
    r = st.wilcoxon(a, b, zero_method="wilcox", alternative="two-sided")
    return (float(r.statistic), float(r.pvalue))


def mcnemar(a_ok: Sequence[bool], b_ok: Sequence[bool]) -> tuple[int, int, float]:
    """Exact McNemar on paired binary outcomes. Returns (b01, b10, p)."""
    b01 = sum(1 for x, y in zip(a_ok, b_ok) if not x and y)
    b10 = sum(1 for x, y in zip(a_ok, b_ok) if x and not y)
    n = b01 + b10
    p = 1.0 if n == 0 else min(1.0, 2 * st.binom.cdf(min(b01, b10), n, 0.5))
    return b01, b10, float(p)


def holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, tuple[float, bool]]:
    """Holm step-down. Returns name -> (adjusted p, reject)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        adj = min(1.0, (m - i) * p)
        running = max(running, adj)
        out[k] = (running, running <= alpha)
    return out


def cohen_kappa(r1: Sequence[str], r2: Sequence[str]) -> float:
    cats = sorted(set(r1) | set(r2))
    n = len(r1)
    if n == 0:
        return math.nan
    po = sum(1 for x, y in zip(r1, r2) if x == y) / n
    pe = sum((list(r1).count(c) / n) * (list(r2).count(c) / n) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def noninferior(diffs: Sequence[float], margin: float, seed: int = 0) -> tuple[float, bool]:
    """One-sided 95% lower bound of mean(diff) via bootstrap; non-inferior if bound > -margin."""
    mean, lo, _ = bootstrap_ci(diffs, alpha=0.10, seed=seed)
    return lo, lo > -margin
