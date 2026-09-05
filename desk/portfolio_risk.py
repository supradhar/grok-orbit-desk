"""Phase 7 — portfolio risk: vol targeting, covariance, CVaR, simple optimizer."""

from __future__ import annotations

import math
from typing import Any


def returns_from_marks(marks: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(marks)):
        a, b = marks[i - 1], marks[i]
        if a:
            out.append((b - a) / a)
    return out


def realized_vol(rets: list[float]) -> float:
    if len(rets) < 2:
        return 0.02
    mu = sum(rets) / len(rets)
    var = sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)
    return max(1e-6, var**0.5)


def vol_target_weight(target_vol: float, asset_vol: float, cap: float = 0.25) -> float:
    if asset_vol <= 0:
        return 0.0
    return min(cap, target_vol / asset_vol)


def cov_matrix(series: dict[str, list[float]]) -> tuple[list[str], list[list[float]]]:
    syms = [s for s, v in series.items() if len(v) >= 3]
    # align to min length
    n = min((len(series[s]) for s in syms), default=0)
    if n < 3 or not syms:
        return syms, []
    aligned = {s: series[s][-n:] for s in syms}
    means = {s: sum(aligned[s]) / n for s in syms}
    mat: list[list[float]] = []
    for a in syms:
        row: list[float] = []
        for b in syms:
            cov = sum((aligned[a][i] - means[a]) * (aligned[b][i] - means[b]) for i in range(n)) / (n - 1)
            row.append(cov)
        mat.append(row)
    return syms, mat


def portfolio_variance(weights: dict[str, float], syms: list[str], cov: list[list[float]]) -> float:
    if not cov:
        return 0.0
    idx = {s: i for i, s in enumerate(syms)}
    var = 0.0
    for a, wa in weights.items():
        if a not in idx:
            continue
        for b, wb in weights.items():
            if b not in idx:
                continue
            var += wa * wb * cov[idx[a]][idx[b]]
    return max(0.0, var)


def cvar(rets: list[float], alpha: float = 0.05) -> float | None:
    """Expected shortfall of loss distribution (positive = loss)."""
    if len(rets) < 5:
        return None
    losses = sorted(-r for r in rets)  # positive loss
    k = max(1, int(math.ceil(alpha * len(losses))))
    tail = losses[-k:] if k else losses
    # worst k losses
    worst = sorted(losses, reverse=True)[:k]
    return sum(worst) / len(worst)


def optimize_weights(
    alphas: dict[str, float],
    series: dict[str, list[float]],
    *,
    lam: float = 5.0,
    gamma: float = 0.01,
    prev: dict[str, float] | None = None,
    max_w: float = 0.2,
    gross_cap: float = 1.0,
    steps: int = 40,
) -> dict[str, float]:
    """
    Greedy projected ascent for max α'w − λ w'Σw − γ ||w−w_prev||₁
    under box and gross constraints. Deterministic, no external solver.
    """
    syms, cov = cov_matrix(series)
    if not syms:
        return {s: 0.0 for s in alphas}
    prev = prev or {}
    w = {s: 0.0 for s in syms}
    for _ in range(steps):
        # gradient of α − 2λ Σw − γ sign(w−prev)
        grad: dict[str, float] = {}
        for i, a in enumerate(syms):
            g = float(alphas.get(a) or 0.0)
            if cov:
                for j, b in enumerate(syms):
                    g -= 2 * lam * cov[i][j] * w[b]
            diff = w[a] - float(prev.get(a) or 0.0)
            g -= gamma * (1.0 if diff > 0 else -1.0 if diff < 0 else 0.0)
            grad[a] = g
        # step
        for a in syms:
            w[a] = w[a] + 0.05 * grad[a]
            w[a] = max(-max_w, min(max_w, w[a]))
        # project gross
        gross = sum(abs(x) for x in w.values())
        if gross > gross_cap and gross > 0:
            scale = gross_cap / gross
            w = {a: w[a] * scale for a in syms}
    return w


def stress_shocks(
    weights: dict[str, float],
    *,
    scenarios: dict[str, dict[str, float]] | None = None,
) -> dict[str, float]:
    """
    Apply factor/asset return shocks and report portfolio P&L under each scenario.
    scenarios: name -> {symbol: return}
    """
    scenarios = scenarios or {
        "crypto_crash": {"BTC": -0.15, "ETH": -0.18, "SOL": -0.25},
        "risk_on": {"BTC": 0.08, "ETH": 0.10, "SOL": 0.14},
        "gold_spike": {"XAUUSD": 0.05, "BTC": -0.03},
        "correlation_1": {"BTC": -0.10, "ETH": -0.10, "SOL": -0.10, "XAUUSD": -0.02},
        "liquidity_stress": {"BTC": -0.06, "ETH": -0.07, "SOL": -0.12, "XAUUSD": -0.01},
    }
    out: dict[str, float] = {}
    for name, shocks in scenarios.items():
        pnl = 0.0
        for sym, w in weights.items():
            pnl += w * float(shocks.get(sym) or 0.0)
        out[name] = round(pnl, 5)
    return out


def risk_snapshot(
    positions: dict[str, float],
    history_marks: dict[str, list[float]],
    *,
    target_vol: float = 0.01,
) -> dict[str, Any]:
    series = {s: returns_from_marks(ms) for s, ms in history_marks.items() if len(ms) >= 3}
    vols = {s: realized_vol(series.get(s) or []) for s in positions}
    target_w = {s: vol_target_weight(target_vol, vols.get(s, 0.02)) for s in positions}
    syms, cov = cov_matrix(series)
    gross = sum(abs(v) for v in positions.values()) or 1.0
    w = {s: positions.get(s, 0.0) / gross for s in positions}
    pvar = portfolio_variance(w, syms, cov)
    port_rets: list[float] = []
    if series:
        n = min(len(v) for v in series.values())
        for i in range(n):
            r = 0.0
            for s, wi in w.items():
                if s in series and len(series[s]) >= n:
                    r += wi * series[s][-n + i]
            port_rets.append(r)
    return {
        "asset_vols": {k: round(v, 5) for k, v in vols.items()},
        "vol_target_weights": {k: round(v, 4) for k, v in target_w.items()},
        "portfolio_vol": round(pvar**0.5, 5),
        "portfolio_variance": round(pvar, 8),
        "cvar_5": None if cvar(port_rets) is None else round(cvar(port_rets) or 0.0, 5),
        "weights": {k: round(v, 4) for k, v in w.items()},
        "gross": round(gross, 2),
        "stress": stress_shocks(w),
        "concentration": round(max((abs(x) for x in w.values()), default=0.0), 4),
    }
