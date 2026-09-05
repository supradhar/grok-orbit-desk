from __future__ import annotations

from typing import Any

from desk.backtest.data import Bar
from desk.scoring import pct_change, rsi_like


def _closes(bars: list[Bar]) -> list[float]:
    return [b.close for b in bars]


def feature_snapshot(sym: str, bars: list[Bar]) -> dict[str, Any]:
    """Deterministic OHLCV features available at last bar event_time (no future)."""
    if not bars:
        return {"symbol": sym, "mark": None, "factors": {}}
    last = bars[-1]
    closes = _closes(bars)
    c1 = closes[-2] if len(closes) >= 2 else last.close
    c24 = closes[-24] if len(closes) >= 24 else closes[0]
    mom_1 = pct_change(last.close, c1)
    mom_24 = pct_change(last.close, c24)
    # realized vol of last 20 returns
    rets = []
    for i in range(max(1, len(closes) - 20), len(closes)):
        if closes[i - 1]:
            rets.append((closes[i] - closes[i - 1]) / closes[i - 1])
    vol = (sum(r * r for r in rets) / len(rets)) ** 0.5 if rets else 0.0
    window = bars[-32:] if len(bars) >= 8 else bars
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    mid = (hi + lo) / 2 if hi > lo else last.close
    structure = pct_change(last.close, mid) * 2.0
    vols = [b.volume for b in bars[-20:]]
    v_avg = sum(vols) / len(vols) if vols else 0.0
    vol_score = ((last.volume / v_avg) - 1.0) * 40.0 if v_avg else 0.0
    rsi = rsi_like(closes)
    rsi_score = (50.0 - rsi) * 1.2  # mean-revert lean at extremes
    factors = {
        "momentum": max(-100.0, min(100.0, mom_1 * 4.0 + mom_24 * 1.5)),
        "volume": max(-100.0, min(100.0, vol_score)),
        "volatility": max(-100.0, min(100.0, -vol * 800.0)),  # high vol = caution
        "structure": max(-100.0, min(100.0, structure)),
        "liquidity": max(-100.0, min(100.0, vol_score * 0.5)),
        "flows": max(-100.0, min(100.0, mom_1 * 2.0)),
        "policy": 0.0,
        "news": 0.0,
        "social": 0.0,
        "whales": 0.0,
        "derivatives": max(-100.0, min(100.0, rsi_score)),
    }
    return {
        "symbol": sym,
        "mark": last.close,
        "ts": last.ts,
        "open": last.open,
        "high": last.high,
        "low": last.low,
        "close": last.close,
        "volume": last.volume,
        "factors": factors,
        "rsi": rsi,
        "realized_vol": vol,
    }


def blend_factors(factors: dict[str, float], weights: dict[str, float] | None = None) -> float:
    weights = weights or {k: 1.0 for k in factors}
    num = den = 0.0
    for k, v in factors.items():
        w = float(weights.get(k, 0.0))
        if w <= 0:
            continue
        num += float(v) * w
        den += w
    return num / den if den else 0.0
