from __future__ import annotations

import argparse
from pathlib import Path

from desk.backtest.runner import run_backtest
from desk.config_load import ROOT


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Orbit Backtest Engine v1")
    p.add_argument("--symbols", default="BTC,ETH,SOL,XAUUSD")
    p.add_argument("--start", default=None, help="YYYY-MM-DD")
    p.add_argument("--end", default=None, help="YYYY-MM-DD")
    p.add_argument("--data", default=None, help="Directory of OHLCV CSVs (SYMBOL.csv)")
    p.add_argument("--warmup", type=int, default=250)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--walkforward", action="store_true")
    p.add_argument("--out", default=None, help="Output directory under data/backtests/")
    args = p.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    data_dir = Path(args.data) if args.data else ROOT / "data" / "ohlcv"
    out = run_backtest(
        symbols=symbols,
        data_dir=data_dir,
        start=args.start,
        end=args.end,
        warmup=args.warmup,
        seed=args.seed,
        walkforward=args.walkforward,
        out_dir=Path(args.out) if args.out else None,
    )
    print(out["run_id"], out["metrics_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
