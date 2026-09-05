from __future__ import annotations

import math
import re
from typing import Any

import httpx


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return dot / (na * nb)


class Embedder:
    """Local nomic (or first embed model) via Ollama. Cached by text."""

    def __init__(self, host: str, model: str = "nomic-embed-text") -> None:
        self.host = host.rstrip("/")
        self.preferred = model
        self.model = ""
        self.ok = False
        self._cache: dict[str, list[float]] = {}

    async def probe(self, installed: list[str] | None = None) -> None:
        names = installed or []
        if not names:
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(f"{self.host}/api/tags")
                    r.raise_for_status()
                    names = [m.get("name") for m in (r.json().get("models") or []) if m.get("name")]
            except Exception:
                self.ok = False
                return
        hit = next((n for n in names if self.preferred in n or "nomic" in n or "embed" in n.lower()), "")
        if not hit:
            self.ok = False
            self.model = ""
            return
        self.model = hit
        self.ok = True

    async def embed(self, text: str) -> list[float] | None:
        key = (text or "").strip()[:400]
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        if not self.ok:
            await self.probe()
        if not self.ok or not self.model:
            return None
        vec: list[float] | None = None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.host}/api/embed",
                    json={"model": self.model, "input": key, "keep_alive": "45m"},
                )
                if r.status_code == 200:
                    data = r.json()
                    embs = data.get("embeddings") or []
                    if embs:
                        vec = list(embs[0])
                if vec is None:
                    r = await client.post(
                        f"{self.host}/api/embeddings",
                        json={"model": self.model, "prompt": key, "keep_alive": "45m"},
                    )
                    r.raise_for_status()
                    vec = list((r.json().get("embedding") or []))
        except Exception:
            return None
        if not vec:
            return None
        self._cache[key] = vec
        if len(self._cache) > 400:
            for k in list(self._cache)[:80]:
                self._cache.pop(k, None)
        return vec

    async def tag_news(self, items: list[dict[str, Any]], assets: list[Any], use_embed: bool = True) -> None:
        if not items:
            return
        for it in items:
            low = (str(it.get("title") or "") + " " + str(it.get("description") or "")).lower()
            tickers: list[str] = []
            for a in assets:
                kws = list(dict.fromkeys([*(a.keywords or []), a.symbol, a.id.replace("-", " ")]))
                if any(re.search(rf"\b{re.escape(str(k).lower())}\b", low) for k in kws if k):
                    tickers.append(a.symbol)
            it["tickers"] = tickers
        if not use_embed:
            return
        if not self.ok:
            await self.probe()
        if not self.ok:
            return
        queries: dict[str, list[float]] = {}
        for a in assets[:16]:
            q = " ".join([a.symbol, a.id.replace("-", " ")] + list(a.keywords or [])[:3])
            vec = await self.embed(q)
            if vec:
                queries[a.symbol] = vec
        extra = [it for it in items if not it.get("tickers")][:24]
        matched = [it for it in items if it.get("tickers") and not it.get("vec")][:18]
        for it in extra + matched:
            blob = f"{it.get('title') or ''} {str(it.get('description') or '')[:200]}"
            vec = await self.embed(blob)
            if not vec:
                continue
            it["vec"] = vec
            for a in assets:
                if a.symbol in (it.get("tickers") or []):
                    continue
                sim = cosine(vec, queries[a.symbol]) if a.symbol in queries else 0.0
                if sim >= 0.32:
                    it.setdefault("tickers", []).append(a.symbol)

    def cluster(self, items: list[dict[str, Any]], threshold: float = 0.72) -> list[dict[str, Any]]:
        clusters: list[dict[str, Any]] = []
        for it in items:
            vec = it.get("vec")
            placed = False
            if vec:
                for c in clusters:
                    if cosine(vec, c["vec"]) >= threshold:
                        c["items"].append(it)
                        placed = True
                        break
            if not placed:
                title = str(it.get("title") or "story")
                clusters.append(
                    {
                        "label": " ".join(title.lower().split()[:3]),
                        "items": [it],
                        "vec": vec or [],
                    }
                )
        return clusters
