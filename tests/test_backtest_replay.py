from __future__ import annotations

from desk.backtest.clock import Clock
from desk.backtest.data import Bar, write_synthetic_fixture
from desk.backtest.features import feature_snapshot
from desk.backtest.validation import assert_next_bar


def test_bars_asof_no_lookahead(tmp_path):
    path = tmp_path / "BTC.csv"
    write_synthetic_fixture(path, "BTC", n=50, seed=1)
    from desk.backtest.data import load_csv

    bars = load_csv(path)
    t = bars[10].ts
    clock = Clock([b.ts for b in bars])
    asof = clock.bars_asof(bars, t)
    assert asof[-1].ts == t
    assert all(b.ts <= t for b in asof)
    # feature uses only asof
    feat = feature_snapshot("BTC", asof)
    assert feat["ts"] == t
    assert feat["mark"] == asof[-1].close


def test_next_bar_invariant():
    assert_next_bar(100.0, 101.0)
    try:
        assert_next_bar(100.0, 100.0)
        assert False, "should raise"
    except AssertionError:
        pass


def test_feature_ignores_future_bar():
    bars = [
        Bar(100.0, 1, 1, 1, 10.0, 1),
        Bar(200.0, 1, 1, 1, 20.0, 1),
        Bar(300.0, 1, 1, 1, 30.0, 1),
    ]
    feat = feature_snapshot("BTC", bars[:2])
    assert feat["mark"] == 20.0
    assert feat["ts"] == 200.0
