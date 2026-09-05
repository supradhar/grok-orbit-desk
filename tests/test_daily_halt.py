from __future__ import annotations

from datetime import datetime, timezone

from desk.paper import PaperBroker
from desk import risk


def _broker(equity: float = 100_000.0) -> PaperBroker:
    return PaperBroker(equity=equity, slippage_bps=6, max_gross_pct=0.4, fee_bps=4)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_daily_halt_uses_day_start_not_lifetime():
    p = _broker(100_000)
    p.day_start_key = _today()
    p.day_start_equity = 90_000  # already down from lifetime start
    p.cash = 88_200  # ~2% below day start → halt; lifetime DD still only ~11.8%
    assert (p.starting - p.equity) / p.starting < 0.15
    assert p.daily_drawdown_pct >= 0.02
    assert risk.halted(p, 0.02) is True
    assert p.halt_reason == "daily_loss"


def test_below_limit_not_halted():
    p = _broker(100_000)
    p.day_start_key = _today()
    p.day_start_equity = 100_000
    p.cash = 99_000  # 1%
    assert risk.halted(p, 0.02) is False


def test_next_day_resets_halt():
    p = _broker(100_000)
    p.day_start_key = _today()
    p.day_start_equity = 100_000
    p.cash = 97_000
    assert risk.halted(p, 0.02) is True
    # Simulate next UTC day
    ts = datetime(2099, 6, 1, tzinfo=timezone.utc).timestamp()
    p.sync_risk_day(ts)
    assert p.day_start_key == "2099-06-01"
    assert p.halted is False
    assert abs(p.day_start_equity - p.equity) < 1e-6


def test_restart_restores_day_baseline(tmp_path, monkeypatch):
    from desk import store

    monkeypatch.setattr(store, "DATA", tmp_path / "desk.json")
    p = _broker(100_000)
    p.day_start_equity = 95_000
    p.day_start_key = "2024-03-03"
    p.halted = True
    p.halt_reason = "daily_loss"
    p.halt_timestamp = 123.0
    store.save_desk(p, [], 1, {})
    p2 = _broker(100_000)
    store.restore_desk(p2, [])
    assert p2.day_start_equity == 95_000
    assert p2.day_start_key == "2024-03-03"
    assert p2.halted is True
    assert p2.halt_reason == "daily_loss"
