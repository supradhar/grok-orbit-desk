from __future__ import annotations

from typing import Iterator

from desk.backtest.clock import Clock
from desk.backtest.data import Bar


def align_timestamps(universe: dict[str, list[Bar]]) -> list[float]:
    # Intersection of timestamps so every symbol has a bar (strict).
    sets = [set(b.ts for b in bars) for bars in universe.values()]
    if not sets:
        return []
    common = set.intersection(*sets) if len(sets) > 1 else sets[0]
    return sorted(common)


def replay(universe: dict[str, list[Bar]]) -> Iterator[tuple[float, dict[str, list[Bar]]]]:
    """Yield (t, {sym: bars_asof_t}) chronologically with no lookahead."""
    stamps = align_timestamps(universe)
    clock = Clock(stamps)
    for t in clock:
        snap = {sym: clock.bars_asof(bars, t) for sym, bars in universe.items()}
        yield t, snap
