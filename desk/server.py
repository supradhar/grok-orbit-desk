from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from desk.orchestrator import OrbitDesk

WEB = Path(__file__).resolve().parent.parent / "web"
desk = OrbitDesk()


class WatchItem(BaseModel):
    id: str
    symbol: str
    name: str = ""
    yahoo: str = ""


class FocusItem(BaseModel):
    symbol: str = ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(desk.loop())
    yield
    task.cancel()


app = FastAPI(title="Grok Orbit Desk", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=str(WEB)), name="assets")


@app.middleware("http")
async def no_store_ui(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/assets"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
async def state() -> dict:
    return desk.client_state()


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "tick": desk.tick,
        "regime": desk.regime,
        "sources_ok": desk.sources_ok,
        "agents": len(desk.agents),
        "equity": desk.paper.equity,
        "llm": desk.llm.status(),
        "focus": desk.focus_symbol,
        "committee_ok": desk.committee_ok,
        "clock": desk.clock,
        "decision_tick": desk.decision_tick,
        "embed": {"ok": desk.embed.ok, "model": desk.embed.model or None},
    }


@app.get("/api/search")
async def search(q: str = "") -> dict:
    hits = await desk.search_tickers(q)
    return {"query": q, "hits": hits}


@app.post("/api/watchlist")
async def watchlist(item: WatchItem) -> dict:
    msg = await desk.add_ticker(item.id, item.symbol, item.name, item.yahoo)
    return {"ok": msg in {"added", "exists"}, "message": msg}


@app.get("/api/symbols/{symbol}")
async def symbol(symbol: str) -> dict:
    detail = desk.symbol_detail(symbol)
    if not detail:
        return {"ok": False, "message": "unknown symbol"}
    return detail


@app.post("/api/symbols/{symbol}/brief")
async def brief(symbol: str) -> dict:
    text = await desk.blotter_brief(symbol)
    return {"ok": bool(text), "brief": text, "llm": desk.llm.status()}


@app.post("/api/memos/{memo_id}/approve")
async def approve(memo_id: str) -> dict:
    msg = await desk.decide(memo_id, True)
    return {"ok": msg == "filled", "message": msg}


@app.post("/api/memos/{memo_id}/reject")
async def reject(memo_id: str) -> dict:
    msg = await desk.decide(memo_id, False)
    return {"ok": True, "message": msg}


@app.post("/api/positions/{symbol}/close")
async def close_position(symbol: str) -> dict:
    msg = await desk.close_position(symbol)
    return {"ok": msg == "closed", "message": msg}


@app.post("/api/focus")
async def focus(item: FocusItem) -> dict:
    symbol = desk.set_focus(item.symbol)
    return {"ok": True, "symbol": symbol}


@app.post("/api/tick")
async def tick(item: FocusItem | None = None) -> dict:
    if item and item.symbol:
        desk.set_focus(item.symbol)
    snap = await desk.cycle()
    return {
        "tick": snap.tick,
        "regime": snap.regime,
        "pending": sum(1 for m in snap.memos if m.status == "pending"),
        "committee_ok": desk.committee_ok,
        "focus": desk.focus_symbol,
        "clock": desk.clock,
        "decision_tick": desk.decision_tick,
    }


@app.get("/api/lab")
async def lab() -> dict:
    return desk.research_lab()


@app.get("/api/lab/attribution")
async def lab_attribution() -> dict:
    from desk.factors import agent_attribution

    return {"rows": agent_attribution(desk.history)}


@app.get("/api/lab/ablation")
async def lab_ablation() -> dict:
    from desk.factors import ablation_study

    return ablation_study(desk.history)


@app.get("/api/lab/ml")
async def lab_ml() -> dict:
    from desk.ml_alpha import train_logistic_alpha

    result = train_logistic_alpha(desk.history)
    result.pop("model", None)
    return result


@app.get("/api/experiments")
async def experiments() -> dict:
    from desk.research_db import ResearchDB

    db = ResearchDB()
    try:
        return {"experiments": db.list_experiments()}
    finally:
        db.close()


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    desk.listeners.append(q)
    try:
        await sock.send_json(desk.snapshot_plain())
        while True:
            payload = await q.get()
            await sock.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        if q in desk.listeners:
            desk.listeners.remove(q)
