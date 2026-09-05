from __future__ import annotations

from typing import Any

BLEND_SKIP = {"article", "social_post", "sector"}
CORE = [
    "momentum",
    "volume",
    "volatility",
    "derivatives",
    "liquidity",
    "news",
    "social",
    "whales",
    "flows",
    "structure",
    "policy",
]


def _pearson(xs: list[float], ys: list[float], ws: list[float] | None = None) -> float | None:
    n = min(len(xs), len(ys))
    if n < 8:
        return None
    xs, ys = xs[:n], ys[:n]
    if ws:
        ws = ws[:n]
        wsum = sum(ws) or 1.0
        mx = sum(w * x for w, x in zip(ws, xs)) / wsum
        my = sum(w * y for w, y in zip(ws, ys)) / wsum
        num = sum(w * (x - mx) * (y - my) for w, x, y in zip(ws, xs, ys))
        dx = sum(w * (x - mx) ** 2 for w, x in zip(ws, xs)) ** 0.5
        dy = sum(w * (y - my) ** 2 for w, y in zip(ws, ys)) ** 0.5
    else:
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx < 1e-12 or dy < 1e-12:
        return 0.0
    return max(-1.0, min(1.0, num / (dx * dy)))


def factor_ics(history: dict[str, list[dict[str, Any]]], horizon_sec: float = 180.0) -> dict[str, dict[str, Any]]:
    by_fac: dict[str, list[tuple[float, float]]] = {f: [] for f in CORE}
    for rows in history.values():
        for i, a in enumerate(rows):
            m0 = a.get("mark")
            if not m0:
                continue
            b = _later_row(rows, i, horizon_sec)
            if not b or not b.get("mark"):
                continue
            ret = (float(b["mark"]) - float(m0)) / float(m0)
            facs = a.get("factors") or {}
            for f in CORE:
                val = facs.get(f)
                if val is None:
                    continue
                by_fac[f].append((float(val), ret))
    out: dict[str, dict[str, Any]] = {}
    for f, pairs in by_fac.items():
        ic = _pearson(
            [p[0] for p in pairs],
            [p[1] for p in pairs],
            [0.5 ** ((len(pairs) - 1 - i) / 16.0) for i in range(len(pairs))],
        )
        out[f] = {"ic": None if ic is None else round(ic, 3), "n": len(pairs)}
    return out


def _later_row(rows: list[dict[str, Any]], i: int, horizon_sec: float) -> dict[str, Any] | None:
    a = rows[i]
    t0 = a.get("ts")
    if t0:
        target = float(t0) + horizon_sec
        for nxt in rows[i + 1 :]:
            ts = nxt.get("ts")
            if ts and float(ts) >= target and nxt.get("mark"):
                return nxt
        return None
    hop = 6
    if i + hop < len(rows):
        return rows[i + hop]
    return None


def blend_weights(
    ics: dict[str, dict[str, Any]],
    shrink: float = 20.0,
    prior_mix: float = 0.6,
    cap: float = 0.22,
) -> dict[str, float]:
    prior = 1.0 / len(CORE)
    ic_w: dict[str, float] = {}
    for f in CORE:
        row = ics.get(f) or {}
        ic = row.get("ic")
        n = int(row.get("n") or 0)
        if ic is None or n < 8:
            ic_w[f] = 0.0
        else:
            ic_w[f] = max(0.0, float(ic) * n / (n + shrink))
    tot = sum(ic_w.values())
    mixed: dict[str, float] = {}
    for f in CORE:
        sample = (ic_w[f] / tot) if tot > 1e-9 else prior
        mixed[f] = min(cap, (1.0 - prior_mix) * sample + prior_mix * prior)
    s = sum(mixed.values()) or 1.0
    return {f: mixed[f] / s for f in CORE}


def mix_ic(ics: dict[str, dict[str, Any]], weights: dict[str, float]) -> float | None:
    acc = 0.0
    wsum = 0.0
    for f, w in weights.items():
        ic = (ics.get(f) or {}).get("ic")
        if ic is None:
            continue
        acc += float(ic) * w
        wsum += w
    if wsum <= 1e-9:
        return None
    return round(acc / wsum, 3)


def weighted_blend(factors: list[Any], weights: dict[str, float] | None = None) -> tuple[float, float]:
    """Returns (blend, known_weight). Unknown factors are dropped, not treated as 0."""
    weights = weights or {f: 1.0 for f in CORE}
    num = 0.0
    den = 0.0
    for f in factors:
        name = getattr(f, "factor", None)
        if name in BLEND_SKIP or name not in weights:
            continue
        if getattr(f, "unknown", False):
            continue
        if getattr(f, "symbol", True) is None:
            continue
        conf = max(float(getattr(f, "confidence", 0.2) or 0.2), 0.05)
        w = weights.get(name, 0.0) * conf
        if w <= 0:
            continue
        num += float(f.score) * w
        den += w
    if den <= 1e-9:
        return 0.0, 0.0
    return num / den, den
