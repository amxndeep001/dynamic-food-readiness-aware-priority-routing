"""Hand-written statistics vs scipy (test-only cross-check), and metric sanity."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from eval.metrics import compute_metrics
from eval.stats import holm, paired_compare, paired_t, t_ppf, t_sf_two_sided, wilcoxon_signed_rank
from sim.config import load_config
from sim.simulator import run_simulation

scipy_stats = pytest.importorskip("scipy.stats")


@pytest.mark.parametrize("df", [1, 2, 5, 29, 100])
def test_t_distribution_matches_scipy(df: int) -> None:
    for t in [0.0, 0.3, 1.0, 2.0, 3.5, 8.0]:
        assert t_sf_two_sided(t, df) == pytest.approx(2 * scipy_stats.t.sf(t, df), rel=1e-8, abs=1e-12)
    for q in [0.9, 0.975, 0.995]:
        assert t_ppf(q, df) == pytest.approx(scipy_stats.t.ppf(q, df), rel=1e-6)


@pytest.mark.parametrize("seed", range(10))
def test_paired_t_matches_scipy(seed: int) -> None:
    rng = np.random.default_rng(seed)
    a = rng.normal(10, 2, 30)
    b = a + rng.normal(0.4, 1, 30)
    mean, t, p, lo, hi = paired_t(a, b)
    ref = scipy_stats.ttest_rel(a, b)
    assert t == pytest.approx(ref.statistic, rel=1e-9)
    assert p == pytest.approx(ref.pvalue, rel=1e-6)
    assert lo < mean < hi


@pytest.mark.parametrize("seed", range(10))
def test_wilcoxon_exact_matches_scipy_without_ties(seed: int) -> None:
    rng = np.random.default_rng(seed)
    a = rng.normal(0, 1, 20)
    b = a + rng.normal(0.3, 1, 20)
    ref = scipy_stats.wilcoxon(a, b, method="exact")
    assert wilcoxon_signed_rank(a, b) == pytest.approx(ref.pvalue, rel=1e-9)


def test_wilcoxon_with_ties_matches_brute_force() -> None:
    # Brute force over all 2^n sign flips, with tied |differences|.
    d = np.array([1.0, 1.0, 2.0, -2.0, 3.0, 3.0, 3.0, -0.5, 4.0])
    a, b = d, np.zeros_like(d)
    absd = np.abs(d)
    ranks = scipy_stats.rankdata(absd)
    w_obs = ranks[d > 0].sum()
    ws = [sum(r for r, s in zip(ranks, signs) if s) for signs in itertools.product([0, 1], repeat=len(d))]
    ws = np.array(ws)
    p = min(1.0, 2 * min((ws <= w_obs + 1e-9).mean(), (ws >= w_obs - 1e-9).mean()))
    assert wilcoxon_signed_rank(a, b) == pytest.approx(p)


def test_wilcoxon_all_zero_and_paired_counts() -> None:
    x = np.array([1.0, 2.0, 3.0])
    assert wilcoxon_signed_rank(x, x) == 1.0
    r = paired_compare([1, 2, 5], [2, 2, 4])
    assert (r.wins, r.losses, r.ties) == (1, 1, 1)


def test_holm() -> None:
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.5]) == [0.5]


def test_metrics_are_consistent() -> None:
    cfg = load_config(overrides={"sim": {"start_hour": 11, "end_hour": 14, "drain_minutes": 90}})
    result = run_simulation(cfg, "nearest", "peak", 0)
    m = compute_metrics(result, [[12, 14]])
    assert m["orders"] == len(result.orders)
    assert 0 <= m["late_pct"] <= 100
    assert m["late_count"] >= m["unserved"]
    assert m["p90_delivery_min"] >= m["avg_delivery_min"] * 0.5
    assert m["food_wait_min"] >= 0 and m["rider_wait_min"] >= 0
    assert 0 < m["peak_orders"] < m["orders"]
    assert m["total_distance_km"] == pytest.approx(sum(o.distance_m for o in result.orders) / 1000)
