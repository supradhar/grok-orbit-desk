from __future__ import annotations

from desk.broker import LiveBrokerStub, PaperBrokerAdapter, BrokerOrder
from desk.observability import redact_secrets
from desk.paper import PaperBroker
from desk.promotion import evaluate_promotion
from desk.scoring import utc_now


def test_paper_adapter_and_kill():
    paper = PaperBroker(100_000, 6, 0.5, 4)
    paper.marks["BTC"] = 100.0
    br = PaperBrokerAdapter(paper)
    msg = br.submit(BrokerOrder("BTC", "long", 5000, "o1", utc_now()))
    assert msg == "filled"
    br.kill_switch()
    assert paper.halted is True
    assert not paper.positions


def test_live_stub_blocked():
    stub = LiveBrokerStub()
    try:
        stub.submit(BrokerOrder("BTC", "long", 1, "x", utc_now()))
        assert False
    except RuntimeError:
        pass


def test_redact_secrets():
    out = redact_secrets({"api_key": "secret", "fee_bps": 4, "nested": {"token": "x"}})
    assert out["api_key"] == "***"
    assert out["nested"]["token"] == "***"
    assert out["fee_bps"] == 4


def test_promotion_gate():
    bad = evaluate_promotion({"data_quality": True, "no_lookahead": False})
    assert bad["promote"] is False
    assert bad["failed_at"] == "no_lookahead"
    good = evaluate_promotion({k: True for k in [
        "data_quality", "no_lookahead", "sufficient_sample", "oos_positive_expectancy",
        "risk_adjusted_oos", "cost_aware", "regime_stable", "acceptable_drawdown",
        "correlation_ok", "capacity_ok",
    ]})
    assert good["promote"] is True
