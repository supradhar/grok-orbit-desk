from __future__ import annotations

from desk.models import DecisionMemo
from desk.paper import PaperBroker
from desk.scoring import utc_now


def test_fees_and_slippage_applied():
    p = PaperBroker(equity=100_000, slippage_bps=10, max_gross_pct=0.5, fee_bps=10)
    p.marks["BTC"] = 100.0
    memo = DecisionMemo(
        id="t1",
        symbol="BTC",
        side="long",
        conviction=0.5,
        size_usd=10_000,
        entry=100.0,
        stop=0,
        target=0,
        thesis="t",
        invalidation="i",
        factors=[],
        risk_notes=[],
        status="pending",
        ts=utc_now(),
    )
    msg = p.approve(memo)
    assert msg == "filled"
    fill = p.fills[-1]
    # long pays slippage: 100 * 1.001 = 100.1
    assert abs(fill.price - 100.1) < 1e-9
    # cash reduced by notional + fee
    notional = fill.qty * fill.price
    fee = notional * 0.001
    assert abs(p.cash - (100_000 - notional - fee)) < 1e-6
