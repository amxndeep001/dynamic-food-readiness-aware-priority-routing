"""Dispatch rules sharing the ``Dispatcher`` interface."""

from __future__ import annotations

from typing import Callable

from dispatch.base import Dispatcher
from dispatch.dfpr import DFPR
from dispatch.fifo import FifoDispatcher
from dispatch.nearest import NearestOrderFirst
from dispatch.nearest_time import NearestTimePair
from dispatch.shortest_path_dispatch import ShortestPathDispatch
from dispatch.static_priority import StaticPriority

# name -> factory taking the full config dict
METHODS: dict[str, Callable[[dict], Dispatcher]] = {
    "fifo": lambda cfg: FifoDispatcher(),
    "nearest": lambda cfg: NearestOrderFirst(),
    "nearest_time": lambda cfg: NearestTimePair(),
    "shortest_path": lambda cfg: ShortestPathDispatch(),
    "static_priority": lambda cfg: StaticPriority(),
    "dfpr": DFPR.from_config,
}


def make_dispatcher(name: str, cfg: dict) -> Dispatcher:
    if name not in METHODS:
        raise ValueError(f"unknown method {name!r}; choose from {sorted(METHODS)}")
    return METHODS[name](cfg)
