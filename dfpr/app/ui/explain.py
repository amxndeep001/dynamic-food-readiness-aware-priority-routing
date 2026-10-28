"""Plain-English explanations of a recorded decision (built from its numbers)."""

from __future__ import annotations

import re

FACTOR_WORDS = {"U": "urgency", "F": "food readiness", "W": "waiting time", "D": "distance",
                "C": "traffic delay", "R": "rider waiting"}


def fmt_dur(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    m = seconds / 60
    if abs(m) < 1:
        return "under a minute"
    return f"{m:.0f} min"


def clock(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600 % 24:02d}:{t // 60 % 60:02d}:{t % 60:02d}"


def _factor_phrase(k: str, d: dict) -> str:
    if k == "U":
        due = d.get("time_to_deadline", 0)
        return f"deadline in {fmt_dur(due)}" if due > 0 else f"already {fmt_dur(-due)} past its deadline"
    if k == "F":
        food = "food is already ready" if d.get("food_ready") else f"food ready in {fmt_dur(d.get('food_ready_in'))}"
        return f"{food}, rider arrives in {fmt_dur(d.get('rider_arrival_in'))}"
    if k == "W":
        return f"has waited {fmt_dur(d.get('waiting_for'))}"
    if k == "D":
        return f"{d.get('distance_m', 0) / 1000:.1f} km trip"
    if k == "C":
        return f"{fmt_dur(d.get('traffic_delay'))} of traffic delay"
    if k == "R":
        w = d.get("rider_wait", 0)
        return "rider would not wait" if w < 30 else f"rider would wait {fmt_dur(w)} at the restaurant"
    return k


def _consequence(d: dict) -> str:
    rw, fw = d.get("rider_wait", 0.0), d.get("food_wait", 0.0)
    if rw >= 60:
        return f"Prediction: the rider will wait about **{fmt_dur(rw)}** at the restaurant."
    if fw >= 60:
        return f"Prediction: the food will wait about **{fmt_dur(fw)}** for the rider."
    return "Prediction: rider and food arrive at about the same time."


def why_dfpr(dec: dict) -> str:
    c = dec["candidates"][0]
    n = dec["n_candidates"]
    contrib, d = c["contributions"], c["details"]
    head = f"**Order #{c['order_id']} → rider {c['rider_id']}** at {clock(dec['time'])}."
    if n == 1:
        return "<br>".join([head, f"It is the only order waiting, so it goes to the nearest free rider "
                                  f"(rider {c['rider_id']}).", _consequence(d)])
    helped = [k for k in sorted(contrib, key=lambda k: -contrib[k]) if contrib[k] > 0.005][:2]
    if helped:
        reasons = "Biggest reasons: " + "; ".join(
            f"{_factor_phrase(k, d)} ({FACTOR_WORDS[k]} {contrib[k]:+.2f})" for k in helped) + "."
    else:
        least = max(contrib, key=lambda k: contrib[k])
        reasons = f"Every factor counted against it, but its penalties were the smallest (e.g. {_factor_phrase(least, d)})."
    lines = [head + f" Score **{c['score']:.2f}**, the highest of {n} waiting orders.", reasons]
    r = dec.get("runner_up")
    if r is not None:
        rc = r["contributions"]
        k = max(rc, key=lambda f: contrib[f] - rc[f])
        close = " It was a close call." if c["score"] - r["score"] < 0.05 else ""
        lines.append(f"**Runner-up #{r['order_id']}** (score {r['score']:.2f}) lost mainly on {FACTOR_WORDS[k]}: "
                     f"{_factor_phrase(k, r['details'])} ({rc[k]:+.2f} vs {contrib[k]:+.2f} for #{c['order_id']})."
                     + close)
    lines.append(_consequence(d))
    return "<br>".join(lines)


BASELINE_RULE = {
    "nearest": ("Nearest order first", "the free rider who has waited longest takes the order whose restaurant is "
                "closest by road", lambda v: f"{v:.0f} m away"),
    "shortest_path": ("Shortest-path dispatch", "the free rider who has waited longest takes the order with the "
                      "shortest total trip (to restaurant + to customer)", lambda v: f"{v / 1000:.2f} km in total"),
    "static_priority": ("Static priority (EDF)", "the order with the earliest deadline goes first, to the nearest "
                        "free rider; the ranking is fixed when the order arrives", lambda v: f"due in {fmt_dur(v)}"),
    "nearest_time": ("Nearest pair (traffic-aware)", "the free rider and order with the shortest traffic-aware "
                     "drive to the restaurant are paired", lambda v: f"{fmt_dur(v)} away"),
    "fifo": ("FIFO", "the oldest order goes to the free rider who has waited longest", lambda v: "oldest order"),
}


def why_baseline(dec: dict) -> str:
    c = dec["candidates"][0]
    name, rule, fmt = BASELINE_RULE.get(dec["method"], (dec["method"], "its own rule", lambda v: f"{v:.1f}"))
    lines = [f"**Order #{c['order_id']} → rider {c['rider_id']}** at {clock(dec['time'])}.",
             f"**{name}**: {rule}. #{c['order_id']} is {fmt(c['value'])}."]
    r = dec.get("runner_up")
    if r is not None:
        lines.append(f"Runner-up #{r['order_id']}: {fmt(r['value'])}.")
    lines.append("This rule does not look at when the food will be ready. " + _consequence(c["details"]))
    return "<br>".join(lines)


def _html(text: str) -> str:
    # The card is raw HTML, where Markdown **bold** is not parsed.
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def why(dec: dict | None) -> tuple[str, bool]:
    """(HTML text, is_dfpr) for the 'Why this order?' card."""
    if dec is None:
        return "No decision yet: riders are waiting for the first order.", True
    if not dec["candidates"] or dec["chosen"] is None:
        return "Nothing to decide: no waiting orders or no free rider.", True
    if dec["method"] == "dfpr":
        return _html(why_dfpr(dec)), True
    return _html(why_baseline(dec)), False
