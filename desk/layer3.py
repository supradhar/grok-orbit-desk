from __future__ import annotations

from typing import Any

from desk.models import AgentState, AnalysisReport, Asset, VerifiedFactorBook
from desk.scoring import stdev, utc_now

COLOR = "#c4b5fd"


def spawn_agents(assets: list[Asset], sectors: dict[str, list[str]]) -> list[AgentState]:
    agents = [
        AgentState(
            id=f"l3-{a.symbol}",
            name=f"{a.symbol} analyst",
            layer=3,
            role="synthesis-analyst",
            factor="blend",
            symbol=a.symbol,
            color=COLOR,
        )
        for a in assets
    ]
    agents.append(
        AgentState(
            id="l3-REGIME",
            name="regime analyst",
            layer=3,
            role="synthesis-analyst",
            factor="regime",
            symbol=None,
            color=COLOR,
        )
    )
    for name in list(sectors)[:4]:
        agents.append(
            AgentState(
                id=f"l3-SEC-{name}",
                name=f"{name} sector analyst",
                layer=3,
                role="synthesis-analyst",
                factor="sector",
                symbol=name.upper(),
                color=COLOR,
            )
        )
    return agents


def spawn_for_symbol(asset: Asset) -> list[AgentState]:
    return [
        AgentState(
            id=f"l3-{asset.symbol}",
            name=f"{asset.symbol} analyst",
            layer=3,
            role="synthesis-analyst",
            factor="blend",
            symbol=asset.symbol,
            color=COLOR,
        )
    ]


def _regime_from(books: list[VerifiedFactorBook], snap: dict[str, Any]) -> str:
    glob = [f for b in books for f in b.factors if f.symbol is None]
    vix = next((f for f in glob if f.factor == "macro_vix"), None)
    dxy = next((f for f in glob if f.factor == "macro_dxy"), None)
    fg = next((f for f in glob if f.factor == "fear_greed"), None)
    spx = next((f for f in glob if f.factor == "macro_spx"), None)
    if (vix and vix.score < -20) or (dxy and dxy.score < -20) or (spx and spx.score < -20):
        return "risk-off"
    if fg and fg.score > 25:
        return "fear-bounce"
    if fg and fg.score < -25:
        return "greed-caution"
    if (spx and spx.score > 15) and (dxy and dxy.score > 0):
        return "risk-on"
    return "neutral"


def synthesize(
    books: list[VerifiedFactorBook],
    snap: dict[str, Any],
    assets: list[Asset],
    sectors: dict[str, list[str]],
    agents: list[AgentState],
    ic_weights: dict[str, float] | None = None,
) -> list[AnalysisReport]:
    now = utc_now()
    by_id = {a.id: a for a in agents if a.layer == 3}
    regime = _regime_from(books, snap)
    reports: list[AnalysisReport] = []
    book_map = {b.symbol: b for b in books}

    def finish(rep: AnalysisReport) -> None:
        agent = by_id.get(rep.agent_id)
        if agent:
            agent.status = "live"
            agent.last_score = rep.blended
            agent.last_note = rep.thesis[:120]
            agent.last_beat = now
        reports.append(rep)

    for asset in assets:
        book = book_map.get(asset.symbol)
        if not book:
            continue
        local = [f for f in book.factors if f.symbol == asset.symbol and f.factor not in {"article", "social_post"}]
        known = [f for f in local if not getattr(f, "unknown", False)]
        from desk.ic import weighted_blend

        # Crypto IC weights are wrong for yahoo-only metals/FX — use confidence-equal blend.
        yahoo_only = bool(asset.yahoo and not asset.binance)
        use_w = None if yahoo_only else ic_weights
        blended, _ = weighted_blend(known, use_w)
        book.blended_raw = blended
        scores = [f.score for f in known]
        agreement = 1.0
        if scores:
            agreement = max(0.0, min(1.0, 1.0 - stdev(scores) / 80.0))
        conf = book.trust * (0.45 + 0.55 * agreement)
        bulls = [f"{f.factor} {f.score:+.0f}" for f in sorted(known, key=lambda x: -x.score)[:3] if f.score > 8]
        bears = [f"{f.factor} {f.score:+.0f}" for f in sorted(known, key=lambda x: x.score)[:3] if f.score < -8]
        direction = "bid-biased" if blended > 12 else "offer-biased" if blended < -12 else "two-sided"
        thesis = (
            f"{asset.symbol} {direction} in a {regime} tape. "
            f"Verified blend {blended:+.1f} (trust {book.trust:.2f}, agreement {agreement:.2f}). "
        )
        if bulls:
            thesis += "Supports: " + ", ".join(bulls) + ". "
        if bears:
            thesis += "Drags: " + ", ".join(bears) + "."
        if book.flags:
            show = [f for f in book.flags if f != "social_waived"]
            if show:
                thesis += f" Verifier flags: {', '.join(show)}."
            if "social_waived" in book.flags:
                thesis += " Social waived (non-crypto tape)."
        if "unknown_tape" in book.flags:
            thesis += " Tape is dark — news and social are unknown, not quiet."
            conf *= 0.55
        elif "unknown_news" in book.flags:
            thesis += " Part of the tape is unknown; do not treat a 0 bar as agreement."
            conf *= 0.75
        elif "unknown_social" in book.flags:
            thesis += " Part of the tape is unknown; do not treat a 0 bar as agreement."
            conf *= 0.75
        cal = snap.get("calendar") or {}
        if cal.get("notes"):
            thesis += " Calendar: " + "; ".join(cal["notes"][:2]) + "."
        if cal.get("event_risk"):
            thesis += " High-impact print is inside the window — size should stay small."
            conf *= 0.8
        pol = next((f for f in known if f.factor == "policy"), None)
        if pol and abs(pol.score) >= 8:
            thesis += f" Policy factor {pol.score:+.0f} from claims/NFP/FOMC nowcast."
        finish(
            AnalysisReport(
                agent_id=f"l3-{asset.symbol}",
                symbol=asset.symbol,
                blended=blended,
                confidence=conf,
                agreement=agreement,
                regime=regime,
                thesis=thesis.strip(),
                bull_factors=bulls,
                bear_factors=bears,
                trust=book.trust,
                ts=now,
            )
        )

    finish(
        AnalysisReport(
            agent_id="l3-REGIME",
            symbol="REGIME",
            blended=0.0,
            confidence=0.7,
            agreement=1.0,
            regime=regime,
            thesis=(
                f"Cross-asset regime labelled {regime} from macro, VIX, DXY, SPX and fear/greed packets."
                + (
                    f" Calendar: {(snap.get('calendar') or {}).get('notes', [''])[0]}."
                    if (snap.get("calendar") or {}).get("notes")
                    else ""
                )
            ),
            bull_factors=[],
            bear_factors=[],
            trust=1.0,
            ts=now,
        )
    )
    for name, members in list(sectors.items())[:4]:
        member_reps = [r for r in reports if r.symbol in members]
        if not member_reps:
            continue
        avg = sum(r.blended for r in member_reps) / len(member_reps)
        finish(
            AnalysisReport(
                agent_id=f"l3-SEC-{name}",
                symbol=name.upper(),
                blended=avg,
                confidence=sum(r.confidence for r in member_reps) / len(member_reps),
                agreement=sum(r.agreement for r in member_reps) / len(member_reps),
                regime=regime,
                thesis=f"Sector {name} mean blend {avg:+.1f} across {len(member_reps)} names.",
                bull_factors=[],
                bear_factors=[],
                trust=sum(r.trust for r in member_reps) / len(member_reps),
                ts=now,
            )
        )
    return reports
