from __future__ import annotations

from desk.models import DecisionMemo
from desk.paper import PaperBroker
from desk.scoring import utc_now


def test_order_state_reject_flip():
    p = PaperBroker(100_000, 0, 0.8, 0)
    p.marks["BTC"] = 100
    m1 = DecisionMemo("1", "BTC", "long", 0.5, 1000, 100, 0, 0, "t", "i", [], [], "pending", utc_now())
    assert p.approve(m1) == "filled"
    m2 = DecisionMemo("2", "BTC", "short", 0.5, 1000, 100, 0, 0, "t", "i", [], [], "pending", utc_now())
    assert "flip" in p.approve(m2)
