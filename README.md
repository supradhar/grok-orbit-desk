# Grok Orbit Desk

Local paper-trading research desk for crypto majors plus standalone metals (XAUUSD via COMEX `GC=F`). One process runs ~500 lightweight agents across five layers (L1 factors → L5 promotion memo). Fills only happen after an L5 memo and explicit human **Approve**.

**Not financial advice. Paper trading only.** Third-party feeds (Yahoo, Binance, FRED, Forex Factory, Reddit, etc.) can fail or rate-limit.

## Quick start

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m desk
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787). Hard-refresh if the UI looks stale.

Optional: run [Ollama](https://ollama.com) locally (`qwen2.5:3b` by default) for LLM layer notes — the desk still works without it.

## What it does

| Layer | Role |
|-------|------|
| L1 | Factor agents (tape, structure, news, policy/macro calendar, …) |
| L2 | Source / trust books |
| L3 | Blend + regime / HMM telemetry |
| L4 | Challenge / veto |
| L5 | Promotion memo → human Approve → paper fill |

Gold and other yahoo-only names are **standalone** (no BTC β residual). Crypto HMM panic does not flatten metals. Macro calendar uses Forex Factory week JSON plus FRED series (claims, NFP, unemployment, Fed funds, CPI).

## Config

Edit `config.yaml`:

- `watchlist` — Binance symbols and/or `yahoo:` marks (e.g. `GC=F` for gold)
- `min_confluence`, `min_trust`, `min_skill` — promotion gates
- `llm.host` / `llm.model` — Ollama endpoint
- `sectors.metals` / `high_beta` — risk grouping

Runtime state lives under `data/` (gitignored).

## Disclaimer

This is a research / paper-trading UI for personal use. Do not connect live brokerage keys. Past paper PnL is not predictive.
