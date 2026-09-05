from __future__ import annotations

from typing import Any

from desk.backtest.data import Bar


def validate_bars(symbol: str, bars: list[Bar]) -> list[str]:
    errs: list[str] = []
    if not bars:
        errs.append(f"{symbol}: empty")
        return errs
    prev = None
    for i, b in enumerate(bars):
        if b.close <= 0 or b.open <= 0:
            errs.append(f"{symbol}[{i}]: non-positive price")
        if b.high < b.low:
            errs.append(f"{symbol}[{i}]: high < low")
        if b.high < max(b.open, b.close) or b.low > min(b.open, b.close):
            errs.append(f"{symbol}[{i}]: OHLC inconsistent")
        if prev is not None and b.ts < prev:
            errs.append(f"{symbol}[{i}]: out of order timestamp")
        if prev is not None and b.ts == prev:
            errs.append(f"{symbol}[{i}]: duplicate timestamp")
        prev = b.ts
    return errs


def validate_universe(universe: dict[str, list[Bar]]) -> None:
    errs: list[str] = []
    for sym, bars in universe.items():
        errs.extend(validate_bars(sym, bars))
    if errs:
        raise ValueError("data validation failed:\n" + "\n".join(errs[:40]))


def assert_no_lookahead(feature_ts: float, bar_ts: float) -> None:
    if bar_ts > feature_ts:
        raise AssertionError(f"lookahead: used bar {bar_ts} after feature time {feature_ts}")


def assert_next_bar(signal_ts: float, fill_ts: float) -> None:
    if fill_ts <= signal_ts:
        raise AssertionError(f"same-bar fill forbidden: signal={signal_ts} fill={fill_ts}")
