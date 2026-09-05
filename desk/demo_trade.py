"""CLI for Binance Demo Trading (simulation funds).

  $env:BINANCE_API_KEY="..."
  $env:BINANCE_API_SECRET="..."
  python -m desk.demo_trade status
  python -m desk.demo_trade buy BTCUSDT 25
"""

from __future__ import annotations

import argparse
import json
import sys

from desk.binance_demo import BinanceDemoBroker
from desk.broker import BrokerOrder
from desk.scoring import utc_now


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Binance Demo Trading CLI")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Ping + balances")
    buy = sub.add_parser("buy", help="Market buy notional USDT on demo")
    buy.add_argument("symbol", help="e.g. BTCUSDT")
    buy.add_argument("usd", type=float)
    sell = sub.add_parser("sell", help="Market sell notional USDT on demo")
    sell.add_argument("symbol")
    sell.add_argument("usd", type=float)
    args = p.parse_args(argv)

    try:
        br = BinanceDemoBroker()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        print(
            "\nSECURITY: revoke any key pasted in chat.\n"
            "Create NEW keys in Binance Demo Trading (not production).\n"
            "PowerShell:\n"
            '  $env:BINANCE_API_KEY="demo_key"\n'
            '  $env:BINANCE_API_SECRET="demo_secret"\n'
            '  $env:BINANCE_BASE_URL="https://demo-api.binance.com"\n',
            file=sys.stderr,
        )
        return 2

    if args.cmd == "status":
        br.ping()
        print(json.dumps({"ok": True, "base": br.base_url, "balances": br.balances()[:30]}, indent=2))
        return 0

    side = "long" if args.cmd == "buy" else "short"
    sym = args.symbol.upper().replace("/", "")
    base = sym[:-4] if sym.endswith("USDT") else sym
    msg = br.submit(
        BrokerOrder(
            symbol=base,
            side=side,
            size_usd=float(args.usd),
            client_id=f"demo-{int(utc_now())}",
            ts=utc_now(),
        )
    )
    print(json.dumps({"result": msg, "symbol": sym, "side": side, "usd": args.usd}, indent=2))
    return 0 if str(msg).startswith("demo:") else 1


if __name__ == "__main__":
    raise SystemExit(main())
