from __future__ import annotations

import asyncio
import csv
import io
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from desk.scoring import clamp

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_IDS = ("ICSA", "PAYEMS", "UNRATE", "FEDFUNDS", "CPIAUCSL")

# Higher print vs consensus → this sign on the *dovish* axis (positive = easier policy / gold-friendly).
KIND_DOVISH = {
    "claims": 1.0,
    "unrate": 1.0,
    "nfp": -1.0,
    "adp": -1.0,
    "jolts": -1.0,
    "cpi": -1.0,
    "pce": -1.0,
    "ppi": -1.0,
    "earnings": -1.0,
    "fomc": -1.0,
    "pmi": -0.25,
    "gdp": -0.2,
    "retail": -0.2,
}


def parse_num(text: str | None) -> float | None:
    if text is None:
        return None
    s = str(text).strip().replace(",", "")
    if not s or s in {".", "-"}:
        return None
    mult = 1.0
    if s.endswith("%"):
        try:
            return float(s[:-1])
        except ValueError:
            return None
    if s[-1] in "Kk":
        mult = 1e3
        s = s[:-1]
    elif s[-1] in "Mm":
        mult = 1e6
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def classify(title: str) -> str | None:
    t = title.lower()
    if "claim" in t:
        return "claims"
    if "adp" in t:
        return "adp"
    if "jolts" in t:
        return "jolts"
    if "non-farm" in t or "nonfarm" in t or "employment change" in t:
        return "nfp"
    if "unemployment rate" in t:
        return "unrate"
    if "federal funds" in t or "fomc" in t or "fed interest rate" in t or "fed rate decision" in t:
        return "fomc"
    if "cpi" in t or "consumer price" in t:
        return "cpi"
    if "pce" in t:
        return "pce"
    if "ppi" in t or "producer price" in t:
        return "ppi"
    if "hourly earnings" in t:
        return "earnings"
    if "pmi" in t or "ism" in t:
        return "pmi"
    if "gdp" in t:
        return "gdp"
    if "retail" in t:
        return "retail"
    return None


def _parse_when(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def _csv_tail(text: str, col: str, n: int = 8) -> list[float]:
    rows = list(csv.DictReader(io.StringIO(text)))
    out: list[float] = []
    for row in rows:
        val = parse_num(row.get(col) or row.get(col.lower()) or "")
        if val is None:
            continue
        out.append(val)
    return out[-n:]


def _surprise(actual: float, forecast: float, kind: str) -> float:
    if kind == "claims":
        denom = 8_000.0
    elif kind in {"nfp", "adp"}:
        denom = 25_000.0
    elif kind == "jolts":
        denom = 200_000.0
    elif kind == "unrate":
        denom = 0.15
    elif kind in {"cpi", "pce", "ppi", "earnings"}:
        denom = 0.12
    elif kind == "fomc":
        denom = 0.25
    else:
        denom = max(abs(forecast) * 0.04, 0.4)
    z = (actual - forecast) / denom
    return clamp(z * 22 * KIND_DOVISH.get(kind, 0.0))


def nowcast_bundle(fred: dict[str, list[float]], events: list[dict[str, Any]], tnx_chg: float | None) -> dict[str, Any]:
    def _usd(kind: str) -> dict[str, Any] | None:
        return next((e for e in events if e.get("kind") == kind and e.get("country") == "USD"), None)

    icsa = fred.get("ICSA") or []
    payems = fred.get("PAYEMS") or []
    unrate = fred.get("UNRATE") or []
    fed = fred.get("FEDFUNDS") or []
    cpi = fred.get("CPIAUCSL") or []
    claims_now = sum(icsa[-4:]) / 4 if len(icsa) >= 4 else (icsa[-1] if icsa else None)
    nfp_last = (payems[-1] - payems[-2]) * 1000 if len(payems) >= 2 else None
    claims_event = _usd("claims")
    nfp_event = _usd("nfp")
    cpi_event = _usd("cpi")
    if claims_now is None and claims_event and claims_event.get("previous_n"):
        claims_now = float(claims_event["previous_n"])
    if nfp_last is None and nfp_event and nfp_event.get("previous_n") is not None:
        nfp_last = float(nfp_event["previous_n"])
    out: dict[str, Any] = {}
    if claims_now is not None:
        fc = (claims_event or {}).get("forecast_n")
        out["claims"] = {
            "nowcast": claims_now,
            "forecast": fc,
            "last_official": icsa[-1] if icsa else None,
            "note": (
                f"4-week claims avg {claims_now/1000:.0f}k"
                + (f" vs consensus {fc/1000:.0f}k" if fc else "")
                + (f"; last official {icsa[-1]/1000:.0f}k" if icsa else "")
            ),
        }
    if nfp_event:
        fc = nfp_event.get("forecast_n")
        nfp_now = fc
        if fc is not None and claims_now is not None and (claims_event or {}).get("forecast_n"):
            gap = claims_now - float(claims_event["forecast_n"])
            nfp_now = fc - 2.0 * gap
        elif nfp_last is not None:
            nfp_now = nfp_last
        out["nfp"] = {
            "nowcast": nfp_now,
            "forecast": fc,
            "last_official": nfp_last,
            "note": (
                f"NFP desk nowcast {nfp_now/1000:.0f}k" if nfp_now is not None else "NFP nowcast n/a"
            )
            + (f" vs consensus {fc/1000:.0f}k" if fc else "")
            + (f"; last payrolls {nfp_last/1000:.0f}k" if nfp_last is not None else ""),
        }
    if unrate:
        out["unrate"] = {
            "nowcast": unrate[-1],
            "forecast": (_usd("unrate") or {}).get("forecast_n"),
            "last_official": unrate[-1],
            "note": f"UNRATE last official {unrate[-1]:.1f}%",
        }
    if len(cpi) >= 2:
        mom = (cpi[-1] / cpi[-2] - 1.0) * 100.0
        fc = (cpi_event or {}).get("forecast_n")
        out["cpi"] = {
            "nowcast": mom,
            "forecast": fc,
            "last_official": mom,
            "note": (
                f"CPI MoM desk {mom:+.2f}%"
                + (f" vs consensus {fc:+.2f}%" if fc is not None else "")
                + f"; index {cpi[-1]:.1f}"
            ),
        }
    if fed:
        lean = "hold"
        if tnx_chg is not None and tnx_chg < -0.04:
            lean = "easier / cut-lean"
        elif tnx_chg is not None and tnx_chg > 0.04:
            lean = "tighter / hike-lean"
        tnx_bit = f"{tnx_chg:+.2f}pp" if tnx_chg is not None else "n/a"
        out["fed"] = {
            "nowcast": fed[-1],
            "last_official": fed[-1],
            "note": f"Fed funds {fed[-1]:.2f}%; 10Y {tnx_bit} — desk {lean}",
        }
    return out


def analyze(raw_events: list[dict[str, Any]], fred: dict[str, list[float]], tnx_chg: float | None = None) -> dict[str, Any]:
    now = time.time()
    events: list[dict[str, Any]] = []
    for row in raw_events:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        kind = classify(title)
        when = _parse_when(str(row.get("date") or ""))
        ev = {
            "title": title,
            "country": str(row.get("country") or ""),
            "impact": str(row.get("impact") or ""),
            "date": row.get("date"),
            "ts": when,
            "forecast": row.get("forecast") or "",
            "previous": row.get("previous") or "",
            "actual": row.get("actual") or "",
            "forecast_n": parse_num(row.get("forecast")),
            "previous_n": parse_num(row.get("previous")),
            "actual_n": parse_num(row.get("actual")),
            "kind": kind,
        }
        events.append(ev)

    nowcasts = nowcast_bundle(fred, events, tnx_chg)
    # Never treat FEDFUNDS level as an FOMC decision nowcast — only score FOMC on actual print.
    kind_nowcast = {
        "claims": (nowcasts.get("claims") or {}).get("nowcast"),
        "nfp": (nowcasts.get("nfp") or {}).get("nowcast"),
        "unrate": (nowcasts.get("unrate") or {}).get("nowcast"),
        "cpi": (nowcasts.get("cpi") or {}).get("nowcast"),
    }

    scored: list[dict[str, Any]] = []
    gold = 0.0
    growth = 0.0
    wsum = 0.0
    event_risk = False
    next_ev = None
    for ev in events:
        if ev["impact"] not in {"High", "Medium"}:
            continue
        usd = ev["country"] in {"USD", "All"}
        if not usd:
            continue
        weight = 1.0
        if ev["impact"] == "High":
            weight *= 1.25
        actual = ev["actual_n"]
        used = actual
        src = "print"
        if used is None and ev["kind"] in kind_nowcast and kind_nowcast[ev["kind"]] is not None:
            used = float(kind_nowcast[ev["kind"]])
            src = "nowcast"
        fc = ev["forecast_n"]
        score = 0.0
        # Skip zero-info nowcasts that are just consensus echoed back.
        if used is not None and fc is not None and ev["kind"]:
            if src == "nowcast" and abs(used - fc) < 1e-9:
                score = 0.0
            else:
                score = _surprise(used, fc, ev["kind"])
                if src == "nowcast":
                    score *= 0.55
                    weight *= 0.7
        ev = dict(ev)
        ev["used"] = used
        ev["used_src"] = src
        ev["score"] = round(score, 1)
        if when := ev.get("ts"):
            eta = when - now
            ev["eta_sec"] = eta
            # Pre-print risk stronger than post-print.
            if -15 * 60 < eta < 90 * 60 and ev["impact"] == "High" and usd:
                event_risk = True
            if eta > -2 * 3600 and (next_ev is None or eta < next_ev.get("eta_sec", 9e9)):
                if eta > -15 * 60:
                    next_ev = ev
        scored.append(ev)
        if ev["kind"] and score:
            gold += score * weight
            if ev["kind"] in {"pmi", "gdp", "retail", "nfp", "adp"}:
                growth += (-score if ev["kind"] in {"nfp", "adp"} else score) * weight
            wsum += weight

    gold_score = clamp(gold / max(wsum, 1.0) * min(wsum, 3.0)) if wsum else 0.0
    crypto_score = clamp(0.65 * gold_score + 0.35 * clamp(growth)) if wsum else 0.0
    headlines = []
    for ev in scored[:16]:
        bits = [f"{ev['country']} {ev['title']}"]
        if ev.get("forecast"):
            bits.append(f"consensus {ev['forecast']}")
        if ev.get("previous"):
            bits.append(f"prev {ev['previous']}")
        if ev.get("used") is not None:
            bits.append(f"{ev['used_src']} {ev['used']:.4g}")
        headlines.append(
            {
                "title": " · ".join(bits),
                "description": f"{ev.get('impact')} impact {ev.get('kind') or 'macro'} print",
                "link": "https://www.forexfactory.com/calendar",
                "source": "forex_factory",
                "tickers": ["XAUUSD", "BTC", "ETH"],
            }
        )

    notes = [v["note"] for v in nowcasts.values() if v.get("note")]
    if next_ev:
        notes.insert(0, f"Next: {next_ev['country']} {next_ev['title']} ({next_ev.get('forecast') or 'no consensus'})")
    return {
        "events": scored[:24],
        "nowcasts": nowcasts,
        "gold_score": gold_score,
        "crypto_score": crypto_score,
        "event_risk": event_risk,
        "next": next_ev,
        "headlines": headlines,
        "notes": notes[:8],
        "source": FF_URL,
        "fred": {k: v[-1] if v else None for k, v in fred.items()},
        "_fred_series": {k: list(v) for k, v in fred.items() if v},
    }


def _fred_sync(sid: str) -> list[float]:
    # Minimal headers — long Chrome UA + text/plain Accept sometimes hangs on FRED.
    headers = {"User-Agent": "OrbitDesk/1.0", "Accept": "*/*"}
    try:
        r = httpx.get(FRED_CSV, params={"id": sid}, headers=headers, timeout=10.0, follow_redirects=True)
        r.raise_for_status()
        return _csv_tail(r.text, sid, 8)
    except Exception:
        return []


async def fetch_fred() -> dict[str, list[float]]:
    """FRED chart CSV — sync worker, one series at a time, hard wall budget."""
    fred: dict[str, list[float]] = {sid: [] for sid in FRED_IDS}
    order = ["ICSA", "UNRATE", "PAYEMS", "FEDFUNDS", "CPIAUCSL"]
    loop = asyncio.get_running_loop()
    deadline = time.time() + 12.0
    for sid in order:
        if time.time() > deadline:
            break
        try:
            vals = await asyncio.wait_for(loop.run_in_executor(None, _fred_sync, sid), timeout=9.0)
            if vals:
                fred[sid] = vals
        except Exception:
            continue
    return fred


async def fetch(client: httpx.AsyncClient, tnx_chg: float | None = None, fred_prior: dict[str, list[float]] | None = None) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    try:
        r = await client.get(FF_URL, timeout=12.0)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            raw = data
    except Exception:
        raw = []

    fred = await fetch_fred()
    # Keep last-good series when FRED flakes this tick.
    prior = fred_prior or {}
    for sid in FRED_IDS:
        if not fred.get(sid) and prior.get(sid):
            fred[sid] = list(prior[sid])
    return analyze(raw, fred, tnx_chg=tnx_chg)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty() -> dict[str, Any]:
    return {
        "events": [],
        "nowcasts": {},
        "gold_score": 0.0,
        "crypto_score": 0.0,
        "event_risk": False,
        "next": None,
        "headlines": [],
        "notes": ["economic calendar dark"],
        "source": FF_URL,
        "fred": {},
        "ts": _iso_now(),
    }
