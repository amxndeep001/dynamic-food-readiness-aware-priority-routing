"""IndexedMaxHeap is checked against a heapq-based reference model.

The reference uses lazy deletion: every push/update adds a fresh heapq entry and
stale entries are skipped on pop. Its ordering key is ``(-priority, seq)`` where
``seq`` is the original insertion counter, i.e. exactly the tie-break rule the
indexed heap promises (higher priority first, then older key first).
"""

import heapq
import random

import pytest

from ds.indexed_heap import IndexedMaxHeap


class ReferenceMaxHeap:
    def __init__(self) -> None:
        self.h: list[tuple[float, int, int]] = []
        self.current: dict[int, tuple[float, int]] = {}
        self.seq = 0

    def push(self, key: int, prio: float) -> None:
        self.seq += 1
        self.current[key] = (prio, self.seq)
        heapq.heappush(self.h, (-prio, self.seq, key))

    def update(self, key: int, prio: float) -> None:
        _, seq = self.current[key]
        self.current[key] = (prio, seq)
        heapq.heappush(self.h, (-prio, seq, key))

    def remove(self, key: int) -> None:
        del self.current[key]

    def _clean(self) -> None:
        while self.h:
            negp, seq, key = self.h[0]
            if self.current.get(key) == (-negp, seq):
                return
            heapq.heappop(self.h)

    def peek(self) -> tuple[int, float]:
        self._clean()
        negp, _, key = self.h[0]
        return key, -negp

    def pop(self) -> tuple[int, float]:
        self._clean()
        negp, _, key = heapq.heappop(self.h)
        del self.current[key]
        return key, -negp


@pytest.mark.parametrize("seed", range(8))
def test_random_operations_match_heapq(seed: int) -> None:
    rng = random.Random(seed)
    heap: IndexedMaxHeap[int] = IndexedMaxHeap()
    ref = ReferenceMaxHeap()
    next_key = 0
    # Small integer priorities on some seeds force many ties.
    prio = (lambda: float(rng.randint(0, 5))) if seed % 2 else (lambda: rng.random())

    for _ in range(2000):
        op = rng.random()
        if op < 0.35 or not ref.current:
            p = prio()
            heap.push(next_key, p)
            ref.push(next_key, p)
            next_key += 1
        elif op < 0.55:
            assert heap.pop_max() == ref.pop()
        elif op < 0.80:
            key = rng.choice(list(ref.current))
            p = prio()
            heap.update_key(key, p)
            ref.update(key, p)
        elif op < 0.92:
            key = rng.choice(list(ref.current))
            assert heap.remove(key) == ref.current[key][0]
            ref.remove(key)
        else:
            assert heap.peek() == ref.peek()

        heap.check_invariants()
        assert len(heap) == len(ref.current)
        for key in ref.current:
            assert key in heap
            assert heap.priority(key) == ref.current[key][0]

    # Drain: full pop order must match.
    while ref.current:
        assert heap.pop_max() == ref.pop()
        heap.check_invariants()
    assert len(heap) == 0


def test_empty_heap_errors() -> None:
    heap: IndexedMaxHeap[str] = IndexedMaxHeap()
    with pytest.raises(IndexError):
        heap.pop_max()
    with pytest.raises(IndexError):
        heap.peek()


def test_missing_and_duplicate_keys() -> None:
    heap: IndexedMaxHeap[str] = IndexedMaxHeap()
    heap.push("a", 1.0)
    with pytest.raises(KeyError):
        heap.push("a", 2.0)
    with pytest.raises(KeyError):
        heap.update_key("zzz", 1.0)
    with pytest.raises(KeyError):
        heap.remove("zzz")
    assert not heap.contains("zzz")


def test_ties_pop_in_insertion_order() -> None:
    heap: IndexedMaxHeap[str] = IndexedMaxHeap()
    for k in "abcde":
        heap.push(k, 1.0)
    # Refreshing a key's score to the same value must not change its age.
    heap.update_key("a", 1.0)
    assert [heap.pop_max()[0] for _ in range(5)] == list("abcde")


def test_single_element_and_remove_last() -> None:
    heap: IndexedMaxHeap[int] = IndexedMaxHeap()
    heap.push(7, 3.0)
    assert heap.peek() == (7, 3.0)
    heap.update_key(7, -1.0)
    assert heap.peek() == (7, -1.0)
    assert heap.remove(7) == -1.0
    assert len(heap) == 0 and 7 not in heap
    heap.check_invariants()


def test_update_key_moves_both_directions() -> None:
    heap: IndexedMaxHeap[int] = IndexedMaxHeap()
    for k in range(10):
        heap.push(k, float(k))
    heap.update_key(0, 100.0)  # bottom -> top
    assert heap.peek() == (0, 100.0)
    heap.update_key(0, -100.0)  # top -> bottom
    assert heap.peek() == (9, 9.0)
    heap.check_invariants()
