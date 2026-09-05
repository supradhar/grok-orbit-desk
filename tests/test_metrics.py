from __future__ import annotations

from desk.backtest.metrics import max_drawdown, sharpe, summarize, trade_stats
from desk.backtest.execution import FillEvent


def test_metrics_basic():
    eq = [{"ts": i, "equity": 100_000 * (1 + 0.001 * i), "turnover": 0, "fees": 0} for i in range(50)]
    m = summarize(eq, [], 100_000, periods_per_year=24 * 365)
    assert m["end_equity"] > 100_000
    assert m["total_return"] > 0
    dd, _, _ = max_drawdown([100, 110, 90, 95])
    assert dd > 0.1
    fills = [
        FillEvent("BTC", "long", 1, 100, 0.1, 1, "o"),
        FillEvent("BTC", "close", 1, 110, 0.1, 2, "c"),
    ]
    ts = trade_stats(fills)
    assert ts["n_trades"] == 1
    assert ts["total_pnl"] > 0
    assert sharpe([0.01, -0.005, 0.002, 0.003]) is not None
