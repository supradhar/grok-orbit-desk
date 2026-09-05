from __future__ import annotations

from desk.ab_study import run_abc_study
from desk.portfolio_risk import stress_shocks


def test_abc_study(tmp_path):
    out = run_abc_study(tmp_path / "ohlcv", symbols=["BTC", "ETH"], warmup=40)
    assert "A" in out["runs"] and "B" in out["runs"] and "C" in out["runs"]
    assert "comparison" in out
    assert "systems" in out["comparison"]


def test_stress_shocks():
    s = stress_shocks({"BTC": 0.5, "ETH": 0.5})
    assert "crypto_crash" in s
    assert s["crypto_crash"] < 0
