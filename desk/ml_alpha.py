"""Phase 10 — ML alpha baselines (pure-Python logistic; optional sklearn-free)."""

from __future__ import annotations

import math
import random
from typing import Any


def _sigmoid(x: float) -> float:
    if x >= 20:
        return 1.0
    if x <= -20:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


class LogisticModel:
    def __init__(self, n_features: int, lr: float = 0.05, l2: float = 0.01, seed: int = 42) -> None:
        rng = random.Random(seed)
        self.w = [rng.uniform(-0.01, 0.01) for _ in range(n_features)]
        self.b = 0.0
        self.lr = lr
        self.l2 = l2
        self.n_features = n_features

    def predict_proba(self, x: list[float]) -> float:
        z = self.b + sum(wi * xi for wi, xi in zip(self.w, x))
        return _sigmoid(z)

    def fit(self, X: list[list[float]], y: list[int], epochs: int = 40) -> None:
        n = len(X)
        if n == 0:
            return
        for _ in range(epochs):
            for i in range(n):
                p = self.predict_proba(X[i])
                err = p - y[i]
                for j in range(self.n_features):
                    self.w[j] -= self.lr * (err * X[i][j] + self.l2 * self.w[j])
                self.b -= self.lr * err


def build_xy_from_history(
    history: dict[str, list[dict[str, Any]]],
    feature_names: list[str],
    horizon_sec: float = 480.0,
) -> tuple[list[list[float]], list[int], list[str]]:
    from desk.ic import _later_row

    X: list[list[float]] = []
    y: list[int] = []
    meta: list[str] = []
    for sym, rows in history.items():
        for i, a in enumerate(rows):
            facs = a.get("factors") or {}
            m0 = a.get("mark")
            if not m0:
                continue
            vec = [float(facs[f]) if facs.get(f) is not None else 0.0 for f in feature_names]
            if all(v == 0 for v in vec):
                continue
            b = _later_row(rows, i, horizon_sec)
            if not b or not b.get("mark"):
                continue
            ret = (float(b["mark"]) - float(m0)) / float(m0)
            X.append(vec)
            y.append(1 if ret > 0 else 0)
            meta.append(sym)
    return X, y, meta


def train_logistic_alpha(
    history: dict[str, list[dict[str, Any]]],
    feature_names: list[str] | None = None,
    horizon_sec: float = 480.0,
) -> dict[str, Any]:
    from desk.ic import CORE

    feature_names = feature_names or list(CORE)
    X, y, _ = build_xy_from_history(history, feature_names, horizon_sec)
    if len(X) < 20:
        return {"ok": False, "n": len(X), "reason": "insufficient_samples"}
    # walk-forward-ish: first 70% train, last 30% test
    cut = int(len(X) * 0.7)
    model = LogisticModel(len(feature_names))
    model.fit(X[:cut], y[:cut])
    # evaluate
    correct = 0
    brier = 0.0
    n_te = len(X) - cut
    for i in range(cut, len(X)):
        p = model.predict_proba(X[i])
        pred = 1 if p >= 0.5 else 0
        correct += int(pred == y[i])
        brier += (p - y[i]) ** 2
    return {
        "ok": True,
        "n": len(X),
        "n_train": cut,
        "n_test": n_te,
        "accuracy": round(correct / n_te, 3) if n_te else None,
        "brier": round(brier / n_te, 4) if n_te else None,
        "features": feature_names,
        "weights": [round(w, 4) for w in model.w],
        "bias": round(model.b, 4),
        "model": model,
    }


def expected_return_from_proba(p_up: float, scale: float = 0.01) -> float:
    """Map P(up) to a signed expected return heuristic."""
    return (p_up - 0.5) * 2.0 * scale
