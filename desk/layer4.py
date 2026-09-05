from __future__ import annotations

from typing import Any

from desk.models import AgentState, AnalysisReport, Asset, ChallengeReport, VerifiedFactorBook
from desk.scoring import utc_now
from desk.signal import alpha_score, residual_floor

COLOR = "#f0abfc"


def spawn_agents(assets: list[Asset]) -> list[AgentState]:
    return [
        AgentState(
            id=f"l4-{a.symbol}",
            name=f"{a.symbol} advocate",
            layer=4,
            role="devils-advocate",
            factor="challenge",
            symbol=a.symbol,
            color=COLOR,
        )
        for a in assets
    ]


def challenge(
    reports: list[AnalysisReport],
    books: list[VerifiedFactorBook],
    snap: dict[str, Any],
    assets: list[Asset],
    agents: list[AgentState],
    cfg: dict[str, Any],
) -> list[ChallengeReport]:
    now = utc_now()
    by_id = {a.id: a for a in agents if a.layer == 4}
    book_map = {b.symbol: b for b in books}
    min_conf = float(cfg.get("min_confluence") or 42)
    out: list[ChallengeReport] = []

    for asset in assets:
        rep = next((r for r in reports if r.symbol == asset.symbol), None)
        book = book_map.get(asset.symbol)
        if not rep or not book:
            continue
        attacks: list[str] = []
        adj = 1.0
        veto = False

        if book.garbage:
            attacks.append("L2 marked the book garbage — skip any recommendation.")
            veto = True
            adj = 0.0

        sig = alpha_score(rep)
        floor = min_conf if asset.symbol == "BTC" else residual_floor(cfg)
        if getattr(rep, "standalone", False) and asset.symbol != "BTC":
            floor = max(14.0, min_conf * 0.65)
        if abs(sig) < floor:
            label = "blend" if asset.symbol == "BTC" or getattr(rep, "standalone", False) else "idio"
            attacks.append(f"|{label}| {abs(sig):.1f} below confluence {floor:.1f}.")
            veto = True
            adj = 0.0

        if rep.agreement < 0.35:
            attacks.append(f"factors disagree (agreement {rep.agreement:.2f}).")
            adj *= 0.55

        local = {f.factor: f for f in book.factors if f.symbol == asset.symbol}
        glob = {f.factor: f for f in book.factors if f.symbol is None}
        deriv = local.get("derivatives")
        liq = local.get("liquidity")
        news = local.get("news")
        vol = local.get("volatility")

        long_bias = sig > 0
        if deriv and deriv.score < -25 and long_bias:
            attacks.append("funding/OI crowding fights a long (crowded longs).")
            adj *= 0.6
        if deriv and deriv.score > 25 and not long_bias:
            attacks.append("crowded shorts fight a short.")
            adj *= 0.6
        if liq and liq.score < -20:
            attacks.append("liquidity hole — size should be cut or idea killed.")
            adj *= 0.5
            if asset.symbol in {"PEPE", "DOGE"} and liq.score < -30:
                attacks.append("meme book too thin.")
                veto = True
        if news and abs(news.score) > 40 and news.score * sig < 0:
            attacks.append("headline tape contradicts the residual.")
            adj *= 0.7
        if vol and vol.score < -30:
            attacks.append("vol shock — stops will be noisy.")
            adj *= 0.75
        if rep.regime == "risk-off" and long_bias and asset.symbol not in {"BTC", "ETH"} and not getattr(rep, "standalone", False):
            attacks.append("risk-off macro veto on high-beta long.")
            adj *= 0.4
            if abs(sig) < floor + 15:
                veto = True
        if rep.regime == "greed-caution" and long_bias and not getattr(rep, "standalone", False):
            attacks.append("extreme greed — chase risk.")
            adj *= 0.7
        if rep.trust < 0.28:
            attacks.append(f"verifier trust only {rep.trust:.2f}.")
            adj *= 0.5
        if book.flags and "unknown_tape" in book.flags:
            attacks.append("news and social are unknown — blend is price structure only.")
            adj *= 0.45
            if abs(sig) < floor + 8:
                veto = True
        elif book.flags and "unknown_news" in book.flags:
            attacks.append("incomplete tape (missing news).")
            adj *= 0.7
        elif book.flags and "unknown_social" in book.flags and "social_waived" not in book.flags:
            attacks.append("incomplete tape (missing social).")
            adj *= 0.7
        cal = snap.get("calendar") or {}
        if cal.get("event_risk"):
            attacks.append("high-impact US print inside the window — fade size, do not chase.")
            adj *= 0.55
        pol = local.get("policy")
        if pol and not getattr(pol, "unknown", False) and abs(pol.score) >= 12 and pol.score * sig < 0:
            attacks.append("desk nowcast on claims/NFP/FOMC fights the residual.")
            adj *= 0.7
        resid = float(getattr(rep, "residual", 0) or 0)
        beta = float(getattr(rep, "beta", 0) or 0)
        sigma = float(getattr(rep, "sigma", 0) or 0)
        if (
            asset.symbol != "BTC"
            and not getattr(rep, "standalone", False)
            and getattr(rep, "beta_ok", False)
            and abs(rep.blended) >= min_conf * 0.6
            and abs(resid) < min_conf * 0.4
            and abs(beta) > 0.75
        ):
            attacks.append(
                f"idiosyncratic residual {resid:+.1f} vs blend {rep.blended:+.1f} (β {beta:.2f} to BTC) — beta, not alpha."
            )
            adj *= 0.55
        if sigma > 28 and abs(sig) < 1.6 * sigma:
            attacks.append(f"posterior σ {sigma:.0f} — signal is inside the noise band.")
            adj *= 0.7

        if not attacks:
            attacks.append("no material hole found — thesis survives challenge.")

        surviving = rep.thesis if not veto else f"VETO {asset.symbol}: " + "; ".join(attacks[:3])
        if not veto:
            surviving = f"After challenge (×{adj:.2f}): {rep.thesis}"

        agent = by_id.get(f"l4-{asset.symbol}")
        report = ChallengeReport(
            agent_id=f"l4-{asset.symbol}",
            symbol=asset.symbol,
            veto=veto,
            conviction_adj=max(0.0, min(1.0, adj)),
            attacks=attacks[:6],
            surviving_thesis=surviving,
            ts=now,
        )
        if agent:
            agent.status = "live"
            agent.last_score = 0.0 if veto else adj * 100
            agent.last_note = "VETO " + attacks[0] if veto else attacks[0]
            agent.last_beat = now
        out.append(report)
    return out
