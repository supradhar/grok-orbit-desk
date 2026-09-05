const canvas = document.getElementById("orbit");
const ctx = canvas.getContext("2d");
const memosEl = document.getElementById("memos");
const heatEl = document.getElementById("heat");
const bookEl = document.getElementById("book");
const journalEl = document.getElementById("journal");
const qualityEl = document.getElementById("quality");
const inspEl = document.getElementById("inspector");
const tipEl = document.getElementById("tip");
const feedsEl = document.getElementById("feeds");
const funnelEl = document.getElementById("funnel");
const tapeEl = document.getElementById("tape");
const actionNowEl = document.getElementById("action-now");

const LAYER_COLOR = { 1: "#5eead4", 2: "#7dd3fc", 3: "#c4b5fd", 4: "#f0abfc", 5: "#fbbf24" };
const RING = { 5: 58, 4: 108, 3: 162, 2: 218, 1: 278 };
const MAX_DRAW = { 1: 180, 2: 40, 3: 36, 4: 28, 5: 6 };
const FACTOR_LABEL = {
  momentum: "mom",
  volume: "vol",
  volatility: "σ",
  derivatives: "fund",
  liquidity: "liq",
  news: "news",
  social: "soc",
  whales: "whal",
  flows: "flow",
  structure: "str",
  policy: "pol",
};

let state = null;
let packets = [];
let seenPacket = 0;
let selected = null;
let memoFilter = "pending";
let briefCache = {};
let hits = [];
let t0 = performance.now();
let cssW = 900;
let cssH = 640;

function tickerBox() {
  return document.getElementById("ticker");
}

function normalizeSym(q) {
  return String(q || "")
    .trim()
    .toUpperCase()
    .replace("/", "")
    .replace("-", "");
}

function watchHas(sym) {
  return !!(sym && (state?.watchlist || []).some((a) => a.symbol.toUpperCase() === sym));
}

function persistSelected(sym) {
  selected = sym ? String(sym).toUpperCase() : null;
  if (!selected) return;
  try {
    localStorage.setItem("orbit-ticker", selected);
  } catch {
    /* ignore */
  }
  const hash = (location.hash || "").replace("#", "").toUpperCase();
  if (hash !== selected) history.replaceState(null, "", "#" + selected);
  fetch("/api/focus", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: selected }),
  }).catch(() => {});
  const box = tickerBox();
  if (!box) return;
  if (document.activeElement === box && normalizeSym(box.value) !== selected) return;
  if (normalizeSym(box.value) !== selected) box.value = selected;
}

function resolveSelected() {
  const box = tickerBox();
  const typed = normalizeSym(box?.value || "");
  if (typed && watchHas(typed)) return typed;
  if (box && document.activeElement === box && typed) return selected;
  const hashed = normalizeSym((location.hash || "").replace("#", ""));
  if (hashed && watchHas(hashed)) return hashed;
  let stored = "";
  try {
    stored = normalizeSym(localStorage.getItem("orbit-ticker") || "");
  } catch {
    stored = "";
  }
  if (stored && watchHas(stored)) return stored;
  if (selected && watchHas(selected)) return selected;
  return null;
}

function money(n, d = 0) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n < 0 ? "-" : "";
  return sign + "$" + Math.abs(n).toLocaleString(undefined, { maximumFractionDigits: d });
}

function rr(m) {
  const risk = Math.abs(m.entry - m.stop);
  const reward = Math.abs(m.target - m.entry);
  return risk ? (reward / risk).toFixed(2) : "—";
}

function fitCanvas() {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  cssW = Math.max(320, rect.width);
  cssH = Math.max(420, Math.min(rect.width * 0.82, window.innerHeight * 0.68));
  canvas.width = Math.floor(cssW * dpr);
  canvas.height = Math.floor(cssH * dpr);
  canvas.style.height = cssH + "px";
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
  return el;
}

function renderKpis(s) {
  setText("kpi-equity", money(s.equity));
  setText("kpi-cash", money(s.cash));
  const pnl = setText("kpi-pnl", money(s.pnl));
  if (pnl) pnl.style.color = (s.pnl || 0) >= 0 ? "#34d399" : "#f87171";
  setText("kpi-exp", ((s.exposure_pct || 0) * 100).toFixed(1) + "%");
  setText("kpi-regime", s.regime || "—");
  const focus = selected || s.focus;
  const row = (s.analyses || []).find((x) => x.symbol === focus);
  setText("kpi-idio", row && row.residual != null ? (row.residual >= 0 ? "+" : "") + Number(row.residual).toFixed(1) : "—");
  setText("kpi-beta", row && row.beta_ok && row.beta != null ? Number(row.beta).toFixed(2) : "—");
  const idioEl = document.getElementById("kpi-idio");
  if (idioEl && row) idioEl.style.color = Number(row.residual) >= 0 ? "#34d399" : "#f87171";
  const risk = s.risk || {};
  const riskEl = setText("kpi-risk", risk.halted ? "HALT" : ((risk.drawdown_pct || 0) * 100).toFixed(1) + "% dd");
  if (riskEl) riskEl.style.color = risk.halted ? "#f87171" : "";
  setText("kpi-tick", s.tick ?? "—");
}

function layerEntries(llm) {
  const layers = llm?.layers || {};
  const ran = llm?.ran || {};
  return Object.entries(layers).map(([k, v]) => {
    const did = ran[k] === true;
    const model = v && typeof v === "object" ? String(v.model || "").split(":")[0] : "";
    return { k, ok: did, model, assigned: !!(v && (v.ok || v.model)) };
  });
}

function renderFeeds(s) {
  if (!feedsEl) return;
  const src = s.sources_ok || {};
  const llm = s.llm || {};
  const layerPills = layerEntries(llm)
    .map((x) => `<span class="pill ${x.ok ? "up" : "down"}">L${x.k} ${x.model || (x.ok ? "llm" : "down")}</span>`)
    .join("");
  const llmPill = llm.ok
    ? layerPills || `<span class="pill up">llm ${llm.model || ""}</span>`
    : `<span class="pill down">llm ${llm.error || "offline"}</span>`;
  const haltPill = (s.risk || {}).halted ? '<span class="pill down">desk halt</span>' : "";
  feedsEl.innerHTML =
    haltPill +
    llmPill +
    (Object.keys(src).length
      ? Object.entries(src)
          .map(([k, v]) => `<span class="pill ${v ? "up" : "down"}">${k}${v ? "" : " down"}</span>`)
          .join("")
      : '<span class="pill">waiting on first cycle</span>');
}

function renderAction(s) {
  const act = s.action || {};
  if (actionNowEl) actionNowEl.textContent = act.now || "Waiting on a tick.";
  if (!tapeEl) return;
  const desks = act.desks || [];
  if (!desks.length) {
    tapeEl.innerHTML = selected
      ? "<li>No L1 desks reporting on this ticker yet — wait for the next research tick.</li>"
      : "";
    return;
  }
  tapeEl.innerHTML = desks
    .map((d) => {
      const sc = d.score == null ? "—" : Number(d.score).toFixed(0);
      return `<li class="${d.status || ""}"><strong>${d.name}</strong> <span>${d.factor}</span> ${sc} — ${d.note || ""}</li>`;
    })
    .join("");
}

function nextPrint(s) {
  const n = (s.calendar || s.funnel || {}).next || s.funnel?.next_print || {};
  if (n.title) return `${n.country || ""} ${n.title}`.trim();
  const ev = ((s.calendar || {}).events || [])[0];
  return ev ? `${ev.country || ""} ${ev.title}` : "—";
}

function calendarHtml(cal) {
  if (!cal || (!(cal.events || []).length && !Object.keys(cal.nowcasts || {}).length)) {
    return '<p class="meta">No FX calendar loaded this tick.</p>';
  }
  const nowcasts = Object.values(cal.nowcasts || {})
    .map((x) => x.note)
    .filter(Boolean);
  const rows = (cal.events || [])
    .slice(0, 8)
    .map((e) => {
      const used = e.used == null ? "" : ` · ${e.used_src} ${Number(e.used).toPrecision(4)}`;
      return `<li><span class="meta">${e.country} ${e.impact}</span> ${e.title} — consensus ${e.forecast || "—"} prev ${e.previous || "—"}${used}</li>`;
    })
    .join("");
  return `<h3 class="debate-h">FX calendar / nowcast</h3>${
    nowcasts.length ? `<p class="meta">${nowcasts.join(" · ")}</p>` : ""
  }${rows ? `<ol class="articles">${rows}</ol>` : ""}`;
}

function renderFunnel(s) {
  const f = s.funnel || {};
  const st = s.stats || {};
  const llmBits = layerEntries(s.llm)
    .filter((x) => x.ok)
    .map((x) => `L${x.k}:${x.model}`)
    .join(" ");
  const play = (s.in_play || f.in_play || []).join(" ") || "—";
  const embed = s.embed?.ok ? (s.embed.model || "nomic") : "off";
  funnelEl.innerHTML = [
    ["clock", `${s.clock || f.clock || "idle"} · f${s.tick ?? "—"}/d${s.decision_tick ?? f.decision_tick ?? 0}`],
    ["HMM", (s.telemetry?.hmm || {}).state || f.hmm || "—"],
    ["L1 scores", f.factors ?? st.l1],
    ["verified", f.verified],
    ["garbage", f.garbage],
    ["L4 pass", f.pass],
    ["veto", f.veto],
    ["articles", f.articles],
    ["headlines", f.headlines],
    ["social posts", f.social],
    ["next print", nextPrint(s)],
    ["pending", f.pending],
    ["in play", play],
    ["embed", embed],
    ["LLM committee", llmBits || "waiting"],
    ["L5 gate", s.committee_ok ? "open" : "blocked"],
  ]
    .map(([k, v]) => `<li>${k} <strong>${v ?? "—"}</strong></li>`)
    .join("");
}

function renderMemos(s) {
  const all = s.memos || [];
  let memos = all;
  if (memoFilter === "desk") {
    memos = all.filter((m) => m.status === "pending");
  } else if (memoFilter === "all") {
    memos = all;
  } else if (selected) {
    memos = all.filter((m) => m.symbol === selected && m.status === "pending");
  } else {
    memos = all.filter((m) => m.status === "pending");
  }
  if (!memos.length) {
    if (selected && memoFilter !== "desk" && memoFilter !== "all") {
      const chal = (s.challenges || []).find((c) => c.symbol === selected);
      const why = chal?.veto
        ? `L4 vetoed ${selected}: ${(chal.attacks || ["below confluence"])[0]}`
        : `No Head-of-Desk memo for ${selected} this tape.`;
      memosEl.innerHTML = `<p class="empty">${why} Blotter at left is the research. Open Desk to see PEPE/XRP-style ideas.</p>`;
      return;
    }
    memosEl.innerHTML = s.committee_ok
      ? '<p class="empty">No memos in this view. L5 only writes after L2–L4 survive.</p>'
      : '<p class="empty">L5 is blocked this tick — L2 or L4 did not finish. No new paper ideas until the committee completes.</p>';
    return;
  }
  memosEl.innerHTML = memos
    .map((m) => {
      const pending = m.status === "pending";
      const chips = (m.factors || []).map((x) => `<span class="chip">${x}</span>`).join("");
      return `<article class="memo" data-sym="${m.symbol}">
        <h3><span class="side ${m.side}">${m.side}</span> ${m.symbol}</h3>
        <p class="meta">${money(m.size_usd)} · conv ${(m.conviction * 100).toFixed(0)}% · R:R ${rr(m)} · entry ${Number(m.entry).toPrecision(6)}</p>
        <div class="chips">${chips}</div>
        <p>${m.thesis}</p>
        <p class="meta">Invalidate: ${m.invalidation}</p>
        <p class="status ${m.status}">${m.status}</p>
        ${
          pending
            ? `<div class="actions">
                <button data-approve="${m.id}">Approve paper fill</button>
                <button class="danger" data-reject="${m.id}">Reject</button>
              </div>`
            : ""
        }
      </article>`;
    })
    .join("");
}

function heatColor(v) {
  const x = Math.max(-80, Math.min(80, v));
  if (x >= 0) return `rgba(52, 211, 153, ${0.12 + x / 80 * 0.7})`;
  return `rgba(248, 113, 113, ${0.12 + (-x) / 80 * 0.7})`;
}

function renderHeat(s) {
  const grid = s.heatmap || {};
  const syms = Object.keys(grid).sort();
  if (!syms.length) {
    heatEl.innerHTML = '<p class="empty">Heatmap fills after L1 scores each factor.</p>';
    return;
  }
  const factors = [...new Set(syms.flatMap((sy) => Object.keys(grid[sy])))];
  let html = "<table><thead><tr><th></th>";
  for (const f of factors) html += `<th title="${f}">${FACTOR_LABEL[f] || f.slice(0, 4)}</th>`;
  html += "</tr></thead><tbody>";
  for (const sy of syms) {
    html += `<tr data-sym="${sy}" class="${selected === sy ? "sel" : ""}"><td class="sym">${sy}</td>`;
    for (const f of factors) {
      const v = grid[sy][f];
      const unk = v == null;
      html += `<td title="${f} ${unk ? "unknown" : v}" style="background:${unk ? "transparent" : heatColor(v)}">${unk ? "—" : Number(v).toFixed(0)}</td>`;
    }
    html += "</tr>";
  }
  html += "</tbody></table>";
  heatEl.innerHTML = html;
}

function renderBook(s) {
  const pos = s.positions || [];
  if (!pos.length) {
    bookEl.innerHTML = '<p class="empty">No paper positions. Approve a memo to fill.</p>';
  } else {
    bookEl.innerHTML = pos
      .map(
        (p) =>
          `<div class="pos">${p.side} ${p.symbol} · ${money(p.notional)} · pnl ${money(p.pnl, 2)}
            ${p.stop ? `<span class="meta">stop ${Number(p.stop).toPrecision(6)}</span>` : ""}
            ${p.target ? `<span class="meta">tgt ${Number(p.target).toPrecision(6)}</span>` : ""}
            <button class="ghost" data-close="${p.symbol}">Close</button></div>`
      )
      .join("");
  }
  const logs = s.journal || [];
  journalEl.innerHTML = logs.length
    ? logs
        .slice()
        .reverse()
        .map((j) => `<div class="log">t${j.tick} ${j.label} — ${j.detail || ""}</div>`)
        .join("")
    : '<p class="empty">Research log fills each tick.</p>';
}

function sparkSvg(series, key) {
  const vals = (series || []).map((x) => x[key]).filter((v) => v != null);
  if (vals.length < 2) return "";
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const w = 220;
  const h = 42;
  const pts = vals
    .map((v, i) => {
      const x = (i / (vals.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline fill="none" stroke="#5eead4" stroke-width="1.5" points="${pts}"/></svg>`;
}

function bar(score, unknown) {
  if (unknown) return `<div class="bar unk"><em>—</em></div>`;
  const clamped = Math.max(-100, Math.min(100, score || 0));
  const pct = Math.abs(clamped) / 2;
  const col = clamped >= 0 ? "#34d399" : "#f87171";
  const left = clamped >= 0 ? 50 : 50 - pct;
  return `<div class="bar"><span style="width:${pct}%;margin-left:${left}%;background:${col}"></span></div>`;
}

async function renderInspector(sym, wantBrief = false) {
  const hint = document.getElementById("insp-hint");
  const title = document.getElementById("blotter-sym");
  if (!sym) {
    if (hint) hint.textContent = "Type a ticker and press Open, or click the orbit.";
    if (title) title.textContent = "";
    inspEl.innerHTML = "";
    return;
  }
  if (title) title.textContent = sym;
  if (hint) hint.textContent = `${sym} research stack`;
  let detail = null;
  try {
    detail = await (await fetch(`/api/symbols/${sym}`)).json();
  } catch {
    inspEl.innerHTML = '<p class="empty">Could not load blotter.</p>';
    return;
  }
  if (!detail || detail.ok === false) {
    inspEl.innerHTML = '<p class="empty">Unknown symbol.</p>';
    return;
  }
  const a = (state?.analyses || []).find((x) => x.symbol === sym);
  const c = (state?.challenges || []).find((x) => x.symbol === sym);
  const b = (state?.books || []).find((x) => x.symbol === sym);
  const mark = detail.mark ?? state?.marks?.[sym];
  const factors = (detail.factors || []).filter((f) => f.symbol === sym && f.factor !== "article" && f.factor !== "social_post");
  const articles = detail.articles || (detail.factors || []).filter((f) => f.factor === "article");
  const articleHtml = articles.length
    ? `<h3 class="debate-h">Article desks</h3><ol class="articles">${articles
        .map((f) => `<li><span class="meta">${f.agent_id} ${Number(f.score || 0).toFixed(0)}</span> ${f.note || ""}</li>`)
        .join("")}</ol>`
    : '<p class="meta">No article desks assigned this tick — no matching headlines, or wait for the next tick.</p>';
  const hist = detail.history || state?.history?.[sym] || [];
  const pos = detail.position;
  const debate = detail.debate || (state?.debate || []).filter((d) => d.symbol === sym);
  const debateHtml = debate.length
    ? `<ol class="debate">${debate
        .map(
          (d) =>
            `<li><span class="meta">L${d.from_layer}→L${d.to_layer} ${String(d.model || "").split(":")[0]} ${d.kind || ""}</span> ${d.text || ""}</li>`
        )
        .join("")}</ol>`
    : '<p class="meta">No layer debate this tick yet.</p>';
  const card = detail.checklist || (state?.checklists || {})[sym];
  const checkHtml = card
    ? `<h3 class="debate-h">Promotion checklist</h3><ul class="checks">${Object.entries(card)
        .filter(([k]) => !["ok", "news_waived", "mix_ic", "skill_hit", "skill_n"].includes(k))
        .map(([k, v]) => {
          if (k === "skill") {
            const hit = card.skill_hit == null ? "" : ` ${(Number(card.skill_hit) * 100).toFixed(0)}% n${card.skill_n ?? 0}`;
            return `<li class="${v ? "ok" : "fail"}">skill ${v ? "pass" : "fail"}${hit}</li>`;
          }
          return `<li class="${v ? "ok" : "fail"}">${k} ${v ? "pass" : "fail"}</li>`;
        })
        .join("")}${card.ok ? '<li class="ok">promote</li>' : '<li class="fail">hold</li>'}</ul>`
    : "";
  const tel = detail.telemetry || {};
  const telHtml = `<div class="hud-chips">
    <span>idio ${tel.residual != null ? Number(tel.residual).toFixed(1) : "—"}</span>
    <span>β ${tel.beta_ok && tel.beta != null ? Number(tel.beta).toFixed(2) : "—"}</span>
    <span>σ ${tel.sigma != null ? Number(tel.sigma).toFixed(0) : "—"}</span>
    <span>λ ${tel.hawkes != null ? Number(tel.hawkes).toFixed(2) : "—"}</span>
    <span>${(tel.hmm && tel.hmm.state) || ""}</span>
  </div>`;
  inspEl.innerHTML = `
    <p class="meta">${sym} · mark ${mark != null ? Number(mark).toPrecision(6) : "—"} · blend ${(a?.blended ?? b?.blended_raw ?? 0).toFixed?.(1) ?? a?.blended}</p>
    ${telHtml}
    ${sparkSvg(hist, "blend")}
    <p>${a?.thesis || "No synthesis yet this tick."}</p>
    <p class="flags">${(b?.flags || []).join(" · ") || "no verifier flags"}</p>
    <p class="meta">${c?.veto ? "L4 VETO" : "L4 pass"} ×${(c?.conviction_adj ?? 1).toFixed?.(2) ?? ""} — ${(c?.attacks || [])[0] || ""}</p>
    ${checkHtml}
    <h3 class="debate-h">Layer talk</h3>
    ${debateHtml}
    ${articleHtml}
    ${calendarHtml(detail.calendar || state?.calendar)}
    ${factors
      .map(
        (f) =>
          `<div class="score-row"><span>${f.factor}</span>${bar(f.score, f.unknown)}<span>${f.unknown ? "—" : (f.score || 0).toFixed(0)}</span></div>`
      )
      .join("")}
    ${
      pos
        ? `<div class="pos">${pos.side} ${money(pos.notional)} pnl ${money(pos.pnl, 2)}
            <button class="ghost" data-close="${sym}">Close</button></div>`
        : ""
    }
    <p class="brief" id="llm-brief">${briefCache[sym] || (wantBrief ? "Asking the local model for a blotter brief…" : "")}</p>
  `;
  if (wantBrief && !briefCache[sym]) {
    fetch(`/api/symbols/${sym}/brief`, { method: "POST" })
      .then((r) => r.json())
      .then((j) => {
        const el = document.getElementById("llm-brief");
        const text = j.brief
          ? j.brief
          : j.llm && !j.llm.ok
            ? `Local LLM offline (${j.llm.error || "no model"}). Template research is still on the blotter.`
            : "No brief this tick.";
        briefCache[sym] = text;
        if (el) el.textContent = text;
      })
      .catch(() => {
        briefCache[sym] = "Local LLM did not answer.";
        const el = document.getElementById("llm-brief");
        if (el) el.textContent = briefCache[sym];
      });
  }
}

let replayLayer = null;

function workingAgent(s, sym) {
  const agents = s?.agents || [];
  if (replayLayer) {
    const atLayer = agents.filter((a) => a.layer === replayLayer);
    const named = sym ? atLayer.filter((a) => a.symbol === sym) : [];
    if (named[0]) return named[0];
    if (atLayer[0]) return atLayer[0];
  }
  const pool = sym ? agents.filter((a) => a.symbol === sym || (!a.symbol && a.layer >= 3)) : agents;
  const live = pool.filter((a) => a.status === "live");
  const src = live.length ? live : pool;
  if (!src.length) return null;
  return src.reduce((best, a) => ((a.last_beat || 0) >= (best.last_beat || 0) ? a : best), src[0]);
}

function replayHandoff() {
  return new Promise((resolve) => {
    const layers = [1, 2, 3, 4, 5];
    let i = 0;
    replayLayer = layers[0];
    const step = () => {
      i += 1;
      if (i >= layers.length) {
        replayLayer = null;
        resolve();
        return;
      }
      replayLayer = layers[i];
      setTimeout(step, 420);
    };
    setTimeout(step, 420);
  });
}

function drawOrbit(s, now) {
  const w = cssW;
  const h = cssH;
  ctx.clearRect(0, 0, w, h);
  const cx = w * 0.5;
  const cy = h * 0.5;
  hits = [];
  const scale = Math.min(w, h) / 720;
  const ringFor = {};
  for (const k of Object.keys(RING)) ringFor[k] = RING[k] * scale * 1.15;

  const grd = ctx.createRadialGradient(cx, cy, 8, cx, cy, ringFor[1] + 20);
  grd.addColorStop(0, "rgba(251, 191, 36, 0.07)");
  grd.addColorStop(0.45, "rgba(94, 234, 212, 0.03)");
  grd.addColorStop(1, "rgba(12, 16, 20, 0)");
  ctx.fillStyle = grd;
  ctx.fillRect(0, 0, w, h);

  for (let i = 1; i <= 4; i++) {
    ctx.beginPath();
    ctx.strokeStyle = "rgba(94, 234, 212, 0.05)";
    ctx.ellipse(cx, cy, ringFor[1] * (i / 4), ringFor[1] * 0.9 * (i / 4), 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  const sweep = (now / 3200) % (Math.PI * 2);
  ctx.beginPath();
  ctx.strokeStyle = "rgba(94, 234, 212, 0.22)";
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + Math.cos(sweep) * ringFor[1], cy + Math.sin(sweep) * ringFor[1] * 0.9);
  ctx.stroke();

  for (let layer = 5; layer >= 1; layer--) {
    ctx.beginPath();
    ctx.strokeStyle = LAYER_COLOR[layer] + "44";
    ctx.lineWidth = layer === 1 ? 1 : 1.2;
    ctx.ellipse(cx, cy, ringFor[layer], ringFor[layer] * 0.9, 0, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.fillStyle = LAYER_COLOR[5];
  ctx.beginPath();
  ctx.arc(cx, cy, 11 * scale * 1.4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = "#e8e0d4";
  ctx.font = `${11 * Math.max(scale * 1.3, 0.85)}px IBM Plex Mono, ui-monospace, monospace`;
  ctx.textAlign = "center";
  ctx.fillText("HoD", cx, cy - 18 * scale * 1.3);

  const labels = { 1: "L1 research", 2: "L2 verify", 3: "L3 synthesize", 4: "L4 challenge", 5: "L5 memo" };
  ctx.textAlign = "left";
  ctx.fillStyle = "#8b938c";
  ctx.font = `${10 * Math.max(scale * 1.2, 0.8)}px Syne, sans-serif`;
  for (const layer of [1, 2, 3, 4, 5]) {
    ctx.fillText(labels[layer], cx + ringFor[layer] * 0.12, cy - ringFor[layer] * 0.9 + 4);
  }

  const hmm = s.telemetry?.hmm || {};
  ctx.fillStyle = "#5eead4";
  ctx.font = `${10 * Math.max(scale * 1.15, 0.78)}px IBM Plex Mono, ui-monospace, monospace`;
  ctx.fillText(
    `HMM ${hmm.state || "—"}  breadth ${(hmm.breadth ?? 0).toFixed(2)}  energy ${(hmm.energy ?? 0).toFixed(2)}`,
    12,
    16
  );
  const nowAgent = workingAgent(s, selected);
  if (nowAgent) {
    const layerName = { 1: "research", 2: "verify", 3: "synthesize", 4: "challenge", 5: "memo" }[nowAgent.layer] || "";
    ctx.fillStyle = "#fde68a";
    ctx.fillText(
      `NOW L${nowAgent.layer} ${layerName} · ${(nowAgent.name || "").slice(0, 28)}${nowAgent.status === "live" ? " · live" : ""}`,
      12,
      30
    );
  } else {
    ctx.fillStyle = "#8b938c";
    ctx.fillText("NOW — click Run research tick, then hover a white dot", 12, 30);
  }

  const byLayer = { 1: [], 2: [], 3: [], 4: [], 5: [] };
  for (const a of s.agents || []) {
    if (byLayer[a.layer]) byLayer[a.layer].push(a);
  }
  const l3pos = {};
  for (const layer of [1, 2, 3, 4, 5]) {
    const all = byLayer[layer];
    const mine = selected ? all.filter((a) => a.symbol === selected) : [];
    const rest = selected ? all.filter((a) => a.symbol !== selected) : all;
    const list = mine.length ? mine.concat(rest) : all;
    const cap = layer === 1 && mine.length ? Math.min(list.length, Math.max(MAX_DRAW[1], mine.length + 40)) : Math.min(list.length, MAX_DRAW[layer]);
    const n = cap;
    const r = ringFor[layer];
    for (let i = 0; i < n; i++) {
      const a = list[i] || list[Math.floor((i * list.length) / n)];
      const ang = (i / n) * Math.PI * 2 + now / (22000 / layer);
      const x = cx + Math.cos(ang) * r;
      const y = cy + Math.sin(ang) * r * 0.9;
      if (layer === 3 && a.symbol) l3pos[a.symbol] = { x, y };
      const live = a.status === "live";
      const sel = selected && a.symbol === selected;
      const hot = nowAgent && a.id === nowAgent.id;
      const article = a.factor === "article" || a.factor === "social_post";
      const rad = (layer === 1 ? (article ? 2.6 : 2.1) : 3.3) * (sel ? 1.8 : 1) * (hot ? 1.25 : 1) * Math.max(scale * 1.2, 0.85);
      if (hot) {
        ctx.beginPath();
        ctx.strokeStyle = `rgba(253, 230, 138, ${0.35 + 0.45 * Math.abs(Math.sin(now / 220))})`;
        ctx.lineWidth = 2;
        ctx.arc(x, y, rad + 5 + 2 * Math.sin(now / 180), 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.beginPath();
      ctx.globalAlpha = live ? 0.95 : sel ? 0.55 : 0.32;
      ctx.fillStyle = hot ? "#fde68a" : sel ? "#fff" : a.color || LAYER_COLOR[layer];
      ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
      if (hot) {
        ctx.fillStyle = "#fde68a";
        ctx.font = `${9 * Math.max(scale * 1.15, 0.78)}px IBM Plex Mono, ui-monospace, monospace`;
        ctx.textAlign = "center";
        ctx.fillText((a.name || "").slice(0, 16), x, y - rad - 6);
      } else if (sel && article && live && i < 8) {
        ctx.fillStyle = "#e8e0d4";
        ctx.font = `${8 * Math.max(scale * 1.1, 0.75)}px IBM Plex Mono, ui-monospace, monospace`;
        ctx.textAlign = "center";
        ctx.fillText((a.name || "").replace(`${selected} `, "").slice(0, 10), x, y - rad - 3);
      }
      hits.push({ x, y, r: rad + 6, agent: a });
    }
  }

  for (const e of s.telemetry?.graph || []) {
    const a = l3pos[e.from];
    const b = l3pos[e.to];
    if (!a || !b) continue;
    ctx.beginPath();
    ctx.strokeStyle = `rgba(125, 211, 252, ${0.12 + Math.min(0.55, Math.abs(e.corr || 0))})`;
    ctx.lineWidth = 1;
    ctx.moveTo(a.x, a.y);
    ctx.quadraticCurveTo(cx, cy, b.x, b.y);
    ctx.stroke();
  }

  packets.forEach((p, i) => {
    const fromR = ringFor[p.from_layer] || ringFor[1];
    const toR = ringFor[p.to_layer] || ringFor[5];
    const age = (now - p.born) / 1600;
    if (age > 1 || age < 0) return;
    const r = fromR + (toR - fromR) * age;
    const ang = (i * 0.85 + now / 1100) % (Math.PI * 2);
    const x = cx + Math.cos(ang) * r;
    const y = cy + Math.sin(ang) * r * 0.9;
    ctx.beginPath();
    ctx.fillStyle = LAYER_COLOR[p.to_layer || p.from_layer] || "#fff";
    ctx.arc(x, y, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });
}

function loop(ts) {
  if (state) drawOrbit(state, ts - t0);
  requestAnimationFrame(loop);
}

function renderQuality(s) {
  if (!qualityEl) return;
  const q = s.quality || {};
  const a = q.next_6 || {};
  const b = q.next_12 || {};
  const pct = (x) => (x == null ? "—" : (x * 100).toFixed(0) + "%");
  const ic = s.ic || {};
  const mix = ic.mix;
  const weights = ic.weights || {};
  const ics = ic.ics || {};
  const icBits = Object.entries(weights)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 6)
    .map(([k, w]) => {
      const row = ics[k] || {};
      const icv = row.ic == null ? "n/a" : (row.ic > 0 ? "+" : "") + row.ic;
      return `${k} ${(Number(w) * 100).toFixed(0)}% (${icv})`;
    })
    .join(" · ");
  const graph = (s.telemetry?.graph || [])
    .slice(0, 6)
    .map((e) => `${e.from}→${e.to} lag${e.lag} r${e.corr}`)
    .join(" · ");
  const hmm = s.telemetry?.hmm || {};
  const wf = q.walk_forward || {};
  const is = wf.in_sample || {};
  const oos = wf.out_of_sample || {};
  qualityEl.innerHTML = `
    <p class="meta">Focus ${s.focus || "—"} · HMM ${hmm.state || "—"} · mix IC ${mix == null ? "n<8" : mix}</p>
    <p>${a.label || "Next ~3 min"} · |idio|≥${a.min_score ?? a.min_blend ?? "—"} · n ${a.n ?? 0} · hit ${pct(a.hit_rate)} · avg signed ${a.avg_signed_return ?? "—"}</p>
    <p>${b.label || "Next ~8 min"} · n ${b.n ?? 0} · hit ${pct(b.hit_rate)} — this horizon is the promotion skill gate</p>
    <p>Walk-forward IS n ${is.n ?? 0} hit ${pct(is.hit_rate)} · OOS n ${oos.n ?? 0} hit ${pct(oos.hit_rate)}</p>
    <p class="meta">${icBits || "IC weights equal until 8 samples per factor."}</p>
    <p class="meta">${graph || "Lead-lag graph fills after ~12 return samples vs BTC (lag ≥ 1)."}</p>
    <p class="hint">${q.note || "Quality fills after several minutes of tape."}</p>
  `;
}

let labTab = "agents";

function renderLab(s) {
  const panel = document.getElementById("lab-panel");
  if (!panel) return;
  const lab = s.lab || {};
  if (labTab === "agents") {
    const rows = lab.attribution || [];
    panel.innerHTML = rows.length
      ? `<table><thead><tr><th>Factor</th><th>n</th><th>Hit</th><th>Expectancy</th><th>IC</th><th>PF</th></tr></thead><tbody>${rows
          .map(
            (r) =>
              `<tr><td>${r.factor}</td><td>${r.signal_count}</td><td>${r.hit_rate ?? "—"}</td><td>${r.expectancy ?? "—"}</td><td>${r.ic ?? "—"}</td><td>${r.profit_factor ?? "—"}</td></tr>`
          )
          .join("")}</tbody></table>`
      : "<p class='hint'>Agent attribution fills as mark history accumulates.</p>";
  } else if (labTab === "factors") {
    const decay = lab.decay || {};
    const keys = Object.keys(decay);
    panel.innerHTML = keys.length
      ? keys
          .map((f) => {
            const d = decay[f] || {};
            const bits = Object.entries(d)
              .map(([h, v]) => `${h}s IC ${v.ic ?? "n/a"} (n=${v.n})`)
              .join(" · ");
            return `<p><strong>${f}</strong> — ${bits}</p>`;
          })
          .join("")
      : "<p class='hint'>Factor decay needs more tape.</p>";
  } else if (labTab === "risk") {
    const pr = lab.portfolio_risk || {};
    panel.innerHTML = pr.portfolio_vol != null
      ? `<p>Portfolio vol ${pr.portfolio_vol} · CVaR5 ${pr.cvar_5 ?? "—"} · gross ${pr.gross ?? "—"} · conc ${pr.concentration ?? "—"}</p>
         <p class="meta">Weights: ${JSON.stringify(pr.weights || {})}</p>
         <p class="meta">Stress: ${JSON.stringify(pr.stress || {})}</p>
         <p class="meta">Vol-target: ${JSON.stringify(pr.vol_target_weights || {})}</p>`
      : "<p class='hint'>Open positions to see covariance / CVaR risk.</p>";
  } else if (labTab === "data") {
    const dq = lab.data_quality || {};
    panel.innerHTML = `<p>Observations ${dq.observations ?? 0} · stale ${dq.stale_ratio ?? "—"} · revisions ${dq.revisions ?? 0} · degraded ${dq.degraded ?? false}</p>
      <p class="meta">Latency: ${JSON.stringify(dq.avg_latency_sec || {})}</p>
      <p class="meta">Missingness: ${JSON.stringify(dq.missingness || {})}</p>`;
  } else if (labTab === "abc") {
    panel.innerHTML = "<p class='hint'>Running A/B/C study…</p>";
    fetch("/api/lab/abc")
      .then((r) => r.json())
      .then((data) => {
        const cmp = data.comparison || {};
        const systems = cmp.systems || {};
        const rows = Object.entries(systems)
          .map(([id, m]) => `<tr><td>${id}</td><td>${m.sharpe ?? "—"}</td><td>${m.total_return ?? "—"}</td><td>${m.max_drawdown ?? "—"}</td><td>${m.expectancy ?? "—"}</td><td>${m.n_trades ?? "—"}</td></tr>`)
          .join("");
        panel.innerHTML = `<table><thead><tr><th>System</th><th>Sharpe</th><th>Return</th><th>DD</th><th>Expectancy</th><th>Trades</th></tr></thead><tbody>${rows}</tbody></table>
          <p class="meta">Deltas: ${JSON.stringify(cmp.deltas || {})}</p>`;
      })
      .catch(() => {
        panel.innerHTML = "<p class='hint'>A/B/C study failed.</p>";
      });
  } else {
    panel.innerHTML = "<p class='hint'>Loading experiments…</p>";
    fetch("/api/experiments")
      .then((r) => r.json())
      .then((data) => {
        const ex = data.experiments || [];
        panel.innerHTML = ex.length
          ? `<table><thead><tr><th>ID</th><th>Commit</th><th>Return</th><th>Sharpe</th></tr></thead><tbody>${ex
              .map((e) => {
                const m = e.metrics || {};
                return `<tr><td>${e.id}</td><td>${(e.git_commit || "").slice(0, 7)}</td><td>${m.total_return ?? "—"}</td><td>${m.sharpe ?? "—"}</td></tr>`;
              })
              .join("")}</tbody></table>`
          : "<p class='hint'>Run <code>python -m desk.backtest</code> to register experiments.</p>";
      })
      .catch(() => {
        panel.innerHTML = "<p class='hint'>Experiments unavailable.</p>";
      });
  }
}

document.getElementById("lab-tabs")?.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-lab]");
  if (!btn) return;
  labTab = btn.dataset.lab;
  document.querySelectorAll("#lab-tabs .tab").forEach((b) => b.classList.toggle("on", b === btn));
  if (state) renderLab(state);
});

function applyState(s) {
  state = s;
  const incoming = s.packets || [];
  for (const p of incoming) {
    const key = `${p.ts || ""}-${p.label}-${p.count}`;
    if (key === seenPacket) continue;
    packets.push({ ...p, born: performance.now() });
    seenPacket = key;
  }
  packets = packets.filter((p) => performance.now() - p.born < 1800);
  const next = resolveSelected();
  if (next) persistSelected(next);
  renderKpis(s);
  renderFeeds(s);
  renderFunnel(s);
  renderAction(s);
  renderQuality(s);
  renderLab(s);
  renderMemos(s);
  renderHeat(s);
  renderBook(s);
  if (selected) renderInspector(selected, false);
}

async function post(url) {
  const r = await fetch(url, { method: "POST" });
  return r.json();
}

function pickHit(ev) {
  const rect = canvas.getBoundingClientRect();
  const x = ev.clientX - rect.left;
  const y = ev.clientY - rect.top;
  let best = null;
  let bestD = 18;
  for (const h of hits) {
    const d = Math.hypot(h.x - x, h.y - y);
    if (d < bestD && d < h.r + 8) {
      best = h;
      bestD = d;
    }
  }
  return { hit: best, x, y };
}

canvas.addEventListener("mousemove", (ev) => {
  const { hit, x, y } = pickHit(ev);
  if (!hit) {
    tipEl.hidden = true;
    return;
  }
  const a = hit.agent;
  tipEl.hidden = false;
  tipEl.style.left = x + 12 + "px";
  tipEl.style.top = y + 12 + "px";
  const score = a.last_score == null ? "" : ` · ${Number(a.last_score).toFixed(0)}`;
  const note = a.last_note ? ` — ${a.last_note}` : "";
  const live = a.status === "live" ? " · live" : "";
  tipEl.textContent = `L${a.layer} ${a.name}${score}${live}${note}`;
});
canvas.addEventListener("mouseleave", () => {
  tipEl.hidden = true;
});
canvas.addEventListener("click", (ev) => {
  const { hit } = pickHit(ev);
  if (!hit?.agent?.symbol) return;
  persistSelected(hit.agent.symbol);
  if (state) {
    renderHeat(state);
    renderMemos(state);
  }
  renderInspector(selected, true);
});

document.getElementById("btn-tick").addEventListener("click", async () => {
  const btn = document.getElementById("btn-tick");
  const typed = normalizeSym(tickerBox()?.value || "");
  if (typed) persistSelected(typed);
  btn.disabled = true;
  try {
    await fetch("/api/tick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: selected || typed || "" }),
    });
    applyState(await (await fetch("/api/state")).json());
    await replayHandoff();
  } finally {
    btn.disabled = false;
  }
});

document.querySelector(".tabs").addEventListener("click", (e) => {
  const t = e.target;
  if (!(t instanceof HTMLElement) || !t.dataset.filter) return;
  memoFilter = t.dataset.filter;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.filter === memoFilter));
  if (state) renderMemos(state);
});

async function onAction(e) {
  const t = e.target;
  if (!(t instanceof HTMLElement)) return;
  if (t.dataset.approve) await post(`/api/memos/${t.dataset.approve}/approve`);
  if (t.dataset.reject) await post(`/api/memos/${t.dataset.reject}/reject`);
  if (t.dataset.close) await post(`/api/positions/${t.dataset.close}/close`);
  if (t.dataset.approve || t.dataset.reject || t.dataset.close) {
    applyState(await (await fetch("/api/state")).json());
  }
  const art = t.closest("[data-sym]");
  if (art && art.dataset.sym && !t.dataset.approve && !t.dataset.reject && !t.dataset.close) {
    persistSelected(art.dataset.sym);
    if (state) {
      renderHeat(state);
      renderMemos(state);
    }
    renderInspector(selected, true);
  }
}

memosEl.addEventListener("click", onAction);
bookEl.addEventListener("click", onAction);
inspEl.addEventListener("click", onAction);
heatEl.addEventListener("click", (e) => {
  const row = e.target.closest("tr[data-sym]");
  if (!row) return;
  persistSelected(row.dataset.sym);
  if (state) {
    renderHeat(state);
    renderMemos(state);
  }
  renderInspector(selected, true);
});

const tickerEl = document.getElementById("ticker");
const suggestEl = document.getElementById("suggest");
let suggestHits = [];
let suggestIdx = -1;
let suggestTimer = 0;

function localSuggest(q) {
  const list = state?.watchlist || [];
  const needle = q.trim().toLowerCase().replace("/", "").replace("-", "");
  if (!needle) return list.slice(0, 8).map((a) => ({ ...a, on_desk: true }));
  return list
    .filter((a) => {
      const blob = `${a.symbol} ${a.id} ${(a.keywords || []).join(" ")} ${a.name || ""}`.toLowerCase();
      return a.symbol.toLowerCase().startsWith(needle) || blob.includes(needle);
    })
    .slice(0, 8)
    .map((a) => ({ ...a, on_desk: true }));
}

function drawSuggest(hits) {
  suggestHits = hits;
  suggestIdx = hits.length ? 0 : -1;
  if (!hits.length) {
    suggestEl.hidden = true;
    suggestEl.innerHTML = "";
    return;
  }
  suggestEl.hidden = false;
  suggestEl.innerHTML = hits
    .map(
      (h, i) =>
        `<li role="option" data-i="${i}" class="${i === suggestIdx ? "on" : ""}">
          <span><span class="sym">${h.symbol}</span> <span class="name">${h.name || h.id || ""}</span></span>
          <span class="tag ${h.on_desk ? "" : "off"}">${h.on_desk ? "on desk" : "add"}</span>
        </li>`
    )
    .join("");
}

function paintActive() {
  [...suggestEl.children].forEach((li, i) => li.classList.toggle("on", i === suggestIdx));
}

async function pickSuggest(hit) {
  if (!hit) return;
  tickerEl.value = hit.symbol;
  suggestEl.hidden = true;
  if (!hit.on_desk && hit.id) {
    await fetch("/api/watchlist", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: hit.id, symbol: hit.symbol, name: hit.name || "", yahoo: hit.yahoo || "" }),
    });
  }
  persistSelected(hit.symbol);
  memoFilter = "pending";
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.filter === "pending"));
  if (state) {
    renderHeat(state);
    renderMemos(state);
  }
  renderInspector(selected, true);
}

function exactWatchHit(q) {
  const needle = (q || "").trim().toUpperCase().replace("/", "").replace("-", "");
  if (!needle) return null;
  const row = (state?.watchlist || []).find((a) => a.symbol.toUpperCase() === needle);
  if (row) return { ...row, on_desk: true };
  return (suggestHits || []).find((h) => String(h.symbol).toUpperCase() === needle) || null;
}

tickerEl.addEventListener("input", () => {
  const q = tickerEl.value;
  drawSuggest(localSuggest(q));
  const exact = exactWatchHit(q);
  if (exact && exact.symbol.toUpperCase() !== selected) {
    pickSuggest(exact);
  }
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(async () => {
    if (tickerEl.value !== q) return;
    try {
      const data = await (await fetch(`/api/search?q=${encodeURIComponent(q)}`)).json();
      if (tickerEl.value === q) drawSuggest(data.hits || localSuggest(q));
    } catch {
      /* keep local list */
    }
  }, 180);
});

tickerEl.addEventListener("focus", () => {
  drawSuggest(localSuggest(tickerEl.value));
});

tickerEl.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (!suggestHits.length) return;
    suggestIdx = (suggestIdx + 1) % suggestHits.length;
    paintActive();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (!suggestHits.length) return;
    suggestIdx = (suggestIdx - 1 + suggestHits.length) % suggestHits.length;
    paintActive();
  } else if (e.key === "Enter") {
    e.preventDefault();
    const hit = exactWatchHit(tickerEl.value) || suggestHits[suggestIdx] || suggestHits[0];
    if (hit) pickSuggest(hit);
  } else if (e.key === "Escape") {
    suggestEl.hidden = true;
  }
});

suggestEl.addEventListener("mousedown", (e) => {
  const li = e.target.closest("li[data-i]");
  if (!li) return;
  e.preventDefault();
  pickSuggest(suggestHits[Number(li.dataset.i)]);
});

document.getElementById("btn-open")?.addEventListener("click", () => {
  const hit = exactWatchHit(tickerEl.value) || suggestHits[suggestIdx] || suggestHits[0] || localSuggest(tickerEl.value)[0];
  if (hit) pickSuggest(hit);
  else persistSelected(normalizeSym(tickerEl.value));
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".ticker-box")) suggestEl.hidden = true;
});

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => applyState(JSON.parse(ev.data));
  ws.onclose = () => setTimeout(connect, 2000);
}

window.addEventListener("resize", () => {
  fitCanvas();
  if (state) drawOrbit(state, performance.now() - t0);
});

fitCanvas();
requestAnimationFrame(loop);
connect();
fetch("/api/state")
  .then((r) => r.json())
  .then(applyState)
  .catch(() => {});
