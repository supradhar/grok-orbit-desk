from __future__ import annotations

from desk import layer2, layer3, layer4
from desk.config_load import load_config
from desk.models import FactorScore


def test_challenge_smoke():
    cfg, assets = load_config()
    assets = assets[:2]
    agents = layer2.spawn_agents(assets) + layer3.spawn_agents(assets, {}) + layer4.spawn_agents(assets)
    factors = [
        FactorScore(
            agent_id="t",
            layer=1,
            factor="momentum",
            symbol=a.symbol,
            score=30.0,
            confidence=0.7,
            note="m",
            sources=["binance"],
        )
        for a in assets
    ]
    snap = {"sources_ok": {"binance": True}, "marks": {a.symbol: 100.0 for a in assets}, "fear_greed": 50, "macro": {}}
    books = layer2.verify(factors, snap, assets, agents)
    reports = layer3.synthesize(books, snap, assets, {}, agents, None)
    challenges = layer4.challenge(reports, books, snap, assets, agents, cfg)
    assert challenges
