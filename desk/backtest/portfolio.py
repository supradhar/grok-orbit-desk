from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from desk.backtest.execution import FillEvent, Order, market_fill, stop_hit


@dataclass
class Position:
    symbol: str
    side: str
    qty: float
    avg_price: float
    stop: float = 0.0
    target: float = 0.0
    entry_ts: float = 0.0


@dataclass
class Portfolio:
    cash: float
    starting: float
    fee_bps: float
    slippage_bps: float
    spread_bps: float
    max_gross_pct: float
    max_position_pct: float
    max_daily_loss_pct: float
    positions: dict[str, Position] = field(default_factory=dict)
    fills: list[FillEvent] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    day_start_equity: float = 0.0
    day_key: str = ""
    halted: bool = False
    fees_paid: float = 0.0
    turnover: float = 0.0

    def __post_init__(self) -> None:
        if not self.day_start_equity:
            self.day_start_equity = self.cash

    def equity(self, marks: dict[str, float]) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            m = marks.get(sym, pos.avg_price)
            if pos.side == "long":
                total += pos.qty * m
            else:
                total += pos.qty * pos.avg_price + pos.qty * (pos.avg_price - m)
        return total

    def gross(self, marks: dict[str, float]) -> float:
        g = 0.0
        for sym, pos in self.positions.items():
            m = marks.get(sym, pos.avg_price)
            g += abs(pos.qty * m)
        return g

    def sync_day(self, ts: float, marks: dict[str, float]) -> None:
        from datetime import datetime, timezone

        key = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        if key != self.day_key:
            self.day_key = key
            self.day_start_equity = self.equity(marks)
            self.halted = False

    def check_halt(self, marks: dict[str, float]) -> None:
        if self.day_start_equity <= 0:
            return
        dd = (self.day_start_equity - self.equity(marks)) / self.day_start_equity
        if dd >= self.max_daily_loss_pct:
            self.halted = True

    def mark_to_market(self, ts: float, marks: dict[str, float]) -> None:
        self.sync_day(ts, marks)
        self.check_halt(marks)
        self.equity_curve.append(
            {
                "ts": ts,
                "equity": self.equity(marks),
                "cash": self.cash,
                "gross": self.gross(marks),
                "halted": self.halted,
                "fees": self.fees_paid,
                "turnover": self.turnover,
                "n_pos": len(self.positions),
            }
        )

    def apply_stops(self, ts: float, bars: dict[str, Any], marks: dict[str, float]) -> list[FillEvent]:
        out: list[FillEvent] = []
        for sym, pos in list(self.positions.items()):
            bar = bars.get(sym)
            if not bar:
                continue
            hit = stop_hit(pos.side, pos.stop, bar.low, bar.high)
            tgt = None
            if pos.target:
                if pos.side == "long" and bar.high >= pos.target:
                    tgt = pos.target
                elif pos.side == "short" and bar.low <= pos.target:
                    tgt = pos.target
            px = hit or tgt
            if px is None:
                continue
            fill = self._close(sym, px, ts, reason="stop" if hit else "target")
            if fill:
                out.append(fill)
        return out

    def submit(self, order: Order, fill_ts: float, mid: float, marks: dict[str, float]) -> FillEvent | None:
        if self.halted:
            return None
        if order.side == "close":
            pos = self.positions.get(order.symbol)
            if not pos:
                return None
            return self._close(order.symbol, mid, fill_ts, reason=order.reason or "close")

        eq = self.equity(marks)
        size = min(order.size_usd, eq * self.max_position_pct)
        if size <= 0:
            return None
        order = Order(order.symbol, order.side, size, order.signal_ts, order.reason)
        fill = market_fill(
            order,
            mid,
            fill_ts,
            fee_bps=self.fee_bps,
            slippage_bps=self.slippage_bps,
            spread_bps=self.spread_bps,
        )
        if not fill:
            return None
        notional = fill.qty * fill.price
        if self.gross(marks) + notional > eq * self.max_gross_pct:
            return None
        if notional + fill.fee > self.cash:
            return None
        self.cash -= notional + fill.fee
        self.fees_paid += fill.fee
        self.turnover += notional
        existing = self.positions.get(order.symbol)
        if existing and existing.side != order.side:
            return None
        if existing and existing.side == order.side:
            total = existing.qty + fill.qty
            existing.avg_price = (existing.avg_price * existing.qty + fill.price * fill.qty) / total
            existing.qty = total
        else:
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                side=order.side,
                qty=fill.qty,
                avg_price=fill.price,
                entry_ts=fill_ts,
            )
        self.fills.append(fill)
        return fill

    def _close(self, symbol: str, mid: float, ts: float, reason: str) -> FillEvent | None:
        pos = self.positions.get(symbol)
        if not pos:
            return None
        # exit adverse to position
        half = self.spread_bps / 2e4
        slip = self.slippage_bps / 1e4
        if pos.side == "long":
            px = mid * (1 - half - slip)
            proceeds = pos.qty * px
        else:
            px = mid * (1 + half + slip)
            proceeds = pos.qty * pos.avg_price + pos.qty * (pos.avg_price - px)
        fee = pos.qty * px * (self.fee_bps / 1e4)
        self.cash += proceeds - fee
        self.fees_paid += fee
        self.turnover += pos.qty * px
        fill = FillEvent(symbol, "close", pos.qty, px, fee, ts, reason)
        self.fills.append(fill)
        del self.positions[symbol]
        return fill

    def set_stops(self, symbol: str, stop: float, target: float) -> None:
        pos = self.positions.get(symbol)
        if pos:
            pos.stop = stop
            pos.target = target
