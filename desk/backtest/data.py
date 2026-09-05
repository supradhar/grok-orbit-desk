from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Bar:
    ts: float  # event_time unix seconds
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def event_time(self) -> float:
        return self.ts


def _parse_ts(raw: str) -> float:
    raw = raw.strip()
    if raw.isdigit():
        v = float(raw)
        # ms vs s
        return v / 1000.0 if v > 1e12 else v
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[:19] if "T" in raw or " " in raw else raw[:10], fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    raise ValueError(f"unparseable timestamp: {raw}")


def load_csv(path: Path) -> list[Bar]:
    rows: list[Bar] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = {k.lower(): k for k in (reader.fieldnames or [])}
        def col(*names: str) -> str:
            for n in names:
                if n in fields:
                    return fields[n]
            raise KeyError(names)

        ts_k = col("ts", "timestamp", "time", "date", "datetime")
        o_k = col("open", "o")
        h_k = col("high", "h")
        l_k = col("low", "l")
        c_k = col("close", "c", "price")
        v_k = fields.get("volume") or fields.get("vol") or fields.get("v")
        for row in reader:
            try:
                bar = Bar(
                    ts=_parse_ts(row[ts_k]),
                    open=float(row[o_k]),
                    high=float(row[h_k]),
                    low=float(row[l_k]),
                    close=float(row[c_k]),
                    volume=float(row[v_k]) if v_k else 0.0,
                )
            except Exception:
                continue
            if bar.close <= 0 or bar.high < bar.low:
                continue
            rows.append(bar)
    rows.sort(key=lambda b: b.ts)
    # drop duplicate timestamps (keep last)
    dedup: dict[float, Bar] = {}
    for b in rows:
        dedup[b.ts] = b
    return [dedup[k] for k in sorted(dedup)]


def load_universe(data_dir: Path, symbols: list[str]) -> dict[str, list[Bar]]:
    out: dict[str, list[Bar]] = {}
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            # try lowercase
            path = data_dir / f"{sym.lower()}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing OHLCV for {sym}: expected {data_dir / (sym + '.csv')}")
        out[sym] = load_csv(path)
    return out


def filter_range(bars: list[Bar], start: float | None, end: float | None) -> list[Bar]:
    out = bars
    if start is not None:
        out = [b for b in out if b.ts >= start]
    if end is not None:
        out = [b for b in out if b.ts <= end]
    return out


def date_to_ts(s: str | None) -> float | None:
    if not s:
        return None
    dt = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp()


def write_synthetic_fixture(path: Path, symbol: str = "BTC", n: int = 600, seed: int = 42) -> Path:
    """Deterministic synthetic OHLCV for tests / smoke runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = seed
    px = 100.0 if symbol != "XAUUSD" else 2000.0
    start = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for i in range(n):
            rng = (1103515245 * rng + 12345) & 0x7FFFFFFF
            shock = ((rng % 1000) - 500) / 100000.0
            # mild trend + noise
            shock += 0.00015 if (i // 40) % 2 == 0 else -0.0001
            o = px
            c = max(0.01, px * (1 + shock))
            h = max(o, c) * (1 + abs(shock) * 0.5)
            l = min(o, c) * (1 - abs(shock) * 0.5)
            vol = 1000 + (rng % 500)
            w.writerow([int(start + i * 3600), f"{o:.6f}", f"{h:.6f}", f"{l:.6f}", f"{c:.6f}", vol])
            px = c
    return path


def as_dicts(bars: list[Bar]) -> list[dict[str, Any]]:
    return [
        {"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
        for b in bars
    ]
