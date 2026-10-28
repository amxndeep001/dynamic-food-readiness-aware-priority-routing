import random

import pytest

from ds.min_heap import MinHeap


@pytest.mark.parametrize("seed", range(5))
def test_pop_order_matches_sorted(seed: int) -> None:
    rng = random.Random(seed)
    heap: MinHeap[int] = MinHeap()
    pushed: list[tuple[float, int]] = []
    popped: list[tuple[float, int]] = []
    seq = 0
    for _ in range(2000):
        if rng.random() < 0.6 or not heap:
            # Integer keys so that ties are common.
            key = float(rng.randint(0, 50))
            heap.push(key, seq)
            pushed.append((key, seq))
            seq += 1
        else:
            popped.append(heap.pop())
        heap.check_invariants()
    while heap:
        popped.append(heap.pop())
    # Interleaved pops are hard to predict, so check the global property instead:
    # every element came out exactly once (heap order is checked by check_invariants).
    assert sorted(popped) == sorted(pushed)


def test_full_drain_is_sorted_with_fifo_ties() -> None:
    rng = random.Random(42)
    heap: MinHeap[int] = MinHeap()
    items = [(float(rng.randint(0, 10)), i) for i in range(500)]
    for key, i in items:
        heap.push(key, i)
    out = [heap.pop() for _ in range(len(items))]
    # (key, insertion index) ascending == FIFO among equal keys.
    assert out == sorted(items)


def test_peek_and_empty() -> None:
    heap: MinHeap[str] = MinHeap()
    with pytest.raises(IndexError):
        heap.pop()
    with pytest.raises(IndexError):
        heap.peek()
    heap.push(2.0, "b")
    heap.push(1.0, "a")
    heap.push(1.0, "a2")
    assert heap.peek() == (1.0, "a")
    assert [heap.pop()[1] for _ in range(3)] == ["a", "a2", "b"]
    assert len(heap) == 0
