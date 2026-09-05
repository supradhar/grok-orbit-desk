from __future__ import annotations

from desk.research_db import ResearchDB
from desk.scoring import utc_now


def test_experiment_roundtrip(tmp_path):
    db = ResearchDB(tmp_path / "r.db")
    db.record_experiment(
        {
            "id": "exp1",
            "created_at": utc_now(),
            "git_commit": "abc",
            "config_hash": "cfg",
            "dataset_hash": "ds",
            "seed": 1,
            "universe": ["BTC"],
            "metrics": {"sharpe": 0.5},
            "notes": "t",
        }
    )
    rows = db.list_experiments()
    assert rows[0]["id"] == "exp1"
    assert rows[0]["metrics"]["sharpe"] == 0.5
    db.close()
