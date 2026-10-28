"""Configuration loading and seeded random streams."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "default.json"

# Order matters: adding a new stream must go at the END so existing streams keep
# their values for a given seed.
RNG_STREAMS = ("orders", "prep", "traffic", "riders")


def deep_merge(base: dict, override: dict) -> dict:
    """Return a copy of ``base`` with ``override`` merged in recursively."""
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str | Path | None = None, overrides: dict[str, Any] | None = None) -> dict:
    """Load the JSON config (default: config/default.json) and apply overrides."""
    cfg = json.loads(Path(path or DEFAULT_CONFIG).read_text())
    return deep_merge(cfg, overrides or {})


def make_rngs(seed: int) -> dict[str, np.random.Generator]:
    """Independent random generators for each source of randomness in a run.

    Each stream is spawned from one SeedSequence, so the order stream, prep
    noise, traffic and rider starts depend only on the seed and never on how
    many random numbers some other component (e.g. a dispatcher) consumed.
    """
    children = np.random.SeedSequence(seed).spawn(len(RNG_STREAMS))
    return {name: np.random.default_rng(ss) for name, ss in zip(RNG_STREAMS, children)}
