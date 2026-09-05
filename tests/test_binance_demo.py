from __future__ import annotations

import os

import pytest

from desk.binance_demo import BinanceDemoBroker


def test_demo_broker_requires_env(monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        BinanceDemoBroker()


def test_sign_stable(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "k")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret")
    br = BinanceDemoBroker()
    sig = br._sign({"symbol": "BTCUSDT", "timestamp": 1})
    assert isinstance(sig, str) and len(sig) == 64
