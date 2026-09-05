"""Binance Spot Demo Trading adapter (simulated funds — not mainnet).

Keys MUST come from environment variables, never from git/config:
  BINANCE_API_KEY
  BINANCE_API_SECRET
  BINANCE_BASE_URL  (default: https://demo-api.binance.com)

Create Demo API keys in the Binance Demo Trading UI — production keys will not work.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.parse
from typing import Any

import httpx

from desk.broker import BrokerFill, BrokerOrder
from desk.scoring import utc_now

DEFAULT_DEMO_BASE = "https://demo-api.binance.com"


class BinanceDemoBroker:
    name = "binance_demo"
    environment = "simulation"

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("BINANCE_API_KEY") or "").strip()
        self.api_secret = (api_secret or os.environ.get("BINANCE_API_SECRET") or "").strip()
        self.base_url = (base_url or os.environ.get("BINANCE_BASE_URL") or DEFAULT_DEMO_BASE).rstrip("/")
        self._killed = False
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                "Set BINANCE_API_KEY and BINANCE_API_SECRET in the environment "
                "(Demo Trading keys from Binance — never commit them)."
            )

    def _sign(self, params: dict[str, Any]) -> str:
        query = urllib.parse.urlencode(params, doseq=True)
        return hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    def _headers(self) -> dict[str, str]:
        return {"X-MBX-APIKEY": self.api_key}

    def _request(self, method: str, path: str, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["signature"] = self._sign(params)
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=20.0) as client:
            r = client.request(method, url, params=params, headers=self._headers())
            try:
                data = r.json()
            except Exception:
                r.raise_for_status()
                return r.text
            if r.status_code >= 400:
                raise RuntimeError(f"Binance demo error {r.status_code}: {data}")
            return data

    def ping(self) -> bool:
        self._request("GET", "/api/v3/ping")
        return True

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account", signed=True)

    def balances(self, non_zero: bool = True) -> list[dict[str, Any]]:
        acct = self.account()
        rows = []
        for b in acct.get("balances") or []:
            free = float(b.get("free") or 0)
            locked = float(b.get("locked") or 0)
            if non_zero and free == 0 and locked == 0:
                continue
            rows.append({"asset": b.get("asset"), "free": free, "locked": locked})
        return rows

    def price(self, symbol: str) -> float:
        data = self._request("GET", "/api/v3/ticker/price", params={"symbol": symbol.upper()})
        return float(data["price"])

    def submit(self, order: BrokerOrder) -> str:
        if self._killed:
            return "rejected:kill_switch"
        # Map desk side → Binance spot BUY/SELL (spot long only; short = sell base)
        side = "BUY" if order.side == "long" else "SELL"
        symbol = order.symbol.upper()
        if not symbol.endswith("USDT") and len(symbol) <= 5:
            symbol = f"{symbol}USDT"
        px = self.price(symbol)
        if px <= 0:
            return "rejected:no_price"
        qty = order.size_usd / px
        # Binance quantity precision — coarse round for demo
        qty = float(f"{qty:.5f}")
        if qty <= 0:
            return "rejected:qty"
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newClientOrderId": order.client_id[:36],
        }
        data = self._request("POST", "/api/v3/order", params=params, signed=True)
        status = str(data.get("status") or "UNKNOWN")
        return f"demo:{status}:{data.get('orderId')}"

    def cancel(self, client_id: str) -> bool:
        # Market orders fill immediately; cancel is a no-op for demo markets
        return False

    def positions(self) -> dict[str, Any]:
        return {b["asset"]: b for b in self.balances()}

    def kill_switch(self) -> None:
        self._killed = True

    def last_fill_from_order(self, raw: dict[str, Any]) -> BrokerFill | None:
        try:
            return BrokerFill(
                client_id=str(raw.get("clientOrderId") or ""),
                symbol=str(raw.get("symbol") or ""),
                side="long" if raw.get("side") == "BUY" else "short",
                qty=float(raw.get("executedQty") or 0),
                price=float(raw.get("cummulativeQuoteQty") or 0)
                / max(float(raw.get("executedQty") or 1), 1e-12),
                fee=0.0,
                ts=utc_now(),
            )
        except Exception:
            return None
