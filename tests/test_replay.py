from __future__ import annotations

from desk.backtest.clock import Clock
from desk.backtest.data import Bar
from desk.backtest.validation import assert_next_bar, assert_no_lookahead, validate_bars


def test_warmup_and_order():
    bars = [Bar(float(i), 1.0 + i * 0.01, 1.1 + i * 0.01, 0.9 + i * 0.01, 1.0 + i * 0.01, 1) for i in range(10)]
    assert not validate_bars("BTC", bars)
    clock = Clock([b.ts for b in bars])
    asof = clock.bars_asof(bars, 5.0)
    assert asof[-1].ts == 5.0
    assert_no_lookahead(5.0, 5.0)
    assert_next_bar(5.0, 6.0)


def test_determinism_fixture(tmp_path):
    from desk.backtest.data import write_synthetic_fixture, load_csv

    p = tmp_path / "BTC.csv"
    write_synthetic_fixture(p, "BTC", n=30, seed=99)
    a = load_csv(p)
    write_synthetic_fixture(p, "BTC", n=30, seed=99)
    b = load_csv(p)
    assert [x.close for x in a] == [x.close for x in b]
