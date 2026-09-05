from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from desk.config_load import ROOT
from desk.models import DecisionMemo, Fill, Position
from desk.paper import PaperBroker

DATA = ROOT / "data" / "desk.json"


def save_desk(
    paper: PaperBroker,
    memos: list[DecisionMemo],
    tick: int,
    history: dict[str, list[dict[str, Any]]] | None = None,
) -> None:
    DATA.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tick": tick,
        "starting": paper.starting,
        "cash": paper.cash,
        "marks": paper.marks,
        "history": {k: v[-48:] for k, v in (history or {}).items()},
        "positions": [p.as_dict() for p in paper.positions.values()],
        "fills": [
            {"idea_id": f.idea_id, "symbol": f.symbol, "side": f.side, "qty": f.qty, "price": f.price, "ts": f.ts}
            for f in paper.fills[-200:]
        ],
        "memos": [
            {
                "id": m.id,
                "symbol": m.symbol,
                "side": m.side,
                "conviction": m.conviction,
                "size_usd": m.size_usd,
                "entry": m.entry,
                "stop": m.stop,
                "target": m.target,
                "thesis": m.thesis,
                "invalidation": m.invalidation,
                "factors": m.factors,
                "risk_notes": m.risk_notes,
                "status": m.status,
                "ts": m.ts,
            }
            for m in memos[-80:]
        ],
    }
    tmp = DATA.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(DATA)


def restore_desk(
    paper: PaperBroker, memos: list[DecisionMemo]
) -> tuple[int, list[DecisionMemo], dict[str, list[dict[str, Any]]]]:
    if not DATA.exists():
        return 0, memos, {}
    try:
        raw: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return 0, memos, {}
    paper.starting = float(raw.get("starting") or paper.starting)
    if raw.get("cash") is not None:
        paper.cash = float(raw["cash"])
    if paper.cash <= 0 and not (raw.get("positions") or []):
        paper.cash = paper.starting
    paper.marks = dict(raw.get("marks") or {})
    paper.positions = {}
    for row in raw.get("positions") or []:
        paper.positions[row["symbol"]] = Position(
            symbol=row["symbol"],
            side=row["side"],
            qty=float(row["qty"]),
            avg_price=float(row["avg_price"]),
            mark=float(row.get("mark") or row["avg_price"]),
            stop=float(row.get("stop") or 0),
            target=float(row.get("target") or 0),
        )
    paper.fills = [
        Fill(
            idea_id=f["idea_id"],
            symbol=f["symbol"],
            side=f["side"],
            qty=float(f["qty"]),
            price=float(f["price"]),
            ts=float(f["ts"]),
        )
        for f in raw.get("fills") or []
    ]
    restored = [DecisionMemo(**m) for m in raw.get("memos") or []]
    hist = raw.get("history") if isinstance(raw.get("history"), dict) else {}
    return int(raw.get("tick") or 0), restored, hist
