from __future__ import annotations

from desk import layer2, layer3
from desk.config_load import load_config
from desk.models import FactorScore


def test_synthesize_smoke():
    _, assets = load_config()
    assets = assets[:2]
    agents = layer2.spawn_agents(assets) + layer3.spawn_agents(assets, {"majors": ["BTC", "ETH"]})
    factors = [
        FactorScore(
            agent_id="t",
            layer=1,
            factor="momentum",
            symbol=a.symbol,
            score=25.0,
            confidence=0.6,
            note="m",
            sources=["binance"],
        )
        for a in assets
    ]
    snap = {"sources_ok": {"binance": True}, "marks": {a.symbol: 100.0 + i for i, a in enumerate(assets)}, "fear_greed": 55, "macro": {}}
    books = layer2.verify(factors, snap, assets, agents)
    reports = layer3.synthesize(books, snap, assets, {"majors": ["BTC", "ETH"]}, agents, None)
    assert any(r.symbol == assets[0].symbol for r in reports)
