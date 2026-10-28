"""DFPR: factor ranges and directions, the lazy-refresh bound, and dynamic-update consistency."""

from __future__ import annotations

import json
import random

import pytest

from dispatch import make_dispatcher
from dispatch.dfpr import (
    DFPR,
    Factors,
    Normalization,
    RouteTerms,
    Weights,
    combine,
    compute_factors,
)
from eval.invariants import check_invariants
from sim.city import build_city
from sim.config import load_config
from sim.events import Event, EventType
from sim.orders import Order
from sim.routing import Router
from sim.simulator import Rider, SimView, run_simulation

SMALL = {"sim": {"start_hour": 11, "end_hour": 14, "drain_minutes": 90}, "riders": {"count": 15}}
NORM = Normalization(45 * 60, 10 * 60, 30 * 60, 10 * 60, 15 * 60, 10_000)
W1 = Weights()
T0 = 40_000.0


def make_order(placed=T0, est_prep=900.0, deadline_after=2400.0, ready_at=None) -> Order:
    o = Order(0, 1, 2, placed, est_prep, placed + deadline_after)
    o.ready_at = ready_at
    return o


def terms(tau_r=300.0, tau_c=600.0, dist_r=2000.0, dist_c=4000.0, delay=0.0) -> RouteTerms:
    return RouteTerms(0, tau_r, tau_r - delay / 2, dist_r, tau_c, tau_c - delay / 2, dist_c)


def random_case(rng: random.Random) -> tuple[Order, RouteTerms, float]:
    placed = T0 + rng.uniform(0, 3600)
    ready = None
    if rng.random() < 0.4:
        ready = placed + rng.uniform(0, 3000)
    order = make_order(placed, rng.uniform(60, 2400), rng.uniform(600, 4000), ready)
    tau_r, tau_c = rng.uniform(0, 1800), rng.uniform(0, 1800)
    rt = RouteTerms(0, tau_r, tau_r * rng.uniform(0.3, 1), rng.uniform(0, 5000),
                    tau_c, tau_c * rng.uniform(0.3, 1), rng.uniform(0, 5000))
    now = placed + rng.uniform(0, 5000)
    if ready is not None:
        now = max(now, ready)  # ready_at is only known once it has happened
    return order, rt, now


# ----------------------------------------------------------------- ranges
def test_all_factors_in_unit_interval() -> None:
    rng = random.Random(0)
    for _ in range(5000):
        f = compute_factors(*random_case(rng), NORM)
        for name, v in vars(f).items():
            assert 0.0 <= v <= 1.0, (name, v)


# -------------------------------------------------------------- directions
def test_combine_signs() -> None:
    base = Factors(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
    s = combine(base, W1)
    for name, sign in [("U", +1), ("F", +1), ("W", +1), ("D", -1), ("C", -1), ("R", -1)]:
        bumped = Factors(**{**vars(base), name: 0.9})
        assert (combine(bumped, W1) - s) * sign > 0, name


def test_more_urgent_order_scores_higher() -> None:
    relaxed = make_order(deadline_after=3000.0)
    urgent = make_order(deadline_after=2000.0)
    now = T0 + 300
    fr, fu = compute_factors(relaxed, terms(), now, NORM), compute_factors(urgent, terms(), now, NORM)
    assert fu.U > fr.U
    assert combine(fu, W1) > combine(fr, W1)


def test_larger_rider_wait_scores_lower() -> None:
    # Food ready at T0+900. A rider arriving at T0+300 waits 600 s, one arriving
    # at T0+700 waits 200 s. Distances and delays are equal, and the predicted
    # delivery (driven by the food) is the same, so only R and F differ.
    order = make_order(est_prep=900.0)
    early = compute_factors(order, terms(tau_r=300.0), T0, NORM)
    late = compute_factors(order, terms(tau_r=700.0), T0, NORM)
    assert early.R > late.R
    assert early.U == late.U and early.D == late.D and early.C == late.C
    assert combine(early, W1) < combine(late, W1)


def test_readiness_alignment_peaks_when_rider_arrives_as_food_is_ready() -> None:
    order = make_order(est_prep=900.0)
    f = {tau: compute_factors(order, terms(tau_r=tau), T0, NORM).F for tau in (300, 600, 900, 1200, 1500)}
    assert f[900] == 1.0
    assert f[600] < f[900] and f[300] < f[600]
    assert f[1200] < f[900] and f[1500] < f[1200]


def test_wait_distance_delay_directions() -> None:
    order = make_order()
    assert compute_factors(order, terms(), T0 + 600, NORM).W > compute_factors(order, terms(), T0 + 60, NORM).W
    assert compute_factors(order, terms(dist_r=4000), T0, NORM).D > compute_factors(order, terms(), T0, NORM).D
    assert compute_factors(order, terms(delay=300), T0, NORM).C > compute_factors(order, terms(), T0, NORM).C


def test_observed_ready_time_replaces_estimate() -> None:
    # Estimated ready at T0+900, but the food actually became ready at T0+200.
    assert compute_factors(make_order(ready_at=T0 + 200), terms(tau_r=300.0), T0 + 200, NORM).R == 0.0
    assert compute_factors(make_order(), terms(tau_r=300.0), T0 + 200, NORM).R > 0.0


# ------------------------------------------------------- lazy-refresh bound
def test_score_drift_is_bounded_by_lipschitz_constant() -> None:
    rng = random.Random(1)
    for _ in range(5000):
        w = Weights(*(rng.uniform(0, 3) for _ in range(6)))
        L = NORM.lipschitz(w)
        order, rt, t1 = random_case(rng)
        t2 = t1 + rng.uniform(0, 3000)
        s1 = combine(compute_factors(order, rt, t1, NORM), w)
        s2 = combine(compute_factors(order, rt, t2, NORM), w)
        assert s2 - s1 <= L * (t2 - t1) + 1e-9


# ---------------------------------------------------- dynamic consistency
class CheckedDFPR(DFPR):
    """DFPR that cross-checks its incremental state against brute force on every call."""

    def on_event(self, event, view):
        super().on_event(event, view)
        self._check_state(view)

    def _check_state(self, view) -> None:
        assert set(self.heap.keys()) == set(view.eligible)
        for oid in self.heap.keys():
            order = view.orders[oid]
            rt = self.terms[oid]
            best = self._best_idle_rider(order, view)
            if best is None:
                assert rt.rider is None
            else:
                # Same travel time as the true nearest idle rider (ties allowed).
                dist = view.router.cache.tree(order.restaurant_node, "time").dist
                assert rt.rider in view.idle
                assert dist[view.riders[rt.rider].node] == pytest.approx(dist[view.riders[best].node])
            assert rt == self._route_terms(order, rt.rider, view), "stale cached route terms"
        # Every cached key is an upper bound in the lazy sense: key + L*now >= true score.
        now = max(self.scored_at.values(), default=0.0)
        for oid in self.heap.keys():
            assert self.heap.priority(oid) + self.L * now >= self.score(oid, view, now) - 1e-9

    def choose(self, now, view):
        exact = {oid: self.score(oid, view, now) for oid in self.heap.keys()} if view.idle else {}
        choice = super().choose(now, view)
        if choice is not None:
            assert exact[choice[1]] == pytest.approx(max(exact.values())), "lazy argmax is not the true argmax"
        return choice


def test_lazy_refresh_path_returns_true_argmax() -> None:
    """Force stale heap entries: decisions spaced out in time with no events between them.

    In full simulations most entries get rescored by RIDER_IDLE / ASSIGNMENT
    just before a decision, so the lazy path is rarely taken; this test makes
    sure it is exercised and still exact.
    """
    cfg = load_config()
    city = build_city(cfg["city"])
    rng = random.Random(5)
    total_refreshes = 0
    for trial in range(15):
        router = Router(city.graph)
        riders = {i: Rider(i, rng.randrange(city.graph.num_nodes)) for i in range(8)}
        view = SimView(city, city.graph, router, {}, riders, {}, {i: T0 for i in riders}, T0, T0 + 3600)
        w = Weights(*(rng.uniform(0, 3) for _ in range(6)))
        dfpr = DFPR(w, cfg["dfpr"]["normalization"])
        dfpr.reset(view)
        t = T0
        for oid in range(25):
            t += rng.uniform(0, 120)
            rest = rng.choice(city.restaurants)
            view.orders[oid] = Order(oid, rest.node, rng.randrange(city.graph.num_nodes), t,
                                     rest.mean_prep_s, t + rng.uniform(2100, 2700))
            view.eligible[oid] = None
            dfpr.on_event(Event(t, EventType.ORDER_PLACED, order_id=oid), view)
        while view.idle:
            t += rng.uniform(30, 600)
            exact = {oid: dfpr.score(oid, view, t) for oid in dfpr.heap.keys()}
            rider, oid = dfpr.choose(t, view)
            assert exact[oid] == pytest.approx(max(exact.values()))
            del view.idle[rider], view.eligible[oid]
        total_refreshes += dfpr.lazy_refreshes
    assert total_refreshes > 0


@pytest.mark.parametrize("scenario,seed", [("peak", 0), ("normal", 1)])
def test_incremental_state_matches_brute_force(scenario: str, seed: int) -> None:
    cfg = load_config(overrides=SMALL)
    # More incidents -> more TRAFFIC_CHANGE events exercising cache invalidation.
    cfg["traffic"]["incident_rate_per_hour"] = 6
    dfpr = CheckedDFPR(Weights(), cfg["dfpr"]["normalization"])
    result = run_simulation(cfg, dfpr, scenario, seed, record_trace=True)
    check_invariants(result)
    assert result.dispatcher_stats["recomputations"].get("TRAFFIC_CHANGE", 0) > 0


def test_full_run_is_deterministic_and_logs_recomputations() -> None:
    cfg = load_config(overrides=SMALL)
    a = run_simulation(cfg, "dfpr", "peak", 3, record_trace=True)
    b = run_simulation(cfg, "dfpr", "peak", 3)
    check_invariants(a)
    assert [o.delivered_at for o in a.orders] == [o.delivered_at for o in b.orders]
    s = a.dispatcher_stats
    assert s["trigger_counts"]["ORDER_PLACED"] == len(a.orders)
    assert s["recomputations"]["ORDER_PLACED"] == len(a.orders)
    assert s["rescores"].get("FOOD_READY", 0) <= s["trigger_counts"]["FOOD_READY"]
    assert s["decisions"] == len(a.orders) - sum(o.status.value == "UNSERVED" and o.assigned_at is None
                                                  for o in a.orders)


def test_weights_file_is_loaded(tmp_path) -> None:
    path = tmp_path / "w.json"
    path.write_text(json.dumps({"weights": {"u": 2, "f": 0, "w": 0.5, "d": 1, "c": 0, "r": 3}}))
    cfg = load_config(overrides={"dfpr": {"weights_file": str(path)}})
    d = make_dispatcher("dfpr", cfg)
    assert d.weights == Weights(2, 0, 0.5, 1, 0, 3)
