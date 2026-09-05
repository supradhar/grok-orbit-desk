from __future__ import annotations

from desk.portfolio_risk import cvar, optimize_weights, portfolio_variance, risk_snapshot, vol_target_weight


def test_vol_target():
    assert vol_target_weight(0.01, 0.02, cap=1.0) == 0.5
    assert vol_target_weight(0.01, 0.001, cap=0.2) == 0.2


def test_cvar():
    rets = [0.01, -0.02, -0.05, 0.0, -0.01, 0.02, -0.03, 0.01, -0.04, 0.0]
    v = cvar(rets, 0.2)
    assert v is not None and v > 0


def test_optimize_and_risk():
    series = {
        "BTC": [0.01, -0.005, 0.002, 0.003, -0.001, 0.004, -0.002, 0.001, 0.0, -0.003],
        "ETH": [0.012, -0.006, 0.001, 0.004, -0.002, 0.005, -0.003, 0.002, -0.001, -0.004],
    }
    w = optimize_weights({"BTC": 0.02, "ETH": 0.01}, series, steps=20)
    assert "BTC" in w
    snap = risk_snapshot({"BTC": 10000, "ETH": 5000}, {"BTC": [100 + i for i in range(20)], "ETH": [50 + i * 0.5 for i in range(20)]})
    assert "portfolio_vol" in snap
