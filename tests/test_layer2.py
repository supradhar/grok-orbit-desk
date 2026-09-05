from __future__ import annotations

from desk import layer2
from desk.config_load import load_config
from desk.models import FactorScore


def test_verify_smoke():
    _, assets = load_config()
    assets = assets[:2]
    agents = layer2.spawn_agents(assets)
    factors = [
        FactorScore(
            agent_id="t",
            layer=1,
            factor="momentum",
            symbol=assets[0].symbol,
            score=20.0,
            confidence=0.5,
            note="ok",
            sources=["binance"],
        )
    ]
    snap = {"sources_ok": {"binance": True}, "marks": {assets[0].symbol: 100.0}}
    books = layer2.verify(factors, snap, assets, agents)
    assert books
    assert books[0].symbol == assets[0].symbol
