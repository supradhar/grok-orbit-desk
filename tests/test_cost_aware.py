from __future__ import annotations

from desk.layer5 import expected_alpha_clears_costs


def test_cost_aware_gate():
    cfg = {"fee_bps": 4, "slippage_bps": 6, "spread_bps": 2, "cost_buffer": 1.25}
    assert expected_alpha_clears_costs(5.0, cfg) is False  # tiny signal
    assert expected_alpha_clears_costs(50.0, cfg) is True
