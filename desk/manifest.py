from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from desk.config_load import ROOT


def _git_commit() -> str | None:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip() or None
    except Exception:
        return None


def config_hash(cfg: dict[str, Any]) -> str:
    blob = json.dumps(cfg, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def dataset_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def build_manifest(
    cfg: dict[str, Any],
    *,
    universe: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    timeframe: str | None = None,
    seed: int | None = None,
    dataset_path: Path | None = None,
    execution: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    llm = cfg.get("llm") or {}
    man: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "config_hash": config_hash(cfg),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "seed": seed,
        "universe": universe or [a.get("symbol") for a in (cfg.get("watchlist") or []) if isinstance(a, dict)],
        "time_range": {"start": start, "end": end},
        "timeframe": timeframe,
        "equity": cfg.get("equity"),
        "fee_bps": cfg.get("fee_bps"),
        "slippage_bps": cfg.get("slippage_bps"),
        "max_daily_loss_pct": cfg.get("max_daily_loss_pct"),
        "max_gross_exposure_pct": cfg.get("max_gross_exposure_pct"),
        "llm_model": llm.get("model"),
        "execution": execution or {},
        "dataset_hash": dataset_hash(dataset_path) if dataset_path else None,
        "assumptions": [
            "Paper trading only — not financial advice.",
            "Backtest v1 uses deterministic OHLCV factors; live news/LLM/macro excluded until event-time data exists.",
            "Next-bar execution; no same-bar fills.",
            "Fixed fee/slippage bps unless execution config overrides.",
        ],
        "limitations": [
            "Public feed quality varies; live desk is not a backtest.",
            "Hit-rate diagnostics are not strategy P&L.",
            "No claim of future profitability from OOS metrics alone.",
        ],
    }
    if extra:
        man.update(extra)
    return man


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
