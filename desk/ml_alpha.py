"""Phase 10 — ML alpha: logistic + LightGBM/sklearn when available + model registry."""

from __future__ import annotations

import math
import random
import time
from typing import Any, Protocol

from desk.ic import CORE


def _sigmoid(x: float) -> float:
    if x >= 20:
        return 1.0
    if x <= -20:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


class Predictor(Protocol):
    def predict_proba_row(self, x: list[float]) -> float: ...


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

    def predict_proba_row(self, x: list[float]) -> float:
        return self.predict_proba(x)

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


class SklearnWrapper:
    def __init__(self, model: Any) -> None:
        self.model = model

    def predict_proba_row(self, x: list[float]) -> float:
        import numpy as np

        proba = self.model.predict_proba(np.asarray([x], dtype=float))[0]
        # class 1 probability if binary
        if len(proba) >= 2:
            return float(proba[1])
        return float(proba[0])


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


def _fit_lightgbm(X: list[list[float]], y: list[int]) -> Predictor | None:
    try:
        import lightgbm as lgb
        import numpy as np
    except Exception:
        return None
    model = lgb.LGBMClassifier(
        n_estimators=40,
        max_depth=3,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.9,
        verbose=-1,
    )
    model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
    return SklearnWrapper(model)


def _fit_sklearn_gbm(X: list[list[float]], y: list[int]) -> Predictor | None:
    try:
        from sklearn.ensemble import GradientBoostingClassifier, HistGradientBoostingClassifier
        import numpy as np
    except Exception:
        return None
    try:
        model = HistGradientBoostingClassifier(max_depth=3, max_iter=40, learning_rate=0.08)
        model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return SklearnWrapper(model)
    except Exception:
        model = GradientBoostingClassifier(n_estimators=40, max_depth=2, learning_rate=0.08)
        model.fit(np.asarray(X, dtype=float), np.asarray(y, dtype=int))
        return SklearnWrapper(model)


def _eval(model: Predictor, X: list[list[float]], y: list[int]) -> dict[str, Any]:
    if not X:
        return {"accuracy": None, "brier": None, "n": 0}
    correct = 0
    brier = 0.0
    for i, row in enumerate(X):
        p = model.predict_proba_row(row)
        pred = 1 if p >= 0.5 else 0
        correct += int(pred == y[i])
        brier += (p - y[i]) ** 2
    n = len(X)
    return {"accuracy": round(correct / n, 3), "brier": round(brier / n, 4), "n": n}


def train_models(
    history: dict[str, list[dict[str, Any]]],
    feature_names: list[str] | None = None,
    horizon_sec: float = 480.0,
) -> dict[str, Any]:
    feature_names = feature_names or list(CORE)
    X, y, _ = build_xy_from_history(history, feature_names, horizon_sec)
    if len(X) < 30:
        return {"ok": False, "n": len(X), "reason": "insufficient_samples"}
    cut = int(len(X) * 0.7)
    Xtr, ytr, Xte, yte = X[:cut], y[:cut], X[cut:], y[cut:]

    logistic = LogisticModel(len(feature_names))
    logistic.fit(Xtr, ytr)
    results: dict[str, Any] = {
        "ok": True,
        "n": len(X),
        "n_train": cut,
        "n_test": len(Xte),
        "features": feature_names,
        "models": {
            "logistic": {
                **_eval(logistic, Xte, yte),
                "weights": [round(w, 4) for w in logistic.w],
                "bias": round(logistic.b, 4),
            }
        },
    }

    lgbm = _fit_lightgbm(Xtr, ytr)
    if lgbm is not None:
        results["models"]["lightgbm"] = _eval(lgbm, Xte, yte)
    gbm = _fit_sklearn_gbm(Xtr, ytr)
    if gbm is not None:
        results["models"]["sklearn_gbm"] = _eval(gbm, Xte, yte)

    # pick best by accuracy then brier
    best_name = "logistic"
    best_acc = results["models"]["logistic"].get("accuracy") or -1
    for name, row in results["models"].items():
        acc = row.get("accuracy")
        if acc is not None and acc > best_acc:
            best_acc = acc
            best_name = name
    results["best"] = best_name
    results["registry"] = register_model(
        {
            "kind": best_name,
            "features": feature_names,
            "metrics": results["models"][best_name],
            "n_train": cut,
            "n_test": len(Xte),
            "horizon_sec": horizon_sec,
        }
    )
    return results


def train_logistic_alpha(
    history: dict[str, list[dict[str, Any]]],
    feature_names: list[str] | None = None,
    horizon_sec: float = 480.0,
) -> dict[str, Any]:
    """Backward-compatible wrapper."""
    out = train_models(history, feature_names, horizon_sec)
    if not out.get("ok"):
        return out
    log = out["models"]["logistic"]
    return {
        "ok": True,
        "n": out["n"],
        "n_train": out["n_train"],
        "n_test": out["n_test"],
        "accuracy": log.get("accuracy"),
        "brier": log.get("brier"),
        "features": out["features"],
        "weights": log.get("weights"),
        "bias": log.get("bias"),
        "best": out.get("best"),
        "all_models": out["models"],
        "registry": out.get("registry"),
    }


def register_model(payload: dict[str, Any]) -> dict[str, Any]:
    from desk.manifest import _git_commit
    from desk.research_db import ResearchDB

    model_id = f"m-{int(time.time())}-{payload.get('kind', 'model')}"
    row = {
        "model_id": model_id,
        "created_at": time.time(),
        "kind": payload.get("kind"),
        "train_range": f"n_train={payload.get('n_train')}",
        "features": payload.get("features") or [],
        "metrics": payload.get("metrics") or {},
        "git_commit": _git_commit(),
    }
    try:
        db = ResearchDB()
        db.record_model(row)
        db.close()
    except Exception:
        pass
    return row


def expected_return_from_proba(p_up: float, scale: float = 0.01) -> float:
    return (p_up - 0.5) * 2.0 * scale
