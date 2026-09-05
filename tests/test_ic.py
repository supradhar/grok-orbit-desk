from __future__ import annotations

from desk.ic import CORE, blend_weights, factor_corr_matrix, factor_ics, recent_factor_series


def test_ic_and_shrink_dampen():
    hist = {
        "BTC": [
            {
                "ts": 1000.0 + i * 60,
                "mark": 100 + i * 0.2,
                "factors": {f: float((i % 5) - 2) * 10 for f in CORE},
            }
            for i in range(40)
        ]
    }
    ics = factor_ics(hist, horizon_sec=120)
    assert "momentum" in ics
    series = recent_factor_series(hist)
    w = blend_weights(ics, factor_series=series)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    mat = factor_corr_matrix(hist)
    assert mat["momentum"]["momentum"] == 1.0
