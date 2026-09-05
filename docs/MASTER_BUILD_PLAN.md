# Master Build Plan (Phases 0–15)

Canonical source: `Grok_Orbit_Desk_Master_Build_Plan.docx` (author desktop).

## Status (foundation sprint)

| Phase | Status |
|-------|--------|
| 0 Baseline / manifests | Done (`desk/manifest.py`, backtest metadata) |
| 1 Correctness (daily halt, history 512, expectancy skill, vol stops) | Done |
| 2 Backtest Engine v1 | Done (`desk/backtest/`) |
| 3 Execution + portfolio sim | Done (next-bar, fees, spread, gap stops) |
| 4 Metrics + walk-forward | Done |
| 5 Factor hygiene (shrink + corr dampen) | Partial (IC shrink + dampen; attribution/ablation next) |
| 6 Cost-aware NO-TRADE | Partial (backtest decide gate) |
| 7–15 Portfolio risk, event-time data, LLM study, ML, DB, UI, live | Not started |

Run: `python -m desk.backtest --symbols BTC,ETH --walkforward`

Promotion gate for new factors/agents remains: data quality → no lookahead → sample → OOS +EV → costs → regime → DD → correlation → capacity → promote.
