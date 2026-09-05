"""Phase 9 — LLM structured evidence packets and A/B/C study harness."""

from __future__ import annotations

import json
from typing import Any


def evidence_packet(
    *,
    symbol: str,
    factors: dict[str, float],
    mark: float | None,
    regime: str | None,
    blend: float | None,
    trust: float | None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "mark": mark,
        "regime": regime,
        "blend": blend,
        "trust": trust,
        "factors": factors,
        "rules": [
            "Use only numbers present in this packet.",
            "Do not invent prices, news, or macro prints.",
            "If evidence is insufficient, set direction to NO_TRADE.",
        ],
    }


def validate_llm_json(raw: str | dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    """Parse and sanitize LLM output; strip numeric claims not in the packet."""
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            # try extract first {...}
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    data = json.loads(raw[start : end + 1])
                except Exception:
                    data = {}
            else:
                data = {}
    else:
        data = dict(raw)
    direction = str(data.get("direction") or "NO_TRADE").upper()
    if direction not in {"LONG", "SHORT", "NO_TRADE"}:
        direction = "NO_TRADE"
    conf = data.get("confidence")
    try:
        confidence = max(0.0, min(1.0, float(conf))) if conf is not None else 0.0
    except Exception:
        confidence = 0.0
    # Reject fabricated marks
    claimed_mark = data.get("mark")
    if claimed_mark is not None and packet.get("mark") is not None:
        try:
            if abs(float(claimed_mark) - float(packet["mark"])) > 1e-6:
                direction = "NO_TRADE"
                confidence = 0.0
        except Exception:
            direction = "NO_TRADE"
    return {
        "direction": direction,
        "confidence": confidence,
        "thesis": str(data.get("thesis") or "")[:400],
        "contradictions": list(data.get("contradictions") or [])[:8],
        "evidence_requirements": list(data.get("evidence_requirements") or [])[:8],
        "risk_flags": list(data.get("risk_flags") or [])[:8],
        "invalidators": list(data.get("invalidators") or [])[:8],
        "packet_symbol": packet.get("symbol"),
    }


def ab_study_specs() -> list[dict[str, str]]:
    return [
        {"id": "A", "name": "deterministic_only", "llm": "off", "debate": "off"},
        {"id": "B", "name": "deterministic_plus_llm", "llm": "on", "debate": "off"},
        {"id": "C", "name": "deterministic_llm_adversarial", "llm": "on", "debate": "on"},
    ]


def compare_study_runs(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare A/B/C metric dicts (sharpe, return, drawdown, expectancy, trades)."""
    keys = ["sharpe", "total_return", "max_drawdown", "expectancy", "n_trades", "win_rate"]
    table: dict[str, Any] = {}
    for rid, metrics in runs.items():
        table[rid] = {k: metrics.get(k) for k in keys}
    # incremental: B vs A, C vs A
    base = runs.get("A") or {}
    deltas: dict[str, Any] = {}
    for rid in ("B", "C"):
        m = runs.get(rid) or {}
        deltas[f"{rid}_minus_A"] = {
            k: None
            if base.get(k) is None or m.get(k) is None
            else round(float(m[k]) - float(base[k]), 4)
            for k in ("sharpe", "total_return", "max_drawdown", "expectancy")
        }
    return {"systems": table, "deltas": deltas, "specs": ab_study_specs()}
