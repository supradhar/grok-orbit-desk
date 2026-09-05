from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desk.backtest.artifacts import write_run_artifacts
from desk.backtest.config import BacktestConfig
from desk.backtest.data import date_to_ts, filter_range, load_universe, write_synthetic_fixture
from desk.backtest.metrics import summarize
from desk.backtest.pipeline import equal_weights, run_bar
from desk.backtest.portfolio import Portfolio
from desk.backtest.replay import align_timestamps, replay
from desk.backtest.validation import validate_universe
from desk.backtest.walkforward import run_walkforward
from desk.config_load import ROOT, load_config
from desk.manifest import build_manifest, write_manifest


def _ensure_fixture(data_dir: Path, symbols: list[str]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            write_synthetic_fixture(path, symbol=sym, n=600, seed=42 + len(sym))


def _run_segment(universe: dict, cfg: BacktestConfig) -> dict[str, Any]:
    validate_universe(universe)
    stamps = align_timestamps(universe)
    if len(stamps) <= cfg.warmup + 2:
        return {"metrics": {"error": "insufficient bars"}, "equity": [], "fills": [], "signals": []}

    port = Portfolio(
        cash=cfg.equity,
        starting=cfg.equity,
        fee_bps=cfg.fee_bps,
        slippage_bps=cfg.slippage_bps,
        spread_bps=cfg.spread_bps,
        max_gross_pct=cfg.max_gross_pct,
        max_position_pct=cfg.max_position_pct,
        max_daily_loss_pct=cfg.max_daily_loss_pct,
    )
    weights = equal_weights()
    pending = []
    signals: list[dict[str, Any]] = []
    bar_i = 0
    for t, snap in replay(universe):
        bar_i += 1
        if bar_i <= cfg.warmup:
            # warm-up: mark only, no signals
            marks = {s: bars[-1].close for s, bars in snap.items() if bars}
            port.mark_to_market(t, marks)
            continue
        pending = run_bar(t, snap, port, cfg, pending, weights=weights, signals_out=signals)

    metrics = summarize(port.equity_curve, port.fills, cfg.equity)
    return {
        "metrics": metrics,
        "equity": port.equity_curve,
        "fills": port.fills,
        "signals": signals,
        "portfolio": port,
    }


def run_backtest(
    symbols: list[str],
    data_dir: Path,
    start: str | None = None,
    end: str | None = None,
    warmup: int = 250,
    seed: int = 42,
    walkforward: bool = False,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    cfg_live, _ = load_config()
    _ensure_fixture(data_dir, symbols)
    raw = load_universe(data_dir, symbols)
    t0, t1 = date_to_ts(start), date_to_ts(end)
    universe = {s: filter_range(bars, t0, t1) for s, bars in raw.items()}
    # if filter emptied, fall back to full fixture
    if any(len(v) < warmup + 10 for v in universe.values()):
        universe = raw

    bt = BacktestConfig(
        symbols=symbols,
        warmup=warmup,
        seed=seed,
        fee_bps=float(cfg_live.get("fee_bps") or 4),
        slippage_bps=float(cfg_live.get("slippage_bps") or 6),
        spread_bps=float(cfg_live.get("spread_bps") or 2),
        max_gross_pct=float(cfg_live.get("max_gross_exposure_pct") or 0.40),
        max_position_pct=float(cfg_live.get("max_position_pct") or 0.08),
        max_daily_loss_pct=float(cfg_live.get("max_daily_loss_pct") or 0.02),
        equity=float(cfg_live.get("equity") or 100000),
        stop_pct=float(cfg_live.get("stop_pct") or 0.02),
    )

    result = _run_segment(universe, bt)
    stamps = align_timestamps(universe)
    wf = None
    if walkforward:
        wf = run_walkforward(universe, stamps, bt, _run_segment)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    out = out_dir or (ROOT / "data" / "backtests" / run_id)
    trades = [
        {
            "symbol": f.symbol,
            "side": f.side,
            "qty": f.qty,
            "price": f.price,
            "fee": f.fee,
            "ts": f.ts,
            "reason": f.reason,
        }
        for f in result["fills"]
    ]
    # strip nested factors for huge signals optionally — artifacts flattens
    meta = build_manifest(
        cfg_live,
        universe=symbols,
        start=start,
        end=end,
        timeframe="1h_fixture_or_csv",
        seed=seed,
        dataset_path=data_dir / f"{symbols[0]}.csv" if symbols else None,
        execution={
            "next_bar_only": True,
            "fee_bps": bt.fee_bps,
            "slippage_bps": bt.slippage_bps,
            "spread_bps": bt.spread_bps,
            "warmup": warmup,
        },
        extra={"run_id": run_id, "engine": "orbit-backtest-v1"},
    )
    write_manifest(out / "metadata.json", meta)
    paths = write_run_artifacts(
        out,
        config=bt.as_dict(),
        metadata=meta,
        equity=result["equity"],
        trades=trades,
        signals=result["signals"],
        metrics=result["metrics"],
        walkforward=wf,
    )
    return {
        "run_id": run_id,
        "out_dir": str(out),
        "metrics": result["metrics"],
        "walkforward": wf,
        "metrics_path": str(paths["metrics"]),
    }
