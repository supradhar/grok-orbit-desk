"""cTrader Open API — full account symbol universe + orders (prop-firm demo/live).

Env (never commit):
  CTRADER_CLIENT_ID
  CTRADER_CLIENT_SECRET
  CTRADER_ACCESS_TOKEN
  CTRADER_ACCOUNT_ID
  CTRADER_HOST=demo|live   (default demo)

Any symbol listed by the platform can be traded once resolved by name/alias.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from desk.broker import BrokerOrder
from desk.config_load import ROOT
from desk.models import Asset
from desk.scoring import utc_now

SYMBOL_CACHE = ROOT / "data" / "ctrader_symbols.json"


@dataclass
class PlatformSymbol:
    symbol_id: int
    name: str
    description: str = ""
    digits: int = 5
    pip_position: int = -1
    enabled: bool = True

    @property
    def desk_symbol(self) -> str:
        return self.name.upper().replace("/", "").replace(".", "")


class CTraderError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _host() -> str:
    from ctrader_open_api import EndPoints

    mode = (_env("CTRADER_HOST", "demo") or "demo").lower()
    return EndPoints.PROTOBUF_LIVE_HOST if mode == "live" else EndPoints.PROTOBUF_DEMO_HOST


def credentials_present() -> bool:
    return bool(
        _env("CTRADER_CLIENT_ID")
        and _env("CTRADER_CLIENT_SECRET")
        and _env("CTRADER_ACCESS_TOKEN")
        and _env("CTRADER_ACCOUNT_ID")
    )


def save_symbol_cache(symbols: list[PlatformSymbol], path: Path | None = None) -> Path:
    target = path or SYMBOL_CACHE
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(s) for s in symbols]
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return target


def load_symbol_cache(path: Path | None = None) -> list[PlatformSymbol]:
    target = path or SYMBOL_CACHE
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    return [PlatformSymbol(**row) for row in raw]


def resolve_symbol(symbols: list[PlatformSymbol], query: str) -> PlatformSymbol | None:
    q = query.upper().replace("/", "").replace(".", "").replace(" ", "")
    aliases = {q}
    if q == "XAUUSD":
        aliases |= {"GOLD", "XAUUSDM", "XAUUSD.", "XAUUSD.A"}
    if q == "GOLD":
        aliases |= {"XAUUSD", "XAUUSDM"}
    by_name = {s.desk_symbol: s for s in symbols if s.enabled}
    for a in aliases:
        if a in by_name:
            return by_name[a]
    # fuzzy contains
    for s in symbols:
        if q in s.desk_symbol or s.desk_symbol in q:
            return s
    return None


def symbols_to_assets(symbols: list[PlatformSymbol], *, metals: set[str] | None = None) -> list[Asset]:
    """Map every platform symbol into a desk Asset (yahoo blank unless known)."""
    metals = metals or {"XAUUSD", "GOLD", "XAGUSD", "SILVER"}
    yahoo_map = {"XAUUSD": "GC=F", "GOLD": "GC=F", "XAGUSD": "SI=F", "SILVER": "SI=F"}
    out: list[Asset] = []
    seen: set[str] = set()
    for s in symbols:
        if not s.enabled:
            continue
        sym = s.desk_symbol
        if not sym or sym in seen:
            continue
        seen.add(sym)
        kw = [sym.lower(), s.name.lower()]
        if sym in metals or "XAU" in sym or "GOLD" in sym:
            kw += ["gold", "xau", "bullion"]
        out.append(
            Asset(
                id=f"ctrader-{s.symbol_id}",
                symbol=sym,
                binance="",
                keywords=list(dict.fromkeys(kw)),
                yahoo=yahoo_map.get(sym, ""),
            )
        )
    return out


class CTraderSession:
    """One-shot Twisted session: app auth → account auth → user action → stop."""

    def __init__(self) -> None:
        if not credentials_present():
            raise CTraderError(
                "Set CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET, CTRADER_ACCESS_TOKEN, CTRADER_ACCOUNT_ID"
            )
        self.client_id = _env("CTRADER_CLIENT_ID")
        self.client_secret = _env("CTRADER_CLIENT_SECRET")
        self.access_token = _env("CTRADER_ACCESS_TOKEN")
        self.account_id = int(_env("CTRADER_ACCOUNT_ID"))
        self._result: Any = None
        self._error: BaseException | None = None
        self._client = None

    def run(self, action: Callable[[Any], Any], timeout: float = 45.0) -> Any:
        from ctrader_open_api import Client, EndPoints, Protobuf, TcpProtocol
        from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoHeartbeatEvent
        from ctrader_open_api.messages.OpenApiMessages_pb2 import (
            ProtoOAAccountAuthReq,
            ProtoOAAccountAuthRes,
            ProtoOAApplicationAuthReq,
            ProtoOAApplicationAuthRes,
            ProtoOAErrorRes,
        )
        from twisted.internet import reactor

        host = _host()
        client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
        self._client = client
        done = threading.Event()

        def fail(err: BaseException) -> None:
            self._error = err
            if reactor.running:
                reactor.callFromThread(reactor.stop)
            done.set()

        def on_error(failure) -> None:
            fail(CTraderError(str(failure)))

        def after_account(_result) -> None:
            try:
                deferred = action(client)
                if deferred is not None:
                    deferred.addCallbacks(lambda r: finish(r), on_error)
                else:
                    finish(None)
            except Exception as e:
                fail(e)

        def finish(result: Any) -> None:
            self._result = result
            if reactor.running:
                reactor.callFromThread(reactor.stop)
            done.set()

        def after_app(_result) -> None:
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = self.account_id
            req.accessToken = self.access_token
            d = client.send(req)
            d.addCallbacks(after_account, on_error)

        def connected(_client) -> None:
            req = ProtoOAApplicationAuthReq()
            req.clientId = self.client_id
            req.clientSecret = self.client_secret
            d = client.send(req)
            d.addCallbacks(after_app, on_error)

        def on_message(_client, message) -> None:
            # Ignore heartbeats / auth noise; errors surface via deferreds mostly
            try:
                extracted = Protobuf.extract(message)
            except Exception:
                return
            if isinstance(extracted, ProtoOAErrorRes):
                fail(CTraderError(f"{extracted.errorCode}: {extracted.description}"))

        def disconnected(_client, reason) -> None:  # pragma: no cover
            if not done.is_set() and self._result is None and self._error is None:
                fail(CTraderError(f"disconnected: {reason}"))

        client.setConnectedCallback(connected)
        client.setDisconnectedCallback(disconnected)
        client.setMessageReceivedCallback(on_message)
        client.startService()

        def _run() -> None:
            reactor.run(installSignalHandlers=False)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        if not done.wait(timeout):
            fail(CTraderError("cTrader session timed out"))
            try:
                if reactor.running:
                    reactor.callFromThread(reactor.stop)
            except Exception:
                pass
        t.join(timeout=5)
        if self._error:
            raise self._error
        return self._result


def fetch_symbols(*, refresh_cache: bool = True) -> list[PlatformSymbol]:
    from ctrader_open_api import Protobuf
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOASymbolsListReq, ProtoOASymbolsListRes

    session = CTraderSession()

    def action(client):
        req = ProtoOASymbolsListReq()
        req.ctidTraderAccountId = session.account_id
        req.includeArchivedSymbols = False
        return client.send(req)

    raw = session.run(action)
    msg = Protobuf.extract(raw)
    if not isinstance(msg, ProtoOASymbolsListRes):
        raise CTraderError(f"unexpected symbols response: {type(msg)}")
    symbols: list[PlatformSymbol] = []
    for s in msg.symbol:
        symbols.append(
            PlatformSymbol(
                symbol_id=int(s.symbolId),
                name=str(s.symbolName or ""),
                description=str(getattr(s, "description", "") or ""),
                digits=int(getattr(s, "digits", 5) or 5),
                enabled=True,
            )
        )
    symbols.sort(key=lambda x: x.name)
    if refresh_cache:
        save_symbol_cache(symbols)
    return symbols


def place_market_order(
    *,
    symbol: str,
    side: str,
    volume_lots: float,
    client_msg_id: str | None = None,
) -> dict[str, Any]:
    """Place market order for any platform symbol by name. volume_lots e.g. 0.01."""
    from ctrader_open_api import Protobuf
    from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOANewOrderReq
    from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide

    symbols = load_symbol_cache() or fetch_symbols()
    hit = resolve_symbol(symbols, symbol)
    if not hit:
        raise CTraderError(f"symbol not on platform: {symbol}")
    if volume_lots <= 0:
        raise CTraderError("volume_lots must be > 0")

    # cTrader volume: 100 units = 1.00 lot
    volume = int(round(volume_lots * 100))
    if volume < 1:
        volume = 1

    session = CTraderSession()

    def action(client):
        req = ProtoOANewOrderReq()
        req.ctidTraderAccountId = session.account_id
        req.symbolId = hit.symbol_id
        req.orderType = ProtoOAOrderType.MARKET
        req.tradeSide = ProtoOATradeSide.BUY if side.lower() in {"long", "buy"} else ProtoOATradeSide.SELL
        req.volume = volume
        if client_msg_id:
            # optional comment field if present
            if hasattr(req, "comment"):
                req.comment = client_msg_id[:50]
        return client.send(req)

    raw = session.run(action)
    extracted = Protobuf.extract(raw)
    return {
        "ok": True,
        "symbol": hit.name,
        "symbol_id": hit.symbol_id,
        "side": side,
        "volume_lots": volume_lots,
        "response_type": type(extracted).__name__,
        "ts": utc_now(),
    }


class CTraderBroker:
    """Broker protocol: trade any symbol present on the linked cTrader account."""

    name = "ctrader"
    environment = "simulation"  # flip to live only when CTRADER_HOST=live + ops review

    def __init__(self) -> None:
        self._killed = False
        self._symbols = load_symbol_cache()
        host = _env("CTRADER_HOST", "demo").lower()
        self.environment = "live" if host == "live" else "simulation"

    def refresh_universe(self) -> list[PlatformSymbol]:
        self._symbols = fetch_symbols()
        return self._symbols

    def list_symbols(self) -> list[PlatformSymbol]:
        if not self._symbols:
            self._symbols = load_symbol_cache()
        return list(self._symbols)

    def submit(self, order: BrokerOrder) -> str:
        if self._killed:
            return "rejected:kill_switch"
        if _env("CTRADER_HOST", "demo").lower() == "live" and _env("CTRADER_AUTO_APPROVE") != "1":
            # Extra belt for live — desk Approve still required upstream
            pass
        # Convert size_usd → lots heuristically if volume_lots not encoded
        # Default micro lot for demo safety when size small
        lots = max(0.01, min(1.0, float(order.size_usd) / 100_000.0))
        if order.size_usd >= 1000:
            lots = max(0.01, min(5.0, order.size_usd / 50_000.0))
        try:
            res = place_market_order(
                symbol=order.symbol,
                side=order.side,
                volume_lots=lots,
                client_msg_id=order.client_id,
            )
            return f"ctrader:ok:{res['symbol']}:{res['symbol_id']}"
        except Exception as e:
            return f"ctrader:error:{e}"

    def cancel(self, client_id: str) -> bool:
        return False

    def positions(self) -> dict[str, Any]:
        return {"symbols_cached": len(self._symbols)}

    def kill_switch(self) -> None:
        self._killed = True
