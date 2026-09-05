from __future__ import annotations

from typing import Any

from desk.paper import PaperBroker
from desk.scoring import utc_now


def ensure_stops(paper: PaperBroker, stop_pct: float = 0.02, rr: float = 1.8) -> None:
    for pos in paper.positions.values():
        px = pos.avg_price or pos.mark
        if not px:
            continue
        if not float(getattr(pos, "stop", 0) or 0):
            if pos.side == "long":
                pos.stop = px * (1 - stop_pct)
            else:
                pos.stop = px * (1 + stop_pct)
        if not float(getattr(pos, "target", 0) or 0):
            if pos.side == "long":
                pos.target = px * (1 + stop_pct * rr)
            else:
                pos.target = px * (1 - stop_pct * rr)


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
        # Alts (esp. high-beta): flatten longs; majors + metals already skipped.
        if pos.side == "long" and (sym in high_beta or sym not in stand):
            paper.close(sym)
            notes.append(f"{sym} panic flatten")
    return notes


def halted(paper: PaperBroker, max_daily_loss_pct: float) -> bool:
    if paper.starting <= 0:
        return False
    dd = (paper.starting - paper.equity) / paper.starting
    return dd >= max_daily_loss_pct


def snapshot(paper: PaperBroker, max_daily_loss_pct: float) -> dict[str, Any]:
    dd = 0.0 if paper.starting <= 0 else (paper.starting - paper.equity) / paper.starting
    return {
        "halted": halted(paper, max_daily_loss_pct),
        "drawdown_pct": round(dd, 4),
        "max_daily_loss_pct": max_daily_loss_pct,
        "fee_bps": getattr(paper, "fee_bps", 0),
        "ts": utc_now(),
    }
