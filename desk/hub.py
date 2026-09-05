from __future__ import annotations

import asyncio
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from desk import calendar as econcal
from desk.eventdata import EventLedger
from desk.models import Asset
from desk.scoring import pct_change

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
BINANCE_HOSTS = [
    "https://api.binance.com",
    "https://api.binance.us",
    "https://data-api.binance.vision",
]
FAPI_HOSTS = [
    "https://fapi.binance.com",
    "https://fstream.binance.com",
    "https://data-api.binance.vision",
]
GECKO = "https://api.coingecko.com/api/v3"
YAHOO_HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart",
    "https://query2.finance.yahoo.com/v8/finance/chart",
)
YAHOO_FALLBACKS = {
    "XAUUSD=X": ("GC=F", "GLD"),
    "XAUUSD": ("GC=F", "GLD"),
    "XAU=X": ("GC=F", "GLD"),
    "XAGUSD=X": ("SI=F", "SLV"),
    "XAGUSD": ("SI=F", "SLV"),
}
BYBIT = "https://api.bybit.com"
HN = "https://hn.algolia.com/api/v1/search_by_date"


class DataHub:
    """One polite fetch cycle; all L1 agents read this snapshot."""

    def __init__(self, assets: list[Asset]) -> None:
        self.assets = assets
        self.by_symbol = {a.symbol: a for a in assets}
        self.by_binance = {a.binance: a for a in assets if a.binance}
        self._ttl: dict[str, tuple[float, Any]] = {}
        self.sources_ok: dict[str, bool] = {}
        self.snapshot: dict[str, Any] = {}
        self._rotate = 0
        self.ledger = EventLedger()

    def _cached(self, key: str, ttl: float) -> Any | None:
        hit = self._ttl.get(key)
        if not hit:
            return None
        exp, val = hit
        if time.time() > exp:
            return None
        return val

    def _put(self, key: str, val: Any, ttl: float) -> Any:
        self._ttl[key] = (time.time() + ttl, val)
        return val

    async def _get(self, client: httpx.AsyncClient, url: str, source: str, **kwargs: Any) -> Any:
        try:
            r = await client.get(url, timeout=12.0, **kwargs)
            r.raise_for_status()
            self.sources_ok[source] = True
            ctype = r.headers.get("content-type", "")
            if "json" in ctype or url.endswith(".json") or "api" in url:
                try:
                    return r.json()
                except Exception:
                    return r.text
            return r.text
        except Exception:
            if not self.sources_ok.get(source):
                self.sources_ok[source] = False
            return None

    async def _first_json(self, client: httpx.AsyncClient, hosts: list[str], path: str, source: str, **kwargs: Any) -> Any:
        for host in hosts:
            data = await self._get(client, host + path, source, **kwargs)
            if data is not None:
                return data
        return None

    async def refresh(self, tick: int = 0, focus: str | None = None) -> dict[str, Any]:
        self.sources_ok = dict(self.sources_ok)
        headers = {"User-Agent": UA, "Accept": "application/json, application/rss+xml, text/xml, */*"}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            tickers_t, funding_t, gecko_t, global_t = await asyncio.gather(
                self._tickers(client),
                self._funding(client),
                self._gecko(client),
                self._global(client),
            )
            heavy = await self._heavy_rotate(client, tick)
            spots = await self._yahoo_spots(client)
            macro = await self._macro(client)
            tnx_chg = None
            if isinstance((macro or {}).get("tnx"), dict):
                tnx_chg = (macro["tnx"] or {}).get("change_pct")
            news, reddit, fng, mempool, stables, econ = await asyncio.gather(
                self._news(client, tick, focus),
                self._reddit(client, focus),
                self._fear_greed(client),
                self._mempool(client),
                self._stables(gecko_t),
                self._calendar(client, tnx_chg),
            )

        snap = {
            "ts": time.time(),
            "tick": tick,
            "tickers": tickers_t or {},
            "funding": funding_t or {},
            "gecko": gecko_t or {},
            "global": global_t or {},
            "klines": heavy.get("klines", {}),
            "depth": heavy.get("depth", {}),
            "whales": heavy.get("whales", {}),
            "macro": macro or {},
            "news": news or [],
            "reddit": reddit or [],
            "fear_greed": fng,
            "mempool": mempool or {},
            "stables": stables or {},
            "calendar": econ or econcal.empty(),
            "sources_ok": dict(self.sources_ok),
            "marks": {},
        }
        for it in (econ or {}).get("headlines") or []:
            snap["news"].append(it)
        for sym, row in (spots or {}).items():
            snap["tickers"][sym] = row
        marks: dict[str, float] = {}
        for a in self.assets:
            t = snap["tickers"].get(a.symbol) or {}
            g = snap["gecko"].get(a.symbol) or {}
            px = t.get("price") or g.get("price")
            if px:
                marks[a.symbol] = float(px)
            if (not t.get("price")) and g.get("price"):
                chg = float(g.get("change_24h") or 0) / 100.0
                price = float(g["price"])
                open_px = price / (1 + chg) if price and chg != -1 else price
                snap["tickers"][a.symbol] = {
                    "price": price,
                    "open": open_px,
                    "high": price * (1 + abs(chg)),
                    "low": max(price * (1 - abs(chg)), price * 0.5) if price else 0,
                    "change_24h": float(g.get("change_24h") or 0),
                    "volume": 0.0,
                    "quote_volume": float(g.get("volume") or 0),
                    "source": g.get("source"),
                }
        snap["marks"] = marks
        # Phase 8 — event-time ledger for marks, news, macro
        now = time.time()
        for sym, px in marks.items():
            src = ((snap["tickers"].get(sym) or {}).get("source")) or "mark"
            self.ledger.record_mark(sym, float(px), str(src), event_time=now)
        for it in snap.get("news") or []:
            self.ledger.record_news(it if isinstance(it, dict) else {"title": str(it)}, source="news")
        fred = ((snap.get("calendar") or {}).get("fred") or {})
        for series, val in fred.items():
            if isinstance(val, (int, float)):
                self.ledger.record_macro(str(series), float(val), release_time=now, source="fred")
        snap["event_data"] = self.ledger.health()
        self.snapshot = snap
        return snap

    async def _tickers(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        cached = self._cached("tickers", 20)
        if cached is not None:
            return cached
        data = await self._first_json(client, BINANCE_HOSTS, "/api/v3/ticker/24hr", "binance")
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(data, list):
            return self._put("tickers", out, 20)
        wanted = set(self.by_binance)
        for row in data:
            sym = row.get("symbol")
            asset = self.by_binance.get(sym)
            if not asset or sym not in wanted:
                continue
            last = float(row.get("lastPrice") or 0)
            high = float(row.get("highPrice") or 0)
            low = float(row.get("lowPrice") or 0)
            open_px = float(row.get("openPrice") or 0)
            out[asset.symbol] = {
                "price": last,
                "open": open_px,
                "high": high,
                "low": low,
                "change_24h": float(row.get("priceChangePercent") or 0),
                "volume": float(row.get("volume") or 0),
                "quote_volume": float(row.get("quoteVolume") or 0),
                "trades": float(row.get("count") or 0),
                "weighted": float(row.get("weightedAvgPrice") or 0),
                "source": "binance ticker/24hr",
            }
        return self._put("tickers", out, 20)

    async def _funding(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        cached = self._cached("funding", 40)
        if cached is not None:
            return cached
        data = await self._first_json(client, FAPI_HOSTS, "/fapi/v1/premiumIndex", "binance_futures")
        out: dict[str, dict[str, Any]] = {}
        if isinstance(data, list):
            for row in data:
                asset = self.by_binance.get(row.get("symbol", ""))
                if not asset:
                    continue
                out[asset.symbol] = {
                    "funding": float(row.get("lastFundingRate") or 0),
                    "mark": float(row.get("markPrice") or 0),
                    "source": "binance premiumIndex",
                }
        if len(out) < max(4, len(self.by_binance) // 4):
            bybit = await self._bybit_linear(client)
            for sym, row in bybit.items():
                out.setdefault(sym, row)
        if len(out) < max(4, len(self.by_binance) // 4):
            okx = await self._okx_funding(client)
            for sym, row in okx.items():
                out.setdefault(sym, row)
        return self._put("funding", out, 40)

    async def _bybit_linear(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        data = await self._get(
            client,
            f"{BYBIT}/v5/market/tickers",
            "bybit_futures",
            params={"category": "linear"},
        )
        out: dict[str, dict[str, Any]] = {}
        rows = (data or {}).get("result", {}).get("list") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            return out
        for row in rows:
            asset = self.by_binance.get(row.get("symbol", ""))
            if not asset:
                continue
            out[asset.symbol] = {
                "funding": float(row.get("fundingRate") or 0),
                "mark": float(row.get("markPrice") or row.get("lastPrice") or 0),
                "source": "bybit linear tickers",
            }
        return out

    async def _okx_funding(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        async def one(asset: Asset) -> tuple[str, dict[str, Any]] | None:
            inst = f"{asset.symbol}-USDT-SWAP"
            data = await self._get(
                client,
                "https://www.okx.com/api/v5/public/funding-rate",
                "okx_futures",
                params={"instId": inst},
            )
            rows = (data or {}).get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list) or not rows:
                return None
            row = rows[0]
            try:
                rate = float(row.get("fundingRate") or 0)
            except Exception:
                return None
            return asset.symbol, {"funding": rate, "mark": 0.0, "source": f"okx {inst}"}

        gathered = await asyncio.gather(*(one(a) for a in self.assets if a.binance))
        return {sym: row for item in gathered if item for sym, row in [item]}

    async def _gecko(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        cached = self._cached("gecko", 45)
        if cached is not None:
            return cached
        ids = ",".join(a.id for a in self.assets if a.binance)
        data = await self._get(
            client,
            f"{GECKO}/coins/markets",
            "coingecko",
            params={"vs_currency": "usd", "ids": ids, "price_change_percentage": "1h,24h,7d"},
        )
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(data, list):
            return self._put("gecko", out, 45)
        id_map = {a.id: a for a in self.assets}
        for row in data:
            asset = id_map.get(row.get("id", ""))
            if not asset:
                continue
            out[asset.symbol] = {
                "price": float(row.get("current_price") or 0),
                "mcap": float(row.get("market_cap") or 0),
                "volume": float(row.get("total_volume") or 0),
                "change_1h": row.get("price_change_percentage_1h_in_currency"),
                "change_24h": row.get("price_change_percentage_24h_in_currency")
                or row.get("price_change_percentage_24h"),
                "change_7d": row.get("price_change_percentage_7d_in_currency"),
                "ath": row.get("ath"),
                "atl": row.get("atl"),
                "source": f"{GECKO}/coins/markets",
            }
        return self._put("gecko", out, 45)

    async def _global(self, client: httpx.AsyncClient) -> dict[str, Any]:
        cached = self._cached("global", 60)
        if cached is not None:
            return cached
        data = await self._get(client, f"{GECKO}/global", "coingecko_global")
        out: dict[str, Any] = {}
        if isinstance(data, dict) and "data" in data:
            d = data["data"]
            out = {
                "btc_dominance": float(d.get("market_cap_percentage", {}).get("btc") or 0),
                "eth_dominance": float(d.get("market_cap_percentage", {}).get("eth") or 0),
                "total_mcap": float(d.get("total_market_cap", {}).get("usd") or 0),
                "total_volume": float(d.get("total_volume", {}).get("usd") or 0),
                "mcap_change": float(d.get("market_cap_change_percentage_24h_usd") or 0),
                "source": f"{GECKO}/global",
            }
        return self._put("global", out, 60)

    async def _heavy_rotate(self, client: httpx.AsyncClient, tick: int) -> dict[str, Any]:
        crypto = [a for a in self.assets if a.binance]
        n = max(len(crypto), 1)
        start = (tick * 4) % n
        batch = [crypto[(start + i) % n] for i in range(min(4, n))] if crypto else []
        klines: dict[str, Any] = dict(self._cached("klines_acc", 400) or {})
        depth: dict[str, Any] = dict(self._cached("depth_acc", 120) or {})
        whales: dict[str, Any] = dict(self._cached("whales_acc", 90) or {})

        async def one(asset: Asset) -> None:
            if not asset.binance:
                return
            kl = await self._first_json(
                client,
                BINANCE_HOSTS,
                "/api/v3/klines",
                "binance_klines",
                params={"symbol": asset.binance, "interval": "1h", "limit": 48},
            )
            if isinstance(kl, list) and kl:
                closes = [float(x[4]) for x in kl]
                vols = [float(x[5]) for x in kl]
                klines[asset.symbol] = {"closes": closes, "volumes": vols, "source": "binance klines"}
            dp = await self._first_json(
                client,
                BINANCE_HOSTS,
                "/api/v3/depth",
                "binance_depth",
                params={"symbol": asset.binance, "limit": 20},
            )
            if isinstance(dp, dict) and dp.get("bids"):
                bids = [(float(p), float(q)) for p, q in dp["bids"][:10]]
                asks = [(float(p), float(q)) for p, q in dp.get("asks", [])[:10]]
                best_bid = bids[0][0] if bids else 0
                best_ask = asks[0][0] if asks else 0
                mid = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
                spread_bps = ((best_ask - best_bid) / mid * 1e4) if mid else None
                depth_usd = 0.0
                if mid:
                    depth_usd = sum(p * q for p, q in bids[:8]) * mid / max(mid, 1e-9)
                    depth_usd = sum(p * q for p, q in bids[:8]) + sum(p * q for p, q in asks[:8])
                depth[asset.symbol] = {
                    "spread_bps": spread_bps,
                    "depth_usd": depth_usd,
                    "source": "binance depth",
                }
            ag = await self._first_json(
                client,
                BINANCE_HOSTS,
                "/api/v3/aggTrades",
                "binance_trades",
                params={"symbol": asset.binance, "limit": 80},
            )
            buy = sell = 0.0
            if isinstance(ag, list):
                px = 0.0
                for tr in ag:
                    px = float(tr.get("p") or 0)
                    qty = float(tr.get("q") or 0)
                    notional = px * qty
                    if notional < 8000:
                        continue
                    if tr.get("m"):
                        sell += notional
                    else:
                        buy += notional
            whales[asset.symbol] = {
                "buy": buy,
                "sell": sell,
                "source": "binance aggTrades",
            }

        await asyncio.gather(*(one(a) for a in batch))
        self._put("klines_acc", klines, 400)
        self._put("depth_acc", depth, 120)
        self._put("whales_acc", whales, 90)
        return {"klines": klines, "depth": depth, "whales": whales}

    @staticmethod
    def _yahoo_intraday(symbol: str) -> bool:
        u = urllib.parse.unquote(symbol).upper()
        return (
            "XAU" in u
            or "XAG" in u
            or u in {"GC=F", "GLD", "SI=F", "SLV"}
            or u.endswith("=X")
        )

    async def _yahoo_chg(self, client: httpx.AsyncClient, symbol: str) -> dict[str, float] | None:
        candidates = [symbol]
        for alt in YAHOO_FALLBACKS.get(symbol, ()):
            if alt not in candidates:
                candidates.append(alt)
        # Gold/spot aliases often 404 — always try COMEX futures as last resort for XAU*.
        if "XAU" in symbol.upper() and "GC=F" not in candidates:
            candidates.append("GC=F")
        # Metals/FX: prefer 15m bars so marks/H-L move within the session (daily bars starve skill).
        schedules = (("15m", "5d"), ("1d", "5d")) if self._yahoo_intraday(symbol) else (("1d", "5d"),)
        for sym in candidates:
            path = urllib.parse.quote(sym, safe="")
            for interval, span in schedules:
                for host in YAHOO_HOSTS:
                    data = await self._get(
                        client,
                        f"{host}/{path}",
                        "yahoo",
                        params={"interval": interval, "range": span},
                    )
                    try:
                        result = data["chart"]["result"][0]
                        meta = result["meta"]
                        quote = result["indicators"]["quote"][0]
                        closes = [c for c in (quote.get("close") or []) if c is not None]
                        highs = [c for c in (quote.get("high") or []) if c is not None]
                        lows = [c for c in (quote.get("low") or []) if c is not None]
                        last = float(meta.get("regularMarketPrice") or closes[-1])
                        # Day change vs prior close; fall back to prior bar for sticky meta.
                        prev = float(meta.get("chartPreviousClose") or 0) or (
                            float(closes[-2]) if len(closes) >= 2 else last
                        )
                        # Structure: prefer session H/L from recent intraday bars when available.
                        if interval != "1d" and len(closes) >= 8:
                            window = max(8, min(len(closes), 32))
                            high = float(max(highs[-window:])) if highs else max(last, prev)
                            low = float(min(lows[-window:])) if lows else min(last, prev)
                        else:
                            high = float(max(highs)) if highs else max(last, prev)
                            low = float(min(lows)) if lows else min(last, prev)
                        return {
                            "price": last,
                            "change_pct": pct_change(last, prev),
                            "prev": prev,
                            "high": high,
                            "low": low,
                            "yahoo_sym": sym,
                        }
                    except Exception:
                        continue
        return None

    async def _yahoo_spots(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        assets = [a for a in self.assets if a.yahoo]
        if not assets:
            return {}
        rows = await asyncio.gather(*(self._yahoo_chg(client, a.yahoo) for a in assets))
        out: dict[str, dict[str, Any]] = {}
        for asset, row in zip(assets, rows):
            if not row:
                self.sources_ok[f"yahoo_{asset.symbol}"] = False
                continue
            self.sources_ok[f"yahoo_{asset.symbol}"] = True
            px = float(row["price"])
            prev = float(row.get("prev") or px)
            high = float(row.get("high") or max(px, prev))
            low = float(row.get("low") or min(px, prev))
            used = row.get("yahoo_sym") or asset.yahoo
            out[asset.symbol] = {
                "price": px,
                "open": prev,
                "high": high,
                "low": low,
                "change_24h": float(row.get("change_pct") or 0),
                "volume": 0.0,
                "quote_volume": 0.0,
                "source": f"yahoo {used}",
                "range_ok": high > low and abs(high - low) / max(px, 1e-9) > 1e-5,
            }
        return out

    async def _macro(self, client: httpx.AsyncClient) -> dict[str, Any]:
        cached = self._cached("macro", 180)
        if cached is not None:
            return cached
        dxy, vix, tnx, spx = await asyncio.gather(
            self._yahoo_chg(client, "DX-Y.NYB"),
            self._yahoo_chg(client, "%5EVIX"),
            self._yahoo_chg(client, "%5ETNX"),
            self._yahoo_chg(client, "%5EGSPC"),
        )
        out = {
            "dxy": dxy,
            "vix": vix,
            "tnx": tnx,
            "spx": spx,
            "source": "yahoo chart",
        }
        return self._put("macro", out, 180)

    async def _calendar(self, client: httpx.AsyncClient, tnx_chg: float | None = None) -> dict[str, Any]:
        cached = self._cached("econ_cal", 300)
        if cached is not None:
            return cached
        prior = self._cached("fred_series", 86400) or {}
        pack = await econcal.fetch(client, tnx_chg=tnx_chg, fred_prior=prior)
        # Persist series vectors for last-good fallback (side channel from calendar.fetch).
        series = pack.pop("_fred_series", None) or prior
        if series:
            self._put("fred_series", series, 86400)
        fred_ok = any(v is not None for v in (pack.get("fred") or {}).values())
        ok = bool(pack.get("events") or fred_ok)
        self.sources_ok["econ_calendar"] = ok
        self.sources_ok["fred"] = fred_ok
        ttl = 300 if fred_ok else 45
        return self._put("econ_cal", pack, ttl)

    def _parse_rss(self, xml_text: str, origin: str) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return items
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "").strip()
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()
            if title:
                items.append({"title": title, "link": link, "source": origin, "description": desc[:1200]})
        if not items:
            for entry in root.iter():
                if not str(entry.tag).endswith("entry"):
                    continue
                title = ""
                link = ""
                desc = ""
                for child in entry:
                    tag = str(child.tag).rsplit("}", 1)[-1]
                    if tag == "title":
                        title = (child.text or "").strip()
                    elif tag == "link":
                        link = child.attrib.get("href") or (child.text or "").strip()
                    elif tag in {"summary", "content"}:
                        desc = re.sub(r"<[^>]+>", " ", child.text or "")
                if title:
                    items.append({"title": title, "link": link, "source": origin, "description": re.sub(r"\s+", " ", desc).strip()[:1200]})
        return items[:40]

    def _google_news(self, query: str) -> str:
        q = re.sub(r"\s+", "+", query.strip())
        return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

    def _news_query(self, asset: Asset) -> str:
        bits = [asset.symbol]
        bits.extend(list(asset.keywords or [])[:4])
        if asset.yahoo and "gold" in " ".join(asset.keywords).lower():
            bits.extend(["gold price", "bullion", "XAU", "FOMC", "jobless claims", "NFP", "CPI"])
        if asset.binance and asset.symbol not in {"BTC", "ETH"}:
            bits.append("crypto")
        return " OR ".join(dict.fromkeys(bits))

    async def _ingest_feeds(self, client: httpx.AsyncClient, feeds: list[tuple[str, str]]) -> list[dict[str, str]]:
        gathered = await asyncio.gather(*[self._get(client, url, name) for url, name in feeds])
        items: list[dict[str, str]] = []
        seen: set[str] = set()
        for (url, _name), payload in zip(feeds, gathered):
            if not isinstance(payload, str):
                continue
            for it in self._parse_rss(payload, url):
                key = re.sub(r"\W+", "", (it.get("title") or "").lower())[:80]
                if not key or key in seen:
                    continue
                seen.add(key)
                items.append(it)
        return items

    async def _news(self, client: httpx.AsyncClient, tick: int = 0, focus: str | None = None) -> list[dict[str, str]]:
        cached = self._cached("news_core", 150)
        if cached is None:
            feeds = [
                ("https://www.coindesk.com/arc/outboundfeeds/rss/", "coindesk"),
                ("https://cointelegraph.com/rss", "cointelegraph"),
                ("https://www.theblock.co/rss.xml", "theblock"),
                ("https://decrypt.co/feed", "decrypt"),
                (self._google_news("cryptocurrency OR bitcoin OR ethereum"), "google_news"),
                (self._google_news("gold price OR XAUUSD OR bullion OR XAU"), "google_gold"),
                ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC=F,GLD,DX-Y.NYB&region=US&lang=en-US", "yahoo_news"),
                ("https://www.kitco.com/rss/kitcowire.xml", "kitco"),
                ("https://www.mining.com/feed/", "mining"),
            ]
            cached = await self._ingest_feeds(client, feeds)
            self._put("news_core", cached, 150)
        items = list(cached)
        n = max(len(self.assets), 1)
        start = (tick * 4) % n
        batch = [self.assets[(start + i) % n] for i in range(min(6, n))]
        focus_asset = next((a for a in self.assets if a.symbol == (focus or "").upper()), None)
        if focus_asset and focus_asset not in batch:
            batch = [focus_asset] + batch[:5]
        deep = [(self._google_news(self._news_query(a)), "google_desk") for a in batch]
        if focus_asset and focus_asset.yahoo:
            deep.append(
                (
                    f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={focus_asset.yahoo}&region=US&lang=en-US",
                    "yahoo_news",
                )
            )
        extra = await self._ingest_feeds(client, deep)
        seen = {re.sub(r"\W+", "", (it.get("title") or "").lower())[:80] for it in items}
        for it in extra:
            key = re.sub(r"\W+", "", (it.get("title") or "").lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(it)
        return items[:160]

    async def _reddit(self, client: httpx.AsyncClient, focus: str | None = None) -> list[dict[str, str]]:
        cached = self._cached("reddit", 180)
        posts: list[dict[str, str]] = list(cached or [])
        seen: set[str] = {re.sub(r"\W+", "", (p.get("title") or "").lower())[:80] for p in posts}

        def add(title: str, link: str, score: str = "0", sub: str = "") -> None:
            key = re.sub(r"\W+", "", title.lower())[:80]
            if not title or not key or key in seen:
                return
            seen.add(key)
            posts.append({"title": title, "link": link, "score": score, "sub": sub})

        hosts = ("https://old.reddit.com", "https://www.reddit.com")
        subs = ["CryptoCurrency", "bitcoin", "ethereum", "ethfinance", "solana", "Gold"]
        focus_asset = next((a for a in self.assets if a.symbol == (focus or "").upper()), None)
        if focus_asset and "gold" in " ".join(focus_asset.keywords).lower():
            subs.extend(["Wallstreetsilver", "GoldReforms"])
        if cached is None:
            json_blocked = False
            for sub in subs:
                # Prefer RSS — Reddit JSON often 403s from datacenter IPs.
                rss = await self._get(client, f"https://www.reddit.com/r/{sub}/hot.rss", "reddit")
                if isinstance(rss, str):
                    for it in self._parse_rss(rss, f"https://www.reddit.com/r/{sub}/"):
                        add(it["title"], it.get("link") or "", "0", sub)
                if len([p for p in posts if p.get("sub") == sub]) >= 3:
                    continue
                if json_blocked:
                    continue
                data = None
                for host in hosts:
                    data = await self._get(
                        client,
                        f"{host}/r/{sub}/hot.json",
                        "reddit",
                        params={"limit": "20", "raw_json": "1"},
                    )
                    if isinstance(data, dict):
                        break
                if data is None:
                    json_blocked = True
                    continue
                try:
                    children = data["data"]["children"]
                except Exception:
                    children = []
                for ch in children:
                    d = ch.get("data") or {}
                    title = d.get("title") or ""
                    if title:
                        add(title, "https://www.reddit.com" + str(d.get("permalink") or ""), str(d.get("score") or 0), sub)
            if len(posts) < 8:
                hn = await self._get(
                    client,
                    HN,
                    "hackernews",
                    params={"query": "bitcoin OR ethereum OR crypto OR gold", "tags": "story", "hitsPerPage": "25"},
                )
                hits = (hn or {}).get("hits") if isinstance(hn, dict) else None
                for row in hits or []:
                    title = str(row.get("title") or "").strip()
                    url = str(row.get("url") or f"https://news.ycombinator.com/item?id={row.get('objectID')}")
                    add(title, url, str(row.get("points") or 0), "hn")
            self._put("reddit", posts[:80], 180)
        if focus_asset:
            q = " OR ".join([focus_asset.symbol] + list(focus_asset.keywords or [])[:3])
            hn = await self._get(client, HN, "hackernews", params={"query": q, "tags": "story", "hitsPerPage": "15"})
            hits = (hn or {}).get("hits") if isinstance(hn, dict) else None
            for row in hits or []:
                title = str(row.get("title") or "").strip()
                url = str(row.get("url") or f"https://news.ycombinator.com/item?id={row.get('objectID')}")
                add(title, url, str(row.get("points") or 0), "hn")
        return posts[:80]

    async def _fear_greed(self, client: httpx.AsyncClient) -> int | None:
        cached = self._cached("fng", 300)
        if cached is not None:
            return cached
        data = await self._get(client, "https://api.alternative.me/fng/?limit=1", "fear_greed")
        try:
            val = int(data["data"][0]["value"])
        except Exception:
            val = None
        return self._put("fng", val, 300)

    async def _mempool(self, client: httpx.AsyncClient) -> dict[str, Any]:
        cached = self._cached("mempool", 120)
        if cached is not None:
            return cached
        data = await self._get(client, "https://mempool.space/api/v1/fees/recommended", "mempool")
        out = data if isinstance(data, dict) else {}
        if out:
            out["source"] = "https://mempool.space/api/v1/fees/recommended"
        return self._put("mempool", out, 120)

    async def _stables(self, gecko: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
        # Use last gecko global total volume as a proxy plus any USDT/USDC if present.
        return {
            "note": "stablecoin dry powder inferred from total crypto volume",
            "source": f"{GECKO}/global",
        }

    async def search_coins(self, query: str) -> list[dict[str, str]]:
        q = query.strip()
        if len(q) < 1:
            return []
        headers = {"User-Agent": UA, "Accept": "application/json"}
        async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
            data = await self._get(client, f"{GECKO}/search", "search", params={"query": q})
        coins = (data or {}).get("coins") if isinstance(data, dict) else None
        out: list[dict[str, str]] = []
        for row in coins or []:
            sym = str(row.get("symbol") or "").upper()
            cid = str(row.get("id") or "")
            name = str(row.get("name") or "")
            if not sym or not cid:
                continue
            out.append({"id": cid, "symbol": sym, "name": name})
            if len(out) >= 8:
                break
        return out

