"""'Export run report': metrics, tables and every chart of the current run, saved to a folder."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from sim.recorder import Trace
from ui.runs import ROOT


def export_report(trace: Trace, params: dict, figures: dict) -> tuple[Path, int, bool]:
    """Write app_exports/<timestamp>_<preset>/ and return (folder, n_charts, pngs_written)."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(params.get("preset", "custom")).lower()).strip("_")[:30]
    folder = ROOT / "app_exports" / f"{datetime.now():%Y%m%d_%H%M%S}_{slug}_{trace.meta['method']}"
    (folder / "charts").mkdir(parents=True, exist_ok=True)

    summary = {"params": params, "meta": trace.meta, "metrics": trace.metrics, "cache": trace.cache_stats,
               "dispatcher_stats": trace.dispatcher_stats, "event_counts": trace.event_counts}
    (folder / "metrics.json").write_text(json.dumps(summary, indent=2, default=str))
    pd.DataFrame(trace.orders).to_csv(folder / "orders.csv", index=False)
    pd.DataFrame(trace.events).to_csv(folder / "events.csv", index=False)
    pd.DataFrame(trace.heap_ops).to_csv(folder / "heap_ops.csv", index=False)
    pd.DataFrame([{
        "time": d["time"], "chosen_order": d["chosen"]["order"] if d["chosen"] else None,
        "chosen_rider": d["chosen"]["rider"] if d["chosen"] else None,
        "runner_up": d["runner_up"]["order_id"] if d["runner_up"] else None,
        "waiting_orders": d["n_candidates"], "free_riders": len(d["idle_riders"]),
        "top_score": d["candidates"][0]["score"] if d["candidates"] else None,
    } for d in trace.decisions]).to_csv(folder / "decisions.csv", index=False)

    # PNGs only if the optional 'kaleido' package (and a browser for it) is available.
    pngs = importlib.util.find_spec("kaleido") is not None
    for key, fig in figures.items():
        fig.write_html(folder / "charts" / f"{key}.html", include_plotlyjs="cdn")
        if pngs:
            try:
                fig.write_image(folder / "charts" / f"{key}.png", scale=2)
            except Exception:
                pngs = False
    return folder, len(figures), pngs and bool(figures)
