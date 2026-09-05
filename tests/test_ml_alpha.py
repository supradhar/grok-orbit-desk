from __future__ import annotations

from desk.ic import CORE
from desk.ml_alpha import LogisticModel, train_logistic_alpha


def test_logistic_learns():
    # linearly separable
    X = [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0], [0.1, 0.9]] * 10
    y = [1, 1, 0, 0] * 10
    m = LogisticModel(2, seed=1)
    m.fit(X, y, epochs=50)
    assert m.predict_proba([1.0, 0.0]) > 0.5
    assert m.predict_proba([0.0, 1.0]) < 0.5


def test_train_from_history():
    hist = {
        "BTC": [
            {
                "ts": 1000.0 + i * 60,
                "mark": 100 + (1 if i % 3 else -1) * i * 0.05,
                "factors": {f: float((i % 7) - 3) * 5 for f in CORE},
            }
            for i in range(80)
        ]
    }
    out = train_logistic_alpha(hist, horizon_sec=120)
    assert out["ok"] is True
    assert out["n_test"] > 0
