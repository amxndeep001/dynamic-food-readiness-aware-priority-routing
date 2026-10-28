"""Discrete-event simulator for food delivery.

Time advances by popping the earliest event from a min-heap (our ``MinHeap``,
FIFO among simultaneous events). Each event updates the state; then the
dispatcher is notified (``on_event``) and asked for assignments (``choose``)
while there are both idle riders and waiting orders.

Order lifecycle
---------------
ORDER_PLACED   restaurant starts cooking immediately; order becomes eligible.
(assignment)   an idle rider is sent to the restaurant along the fastest path.
RIDER_ARRIVED_RESTAURANT
               if the food is ready -> PICKUP now; otherwise the rider waits.
FOOD_READY     at placed_at + *actual* prep time; if the rider is waiting -> PICKUP now.
PICKUP         at max(rider arrival, actual ready); rider leaves for the customer.
DELIVERED      rider is now at the customer's node -> RIDER_IDLE.
TRAFFIC_CHANGE multipliers change; the route cache is invalidated; moving
               riders' remaining travel times are recomputed (same path).

Assumptions (also listed in the README)
---------------------------------------
* A rider moves at constant speed within a road segment; when traffic changes
  mid-segment, the remaining fraction of the segment is re-timed at the new speed.
* Riders do not re-route when traffic changes; they only speed up / slow down.
* The traffic schedule covers [start, end); during the drain period after the
  last order arrives, the final traffic state persists.
* Orders still not delivered at end + drain time are counted as UNSERVED.
"""

from __future__ import annotations

import dataclasses
import time
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd

from dispatch import make_dispatcher
from dispatch.base import Dispatcher
from ds.graph import Graph
from ds.min_heap import MinHeap
from ds.shortest_path import path_cost
from sim.city import City, build_city
from sim.config import make_rngs
from sim.events import Event, EventType
from sim.orders import Order, OrderSpec, OrderStatus, generate_order_stream
from sim.routing import Router
from sim.traffic import TrafficModel, TrafficUpdate, apply_update

HOUR = 3600.0


class RiderStatus(Enum):
    IDLE = "IDLE"
    TO_RESTAURANT = "TO_RESTAURANT"
    WAITING = "WAITING"  # at the restaurant, food not ready yet
    TO_CUSTOMER = "TO_CUSTOMER"


@dataclass
class Rider:
    """A rider and the route they are currently driving (if any).

    ``node_times[k]`` is the (actual or predicted) time the rider reaches
    ``route_nodes[k]``; ``seg_cost[k]`` is how long road k takes at the speed
    currently in force. Together they give the rider's position at any time
    and let the simulator re-time the rest of the route when traffic changes.
    """

    id: int
    node: int  # last node the rider was standing at (route origin while moving)
    capacity: int = 1  # batching hook: v1 riders carry one order at a time
    status: RiderStatus = RiderStatus.IDLE
    orders: list[int] = field(default_factory=list)
    version: int = 0
    distance_m: float = 0.0
    route_nodes: list[int] = field(default_factory=list)
    route_roads: list[int] = field(default_factory=list)
    node_times: list[float] = field(default_factory=list)
    seg_cost: list[float] = field(default_factory=list)

    @property
    def moving(self) -> bool:
        return self.status in (RiderStatus.TO_RESTAURANT, RiderStatus.TO_CUSTOMER)

    def location(self, now: float) -> int:
        """Last node reached at time ``now`` (the rider's node if not moving)."""
        if not self.moving or not self.route_nodes:
            return self.node
        i = bisect_right(self.node_times, now) - 1
        return self.route_nodes[max(0, min(i, len(self.route_nodes) - 1))]

    def predicted_arrival(self) -> float | None:
        """Predicted arrival time at the end of the current route."""
        return self.node_times[-1] if self.moving and self.node_times else None


@dataclass
class SimView:
    """Read-only window on the simulation state handed to dispatchers.

    ``eligible`` and ``idle`` are dicts used as insertion-ordered sets, so
    iterating over them is deterministic.
    """

    city: City
    graph: Graph
    router: Router
    orders: dict[int, Order]
    riders: dict[int, Rider]
    eligible: dict[int, None]  # placed, not yet assigned
    idle: dict[int, float]  # rider id -> idle since
    start_s: float
    end_s: float


@dataclass(frozen=True)
class TrafficInfo:
    """Payload of TRAFFIC_CHANGE as seen by dispatchers."""

    changes: dict[int, tuple[float, float]]  # road -> (old, new) multiplier
    invalidated_sources: list[int]  # route-cache trees that were dropped


@dataclass
class DecisionRecord:
    time: float
    n_eligible: int
    n_idle: int
    seconds: float
    assigned: bool


@dataclass
class SimResult:
    """Everything a run produced; metrics are computed from this."""

    method: str
    scenario: str
    seed: int
    orders: list[Order]
    true_ready_at: dict[int, float]
    specs: list[OrderSpec]
    rider_starts: list[int]
    rider_distance_m: list[float]
    decisions: list[DecisionRecord]
    event_counts: dict[str, int]
    update_seconds: dict[str, float]  # dispatcher on_event time per event type
    dispatcher_stats: dict
    trace: list[tuple[float, str, int | None, int | None]]
    cache_stats: dict[str, int]
    traffic_schedule: list[TrafficUpdate]
    start_s: float
    end_s: float
    wall_time_s: float

    def to_frame(self) -> pd.DataFrame:
        """One row per order, including the true ready time."""
        rows = []
        for o in self.orders:
            row = dataclasses.asdict(o)
            row["status"] = o.status.value
            row["true_ready_at"] = self.true_ready_at[o.id]
            rows.append(row)
        return pd.DataFrame(rows)


class Simulator:
    """Runs one dispatcher over one pre-generated world (orders, traffic, riders)."""

    def __init__(
        self,
        cfg: dict,
        city: City,
        specs: list[OrderSpec],
        traffic: TrafficModel,
        rider_starts: list[int],
        dispatcher: Dispatcher,
        start_s: float,
        end_s: float,
        record_trace: bool = False,
        recorder=None,
    ) -> None:
        self.cfg = cfg
        self.city = city
        self.graph = city.graph
        self.router = Router(self.graph, cfg["routing"]["algorithm"])
        self.specs = specs
        self.traffic = traffic
        self.rider_starts = rider_starts
        self.dispatcher = dispatcher
        self.start_s = start_s
        self.end_s = end_s
        self.cutoff_s = end_s + cfg["sim"]["drain_minutes"] * 60.0
        self.record_trace = record_trace
        # Optional sim.recorder.TraceRecorder for the demo app (None in experiments).
        self.recorder = recorder

        self.now = start_s
        self.queue: MinHeap[Event] = MinHeap()
        self.orders: dict[int, Order] = {}
        self.riders = {i: Rider(i, node, cfg["riders"]["capacity"]) for i, node in enumerate(rider_starts)}
        self.eligible: dict[int, None] = {}
        self.idle: dict[int, float] = {}
        # Hidden truth: dispatchers never see these.
        self._specs = {s.id: s for s in specs}
        self._true_ready: dict[int, float] = {}

        self.decisions: list[DecisionRecord] = []
        self.event_counts: Counter[str] = Counter()
        self.update_seconds: Counter[str] = Counter()
        self.trace: list[tuple[float, str, int | None, int | None]] = []
        self.view = SimView(
            city, self.graph, self.router, self.orders, self.riders, self.eligible, self.idle, start_s, end_s
        )

    # ------------------------------------------------------------------- run
    def run(self) -> SimResult:
        wall0 = time.perf_counter()
        # Traffic first so that the initial state is in place before anything
        # else happens at start_s (equal times pop in insertion order).
        for upd in self.traffic.schedule:
            self._push(Event(upd.time, EventType.TRAFFIC_CHANGE, payload=upd))
        for spec in self.specs:
            self._push(Event(spec.placed_at, EventType.ORDER_PLACED, order_id=spec.id))
        for rid in self.riders:
            self._push(Event(self.start_s, EventType.RIDER_IDLE, rider_id=rid))

        self.dispatcher.reset(self.view)
        if self.recorder is not None:
            self.recorder.start(self)
        while self.queue:
            t, event = self.queue.pop()
            if t > self.cutoff_s:
                break
            assert t >= self.now, "event queue went back in time"
            self.now = t
            public_event = self._handle(event)
            if public_event is None:  # stale rider-arrival event
                continue
            self.event_counts[event.type.value] += 1
            if self.record_trace:
                self.trace.append((t, event.type.value, event.order_id, event.rider_id))
            if self.recorder is not None:
                self.recorder.on_event(self, public_event)
            # Event handling is part of a dynamic method's computational cost,
            # so it is timed too (reported separately from decision time).
            t0 = time.perf_counter()
            self.dispatcher.on_event(public_event, self.view)
            self.update_seconds[event.type.value] += time.perf_counter() - t0
            self._decide()
            if self.recorder is not None:
                self.recorder.after_step(self)

        for o in self.orders.values():
            if o.status != OrderStatus.DELIVERED:
                o.status = OrderStatus.UNSERVED

        cache = self.router.cache
        result = SimResult(
            method=self.dispatcher.name,
            scenario="",
            seed=-1,
            orders=[self.orders[s.id] for s in self.specs if s.id in self.orders],
            true_ready_at={s.id: s.placed_at + s.actual_prep_s for s in self.specs},
            specs=self.specs,
            rider_starts=self.rider_starts,
            rider_distance_m=[r.distance_m for r in self.riders.values()],
            decisions=self.decisions,
            event_counts=dict(self.event_counts),
            update_seconds=dict(self.update_seconds),
            dispatcher_stats=self.dispatcher.stats(),
            trace=self.trace,
            cache_stats={"hits": cache.hits, "misses": cache.misses, "invalidations": cache.invalidations},
            traffic_schedule=self.traffic.schedule,
            start_s=self.start_s,
            end_s=self.end_s,
            wall_time_s=time.perf_counter() - wall0,
        )
        if self.recorder is not None:
            self.recorder.finish(self, result)
        return result

    def _push(self, event: Event) -> None:
        self.queue.push(event.time, event)

    # -------------------------------------------------------------- decisions
    def _decide(self) -> None:
        """Ask the dispatcher for assignments while riders and orders are both available."""
        while self.idle and self.eligible:
            n_elig, n_idle = len(self.eligible), len(self.idle)
            # The recorder asks for the (read-only) ranking before, and outside
            # the timing of, choose(), so decision times are not affected.
            ranked = self.recorder.before_choose(self) if self.recorder is not None else None
            t0 = time.perf_counter()
            choice = self.dispatcher.choose(self.now, self.view)
            dt = time.perf_counter() - t0
            if self.recorder is not None:
                self.recorder.after_choose(self, ranked, choice)
            self.decisions.append(DecisionRecord(self.now, n_elig, n_idle, dt, choice is not None))
            if choice is None:
                break
            self._assign(*choice)

    def _assign(self, rider_id: int, order_id: int) -> None:
        if rider_id not in self.idle:
            raise ValueError(f"dispatcher chose rider {rider_id}, who is not idle")
        if order_id not in self.eligible:
            raise ValueError(f"dispatcher chose order {order_id}, which is not eligible")
        rider, order = self.riders[rider_id], self.orders[order_id]
        if len(rider.orders) >= rider.capacity:
            raise ValueError(f"rider {rider_id} is at capacity")
        del self.idle[rider_id]
        del self.eligible[order_id]
        order.status = OrderStatus.ASSIGNED
        order.assigned_at = self.now
        order.rider_id = rider_id
        rider.orders.append(order_id)
        rider.status = RiderStatus.TO_RESTAURANT
        self._depart(rider, order, order.restaurant_node, EventType.RIDER_ARRIVED_RESTAURANT)

    # --------------------------------------------------------------- movement
    def _depart(self, rider: Rider, order: Order, dest: int, arrival: EventType) -> None:
        """Send the rider along the fastest path (current traffic) and schedule arrival."""
        route = self.router.route(rider.node, dest)
        length = path_cost(self.graph, route.roads, "length")
        rider.distance_m += length
        order.distance_m += length
        cost = self.graph.costs("time")
        rider.route_nodes = route.nodes
        rider.route_roads = route.roads
        rider.seg_cost = [cost[r] for r in route.roads]
        times = [self.now]
        for c in rider.seg_cost:
            times.append(times[-1] + c)
        rider.node_times = times
        rider.version += 1
        self._push(Event(times[-1], arrival, order.id, rider.id, version=rider.version))
        if self.recorder is not None:
            self.recorder.on_leg(self, rider)

    def _retime(self, rider: Rider, arrival: EventType) -> None:
        """Recompute a moving rider's remaining travel times after a traffic change."""
        times, roads = rider.node_times, rider.route_roads
        i = bisect_right(times, self.now) - 1
        if i >= len(roads):
            return  # already at the destination; the arrival event is due now
        cost = self.graph.costs("time")
        # Fraction of the current road still to drive, at the old speed's pace.
        frac = (times[i + 1] - self.now) / rider.seg_cost[i] if rider.seg_cost[i] > 0 else 0.0
        old_arrival = times[-1]
        rider.seg_cost[i] = cost[roads[i]]
        times[i + 1] = self.now + frac * rider.seg_cost[i]
        for j in range(i + 1, len(roads)):
            rider.seg_cost[j] = cost[roads[j]]
            times[j + 1] = times[j] + rider.seg_cost[j]
        if times[-1] != old_arrival:
            rider.version += 1  # the previously scheduled arrival is now stale
            self._push(Event(times[-1], arrival, rider.orders[0], rider.id, version=rider.version))
            if self.recorder is not None:
                self.recorder.on_retime(self, rider, i, frac)

    def _stop(self, rider: Rider, node: int) -> None:
        rider.node = node
        rider.route_nodes, rider.route_roads, rider.node_times, rider.seg_cost = [], [], [], []

    # ---------------------------------------------------------------- handlers
    def _handle(self, ev: Event) -> Event | None:
        """Apply an event to the state. Returns the event dispatchers should see
        (None if it was a stale, cancelled rider arrival)."""
        et = ev.type
        if et in (EventType.RIDER_ARRIVED_RESTAURANT, EventType.DELIVERED):
            if ev.version != self.riders[ev.rider_id].version:
                return None

        if et == EventType.ORDER_PLACED:
            spec = self._specs[ev.order_id]
            self.orders[spec.id] = Order.from_spec(spec)
            self.eligible[spec.id] = None
            self._true_ready[spec.id] = spec.placed_at + spec.actual_prep_s
            self._push(Event(self._true_ready[spec.id], EventType.FOOD_READY, order_id=spec.id))

        elif et == EventType.FOOD_READY:
            order = self.orders[ev.order_id]
            order.ready_at = self.now
            if order.rider_id is not None and self.riders[order.rider_id].status == RiderStatus.WAITING:
                self._push(Event(self.now, EventType.PICKUP, order.id, order.rider_id))

        elif et == EventType.RIDER_ARRIVED_RESTAURANT:
            rider, order = self.riders[ev.rider_id], self.orders[ev.order_id]
            self._stop(rider, order.restaurant_node)
            rider.status = RiderStatus.WAITING
            order.rider_arrived_at = self.now
            if order.ready_at is not None:
                self._push(Event(self.now, EventType.PICKUP, order.id, rider.id))

        elif et == EventType.PICKUP:
            rider, order = self.riders[ev.rider_id], self.orders[ev.order_id]
            assert self.now >= self._true_ready[order.id], "pickup before food was ready"
            order.picked_at = self.now
            order.status = OrderStatus.PICKED_UP
            rider.status = RiderStatus.TO_CUSTOMER
            self._depart(rider, order, order.customer_node, EventType.DELIVERED)

        elif et == EventType.DELIVERED:
            rider, order = self.riders[ev.rider_id], self.orders[ev.order_id]
            order.delivered_at = self.now
            order.status = OrderStatus.DELIVERED
            rider.orders.remove(order.id)
            self._stop(rider, order.customer_node)
            rider.status = RiderStatus.IDLE
            self._push(Event(self.now, EventType.RIDER_IDLE, rider_id=rider.id))

        elif et == EventType.RIDER_IDLE:
            self.idle[ev.rider_id] = self.now

        elif et == EventType.TRAFFIC_CHANGE:
            changes = apply_update(self.graph, ev.payload)
            invalidated = self.router.on_traffic_change(changes)
            if changes:
                for rider in self.riders.values():
                    if rider.status == RiderStatus.TO_RESTAURANT:
                        self._retime(rider, EventType.RIDER_ARRIVED_RESTAURANT)
                    elif rider.status == RiderStatus.TO_CUSTOMER:
                        self._retime(rider, EventType.DELIVERED)
            return dataclasses.replace(ev, payload=TrafficInfo(changes, invalidated))

        return ev


def run_simulation(
    cfg: dict,
    dispatcher: Dispatcher | str,
    scenario: str = "normal",
    seed: int = 0,
    record_trace: bool = False,
    recorder=None,
    specs: list[OrderSpec] | None = None,
    rider_starts: list[int] | None = None,
) -> SimResult:
    """Build the world for (scenario, seed) and run one dispatcher on it.

    The world (orders, prep times, traffic, rider starts) depends only on the
    config, scenario and seed, never on the dispatcher. A fresh city is built
    per run because traffic multipliers are written into its graph.
    """
    if isinstance(dispatcher, str):
        dispatcher = make_dispatcher(dispatcher, cfg)
    city = build_city(cfg["city"])
    rngs = make_rngs(seed)
    start_s = cfg["sim"]["start_hour"] * HOUR
    end_s = cfg["sim"]["end_hour"] * HOUR
    generated = generate_order_stream(cfg["demand"], scenario, city, start_s, end_s, rngs["orders"], rngs["prep"])
    traffic = TrafficModel(cfg["traffic"], city.graph, rngs["traffic"], start_s, end_s)
    starts = [int(x) for x in rngs["riders"].integers(city.graph.num_nodes, size=cfg["riders"]["count"])]
    # A scripted world (demo presets) may replace the generated orders / rider starts.
    sim = Simulator(cfg, city, generated if specs is None else specs, traffic,
                    starts if rider_starts is None else rider_starts, dispatcher, start_s, end_s,
                    record_trace, recorder)
    result = sim.run()
    result.scenario = scenario
    result.seed = seed
    return result
