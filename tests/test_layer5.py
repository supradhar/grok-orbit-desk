from __future__ import annotations

from desk.layer5 import expected_alpha_clears_costs, promotion_checks, spawn_agents
from desk.models import AnalysisReport, ChallengeReport, VerifiedFactorBook


def test_spawn_l5():
    assert spawn_agents()


def test_promotion_checks_structure():
    rep = AnalysisReport(
        agent_id="a",
        symbol="BTC",
        blended=30.0,
        confidence=0.5,
        agreement=0.6,
        regime="expansion",
        thesis="t",
        bull_factors=["momentum"],
        bear_factors=[],
        residual=30.0,
        beta=1.0,
        beta_ok=True,
        sigma=10.0,
        standalone=False,
    )
    ch = ChallengeReport(
        agent_id="c",
        symbol="BTC",
        veto=False,
        conviction_adj=1.0,
        attacks=[],
        surviving_thesis="ok",
    )
    book = VerifiedFactorBook(
        agent_id="b",
        symbol="BTC",
        trust=0.8,
        flags=[],
        factors=[],
        blended_raw=30.0,
        garbage=False,
    )
    cfg = {
        "min_confidence": 0.3,
        "min_trust": 0.5,
        "min_confluence": 20,
        "min_skill": 0.4,
        "min_skill_n": 30,
        "fee_bps": 4,
        "slippage_bps": 6,
        "spread_bps": 2,
    }
    out = promotion_checks(
        rep,
        ch,
        book,
        cfg,
        mix_ic=0.05,
        news_weight=0.1,
        skill={"n": 40, "hit_rate": 0.55, "expectancy": 0.001, "persist": True},
        hmm="expansion",
    )
    assert "ok" in out
    assert "cost_aware" in out
    assert expected_alpha_clears_costs(50.0, cfg) is True
