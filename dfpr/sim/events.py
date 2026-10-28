"""Event types for the discrete-event simulator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventType(Enum):
    ORDER_PLACED = "ORDER_PLACED"
    FOOD_READY = "FOOD_READY"
    RIDER_ARRIVED_RESTAURANT = "RIDER_ARRIVED_RESTAURANT"
    PICKUP = "PICKUP"
    DELIVERED = "DELIVERED"
    RIDER_IDLE = "RIDER_IDLE"
    TRAFFIC_CHANGE = "TRAFFIC_CHANGE"


@dataclass(frozen=True)
class Event:
    """Something that happens at ``time``.

    ``version`` is used only for rider-arrival events: when traffic changes, a
    moving rider's arrival is rescheduled and the rider's version is bumped,
    so the old (now wrong) arrival event is recognised as stale and ignored.
    """

    time: float
    type: EventType
    order_id: int | None = None
    rider_id: int | None = None
    version: int = 0
    payload: Any = None
