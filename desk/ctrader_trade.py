"""CLI: sync/trade full cTrader symbol universe.

  $env:CTRADER_CLIENT_ID="..."
  $env:CTRADER_CLIENT_SECRET="..."
  $env:CTRADER_ACCESS_TOKEN="..."
  $env:CTRADER_ACCOUNT_ID="..."
  $env:CTRADER_HOST="demo"

  python -m desk.ctrader_trade symbols
  python -m desk.ctrader_trade buy XAUUSD 0.01
  python -m desk.ctrader_trade buy EURUSD 0.01
"""

from __future__ import annotations

import argparse
import json
import sys

from desk.ctrader_client import (
    CTraderBroker,
    CTraderError,
    credentials_present,
    fetch_symbols,
    load_symbol_cache,
    place_market_order,
    resolve_symbol,
    symbols_to_assets,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="cTrader prop-firm — all platform symbols")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("symbols", help="Fetch & cache all account symbols")
    sub.add_parser("cached", help="Show cached symbols")
    find = sub.add_parser("find", help="Resolve a symbol name/alias")
    find.add_argument("query")
    buy = sub.add_parser("buy", help="Market buy lots")
    buy.add_argument("symbol")
    buy.add_argument("lots", type=float)
    sell = sub.add_parser("sell", help="Market sell lots")
    sell.add_argument("symbol")
    sell.add_argument("lots", type=float)
    sub.add_parser("assets", help="Print desk Asset JSON for platform universe")

    args = p.parse_args(argv)

    if args.cmd == "cached":
        rows = load_symbol_cache()
        print(json.dumps([{"id": s.symbol_id, "name": s.name} for s in rows], indent=2))
        print(f"count={len(rows)}", file=sys.stderr)
        return 0

    if args.cmd == "find":
        rows = load_symbol_cache()
        hit = resolve_symbol(rows, args.query)
        if not hit:
            print(json.dumps({"ok": False, "query": args.query}))
            return 1
        print(json.dumps({"ok": True, "symbol_id": hit.symbol_id, "name": hit.name, "desk": hit.desk_symbol}))
        return 0

    if args.cmd == "assets":
        rows = load_symbol_cache()
        assets = symbols_to_assets(rows)
        print(json.dumps([{"symbol": a.symbol, "id": a.id, "yahoo": a.yahoo} for a in assets], indent=2))
        return 0

    if not credentials_present():
        print(
            "Missing cTrader env credentials.\n"
            "Set CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN,\n"
            "CTRADER_ACCOUNT_ID, and CTRADER_HOST=demo|live\n"
            "(create an Open API app at https://openapi.ctrader.com/ ).",
            file=sys.stderr,
        )
        return 2

    try:
        if args.cmd == "symbols":
            rows = fetch_symbols()
            print(json.dumps({"ok": True, "count": len(rows), "sample": [s.name for s in rows[:20]]}, indent=2))
            return 0
        if args.cmd in {"buy", "sell"}:
            side = "long" if args.cmd == "buy" else "short"
            res = place_market_order(symbol=args.symbol, side=side, volume_lots=float(args.lots))
            print(json.dumps(res, indent=2))
            return 0
    except CTraderError as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
