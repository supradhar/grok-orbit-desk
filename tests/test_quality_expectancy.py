from __future__ import annotations

from desk.quality import skill_ok, skill_map


def test_expectancy_in_skill_map():
    hist = {
        "BTC": [
            {"ts": 1000.0 + i * 60, "mark": 100 + i, "residual": 20.0, "beta_ok": True}
            for i in range(40)
        ]
    }
    # upward marks with positive residual → hits
    sm = skill_map(hist, min_score=8.0, horizon_sec=120)
    row = sm["BTC"]
    assert row["n"] > 0
    assert row.get("expectancy") is not None
    assert row.get("hit_rate") is not None


def test_skill_ok_requires_sample():
    assert skill_ok({"n": 5, "hit_rate": 0.9, "expectancy": 0.01}, min_skill_n=30) is False
    assert skill_ok({"n": 30, "hit_rate": 0.55, "expectancy": -0.01}, min_skill=0.48, min_skill_n=30) is True
    assert skill_ok({"n": 30, "hit_rate": 0.2, "expectancy": 0.001}, min_skill=0.48, min_skill_n=30) is True
    assert skill_ok({"n": 30, "hit_rate": 0.2, "expectancy": -0.01}, min_skill=0.48, min_skill_n=30) is False
