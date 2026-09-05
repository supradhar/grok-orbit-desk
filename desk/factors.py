"""Phase 5 — factor hygiene: normalize, decay, attribution, ablation."""

from __future__ import annotations

from typing import Any

from desk.ic import CORE, _later_row, _pearson, factor_ics


def winsorize(xs: list[float], p: float = 0.05) -> list[float]:
    if len(xs) < 4:
        return list(xs)
    ordered = sorted(xs)
    lo = ordered[max(0, int(len(ordered) * p))]
    hi = ordered[min(len(ordered) - 1, int(len(ordered) * (1 - p)))]
    return [min(hi, max(lo, x)) for x in xs]


def zscore(xs: list[float]) -> tuple[list[float], float, float]:
    if len(xs) < 2:
        return list(xs), 0.0, 1.0
    mu = sum(xs) / len(xs)
    var = sum((x - mu) ** 2 for x in xs) / (len(xs) - 1)
    sd = var**0.5 or 1.0
    return [(x - mu) / sd for x in xs], mu, sd


def robust_zscore(xs: list[float]) -> tuple[list[float], float, float]:
    if len(xs) < 2:
        return list(xs), 0.0, 1.0
    ordered = sorted(xs)
    mid = len(ordered) // 2
    med = ordered[mid] if len(ordered) % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])
    abs_dev = sorted(abs(x - med) for x in xs)
    mad = abs_dev[len(abs_dev) // 2] or 1.0
    scale = 1.4826 * mad
    return [(x - med) / scale for x in xs], med, scale


def normalize_factor_cross_section(
    scores_by_symbol: dict[str, float],
    *,
    robust: bool = True,
) -> dict[str, dict[str, float]]:
    """Return {sym: {raw, z, mu/med, scale}} for one factor at one timestamp."""
    syms = list(scores_by_symbol)
    raw = [float(scores_by_symbol[s]) for s in syms]
    clipped = winsorize(raw)
    zs, center, scale = robust_zscore(clipped) if robust else zscore(clipped)
    return {
        s: {"raw": raw[i], "z": round(zs[i], 4), "center": center, "scale": scale}
        for i, s in enumerate(syms)
    }


def factor_decay(
    history: dict[str, list[dict[str, Any]]],
    factor: str,
    horizons_sec: list[float] | None = None,
) -> dict[str, Any]:
    horizons_sec = horizons_sec or [300, 900, 1800, 3600, 14400, 86400]
    out: dict[str, Any] = {}
    for h in horizons_sec:
        xs: list[float] = []
        ys: list[float] = []
        for rows in history.values():
            for i, a in enumerate(rows):
                facs = a.get("factors") or {}
                val = facs.get(factor)
                m0 = a.get("mark")
                if val is None or not m0:
                    continue
                b = _later_row(rows, i, h)
                if not b or not b.get("mark"):
                    continue
                xs.append(float(val))
                ys.append((float(b["mark"]) - float(m0)) / float(m0))
        ic = _pearson(xs, ys)
        out[str(int(h))] = {"ic": None if ic is None else round(ic, 3), "n": len(xs)}
    return out


def agent_attribution(
    history: dict[str, list[dict[str, Any]]],
    horizon_sec: float = 480.0,
    min_score: float = 8.0,
) -> list[dict[str, Any]]:
    """Per-factor OOS-style skill table from tape history."""
    rows_out: list[dict[str, Any]] = []
    ics = factor_ics(history, horizon_sec=horizon_sec)
    for fac in CORE:
        # Build pseudo-history keyed by factor score as signal
        hits = 0
        n = 0
        signed: list[float] = []
        for rows in history.values():
            for i, a in enumerate(rows):
                facs = a.get("factors") or {}
                val = facs.get(fac)
                m0 = a.get("mark")
                if val is None or not m0 or abs(float(val)) < min_score:
                    continue
                b = _later_row(rows, i, horizon_sec)
                if not b or not b.get("mark"):
                    continue
                ret = (float(b["mark"]) - float(m0)) / float(m0)
                n += 1
                good = (float(val) > 0 and ret > 0) or (float(val) < 0 and ret < 0)
                if good:
                    hits += 1
                signed.append(ret if float(val) > 0 else -ret)
        wins = [r for r in signed if r > 0]
        losses = [r for r in signed if r <= 0]
        p_win = (len(wins) / n) if n else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        expectancy = p_win * avg_win - (1 - p_win) * avg_loss if n else None
        gw = sum(wins)
        gl = abs(sum(losses))
        pf = (gw / gl) if gl > 1e-12 else None
        ic_row = ics.get(fac) or {}
        rows_out.append(
            {
                "factor": fac,
                "signal_count": n,
                "hit_rate": round(hits / n, 3) if n else None,
                "expectancy": None if expectancy is None else round(expectancy, 5),
                "ic": ic_row.get("ic"),
                "ic_n": ic_row.get("n"),
                "profit_factor": None if pf is None else round(pf, 3),
                "mean_return": round(sum(signed) / len(signed), 5) if signed else None,
            }
        )
    rows_out.sort(key=lambda r: (r.get("expectancy") is not None, r.get("expectancy") or -1e9), reverse=True)
    return rows_out


def ablation_study(
    history: dict[str, list[dict[str, Any]]],
    horizon_sec: float = 180.0,
    min_blend: float = 8.0,
) -> dict[str, Any]:
    """All-factor baseline vs remove-one-factor hit/expectancy deltas."""
    from desk.ic import blend_weights, weighted_blend
    from desk.models import FactorScore

    def synth_blend(rows_facs: dict[str, float | None], skip: str | None) -> float | None:
        factors = []
        for name, val in rows_facs.items():
            if val is None or name == skip:
                continue
            factors.append(
                FactorScore(
                    agent_id="ablation",
                    layer=1,
                    factor=name,
                    symbol="X",
                    score=float(val),
                    confidence=0.5,
                    note="",
                )
            )
        if not factors:
            return None
        w = {f: 1.0 for f in CORE}
        blend, _ = weighted_blend(factors, w)
        return blend

    def eval_skip(skip: str | None) -> dict[str, Any]:
        hits = n = 0
        signed: list[float] = []
        for rows in history.values():
            for i, a in enumerate(rows):
                facs = a.get("factors") or {}
                blend = synth_blend(facs, skip)
                m0 = a.get("mark")
                if blend is None or not m0 or abs(blend) < min_blend:
                    continue
                b = _later_row(rows, i, horizon_sec)
                if not b or not b.get("mark"):
                    continue
                ret = (float(b["mark"]) - float(m0)) / float(m0)
                n += 1
                if (blend > 0 and ret > 0) or (blend < 0 and ret < 0):
                    hits += 1
                signed.append(ret if blend > 0 else -ret)
        exp = (sum(signed) / len(signed)) if signed else None
        return {
            "n": n,
            "hit_rate": round(hits / n, 3) if n else None,
            "avg_signed_return": None if exp is None else round(exp, 5),
        }

    baseline = eval_skip(None)
    removals: dict[str, Any] = {}
    for fac in CORE:
        row = eval_skip(fac)
        removals[fac] = {
            **row,
            "delta_hit": None
            if baseline["hit_rate"] is None or row["hit_rate"] is None
            else round(row["hit_rate"] - baseline["hit_rate"], 3),
            "delta_return": None
            if baseline["avg_signed_return"] is None or row["avg_signed_return"] is None
            else round(row["avg_signed_return"] - baseline["avg_signed_return"], 5),
        }
    # Factors whose removal improves return are candidates to retire
    retire = [
        f
        for f, r in removals.items()
        if r.get("delta_return") is not None and r["delta_return"] > 0 and (r.get("n") or 0) >= 8
    ]
    return {"baseline": baseline, "remove_one": removals, "retire_candidates": retire}
