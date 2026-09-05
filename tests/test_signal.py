from __future__ import annotations

from desk import signal
from desk.models import AnalysisReport


def _rep(symbol: str, blended: float, **kw) -> AnalysisReport:
    return AnalysisReport(
        agent_id="t",
        symbol=symbol,
        blended=blended,
        confidence=0.5,
        agreement=0.5,
        regime="x",
        thesis="",
        bull_factors=[],
        bear_factors=[],
        **kw,
    )


def test_alpha_and_hmm_excludes_standalone():
    reports = [
        _rep("BTC", 20),
        _rep("ETH", 15),
        _rep("XAUUSD", 80, standalone=True),
    ]
    hmm = signal.hmm_state(reports, [], watch={"BTC", "ETH", "XAUUSD"}, exclude={"XAUUSD"})
    assert "state" in hmm
    assert signal.alpha_score(reports[0]) == 20
