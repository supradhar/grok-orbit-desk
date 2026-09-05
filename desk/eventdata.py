"""Phase 8 — event-time data schema and provider adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass
class Observation:
    symbol: str | None
    field: str
    value: float | str | None
    event_time: float  # when the fact became true in the world
    arrival_time: float  # when we ingested it
    source: str
    quality: float = 1.0
    revision: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class Provider(Protocol):
    name: str

    def fetch(self, symbol: str, field: str, asof: float) -> Observation | None: ...


class MemoryProvider:
    """In-memory event-time store for backtests / tests."""

    name = "memory"

    def __init__(self) -> None:
        self._rows: list[Observation] = []

    def publish(self, obs: Observation) -> None:
        self._rows.append(obs)

    def fetch(self, symbol: str, field: str, asof: float) -> Observation | None:
        """Latest observation with arrival_time <= asof (no lookahead on ingestion)."""
        hit: Observation | None = None
        for o in self._rows:
            if o.field != field:
                continue
            if symbol and o.symbol and o.symbol != symbol:
                continue
            if o.arrival_time > asof:
                continue
            if hit is None or o.arrival_time > hit.arrival_time or (
                o.arrival_time == hit.arrival_time and o.revision > hit.revision
            ):
                hit = o
        return hit

    def asof_value(self, symbol: str, field: str, asof: float) -> float | str | None:
        o = self.fetch(symbol, field, asof)
        return None if o is None else o.value


def macro_asof(provider: MemoryProvider, series: str, release_asof: float) -> float | None:
    """Macro must use value known at historical release/arrival time, not revised final."""
    v = provider.asof_value(None, series, release_asof)
    return float(v) if v is not None else None


def news_available(provider: MemoryProvider, article_id: str, asof: float) -> bool:
    o = provider.fetch(None, f"news:{article_id}", asof)
    return o is not None


def quality_gate(observations: list[Observation], min_quality: float = 0.4) -> bool:
    if not observations:
        return False
    return all(o.quality >= min_quality for o in observations)
