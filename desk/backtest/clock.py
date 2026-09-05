from __future__ import annotations

from desk.backtest.data import Bar


class Clock:
    """Monotonic event-time clock for chronological replay."""

    def __init__(self, timestamps: list[float]) -> None:
        self.timestamps = sorted(set(timestamps))
        self.i = 0

    @property
    def t(self) -> float | None:
        if self.i < 0 or self.i >= len(self.timestamps):
            return None
        return self.timestamps[self.i]

    def __iter__(self):
        self.i = 0
        return self

    def __next__(self) -> float:
        if self.i >= len(self.timestamps):
            raise StopIteration
        t = self.timestamps[self.i]
        self.i += 1
        return t

    def bars_asof(self, series: list[Bar], t: float) -> list[Bar]:
        """Only bars with event_time <= t."""
        out: list[Bar] = []
        for b in series:
            if b.event_time > t:
                break
            out.append(b)
        return out
