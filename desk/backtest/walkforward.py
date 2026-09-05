from __future__ import annotations

from typing import Any, Callable

from desk.backtest.config import BacktestConfig
from desk.backtest.data import Bar


def walkforward_windows(
    timestamps: list[float],
    train_bars: int = 200,
    test_bars: int = 50,
    step: int = 50,
) -> list[tuple[int, int, int, int]]:
    """Return index windows (train_lo, train_hi, test_lo, test_hi) exclusive hi."""
    n = len(timestamps)
    out: list[tuple[int, int, int, int]] = []
    i = 0
    while i + train_bars + test_bars <= n:
        tr_lo, tr_hi = i, i + train_bars
        te_lo, te_hi = tr_hi, tr_hi + test_bars
        out.append((tr_lo, tr_hi, te_lo, te_hi))
        i += step
    return out


def run_walkforward(
    universe: dict[str, list[Bar]],
    timestamps: list[float],
    cfg: BacktestConfig,
    run_segment: Callable[[dict[str, list[Bar]], BacktestConfig], dict[str, Any]],
    train_bars: int = 200,
    test_bars: int = 50,
    step: int = 50,
) -> dict[str, Any]:
    """
    For each window: optionally tune on train (v1: freeze equal weights),
    evaluate metrics on test only. Aggregate OOS.
    """
    windows = walkforward_windows(timestamps, train_bars, test_bars, step)
    oos: list[dict[str, Any]] = []
    for tr_lo, tr_hi, te_lo, te_hi in windows:
        te_start = timestamps[te_lo]
        te_end = timestamps[te_hi - 1]
        # slice universe to test range including warmup from prior bars
        warm_start_i = max(0, te_lo - cfg.warmup)
        warm_start_t = timestamps[warm_start_i]
        sliced: dict[str, list[Bar]] = {}
        for sym, bars in universe.items():
            sliced[sym] = [b for b in bars if warm_start_t <= b.ts <= te_end]
        seg_cfg = BacktestConfig(**{**cfg.as_dict(), "symbols": cfg.symbols})
        # freeze: v1 does not fit on train beyond using train length as warm context
        result = run_segment(sliced, seg_cfg)
        metrics = result.get("metrics") or {}
        oos.append(
            {
                "train": [tr_lo, tr_hi],
                "test": [te_lo, te_hi],
                "test_start": te_start,
                "test_end": te_end,
                "total_return": metrics.get("total_return"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "expectancy": metrics.get("expectancy"),
                "n_trades": metrics.get("n_trades"),
            }
        )
    rets = [x["total_return"] for x in oos if x.get("total_return") is not None]
    sharpes = [x["sharpe"] for x in oos if x.get("sharpe") is not None]
    return {
        "n_windows": len(oos),
        "windows": oos,
        "oos_mean_return": round(sum(rets) / len(rets), 4) if rets else None,
        "oos_mean_sharpe": round(sum(sharpes) / len(sharpes), 3) if sharpes else None,
        "oos_positive_windows": sum(1 for r in rets if r > 0),
    }
