from __future__ import annotations

import json
import re
from typing import Any

import httpx

EMBED_MARKERS = ("embed", "nomic", "minilm", "bge-", "mxbai")

# Resident qwen on every layer so Ollama does not swap llama in (NUM_PARALLEL=1).
LAYER_PREFS: dict[int, tuple[str, ...]] = {
    1: ("qwen2.5:3b", "qwen2.5", "phi3", "llama3.2:3b", "mistral", "llama3.1"),
    2: ("qwen2.5:3b", "qwen2.5", "phi3", "mistral", "llama3.2"),
    3: ("qwen2.5:3b", "qwen2.5", "llama3.2:3b", "mistral", "llama3.1"),
    4: ("qwen2.5:3b", "qwen2.5", "mistral", "llama3.2", "llama3.1"),
    5: ("qwen2.5:3b", "qwen2.5", "mistral", "llama3.1"),
}


def parse_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fence.group(1) if fence else text
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = raw[start : end + 1]
    try:
        data = json.loads(blob)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", blob)
        try:
            data = json.loads(cleaned)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _is_generative(name: str) -> bool:
    low = name.lower()
    return not any(m in low for m in EMBED_MARKERS)


def _match(names: list[str], wanted: str) -> str:
    return next((n for n in names if wanted == n or wanted in n or n.startswith(wanted.split(":")[0])), "")


def assign_layer_models(installed: list[str], cfg_layers: dict[str, Any] | None = None) -> dict[int, str]:
    gen = [n for n in installed if _is_generative(n)]
    assigned: dict[int, str] = {}
    cfg_layers = cfg_layers or {}
    for layer in range(1, 6):
        preferred = str(cfg_layers.get(str(layer)) or cfg_layers.get(layer) or "").strip()
        if preferred:
            hit = _match(gen, preferred)
            if hit:
                assigned[layer] = hit
                continue
        for cand in LAYER_PREFS[layer]:
            hit = _match(gen, cand)
            if hit:
                assigned[layer] = hit
                break
        if layer not in assigned and gen:
            assigned[layer] = gen[0]
    uniq = list(dict.fromkeys(gen))
    # Keep L4 on the resident L1/L2 model when possible so llama is not swapped in for attacks.
    if assigned.get(4) and assigned.get(1) and assigned[4] != assigned[1]:
        if assigned.get(3) and assigned[4] == assigned[3]:
            assigned[4] = assigned[1]
    return assigned


class LocalLLM:
    """Pool of local Ollama models — one family per research layer when possible."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        llm = cfg.get("llm") or {}
        self.host = str(llm.get("host") or "http://127.0.0.1:11434").rstrip("/")
        self.preferred = str(llm.get("model") or "")
        self.timeout = float(llm.get("timeout") or 180)
        self.cfg_layers = llm.get("layers") if isinstance(llm.get("layers"), dict) else {}
        self.model = ""
        self.layer_models: dict[int, str] = {}
        self.ok = False
        self.last_error = "not probed"
        self.layer_error: dict[int, str] = {}

    def model_for(self, layer: int | None = None) -> str:
        if layer and self.layer_models.get(layer):
            return self.layer_models[layer]
        return self.model

    def status(self) -> dict[str, Any]:
        layers = {
            str(k): {"model": v, "ok": self.ok and not self.layer_error.get(k)}
            for k, v in self.layer_models.items()
        }
        return {
            "ok": self.ok,
            "model": self.model or None,
            "host": self.host,
            "error": None if self.ok else self.last_error,
            "layers": layers,
        }

    async def probe(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"{self.host}/api/tags")
                r.raise_for_status()
                names = [m.get("name") for m in (r.json().get("models") or []) if m.get("name")]
        except Exception as exc:
            self.ok = False
            self.model = ""
            self.layer_models = {}
            self.last_error = str(exc)[:120]
            return
        gen = [n for n in names if _is_generative(n)]
        if not gen:
            self.ok = False
            self.last_error = "ollama has no generative models"
            return
        self.layer_models = assign_layer_models(names, self.cfg_layers)
        self.model = self.layer_models.get(5) or self.preferred or gen[0]
        if self.preferred:
            hit = _match(gen, self.preferred)
            if hit:
                self.model = hit
                if 5 not in self.cfg_layers:
                    self.layer_models[5] = hit
        self.ok = True
        self.last_error = ""
        self.layer_error = {}

    async def warmup(self, layers: tuple[int, ...] = (1, 2, 4)) -> None:
        if not self.ok:
            await self.probe()
        if not self.ok:
            return
        seen: set[str] = set()
        for layer in layers:
            model = self.layer_models.get(layer)
            if not model or model in seen:
                continue
            seen.add(model)
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    await client.post(
                        f"{self.host}/api/generate",
                        json={
                            "model": model,
                            "prompt": "Reply with ok.",
                            "stream": False,
                            "keep_alive": "45m",
                            "options": {"num_predict": 4, "temperature": 0},
                        },
                    )
            except Exception as exc:
                self.last_error = str(exc)[:160]

    async def complete(
        self,
        prompt: str,
        system: str,
        max_tokens: int = 220,
        layer: int | None = None,
        temperature: float = 0.25,
        force_json: bool = False,
    ) -> str | None:
        if not self.ok or not self.model:
            await self.probe()
        model = self.model_for(layer)
        if not self.ok or not model:
            return None
        body: dict[str, Any] = {
            "model": model,
            "prompt": f"{system.strip()}\n\n{prompt.strip()}",
            "stream": False,
            "keep_alive": "45m",
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if force_json:
            body["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.host}/api/generate", json=body)
                r.raise_for_status()
                text = (r.json().get("response") or "").strip()
                return text or None
        except Exception as exc:
            err = str(exc)[:160]
            self.last_error = err
            if layer:
                self.layer_error[layer] = err
            return None

    async def complete_json(
        self,
        prompt: str,
        system: str,
        max_tokens: int = 700,
        layer: int | None = None,
        temperature: float = 0.15,
        retries: int = 1,
    ) -> dict[str, Any] | None:
        last_err = "no response"
        for attempt in range(retries + 1):
            text = await self.complete(
                prompt,
                system + "\nReply with a single JSON object only. No markdown.",
                max_tokens,
                layer=layer,
                temperature=temperature + attempt * 0.12,
                force_json=True,
            )
            data = parse_json_object(text or "")
            if data is not None:
                if layer:
                    self.layer_error.pop(layer, None)
                return data
            last_err = "model returned non-JSON" if text else (self.last_error or "empty")
        self.last_error = last_err
        if layer:
            self.layer_error[layer] = last_err[:80]
        return None

    async def blotter_brief(self, symbol: str, payload: dict[str, Any]) -> str | None:
        analysis = payload.get("analysis") or {}
        challenge = payload.get("challenge") or {}
        book = payload.get("book") or {}
        debate = payload.get("debate") or []
        talk = "; ".join(str(d.get("text") or "")[:80] for d in debate[-4:])
        prompt = (
            f"Brief the blotter for {symbol} in 3 sentences. "
            f"Mark {payload.get('mark')}. Blend {analysis.get('blended')}. "
            f"Thesis: {str(analysis.get('thesis') or '')[:400]} "
            f"Verifier flags: {book.get('flags')}. "
            f"L4: veto={challenge.get('veto')} attacks={challenge.get('attacks')}. "
            f"Layer debate: {talk or 'none'}. "
            f"State what is known vs unknown. No trade instruction unless L5 already wrote a memo."
        )
        system = "You are a desk blotter. Compress research. No hype. No live-trading advice."
        return await self.complete(prompt, system, max_tokens=180, layer=5)
