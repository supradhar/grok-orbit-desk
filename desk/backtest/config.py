from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BacktestConfig:
    symbols: list[str]
    warmup: int = 250
    seed: int = 42
    fee_bps: float = 4.0
    slippage_bps: float = 6.0
    spread_bps: float = 2.0
    max_gross_pct: float = 0.40
    max_position_pct: float = 0.08
    max_daily_loss_pct: float = 0.02
    min_confluence: float = 14.0
    equity: float = 100_000.0
    stop_pct: float = 0.02
    rr: float = 1.8
    next_bar_only: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "warmup": self.warmup,
            "seed": self.seed,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "spread_bps": self.spread_bps,
            "max_gross_pct": self.max_gross_pct,
            "max_position_pct": self.max_position_pct,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "min_confluence": self.min_confluence,
            "equity": self.equity,
            "stop_pct": self.stop_pct,
            "rr": self.rr,
            "next_bar_only": self.next_bar_only,
        }
