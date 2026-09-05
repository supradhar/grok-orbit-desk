from __future__ import annotations

from typing import Any

from desk.models import AgentState, Asset, FactorScore, VerifiedFactorBook
from desk.scoring import stdev, utc_now

COLOR = "#7dd3fc"


def spawn_agents(assets: list[Asset]) -> list[AgentState]:
    return [
        AgentState(
            id=f"l2-{a.symbol}",
            name=f"{a.symbol} verifier",
            layer=2,
            role="source-verifier",
            factor="trust",
            symbol=a.symbol,
            color=COLOR,
        )
        for a in assets
    ]


def verify(
    factors: list[FactorScore],
    snap: dict[str, Any],
    assets: list[Asset],
    agents: list[AgentState],
    ic_weights: dict[str, float] | None = None,
) -> list[VerifiedFactorBook]:
    now = utc_now()
    by_id = {a.id: a for a in agents if a.layer == 2}
    ok = snap.get("sources_ok") or {}
    books: list[VerifiedFactorBook] = []

    for asset in assets:
        raw = [f for f in factors if f.symbol == asset.symbol]
        globals_ = [f for f in factors if f.symbol is None]
        combined = raw + globals_
        flags: list[str] = []

        has_px = bool(
            (snap.get("marks") or {}).get(asset.symbol)
            or ((snap.get("tickers") or {}).get(asset.symbol) or {}).get("price")
        )
        yahoo_only = bool(asset.yahoo and not asset.binance)
        if yahoo_only:
            if not has_px:
                flags.append("price_feed_gap")
        elif not has_px and not ok.get("binance", True) and not ok.get("coingecko", True):
            flags.append("price_feed_gap")

        # Crypto microstructure factors are N/A for yahoo-only metals/FX — don't thin-book them.
        applicable = [
            f
            for f in raw
            if f.factor not in {"article", "social_post"}
            and not (
                yahoo_only
                and f.factor in {"volume", "derivatives", "liquidity", "whales", "flows"}
                and getattr(f, "unknown", False)
            )
        ]
        live = [f for f in applicable if f.confidence >= 0.22 and not getattr(f, "unknown", False)]
        need = 3 if yahoo_only else 4
        if len(live) < need:
            flags.append("thin_book")

        news = next((f for f in raw if f.factor == "news"), None)
        social = next((f for f in raw if f.factor == "social"), None)
        deriv = next((f for f in raw if f.factor == "derivatives"), None)
        if news and (getattr(news, "unknown", False) or news.confidence < 0.22 or not news.sources):
            flags.append("unknown_news")
        # Gold/FX rarely has Reddit crypto social — treat missing social as waived, not a trust hit.
        if social and (getattr(social, "unknown", False) or social.confidence < 0.22 or not social.sources):
            if yahoo_only:
                flags.append("social_waived")
            else:
                flags.append("unknown_social")
        if "unknown_news" in flags and "unknown_social" in flags:
            flags.append("unknown_tape")
        if news and "disagree" in (news.note or ""):
            flags.append("news_desks_split")
        if (
            news
            and deriv
            and not getattr(deriv, "unknown", False)
            and news.confidence > 0.3
            and deriv.confidence > 0.3
        ):
            if news.score * deriv.score < 0 and abs(news.score - deriv.score) > 50:
                flags.append("news_vs_funding_disagreement")

        mom = next((f for f in raw if f.factor == "momentum"), None)
        liq = next((f for f in raw if f.factor == "liquidity"), None)
        if (
            mom
            and liq
            and not getattr(liq, "unknown", False)
            and mom.score > 35
            and liq.score < -15
        ):
            flags.append("move_on_thin_book")

        verified: list[FactorScore] = []
        for f in combined:
            conf = f.confidence
            unk = bool(getattr(f, "unknown", False))
            # Don't invent "no_source" flags for factors that are honestly unknown / N/A.
            if not f.sources and not unk:
                conf *= 0.45
                if f.symbol == asset.symbol and f.factor not in {"article", "social_post"}:
                    flags.append(f"no_source:{f.factor}")
            if f.factor in {"liquidity", "whales", "volatility"} and conf < 0.35 and not unk:
                conf *= 0.8
            verified.append(
                FactorScore(
                    agent_id=f.agent_id,
                    layer=2,
                    factor=f.factor,
                    symbol=f.symbol,
                    score=f.score,
                    confidence=max(0.05, min(1.0, conf)),
                    note=f.note,
                    evidence=list(f.evidence),
                    sources=list(f.sources),
                    ts=now,
                    unknown=bool(unk or conf < 0.18),
                )
            )

        from desk.ic import weighted_blend

        skip = {"article", "social_post"}
        local_known = [
            f
            for f in verified
            if f.symbol == asset.symbol and f.factor not in skip and not f.unknown
        ]
        use_w = None if yahoo_only else ic_weights
        blended, known_w = weighted_blend(local_known, use_w)
        scores = [f.score for f in local_known]
        dispersion = stdev(scores) if scores else 80.0
        if dispersion > 55:
            flags.append("high_dispersion")

        # unique flags
        flags = list(dict.fromkeys(flags))
        # Yahoo-only books have fewer CORE factors — scale known_w requirement down.
        trust_den = 0.35 if yahoo_only else 0.55
        trust = min(1.0, (known_w / trust_den) if known_w else 0.1)
        # social_waived is informational, not a penalty
        penalty_flags = [f for f in flags if f != "social_waived"]
        trust *= max(0.2, 1.0 - 0.08 * len(penalty_flags))
        if "unknown_news" in flags:
            trust *= 0.72
        if "unknown_social" in flags:
            trust *= 0.78
        if "unknown_tape" in flags:
            trust *= 0.7
        trust = max(0.0, min(1.0, trust))
        garbage = trust < 0.22 or "price_feed_gap" in flags

        agent = by_id.get(f"l2-{asset.symbol}")
        book = VerifiedFactorBook(
            agent_id=f"l2-{asset.symbol}",
            symbol=asset.symbol,
            trust=trust,
            flags=flags,
            factors=verified,
            blended_raw=blended,
            garbage=garbage,
            ts=now,
        )
        if agent:
            agent.status = "live"
            agent.last_score = trust * 100
            agent.last_note = f"trust {trust:.2f}" + (f" flags {', '.join(flags)}" if flags else "")
            agent.last_beat = now
        books.append(book)
    return books
