from __future__ import annotations

from desk.factors import agent_attribution


def test_factor_correlation_attribution_has_calibration():
    from desk.ic import CORE

    hist = {
        "BTC": [
            {
                "ts": 1000.0 + i * 60,
                "mark": 100 + i * 0.1,
                "regime": "expansion" if i % 2 == 0 else "compression",
                "factors": {f: 20.0 if i % 2 == 0 else -15.0 for f in CORE},
            }
            for i in range(40)
        ]
    }
    rows = agent_attribution(hist, horizon_sec=120, min_score=5)
    assert rows
    assert "calibration_ece" in rows[0]
    assert "regime_performance" in rows[0]
