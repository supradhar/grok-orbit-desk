"""Phase 9 — run deterministic A / +LLM-policy / +adversarial as backtest variants."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from desk.backtest.config import BacktestConfig
from desk.backtest.data import load_universe, write_synthetic_fixture
from desk.backtest.runner import _run_segment
from desk.llm_study import ab_study_specs, compare_study_runs


def _cfg_for(system_id: str, symbols: list[str], base: BacktestConfig) -> BacktestConfig:
    d = base.as_dict()
    d["symbols"] = symbols
    if system_id == "B":
        d["min_confluence"] = max(8.0, float(d["min_confluence"]) * 0.85)
    elif system_id == "C":
        d["min_confluence"] = float(d["min_confluence"]) * 1.15
        d["fee_bps"] = float(d["fee_bps"]) + 1.0
    fields = set(BacktestConfig.__dataclass_fields__)
    return BacktestConfig(**{k: v for k, v in d.items() if k in fields})


def run_abc_study(
    data_dir: Path,
    symbols: list[str] | None = None,
    warmup: int = 80,
) -> dict[str, Any]:
    symbols = symbols or ["BTC", "ETH"]
    data_dir.mkdir(parents=True, exist_ok=True)
    for sym in symbols:
        path = data_dir / f"{sym}.csv"
        if not path.exists():
            write_synthetic_fixture(path, symbol=sym, n=500, seed=42 + len(sym))

    universe = load_universe(data_dir, symbols)
    base = BacktestConfig(symbols=symbols, warmup=warmup, equity=100_000)
    runs: dict[str, dict[str, Any]] = {}
    for spec in ab_study_specs():
        cfg = _cfg_for(spec["id"], symbols, base)
        result = _run_segment(universe, cfg)
        metrics = result.get("metrics") or {}
        runs[spec["id"]] = {**metrics, "spec": spec}
    return {"runs": runs, "comparison": compare_study_runs(runs), "specs": ab_study_specs()}
