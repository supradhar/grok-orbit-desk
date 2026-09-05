"""Phase 15 — live broker interface (paper-compatible semantics; no real money)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from desk.models import DecisionMemo
from desk.paper import PaperBroker
from desk.scoring import utc_now


@dataclass
class BrokerOrder:
    symbol: str
    side: str
    size_usd: float
    client_id: str
    ts: float


@dataclass
class BrokerFill:
    client_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    ts: float


class Broker(Protocol):
    name: str
    environment: str  # research | paper | simulation | live

    def submit(self, order: BrokerOrder) -> str: ...
    def cancel(self, client_id: str) -> bool: ...
    def positions(self) -> dict[str, Any]: ...
    def kill_switch(self) -> None: ...


class PaperBrokerAdapter:
    """Wraps PaperBroker with the same order semantics as a future live adapter."""

    name = "paper"
    environment = "paper"

    def __init__(self, paper: PaperBroker) -> None:
        self.paper = paper
        self._killed = False
        self._orders: dict[str, BrokerOrder] = {}

    def submit(self, order: BrokerOrder) -> str:
        if self._killed or self.paper.halted:
            return "rejected:kill_or_halt"
        self._orders[order.client_id] = order
        memo = DecisionMemo(
            id=order.client_id,
            symbol=order.symbol,
            side=order.side,  # type: ignore[arg-type]
            conviction=0.5,
            size_usd=order.size_usd,
            entry=self.paper.marks.get(order.symbol) or 0.0,
            stop=0.0,
            target=0.0,
            thesis="broker adapter",
            invalidation="",
            factors=[],
            risk_notes=[],
            status="pending",
            ts=order.ts or utc_now(),
        )
        return self.paper.approve(memo)

    def cancel(self, client_id: str) -> bool:
        return self._orders.pop(client_id, None) is not None

    def positions(self) -> dict[str, Any]:
        return {s: p.as_dict() for s, p in self.paper.positions.items()}

    def kill_switch(self) -> None:
        self._killed = True
        self.paper.halted = True
        self.paper.halt_reason = "kill_switch"
        self.paper.halt_timestamp = utc_now()
        for sym in list(self.paper.positions):
            self.paper.close(sym)


class LiveBrokerStub:
    """
    Live path is intentionally disabled until OOS paper validation + ops review.
    Submitting raises — research code must not accidentally route here.
    """

    name = "live_stub"
    environment = "live"

    def submit(self, order: BrokerOrder) -> str:
        raise RuntimeError("Live execution disabled until Phase 15 promotion gate passes")

    def cancel(self, client_id: str) -> bool:
        return False

    def positions(self) -> dict[str, Any]:
        return {}

    def kill_switch(self) -> None:
        return None
