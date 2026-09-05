from __future__ import annotations

from typing import Any

from desk.llm import LocalLLM
from desk.models import AgentState, AnalysisReport, ChallengeReport, DecisionMemo, FactorScore, VerifiedFactorBook
from desk.scoring import clamp, utc_now
from desk.signal import alpha_score, residual_floor

LLM_COLOR = "#fde68a"


def spawn_llm_agents() -> list[AgentState]:
    roles = [
        (1, "llm-L1", "L1 factor LLM"),
        (2, "llm-L2", "L2 verifier LLM"),
        (3, "llm-L3", "L3 synthesis LLM"),
        (4, "llm-L4", "L4 advocate LLM"),
        (5, "llm-L5", "L5 head-of-desk LLM"),
    ]
    return [
        AgentState(
            id=aid,
            name=name,
            layer=layer,
            role="llm-agent",
            factor="llm",
            symbol=None,
            color=LLM_COLOR,
        )
        for layer, aid, name in roles
    ]


def bind_models(agents: list[AgentState], llm: LocalLLM) -> None:
    for layer, model in llm.layer_models.items():
        agent = next((a for a in agents if a.id == f"llm-L{layer}"), None)
        if agent:
            short = model.split(":")[0]
            agent.name = f"L{layer} {short}"
            agent.last_note = model


def _mark(agents: list[AgentState], layer: int, ok: bool, note: str, score: float | None = None) -> None:
    agent = next((a for a in agents if a.id == f"llm-L{layer}"), None)
    if not agent:
        return
    agent.status = "live" if ok else "idle"
    agent.last_note = note[:180]
    agent.last_score = score
    agent.last_beat = utc_now()


def _compact_factors(factors: list[FactorScore], symbols: set[str] | None = None, limit: int = 12) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for f in factors:
        if not f.symbol:
            continue
        if f.factor in {"article", "social_post"}:
            continue
        if symbols is not None and f.symbol not in symbols:
            continue
        out.setdefault(f.symbol, {})[f.factor] = round(f.score, 1)
    keys = list(out)[:limit]
    return {k: out[k] for k in keys}


def _symbol_map(data: dict[str, Any], symbols: list[str] | None = None) -> dict[str, Any]:
    if not data:
        return {}
    for key in ("books", "symbols", "data", "result", "items"):
        inner = data.get(key)
        if isinstance(inner, dict):
            data = inner
            break
        if isinstance(inner, list) and symbols:
            mapped: dict[str, Any] = {}
            for i, row in enumerate(inner):
                if isinstance(row, dict) and row.get("symbol"):
                    mapped[str(row["symbol"]).upper()] = row
                elif isinstance(row, dict) and i < len(symbols):
                    mapped[symbols[i]] = row
            if mapped:
                return mapped
    if symbols and len(symbols) == 1 and ("trust" in data or "veto" in data or "blended" in data):
        return {symbols[0]: data}
    return data


def _focus(
    books: list[VerifiedFactorBook],
    reports: list[AnalysisReport],
    focus_symbol: str | None = None,
    min_confluence: float = 16.0,
    limit: int = 5,
) -> list[str]:
    names: list[str] = []
    focus = (focus_symbol or "").upper().strip()
    if focus:
        names.append(focus)
    band: list[tuple[float, str]] = []
    for r in reports:
        if r.symbol in {"REGIME", focus} or not r.symbol:
            continue
        sig = abs(alpha_score(r))
        floor = min_confluence if r.symbol == "BTC" else residual_floor({"min_confluence": min_confluence})
        gap = abs(sig - floor)
        if sig >= floor * 0.65:
            band.append((gap, r.symbol))
    band.sort()
    for _, sym in band:
        if sym not in names:
            names.append(sym)
        if len(names) >= limit:
            break
    if len(names) < 2:
        heat = sorted(
            ((abs(b.blended_raw), b.symbol) for b in books if b.symbol not in names),
            reverse=True,
        )
        for _, sym in heat:
            names.append(sym)
            if len(names) >= min(3, limit):
                break
    return names[:limit]


def _turn(layer: int, to_layer: int, symbol: str, model: str, kind: str, text: str) -> dict[str, Any]:
    return {
        "from_layer": layer,
        "to_layer": to_layer,
        "symbol": symbol,
        "model": model,
        "kind": kind,
        "text": text[:220],
        "ts": utc_now(),
    }


async def run_l1(
    llm: LocalLLM,
    factors: list[FactorScore],
    marks: dict[str, float],
    agents: list[AgentState],
    symbols: list[str] | None = None,
    critique: str = "",
) -> tuple[bool, list[dict[str, Any]]]:
    focus = set(symbols) if symbols else None
    compact = _compact_factors(factors, focus)
    if not compact:
        _mark(agents, 1, False, "L1 LLM: nothing to score")
        return False, []
    headlines = [f.note for f in factors if f.factor == "news" and f.symbol and (not focus or f.symbol in focus)][:12]
    extra = f"\nL2 critique to answer: {critique}" if critique else ""
    mark_s = {k: round(v, 6) for k, v in list(marks.items())[:16] if not focus or k in focus}
    data = await llm.complete_json(
        prompt=(
            f"Marks: {mark_s}\n"
            f"Heuristic factor scores (-100..100): {compact}\n"
            f"News notes: {headlines}{extra}\n"
            'JSON only: {"SYMBOL": {"momentum": 0, "volume": 0, "news": 0, "note": "short"}}'
        ),
        system="L1 factor research. Judge factors only. Do not invent prints or news. Do not trade.",
        max_tokens=420,
        layer=1,
    )
    model = llm.model_for(1)
    if not data:
        _mark(agents, 1, False, f"L1 {model} skipped (no JSON)")
        return False, []
    now = utc_now()
    touched = 0
    debate: list[dict[str, Any]] = []
    for f in factors:
        row = data.get(f.symbol or "")
        if not isinstance(row, dict) or f.factor not in row:
            continue
        try:
            llm_score = clamp(float(row[f.factor]))
        except (TypeError, ValueError):
            continue
        f.score = clamp(0.4 * f.score + 0.6 * llm_score)
        f.confidence = min(1.0, f.confidence + 0.08)
        note = str(row.get("note") or "")
        if note:
            f.evidence = (f.evidence + [f"L1 {model}: {note[:120]}"])[:6]
            debate.append(_turn(1, 2, f.symbol or "", model, "revise" if critique else "score", note))
        f.sources = list(dict.fromkeys(f.sources + [f"ollama:{model}"]))
        f.ts = now
        touched += 1
    _mark(agents, 1, True, f"L1 {model} adjusted {touched} ticks", float(touched))
    return True, debate[:12]


async def run_l2(
    llm: LocalLLM,
    books: list[VerifiedFactorBook],
    agents: list[AgentState],
    symbols: list[str] | None = None,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    subset = [b for b in books if not symbols or b.symbol in symbols]
    payload = {
        b.symbol: {
            "trust": round(b.trust, 2),
            "flags": b.flags[:4],
            "blend": round(b.blended_raw, 1),
            "garbage": b.garbage,
        }
        for b in subset[:10]
    }
    data = await llm.complete_json(
        prompt=(
            f"Verifier books: {payload}\n"
            'JSON only: {"SYMBOL": {"trust": 0.0, "garbage": false, "flags": ["unknown_news"], "critique": "short"}, ...}'
        ),
        system="L2 verifier. Judge missing sources. Unknown news/social is not a quiet tape. Do not trade.",
        max_tokens=380,
        layer=2,
        temperature=0.1,
    )
    model = llm.model_for(2)
    data = _symbol_map(data or {}, [b.symbol for b in subset])
    if not data:
        _mark(agents, 2, False, f"L2 {model} skipped (no JSON)")
        return False, [], []
    n = 0
    debate: list[dict[str, Any]] = []
    disputed: list[str] = []
    for b in books:
        row = data.get(b.symbol)
        if not isinstance(row, dict):
            continue
        if "trust" in row:
            try:
                b.trust = max(0.0, min(1.0, float(row["trust"])))
            except (TypeError, ValueError):
                pass
        if "garbage" in row:
            b.garbage = bool(row["garbage"])
        extra = row.get("flags")
        if isinstance(extra, list):
            b.flags = list(dict.fromkeys(b.flags + [str(x)[:48] for x in extra[:4]]))
        critique = str(row.get("critique") or "")
        if critique:
            debate.append(_turn(2, 1, b.symbol, model, "critique", critique))
            disputed.append(b.symbol)
        if b.garbage or b.trust < 0.35:
            disputed.append(b.symbol)
        n += 1
    _mark(agents, 2, True, f"L2 {model} rewrote {n} books", float(n))
    return True, debate, list(dict.fromkeys(disputed))


async def run_l3(
    llm: LocalLLM,
    reports: list[AnalysisReport],
    agents: list[AgentState],
    attacks: dict[str, list[str]] | None = None,
    symbols: list[str] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    payload = {
        r.symbol: {
            "blended": round(r.blended, 1),
            "trust": round(r.trust, 2),
            "agreement": round(r.agreement, 2),
            "thesis": r.thesis[:160],
            "bull": r.bull_factors,
            "bear": r.bear_factors,
            "l4": (attacks or {}).get(r.symbol) or [],
        }
        for r in reports
        if r.symbol != "REGIME" and (not symbols or r.symbol in symbols)
    }
    if not payload:
        _mark(agents, 3, False, "L3 LLM: empty pack")
        return False, []
    mode = "Answer L4 attacks. Concede if they are right. Do not invent prices." if attacks else "Write the desk thesis. Do not place orders."
    data = await llm.complete_json(
        prompt=(
            f"Analyst pack: {payload}\n"
            'JSON only: {"regime": "neutral", "SYMBOL": {"blended": 0, "thesis": "2 sentences", "bull": [], "bear": [], "concede": false}}'
        ),
        system=f"L3 synthesis. {mode}",
        max_tokens=480,
        layer=3,
    )
    model = llm.model_for(3)
    if not data:
        _mark(agents, 3, False, f"L3 {model} skipped (no JSON)")
        return False, []
    regime = str(data.get("regime") or "")
    n = 0
    debate: list[dict[str, Any]] = []
    for r in reports:
        if regime and r.symbol == "REGIME":
            r.regime = regime
            r.thesis = f"LLM regime {regime}."
            n += 1
            continue
        row = data.get(r.symbol)
        if not isinstance(row, dict):
            continue
        if "blended" in row:
            try:
                r.blended = clamp(float(row["blended"]))
            except (TypeError, ValueError):
                pass
        if row.get("thesis"):
            r.thesis = str(row["thesis"])[:500]
        if isinstance(row.get("bull"), list):
            r.bull_factors = [str(x) for x in row["bull"][:4]]
        if isinstance(row.get("bear"), list):
            r.bear_factors = [str(x) for x in row["bear"][:4]]
        if regime:
            r.regime = regime
        if row.get("concede"):
            r.blended *= 0.55
            debate.append(_turn(3, 4, r.symbol, model, "concede", r.thesis[:180]))
        elif attacks and r.symbol in attacks:
            debate.append(_turn(3, 4, r.symbol, model, "revise", r.thesis[:180]))
        else:
            debate.append(_turn(3, 4, r.symbol, model, "thesis", r.thesis[:180]))
        n += 1
    _mark(agents, 3, True, f"L3 {model} wrote {n} theses", float(n))
    return True, debate[:16]


async def run_l4(
    llm: LocalLLM,
    challenges: list[ChallengeReport],
    reports: list[AnalysisReport],
    agents: list[AgentState],
    symbols: list[str] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    payload = {
        c.symbol: {
            "veto": c.veto,
            "adj": round(c.conviction_adj, 2),
            "attacks": c.attacks[:3],
            "blend": next((round(r.blended, 1) for r in reports if r.symbol == c.symbol), 0),
            "thesis": next((r.thesis[:140] for r in reports if r.symbol == c.symbol), ""),
        }
        for c in challenges
        if not symbols or c.symbol in symbols
    }
    data = await llm.complete_json(
        prompt=(
            f"Challenge pack: {payload}\n"
            'JSON only: {"SYMBOL": {"veto": false, "adj": 0.5, "attacks": ["hole"]}, ...}'
        ),
        system="L4 devil's advocate. Attack weak theses. Unknown tape is a hole. Stay on this resident model. Do not trade.",
        max_tokens=380,
        layer=4,
        temperature=0.25,
    )
    model = llm.model_for(4)
    data = _symbol_map(data or {}, list(payload))
    if not data:
        _mark(agents, 4, False, f"L4 {model} skipped (no JSON)")
        return False, []
    n = 0
    debate: list[dict[str, Any]] = []
    for c in challenges:
        row = data.get(c.symbol)
        if not isinstance(row, dict):
            continue
        if "veto" in row:
            c.veto = bool(row["veto"])
        if "adj" in row:
            try:
                c.conviction_adj = max(0.0, min(1.0, float(row["adj"])))
            except (TypeError, ValueError):
                pass
        if isinstance(row.get("attacks"), list) and row["attacks"]:
            c.attacks = [str(x)[:120] for x in row["attacks"][:5]]
        c.surviving_thesis = ("VETO " if c.veto else "After LLM challenge: ") + "; ".join(c.attacks[:2])
        debate.append(_turn(4, 3, c.symbol, model, "veto" if c.veto else "attack", "; ".join(c.attacks[:2])))
        n += 1
    _mark(agents, 4, True, f"L4 {model} challenged {n} names", float(n))
    return True, debate


async def run_l5(
    llm: LocalLLM,
    memos: list[DecisionMemo],
    reports: list[AnalysisReport],
    challenges: list[ChallengeReport],
    agents: list[AgentState],
    debate: list[dict[str, Any]] | None = None,
) -> bool:
    if not memos:
        _mark(agents, 5, True, "L5 LLM: no memos this tick", 0)
        return True
    payload = [
        {
            "id": m.id,
            "symbol": m.symbol,
            "side": m.side,
            "blend": next((round(r.blended, 1) for r in reports if r.symbol == m.symbol), 0),
            "attacks": next((c.attacks[:3] for c in challenges if c.symbol == m.symbol), m.risk_notes[:3]),
            "entry": m.entry,
            "stop": m.stop,
            "target": m.target,
            "talk": [
                d.get("text")
                for d in (debate or [])
                if d.get("symbol") == m.symbol
            ][-3:],
        }
        for m in memos[:4]
    ]
    data = await llm.complete_json(
        prompt=(
            f"Pending paper memos after layer debate: {payload}\n"
            'Return {"memos": [{"id": "...", "thesis": "2-3 sentences", "invalidation": "...", "keep": true}]}. '
            "Set keep=false to drop a weak idea."
        ),
        system="You are the L5 Head of Desk agent. Paper trading only. Skeptical. No hype. Weigh the layer debate.",
        max_tokens=550,
        layer=5,
    )
    model = llm.model_for(5)
    if not data:
        _mark(agents, 5, False, f"L5 {model} skipped (no JSON)")
        return False
    rows = data.get("memos") if isinstance(data.get("memos"), list) else []
    by_id = {m.id: m for m in memos}
    kept = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        m = by_id.get(str(row.get("id") or ""))
        if not m:
            continue
        if row.get("keep") is False:
            m.status = "expired"
            continue
        if row.get("thesis"):
            m.thesis = str(row["thesis"])[:700]
        if row.get("invalidation"):
            m.invalidation = str(row["invalidation"])[:300]
        kept += 1
    _mark(agents, 5, True, f"L5 {model} signed {kept} memos", float(kept))
    return True


async def run_research_committee(
    llm: LocalLLM,
    factors: list[FactorScore],
    books: list[VerifiedFactorBook],
    reports: list[AnalysisReport],
    challenges: list[ChallengeReport],
    marks: dict[str, float],
    agents: list[AgentState],
    rounds: int = 2,
    focus_symbol: str | None = None,
    min_confluence: float = 16.0,
    in_play: list[str] | None = None,
) -> tuple[dict[int, bool], list[dict[str, Any]]]:
    """L1↔L2 on resident qwen. Llama L3/L5 only for in-play names. L4 stays on qwen."""
    bind_models(agents, llm)
    used: dict[int, bool] = {1: False, 2: False, 3: False, 4: False}
    debate: list[dict[str, Any]] = []
    if not llm.ok:
        await llm.probe()
    if not llm.ok:
        for layer in range(1, 5):
            _mark(agents, layer, False, f"LLM offline: {llm.last_error}")
        return used, debate

    play = [s.upper() for s in (in_play or [])]
    if not play:
        play = _focus(books, reports, focus_symbol, min_confluence, limit=5)
    if focus_symbol and focus_symbol.upper() not in play:
        play = [focus_symbol.upper()] + play
    play = play[:6]

    ok1, d1 = await run_l1(llm, factors, marks, agents, play)
    used[1] = ok1
    debate.extend(d1)

    ok2, d2, disputed = await run_l2(llm, books, agents, play)
    used[2] = ok2
    debate.extend(d2)

    if rounds >= 2 and disputed and ok2:
        critique = "; ".join(t["text"] for t in d2[:4])
        ok1b, d1b = await run_l1(llm, factors, marks, agents, disputed[:6], critique=critique)
        used[1] = used[1] or ok1b
        debate.extend(d1b)
        ok2b, d2b, _ = await run_l2(llm, books, agents, disputed[:6])
        used[2] = used[2] or ok2b
        debate.extend(d2b)

    heavy = [
        r.symbol
        for r in reports
        if r.symbol != "REGIME"
        and r.symbol in play
        and abs(alpha_score(r)) >= (min_confluence if r.symbol == "BTC" else residual_floor({"min_confluence": min_confluence}))
    ]
    if not heavy:
        used[3] = True
        used[4] = True
        _mark(agents, 3, True, "L3/L4 skipped — nothing at confluence", 0)
        _mark(agents, 4, True, "L3/L4 skipped — nothing at confluence", 0)
        return used, debate[-40:]

    ok3, d3 = await run_l3(llm, reports, agents, symbols=heavy)
    used[3] = ok3
    debate.extend(d3)

    ok4, d4 = await run_l4(llm, challenges, reports, agents, heavy)
    used[4] = ok4
    debate.extend(d4)

    if rounds >= 2 and d4:
        hot = [c.symbol for c in challenges if c.symbol in heavy and (c.veto or c.conviction_adj < 0.85)][:6]
        if hot:
            attacks = {c.symbol: c.attacks[:3] for c in challenges if c.symbol in hot}
            ok3b, d3b = await run_l3(llm, reports, agents, attacks=attacks, symbols=hot)
            used[3] = used[3] or ok3b
            debate.extend(d3b)
            ok4b, d4b = await run_l4(llm, challenges, reports, agents, hot)
            used[4] = used[4] or ok4b
            debate.extend(d4b)

    return used, debate[-40:]
