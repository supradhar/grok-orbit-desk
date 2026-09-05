from __future__ import annotations

from desk import risk
from desk.paper import PaperBroker


def test_vol_stops_scale():
    marks = [100 + i * 0.5 for i in range(30)]
    sp = risk.stop_pct_for_symbol(marks, base_stop_pct=0.02)
    assert sp >= 0.008
    paper = PaperBroker(100_000, 6, 0.4, 4)
    from desk.models import Position

    paper.positions["BTC"] = Position("BTC", "long", 1, 100, 100, 0, 0)
    risk.ensure_stops(paper, stop_pct=0.02, history={"BTC": [{"mark": m} for m in marks]})
    assert paper.positions["BTC"].stop > 0
    assert paper.positions["BTC"].target > paper.positions["BTC"].avg_price


def test_gross_halt_exposure_not_nan():
    paper = PaperBroker(100_000, 6, 0.4, 4)
    assert paper.equity == 100_000
    snap = risk.snapshot(paper, 0.02)
    assert snap["drawdown_pct"] == 0.0
