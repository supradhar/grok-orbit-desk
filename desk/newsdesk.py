from __future__ import annotations

import re
from typing import Any

from desk.models import AgentState, FactorScore
from desk.scoring import clamp, headline_sentiment, match_keywords, utc_now

ARTICLE_DESKS = 8
SOCIAL_DESKS = 3
COLOR_ARTICLE = "#99f6e4"

STOP = {
    "this", "that", "with", "from", "have", "will", "your", "about", "after", "over",
    "into", "just", "more", "than", "been", "were", "they", "them", "their", "what",
    "when", "where", "which", "while", "could", "would", "should", "crypto", "price",
    "market", "today", "week", "says", "after", "amid", "as", "for", "and", "the",
}


def spawn_desks(symbol: str) -> list[AgentState]:
    agents = []
    for i in range(ARTICLE_DESKS):
        agents.append(
            AgentState(
                id=f"l1-{symbol}-article-{i}",
                name=f"{symbol} article {i + 1}",
                layer=1,
                role="article-researcher",
                factor="article",
                symbol=symbol,
                color=COLOR_ARTICLE,
            )
        )
    for i in range(SOCIAL_DESKS):
        agents.append(
            AgentState(
                id=f"l1-{symbol}-social-{i}",
                name=f"{symbol} social {i + 1}",
                layer=1,
                role="social-researcher",
                factor="social_post",
                symbol=symbol,
                color=COLOR_ARTICLE,
            )
        )
    return agents


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) > 3 and w not in STOP}


def _cluster(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for it in items:
        toks = _tokens(str(it.get("title") or ""))
        if not toks:
            toks = {f"item{len(clusters)}"}
        placed = False
        for c in clusters:
            inter = len(toks & c["tokens"])
            denom = max(1, min(len(toks), len(c["tokens"])))
            if inter / denom >= 0.5:
                c["items"].append(it)
                c["tokens"] |= toks
                placed = True
                break
        if not placed:
            words = [w for w in re.findall(r"[a-z0-9]+", str(it.get("title") or "").lower()) if len(w) > 3 and w not in STOP]
            label = " ".join(words[:3]) or "story"
            clusters.append({"label": label, "tokens": toks, "items": [it]})
    return clusters


def research_item(item: dict[str, Any], keywords: list[str]) -> dict[str, Any]:
    title = str(item.get("title") or "")
    body = re.sub(r"<[^>]+>", " ", str(item.get("description") or item.get("summary") or ""))
    body = re.sub(r"\s+", " ", body).strip()
    blob = f"{title}. {body[:900]}"
    score, tags = headline_sentiment(blob)
    hits = match_keywords(blob, keywords) if keywords else True
    density = 0
    low = blob.lower()
    for kw in keywords or []:
        density += low.count(kw.lower())
    if density:
        score = clamp(score * (1.0 + min(0.4, 0.08 * density)))
    source = str(item.get("source") or item.get("link") or "")
    conf = 0.28
    if body:
        conf += min(0.28, len(body) / 1400)
    if hits:
        conf += 0.18
    if density:
        conf += min(0.16, density * 0.04)
    if any(
        s in source
        for s in (
            "coindesk",
            "cointelegraph",
            "reuters",
            "bloomberg",
            "kitco",
            "mining.com",
            "finance.yahoo",
            "yahoo.com",
        )
    ):
        conf += 0.08
    conf = max(0.12, min(0.92, conf))
    note = title[:140] if title else "untitled"
    evidence = [title[:160]]
    if body:
        evidence.append(body[:220])
    if tags:
        evidence.append("tags: " + ", ".join(tags[:6]))
    return {
        "score": clamp(score),
        "confidence": conf,
        "note": note,
        "evidence": evidence[:4],
        "source": item.get("link") or source,
        "title": title,
        "body": body[:400],
    }


def cover(
    items: list[dict[str, Any]],
    keywords: list[str],
    symbol: str,
    by_id: dict[str, AgentState],
    kind: str,
    now: float,
) -> tuple[list[FactorScore], dict[str, Any]]:
    """One agent per article. Same-story articles sit in a subgroup (cluster)."""
    n_desks = ARTICLE_DESKS if kind == "article" else SOCIAL_DESKS
    prefix = "article" if kind == "article" else "social"
    kws = list(dict.fromkeys([*(keywords or []), symbol, symbol.lower()]))
    # Short tickers (OP, UNI, SOL…) false-positive on English — require ticker tag or multi-token hit.
    short = {k.lower() for k in kws if len(str(k)) <= 3}
    matched: list[dict[str, Any]] = []
    seen: set[str] = set()
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        key = re.sub(r"\W+", "", title.lower())[:80]
        if key in seen:
            continue
        tagged = symbol in (it.get("tickers") or [])
        title_hit = match_keywords(title, kws)
        body_hit = match_keywords(str(it.get("description") or ""), kws)
        if kws and not (tagged or title_hit or body_hit):
            continue
        if not tagged and title_hit:
            hits = [k for k in kws if match_keywords(title, [k])]
            if hits and all(str(h).lower() in short for h in hits) and len(hits) < 2:
                # lone short-token match without ticker tag — skip
                continue
        seen.add(key)
        matched.append(it)
    matched.sort(key=lambda it: 0 if symbol in (it.get("tickers") or []) else 1)
    matched = matched[: max(n_desks * 2, 16)]
    packets: list[FactorScore] = []
    assignments: list[dict[str, Any]] = []
    if not matched:
        for i in range(n_desks):
            agent = by_id.get(f"l1-{symbol}-{prefix}-{i}")
            if agent:
                agent.status = "idle"
                agent.last_note = "standby — no matching story"
                agent.last_score = None
        return packets, {"n": 0, "clusters": 0, "split": False, "assignments": []}

    clusters = _cluster(matched)
    desk_i = 0
    cluster_scores: list[tuple[float, float]] = []
    for ci, cluster in enumerate(clusters):
        local: list[tuple[float, float]] = []
        for it in cluster["items"]:
            if desk_i >= n_desks:
                break
            dug = research_item(it, kws)
            agent_id = f"l1-{symbol}-{prefix}-{desk_i}"
            packet = FactorScore(
                agent_id=agent_id,
                layer=1,
                factor=kind,
                symbol=symbol,
                score=dug["score"],
                confidence=dug["confidence"],
                note=f"[{cluster['label']}] {dug['note']}",
                evidence=dug["evidence"] + [f"cluster:{cluster['label']}"],
                sources=[str(dug["source"])] if dug["source"] else [],
                ts=now or utc_now(),
            )
            agent = by_id.get(agent_id)
            if agent:
                agent.status = "live"
                agent.last_score = packet.score
                agent.last_note = packet.note[:160]
                agent.last_beat = packet.ts
            packets.append(packet)
            assignments.append(
                {
                    "agent": agent.name if agent else agent_id,
                    "cluster": cluster["label"],
                    "title": dug["title"][:140],
                    "score": round(dug["score"], 1),
                    "confidence": round(dug["confidence"], 2),
                }
            )
            local.append((dug["score"], dug["confidence"]))
            desk_i += 1
        if local:
            w = sum(c for _, c in local) or 1.0
            cluster_scores.append((sum(s * c for s, c in local) / w, w))

    for i in range(desk_i, n_desks):
        agent = by_id.get(f"l1-{symbol}-{prefix}-{i}")
        if agent:
            agent.status = "idle"
            agent.last_note = "standby — no leftover article"
            agent.last_score = None

    split = False
    if len(cluster_scores) >= 2:
        signs = [1 if s > 8 else -1 if s < -8 else 0 for s, _ in cluster_scores]
        if 1 in signs and -1 in signs:
            split = True
    return packets, {
        "n": len(packets),
        "clusters": len(clusters),
        "split": split,
        "assignments": assignments,
        "cluster_scores": [(round(s, 1), round(w, 2)) for s, w in cluster_scores],
    }


def blend_cover(cover_meta: dict[str, Any], packets: list[FactorScore]) -> tuple[float, float, str, list[str], list[str]]:
    if not packets:
        return 0.0, 0.12, "unknown — no matching headlines", ["unknown — no matching headlines"], []
    w = sum(max(p.confidence, 0.05) for p in packets) or 1.0
    score = sum(p.score * max(p.confidence, 0.05) for p in packets) / w
    conf = min(0.9, 0.28 + 0.08 * len(packets))
    if cover_meta.get("split"):
        conf *= 0.55
        note = f"{len(packets)} articles / {cover_meta.get('clusters')} stories — desks disagree on sign"
    else:
        note = f"{len(packets)} articles / {cover_meta.get('clusters')} stories, blend {score:+.0f}"
    evidence = [a["title"] for a in cover_meta.get("assignments") or []][:6]
    sources = [s for p in packets for s in p.sources][:6]
    return clamp(score), conf, note, evidence, sources
