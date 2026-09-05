"""Phase 11 — SQLite research persistence and experiment registry."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from desk.config_load import ROOT

DEFAULT_DB = ROOT / "data" / "research.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS experiments (
  id TEXT PRIMARY KEY,
  created_at REAL,
  git_commit TEXT,
  config_hash TEXT,
  dataset_hash TEXT,
  seed INTEGER,
  universe TEXT,
  metrics_json TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS market_bars (
  symbol TEXT,
  event_time REAL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  source TEXT,
  PRIMARY KEY (symbol, event_time)
);
CREATE TABLE IF NOT EXISTS factor_signals (
  ts REAL,
  symbol TEXT,
  factor TEXT,
  score REAL,
  run_id TEXT
);
CREATE TABLE IF NOT EXISTS fills (
  ts REAL,
  symbol TEXT,
  side TEXT,
  qty REAL,
  price REAL,
  fee REAL,
  run_id TEXT
);
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  ts REAL,
  equity REAL,
  cash REAL,
  gross REAL,
  run_id TEXT
);
CREATE TABLE IF NOT EXISTS models (
  model_id TEXT PRIMARY KEY,
  created_at REAL,
  kind TEXT,
  train_range TEXT,
  features_json TEXT,
  metrics_json TEXT,
  git_commit TEXT
);
"""


class ResearchDB:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_experiment(self, exp: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO experiments
            (id, created_at, git_commit, config_hash, dataset_hash, seed, universe, metrics_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                exp["id"],
                float(exp.get("created_at") or 0),
                exp.get("git_commit"),
                exp.get("config_hash"),
                exp.get("dataset_hash"),
                exp.get("seed"),
                json.dumps(exp.get("universe") or []),
                json.dumps(exp.get("metrics") or {}),
                exp.get("notes"),
            ),
        )
        self._conn.commit()

    def list_experiments(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT id, created_at, git_commit, config_hash, metrics_json, notes FROM experiments ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        out = []
        for row in cur.fetchall():
            out.append(
                {
                    "id": row[0],
                    "created_at": row[1],
                    "git_commit": row[2],
                    "config_hash": row[3],
                    "metrics": json.loads(row[4] or "{}"),
                    "notes": row[5],
                }
            )
        return out

    def insert_bars(self, symbol: str, bars: list[dict[str, Any]], source: str = "csv") -> int:
        n = 0
        for b in bars:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO market_bars
                (symbol, event_time, open, high, low, close, volume, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    float(b["ts"]),
                    float(b["open"]),
                    float(b["high"]),
                    float(b["low"]),
                    float(b["close"]),
                    float(b.get("volume") or 0),
                    source,
                ),
            )
            n += 1
        self._conn.commit()
        return n

    def record_model(self, model: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO models
            (model_id, created_at, kind, train_range, features_json, metrics_json, git_commit)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model["model_id"],
                float(model.get("created_at") or 0),
                model.get("kind"),
                model.get("train_range"),
                json.dumps(model.get("features") or []),
                json.dumps(model.get("metrics") or {}),
                model.get("git_commit"),
            ),
        )
        self._conn.commit()
