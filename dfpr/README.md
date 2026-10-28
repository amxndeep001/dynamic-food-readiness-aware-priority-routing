# DFPR: Dynamic Food-Readiness-Aware Priority Routing

A Data Structures course project. It is a working prototype of a food-delivery
dispatcher that ranks waiting orders with a dynamically updated priority score,
plus a fair, seeded experiment comparing it with standard baselines in a
discrete-event simulation of a synthetic city.

The contribution is the **scoring rule and its dynamic updates**. The supporting
data structures (indexed binary heap, binary min-heap, weighted graph, Dijkstra,
A\*, route cache) are standard, and all are implemented from scratch: no `heapq`
or `networkx` in the core code.

> **Results in one paragraph** (details, tests and caveats in [`results/summary.md`](results/summary.md)):
> Under **peak demand**, tuned DFPR had 2.97% late or unserved orders. The best
> baseline, Static priority (EDF), had 13.27%. Mean delivery was 23.2 vs 27.4 min
> and p90 was 33.5 vs 42.5 min. DFPR won on all 30 held-out seeds against every
> baseline (Holm-corrected p < 0.001), and untuned equal-weight DFPR also beat every
> baseline. Under **normal demand** all methods tie for practical purposes, because
> delivery time is limited by food preparation.
>
> DFPR **loses** on:
> - rider waiting time at restaurants (+0.35 to +1.6 min per order, depending on the comparison)
> - distance against the location-only rules (+4% vs Nearest, +12% vs the traffic-aware nearest pair at peak)
> - computation: about 10-14 ms per order of event handling vs about 0.01 ms; cost grows linearly with waiting orders
>
> Its advantage also shrinks as prep-time estimates get noisier. In the ablation,
> the waiting-time and traffic-delay terms mattered most, and the
> readiness-alignment term F had no measurable effect.

---

## Demo app (for the presentation)

An interactive Streamlit app replays simulations visually. It reuses the
project's own simulator, dispatchers and data structures: the UI only draws
what a `sim.recorder.TraceRecorder` captured during a real run.

```bash
cd dfpr
py -3.13 -m pip install -r requirements.txt     # adds streamlit and plotly
py -3.13 -m streamlit run app/app.py            # opens http://localhost:8501
```

| Tab | Shows |
|---|---|
| 🗺️ Live Dispatch | City map replay (roads coloured by traffic, riders by status), the priority queue at each decision, a plain-English "Why this order?", the event log, and live KPIs |
| 📊 Score Breakdown | Each factor's signed contribution per order; what-if weight sliders that re-rank instantly; the formula filled in |
| ⏱️ Waiting Times | Timeline per order (rider waiting = red, food waiting = orange), distributions, arrivals vs waits over the day |
| ⚖️ Method Comparison | Same world, different rules: synced side-by-side replay, metric bars, radar chart, and a win/loss summary computed from the numbers, plus the 30-seed results with error bars |
| 🌳 Data Structures | Step through push / pop_max / update_key on the real indexed heap (tree, array and position map); Dijkstra vs A* explored nodes; Big-O table with measured counts |
| 📈 Scalability & Ablation | Plots from the experiment CSVs (with a quick-run button if they are missing) |

- **Presets** (sidebar): *Small and clear*, *Readiness matters*, *Lunch rush*,
  *Traffic jam*. Each one runs with one click and has a caption saying what to watch.
- **PNG of any chart:** use the camera icon in the chart's toolbar.
- **📁 Export run report:** saves metrics (JSON), orders, decisions, events and
  heap operations (CSV) and every chart (HTML) to `app_exports/<timestamp>_…/`.
- The recorder is **off in all experiments**. A test checks that a recorded run
  makes exactly the same decisions as an unrecorded one.

### 5-minute demo script

| Time | Do this | Point out |
|---|---|---|
| 0:00 | Open the app. *Small and clear* is already loaded. Expand "What am I looking at?" | The map legend: restaurants (squares), customers (purple diamonds), riders coloured by status |
| 0:30 | Press **Step ▶** two or three times | The **Priority queue** on the right (green = chosen, amber = runner-up) and the **Why this order?** card, e.g. "Runner-up #… lost mainly on rider waiting" |
| 1:15 | Preset **Readiness matters**, then press **▶ Play** | Each rider stands next to a restaurant whose food needs 14 min, yet DFPR sends it to the farther, almost-ready order first: the queue shows the 12-minute rider wait penalty |
| 2:00 | Tab **⚖️ Method Comparison** (DFPR vs Nearest order first) | Nearest-first parks both riders for 14 min, giving 18.2 min mean delivery vs 10.0 for DFPR. Also point out that DFPR drives *more* km here (9.5 vs 7.7) |
| 2:45 | Preset **Lunch rush**, then tab **⏱️ Waiting Times** | The arrivals panel shows the 12:00 surge; average waits rise with it. The timeline shows red (rider waiting) and orange (food waiting) segments |
| 3:30 | Tab **📊 Score Breakdown**, move the **w_r** slider to 0 | The queue re-ranks with ↑/↓ arrows. This is the ablation in miniature |
| 4:00 | Tab **🌳 Data Structures**, operation `update_key`, click **Next step ▶** a few times | Swaps in the tree, the array and the position map, and Dijkstra vs A* nodes expanded (same cost) |
| 4:40 | Tab **⚖️ Method Comparison**, scroll to "Main experiment" | 30 held-out days: DFPR is significantly better on late %, mean and p90 at peak. Say where it loses: rider waiting, distance vs Nearest, compute cost. Mention that in the *Traffic jam* preset it does **not** beat Nearest (the banner says so) |

---

## 1. How to run

Requirements: **Python 3.11+** with `numpy`, `pandas`, `matplotlib` and `pytest`.
`networkx` and `scipy` are used **only in tests**, to cross-check the hand-written
Dijkstra and statistics; those tests are skipped if they are missing. On the
development machine the default `python` was 3.9, so commands were run with
`py -3.13`; replace that with whatever starts Python 3.11+ on your machine.

```bash
cd dfpr
py -3.13 -m pytest -q                                          # all tests (~30 s)

py -3.13 main.py --method dfpr --scenario peak --seed 3        # one simulated day, prints metrics
py -3.13 main.py --method nearest --scenario normal --seed 0   # methods: dfpr, static_priority, nearest,
                                                               #   shortest_path, nearest_time, fifo

py -3.13 main.py run-all --quick    # whole pipeline on tiny settings (~2 min) -> results_quick/
py -3.13 main.py run-all            # full experiments (about 1 hour on 8 cores) -> results/
py -3.13 main.py tune | compare | scaling | ablation | sensitivity | plots | report   # one step
```

A single `--method dfpr` run uses the tuned weights in `results/best_weights.json`
when that file exists (the weights are printed), and otherwise the equal default
weights from the config.

`run-all` runs, in order:
1. `tune`: weight search on development seeds 0-9, writes `best_weights.json`.
2. `compare`: all methods on held-out seeds 100-129, normal and peak scenarios, with paired tests.
3. `scaling`: cost microbenchmark versus number of orders and riders.
4. `ablation`: each weight set to 0 in turn.
5. `sensitivity`: varies the prep-time noise.
6. `plots`, then `report`, which writes `results/summary.md`.

Every run is checked with `eval/invariants.py`, so an impossible run (for
example, food picked up before it was ready) stops the experiment instead of
reaching a table.

A different configuration can be passed with `--config my.json` (same keys as
`config/default.json`). To use a real road network, set `city.map_file` to a JSON
edge list (see §3.1).

---

## 2. Project layout

```
dfpr/
  ds/                      hand-written data structures
    indexed_heap.py        indexed binary max-heap (order priority queue)
    min_heap.py            binary min-heap with FIFO tie-break (event queue, Dijkstra/A* frontier)
    graph.py               adjacency-list road graph, per-road traffic multiplier, JSON I/O
    shortest_path.py       Dijkstra (with path reconstruction) and A*
    route_cache.py         cache of shortest-path trees with selective invalidation
  sim/                     discrete-event simulation
    city.py                grid city generator / JSON map loader, restaurants, customers
    orders.py              order stream (non-homogeneous Poisson), prep times, deadlines
    traffic.py             time-of-day profile + random congestion incidents
    routing.py             the single router every method moves riders with
    events.py              event types
    simulator.py           event loop, riders, order lifecycle, re-timing under traffic
    recorder.py            optional trace recorder for the demo app (off in experiments)
    config.py              config loading, seeded independent random streams
  dispatch/                dispatch rules behind one interface (base.py)
    fifo.py                trivial reference rule
    nearest.py             Nearest Order First
    shortest_path_dispatch.py  Shortest-Path Dispatch
    static_priority.py     Static Priority (earliest deadline first)
    nearest_time.py        traffic-aware nearest pair (extra control baseline)
    dfpr.py                DFPR
  eval/  metrics.py  stats.py  invariants.py
  experiments/  tune.py  compare.py  scaling.py  ablation.py  sensitivity.py  plots.py  report.py  common.py
  app/                     Streamlit demo: app.py (entry), ui/ (theme, runs, presets, map, tabs/)
  config/default.json      every parameter
  tests/                   pytest suite
  results/                 CSVs, plots/, best_weights.json, summary.md, interpretation.md
  main.py                  command-line interface
```

---

## 3. Simulation model and assumptions

Units: time in **seconds** (minutes in configs and reports), distance in **metres**.
The clock is seconds since midnight.

### 3.1 City and roads
- The default city is a 25x25 grid (625 nodes) with 200 m blocks and local
  streets at 30 km/h. Three diagonal **arterials** run at 50 km/h.
- 5% of local streets are closed at random. A closure is skipped if it would
  disconnect the city, so every customer is reachable.
- Result: 625 nodes and 1,199 roads, each stored as 2 directed edges sharing one road id.
- The city has its **own fixed seed** (`city.seed`). All runs take place in the
  same city; run seeds change only demand, prep noise, traffic and rider starts.
- **Real map:** `Graph.from_json` / `City.from_json` read
  `{"nodes": [[id, x, y], ...], "edges": [[u, v, length_m, speed_mps], ...]}`,
  optionally with `"restaurants": [[node, mean_prep_s], ...]`. Missing
  restaurants are generated. A road shorter than the straight line between its
  ends is rejected, because it would break the A\* heuristic.

### 3.2 Restaurants and orders
- 40 restaurants sit at random nodes, each with a mean prep time drawn from 8-20 min.
- Customers come from a mixture: 70% from 4 Gaussian "residential" clusters
  (σ = 600 m), 30% uniform over the city, snapped to the nearest node.
- Orders arrive as a **non-homogeneous Poisson process**, generated by thinning.
  - *normal*: a flat 40 orders/h from 10:00 to 22:00 (about 480 orders a day).
  - *peak*: ×2.5 during 12-14 h and 19-21 h (about 720 orders a day).
- **Estimated prep** (shown to dispatchers) = restaurant mean × U(0.85, 1.15).
- **Actual prep** = estimate × exp(σZ − σ²/2), with Z ~ N(0,1) and σ = 0.3. This
  noise has mean 1, so estimates are unbiased but noisy. The true value is
  hidden from dispatchers: they see it only when FOOD_READY fires.
- **Deadline** = placement time + U(35, 45) min.
- The restaurant starts cooking at placement, whether or not a rider has been assigned.

### 3.3 Riders
- 18 riders start at random nodes. Each carries **one order at a time**
  (`riders.capacity = 1`; `Rider.orders` is a list, which is the hook for batching).
- **Pickup** happens at max(rider arrival, actual ready time): the rider waits
  if early, and the food waits if the rider is late.
- After delivery the rider becomes idle at the customer's node. There is no repositioning.
- Riders follow the fastest path under traffic at departure (A\* by default,
  Dijkstra selectable via `routing.algorithm`). **All methods use this same router.**
- When traffic changes mid-trip, the rest of the trip is **re-timed** at the
  new speeds, including the unfinished part of the current road. Riders do not re-route.

### 3.4 Traffic
- Effective multiplier on road r at time t = tod(t) × the product of the active
  incident factors. It is always ≥ 1: traffic only slows travel.
- **tod** is piecewise linear in the hour (1.0 off-peak, 1.35 around 12:30,
  1.45 around 19:30) and changes in 15-minute steps.
- **Incidents** arrive as a Poisson process (1.5 per hour). Each slows every road
  within 700 m of a random node by ×1.5-2.5 for 10-30 min.
- The whole schedule is generated from the seed before the run and delivered as
  TRAFFIC_CHANGE events. After 22:00 (during the drain period) the last traffic
  state persists.

### 3.5 Events and decisions
- **Event types:** ORDER_PLACED, FOOD_READY, RIDER_ARRIVED_RESTAURANT, PICKUP,
  DELIVERED, RIDER_IDLE and TRAFFIC_CHANGE.
- They are processed in time order from a binary min-heap. Simultaneous events
  are processed first-in, first-out.
- After each event, the dispatcher's `on_event` is called. Then `choose()` is
  called repeatedly while there is an idle rider and a waiting order. Every
  `choose` call is timed with `time.perf_counter`, and so is every `on_event` call.
- **The simulation ends** at 22:00 plus a 120-minute drain. Orders not delivered
  by then are **unserved** and counted as late.

### 3.6 Determinism and fairness
- Each seed spawns independent random streams (orders, prep noise, traffic,
  riders) from one `numpy.random.SeedSequence`.
- No dispatcher can consume random numbers. With the same seed, every method
  sees identical orders, prep times, traffic and rider starts; this is tested.
- Comparisons are therefore **paired by seed**.

---

## 4. Parameters (`config/default.json`)

| Group | Parameter | Default | Meaning |
|---|---|---|---|
| city | `seed` | 2026 | fixed seed of the city map |
| city | `grid_size`, `spacing_m` | 25, 200 | grid size, block length |
| city | `local_speed_kmh`, `arterial_speed_kmh` | 30, 50 | free-flow speeds |
| city | `num_arterials`, `edge_removal_frac` | 3, 0.05 | diagonal arterials, closed streets |
| city | `num_restaurants`, `prep_mean_min_range` | 40, [8, 20] | restaurants, their mean prep time |
| city | `num_customer_clusters`, `cluster_sigma_m`, `cluster_frac` | 4, 600, 0.7 | customer location mixture |
| traffic | `step_minutes`, `tod_profile` | 15, see file | time-of-day multiplier |
| traffic | `incident_rate_per_hour`, `incident_radius_m` | 1.5, 700 | congestion incidents |
| traffic | `incident_factor_range`, `incident_duration_min_range` | [1.5, 2.5], [10, 30] | incident severity and length |
| routing | `algorithm` | `astar` | movement routing (`astar` or `dijkstra`) |
| sim | `start_hour`, `end_hour`, `drain_minutes` | 10, 22, 120 | simulated day |
| demand | `base_rate_per_hour` | 40 | order arrival rate |
| demand | `scenarios.peak.peaks` | [[12,14,2.5],[19,21,2.5]] | peak windows and multipliers |
| demand | `est_prep_spread`, `prep_noise_sigma` | 0.15, 0.3 | prep estimate spread, lognormal noise |
| demand | `deadline_window_min` | [35, 45] | promised delivery window |
| riders | `count`, `capacity` | 18, 1 | fleet size, orders per rider |
| dfpr | `weights` | all 1.0 | untuned default weights |
| dfpr | `weights_file` | null | JSON with tuned weights (`results/best_weights.json`) |
| dfpr | `normalization.*` | 45, 10, 30, 10, 15 min | H_u, H_f, H_w, C_max, H_r (see §5) |
| metrics | `peak_windows` | [[12,14],[19,21]] | windows for peak-only metrics |
| experiments | `dev_seeds`, `test_seeds` | [0,10), [100,130) | tuning vs evaluation seeds |
| experiments | `tuning.*` | 40 random + 20 refined | search budget, weight range [0, 3], objective |

The load level (18 riders, 40 orders/h) was chosen **before DFPR existed**, from
baseline-only runs, so that the peak scenario is stressed but not collapsed.

---

## 5. DFPR: the score and its normalisation

For an eligible order *i* at time *t*:

```
P_i(t) = w_u*U + w_f*F + w_w*W - w_d*D - w_c*C - w_r*R
```

**Candidate rider.** The rider-dependent terms use the idle rider with the
shortest traffic-aware travel time to the order's restaurant. If the order is
picked, that rider is assigned.

**Quantities used:**
- τ_r, τ_c: traffic-aware travel time, rider→restaurant and restaurant→customer.
- free_r, free_c: the same at free-flow speed.
- dist_r, dist_c: road distance for the same two legs.
- *a* = t + τ_r: predicted rider arrival at the restaurant.
- *e*: the food's ready time. It is the observed ready time once FOOD_READY
  has fired; otherwise max(placed + est_prep, t), because the food is known not
  to be ready yet.
- d̂ = max(a, e) + τ_c: predicted delivery time.

Every factor is clipped to [0, 1] with clip(x) = min(1, max(0, x)):

| Factor | Formula | Meaning |
|---|---|---|
| **U** urgency | clip(1 − (deadline − d̂) / H_u), H_u = 45 min | 0 with ≥ 45 min of predicted slack, 1 if predicted late |
| **F** readiness alignment | clip(1 − \|e − a\| / H_f), H_f = 10 min | 1 when the rider arrives exactly as the food is ready |
| **W** waiting | clip((t − placed) / H_w), H_w = 30 min | how long the order has been waiting |
| **D** distance | clip((dist_r + dist_c) / D_max) | D_max = 2 × the largest road distance from any restaurant to any node, so D ≤ 1 by construction |
| **C** traffic delay | clip((τ_r − free_r + τ_c − free_c) / C_max), C_max = 10 min | extra time caused by traffic on both legs |
| **R** rider wait | clip(max(0, e − a) / H_r), H_r = 15 min | predicted rider waiting time at the restaurant |

The weights are **tuned** (§7), not hard-coded. Multiplying all six by the same
positive constant gives the same ranking, so only the ratios matter.

**Dynamic updates.** Waiting orders sit in an indexed max-heap. Each update is
logged against the event that triggered it (see `dispatcher_stats` in each run):

| Trigger | What is recomputed |
|---|---|
| ORDER_PLACED | the new order: candidate rider, route terms, score (push) |
| FOOD_READY | that order's score only (*e* becomes the observed time; `update_key`) |
| TRAFFIC_CHANGE | only orders whose restaurant's shortest-path tree was invalidated by the route cache |
| RIDER_IDLE | only orders for which the newly idle rider is closer than their current candidate |
| assignment | orders whose candidate was the rider just assigned (they get the next-nearest idle rider) |
| time passing | lazily at decision time (below) |

**Lazy time refresh.** Between events, scores change only because *t* advances,
and each factor changes at a bounded rate:
- |dU/dt| ≤ 1/H_u, |dF/dt| ≤ 1/H_f, |dW/dt| ≤ 1/H_w, |dR/dt| ≤ 1/H_r
- D and C do not change with *t*.

So a score computed at time *s* is at most **L·(t − s)** higher at time *t*, with
L = w_u/H_u + w_f/H_f + w_w/H_w + w_r/H_r.

The heap stores the key P_i(s_i) − L·s_i, so key + L·t is an upper bound on the
order's current score. To choose, look at the heap's top entry:
- If it was scored at the current time, its bound is exact and beats every
  other order's bound, so it is the true maximum.
- Otherwise, rescore it, update its key and look again.

This returns the exact best order and is tested against brute force. In the
experiments it was rarely needed: assignments and RIDER_IDLE events already
rescore most orders at the current time.

---

## 6. Complexity

V = nodes, E = roads, N = waiting orders, R = idle riders, n = heap size.

| Operation | Cost | Notes |
|---|---|---|
| Indexed heap `push`, `pop_max`, `update_key`, `remove` | O(log n) | position map key→index makes any key findable in O(1) |
| Indexed heap `peek`, `contains`, `priority`, `len` | O(1) | |
| Min-heap `push`, `pop` | O(log n) | FIFO tie-break via insertion counter |
| Dijkstra (single source, lazy deletion) | O((V + E) log V) | heap holds ≤ E entries; early exit at a target |
| A\* | O((V + E) log V) worst case | admissible straight-line heuristic, explores far fewer nodes in practice |
| Route cache lookup | O(1) on a hit, one Dijkstra on a miss | trees rooted at restaurants; roads are two-way and share their multiplier, so dist(rider→restaurant) = dist(restaurant→rider) |
| Route cache invalidation | O(T · changed roads) | T cached trees; slower road: drop trees that use it; faster road: drop trees where it now gives a shortcut |
| Order / rider / status lookups | O(1) | Python dicts used as hash maps |
| **Per decision** FIFO, Nearest, Shortest-path | O(N + R) | |
| **Per decision** Static priority (EDF) | O(log N + R) | heap pop, nearest idle rider |
| **Per decision** Nearest pair (traffic-aware) | O(N · R) | |
| **Per decision** DFPR `choose` | O(k log N + m(R + log N)) | k lazy refreshes, m orders whose candidate was the assigned rider |
| DFPR ORDER_PLACED / FOOD_READY | O(R + log N) / O(log N) | |
| DFPR RIDER_IDLE | O(N + m' log N) | m' orders whose candidate changes |
| DFPR TRAFFIC_CHANGE | O(a(R + log N)) + one Dijkstra per invalidated restaurant | a affected orders |
| Simulation | O(events · log events) + routing | about 6 events per order, plus traffic and re-timing |

**Measured** (see `results/summary.md` §4): with the cache warm, DFPR's cost
per assignment grows roughly **linearly** with N (≈ 0.1 ms at N = 10 to ≈ 5.6 ms
at N = 800). That is because a rider becoming idle, or being assigned, can change
the candidate rider of many orders. Static priority is almost flat
(≈ 0.02 ms, O(log N)). In full simulations, DFPR's event handling costs
≈ 11 ms per order, mostly Dijkstra re-runs after traffic changes, against
≈ 0.01 ms for the baselines.

---

## 7. Experiments (summary; full tables in `results/summary.md`)

| Experiment | Design |
|---|---|
| Weight tuning | Random search: 40 random weight vectors in [0, 3]^6, plus equal weights, plus 20 refinements around the best 4. Run on **dev seeds 0-9**, both scenarios. Objective: mean of late % + mean delivery minutes (configurable). |
| Main comparison | All methods on **held-out seeds 100-129**, normal and peak. Reported as mean ± std. Paired tests: exact Wilcoxon signed-rank test with Holm correction, plus a paired t-test with 95% CI. |
| Scaling | Microbenchmark: decision + update time per assignment vs N (R = 10) and vs R (N = 100). |
| Ablation | Tuned DFPR with each weight set to 0, on held-out seeds. Paired difference against full DFPR. |
| Sensitivity | Prep noise σ ∈ {0, 0.15, 0.3, 0.5, 0.7}, peak scenario, 20 held-out seeds. Weights are not re-tuned. |

Metrics are defined in `eval/metrics.py`:
- mean and p90 delivery time (placement → delivery)
- late % (delivered after the deadline **or** unserved)
- total distance
- food waiting (ready → pickup) and rider waiting (arrival → ready)
- decision and update time
- the same delivery metrics restricted to orders placed in the peak windows

The statistics in `eval/stats.py` use only numpy and are tested against scipy.

### Headline results (held-out seeds 100-129, mean over 30 seeds)

| Peak scenario | Late % | Mean (min) | p90 (min) | Food wait (min) | Rider wait (min) | Distance (km) |
|---|---|---|---|---|---|---|
| **DFPR (tuned)** | **2.97** | **23.2** | **33.5** | **4.0** | 4.6 | 3,682 |
| DFPR (equal weights) | 8.41 | 24.6 | 38.9 | 5.4 | 4.8 | 3,679 |
| FIFO (reference) | 12.76 | 27.1 | 41.7 | 8.0 | **3.6** | 4,254 |
| Static priority (EDF) | 13.27 | 27.4 | 42.5 | 8.2 | 4.3 | 3,951 |
| Nearest pair (traffic-aware) | 15.25 | 28.6 | 56.8 | 9.5 | 6.4 | **3,286** |
| Nearest order first | 15.52 | 28.7 | 57.1 | 9.6 | 5.8 | 3,541 |
| Shortest-path dispatch | 17.03 | 32.8 | 77.0 | 13.7 | 6.0 | 3,658 |

**Normal scenario:** every method has 0.63-0.64% late and a mean delivery of
19.13-19.24 min. DFPR's mean-delivery advantage is statistically significant but
only 0.01-0.10 min. DFPR's riders wait about 1.5 min longer at restaurants than
under Nearest, Shortest-path and FIFO, and drive about 16% less than those three.

**Where DFPR wins, where it loses, the ablation and the noise sensitivity** are
discussed in [`results/summary.md`](results/summary.md) §7, which also lists the
threats to validity. Plots are in `results/plots/`.

---

## 8. Tests

`py -3.13 -m pytest -q` runs 193 tests (including the demo's recorder and app smoke tests):
- **Heaps:** the indexed heap matches a `heapq` reference on random push, pop,
  update_key and remove sequences, with the heap order and position map checked
  after every operation. The min-heap breaks ties first-in, first-out.
- **Shortest paths:** Dijkstra matches `networkx` on random graphs in all three
  cost modes. A\* matches Dijkstra's costs under random traffic. Route-cache
  results equal a fresh Dijkstra after random traffic changes.
- **City and traffic:** the city is connected and deterministic, survives a JSON
  save and reload, and the traffic schedule is deterministic and never below 1.
- **Simulator:**
  - Runs are deterministic, and the world (orders, prep times, traffic, rider
    starts) is identical for different dispatchers.
  - Food is never picked up before it is ready, and pickup happens exactly at
    the later of rider arrival and food ready.
  - Each order is picked up and delivered exactly once, and every order ends
    up delivered or unserved.
  - Re-timing under traffic is checked exactly on a hand-computed example.
- **Baselines:** hand-made decision cases, including road distance vs straight-line
  distance and traffic changing the nearest choice.
- **DFPR:**
  - Every factor stays within [0, 1], and each term moves the score in the
    right direction (more urgent → higher; larger rider wait → lower).
  - The rate bound for lazy refresh holds.
  - On full runs, the incrementally maintained state equals a brute-force
    recomputation after every event, and every lazy choice equals the
    brute-force best.
- **Statistics:** match scipy, including exact Wilcoxon with ties against brute force.

---

## 9. Limitations

- **Synthetic map and demand.** It is a grid city with synthetic traffic and
  Poisson demand. One city and one load level were evaluated. The JSON loader
  allows a real map, but none was tested.
- **Single-order riders.** No batching (the `capacity` / `Rider.orders` hook
  exists but is unused), no repositioning of idle riders, no order cancellations.
- **Simulated prep times.** Actual prep = estimate × independent lognormal
  noise. Real errors may be biased, correlated within a restaurant, or depend on
  how busy the kitchen is. DFPR's advantage shrinks as this noise grows.
- **Riders do not re-route** when traffic changes. They are only re-timed.
- **Traffic only slows travel** (multipliers ≥ 1), which the A\* heuristic relies on.
- **Tuning budget asymmetry.** DFPR's weights were tuned with about 1,200 dev
  runs; the baselines have no parameters. Equal-weight DFPR is reported too.
- **Baseline definitions** follow the specification: Nearest and Shortest-path
  use metres and let the longest-idle rider choose. A stricter, traffic-aware
  nearest-pair control (`nearest_time`) was added to separate the effect of the
  score from those modelling differences.
- **Orders predicted to be late get maximum urgency** (U = 1), even if they are
  hopeless. A triage rule was not explored.
- **Readiness alignment F had no measurable effect** in the ablation. The
  food-readiness benefit came through R and through using the observed ready time.
- **Cost.** DFPR is not O(log N) per decision overall (§6). Timings are
  single-machine wall-clock measurements in CPython and vary from run to run.
