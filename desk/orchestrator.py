from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Any

from desk import layer1, layer2, layer3, layer4, layer5, layer_llm
from desk.bus import EventBus
from desk.catalog import CATALOG
from desk.config_load import load_config
from desk.embed import Embedder
from desk.hub import DataHub
from desk.ic import CORE, blend_weights, factor_ics, mix_ic, recent_factor_series
from desk.llm import LocalLLM
from desk.models import AgentState, Asset, DecisionMemo, DeskSnapshot, to_plain
from desk.paper import PaperBroker
from desk.quality import research_quality, skill_map
from desk import risk
from desk.scoring import utc_now
from desk import signal
from desk.store import restore_desk, save_desk


class OrbitDesk:
    def __init__(self) -> None:
        cfg, assets = load_config()
        self.cfg = cfg
        self.assets = assets
        self.sectors: dict[str, list[str]] = cfg.get("sectors") or {}
        self.hub = DataHub(assets)
        self.bus = EventBus()
        self.paper = PaperBroker(
            equity=float(cfg["equity"]),
            slippage_bps=float(cfg.get("slippage_bps") or 6),
            max_gross_pct=float(cfg.get("max_gross_exposure_pct") or 0.55),
            fee_bps=float(cfg.get("fee_bps") or 4),
            risk_day_tz=str(cfg.get("risk_day_tz") or "UTC"),
        )
        self.history_rows = int(cfg.get("history_rows") or 512)
        self.agents: list[AgentState] = (
            layer1.spawn_agents(assets, self.sectors)
            + layer2.spawn_agents(assets)
            + layer3.spawn_agents(assets, self.sectors)
            + layer4.spawn_agents(assets)
            + layer5.spawn_agents()
            + layer_llm.spawn_llm_agents()
        )
        self.factors: list = []
        self.books: list = []
        self.analyses: list = []
        self.challenges: list = []
        self.memos: list[DecisionMemo] = []
        self.tick = 0
        self.regime = "unknown"
        self.sources_ok: dict[str, bool] = {}
        self.history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.journal: list[dict[str, Any]] = []
        self.llm = LocalLLM(cfg)
        self.embed = Embedder(self.llm.host)
        self.llm_layers: dict[int, bool] = {}
        self.debate: list[dict[str, Any]] = []
        self.focus_symbol: str | None = None
        self.committee_ok = False
        self.clock = "idle"
        self.decision_tick = 0
        self.ic_weights: dict[str, float] = {f: 1.0 for f in CORE}
        self.ics: dict[str, dict[str, Any]] = {}
        self.mix_ic: float | None = None
        self.checklists: dict[str, dict[str, Any]] = {}
        self.in_play: list[str] = []
        self._last_play: set[str] = set()
        self._last_promote: set[str] = set()
        self.telemetry: dict[str, Any] = {}
        self._skill: dict[str, dict[str, Any]] = {}
        self._snap: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self.listeners: list[asyncio.Queue] = []
        saved_tick, saved_memos, saved_hist = restore_desk(self.paper, self.memos)
        self.tick = saved_tick
        if saved_memos:
            self.memos = saved_memos
        if saved_hist:
            for sym, rows in saved_hist.items():
                self.history[sym] = rows[-self.history_rows :]
        self.paper.halted = risk.halted(self.paper, float(cfg.get("max_daily_loss_pct") or 0.02))
        risk.ensure_stops(self.paper, stop_pct=float(cfg.get("stop_pct") or 0.02), history=self.history)
        self._refresh_ic()

    def research_lab(self) -> dict[str, Any]:
        """Phase 5/7/10/13 — compact research terminal payload."""
        from desk.factors import ablation_study, agent_attribution, factor_decay
        from desk.ic import CORE
        from desk.portfolio_risk import risk_snapshot

        hist_marks = {
            s: [float(r["mark"]) for r in rows if r.get("mark")]
            for s, rows in self.history.items()
        }
        notionals = {
            s: float(p.notional)
            for s, p in self.paper.positions.items()
        }
        attr = agent_attribution(self.history) if self.history else []
        decay = {f: factor_decay(self.history, f) for f in list(CORE)[:4]} if self.history else {}
        try:
            abl = ablation_study(self.history) if sum(len(v) for v in self.history.values()) >= 20 else {}
        except Exception:
            abl = {}
        return {
            "attribution": attr[:12],
            "decay": decay,
            "ablation": abl,
            "portfolio_risk": risk_snapshot(notionals, hist_marks) if notionals else {},
            "environment": "paper",
        }

    def action_tape(self) -> dict[str, Any]:
        focus = self.focus_symbol
        chal = next((c for c in self.challenges if c.symbol == focus), None) if focus else None
        arts = [f for f in self.factors if f.factor == "article" and (not focus or f.symbol == focus)]
        desks = [
            {
                "name": a.name,
                "factor": a.factor,
                "score": a.last_score,
                "note": a.last_note,
                "status": a.status,
                "symbol": a.symbol,
            }
            for a in self.agents
            if a.layer == 1
            and focus
            and a.symbol == focus
            and a.factor in {"article", "social_post", "news", "momentum", "liquidity", "structure", "volume", "policy"}
        ]
        if not focus:
            now = "Open a ticker to watch L1 article desks work that name."
        else:
            n = len(arts)
            clusters = len({(f.note or "").split("]")[0] for f in arts})
            l4 = ""
            if chal:
                l4 = " L4 vetoed." if chal.veto else " L4 passed."
            gate = " L5 gate blocked." if not self.committee_ok else " L5 gate open."
            headlines = len((self.hub.snapshot or {}).get("news") or [])
            now = (
                f"L1 {focus}: {n} article researcher{'s' if n != 1 else ''} on "
                f"{clusters or 0} story group{'s' if clusters != 1 else ''} "
                f"from {headlines} headlines.{l4}{gate}"
            )
        return {"now": now, "desks": desks[:18], "articles": [to_plain(f) for f in arts[:12]]}

    def memo_by_id(self, memo_id: str) -> DecisionMemo | None:
        return next((m for m in self.memos if m.id == memo_id), None)

    def heatmap(self) -> dict[str, dict[str, float | None]]:
        grid: dict[str, dict[str, float]] = {}
        watch = {a.symbol for a in self.assets}
        skip = {"article", "social_post"}
        for f in self.factors:
            if not f.symbol or f.layer != 1 or f.symbol not in watch:
                continue
            if f.factor in skip:
                continue
            if getattr(f, "unknown", False):
                grid.setdefault(f.symbol, {})[f.factor] = None
            else:
                grid.setdefault(f.symbol, {})[f.factor] = round(f.score, 1)
        return grid

    def _funnel(self) -> dict[str, Any]:
        return {
            "factors": len(self.factors),
            "verified": sum(1 for b in self.books if not b.garbage),
            "garbage": sum(1 for b in self.books if b.garbage),
            "pass": sum(1 for c in self.challenges if not c.veto),
            "veto": sum(1 for c in self.challenges if c.veto),
            "pending": sum(1 for m in self.memos if m.status == "pending"),
            "approved": sum(1 for m in self.memos if m.status == "approved"),
            "articles": sum(1 for f in self.factors if f.factor == "article"),
            "headlines": len((self.hub.snapshot or {}).get("news") or []),
            "social": len((self.hub.snapshot or {}).get("reddit") or []),
            "next_print": ((self.hub.snapshot or {}).get("calendar") or {}).get("next", {}) or {},
            "clock": self.clock,
            "decision_tick": self.decision_tick,
            "in_play": list(self.in_play),
            "hmm": (self.telemetry.get("hmm") or {}).get("state"),
            "halted": bool(self.paper.halted),
        }

    def _note(self, label: str, detail: str = "") -> None:
        self.journal.append({"ts": utc_now(), "tick": self.tick, "label": label, "detail": detail[:180]})
        self.journal = self.journal[-40:]

    def snapshot(self) -> DeskSnapshot:
        stats = {
            "agents": len(self.agents),
            "l1": sum(1 for a in self.agents if a.layer == 1),
            "l2": sum(1 for a in self.agents if a.layer == 2),
            "l3": sum(1 for a in self.agents if a.layer == 3),
            "l4": sum(1 for a in self.agents if a.layer == 4),
            "l5": sum(1 for a in self.agents if a.layer == 5),
            "pending": sum(1 for m in self.memos if m.status == "pending"),
            "approved": sum(1 for m in self.memos if m.status == "approved"),
            "llm_layers": {str(k): v for k, v in self.llm_layers.items()},
        }
        eq = self.paper.equity
        return DeskSnapshot(
            ts=utc_now(),
            equity=eq,
            cash=self.paper.cash,
            pnl=eq - self.paper.starting,
            tick=self.tick,
            regime=self.regime,
            agents=self.agents,
            factors=self.factors[-240:],
            books=self.books,
            analyses=self.analyses,
            challenges=self.challenges,
            memos=list(reversed(self.memos[-40:])),
            positions=self.paper.snapshot_positions(),
            marks=dict(self.paper.marks),
            packets=self.bus.recent(50),
            sources_ok=self.sources_ok,
            stats=stats,
            heatmap=self.heatmap(),
            journal=list(self.journal[-24:]),
            history={k: v[-self.history_rows :] for k, v in self.history.items()},
            funnel=self._funnel(),
            exposure_pct=(self.paper.gross / eq) if eq else 0.0,
        )

    def client_state(self) -> dict[str, Any]:
        """Slim payload for the websocket — inspector fetches full symbol detail."""
        snap = self.snapshot()
        return {
            "ts": snap.ts,
            "equity": snap.equity,
            "cash": snap.cash,
            "pnl": snap.pnl,
            "tick": snap.tick,
            "regime": snap.regime,
            "exposure_pct": snap.exposure_pct,
            "stats": snap.stats,
            "funnel": snap.funnel,
            "sources_ok": snap.sources_ok,
            "marks": snap.marks,
            "heatmap": snap.heatmap,
            "history": snap.history,
            "journal": snap.journal,
            "positions": snap.positions,
            "packets": snap.packets[-12:],
            "llm": {**self.llm.status(), "ran": {str(k): v for k, v in self.llm_layers.items()}},
            "debate": self.debate[-16:],
            "focus": self.focus_symbol,
            "committee_ok": self.committee_ok,
            "clock": self.clock,
            "decision_tick": self.decision_tick,
            "in_play": list(self.in_play),
            "ic": {"weights": self.ic_weights, "ics": self.ics, "mix": self.mix_ic},
            "checklists": self.checklists,
            "embed": {"ok": self.embed.ok, "model": self.embed.model or None},
            "telemetry": {
                "hmm": (self.telemetry.get("hmm") or {}),
                "graph": (self.telemetry.get("graph") or [])[:8],
                "hawkes": self.telemetry.get("hawkes") or {},
            },
            "quality": research_quality(self.history, signal.residual_floor(self.cfg)),
            "lab": self.research_lab(),
            "risk": risk.snapshot(self.paper, float(self.cfg.get("max_daily_loss_pct") or 0.02)),
            "calendar": (self.hub.snapshot or {}).get("calendar") or {},
            "action": self.action_tape(),
            "watchlist": [
                {"symbol": a.symbol, "id": a.id, "keywords": a.keywords, "name": a.id.replace("-", " ")}
                for a in self.assets
            ],
            "memos": to_plain(snap.memos),
            "analyses": [
                {
                    "symbol": r.symbol,
                    "blended": round(r.blended, 2),
                    "confidence": round(r.confidence, 3),
                    "agreement": round(r.agreement, 3),
                    "regime": r.regime,
                    "thesis": r.thesis,
                    "bull_factors": r.bull_factors,
                    "bear_factors": r.bear_factors,
                    "trust": round(r.trust, 3),
                    "residual": round(float(getattr(r, "residual", 0) or 0), 2),
                    "beta": round(float(getattr(r, "beta", 0) or 0), 3),
                    "beta_ok": bool(getattr(r, "beta_ok", False) or r.symbol == "BTC"),
                    "sigma": round(float(getattr(r, "sigma", 0) or 0), 1),
                    "hawkes": round(float(getattr(r, "hawkes", 0) or 0), 2),
                }
                for r in self.analyses
            ],
            "challenges": [
                {
                    "symbol": c.symbol,
                    "veto": c.veto,
                    "conviction_adj": c.conviction_adj,
                    "attacks": c.attacks,
                    "surviving_thesis": c.surviving_thesis,
                }
                for c in self.challenges
            ],
            "books": [
                {
                    "symbol": b.symbol,
                    "trust": round(b.trust, 3),
                    "flags": b.flags,
                    "blended_raw": round(b.blended_raw, 2),
                    "garbage": b.garbage,
                }
                for b in self.books
            ],
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "layer": a.layer,
                    "factor": a.factor,
                    "symbol": a.symbol,
                    "status": a.status,
                    "last_score": a.last_score,
                    "last_note": (a.last_note or "")[:80],
                    "last_beat": a.last_beat,
                    "color": a.color,
                }
                for a in self.agents
            ],
        }

    def symbol_detail(self, symbol: str) -> dict[str, Any] | None:
        sym = symbol.upper()
        if not any(a.symbol == sym for a in self.assets):
            return None
        factors = [to_plain(f) for f in self.factors if f.symbol == sym]
        book = next((b for b in self.books if b.symbol == sym), None)
        analysis = next((r for r in self.analyses if r.symbol == sym), None)
        challenge = next((c for c in self.challenges if c.symbol == sym), None)
        return {
            "symbol": sym,
            "mark": self.paper.marks.get(sym),
            "factors": factors,
            "book": to_plain(book) if book else None,
            "analysis": to_plain(analysis) if analysis else None,
            "challenge": to_plain(challenge) if challenge else None,
            "history": self.history.get(sym, [])[-self.history_rows :],
            "memos": to_plain([m for m in self.memos if m.symbol == sym][-8:]),
            "position": next((p for p in self.paper.snapshot_positions() if p["symbol"] == sym), None),
            "debate": [d for d in self.debate if d.get("symbol") == sym][-12:],
            "articles": [to_plain(f) for f in self.factors if f.symbol == sym and f.factor == "article"][:12],
            "social_posts": [to_plain(f) for f in self.factors if f.symbol == sym and f.factor == "social_post"][:6],
            "checklist": self.checklists.get(sym),
            "calendar": (self.hub.snapshot or {}).get("calendar") or {},
            "telemetry": {
                "beta": float(getattr(analysis, "beta", 0) or 0) if analysis else 0,
                "beta_ok": bool(getattr(analysis, "beta_ok", False) or (analysis and analysis.symbol == "BTC")) if analysis else False,
                "residual": float(getattr(analysis, "residual", 0) or 0) if analysis else 0,
                "sigma": float(getattr(analysis, "sigma", 0) or 0) if analysis else 0,
                "hawkes": float(getattr(analysis, "hawkes", 0) or 0) if analysis else 0,
                "hmm": (self.telemetry.get("hmm") or {}),
                "edges": [e for e in (self.telemetry.get("graph") or []) if e.get("from") == sym or e.get("to") == sym],
            },
        }

    def search_local(self, query: str) -> list[dict[str, Any]]:
        q = query.strip().lower().replace("/", "").replace("-", "")
        hits: list[dict[str, Any]] = []
        on_desk = {a.symbol.upper() for a in self.assets}

        def consider(symbol: str, cid: str, name: str, keywords: list[str], yahoo: str = "") -> None:
            blob = " ".join([symbol, cid, name, *keywords]).lower().replace("/", "")
            if q and not (q == symbol.lower() or symbol.lower().startswith(q) or q in blob):
                return
            hits.append(
                {
                    "symbol": symbol,
                    "id": cid,
                    "name": name,
                    "on_desk": symbol.upper() in on_desk,
                    "yahoo": yahoo,
                }
            )

        for a in self.assets:
            consider(a.symbol, a.id, a.id.replace("-", " "), a.keywords, a.yahoo)
        for row in CATALOG:
            if row["symbol"] in on_desk:
                continue
            consider(row["symbol"], row["id"], row["name"], row["keywords"], row.get("yahoo") or "")
        if not q:
            return hits[:12]
        hits.sort(key=lambda h: (0 if h["symbol"].lower() == q else 1, 0 if h["on_desk"] else 1, h["symbol"]))
        # unique by symbol
        seen: set[str] = set()
        uniq = []
        for h in hits:
            if h["symbol"] in seen:
                continue
            seen.add(h["symbol"])
            uniq.append(h)
        return uniq[:12]

    def add_asset(self, gecko_id: str, symbol: str, name: str = "", yahoo: str = "") -> str:
        sym = symbol.upper().strip().replace("/", "")
        gecko_id = (gecko_id or sym.lower()).strip()
        yahoo = yahoo.strip()
        cat = next((c for c in CATALOG if c["symbol"] == sym or c["id"] == gecko_id), None)
        if cat:
            yahoo = yahoo or cat.get("yahoo") or ""
            name = name or cat.get("name") or ""
            gecko_id = cat["id"]
        if not sym:
            return "missing"
        if any(a.symbol == sym for a in self.assets):
            return "exists"
        keywords = [sym.lower(), gecko_id.replace("-", " ")]
        if name:
            keywords.append(name.lower())
        if cat:
            keywords.extend(cat.get("keywords") or [])
        asset = Asset(
            id=gecko_id,
            symbol=sym,
            binance="" if yahoo else f"{sym}USDT",
            keywords=list(dict.fromkeys(keywords)),
            yahoo=yahoo,
        )
        self.assets.append(asset)
        self.hub.assets.append(asset)
        self.hub.by_symbol[asset.symbol] = asset
        if asset.binance:
            self.hub.by_binance[asset.binance] = asset
        extra = (
            layer1.spawn_for_symbol(asset)
            + layer2.spawn_agents([asset])
            + layer3.spawn_for_symbol(asset)
            + layer4.spawn_agents([asset])
        )
        self.agents.extend(extra)
        self._note("watchlist", f"added {sym} ({gecko_id})")
        return "added"

    async def search_tickers(self, query: str) -> list[dict[str, Any]]:
        local = self.search_local(query)
        seen = {h["symbol"] for h in local}
        remote: list[dict[str, Any]] = []
        if len(query.strip()) >= 1:
            try:
                remote = await self.hub.search_coins(query)
            except Exception:
                remote = []
        for row in remote:
            if row["symbol"] in seen:
                continue
            remote_hit = {**row, "on_desk": False}
            local.append(remote_hit)
            seen.add(row["symbol"])
        return local[:12]

    async def blotter_brief(self, symbol: str) -> str | None:
        detail = self.symbol_detail(symbol)
        if not detail:
            return None
        text = await self.llm.blotter_brief(symbol.upper(), detail)
        if text:
            self._note("llm", f"brief {symbol.upper()}")
        return text

    def snapshot_plain(self) -> dict[str, Any]:
        return self.client_state()

    async def broadcast(self) -> None:
        payload = self.client_state()
        dead: list[asyncio.Queue] = []
        for q in self.listeners:
            try:
                if q.full():
                    _ = q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            if q in self.listeners:
                self.listeners.remove(q)

    def _expire_memos(self) -> None:
        now = utc_now()
        min_c = float(self.cfg.get("min_confluence") or 22)
        stand = {a.symbol for a in self.assets if a.yahoo and not a.binance}
        for m in self.memos:
            if m.status != "pending":
                continue
            if now - m.ts > 8 * 60:
                m.status = "expired"
                continue
            ch = next((c for c in self.challenges if c.symbol == m.symbol), None)
            rep = next((r for r in self.analyses if r.symbol == m.symbol), None)
            if ch and ch.veto:
                m.status = "expired"
                continue
            if not rep:
                continue
            sig = signal.alpha_score(rep)
            if (m.side == "long" and sig < 0) or (m.side == "short" and sig > 0):
                m.status = "expired"
                continue
            # Mirror L4/L5 floors so gold memos don't expire on crypto residual thresholds.
            if m.symbol == "BTC":
                floor = min_c
            elif m.symbol in stand or getattr(rep, "standalone", False):
                floor = max(14.0, min_c * 0.65)
            else:
                floor = signal.residual_floor(self.cfg)
            if abs(sig) < floor * 0.45:
                m.status = "expired"

    def _record_history(self) -> None:
        for a in self.assets:
            rep = next((r for r in self.analyses if r.symbol == a.symbol), None)
            if not rep:
                continue
            facs: dict[str, float | None] = {}
            for name in CORE:
                hit = next((f for f in self.factors if f.symbol == a.symbol and f.factor == name), None)
                if not hit or getattr(hit, "unknown", False):
                    facs[name] = None
                else:
                    facs[name] = round(float(hit.score), 2)
            self.history[a.symbol].append(
                {
                    "tick": self.tick,
                    "blend": round(rep.blended, 2),
                    "residual": round(float(getattr(rep, "residual", 0) or 0), 2),
                    "beta": round(float(getattr(rep, "beta", 0) or 0), 3),
                    "beta_ok": bool(getattr(rep, "beta_ok", False) or a.symbol == "BTC"),
                    "trust": round(rep.trust, 3),
                    "mark": self.paper.marks.get(a.symbol),
                    "factors": facs,
                    "ts": utc_now(),
                }
            )
            self.history[a.symbol] = self.history[a.symbol][-self.history_rows :]

    def _refresh_ic(self) -> None:
        self.ics = factor_ics(self.history, horizon_sec=180)
        series = recent_factor_series(self.history)
        self.ic_weights = blend_weights(self.ics, factor_series=series)
        self.mix_ic = mix_ic(self.ics, self.ic_weights)

    def _in_play(self) -> list[str]:
        floor = float(self.cfg.get("llm_floor") or 14)
        watch = {a.symbol for a in self.assets}
        play: list[str] = []
        focus = (self.focus_symbol or "").upper()
        if focus and focus in watch:
            play.append(focus)
        for r in self.analyses:
            if r.symbol not in watch or r.symbol in play:
                continue
            if abs(r.blended) >= floor or abs(signal.alpha_score(r)) >= signal.residual_floor(self.cfg):
                play.append(r.symbol)
        self.in_play = play[:8]
        return self.in_play

    def _promote_names(self) -> list[str]:
        watch = {a.symbol for a in self.assets}
        return [r.symbol for r in self.analyses if r.symbol in watch and signal.promote_ok(r, self.cfg)]

    async def _feature_pass_locked(self) -> dict[str, Any]:
        self.clock = "feature"
        self.tick += 1
        snap = await self.hub.refresh(self.tick, self.focus_symbol)
        self.sources_ok = snap.get("sources_ok") or {}
        self.paper.mark(snap.get("marks") or {})
        risk.ensure_stops(
            self.paper,
            stop_pct=float(self.cfg.get("stop_pct") or 0.02),
            history=self.history,
        )
        stop_notes = risk.apply_stops(self.paper)
        for note in stop_notes:
            self._note("stop", note)
        loss_cap = float(self.cfg.get("max_daily_loss_pct") or 0.02)
        self.paper.halted = risk.halted(self.paper, loss_cap)
        self._expire_memos()
        await self.embed.tag_news(snap.get("news") or [], self.assets, use_embed=False)
        await self.embed.tag_news(snap.get("reddit") or [], self.assets, use_embed=False)

        self.factors = layer1.research(snap, self.assets, self.sectors, self.agents)
        await self.bus.publish(
            "l1",
            {"from_layer": 1, "to_layer": 2, "count": len(self.factors), "label": "factor research"},
        )
        await self.broadcast()

        self.books = layer2.verify(self.factors, snap, self.assets, self.agents, self.ic_weights)
        await self.bus.publish(
            "l2",
            {
                "from_layer": 2,
                "to_layer": 3,
                "count": len(self.books),
                "label": "source verification",
                "garbage": sum(1 for b in self.books if b.garbage),
            },
        )
        await self.broadcast()

        self.analyses = layer3.synthesize(
            self.books, snap, self.assets, self.sectors, self.agents, self.ic_weights
        )
        prev_hmm = (self.telemetry.get("hmm") or {}).get("state")
        self.telemetry = signal.annotate(
            self.analyses,
            self.history,
            self.factors,
            self.books,
            {a.symbol for a in self.assets},
            prev_hmm=prev_hmm,
            standalone={a.symbol for a in self.assets if a.yahoo and not a.binance},
        )
        hmm = (self.telemetry.get("hmm") or {}).get("state") or "unknown"
        high_beta = set(self.sectors.get("high_beta") or [])
        standalone = {a.symbol for a in self.assets if a.yahoo and not a.binance}
        for note in risk.panic_cut(self.paper, hmm, high_beta, standalone=standalone):
            self._note("panic", note)
        self.paper.halted = risk.halted(self.paper, float(self.cfg.get("max_daily_loss_pct") or 0.02))
        regime_rep = next((r for r in self.analyses if r.symbol == "REGIME"), None)
        self.regime = f"{regime_rep.regime} · {hmm}" if regime_rep else hmm
        await self.bus.publish(
            "l3",
            {"from_layer": 3, "to_layer": 4, "count": len(self.analyses), "label": "synthesis", "regime": self.regime},
        )
        await self.broadcast()

        self.challenges = layer4.challenge(self.analyses, self.books, snap, self.assets, self.agents, self.cfg)
        await self.bus.publish(
            "l4",
            {
                "from_layer": 4,
                "to_layer": 5,
                "count": len(self.challenges),
                "label": "challenge",
                "vetoes": sum(1 for c in self.challenges if c.veto),
            },
        )
        self._record_history()
        self._refresh_ic()
        news_w = float(self.ic_weights.get("news") or 0.1)
        self._skill = skill_map(
            self.history,
            signal.residual_floor(self.cfg),
            float(self.cfg.get("skill_horizon_sec") or 480),
        )
        hmm = (self.telemetry.get("hmm") or {}).get("state")
        cards: dict[str, dict[str, Any]] = {}
        ch_map = {c.symbol: c for c in self.challenges}
        book_map = {b.symbol: b for b in self.books}
        for asset in self.assets:
            rep = next((r for r in self.analyses if r.symbol == asset.symbol), None)
            ch = ch_map.get(asset.symbol)
            book = book_map.get(asset.symbol)
            if rep and ch and book:
                cards[asset.symbol] = layer5.promotion_checks(
                    rep, ch, book, self.cfg, self.mix_ic, news_w, self._skill.get(asset.symbol), hmm
                )
        self.checklists = cards
        self._expire_memos()
        funnel = self._funnel()
        self._note("feature", f"t{self.tick} L1 {funnel['factors']} · verified {funnel['verified']} · veto {funnel['veto']}")
        self.persist()
        self._snap = snap
        return snap

    async def _decision_pass_locked(self, snap: dict[str, Any] | None = None) -> None:
        self.clock = "decision"
        self.decision_tick += 1
        snap = snap or getattr(self, "_snap", None) or {
            "marks": dict(self.paper.marks),
            "tickers": {},
            "sources_ok": self.sources_ok,
        }
        play = self._in_play()
        rounds = max(1, min(2, int(self.cfg.get("debate_rounds") or 2)))
        research_used, debate = await layer_llm.run_research_committee(
            self.llm,
            self.factors,
            self.books,
            self.analyses,
            self.challenges,
            dict(self.paper.marks),
            self.agents,
            rounds=rounds,
            focus_symbol=self.focus_symbol,
            min_confluence=float(self.cfg.get("min_confluence") or 16),
            in_play=play,
        )
        self.debate = (self.debate + debate)[-48:]
        for turn in debate[-8:]:
            await self.bus.publish(
                "talk",
                {
                    "from_layer": turn.get("from_layer") or 0,
                    "to_layer": turn.get("to_layer") or 0,
                    "count": 1,
                    "label": f"L{turn.get('from_layer')}→L{turn.get('to_layer')} {turn.get('symbol')}",
                },
            )

        prior = {c.symbol: c for c in self.challenges}
        fresh = layer4.challenge(self.analyses, self.books, snap, self.assets, self.agents, self.cfg)
        for c in fresh:
            old = prior.get(c.symbol)
            if not old:
                continue
            c.attacks = list(dict.fromkeys(c.attacks + old.attacks))[:6]
            if not c.veto:
                c.veto = old.veto
                c.conviction_adj = min(c.conviction_adj, old.conviction_adj)
                c.surviving_thesis = old.surviving_thesis or c.surviving_thesis
        self.challenges = fresh
        regime_rep = next((r for r in self.analyses if r.symbol == "REGIME"), None)
        if regime_rep:
            hmm = (self.telemetry.get("hmm") or {}).get("state") or "unknown"
            self.regime = f"{regime_rep.regime} · {hmm}"

        self.committee_ok = bool(research_used.get(2) and research_used.get(4))
        if not self.committee_ok:
            self._note("committee", "L5 blocked — L2 or L4 did not finish")
        new_memos, checklists = layer5.recommend(
            self.analyses,
            self.challenges,
            self.books,
            snap,
            self.assets,
            self.agents,
            self.cfg,
            self.paper.equity,
            self.memos,
            committee_ok=self.committee_ok,
            mix_ic=self.mix_ic,
            ic_weights=self.ic_weights,
            halted=self.paper.halted,
            skill_by_symbol=self._skill,
            hmm=(self.telemetry.get("hmm") or {}).get("state"),
        )
        self.checklists = checklists
        self.memos.extend(new_memos)
        await self.bus.publish(
            "l5",
            {"from_layer": 5, "to_layer": 0, "count": len(new_memos), "label": "decision memos"},
        )
        l5_ok = False
        if self.committee_ok:
            l5_ok = await layer_llm.run_l5(
                self.llm,
                new_memos,
                self.analyses,
                self.challenges,
                self.agents,
                self.debate,
            )
        else:
            layer_llm._mark(self.agents, 5, False, "L5 blocked: waiting on L2/L4")
        self.llm_layers = {**research_used, 5: l5_ok}
        names = ",".join(
            f"L{k}:{self.llm.model_for(k).split(':')[0]}" for k, v in self.llm_layers.items() if v
        ) or "none"
        self._note("llm-committee", names)
        funnel = self._funnel()
        self._note(
            "decision-clock",
            f"d{self.decision_tick} play {','.join(play) or '—'} · veto {funnel['veto']} · memos +{len(new_memos)}",
        )
        self.persist()
        self.clock = "idle"

    async def cycle(self) -> DeskSnapshot:
        async with self._lock:
            snap = await self._feature_pass_locked()
            await self._decision_pass_locked(snap)
            self._last_play = set(self._in_play())
            self._last_promote = set(self._promote_names())
            state = self.snapshot()
        await self.broadcast()
        return state

    def persist(self) -> None:
        try:
            save_desk(
                self.paper,
                self.memos,
                self.tick,
                {k: v[-self.history_rows :] for k, v in self.history.items()},
                history_rows=self.history_rows,
            )
        except Exception:
            pass

    def set_focus(self, symbol: str) -> str:
        sym = (symbol or "").upper().strip().replace("/", "").replace("-", "")
        if not sym:
            self.focus_symbol = None
            return ""
        if any(a.symbol == sym for a in self.assets):
            self.focus_symbol = sym
        else:
            self.focus_symbol = sym
        return self.focus_symbol or ""

    async def decide(self, memo_id: str, approve: bool) -> str:
        async with self._lock:
            memo = self.memo_by_id(memo_id)
            if not memo:
                return "missing"
            if approve:
                self.paper.halted = risk.halted(self.paper, float(self.cfg.get("max_daily_loss_pct") or 0.02))
                msg = self.paper.approve(memo)
            else:
                msg = self.paper.reject(memo)
            self._note("decision", f"{memo.symbol} {memo.side} {msg}")
            self.persist()
        await self.broadcast()
        return msg

    async def close_position(self, symbol: str) -> str:
        async with self._lock:
            msg = self.paper.close(symbol.upper())
            self._note("close", f"{symbol.upper()} {msg}")
            self.persist()
        await self.broadcast()
        return msg

    async def add_ticker(self, gecko_id: str, symbol: str, name: str = "", yahoo: str = "") -> str:
        async with self._lock:
            return self.add_asset(gecko_id, symbol, name, yahoo)

    async def loop(self) -> None:
        await self.llm.probe()
        await self.embed.probe()
        await self.llm.warmup()
        feature_delay = float(self.cfg.get("feature_seconds") or 5)
        decision_delay = float(self.cfg.get("tick_seconds") or 40)
        last_decision = 0.0
        while True:
            try:
                async with self._lock:
                    await self._feature_pass_locked()
                    play = list(self._in_play())
                    now = time.monotonic()
                    promote = self._promote_names()
                    new_promote = [s for s in promote if s not in self._last_promote]
                    due = last_decision <= 0 or (now - last_decision) >= decision_delay or bool(new_promote)
                await self.broadcast()
                if due:
                    async with self._lock:
                        await self._decision_pass_locked()
                        last_decision = time.monotonic()
                        self._last_play = set(play)
                        self._last_promote = set(promote)
                    await self.broadcast()
            except Exception as exc:
                await self.bus.publish("error", {"from_layer": 0, "to_layer": 0, "label": str(exc)})
                self._note("error", str(exc))
            await asyncio.sleep(feature_delay)
