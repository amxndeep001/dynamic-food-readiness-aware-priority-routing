*Written by hand after reviewing the tables above. If the experiments are re-run, re-check these statements against the new numbers.*

### Where DFPR wins

**Peak scenario: a large and consistent win on the delivery metrics.** Tuned DFPR has
2.97% late or unserved orders. The best baseline, Static priority (EDF), has 13.27%,
and FIFO has 12.76%. Mean delivery is 23.2 vs 27.4 min and p90 is 33.5 vs 42.5 min.
DFPR is better on **all 30 held-out seeds** against every baseline for late %, mean,
p90 and food waiting time (Holm-corrected p < 0.001). Restricted to the lunch and
dinner windows, the late rate is 4.8% vs 21-29%.

**This is not only an effect of tuning.** DFPR with untuned equal weights (8.41% late)
also beats every baseline at peak. Tuning on the development seeds cuts its late rate
by a further 5.4 percentage points, and the gain holds on the held-out seeds.

**The advantage holds across prep-time noise levels.** DFPR has the lowest late rate
at every sigma from 0 to 0.7 (20/20 seeds against every baseline). Its weights were
tuned only at sigma = 0.3.

**The win comes from the score, not from DFPR's use of traffic-aware times or its
rider choice.** The control baseline *Nearest pair (traffic-aware)* uses exactly
DFPR's routing information and rider choice: traffic-aware travel times and the
nearest idle rider. It has no priority score. At peak it does no better than
plain Nearest order first (15.25% vs 15.52% late), and DFPR beats it by 12.3
points of late %, 5.4 min mean and 23.3 min p90 on all 30 seeds. Its only win is
distance: it drives 395 km (11%) less than DFPR.

**Mechanism (supported by the ablation).** Under overload, the rules that serve the
oldest or most urgent order first (EDF, FIFO) send riders on long trips and lose
throughput. The rules that serve the nearest order first (Nearest, Shortest-path)
keep throughput up but starve far-away orders: their p90 is 57-77 min. DFPR prefers
short, low-delay trips (C, D) but raises an order's priority the longer it waits (W),
so it gets throughput without starving anyone. Removing W (+2.4 points of late %) or
C (+3.1 points) hurts most.

### Where DFPR loses or does not matter

- **Normal load: practically a tie.** Every method has about 0.63% late. DFPR's
  mean-delivery advantage is statistically significant but tiny: 0.03-0.10 min, i.e.
  2-6 seconds. At this load, delivery time is set by food preparation, not by
  dispatch: riders usually arrive before the food is ready. No method can fix the
  ~0.6% of orders whose actual prep time alone overruns the deadline.
- **Rider waiting time at the restaurant is worse.** In the normal scenario it is
  +1.5 min per order vs Nearest, Shortest-path and FIFO. At peak it is +0.35 min vs
  EDF and +1.0 min vs FIFO. DFPR (like EDF) sends the *nearest* idle rider, who
  arrives early and waits for the food.
- **Distance.** At peak DFPR covers 4% more km than Nearest order first (+141 km,
  28/30 seeds) and 12% more than the traffic-aware nearest pair (+395 km, 30/30
  seeds). In the normal scenario it covers 0.7% more than EDF. It does beat
  FIFO, Nearest and Shortest-path by about 450 km (16%) in the normal scenario, but
  that saving comes from *choosing the nearest idle rider*, which EDF also does. It
  is not specific to the DFPR score.
- **Computational cost.** DFPR's event handling costs about 10-14 ms per order
  (timings vary between runs), against about 0.01 ms for the baselines. A full-day
  simulation takes roughly 3.7x longer. Most of that is re-running Dijkstra on restaurant routes after traffic
  changes invalidate them. Its decision step itself is cheap (0.21 ms mean, 13 ms
  max). In the microbenchmark, cost per assignment grows roughly linearly with the
  number of waiting orders (0.1 ms at N=10, 5.6 ms at N=800), because a rider
  becoming idle or being assigned forces many orders to be rescored. Static priority
  stays almost flat (0.016-0.024 ms, O(log N)). The indexed heap gives O(log N)
  updates for single-order events, but **DFPR is not an O(log N)-per-decision
  method overall**. The lazy time refresh was almost never needed in real runs.
- **Sensitive to prep-time noise.** DFPR's late rate rises 8x from sigma = 0 to 0.7
  (1.4% to 11.6%), a larger relative increase than Nearest's (14.6% to 21.1%). Its
  lead over Nearest shrinks from 13.1 to 9.5 percentage points. DFPR relies on the
  prep-time estimates, so its benefit shrinks as they get worse.

### What the ablation says about the six factors

| Factor | Effect at peak when removed | Verdict |
|---|---|---|
| C, traffic delay | +3.1 pts late, +2.2 min mean | most important. **Caveat:** delay = (multiplier - 1) x free-flow time, so C is largely a *travel-time* measure; it favours short trips in congested periods rather than adding genuinely new traffic information |
| W, waiting time | +2.4 pts late | important: prevents starvation of far-away orders |
| R, rider waiting at the restaurant | +0.9 pts late, +0.4 min mean | helps, at the cost of 151 km more distance |
| D, road distance | +0.4 pts late, +0.45 min mean | small (overlaps with C) |
| U, urgency | +0.3 pts late, but -0.25 min mean | a trade-off: it lowers late % slightly but raises mean delivery |
| F, readiness alignment | no significant effect (p = 0.78) | **not useful in this setup**; tuning drove its weight to 0.05 |

The food-readiness idea helps through **R** (avoid sending riders who will wait)
and through using the *observed* ready time, not through the alignment term F. This
should be stated plainly when presenting the project. Under normal load no factor
has a practically meaningful effect.

### Threats to validity

1. **One synthetic city and one load level.** The load (18 riders, 40 orders/h) was
   chosen from baseline-only runs before DFPR existed. At heavier overload the
   location-based baselines improve relative to EDF and FIFO (see the calibration in
   Phase 4), and DFPR was not evaluated there.
2. **Tuning budget.** DFPR's weights were tuned with 1,220 development runs. The
   baselines have no parameters to tune. The equal-weights result shows that the win
   does not depend on tuning, but the size of the gap partly does.
3. **Baseline definitions follow the specification.** Nearest and Shortest-path
   measure *metres* and let the longest-idle rider choose, while DFPR uses
   traffic-aware *travel time* and the nearest rider. The traffic-aware
   nearest-pair control removes that difference and performs like plain Nearest,
   so this does not explain DFPR's margin. Traffic-aware variants of EDF and
   Shortest-path were not run.
4. **Single-order riders, simulated prep times and traffic.** Real platforms batch
   orders, and real prep-time errors may not be lognormal or independent.
5. **Late orders get maximum urgency.** U = 1 for any order predicted to be late,
   including hopeless ones. A triage rule might do better on late %, and this was
   not explored.
