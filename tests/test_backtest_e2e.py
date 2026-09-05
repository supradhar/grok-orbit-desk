from __future__ import annotations

from desk.backtest.runner import run_backtest
from desk.config_load import ROOT


def test_backtest_fixture_e2e(tmp_path):
    data = tmp_path / "ohlcv"
    out = tmp_path / "run"
    result = run_backtest(
        symbols=["BTC", "ETH"],
        data_dir=data,
        warmup=50,
        seed=7,
        walkforward=False,
        out_dir=out,
    )
    assert (out / "metrics.json").exists()
    assert (out / "equity.csv").exists()
    assert "total_return" in result["metrics"] or "error" in result["metrics"]
