# Master Build Plan (Phases 0–15)

Canonical source: `Grok_Orbit_Desk_Master_Build_Plan.docx`.

## Status

| Phase | Status | Modules |
|-------|--------|---------|
| 0 Baseline / manifests | Done | `desk/manifest.py` |
| 1 Correctness | Done | paper/risk/store/quality/layer5 |
| 2 Backtest Engine v1 | Done | `desk/backtest/` |
| 3 Execution + portfolio sim | Done | execution.py, portfolio.py |
| 4 Metrics + walk-forward | Done | metrics.py, walkforward.py |
| 5 Factor hygiene / attribution / ablation | Done | `desk/factors.py` |
| 6 Cost-aware NO-TRADE | Done | layer5 + backtest pipeline |
| 7 Portfolio risk / optimizer | Done | `desk/portfolio_risk.py` |
| 8 Event-time data | Done | `desk/eventdata.py` |
| 9 LLM evidence + A/B harness | Done | `desk/llm_study.py` |
| 10 ML alpha (logistic) | Done | `desk/ml_alpha.py` |
| 11 SQLite experiments | Done | `desk/research_db.py` |
| 12 Tests + CI | Done | `tests/`, `.github/workflows/ci.yml` |
| 13 Research terminal UI | Done | labs section in `web/` |
| 14 Observability / secrets | Done | `desk/observability.py` |
| 15 Live broker interface | Stub only | `desk/broker.py` (live raises; paper adapter works) |

## Commands

```bash
pytest -q
python -m desk.backtest --symbols BTC,ETH --walkforward --warmup 100
python -m desk
```

## Promotion gate

`desk/promotion.py` — DATA QUALITY → … → CAPACITY → PROMOTE.

Live money remains **blocked** until OOS paper validation and ops review (Phase 15 stub enforces this).
