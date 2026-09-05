from __future__ import annotations

from desk.eventdata import EventLedger
from desk.hub import DataHub
from desk.models import Asset


def test_hub_ledger_records_marks():
    assets = [Asset(id="bitcoin", symbol="BTC", binance="BTCUSDT", keywords=["btc"])]
    hub = DataHub(assets)
    hub.ledger.record_mark("BTC", 100.0, "test", event_time=50.0)
    hub.ledger.record_news({"title": "x", "link": "http://a", "published_at": 40.0})
    hub.ledger.record_macro("CPIAUCSL", 300.0, release_time=60.0)
    h = hub.ledger.health()
    assert h["observations"] >= 3
    assert hub.ledger.asof_mark("BTC", 49.0) is None
    assert hub.ledger.asof_mark("BTC", 51.0) == 100.0
