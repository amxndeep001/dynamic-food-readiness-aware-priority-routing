"""Binary min-heap with insertion-order tie-breaking.

Used for two things:
  * the discrete-event simulator's event queue (key = event time), and
  * the frontier in Dijkstra / A* (key = tentative distance).

Entries are stored as ``(key, seq, item)``. ``seq`` is a monotonically increasing
insertion counter, so two events scheduled for the same time pop in the order
they were pushed (FIFO). That makes simulations reproducible and means items
never have to be comparable themselves.

Complexities: push / pop O(log n), peek / len O(1).
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class MinHeap(Generic[T]):
    """Binary min-heap of ``(key, item)`` pairs with FIFO tie-breaking."""

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, T]] = []
        self._seq = 0

    def __len__(self) -> int:
        return len(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)

    def push(self, key: float, item: T) -> None:
        """Insert ``item`` with priority ``key``. O(log n)."""
        self._heap.append((key, self._seq, item))
        self._seq += 1
        self._sift_up(len(self._heap) - 1)

    def peek(self) -> tuple[float, T]:
        """Return the smallest ``(key, item)`` without removing it. O(1)."""
        if not self._heap:
            raise IndexError("peek from empty heap")
        key, _, item = self._heap[0]
        return key, item

    def pop(self) -> tuple[float, T]:
        """Remove and return the smallest ``(key, item)``. O(log n)."""
        if not self._heap:
            raise IndexError("pop from empty heap")
        h = self._heap
        top = h[0]
        last = h.pop()
        if h:
            h[0] = last
            self._sift_down(0)
        return top[0], top[2]

    def _less(self, i: int, j: int) -> bool:
        a, b = self._heap[i], self._heap[j]
        return (a[0], a[1]) < (b[0], b[1])

    def _sift_up(self, i: int) -> None:
        h = self._heap
        while i > 0:
            parent = (i - 1) // 2
            if self._less(i, parent):
                h[i], h[parent] = h[parent], h[i]
                i = parent
            else:
                break

    def _sift_down(self, i: int) -> None:
        h = self._heap
        n = len(h)
        while True:
            left, right = 2 * i + 1, 2 * i + 2
            smallest = i
            if left < n and self._less(left, smallest):
                smallest = left
            if right < n and self._less(right, smallest):
                smallest = right
            if smallest == i:
                break
            h[i], h[smallest] = h[smallest], h[i]
            i = smallest

    def check_invariants(self) -> None:
        """Assert the heap property (used by tests). O(n)."""
        n = len(self._heap)
        for i in range(n):
            for c in (2 * i + 1, 2 * i + 2):
                if c < n:
                    assert not self._less(c, i), f"heap order violated at {i}->{c}"
