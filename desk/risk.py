from __future__ import annotations

from typing import Any

from desk.paper import PaperBroker
from desk.scoring import utc_now


def realized_vol(marks: list[float], lookback: int = 20) -> float | None:
    """Simple close-to-close vol from recent marks; returns fractional std of returns."""
    if len(marks) < max(3, lookback // 2):
        return None
    window = marks[-lookback:]
    rets: list[float] = []
    for i in range(1, len(window)):
        a, b = window[i - 1], window[i]
        if a and b:
            rets.append((b - a) / a)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return var**0.5


def stop_pct_for_symbol(
    history_marks: list[float] | None,
    base_stop_pct: float = 0.02,
    k: float = 2.5,
    floor: float = 0.008,
    ceil: float = 0.08,
) -> float:
    """ATR-ish: k * realized vol, clamped; falls back to base_stop_pct."""
    vol = realized_vol(history_marks or [])
    if vol is None:
        return base_stop_pct
    return max(floor, min(ceil, k * vol))


def size_scale_for_stop(stop_pct: float, base_stop_pct: float = 0.02) -> float:
    """Widen stop ⇒ shrink size so $ risk stays ~constant."""
    if stop_pct <= 0:
        return 1.0
    return min(1.0, base_stop_pct / stop_pct)


def ensure_stops(
    paper: PaperBroker,
    stop_pct: float = 0.02,
    rr: float = 1.8,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    hist = history or {}
    for pos in paper.positions.values():
        px = pos.avg_price or pos.mark
        if not px:
            continue
        marks = [float(r["mark"]) for r in hist.get(pos.symbol, []) if r.get("mark")]
        sp = stop_pct_for_symbol(marks, base_stop_pct=stop_pct)
        if not float(getattr(pos, "stop", 0) or 0):
            if pos.side == "long":
                pos.stop = px * (1 - sp)
            else:
                pos.stop = px * (1 + sp)
        if not float(getattr(pos, "target", 0) or 0):
            if pos.side == "long":
                pos.target = px * (1 + sp * rr)
            else:
                pos.target = px * (1 - sp * rr)


def apply_stops(paper: PaperBroker) -> list[str]:
    notes: list[str] = []
    for sym, pos in list(paper.positions.items()):
        mark = paper.marks.get(sym) or pos.mark or pos.avg_price
        pos.mark = mark
        stop = float(getattr(pos, "stop", 0) or 0)
        target = float(getattr(pos, "target", 0) or 0)
        hit = ""
        if pos.side == "long":
            if stop and mark <= stop:
                hit = "stop"
            elif target and mark >= target:
                hit = "target"
        else:
            if stop and mark >= stop:
                hit = "stop"
            elif target and mark <= target:
                hit = "target"
        if hit:
            # Gap-aware: fill at mark (may be beyond stop)
            paper.close(sym)
            notes.append(f"{sym} {hit} at {mark:.6g}")
    return notes


def panic_cut(
    paper: PaperBroker,
    hmm: str,
    high_beta: set[str],
    standalone: set[str] | None = None,
) -> list[str]:
    """Flatten crypto risk-on longs in HMM panic — never metals/FX standalone."""
    if hmm != "panic":
        return []
    stand = standalone or set()
    notes: list[str] = []
    for sym, pos in list(paper.positions.items()):
        if sym in stand or sym in {"BTC", "ETH"}:
            continue
        if pos.side == "long" and (sym in high_beta or sym not in stand):
            paper.close(sym)
            notes.append(f"{sym} panic flatten")
    return notes


def halted(paper: PaperBroker, max_daily_loss_pct: float, ts: float | None = None) -> bool:
    paper.sync_risk_day(ts)
    if paper.day_start_equity <= 0:
        return False
    dd = paper.daily_drawdown_pct
    if dd >= max_daily_loss_pct:
        if not paper.halted:
            paper.halted = True
            paper.halt_reason = "daily_loss"
            paper.halt_timestamp = ts if ts is not None else utc_now()
        return True
    return bool(paper.halted)


def snapshot(paper: PaperBroker, max_daily_loss_pct: float) -> dict[str, Any]:
    paper.sync_risk_day()
    dd = paper.daily_drawdown_pct
    return {
        "halted": halted(paper, max_daily_loss_pct),
        "drawdown_pct": round(dd, 4),
        "lifetime_drawdown_pct": round(
            (paper.starting - paper.equity) / paper.starting if paper.starting > 0 else 0.0, 4
        ),
        "day_start_equity": round(paper.day_start_equity, 2),
        "day_start_key": paper.day_start_key,
        "halt_reason": paper.halt_reason,
        "halt_timestamp": paper.halt_timestamp,
        "max_daily_loss_pct": max_daily_loss_pct,
        "fee_bps": getattr(paper, "fee_bps", 0),
        "ts": utc_now(),
    }
