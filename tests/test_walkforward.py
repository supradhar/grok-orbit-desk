from __future__ import annotations

from desk.backtest.walkforward import walkforward_windows


def test_walkforward_windows():
    stamps = list(range(400))
    wins = walkforward_windows(stamps, train_bars=100, test_bars=50, step=50)
    assert wins
    for tr_lo, tr_hi, te_lo, te_hi in wins:
        assert tr_hi == te_lo
        assert te_hi - te_lo == 50
        assert tr_hi - tr_lo == 100
