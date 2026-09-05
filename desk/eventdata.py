"""Phase 8 — event-time data schema, ledger, and provider adapters."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
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
    """In-memory event-time store for backtests / tests / live ledger mirror."""

    name = "memory"

    def __init__(self) -> None:
        self._rows: list[Observation] = []

    def publish(self, obs: Observation) -> None:
        self._rows.append(obs)
        if len(self._rows) > 50_000:
            self._rows = self._rows[-40_000:]

    def fetch(self, symbol: str | None, field: str, asof: float) -> Observation | None:
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

    def asof_value(self, symbol: str | None, field: str, asof: float) -> float | str | None:
        o = self.fetch(symbol, field, asof)
        return None if o is None else o.value

    def stale_ratio(self, now: float, max_age: float = 300.0) -> float:
        if not self._rows:
            return 1.0
        recent = sum(1 for o in self._rows[-200:] if now - o.arrival_time <= max_age)
        return 1.0 - recent / min(200, len(self._rows))


def macro_asof(provider: MemoryProvider, series: str, release_asof: float) -> float | None:
    v = provider.asof_value(None, series, release_asof)
    return float(v) if v is not None else None


def news_available(provider: MemoryProvider, article_id: str, asof: float) -> bool:
    o = provider.fetch(None, f"news:{article_id}", asof)
    return o is not None


def quality_gate(observations: list[Observation], min_quality: float = 0.4) -> bool:
    if not observations:
        return False
    return all(o.quality >= min_quality for o in observations)


@dataclass
class EventLedger:
    """Live hub side-channel: every mark/news/macro row gets event + arrival time."""

    provider: MemoryProvider = field(default_factory=MemoryProvider)
    source_latency: dict[str, list[float]] = field(default_factory=dict)
    missingness: dict[str, int] = field(default_factory=dict)
    revisions: int = 0

    def record(
        self,
        *,
        symbol: str | None,
        field: str,
        value: Any,
        source: str,
        event_time: float | None = None,
        arrival_time: float | None = None,
        quality: float = 1.0,
        revision: int = 0,
    ) -> Observation:
        now = time.time()
        arr = arrival_time if arrival_time is not None else now
        evt = event_time if event_time is not None else arr
        obs = Observation(
            symbol=symbol,
            field=field,
            value=value,
            event_time=evt,
            arrival_time=arr,
            source=source,
            quality=quality,
            revision=revision,
        )
        # revision detect
        prev = self.provider.fetch(symbol, field, arr + 1e9)
        if prev is not None and prev.value != value:
            self.revisions += 1
            obs.revision = max(revision, prev.revision + 1)
        self.provider.publish(obs)
        lag = max(0.0, arr - evt)
        self.source_latency.setdefault(source, []).append(lag)
        self.source_latency[source] = self.source_latency[source][-200:]
        if value is None:
            self.missingness[source] = self.missingness.get(source, 0) + 1
        return obs

    def record_mark(self, symbol: str, price: float, source: str, event_time: float | None = None) -> None:
        # When event_time is known (replay), arrival defaults to event_time to avoid lookahead.
        self.record(
            symbol=symbol,
            field="mark",
            value=price,
            source=source,
            event_time=event_time,
            arrival_time=event_time if event_time is not None else None,
        )

    def record_news(self, item: dict[str, Any], source: str = "rss") -> None:
        title = str(item.get("title") or "")[:120]
        link = str(item.get("link") or title)
        # published_at if present, else arrival=now (unknown event time → same as arrival, flagged quality)
        pub = item.get("published_at") or item.get("published") or item.get("ts")
        try:
            event_time = float(pub) if pub is not None else None
        except Exception:
            event_time = None
        quality = 1.0 if event_time is not None else 0.7
        self.record(
            symbol=None,
            field=f"news:{hash(link) & 0xFFFFFFFF:x}",
            value=title,
            source=source,
            event_time=event_time,
            quality=quality,
        )

    def record_macro(self, series: str, value: float | None, release_time: float | None, source: str = "fred") -> None:
        self.record(
            symbol=None,
            field=series,
            value=value,
            source=source,
            event_time=release_time,
            quality=1.0 if value is not None else 0.0,
        )

    def health(self) -> dict[str, Any]:
        now = time.time()
        lat: dict[str, float] = {}
        for src, xs in self.source_latency.items():
            if xs:
                lat[src] = round(sum(xs) / len(xs), 3)
        return {
            "observations": len(self.provider._rows),
            "avg_latency_sec": lat,
            "missingness": dict(self.missingness),
            "revisions": self.revisions,
            "stale_ratio": round(self.provider.stale_ratio(now), 3),
            "degraded": self.provider.stale_ratio(now) > 0.6 or self.revisions > 100,
        }

    def asof_mark(self, symbol: str, asof: float) -> float | None:
        v = self.provider.asof_value(symbol, "mark", asof)
        return float(v) if v is not None else None
