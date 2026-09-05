from __future__ import annotations

from desk.config_load import load_config


def test_config_has_foundation_keys():
    cfg, assets = load_config()
    assert cfg["history_rows"] >= 512
    assert cfg["min_skill_n"] >= 30
    assert "risk_day_tz" in cfg
    assert any(a.symbol == "XAUUSD" for a in assets)
