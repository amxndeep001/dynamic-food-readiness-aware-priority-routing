"""Tab 1: Live Dispatch - map playback, priority queue, why-card, event log, KPIs."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from sim.recorder import Trace
from ui.explain import clock, fmt_dur, why
from ui.map_view import map_figure
from ui.theme import explainer, method_label, show

SPEEDS = {"15 s / tick": 15, "30 s / tick": 30, "1 min / tick": 60, "2 min / tick": 120, "5 min / tick": 300,
          "10 min / tick": 600}
EVENT_ICON = {"ORDER_PLACED": "🧾", "FOOD_READY": "🍲", "RIDER_ARRIVED_RESTAURANT": "🏁", "PICKUP": "📦",
              "DELIVERED": "✅", "RIDER_IDLE": "🛵", "TRAFFIC_CHANGE": "🚦"}


def kpis(trace: Trace, t: float) -> dict[str, float]:
    """Running metrics using only what has happened up to time t."""
    done = [o for o in trace.orders if o["delivered_at"] is not None and o["delivered_at"] <= t]
    picked = [o for o in trace.orders if o["picked_at"] is not None and o["picked_at"] <= t]
    late = sum(o["delivered_at"] > o["deadline"] for o in done)
    late += sum(1 for o in trace.orders if o["delivered_at"] is None and t >= o["cutoff_s"])
    return {
        "delivered": len(done),
        "late": late,
        "placed": sum(o["placed_at"] <= t for o in trace.orders),
        "avg_delivery": float(np.mean([o["delivered_at"] - o["placed_at"] for o in done])) if done else None,
        "rider_wait": float(np.mean([max(0.0, o["actual_ready"] - o["rider_arrived_at"]) for o in picked])) if picked else None,
        "food_wait": float(np.mean([max(0.0, o["picked_at"] - o["actual_ready"]) for o in picked])) if picked else None,
    }


def kpi_row(trace: Trace, t: float) -> None:
    k = kpis(trace, t)
    cols = st.columns(5)
    cols[0].metric("Delivered", f"{k['delivered']} / {k['placed']}", help="Delivered so far / orders placed so far")
    cols[1].metric("Late", k["late"], help="Delivered after the deadline, or never delivered")
    cols[2].metric("Avg delivery time", fmt_dur(k["avg_delivery"]) if k["avg_delivery"] is not None else "–")
    cols[3].metric("Avg rider wait", fmt_dur(k["rider_wait"]) if k["rider_wait"] is not None else "–",
                   help="Rider standing at the restaurant until the food is ready")
    cols[4].metric("Avg food wait", fmt_dur(k["food_wait"]) if k["food_wait"] is not None else "–",
                   help="Ready food waiting for the rider to arrive")


def queue_table(dec: dict | None) -> None:
    if dec is None or not dec["candidates"]:
        st.info("Queue empty: no order is waiting for a rider right now.")
        return
    rows = []
    for i, c in enumerate(dec["candidates"][:15], 1):
        d = c["details"]
        food = "✅ ready" if d.get("food_ready") else f"🍳 {fmt_dur(d.get('food_ready_in'))}"
        due = d.get("time_to_deadline", 0)
        rows.append({
            "Rank": i, "Order": f"#{c['order_id']}", "Rider": c["rider_id"],
            "Score" if dec["method"] == "dfpr" else "Rule value":
                f"{c['score']:.2f}" if dec["method"] == "dfpr" else _rule_value(dec["method"], c["value"]),
            "Food": food, "Deadline in": fmt_dur(due) if due > 0 else f"LATE {fmt_dur(-due)}",
        })
    df = pd.DataFrame(rows)
    chosen = dec["chosen"]["order"] if dec["chosen"] else None
    runner = dec["runner_up"]["order_id"] if dec["runner_up"] else None

    def color(row):
        oid = int(row["Order"][1:])
        bg = "#d9f0dc" if oid == chosen else "#fbecc8" if oid == runner else ""
        return [f"background-color: {bg}" if bg else ""] * len(row)

    st.dataframe(df.style.apply(color, axis=1), hide_index=True, width="stretch",
                 height=min(38 * (len(df) + 1) + 4, 420))
    more = dec["n_candidates"] - len(rows)
    st.caption(f"Green = chosen, amber = runner-up. Ranking at the decision at {clock(dec['time'])} "
               f"({dec['n_candidates']} waiting, {len(dec['idle_riders'])} free rider(s))"
               + (f"; {more} more not shown." if more > 0 else "."))


def _rule_value(method: str, v: float) -> str:
    if method in ("nearest", "shortest_path"):
        return f"{v / 1000:.2f} km"
    if method in ("static_priority", "nearest_time"):
        return fmt_dur(v)
    return clock(v)


def event_log(trace: Trace, t: float) -> None:
    evs = trace.events_until(t, 15)
    if not evs:
        st.caption("No events yet.")
        return
    html = "<br>".join(f"<b>{clock(e['time'])}</b> {EVENT_ICON.get(e['type'], '•')} {e['text']}"
                       for e in reversed(evs))
    st.markdown(f"<div class='event-log'>{html}</div>", unsafe_allow_html=True)


# ------------------------------------------------------------------ playback
def _minutes(trace: Trace) -> float:
    return max(1.0, round((trace.end - trace.start) / 60 + 1, 1))


# Playback time lives in "live_t_min", a plain (non-widget) key: Streamlit
# garbage-collects widget keys between runs, which used to reset playback.
# The slider has its own key and is synced both ways.
def _sync_slider() -> None:
    st.session_state["live_t_min"] = st.session_state["live_slider"]


def _step(trace: Trace, direction: int) -> None:
    t = trace.start + st.session_state.get("live_t_min", 0.0) * 60
    times = trace.decision_times()
    if direction > 0:
        nxt = [x for x in times if x > t + 0.5]
        target = nxt[0] if nxt else trace.end
    else:
        prv = [x for x in times if x < t - 0.5]
        target = prv[-1] if prv else trace.start
    st.session_state["live_t_min"] = round((target - trace.start) / 60, 2)
    st.session_state["playing"] = False


def render(trace: Trace, params: dict) -> None:
    explainer(
        "A replay of one simulated period. **Left:** the city. Roads are coloured by traffic, dark squares are "
        "restaurants (the small circle shows orders waiting there: green = food ready, orange = still cooking), "
        "purple diamonds are customers, numbered circles are riders coloured by what they are doing. "
        "**Right:** the dispatcher's ranking at its latest decision and, in plain English, why the top order won."
    )
    if st.session_state.get("live_trace") != id(trace):  # new run: rewind
        st.session_state["live_trace"] = id(trace)
        st.session_state["live_t_min"] = 0.0
        st.session_state["playing"] = False

    c = st.columns([1, 1, 1.4, 4])
    playing = st.session_state.get("playing", False)
    if c[0].button("⏸ Pause" if playing else "▶ Play", type="primary", width="stretch"):
        st.session_state["playing"] = not playing
        if not playing and st.session_state.get("live_t_min", 0.0) >= _minutes(trace) - 0.01:
            st.session_state["live_t_min"] = 0.0
        st.rerun()
    if c[1].button("⏮ Restart", width="stretch"):
        st.session_state["live_t_min"] = 0.0
        st.session_state["playing"] = False
    speed_names = list(SPEEDS)
    default = next((n for n, v in SPEEDS.items() if v == st.session_state.get("speed", 60)), "1 min / tick")
    sel = c[2].selectbox("Speed", speed_names, index=speed_names.index(default), label_visibility="collapsed")
    st.session_state["speed"] = SPEEDS[sel]
    c[3].markdown(f"**{method_label(trace.meta['method'])}** · {len(trace.orders)} orders · "
                  f"{trace.meta['num_riders']} riders · {clock(trace.start)}–{clock(trace.end)}")

    @st.fragment(run_every=0.8 if st.session_state.get("playing") else None)
    def body() -> None:
        total = _minutes(trace)
        cur = min(st.session_state.get("live_t_min", 0.0), total)
        if st.session_state.get("playing"):
            cur = cur + st.session_state.get("speed", 60) / 60
            if cur >= total:
                cur, st.session_state["playing"] = total, False
        st.session_state["live_t_min"] = round(cur, 2)
        st.session_state["live_slider"] = st.session_state["live_t_min"]
        b = st.columns([1, 1, 6])
        b[0].button("◀ Step back", on_click=_step, args=(trace, -1), width="stretch",
                    help="Jump to the previous decision")
        b[1].button("Step ▶", on_click=_step, args=(trace, 1), width="stretch",
                    help="Jump to the next decision")
        b[2].slider("Minutes since start", 0.0, total, step=0.25, key="live_slider", on_change=_sync_slider,
                    label_visibility="collapsed")
        t = trace.start + st.session_state["live_t_min"] * 60

        kpi_row(trace, t)
        left, right = st.columns([0.65, 0.35])
        snap_dec = trace.decisions[i] if (i := trace.decision_index_at(t)) is not None else None
        with left:
            chosen = snap_dec["chosen"]["order"] if snap_dec and snap_dec["chosen"] else None
            fig = map_figure(trace, t, title=f"City at {clock(t)}", highlight_order=chosen)
            show(fig, "live_map", "dfpr_live_map")
        with right:
            st.subheader("Priority queue (latest decision)")
            queue_table(snap_dec)
            st.subheader("Why this order?")
            text, is_dfpr = why(snap_dec)
            st.markdown(f"<div class='why-card {'' if is_dfpr else 'baseline'}'>{text}</div>",
                        unsafe_allow_html=True)
            st.subheader("Event log")
            event_log(trace, t)

    body()
