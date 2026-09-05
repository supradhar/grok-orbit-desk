from __future__ import annotations

from typing import Any


def _later(rows: list[dict[str, Any]], i: int, horizon_sec: float, hop: int) -> dict[str, Any] | None:
    a = rows[i]
    t0 = a.get("ts")
    if t0:
        target = float(t0) + horizon_sec
        for nxt in rows[i + 1 :]:
            ts = nxt.get("ts")
            if ts and float(ts) >= target:
                return nxt
        return None
    if i + hop < len(rows):
        return rows[i + hop]
    return None


def _score(row: dict[str, Any]) -> float | None:
    if row.get("beta_ok") is False:
        return None
    if row.get("residual") is not None:
        return float(row["residual"])
    if row.get("blend") is not None:
        return float(row["blend"])
    return None


def _window(history: dict[str, list[dict[str, Any]]], horizon_sec: float, hop: int, min_score: float) -> dict[str, Any]:
    hits = 0
    n = 0
    signed: list[float] = []
    by_symbol: dict[str, dict[str, Any]] = {}
    for sym, rows in history.items():
        sh = 0
        sw = 0
        for i, a in enumerate(rows):
            b = _later(rows, i, horizon_sec, hop)
            if not b:
                continue
            score = _score(a)
            m0, m1 = a.get("mark"), b.get("mark")
            if score is None or not m0 or not m1:
                continue
            if abs(score) < min_score:
                continue
            ret = (float(m1) - float(m0)) / float(m0)
            n += 1
            sh += 1
            good = (score > 0 and ret > 0) or (score < 0 and ret < 0)
            if good:
                hits += 1
                sw += 1
            signed.append(ret if score > 0 else -ret)
        if sh:
            by_symbol[sym] = {"n": sh, "hit_rate": round(sw / sh, 3)}
    mins = max(1, int(round(horizon_sec / 60)))
    return {
        "horizon_ticks": hop,
        "horizon_sec": horizon_sec,
        "label": f"~{mins} min",
        "min_blend": min_score,
        "min_score": min_score,
        "n": n,
        "hit_rate": round(hits / n, 3) if n else None,
        "avg_signed_return": round(sum(signed) / len(signed), 5) if signed else None,
        "enough": n >= 8,
        "by_symbol": by_symbol,
    }


def _sliced(history: dict[str, list[dict[str, Any]]], start_frac: float, end_frac: float) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for sym, rows in history.items():
        n = len(rows)
        a = int(n * start_frac)
        b = max(a + 1, int(n * end_frac))
        chunk = rows[a:b]
        if len(chunk) >= 4:
            out[sym] = chunk
    return out


def _persist(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 2:
        return False
    a, b = _score(rows[-2]), _score(rows[-1])
    if a is None or b is None or a == 0 or b == 0:
        return False
    return (a > 0) == (b > 0)


def skill_map(history: dict[str, list[dict[str, Any]]], min_score: float = 8.8, horizon_sec: float = 480.0) -> dict[str, dict[str, Any]]:
    hop = 12 if horizon_sec >= 400 else 6
    win = _window(history, horizon_sec, hop, min_score)
    out: dict[str, dict[str, Any]] = {}
    for sym, rows in history.items():
        row = dict(win["by_symbol"].get(sym) or {})
        row["persist"] = _persist(rows)
        row["n"] = int(row.get("n") or 0)
        out[sym] = row
    return out


def research_quality(history: dict[str, list[dict[str, Any]]], min_blend: float = 16.0) -> dict[str, Any]:
    near = _window(history, 180, 6, min_blend)
    far = _window(history, 480, 12, min_blend)
    is_w = _window(_sliced(history, 0.0, 0.6), 180, 6, min_blend)
    oos_w = _window(_sliced(history, 0.6, 1.0), 180, 6, min_blend)
    enough = near["enough"] and oos_w["n"] >= 4
    return {
        "next_6": near,
        "next_12": far,
        "score": "residual",
        "walk_forward": {
            "in_sample": {"n": is_w["n"], "hit_rate": is_w["hit_rate"]},
            "out_of_sample": {"n": oos_w["n"], "hit_rate": oos_w["hit_rate"]},
            "enough": enough,
        },
        "note": (
            "Hit rate is residual (idio) sign vs later mark. Walk-forward is first 60% vs last 40% of tape. "
            "Promotion uses ~8 min skill + trust + persist — not the raw 3 min book."
            if not enough
            else "Idio residual vs later mark — research skill, not P&L. Promotion gates on ~8 min hit rate, trust, and sign persistence."
        ),
    }
