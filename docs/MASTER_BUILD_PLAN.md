# Master Build Plan (Phases 0–15) — completion status

Canonical source: `Grok_Orbit_Desk_Master_Build_Plan.docx`.

## Status (doc-complete prototype)

| Phase | Status | Notes |
|-------|--------|-------|
| 0 Baseline / manifests | Done | `desk/manifest.py` |
| 1 Correctness | Done | daily halt, history 512, expectancy, vol stops |
| 2 Backtest Engine v1 | Done | next-bar, warm-up, fixtures |
| 3 Execution + portfolio | Done | fees/spread/gap stops |
| 4 Metrics + walk-forward | Done | Sharpe/Sortino/CVaR inputs, WF windows |
| 5 Factor hygiene | Done | normalize, decay, attribution + ECE + regime, ablation |
| 6 Cost-aware NO-TRADE | Done | L5 + backtest |
| 7 Portfolio risk | Done | vol target, cov, CVaR, optimizer, **stress shocks** |
| 8 Event-time data | Done | `EventLedger` wired into **live DataHub** |
| 9 LLM A/B/C | Done | evidence packets + **`run_abc_study`** OOS compare |
| 10 ML alpha | Done | logistic + **sklearn GBM** (+ LightGBM if installed), model registry |
| 11 SQLite | Done | full table set from doc (layers, orders, models, datasets…) |
| 12 Tests + CI | Done | doc-named suite; **53 pytest** |
| 13 Research terminal | Done | Agent/Factor/Risk/**Data**/A/B/C/Experiments labs |
| 14 Observability | Done | JSONL, redact secrets, data-quality health |
| 15 Live broker | Stub (correct) | paper adapter works; live raises until promotion gate |

## Verify

```bash
pytest -q
python -m desk.backtest --symbols BTC,ETH --walkforward --warmup 100
python -c "from desk.ab_study import run_abc_study; from pathlib import Path; print(run_abc_study(Path('data/ohlcv')))"
python -m desk
```

Hard-refresh UI **v26**.
