from __future__ import annotations

from typing import Any

from desk.backtest.config import BacktestConfig
from desk.backtest.execution import Order
from desk.backtest.features import blend_factors, feature_snapshot
from desk.backtest.portfolio import Portfolio
from desk.ic import CORE


def decide(
    snap: dict[str, Any],
    cfg: BacktestConfig,
    weights: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """Deterministic L1→L5-lite: blend factors, gate on confluence + cost buffer, emit side or NO TRADE."""
    factors = snap.get("factors") or {}
    blend = blend_factors(factors, weights)
    if abs(blend) < cfg.min_confluence:
        return None  # NO TRADE
    # Cost-aware: rough expected move from |blend|/10000 must beat friction
    friction = (cfg.fee_bps * 2 + cfg.slippage_bps + cfg.spread_bps) / 1e4
    expected_move = abs(blend) / 10000.0  # heuristic scale
    if expected_move < friction * 1.25:
        return None  # NO TRADE — alpha does not clear costs
    side = "long" if blend > 0 else "short"
    return {
        "symbol": snap["symbol"],
        "side": side,
        "blend": blend,
        "factors": factors,
        "mark": snap["mark"],
        "ts": snap["ts"],
    }


def size_usd(portfolio: Portfolio, marks: dict[str, float], cfg: BacktestConfig, stop_pct: float) -> float:
    eq = portfolio.equity(marks)
    base = eq * cfg.max_position_pct
    # widen stop ⇒ shrink size
    scale = min(1.0, cfg.stop_pct / max(stop_pct, 1e-6))
    return base * scale


def run_bar(
    t: float,
    bars_asof: dict[str, list],
    portfolio: Portfolio,
    cfg: BacktestConfig,
    pending: list[Order],
    weights: dict[str, float] | None = None,
    signals_out: list[dict[str, Any]] | None = None,
) -> list[Order]:
    """
    At bar t:
      1) fill pending orders from prior bar (next-bar execution) at this bar open/close mid
      2) apply stops on this bar H/L
      3) compute signals from bars_asof (no lookahead)
      4) queue orders for next bar
    """
    marks = {}
    opens = {}
    lasts = {}
    for sym, bars in bars_asof.items():
        if not bars:
            continue
        lasts[sym] = bars[-1]
        marks[sym] = bars[-1].close
        opens[sym] = bars[-1].open

    # 1) execute pending at this bar open (next-bar)
    still: list[Order] = []
    for order in pending:
        mid = opens.get(order.symbol) or marks.get(order.symbol)
        if mid is None:
            still.append(order)
            continue
        fill = portfolio.submit(order, t, mid, marks)
        if fill and order.side in {"long", "short"}:
            px = fill.price
            sp = cfg.stop_pct
            if order.side == "long":
                portfolio.set_stops(order.symbol, px * (1 - sp), px * (1 + sp * cfg.rr))
            else:
                portfolio.set_stops(order.symbol, px * (1 + sp), px * (1 - sp * cfg.rr))

    # 2) stops
    portfolio.apply_stops(t, lasts, marks)

    # 3) signals
    new_orders: list[Order] = []
    for sym, bars in bars_asof.items():
        if len(bars) < 2:
            continue
        feat = feature_snapshot(sym, bars)
        if feat.get("mark") is None:
            continue
        decision = decide(feat, cfg, weights)
        if signals_out is not None:
            signals_out.append(
                {
                    "ts": t,
                    "symbol": sym,
                    "blend": (decision or {}).get("blend"),
                    "side": (decision or {}).get("side"),
                    "mark": feat["mark"],
                    "factors": feat.get("factors"),
                    "trade": decision is not None,
                }
            )
        if not decision:
            continue
        # flat or same-side add; flip → close first
        pos = portfolio.positions.get(sym)
        if pos and pos.side != decision["side"]:
            new_orders.append(Order(sym, "close", pos.qty * marks[sym], t, reason="flip"))
        stop_pct = cfg.stop_pct
        usd = size_usd(portfolio, marks, cfg, stop_pct)
        new_orders.append(Order(sym, decision["side"], usd, t, reason=f"blend={decision['blend']:.1f}"))

    # 4) mark equity
    portfolio.mark_to_market(t, marks)
    return new_orders


def equal_weights() -> dict[str, float]:
    return {f: 1.0 / len(CORE) for f in CORE}
