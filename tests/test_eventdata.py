from __future__ import annotations

from desk.eventdata import MemoryProvider, Observation, macro_asof, news_available


def test_no_lookahead_on_arrival():
    p = MemoryProvider()
    p.publish(Observation(None, "CPIAUCSL", 300.0, event_time=100.0, arrival_time=200.0, source="fred"))
    p.publish(Observation(None, "CPIAUCSL", 301.0, event_time=100.0, arrival_time=300.0, source="fred", revision=1))
    assert macro_asof(p, "CPIAUCSL", 150.0) is None
    assert macro_asof(p, "CPIAUCSL", 250.0) == 300.0
    assert macro_asof(p, "CPIAUCSL", 350.0) == 301.0


def test_news_availability():
    p = MemoryProvider()
    p.publish(Observation(None, "news:a1", 1.0, event_time=10.0, arrival_time=50.0, source="rss"))
    assert news_available(p, "a1", 40.0) is False
    assert news_available(p, "a1", 50.0) is True
