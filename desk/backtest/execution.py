from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Order:
    symbol: str
    side: str  # long | short | close
    size_usd: float
    signal_ts: float
    reason: str = ""


@dataclass
class FillEvent:
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    ts: float
    reason: str


def fill_price(
    side: str,
    mid: float,
    *,
    slippage_bps: float,
    spread_bps: float,
) -> float:
    """Adverse fill: pay half-spread + slippage."""
    half = spread_bps / 2e4
    slip = slippage_bps / 1e4
    if side == "long":
        return mid * (1 + half + slip)
    if side == "short":
        return mid * (1 - half - slip)
    # close uses mid adverse depending on position — caller passes close side as long/short exit
    return mid


def market_fill(
    order: Order,
    mid: float,
    fill_ts: float,
    *,
    fee_bps: float,
    slippage_bps: float,
    spread_bps: float,
) -> FillEvent | None:
    if mid <= 0 or order.size_usd <= 0:
        return None
    side = order.side
    if side == "close":
        # close treated as exiting long by default; portfolio will pass correct side
        px = mid * (1 - spread_bps / 2e4 - slippage_bps / 1e4)
        qty = order.size_usd / px
        fee = qty * px * (fee_bps / 1e4)
        return FillEvent(order.symbol, "close", qty, px, fee, fill_ts, order.reason)
    px = fill_price(side, mid, slippage_bps=slippage_bps, spread_bps=spread_bps)
    qty = order.size_usd / px
    fee = qty * px * (fee_bps / 1e4)
    return FillEvent(order.symbol, side, qty, px, fee, fill_ts, order.reason)


def stop_hit(side: str, stop: float, bar_low: float, bar_high: float) -> float | None:
    """Gap-aware: if stop breached, return fill at stop or worse gap price."""
    if not stop:
        return None
    if side == "long" and bar_low <= stop:
        return min(stop, bar_open_or(bar_low, stop))
    if side == "short" and bar_high >= stop:
        return max(stop, bar_open_or(bar_high, stop))
    return None


def bar_open_or(extreme: float, stop: float) -> float:
    return extreme
