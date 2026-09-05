from __future__ import annotations

from desk.ctrader_client import (
    PlatformSymbol,
    resolve_symbol,
    save_symbol_cache,
    symbols_to_assets,
)


def test_resolve_aliases(tmp_path):
    rows = [
        PlatformSymbol(1, "EURUSD"),
        PlatformSymbol(2, "XAUUSD"),
        PlatformSymbol(3, "US500"),
    ]
    assert resolve_symbol(rows, "eur/usd").name == "EURUSD"
    assert resolve_symbol(rows, "GOLD").name == "XAUUSD"
    assert resolve_symbol(rows, "xauusd").symbol_id == 2


def test_symbols_to_assets_all():
    rows = [
        PlatformSymbol(1, "EURUSD"),
        PlatformSymbol(2, "XAUUSD"),
        PlatformSymbol(3, "GBPUSD"),
        PlatformSymbol(4, "NAS100"),
    ]
    assets = symbols_to_assets(rows)
    assert {a.symbol for a in assets} == {"EURUSD", "XAUUSD", "GBPUSD", "NAS100"}
    gold = next(a for a in assets if a.symbol == "XAUUSD")
    assert gold.yahoo == "GC=F"


def test_cache_roundtrip(tmp_path):
    path = tmp_path / "syms.json"
    rows = [PlatformSymbol(9, "XAUUSD", description="Gold")]
    save_symbol_cache(rows, path)
    from desk.ctrader_client import load_symbol_cache

    loaded = load_symbol_cache(path)
    assert loaded[0].symbol_id == 9
