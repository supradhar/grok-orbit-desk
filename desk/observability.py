"""Phase 14 — structured logging / observability helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from desk.config_load import ROOT

LOG_PATH = ROOT / "data" / "orbit.jsonl"


def log_event(kind: str, payload: dict[str, Any], path: Path | None = None) -> None:
    row = {"ts": time.time(), "kind": kind, **payload}
    target = path or LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, default=str) + "\n")


def decision_lineage(
    *,
    symbol: str,
    blend: float | None,
    checks: dict[str, Any] | None,
    memo_id: str | None,
    approved: bool | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "blend": blend,
        "checks": checks or {},
        "memo_id": memo_id,
        "approved": approved,
    }


def redact_secrets(cfg: dict[str, Any]) -> dict[str, Any]:
    """Never persist API keys / secrets into artifacts."""
    banned = ("api_key", "apikey", "secret", "password", "token", "authorization")
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        lk = str(k).lower()
        if any(b in lk for b in banned):
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = redact_secrets(v)
        else:
            out[k] = v
    return out


ENVIRONMENTS = ("research", "paper", "simulation", "live")
