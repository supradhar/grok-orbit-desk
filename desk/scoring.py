from __future__ import annotations

import math
import re
from datetime import datetime, timezone

BULL = {
    "rally", "surge", "soar", "breakout", "ath", "all-time high", "etf", "inflow",
    "inflows", "adoption", "partnership", "upgrade", "accumulate", "accumulation",
    "bullish", "pump", "record", "approval", "approved", "beats", "growth",
    "institutional", "buyback", "undervalued", "support", "reversal", "moon",
}
BEAR = {
    "hack", "exploit", "lawsuit", "ban", "banned", "crash", "outflow", "outflows",
    "dump", "insolvency", "sec charges", "delay", "delayed", "bearish", "liquidation",
    "liquidations", "fraud", "rug", "selloff", "sell-off", "collapse", "warning",
    "risk-off", "recession", "inflation surprise", "mtm loss", "default",
}


def clamp(x: float, lo: float = -100.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def sigmoid_score(x: float, scale: float = 1.0) -> float:
    return clamp(200.0 * (1.0 / (1.0 + math.exp(-x / max(scale, 1e-9))) - 0.5))


def pct_change(a: float, b: float) -> float:
    if not b:
        return 0.0
    return (a - b) / b * 100.0


def rsi_like(closes: list[float], n: int = 14) -> float:
    if len(closes) < n + 1:
        return 50.0
    gains = 0.0
    losses = 0.0
    for i in range(-n, 0):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100.0 - 100.0 / (1.0 + rs)


def realized_vol(closes: list[float]) -> float:
    if len(closes) < 8:
        return 0.0
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1]:
            rets.append(math.log(closes[i] / closes[i - 1]))
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    return math.sqrt(var) * math.sqrt(24 * 365) * 100.0


def headline_sentiment(text: str) -> tuple[float, list[str]]:
    t = text.lower()
    hits: list[str] = []
    score = 0.0
    for w in BULL:
        if w in t:
            score += 12
            hits.append(f"+{w}")
    for w in BEAR:
        if w in t:
            score -= 16
            hits.append(f"-{w}")
    return clamp(score), hits[:8]


def match_keywords(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(re.search(rf"\b{re.escape(k.lower())}\b", t) for k in keywords)


def utc_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def momentum_score(change_24h: float, change_1h: float | None, rsi: float | None) -> tuple[float, str]:
    s = change_24h * 3.2
    if change_1h is not None:
        s += change_1h * 4.0
    note = f"24h {change_24h:+.2f}%"
    if rsi is not None:
        note += f", RSI~{rsi:.0f}"
        if rsi > 72:
            s -= (rsi - 72) * 1.4
            note += " stretched"
        elif rsi < 28:
            s += (28 - rsi) * 1.4
            note += " washed-out"
    return clamp(s), note


def volume_score(rvol: float, change_24h: float) -> tuple[float, str]:
    if rvol <= 0:
        return 0.0, "no volume baseline"
    directional = math.copysign(min(abs(change_24h) * 2.5, 40), change_24h)
    fuel = sigmoid_score((rvol - 1.0) * 2.2, 1.2)
    s = 0.55 * directional + 0.45 * math.copysign(abs(fuel), change_24h if change_24h else 1)
    return clamp(s), f"rel volume {rvol:.2f}x, move {change_24h:+.2f}%"


def volatility_score(vol: float, change_24h: float, atr_pct: float | None) -> tuple[float, str]:
    if vol <= 0:
        return 0.0, "vol n/a"
    crash = change_24h < -6
    squeeze = vol < 35
    if crash:
        s = clamp(-35 - abs(change_24h))
        return s, f"vol shock {vol:.0f}% ann, {change_24h:+.1f}%"
    if squeeze:
        return 12.0, f"vol squeeze {vol:.0f}% — breakout fuel"
    s = clamp(-(vol - 55) * 0.4 + change_24h)
    extra = f", ATR {atr_pct:.2f}%" if atr_pct else ""
    return s, f"realized vol {vol:.0f}%{extra}"


def funding_score(funding_pct: float, oi_change: float | None) -> tuple[float, str]:
    # Crowded longs (high +funding) are a mean-reversion headwind.
    s = clamp(-funding_pct * 8000)
    note = f"funding {funding_pct*100:.4f}%"
    if oi_change is not None:
        note += f", OI {oi_change:+.1f}%"
        if oi_change > 8 and funding_pct > 0.0003:
            s -= 18
            note += " crowded long"
        if oi_change > 8 and funding_pct < -0.0002:
            s += 18
            note += " crowded short"
    return clamp(s), note


def liquidity_score(spread_bps: float | None, depth_usd: float | None) -> tuple[float, str]:
    if spread_bps is None and depth_usd is None:
        return 0.0, "book n/a"
    s = 0.0
    bits = []
    if spread_bps is not None:
        bits.append(f"spread {spread_bps:.1f}bps")
        s += 25 - spread_bps * 2.5
    if depth_usd is not None:
        bits.append(f"depth ${depth_usd/1e6:.2f}m")
        s += sigmoid_score(math.log10(max(depth_usd, 1)) - 6.0, 0.6)
    return clamp(s), ", ".join(bits)


def whale_score(large_buy_usd: float, large_sell_usd: float) -> tuple[float, str]:
    net = large_buy_usd - large_sell_usd
    tot = large_buy_usd + large_sell_usd
    if tot <= 0:
        return 0.0, "no large prints"
    s = sigmoid_score(net / max(tot, 1) * 4.0, 0.8)
    return s, f"large prints buy ${large_buy_usd/1e6:.2f}m / sell ${large_sell_usd/1e6:.2f}m"


def flow_score(volume_usd: float, mcap: float | None, change_24h: float) -> tuple[float, str]:
    if not volume_usd:
        return 0.0, "flow n/a"
    turnover = volume_usd / mcap if mcap else 0.0
    s = math.copysign(min(abs(change_24h) * 2.0, 50), change_24h)
    s += clamp((turnover - 0.08) * 120)
    return clamp(s), f"turnover {turnover*100:.2f}%, 24h {change_24h:+.2f}%"


def structure_score(high: float, low: float, last: float, prev: float | None) -> tuple[float, str]:
    if high <= low or not last:
        return 0.0, "range n/a"
    loc = (last - low) / (high - low)
    s = (loc - 0.5) * 80
    note = f"range loc {loc*100:.0f}%"
    if prev:
        if last > prev and loc > 0.7:
            s += 12
            note += ", holding highs"
        if last < prev and loc < 0.3:
            s -= 12
            note += ", losing lows"
    return clamp(s), note


def macro_score(dxy_chg: float | None, vix: float | None, tnx: float | None, spx_chg: float | None) -> tuple[float, str, str]:
    s = 0.0
    bits = []
    if dxy_chg is not None:
        s -= dxy_chg * 8  # stronger dollar pressures crypto
        bits.append(f"DXY {dxy_chg:+.2f}%")
    if vix is not None:
        bits.append(f"VIX {vix:.1f}")
        if vix > 22:
            s -= (vix - 22) * 2.2
        elif vix < 14:
            s += 10
    if tnx is not None:
        bits.append(f"10Y {tnx:.2f}%")
        if tnx > 4.5:
            s -= 12
    if spx_chg is not None:
        s += spx_chg * 4
        bits.append(f"SPX {spx_chg:+.2f}%")
    regime = "risk-on"
    if (vix or 0) > 24 or (dxy_chg or 0) > 0.4 or (spx_chg or 0) < -1.2:
        regime = "risk-off"
    elif abs(s) < 8:
        regime = "neutral"
    return clamp(s), ", ".join(bits) or "macro n/a", regime


def fear_greed_score(value: int) -> tuple[float, str]:
    # Contrarian: extreme fear is a bounce candidate.
    s = clamp((50 - value) * 1.6)
    label = "neutral"
    if value <= 25:
        label = "extreme fear"
    elif value <= 45:
        label = "fear"
    elif value >= 75:
        label = "extreme greed"
    elif value >= 55:
        label = "greed"
    return s, f"{label} ({value})"


def dominance_score(btc_dom: float, btc_dom_chg: float | None, symbol: str) -> tuple[float, str]:
    note = f"BTC.D {btc_dom:.1f}%"
    if btc_dom_chg is not None:
        note += f" {btc_dom_chg:+.2f}pp"
    if symbol == "BTC":
        s = clamp((btc_dom_chg or 0) * 25 + (btc_dom - 52) * 1.2)
    else:
        s = clamp(-(btc_dom_chg or 0) * 30 - max(btc_dom - 54, 0) * 0.8)
    return s, note


def mempool_score(fast_sat: float | None) -> tuple[float, str]:
    if fast_sat is None:
        return 0.0, "mempool n/a"
    note = f"fast fee {fast_sat:.0f} sat/vB"
    if fast_sat >= 40:
        return 18.0, note + " — network demand hot"
    if fast_sat <= 4:
        return -8.0, note + " — chain quiet"
    return 4.0, note


def stablecoin_score(total_volume: float | None, mcap_change: float | None) -> tuple[float, str]:
    s = 0.0
    bits = []
    if mcap_change is not None:
        s += clamp(mcap_change * 2.5)
        bits.append(f"total mcap 24h {mcap_change:+.2f}%")
    if total_volume:
        bits.append(f"total vol ${total_volume/1e9:.1f}b")
        if total_volume > 1.2e11:
            s += 10
        elif total_volume < 4e10:
            s -= 8
    return clamp(s), ", ".join(bits) or "stable/flow n/a"


def stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
