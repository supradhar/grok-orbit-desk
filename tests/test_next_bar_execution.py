from __future__ import annotations

from desk.backtest.config import BacktestConfig
from desk.backtest.data import write_synthetic_fixture, load_csv
from desk.backtest.execution import market_fill, Order
from desk.backtest.validation import assert_next_bar


def test_next_bar_execution_semantics():
    order = Order("BTC", "long", 1000, signal_ts=100.0, reason="t")
    fill = market_fill(order, mid=50.0, fill_ts=200.0, fee_bps=4, slippage_bps=6, spread_bps=2)
    assert fill is not None
    assert_next_bar(order.signal_ts, fill.ts)
    assert fill.price > 50.0  # long pays


def test_fixture_bars_sorted(tmp_path):
    p = tmp_path / "ETH.csv"
    write_synthetic_fixture(p, "ETH", n=20, seed=1)
    bars = load_csv(p)
    assert all(bars[i].ts <= bars[i + 1].ts for i in range(len(bars) - 1))
