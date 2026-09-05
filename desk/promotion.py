"""Promotion gate for any future strategy/factor/agent (Master Plan §22)."""

from __future__ import annotations

from typing import Any


def evaluate_promotion(evidence: dict[str, Any]) -> dict[str, Any]:
    """
    evidence keys (bool or None):
      data_quality, no_lookahead, sufficient_sample, oos_positive_expectancy,
      risk_adjusted_oos, cost_aware, regime_stable, acceptable_drawdown,
      correlation_ok, capacity_ok
    """
    steps = [
        "data_quality",
        "no_lookahead",
        "sufficient_sample",
        "oos_positive_expectancy",
        "risk_adjusted_oos",
        "cost_aware",
        "regime_stable",
        "acceptable_drawdown",
        "correlation_ok",
        "capacity_ok",
    ]
    failed: list[str] = []
    for s in steps:
        v = evidence.get(s)
        if v is not True:
            failed.append(s)
            break  # stop at first failure
    return {
        "promote": len(failed) == 0,
        "failed_at": failed[0] if failed else None,
        "checks": {s: bool(evidence.get(s) is True) for s in steps},
    }
