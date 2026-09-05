from __future__ import annotations

from typing import Any

from desk.scoring import utc_now


def alpha_score(rep: Any) -> float:
    """BTC and non-crypto (yahoo) use tape blend; crypto alts use idiosyncratic residual when beta exists."""
    if getattr(rep, "symbol", None) == "BTC" or getattr(rep, "standalone", False):
        return float(getattr(rep, "blended", 0) or 0)
    if not getattr(rep, "beta_ok", False):
        return float(getattr(rep, "blended", 0) or 0)
    resid = getattr(rep, "residual", None)
    if resid is not None:
        return float(resid)
    return float(getattr(rep, "blended", 0) or 0)


def residual_floor(cfg: dict[str, Any] | None = None) -> float:
    cfg = cfg or {}
    if cfg.get("min_residual") is not None:
        return float(cfg["min_residual"])
    return float(cfg.get("min_confluence") or 22) * 0.4


def promote_ok(rep: Any, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or {}
    floor = float(cfg.get("min_confluence") or 22)
    if getattr(rep, "symbol", None) == "BTC":
        return abs(float(getattr(rep, "blended", 0) or 0)) >= floor
    if getattr(rep, "standalone", False):
        return abs(float(getattr(rep, "blended", 0) or 0)) >= max(14.0, floor * 0.65)
    if not getattr(rep, "beta_ok", False):
        return False
    return abs(alpha_score(rep)) >= residual_floor(cfg)


def _returns(rows: list[dict[str, Any]]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1].get("mark"), rows[i].get("mark")
        if not a or not b:
            continue
        out.append((float(b) - float(a)) / float(a))
    return out


def _ols_beta(y: list[float], x: list[float]) -> float | None:
    n = min(len(y), len(x))
    if n < 8:
        return None
    y, x = y[-n:], x[-n:]
    mx = sum(x) / n
    my = sum(y) / n
    den = sum((xi - mx) ** 2 for xi in x)
    if den < 1e-18:
        return 0.0
    beta = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / den
    return max(-0.2, min(2.4, beta))


def btc_betas(history: dict[str, list[dict[str, Any]]], skip: set[str] | None = None) -> dict[str, float]:
    skip = skip or set()
    btc = _returns(history.get("BTC") or [])
    out: dict[str, float] = {"BTC": 1.0}
    if len(btc) < 8:
        return out
    for sym, rows in history.items():
        if sym == "BTC" or sym in skip:
            continue
        beta = _ols_beta(_returns(rows), btc)
        if beta is not None:
            out[sym] = round(beta, 3)
    return out


def news_hawkes(factors: list[Any], now: float | None = None, half_life: float = 240.0) -> dict[str, float]:
    now = now or utc_now()
    lam: dict[str, float] = {}
    decay = 0.693 / max(half_life, 1.0)
    for f in factors:
        if getattr(f, "factor", None) != "article":
            continue
        sym = getattr(f, "symbol", None)
        if not sym:
            continue
        age = max(0.0, now - float(getattr(f, "ts", now) or now))
        lam[sym] = lam.get(sym, 0.0) + 2.718 ** (-decay * age)
    return {k: round(v, 3) for k, v in lam.items()}


def lead_lag(history: dict[str, list[dict[str, Any]]], anchor: str = "BTC") -> list[dict[str, Any]]:
    """If corr(anchor_t, name_{t+k}) peaks at k>0, anchor leads."""
    src = _returns(history.get(anchor) or [])
    if len(src) < 12:
        return []
    edges: list[dict[str, Any]] = []
    for sym, rows in history.items():
        if sym == anchor:
            continue
        tgt = _returns(rows)
        n = min(len(src), len(tgt))
        if n < 12:
            continue
        a, b = src[-n:], tgt[-n:]
        best = (0.0, 0)
        for k in (1, 2, 3, 5):
            if n - k < 10:
                continue
            xs, ys = a[: n - k], b[k:]
            mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            dx = sum((x - mx) ** 2 for x in xs) ** 0.5
            dy = sum((y - my) ** 2 for y in ys) ** 0.5
            if dx < 1e-12 or dy < 1e-12:
                continue
            c = max(-1.0, min(1.0, num / (dx * dy)))
            if abs(c) > abs(best[0]):
                best = (c, k)
        corr, lag = best
        if abs(corr) < 0.18:
            continue
        edges.append(
            {
                "from": anchor if lag >= 0 else sym,
                "to": sym if lag >= 0 else anchor,
                "lag": lag,
                "corr": round(corr, 3),
            }
        )
    edges.sort(key=lambda e: -abs(e["corr"]))
    return edges[:8]


def hmm_state(
    reports: list[Any],
    books: list[Any],
    watch: set[str] | None = None,
    prev: str | None = None,
    exclude: set[str] | None = None,
) -> dict[str, Any]:
    # Crypto breadth/energy only — metals/FX standalone must not drive panic/compression.
    excl = exclude or set()
    names = [
        r
        for r in reports
        if getattr(r, "symbol", None)
        and r.symbol not in excl
        and (watch is None or r.symbol in watch)
    ]
    if not names:
        return {"state": prev or "unknown", "breadth": 0.0, "energy": 0.0}
    blends = [float(r.blended) for r in names]
    breadth = sum(1 for b in blends if b > 8) / len(blends)
    energy = sum(abs(b) for b in blends) / (100.0 * len(blends))
    glob = [f for b in books for f in getattr(b, "factors", []) if f.symbol is None]
    vix = next((f.score for f in glob if f.factor == "macro_vix"), 0.0)
    if vix < -22 or (energy > 0.28 and breadth < 0.25):
        raw = "panic"
    elif energy < 0.11:
        raw = "compression"
    elif breadth > 0.62:
        raw = "expansion"
    else:
        raw = "rotation"
    state = raw
    if prev and prev != "unknown" and raw != prev:
        if raw == "panic":
            state = "panic"
        elif prev == "panic" and (vix < -18 or (energy > 0.22 and breadth < 0.32)):
            state = "panic"
        elif prev == "expansion" and breadth > 0.50:
            state = prev
        elif prev == "compression" and energy < 0.16:
            state = prev
        elif prev == "rotation" and 0.28 < breadth < 0.70 and energy >= 0.09:
            state = prev
        else:
            state = raw
    return {"state": state, "raw": raw, "breadth": round(breadth, 3), "energy": round(energy, 3)}


def annotate(
    reports: list[Any],
    history: dict[str, list[dict[str, Any]]],
    factors: list[Any],
    books: list[Any],
    watch: set[str] | None = None,
    prev_hmm: str | None = None,
    standalone: set[str] | None = None,
) -> dict[str, Any]:
    stand = standalone or set()
    betas = btc_betas(history, skip=stand)
    hawkes = news_hawkes(factors)
    btc = next((r for r in reports if r.symbol == "BTC"), None)
    btc_blend = float(btc.blended) if btc else 0.0
    hmm = hmm_state(reports, books, watch, prev=prev_hmm, exclude=stand)
    graph = lead_lag(history)
    for r in reports:
        if r.symbol in {None, "REGIME"}:
            continue
        if watch and r.symbol not in watch:
            continue
        if r.symbol == "BTC" or r.symbol in stand:
            r.beta = 1.0 if r.symbol == "BTC" else 0.0
            r.beta_ok = True
            r.standalone = r.symbol != "BTC"
            r.residual = round(float(r.blended), 2)
            beta_txt = "standalone (no BTC β)" if r.symbol != "BTC" else "β 1.00"
        elif r.symbol in betas:
            beta = float(betas[r.symbol])
            r.beta = beta
            r.beta_ok = True
            r.standalone = False
            r.residual = round(float(r.blended) - beta * btc_blend, 2)
            beta_txt = f"β {r.beta:.2f}"
        else:
            r.beta = 0.0
            r.beta_ok = False
            r.standalone = False
            r.residual = round(float(r.blended), 2)
            beta_txt = "β n/a"
        r.sigma = round(max(4.0, (1.0 - float(r.agreement or 0.5)) * 55.0), 1)
        r.hawkes = float(hawkes.get(r.symbol) or 0.0)
        r.thesis += (
            f" Idio {r.residual:+.1f} ({beta_txt} vs BTC, σ {r.sigma:.0f}). "
            f"News λ {r.hawkes:.2f}. HMM {hmm['state']}."
        )
    return {"betas": betas, "graph": graph, "hmm": hmm, "hawkes": hawkes}
