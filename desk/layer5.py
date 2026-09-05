from __future__ import annotations

import uuid
from typing import Any

from desk.models import (
    AgentState,
    AnalysisReport,
    Asset,
    ChallengeReport,
    DecisionMemo,
    VerifiedFactorBook,
)
from desk.scoring import utc_now
from desk.signal import alpha_score, residual_floor

COLOR = "#fbbf24"


def spawn_agents() -> list[AgentState]:
    return [
        AgentState(
            id="l5-HOD",
            name="Head of Desk",
            layer=5,
            role="head-of-desk",
            factor="memo",
            symbol=None,
            color=COLOR,
        )
    ]


def _atr_pct(snap: dict[str, Any], symbol: str) -> float:
    t = (snap.get("tickers") or {}).get(symbol) or {}
    px = float(t.get("price") or 0)
    high = float(t.get("high") or 0)
    low = float(t.get("low") or 0)
    if px and high and low and high > low:
        return (high - low) / px
    return 0.025


def promotion_checks(
    rep: AnalysisReport,
    ch: ChallengeReport,
    book: VerifiedFactorBook,
    cfg: dict[str, Any],
    mix_ic: float | None,
    news_weight: float,
    skill: dict[str, Any] | None = None,
    hmm: str | None = None,
) -> dict[str, Any]:
    min_conf = float(cfg.get("min_confidence") or 0.38)
    min_trust = float(cfg.get("min_trust") or 0.55)
    min_confluence = float(cfg.get("min_confluence") or 22)
    min_skill = float(cfg.get("min_skill") or 0.48)
    min_skill_n = int(cfg.get("min_skill_n") or 8)
    unknown_news = "unknown_news" in book.flags or "unknown_tape" in book.flags
    news_waived = unknown_news and news_weight < 0.05
    resid = float(getattr(rep, "residual", 0) or 0)
    sigma = float(getattr(rep, "sigma", 0) or 0)
    beta_ok = bool(getattr(rep, "beta_ok", False)) or rep.symbol == "BTC"
    sig = alpha_score(rep)
    conf_floor = min_confluence if rep.symbol == "BTC" else residual_floor(cfg)
    if getattr(rep, "standalone", False) and rep.symbol != "BTC":
        # Metals/FX have fewer CORE factors — still require a clear lean, not crypto residual floor.
        conf_floor = max(14.0, min_confluence * 0.65)
    skill_row = skill or {}
    skill_n = int(skill_row.get("n") or 0)
    skill_hit = skill_row.get("hit_rate")
    persist = bool(skill_row.get("persist"))
    hmm_state = (hmm or "").split("·")[-1].strip()
    standalone = bool(getattr(rep, "standalone", False)) or rep.symbol == "BTC"
    # Crypto HMM compression = risk-off alts; for gold/FX that can be bullish — waive crypto regime.
    if standalone and rep.symbol != "BTC":
        side_ok = True
    else:
        long_ok = hmm_state in {"", "unknown", "expansion", "rotation"}
        short_ok = hmm_state in {"", "unknown", "compression", "panic", "rotation"}
        side_ok = (sig >= 0 and long_ok) or (sig < 0 and short_ok)
    # Standalone metals: slightly softer trust floor (fewer CORE factors available).
    trust_floor = min_trust * (0.85 if standalone and rep.symbol != "BTC" else 1.0)
    # Skill: cold-start waiver, then softer hit-rate for sticky metals marks.
    skill_floor = 0.40 if standalone and rep.symbol != "BTC" else min_skill
    skill_ok = skill_n >= min_skill_n and skill_hit is not None and float(skill_hit) >= skill_floor
    if standalone and rep.symbol != "BTC" and skill_n < min_skill_n:
        skill_ok = True  # building track record after mark feed restored
    checks = {
        "trust": book.trust >= trust_floor,
        "confluence": abs(sig) >= conf_floor,
        "confidence": rep.confidence >= min_conf,
        "l4": not ch.veto,
        "not_garbage": not book.garbage,
        "news": (not unknown_news) or news_waived,
        "ic": mix_ic is None or mix_ic > 0.02,
        "idio": rep.symbol == "BTC" or getattr(rep, "standalone", False) or (beta_ok and abs(resid) >= conf_floor),
        "precision": sigma < 32 or abs(sig) >= 1.4 * sigma,
        "skill": skill_ok,
        "persist": persist or (standalone and rep.symbol != "BTC" and skill_n < 2),
        "regime": side_ok,
    }
    checks["ok"] = all(checks.values())
    checks["news_waived"] = news_waived
    checks["mix_ic"] = mix_ic
    checks["skill_hit"] = skill_hit
    checks["skill_n"] = skill_n
    return checks


def recommend(
    reports: list[AnalysisReport],
    challenges: list[ChallengeReport],
    books: list[VerifiedFactorBook],
    snap: dict[str, Any],
    assets: list[Asset],
    agents: list[AgentState],
    cfg: dict[str, Any],
    equity: float,
    existing: list[DecisionMemo],
    committee_ok: bool = True,
    mix_ic: float | None = None,
    ic_weights: dict[str, float] | None = None,
    halted: bool = False,
    skill_by_symbol: dict[str, dict[str, Any]] | None = None,
    hmm: str | None = None,
) -> tuple[list[DecisionMemo], dict[str, dict[str, Any]]]:
    now = utc_now()
    hod = next((a for a in agents if a.id == "l5-HOD"), None)
    min_conf = float(cfg.get("min_confidence") or 0.38)
    min_confluence = float(cfg.get("min_confluence") or 42)
    max_pos = float(cfg.get("max_position_pct") or 0.12)
    memos: list[DecisionMemo] = []
    checklists: dict[str, dict[str, Any]] = {}
    pending_keys = {(m.symbol, m.side) for m in existing if m.status == "pending"}
    notes: list[str] = []
    news_w = float((ic_weights or {}).get("news") or 0.1)
    ch_map = {c.symbol: c for c in challenges}
    book_map = {b.symbol: b for b in books}
    skill_map = skill_by_symbol or {}
    for asset in assets:
        rep = next((r for r in reports if r.symbol == asset.symbol), None)
        ch = ch_map.get(asset.symbol)
        book = book_map.get(asset.symbol)
        if rep and ch and book:
            checklists[asset.symbol] = promotion_checks(
                rep, ch, book, cfg, mix_ic, news_w, skill_map.get(asset.symbol), hmm
            )
    if halted:
        notes.append("L5 blocked: desk halted — daily loss cap.")
        if hod:
            hod.status = "idle"
            hod.last_score = 0.0
            hod.last_note = notes[0]
            hod.last_beat = now
        return memos, checklists
    if not committee_ok:
        notes.append("L5 blocked: L2 verifier or L4 advocate did not finish.")
        if hod:
            hod.status = "idle"
            hod.last_score = 0.0
            hod.last_note = notes[0]
            hod.last_beat = now
        return memos, checklists

    for asset in assets:
        rep = next((r for r in reports if r.symbol == asset.symbol), None)
        ch = ch_map.get(asset.symbol)
        book = book_map.get(asset.symbol)
        if not rep or not ch or not book:
            continue
        card = promotion_checks(rep, ch, book, cfg, mix_ic, news_w, skill_map.get(asset.symbol), hmm)
        checklists[asset.symbol] = card
        if not card["ok"]:
            fail = [k for k, v in card.items() if k not in {"ok", "news_waived", "mix_ic", "skill_hit", "skill_n"} and not v]
            notes.append(f"skip {asset.symbol}: " + ",".join(fail[:4]))
            continue
        sig = alpha_score(rep)
        conf_floor = min_confluence if asset.symbol == "BTC" else residual_floor(cfg)
        if getattr(rep, "standalone", False) and asset.symbol != "BTC":
            conf_floor = max(14.0, min_confluence * 0.65)
        conviction = min(1.0, abs(sig) / 100.0 * ch.conviction_adj * (0.5 + 0.5 * rep.agreement))
        if conviction * 100 < conf_floor * 0.5:
            notes.append(f"skip {asset.symbol}: conviction too low")
            continue
        side = "long" if sig > 0 else "short"
        if (asset.symbol, side) in pending_keys:
            notes.append(f"skip {asset.symbol}: pending {side} already")
            continue
        px = float((snap.get("marks") or {}).get(asset.symbol) or 0)
        if not px:
            notes.append(f"skip {asset.symbol}: no mark")
            continue
        atr = _atr_pct(snap, asset.symbol)
        stop_dist = max(0.012, min(0.08, atr * 1.35))
        tgt_dist = stop_dist * 1.8
        if side == "long":
            stop = px * (1 - stop_dist)
            target = px * (1 + tgt_dist)
        else:
            stop = px * (1 + stop_dist)
            target = px * (1 - tgt_dist)
        hit = float(card.get("skill_hit") or 0.5)
        skill_mult = min(1.2, max(0.35, hit / 0.5))
        size = equity * max_pos * max(0.25, conviction) * skill_mult
        local = [f for f in book.factors if f.symbol == asset.symbol and f.factor not in {"article", "social_post"} and not getattr(f, "unknown", False)]
        top = [f.factor for f in sorted(local, key=lambda x: -abs(x.score))[:4]]
        invalidation = (
            f"Invalidate if price crosses {stop:.6g} or if L2 trust drops below 0.25 "
            f"or regime flips against the {side}."
        )
        thesis = (
            f"{asset.symbol} {side.upper()} memo. Idio {sig:+.1f} (blend {rep.blended:+.1f}, "
            f"β {float(getattr(rep, 'beta', 0) or 0):.2f}) after L4 ×{ch.conviction_adj:.2f}. "
            f"8-min skill {hit:.0%} on n={int(card.get('skill_n') or 0)}, persist, trust {book.trust:.2f}. "
            f"{ch.surviving_thesis} Why now: confluence across {', '.join(top) or 'verified factors'} "
            f"in a {rep.regime} regime."
        )
        memo = DecisionMemo(
            id=uuid.uuid4().hex[:10],
            symbol=asset.symbol,
            side=side,
            conviction=conviction,
            size_usd=round(size, 2),
            entry=px,
            stop=round(stop, 8),
            target=round(target, 8),
            thesis=thesis,
            invalidation=invalidation,
            factors=top,
            risk_notes=list(ch.attacks[:4]),
            status="pending",
            ts=now,
        )
        memos.append(memo)
        notes.append(f"memo {asset.symbol} {side} conv {conviction:.2f}")

    if hod:
        hod.status = "live"
        hod.last_score = float(len(memos))
        hod.last_note = "; ".join(notes[-4:]) if notes else "no memos this tick"
        hod.last_beat = now
    return memos, checklists
