# Grok Orbit Desk

Local **paper-trading research desk** for crypto majors plus standalone metals (XAUUSD via COMEX `GC=F`). One process runs lightweight agents across five layers (L1 factors → L5 promotion memo). Fills only after an L5 memo and explicit human **Approve**.

**Not financial advice. Paper trading only.** This is a research prototype: architecture is ahead of empirical proof. Out-of-sample backtest metrics do **not** imply future profitability. Third-party feeds (Yahoo, Binance, FRED, etc.) can fail or rate-limit.

## Quick start (live desk)

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m desk
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

Optional: [Ollama](https://ollama.com) with `qwen2.5:3b` for LLM layer notes — the desk works without it.

## Backtest Engine v1

Deterministic chronological replay on OHLCV (CSV). No live news/LLM/macro. **Next-bar execution only** (signal at bar `t` fills no earlier than `t+1`). Warm-up bars emit no trades.

```bash
# Uses / generates synthetic fixtures under data/ohlcv if CSVs missing
python -m desk.backtest --symbols BTC,ETH,SOL,XAUUSD --warmup 250

# Walk-forward OOS windows
python -m desk.backtest --symbols BTC,ETH --walkforward --warmup 100
```

Artifacts land in `data/backtests/<run_id>/`:

- `config.yaml`, `metadata.json` (git commit, config hash, assumptions)
- `equity.csv`, `trades.csv`, `signals.csv`
- `metrics.json` (return, Sharpe/Sortino, drawdown, expectancy, profit factor, turnover, fees)
- `walkforward.json` when `--walkforward`

Place real data as `data/ohlcv/BTC.csv` with columns `ts,open,high,low,close,volume`.

## Layers

| Layer | Role |
|-------|------|
| L1 | Factor agents (tape, structure, news, policy/macro, …) |
| L2 | Source / trust books |
| L3 | Blend + regime / HMM telemetry |
| L4 | Challenge / veto |
| L5 | Promotion memo → human Approve → paper fill |

Gold/yahoo-only names are **standalone** (no BTC β). Crypto HMM panic does not flatten metals.

## Config knobs

See `config.yaml`: `history_rows` (default 512), `min_skill_n`, `risk_day_tz`, `stop_pct`, fees/slippage, gates, watchlist.

Daily loss halt uses **day_start_equity** (UTC risk day), persisted across restarts — not lifetime starting capital.

## Tests

```bash
pytest -q
```

## Research labs & studies

```bash
# A/B/C deterministic vs softer vs adversarial-friction policies
python -c "from pathlib import Path; from desk.ab_study import run_abc_study; import json; print(json.dumps(run_abc_study(Path('data/ohlcv')), indent=2)[:2000])"
```

UI (hard-refresh **ui 26**): Agent Lab, Factor Lab, Portfolio Risk, Data Quality, A/B/C Study, Experiments.

## What this does *not* claim yet

- Broker-ready live money (Phase 15 stub **blocks** live submits)
- That synthetic-fixture / policy-sim A/B/C proves LLM alpha in production
- That sklearn/LightGBM beats the handcrafted baseline on live markets without your own OOS review

See [docs/MASTER_BUILD_PLAN.md](docs/MASTER_BUILD_PLAN.md).
