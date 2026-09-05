from __future__ import annotations

from desk.factors import ablation_study, agent_attribution, normalize_factor_cross_section, winsorize


def test_normalize_z():
    raw = {"BTC": 10.0, "ETH": 12.0, "SOL": 8.0, "XRP": 11.0}
    out = normalize_factor_cross_section(raw)
    assert "BTC" in out
    assert "z" in out["BTC"]


def test_winsorize():
    xs = list(range(100))
    w = winsorize([float(x) for x in xs], 0.05)
    assert min(w) >= 4
    assert max(w) <= 95


def test_attribution_empty():
    rows = agent_attribution({})
    assert all(r["signal_count"] == 0 for r in rows)


def test_ablation_small_history():
    hist = {
        "BTC": [
            {
                "ts": 1000.0 + i * 60,
                "mark": 100 + i * 0.1,
                "factors": {"momentum": 20.0 if i % 2 == 0 else -10.0, "volume": 5.0},
            }
            for i in range(30)
        ]
    }
    out = ablation_study(hist, horizon_sec=120, min_blend=1.0)
    assert "baseline" in out
    assert "remove_one" in out
