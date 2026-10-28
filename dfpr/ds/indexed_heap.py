"""Indexed binary max-heap.

A plain binary heap cannot change the priority of an arbitrary element
efficiently, because it does not know *where* that element lives in the array.
DFPR needs exactly that operation: when an order's food becomes ready or
traffic changes, its score changes and the order must move inside the queue.

We therefore keep a hash map ``_pos: key -> array index`` alongside the array.
Every time two entries are swapped the map is updated, so locating any key is
O(1) and ``update_key`` / ``remove`` become O(log n).

Complexities (n = number of entries):
    push, pop_max, update_key, remove ........ O(log n)
    peek, contains, priority, len ............ O(1)
"""

from __future__ import annotations

from typing import Callable, Generic, Hashable, Iterator, TypeVar

K = TypeVar("K", bound=Hashable)


class IndexedMaxHeap(Generic[K]):
    """Max-heap of unique keys ordered by a float priority.

    Ties on priority are broken by insertion order (older key wins), which makes
    every pop sequence fully deterministic. Internally each entry is stored as
    ``(priority, tiebreak, key)`` where ``tiebreak = -insertion_counter`` so a
    larger tuple means "higher priority, then older".

    ``observer`` (optional, None by default) is called as ``observer(op, info)``
    for every operation and every swap. It exists only so the demo app can
    record and animate heap operations; it never changes behaviour.
    """

    def __init__(self) -> None:
        self._heap: list[tuple[float, int, K]] = []
        self._pos: dict[K, int] = {}
        self._counter = 0
        self.observer: Callable[[str, dict], None] | None = None

    def _notify(self, op: str, **info) -> None:
        if self.observer is not None:
            self.observer(op, info)

    # ------------------------------------------------------------------ queries
    def __len__(self) -> int:
        return len(self._heap)

    def __contains__(self, key: object) -> bool:
        return key in self._pos

    def contains(self, key: K) -> bool:
        """Return True if ``key`` is in the heap. O(1)."""
        return key in self._pos

    def priority(self, key: K) -> float:
        """Return the current priority of ``key``. O(1). Raises KeyError."""
        return self._heap[self._pos[key]][0]

    def tiebreak(self, key: K) -> int:
        """Tie-break value of ``key`` (larger = inserted earlier). O(1)."""
        return self._heap[self._pos[key]][1]

    def peek(self) -> tuple[K, float]:
        """Return ``(key, priority)`` of the maximum without removing it. O(1)."""
        if not self._heap:
            raise IndexError("peek from empty heap")
        prio, _, key = self._heap[0]
        return key, prio

    def keys(self) -> Iterator[K]:
        """Iterate over keys in arbitrary (array) order."""
        return (entry[2] for entry in self._heap)

    # ---------------------------------------------------------------- mutations
    def push(self, key: K, priority: float) -> None:
        """Insert a new key. O(log n). Raises KeyError if the key already exists."""
        if key in self._pos:
            raise KeyError(f"key {key!r} already in heap")
        self._counter += 1
        self._heap.append((float(priority), -self._counter, key))
        self._pos[key] = len(self._heap) - 1
        self._notify("push", key=key, priority=float(priority), index=len(self._heap) - 1)
        self._sift_up(len(self._heap) - 1)
        self._notify("done")

    def pop_max(self) -> tuple[K, float]:
        """Remove and return ``(key, priority)`` with the highest priority. O(log n)."""
        if not self._heap:
            raise IndexError("pop from empty heap")
        prio, _, key = self._heap[0]
        self._notify("pop_max", key=key, priority=prio, index=0)
        self._delete_at(0)
        self._notify("done")
        return key, prio

    def update_key(self, key: K, new_priority: float) -> None:
        """Change the priority of an existing key and restore heap order. O(log n).

        The original tie-break value is kept, so an order's "age" in the queue
        does not change just because its score was refreshed.
        """
        i = self._pos[key]  # KeyError if missing, which is what we want
        old_prio, tie, _ = self._heap[i]
        self._heap[i] = (float(new_priority), tie, key)
        self._notify("update_key", key=key, priority=float(new_priority), old_priority=old_prio, index=i)
        if new_priority > old_prio:
            self._sift_up(i)
        elif new_priority < old_prio:
            self._sift_down(i)
        self._notify("done")

    def remove(self, key: K) -> float:
        """Remove an arbitrary key and return its priority. O(log n)."""
        i = self._pos[key]
        prio = self._heap[i][0]
        self._notify("remove", key=key, priority=prio, index=i)
        self._delete_at(i)
        self._notify("done")
        return prio

    # ----------------------------------------------------------------- internals
    def _delete_at(self, i: int) -> None:
        # Swap the target with the last entry so we can pop from the end in O(1),
        # then repair the moved entry. It may need to go up OR down, because the
        # last entry is unrelated to the removed one's subtree.
        last = len(self._heap) - 1
        if i != last:
            self._swap(i, last)
        _, _, key = self._heap.pop()
        del self._pos[key]
        self._notify("detach", key=key)
        if i < len(self._heap):
            self._sift_up(i)
            self._sift_down(i)

    def _swap(self, i: int, j: int) -> None:
        # Single place where entries move, so the position map can never drift.
        h = self._heap
        h[i], h[j] = h[j], h[i]
        self._pos[h[i][2]] = i
        self._pos[h[j][2]] = j
        if self.observer is not None:
            self.observer("swap", {"i": i, "j": j})

    def _greater(self, i: int, j: int) -> bool:
        # Compare (priority, tiebreak) only; keys themselves need not be orderable.
        a, b = self._heap[i], self._heap[j]
        return (a[0], a[1]) > (b[0], b[1])

    def _sift_up(self, i: int) -> None:
        while i > 0:
            parent = (i - 1) // 2
            if self._greater(i, parent):
                self._swap(i, parent)
                i = parent
            else:
                break

    def _sift_down(self, i: int) -> None:
        n = len(self._heap)
        while True:
            left, right = 2 * i + 1, 2 * i + 2
            largest = i
            if left < n and self._greater(left, largest):
                largest = left
            if right < n and self._greater(right, largest):
                largest = right
            if largest == i:
                break
            self._swap(i, largest)
            i = largest

    def check_invariants(self) -> None:
        """Assert heap order and position-map consistency (used by tests). O(n)."""
        n = len(self._heap)
        assert len(self._pos) == n, "position map size mismatch"
        for i, (_, _, key) in enumerate(self._heap):
            assert self._pos[key] == i, f"pos[{key!r}]={self._pos[key]} but at index {i}"
            for c in (2 * i + 1, 2 * i + 2):
                if c < n:
                    assert not self._greater(c, i), f"heap order violated at {i}->{c}"
