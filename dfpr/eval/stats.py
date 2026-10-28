"""Paired statistical tests, implemented with numpy only.

Every method is run on the same seeds, so run k of method A and run k of
method B share the same orders, prep times, traffic and rider starts. Paired
tests on the per-seed differences remove that shared "luck" and are much more
sensitive than comparing two independent means.

* Paired t-test: assumes the differences are roughly normal.
* Wilcoxon signed-rank test: makes no normality assumption. The p-value is
  computed *exactly* by enumerating the null distribution, which is cheap
  for n <= ~50 seeds.
* Holm-Bonferroni: we compare DFPR with several baselines at once, so
  p-values are adjusted for multiple comparisons.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


# ------------------------------------------------------------ t distribution
def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Numerical Recipes, 6.4)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularised incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln_front) * _betacf(b, a, 1.0 - x) / b


def t_sf_two_sided(t: float, df: float) -> float:
    """P(|T| >= |t|) for Student's t with ``df`` degrees of freedom."""
    if math.isinf(t):
        return 0.0
    return betainc(df / 2.0, 0.5, df / (df + t * t))


def t_ppf(q: float, df: float) -> float:
    """Quantile of Student's t (by bisection; only used for confidence intervals)."""
    target = 2.0 * (1.0 - q)  # two-sided tail mass beyond the quantile
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_sf_two_sided(mid, df) > target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0 if q >= 0.5 else -(lo + hi) / 2.0


# --------------------------------------------------------------------- tests
@dataclass(frozen=True)
class PairedResult:
    n: int
    mean_diff: float  # mean of (a - b)
    ci_low: float  # 95% CI of the mean difference (t-based)
    ci_high: float
    t_stat: float
    p_t: float
    p_wilcoxon: float
    wins: int  # seeds where a < b (a better, since lower is better)
    losses: int  # seeds where a > b
    ties: int


def paired_t(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float, float]:
    """Returns (mean diff, t, p two-sided, ci_low, ci_high) for a - b."""
    d = np.asarray(a, float) - np.asarray(b, float)
    n = len(d)
    mean = float(d.mean())
    if n < 2:
        return mean, float("nan"), float("nan"), float("nan"), float("nan")
    sd = float(d.std(ddof=1))
    if sd == 0.0:
        p = 1.0 if mean == 0.0 else 0.0
        return mean, (0.0 if mean == 0 else math.copysign(math.inf, mean)), p, mean, mean
    se = sd / math.sqrt(n)
    t = mean / se
    half = t_ppf(0.975, n - 1) * se
    return mean, t, t_sf_two_sided(t, n - 1), mean - half, mean + half


def wilcoxon_signed_rank(a: np.ndarray, b: np.ndarray) -> float:
    """Exact two-sided p-value of the Wilcoxon signed-rank test on a - b.

    Zero differences are dropped (Wilcoxon's original convention). Tied
    |differences| receive average ranks. Average ranks are multiples of 0.5,
    so doubling them gives integers and the exact null distribution of W+
    (each rank is + or - with probability 1/2) can be built by a subset-sum DP.
    """
    d = np.asarray(a, float) - np.asarray(b, float)
    d = d[d != 0.0]
    n = len(d)
    if n == 0:
        return 1.0
    absd = np.abs(d)
    order = np.argsort(absd, kind="mergesort")
    ranks = np.empty(n)
    i = 0
    while i < n:  # average ranks over runs of equal |d|
        j = i
        while j + 1 < n and absd[order[j + 1]] == absd[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j + 2) / 2.0
        i = j + 1
    r2 = np.rint(2 * ranks).astype(int)
    w_plus = int(r2[d > 0].sum())

    total = int(r2.sum())
    counts = np.zeros(total + 1)
    counts[0] = 1.0
    for r in r2:  # number of sign patterns giving each value of 2*W+
        counts[r:] = counts[r:] + counts[: total + 1 - r].copy()
    probs = counts / counts.sum()
    lower = probs[: w_plus + 1].sum()
    upper = probs[w_plus:].sum()
    return float(min(1.0, 2.0 * min(lower, upper)))


def paired_compare(a, b) -> PairedResult:
    """Full paired comparison of per-seed values a vs b (lower is better)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    mean, t, p, lo, hi = paired_t(a, b)
    return PairedResult(
        n=len(a), mean_diff=mean, ci_low=lo, ci_high=hi, t_stat=t, p_t=p,
        p_wilcoxon=wilcoxon_signed_rank(a, b),
        wins=int((a < b).sum()), losses=int((a > b).sum()), ties=int((a == b).sum()),
    )


def holm(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as the input)."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted
