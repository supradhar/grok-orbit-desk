from __future__ import annotations

from desk.llm_study import compare_study_runs, evidence_packet, validate_llm_json


def test_validate_rejects_fabricated_mark():
    packet = evidence_packet(symbol="BTC", factors={"momentum": 10}, mark=100.0, regime="expansion", blend=12.0, trust=0.8)
    out = validate_llm_json('{"direction":"LONG","confidence":0.9,"mark":999,"thesis":"x"}', packet)
    assert out["direction"] == "NO_TRADE"


def test_validate_ok():
    packet = evidence_packet(symbol="BTC", factors={}, mark=100.0, regime=None, blend=5.0, trust=0.5)
    out = validate_llm_json({"direction": "short", "confidence": 0.6, "thesis": "weak"}, packet)
    assert out["direction"] == "SHORT"
    assert out["confidence"] == 0.6


def test_compare_study():
    runs = {
        "A": {"sharpe": 0.5, "total_return": 0.1, "max_drawdown": 0.05, "expectancy": 0.01, "n_trades": 10, "win_rate": 0.5},
        "B": {"sharpe": 0.6, "total_return": 0.12, "max_drawdown": 0.06, "expectancy": 0.012, "n_trades": 12, "win_rate": 0.55},
    }
    cmp = compare_study_runs(runs)
    assert "B_minus_A" in cmp["deltas"]
