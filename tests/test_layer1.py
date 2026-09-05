from __future__ import annotations

from desk.config_load import load_config
from desk.models import Asset


def _assets() -> list[Asset]:
    _, assets = load_config()
    return assets[:3]


def test_spawn_and_research_smoke():
    from desk import layer1

    assets = _assets()
    agents = layer1.spawn_agents(assets, {"majors": ["BTC", "ETH"]})
    assert agents
    snap = {
        "ts": 1.0,
        "marks": {a.symbol: 100.0 for a in assets},
        "tickers": {
            a.symbol: {
                "price": 100.0,
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "change_24h": 1.0,
                "volume": 1e6,
                "quote_volume": 1e8,
                "source": "test",
            }
            for a in assets
        },
        "klines": {},
        "depth": {},
        "funding": {},
        "whales": {},
        "gecko": {},
        "news": [{"title": "bitcoin rally etf inflow", "link": "http://x", "source": "coindesk"}],
        "reddit": [],
        "macro": {},
        "calendar": {"fred": {}, "events": [], "nowcasts": {}, "notes": []},
        "fear_greed": 50,
        "mempool": {},
        "sources_ok": {},
    }
    factors = layer1.research(snap, assets, {"majors": ["BTC", "ETH"]}, agents)
    assert isinstance(factors, list)
