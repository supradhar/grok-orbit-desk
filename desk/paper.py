from __future__ import annotations

from desk.models import DecisionMemo, Fill, Position
from desk.scoring import utc_now


class PaperBroker:
    def __init__(self, equity: float, slippage_bps: float, max_gross_pct: float, fee_bps: float = 4.0) -> None:
        self.starting = equity
        self.cash = equity
        self.slippage_bps = slippage_bps
        self.fee_bps = fee_bps
        self.max_gross_pct = max_gross_pct
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.marks: dict[str, float] = {}
        self.halted = False

    def mark(self, marks: dict[str, float]) -> None:
        self.marks.update(marks)
        for pos in self.positions.values():
            if pos.symbol in self.marks:
                pos.mark = self.marks[pos.symbol]

    @property
    def unrealized(self) -> float:
        return sum(p.pnl for p in self.positions.values())

    @property
    def equity(self) -> float:
        total = self.cash
        for pos in self.positions.values():
            mark = pos.mark or pos.avg_price
            if pos.side == "long":
                total += pos.qty * mark
            else:
                total += pos.qty * pos.avg_price + pos.pnl
        return total

    @property
    def gross(self) -> float:
        return sum(p.notional for p in self.positions.values())

    def approve(self, memo: DecisionMemo) -> str:
        if self.halted:
            memo.status = "rejected"
            return "desk halted — daily loss cap"
        if memo.status != "pending":
            return f"memo already {memo.status}"
        px = self.marks.get(memo.symbol) or memo.entry
        if not px:
            return "no mark"
        slip = self.slippage_bps / 1e4
        fee = self.fee_bps / 1e4
        fill_px = px * (1 + slip) if memo.side == "long" else px * (1 - slip)
        qty = memo.size_usd / fill_px
        notional = qty * fill_px
        cost = notional * fee
        if self.gross + notional > self.equity * self.max_gross_pct:
            memo.status = "rejected"
            return "gross exposure cap"
        if notional + cost > self.cash:
            memo.status = "rejected"
            return "insufficient buying power"
        existing = self.positions.get(memo.symbol)
        if existing and existing.side != memo.side:
            memo.status = "rejected"
            return "would flip an open position — close first"
        self.cash -= notional + cost
        if existing and existing.side == memo.side:
            total = existing.qty + qty
            existing.avg_price = (existing.avg_price * existing.qty + fill_px * qty) / total
            existing.qty = total
            existing.mark = fill_px
            existing.stop = memo.stop or existing.stop
            existing.target = memo.target or existing.target
        else:
            self.positions[memo.symbol] = Position(
                symbol=memo.symbol,
                side=memo.side,
                qty=qty,
                avg_price=fill_px,
                mark=fill_px,
                stop=memo.stop,
                target=memo.target,
            )
        memo.status = "approved"
        self.fills.append(
            Fill(idea_id=memo.id, symbol=memo.symbol, side=memo.side, qty=qty, price=fill_px, ts=utc_now())
        )
        return "filled"

    def reject(self, memo: DecisionMemo) -> str:
        if memo.status != "pending":
            return f"memo already {memo.status}"
        memo.status = "rejected"
        return "rejected"

    def close(self, symbol: str) -> str:
        pos = self.positions.get(symbol)
        if not pos:
            return "no position"
        mark = self.marks.get(symbol) or pos.mark or pos.avg_price
        pos.mark = mark
        fee = (pos.qty * mark) * (self.fee_bps / 1e4)
        if pos.side == "long":
            self.cash += pos.qty * mark - fee
        else:
            self.cash += pos.qty * pos.avg_price + pos.pnl - fee
        del self.positions[symbol]
        self.fills.append(
            Fill(idea_id=f"close-{symbol}", symbol=symbol, side=pos.side, qty=pos.qty, price=mark, ts=utc_now())
        )
        return "closed"

    def snapshot_positions(self) -> list[dict]:
        return [p.as_dict() for p in self.positions.values()]
