from __future__ import annotations

import math
from typing import Any


def _returns(equity: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(equity)):
        a, b = equity[i - 1], equity[i]
        if a:
            out.append((b - a) / a)
    return out


def max_drawdown(equity: list[float]) -> tuple[float, int, int]:
    peak = equity[0] if equity else 0.0
    max_dd = 0.0
    peak_i = 0
    trough_i = 0
    best_peak = 0
    for i, e in enumerate(equity):
        if e > peak:
            peak = e
            best_peak = i
        dd = (peak - e) / peak if peak else 0.0
        if dd > max_dd:
            max_dd = dd
            peak_i = best_peak
            trough_i = i
    return max_dd, peak_i, trough_i


def sharpe(rets: list[float], periods_per_year: float = 24 * 365) -> float | None:
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    sd = var**0.5
    if sd < 1e-12:
        return None
    return (mu / sd) * math.sqrt(periods_per_year)


def sortino(rets: list[float], periods_per_year: float = 24 * 365) -> float | None:
    if len(rets) < 2:
        return None
    mu = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        return None
    dvar = sum(r * r for r in downside) / len(downside)
    dsd = dvar**0.5
    if dsd < 1e-12:
        return None
    return (mu / dsd) * math.sqrt(periods_per_year)


def trade_stats(fills: list[Any]) -> dict[str, Any]:
    # Pair open/close by symbol FIFO for expectancy
    opens: dict[str, list[tuple[float, float, str]]] = {}
    pnls: list[float] = []
    for f in fills:
        side = f.side
        if side in {"long", "short"}:
            opens.setdefault(f.symbol, []).append((f.price, f.qty, side))
        elif side == "close":
            q = opens.get(f.symbol) or []
            if not q:
                continue
            entry, qty, s = q.pop(0)
            if s == "long":
                pnl = (f.price - entry) * qty - f.fee
            else:
                pnl = (entry - f.price) * qty - f.fee
            pnls.append(pnl)
    n = len(pnls)
    if not n:
        return {"n_trades": 0, "win_rate": None, "expectancy": None, "profit_factor": None}
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    p_win = len(wins) / n
    expectancy = p_win * avg_win - (1 - p_win) * avg_loss
    gw = sum(wins)
    gl = abs(sum(losses))
    pf = (gw / gl) if gl > 1e-9 else None
    return {
        "n_trades": n,
        "win_rate": round(p_win, 3),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "expectancy": round(expectancy, 4),
        "profit_factor": None if pf is None else round(pf, 3),
        "total_pnl": round(sum(pnls), 2),
    }


def summarize(
    equity_curve: list[dict[str, Any]],
    fills: list[Any],
    starting: float,
    periods_per_year: float = 24 * 365,
) -> dict[str, Any]:
    eq = [float(r["equity"]) for r in equity_curve]
    if not eq:
        return {"error": "empty equity"}
    rets = _returns(eq)
    dd, _, _ = max_drawdown(eq)
    total_ret = (eq[-1] / starting - 1.0) if starting else 0.0
    sh = sharpe(rets, periods_per_year)
    so = sortino(rets, periods_per_year)
    calmar = (total_ret / dd) if dd > 1e-9 else None
    trades = trade_stats(fills)
    turnover = float(equity_curve[-1].get("turnover") or 0.0)
    fees = float(equity_curve[-1].get("fees") or 0.0)
    return {
        "start_equity": starting,
        "end_equity": round(eq[-1], 2),
        "total_return": round(total_ret, 4),
        "max_drawdown": round(dd, 4),
        "sharpe": None if sh is None else round(sh, 3),
        "sortino": None if so is None else round(so, 3),
        "calmar": None if calmar is None else round(calmar, 3),
        "ann_vol": None
        if len(rets) < 2
        else round((sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * math.sqrt(periods_per_year), 4),
        "turnover": round(turnover, 2),
        "fees_paid": round(fees, 2),
        "n_bars": len(eq),
        **trades,
    }


def buy_hold_return(marks_start: float, marks_end: float) -> float | None:
    if not marks_start:
        return None
    return (marks_end / marks_start) - 1.0
