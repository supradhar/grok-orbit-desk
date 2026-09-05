from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal


Side = Literal["long", "short"]
Layer = Literal[1, 2, 3, 4, 5]


def to_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


@dataclass
class Asset:
    id: str
    symbol: str
    binance: str = ""
    keywords: list[str] = field(default_factory=list)
    yahoo: str = ""


@dataclass
class FactorScore:
    agent_id: str
    layer: int
    factor: str
    symbol: str | None
    score: float  # -100 bearish .. +100 bullish
    confidence: float  # 0..1
    note: str
    evidence: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    ts: float = 0.0
    unknown: bool = False


@dataclass
class VerifiedFactorBook:
    agent_id: str
    symbol: str
    trust: float
    flags: list[str]
    factors: list[FactorScore]
    blended_raw: float
    garbage: bool = False
    ts: float = 0.0


@dataclass
class AnalysisReport:
    agent_id: str
    symbol: str
    blended: float
    confidence: float
    agreement: float
    regime: str
    thesis: str
    bull_factors: list[str]
    bear_factors: list[str]
    trust: float = 1.0
    ts: float = 0.0
    residual: float = 0.0
    beta: float = 0.0
    sigma: float = 0.0
    hawkes: float = 0.0
    beta_ok: bool = False
    standalone: bool = False


@dataclass
class ChallengeReport:
    agent_id: str
    symbol: str
    veto: bool
    conviction_adj: float  # 0..1 multiplier applied to |blended|
    attacks: list[str]
    surviving_thesis: str
    ts: float = 0.0


@dataclass
class DecisionMemo:
    id: str
    symbol: str
    side: Side
    conviction: float
    size_usd: float
    entry: float
    stop: float
    target: float
    thesis: str
    invalidation: str
    factors: list[str]
    risk_notes: list[str]
    status: Literal["pending", "approved", "rejected", "expired"] = "pending"
    ts: float = 0.0


@dataclass
class Fill:
    idea_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    ts: float


@dataclass
class Position:
    symbol: str
    side: Side
    qty: float
    avg_price: float
    mark: float = 0.0
    stop: float = 0.0
    target: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.qty * (self.mark or self.avg_price))

    @property
    def pnl(self) -> float:
        px = self.mark or self.avg_price
        sign = 1.0 if self.side == "long" else -1.0
        return sign * (px - self.avg_price) * self.qty

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "mark": self.mark,
            "notional": self.notional,
            "pnl": self.pnl,
            "stop": self.stop,
            "target": self.target,
        }


@dataclass
class AgentState:
    id: str
    name: str
    layer: int
    role: str
    factor: str | None
    symbol: str | None
    status: str = "idle"
    last_score: float | None = None
    last_note: str = ""
    last_beat: float = 0.0
    color: str = "#6ee7ff"


@dataclass
class DeskSnapshot:
    ts: float
    equity: float
    cash: float
    pnl: float
    tick: int
    regime: str
    agents: list[AgentState]
    factors: list[FactorScore]
    books: list[VerifiedFactorBook]
    analyses: list[AnalysisReport]
    challenges: list[ChallengeReport]
    memos: list[DecisionMemo]
    positions: list[dict[str, Any]]
    marks: dict[str, float]
    packets: list[dict[str, Any]]
    sources_ok: dict[str, bool]
    stats: dict[str, Any]
    heatmap: dict[str, dict[str, float]]
    journal: list[dict[str, Any]] = field(default_factory=list)
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    funnel: dict[str, Any] = field(default_factory=dict)
    exposure_pct: float = 0.0
