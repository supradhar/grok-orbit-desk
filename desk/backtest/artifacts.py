from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml


def write_run_artifacts(
    out_dir: Path,
    *,
    config: dict[str, Any],
    metadata: dict[str, Any],
    equity: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    metrics: dict[str, Any],
    walkforward: dict[str, Any] | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    cfg_path = out_dir / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    paths["config"] = cfg_path

    meta_path = out_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    paths["metadata"] = meta_path

    eq_path = out_dir / "equity.csv"
    _write_csv(eq_path, equity)
    paths["equity"] = eq_path

    tr_path = out_dir / "trades.csv"
    _write_csv(tr_path, trades)
    paths["trades"] = tr_path

    sig_path = out_dir / "signals.csv"
    # flatten factors for csv
    flat_sigs = []
    for s in signals:
        row = {k: v for k, v in s.items() if k != "factors"}
        facs = s.get("factors") or {}
        for fk, fv in facs.items():
            row[f"f_{fk}"] = fv
        flat_sigs.append(row)
    _write_csv(sig_path, flat_sigs)
    paths["signals"] = sig_path

    met_path = out_dir / "metrics.json"
    met_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    paths["metrics"] = met_path

    if walkforward is not None:
        wf_path = out_dir / "walkforward.json"
        wf_path.write_text(json.dumps(walkforward, indent=2), encoding="utf-8")
        paths["walkforward"] = wf_path

    return paths


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys: list[str] = []
    seen = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
