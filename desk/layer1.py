from __future__ import annotations

from typing import Any

from desk.models import AgentState, Asset, FactorScore
from desk import newsdesk
from desk.scoring import (
    clamp,
    dominance_score,
    fear_greed_score,
    flow_score,
    funding_score,
    headline_sentiment,
    liquidity_score,
    macro_score,
    match_keywords,
    mempool_score,
    momentum_score,
    realized_vol,
    rsi_like,
    stablecoin_score,
    structure_score,
    utc_now,
    volatility_score,
    volume_score,
    whale_score,
)

SYMBOL_FACTORS = [
    "momentum",
    "volume",
    "volatility",
    "derivatives",
    "liquidity",
    "news",
    "social",
    "whales",
    "flows",
    "structure",
    "policy",
]

GLOBAL_FACTORS = [
    "macro_dxy",
    "macro_vix",
    "macro_yields",
    "macro_spx",
    "fear_greed",
    "btc_dominance",
    "mempool",
    "stablecoins",
    "world_news",
    "btc_beta_regime",
    "macro_calendar",
    "macro_nowcast",
]

COLOR = "#5eead4"


def spawn_agents(assets: list[Asset], sectors: dict[str, list[str]]) -> list[AgentState]:
    agents: list[AgentState] = []
    for a in assets:
        for fac in SYMBOL_FACTORS:
            agents.append(
                AgentState(
                    id=f"l1-{a.symbol}-{fac}",
                    name=f"{a.symbol} {fac}",
                    layer=1,
                    role="factor-researcher",
                    factor=fac,
                    symbol=a.symbol,
                    color=COLOR,
                )
            )
        agents.extend(newsdesk.spawn_desks(a.symbol))
    for fac in GLOBAL_FACTORS:
        agents.append(
            AgentState(
                id=f"l1-GLOBAL-{fac}",
                name=f"global {fac}",
                layer=1,
                role="factor-researcher",
                factor=fac,
                symbol=None,
                color=COLOR,
            )
        )
    for name in sectors:
        agents.append(
            AgentState(
                id=f"l1-SEC-{name}",
                name=f"sector {name}",
                layer=1,
                role="factor-researcher",
                factor="sector",
                symbol=name.upper(),
                color=COLOR,
            )
        )
    return agents


def spawn_for_symbol(asset: Asset) -> list[AgentState]:
    return [
        AgentState(
            id=f"l1-{asset.symbol}-{fac}",
            name=f"{asset.symbol} {fac}",
            layer=1,
            role="factor-researcher",
            factor=fac,
            symbol=asset.symbol,
            color=COLOR,
        )
        for fac in SYMBOL_FACTORS
    ] + newsdesk.spawn_desks(asset.symbol)


def _beat(agent: AgentState, score: FactorScore) -> FactorScore:
    agent.status = "researching"
    agent.last_score = score.score
    agent.last_note = score.note
    agent.last_beat = score.ts
    return score


def _text_score(items: list[dict[str, Any]], keywords: list[str] | None) -> tuple[float, list[str], list[str], float]:
    hits = 0
    acc = 0.0
    evidence: list[str] = []
    sources: list[str] = []
    for it in items:
        title = str(it.get("title") or "")
        if keywords and not match_keywords(title, keywords):
            continue
        hits += 1
        s, tags = headline_sentiment(title)
        acc += s
        if tags:
            evidence.append(f"{title[:90]} ({', '.join(tags[:3])})")
        if it.get("link"):
            sources.append(str(it["link"]))
    if not hits:
        return 0.0, ["unknown — no matching headlines"], [], 0.12
    return acc / hits, evidence[:5], sources[:5], min(0.9, 0.25 + hits * 0.08)


def research(snap: dict[str, Any], assets: list[Asset], sectors: dict[str, list[str]], agents: list[AgentState]) -> list[FactorScore]:
    now = utc_now()
    by_id = {a.id: a for a in agents if a.layer == 1}
    out: list[FactorScore] = []
    tickers = snap.get("tickers") or {}
    gecko = snap.get("gecko") or {}
    funding = snap.get("funding") or {}
    klines = snap.get("klines") or {}
    depth = snap.get("depth") or {}
    whales = snap.get("whales") or {}
    news = snap.get("news") or []
    reddit = snap.get("reddit") or []
    glob = snap.get("global") or {}
    macro = snap.get("macro") or {}
    cal = snap.get("calendar") or {}
    ok = snap.get("sources_ok") or {}

    btc_chg = (tickers.get("BTC") or {}).get("change_24h") or (gecko.get("BTC") or {}).get("change_24h") or 0.0

    def emit(
        agent_id: str,
        factor: str,
        symbol: str | None,
        score: float,
        conf: float,
        note: str,
        evidence: list[str],
        sources: list[str],
        unknown: bool = False,
    ) -> None:
        agent = by_id.get(agent_id)
        packet = FactorScore(
            agent_id=agent_id,
            layer=1,
            factor=factor,
            symbol=symbol,
            score=0.0 if unknown else clamp(score),
            confidence=max(0.0, min(1.0, conf)),
            note=note,
            evidence=evidence,
            sources=sources,
            ts=now,
            unknown=unknown,
        )
        if agent:
            _beat(agent, packet)
        out.append(packet)

    for a in assets:
        t = tickers.get(a.symbol) or {}
        g = gecko.get(a.symbol) or {}
        kl = klines.get(a.symbol) or {}
        closes = kl.get("closes") or []
        vols = kl.get("volumes") or []
        chg = float(t.get("change_24h") or g.get("change_24h") or 0)
        chg1h = g.get("change_1h")
        if chg1h is not None:
            chg1h = float(chg1h)
        rsi = rsi_like(closes) if len(closes) >= 15 else None
        px = float(t.get("price") or g.get("price") or 0)

        s, note = momentum_score(chg, chg1h, rsi)
        if not t and not g:
            emit(
                f"l1-{a.symbol}-momentum",
                "momentum",
                a.symbol,
                0.0,
                0.12,
                "unknown — no price tape",
                ["no ticker / gecko row"],
                ["no price feed"],
                unknown=True,
            )
        else:
            emit(
                f"l1-{a.symbol}-momentum",
                "momentum",
                a.symbol,
                s,
                0.72 if rsi is not None else 0.5,
                note,
                [f"last {px}" if px else "price from ticker/gecko"],
                [t.get("source") or g.get("source") or "binance/coingecko"],
            )

        rvol = 1.0
        raw_rvol = 1.0
        if vols and len(vols) > 6:
            mean_v = sum(vols[:-1]) / max(len(vols) - 1, 1)
            raw_rvol = vols[-1] / mean_v if mean_v else 1.0
            rvol = min(raw_rvol, 3.5)
        if not vols or len(vols) <= 6:
            emit(
                f"l1-{a.symbol}-volume",
                "volume",
                a.symbol,
                0.0,
                0.12,
                "unknown — no volume tape (klines)",
                ["no kline volumes for this name"],
                [t.get("source") or "no volume feed"],
                unknown=True,
            )
        else:
            s, note = volume_score(rvol, chg)
            if raw_rvol > 3.5:
                note += f" (raw {raw_rvol:.1f}x capped)"
            emit(
                f"l1-{a.symbol}-volume",
                "volume",
                a.symbol,
                s,
                0.65,
                note,
                [f"quote vol ${float(t.get('quote_volume') or 0)/1e6:.1f}m"],
                [t.get("source") or "binance"],
            )

        vol = realized_vol(closes) if closes else 0.0
        atr = None
        if t.get("high") and t.get("low") and px:
            atr = (float(t["high"]) - float(t["low"])) / px * 100
        if vol <= 0 and atr:
            vol = atr * (365 ** 0.5)
        if vol <= 0 and not atr:
            emit(
                f"l1-{a.symbol}-volatility",
                "volatility",
                a.symbol,
                0.0,
                0.12,
                "unknown — no range tape",
                ["no klines and no 24h high/low"],
                [t.get("source") or "no vol feed"],
                unknown=True,
            )
        else:
            s, note = volatility_score(vol, chg, atr)
            if not closes and atr:
                note += " (from 24h range)"
            emit(
                f"l1-{a.symbol}-volatility",
                "volatility",
                a.symbol,
                s,
                0.7 if closes else 0.45,
                note,
                [f"24h range {atr:.2f}%" if atr else "range n/a"],
                [kl.get("source") or t.get("source") or "binance"],
            )

        fr = funding.get(a.symbol) or {}
        if not fr:
            emit(
                f"l1-{a.symbol}-derivatives",
                "derivatives",
                a.symbol,
                0.0,
                0.12,
                "unknown — no funding / futures print",
                ["no premium index for this name"],
                ["no futures feed"],
                unknown=True,
            )
        else:
            s, note = funding_score(float(fr.get("funding") or 0), None)
            emit(
                f"l1-{a.symbol}-derivatives",
                "derivatives",
                a.symbol,
                s,
                0.7,
                note,
                [f"mark {fr.get('mark')}" if fr.get("mark") else "premium index"],
                [fr.get("source") or "https://fapi.binance.com/fapi/v1/premiumIndex"],
            )

        dp = depth.get(a.symbol) or {}
        if not dp:
            emit(
                f"l1-{a.symbol}-liquidity",
                "liquidity",
                a.symbol,
                0.0,
                0.12,
                "unknown — no order book",
                ["depth not available for this name"],
                ["no depth feed"],
                unknown=True,
            )
        else:
            s, note = liquidity_score(dp.get("spread_bps"), dp.get("depth_usd"))
            emit(
                f"l1-{a.symbol}-liquidity",
                "liquidity",
                a.symbol,
                s,
                0.68,
                note,
                ["top-of-book snapshot"],
                [dp.get("source") or "https://api.binance.com/api/v3/depth"],
            )

        art_packets, art_meta = newsdesk.cover(news, a.keywords, a.symbol, by_id, "article", now)
        out.extend(art_packets)
        ns, nconf, nnote, nev, nsrc = newsdesk.blend_cover(art_meta, art_packets)
        emit(f"l1-{a.symbol}-news", "news", a.symbol, ns, nconf, nnote, nev, nsrc, unknown=not art_packets)

        soc_packets, soc_meta = newsdesk.cover(reddit, a.keywords, a.symbol, by_id, "social_post", now)
        out.extend(soc_packets)
        ss, sconf, snote, sev, ssrc = newsdesk.blend_cover(soc_meta, soc_packets)
        if snote.startswith("unknown"):
            snote = "unknown — no matching social"
        emit(f"l1-{a.symbol}-social", "social", a.symbol, ss, sconf, snote, sev, ssrc, unknown=not soc_packets)

        wh = whales.get(a.symbol) or {}
        if not wh:
            emit(
                f"l1-{a.symbol}-whales",
                "whales",
                a.symbol,
                0.0,
                0.12,
                "unknown — no large-print tape",
                ["aggTrades not available for this name"],
                ["no trades feed"],
                unknown=True,
            )
        else:
            s, note = whale_score(float(wh.get("buy") or 0), float(wh.get("sell") or 0))
            emit(
                f"l1-{a.symbol}-whales",
                "whales",
                a.symbol,
                s,
                0.6,
                note,
                ["aggTrades notional > $8k"],
                [wh.get("source") or "https://api.binance.com/api/v3/aggTrades"],
            )

        flow_vol = float(t.get("quote_volume") or g.get("volume") or 0)
        if not flow_vol and not g.get("mcap"):
            emit(
                f"l1-{a.symbol}-flows",
                "flows",
                a.symbol,
                0.0,
                0.12,
                "unknown — no turnover tape",
                ["no quote volume or market cap"],
                [t.get("source") or "no flow feed"],
                unknown=True,
            )
        else:
            s, note = flow_score(flow_vol, g.get("mcap"), chg)
            emit(
                f"l1-{a.symbol}-flows",
                "flows",
                a.symbol,
                s,
                0.62 if g or t else 0.2,
                note,
                [f"mcap ${float(g.get('mcap') or 0)/1e9:.2f}b" if g.get("mcap") else "mcap n/a"],
                [g.get("source") or t.get("source") or "coingecko"],
            )

        s, note = structure_score(float(t.get("high") or 0), float(t.get("low") or 0), px, float(t.get("open") or 0) or None)
        range_ok = bool(t.get("range_ok")) or (
            float(t.get("high") or 0) > float(t.get("low") or 0)
            and abs(float(t.get("high") or 0) - float(t.get("low") or 0)) / max(px, 1e-9) > 0.0005
        )
        if not t or not px or not range_ok:
            emit(
                f"l1-{a.symbol}-structure",
                "structure",
                a.symbol,
                0.0,
                0.12,
                "unknown — no real high/low range",
                ["synthetic or missing OHLC"],
                [t.get("source") or "no structure feed"],
                unknown=True,
            )
        else:
            emit(
                f"l1-{a.symbol}-structure",
                "structure",
                a.symbol,
                s,
                0.6,
                note,
                [f"H {t.get('high')} L {t.get('low')}"],
                [t.get("source") or "binance"],
            )

        gold_nm = a.symbol == "XAUUSD" or "gold" in " ".join(a.keywords or []).lower()
        pol = float((cal.get("gold_score") if gold_nm else cal.get("crypto_score")) or 0)
        pol_notes = list(cal.get("notes") or [])
        if cal.get("event_risk"):
            pol *= 0.4
            pol_notes = ["high-impact print in the window — lean cut"] + pol_notes
        if not (cal.get("events") or cal.get("nowcasts")):
            emit(
                f"l1-{a.symbol}-policy",
                "policy",
                a.symbol,
                0.0,
                0.12,
                "unknown — economic calendar dark",
                ["no claims / NFP / FOMC tape"],
                ["forex factory / FRED"],
                unknown=True,
            )
        else:
            scored = any(abs(float(e.get("score") or 0)) > 0.5 for e in (cal.get("events") or []))
            emit(
                f"l1-{a.symbol}-policy",
                "policy",
                a.symbol,
                pol,
                0.42 if scored else 0.22,
                (pol_notes[0] if pol_notes else "calendar scored")[:160],
                pol_notes[:4] or ["FX calendar"],
                [cal.get("source") or "https://nfs.faireconomy.media/ff_calendar_thisweek.json"],
                unknown=not scored and abs(pol) < 1e-9,
            )

    dxy = (macro.get("dxy") or {}) if isinstance(macro.get("dxy"), dict) else {}
    vix = (macro.get("vix") or {}) if isinstance(macro.get("vix"), dict) else {}
    tnx = (macro.get("tnx") or {}) if isinstance(macro.get("tnx"), dict) else {}
    spx = (macro.get("spx") or {}) if isinstance(macro.get("spx"), dict) else {}
    dxy_chg = dxy.get("change_pct")
    vix_px = vix.get("price")
    tnx_px = tnx.get("price")
    spx_chg = spx.get("change_pct")
    ms, mnote, _regime = macro_score(dxy_chg, vix_px, tnx_px, spx_chg)
    src_yahoo = [macro.get("source") or "yahoo"]
    if dxy_chg is None:
        emit("l1-GLOBAL-macro_dxy", "macro_dxy", None, 0.0, 0.12, "DXY n/a", [mnote], src_yahoo, unknown=True)
    else:
        emit("l1-GLOBAL-macro_dxy", "macro_dxy", None, clamp(-dxy_chg * 8), 0.7, f"DXY {dxy_chg:+.2f}%", [mnote], src_yahoo)
    if vix_px is None:
        emit("l1-GLOBAL-macro_vix", "macro_vix", None, 0.0, 0.12, "VIX n/a", [mnote], src_yahoo, unknown=True)
    else:
        emit("l1-GLOBAL-macro_vix", "macro_vix", None, clamp((14 - vix_px) * 3), 0.7, f"VIX {vix_px:.1f}", [mnote], src_yahoo)
    if tnx_px is None:
        emit("l1-GLOBAL-macro_yields", "macro_yields", None, 0.0, 0.12, "10Y n/a", [mnote], src_yahoo, unknown=True)
    else:
        emit("l1-GLOBAL-macro_yields", "macro_yields", None, clamp((4.2 - tnx_px) * 18), 0.65, f"10Y {tnx_px:.2f}%", [mnote], src_yahoo)
    if spx_chg is None:
        emit("l1-GLOBAL-macro_spx", "macro_spx", None, 0.0, 0.12, "SPX n/a", [mnote], src_yahoo, unknown=True)
    else:
        emit("l1-GLOBAL-macro_spx", "macro_spx", None, clamp(spx_chg * 6), 0.7, f"SPX {spx_chg:+.2f}%", [mnote], src_yahoo)

    fg = snap.get("fear_greed")
    if fg is not None:
        s, note = fear_greed_score(int(fg))
        emit("l1-GLOBAL-fear_greed", "fear_greed", None, s, 0.8, note, [note], ["https://api.alternative.me/fng/"])
    else:
        emit("l1-GLOBAL-fear_greed", "fear_greed", None, 0, 0.12, "fear/greed n/a", [], ["https://api.alternative.me/fng/"], unknown=True)

    btc_dom = float(glob.get("btc_dominance") or 0)
    if not btc_dom:
        emit("l1-GLOBAL-btc_dominance", "btc_dominance", None, 0.0, 0.12, "dominance n/a", [], [glob.get("source") or "coingecko global"], unknown=True)
    else:
        s, note = dominance_score(btc_dom, None, "BTC")
        emit("l1-GLOBAL-btc_dominance", "btc_dominance", None, s, 0.7, note, [note], [glob.get("source") or "coingecko global"])

    fees = snap.get("mempool") or {}
    fast = fees.get("fastestFee") or fees.get("hourFee")
    if fast is None:
        emit("l1-GLOBAL-mempool", "mempool", None, 0.0, 0.12, "mempool n/a", [], [fees.get("source") or "mempool.space"], unknown=True)
    else:
        s, note = mempool_score(float(fast))
        emit("l1-GLOBAL-mempool", "mempool", None, s, 0.6, note, [note], [fees.get("source") or "https://mempool.space/api/v1/fees/recommended"])

    if not glob:
        emit("l1-GLOBAL-stablecoins", "stablecoins", None, 0.0, 0.12, "stablecoin tape n/a", [], ["coingecko"], unknown=True)
    else:
        s, note = stablecoin_score(glob.get("total_volume"), glob.get("mcap_change"))
        emit("l1-GLOBAL-stablecoins", "stablecoins", None, s, 0.55, note, [note], [glob.get("source") or "coingecko"])

    ws, ev, srcs, conf = _text_score(news, None)
    emit("l1-GLOBAL-world_news", "world_news", None, ws, min(conf, 0.75), f"world headline {ws:+.0f}", ev, srcs)

    beta_note = f"BTC 24h {float(btc_chg):+.2f}%"
    emit("l1-GLOBAL-btc_beta_regime", "btc_beta_regime", None, clamp(float(btc_chg) * 3), 0.6 if ok.get("binance") else 0.25, beta_note, [beta_note], ["binance 24hr"])

    cal_src = [cal.get("source") or "https://nfs.faireconomy.media/ff_calendar_thisweek.json"]
    nxt = cal.get("next") or {}
    cal_note = (cal.get("notes") or ["calendar n/a"])[0]
    emit(
        "l1-GLOBAL-macro_calendar",
        "macro_calendar",
        None,
        float(cal.get("gold_score") or 0),
        0.5 if cal.get("events") else 0.12,
        cal_note[:160],
        [f"{e.get('country')} {e.get('title')} {e.get('forecast') or ''}" for e in (cal.get("events") or [])[:6]],
        cal_src,
        unknown=not cal.get("events"),
    )
    nowcast_bits = [v.get("note") for v in (cal.get("nowcasts") or {}).values() if v.get("note")]
    emit(
        "l1-GLOBAL-macro_nowcast",
        "macro_nowcast",
        None,
        float(cal.get("crypto_score") or 0),
        0.4 if nowcast_bits else 0.12,
        (nowcast_bits[0] if nowcast_bits else "no desk nowcast")[:160],
        nowcast_bits[:5] or [f"next {nxt.get('title')}" if nxt else "no upcoming print"],
        cal_src + ["https://fred.stlouisfed.org"],
        unknown=not nowcast_bits,
    )

    for sec_name, members in sectors.items():
        chgs = []
        for sym in members:
            row = tickers.get(sym) or gecko.get(sym) or {}
            if row.get("change_24h") is not None:
                chgs.append(float(row["change_24h"]))
        avg = sum(chgs) / len(chgs) if chgs else 0.0
        emit(
            f"l1-SEC-{sec_name}",
            "sector",
            sec_name.upper(),
            clamp(avg * 4),
            0.55 if chgs else 0.2,
            f"{sec_name} avg 24h {avg:+.2f}% over {len(chgs)} names",
            [f"{sec_name}: {', '.join(members)}"],
            ["binance/coingecko basket"],
        )

    for agent in by_id.values():
        if agent.last_beat != now:
            agent.status = "idle"
        else:
            agent.status = "live"
    return out
