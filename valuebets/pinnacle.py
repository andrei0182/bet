"""Cotele Pinnacle (casa „ascuțită” de referință) pentru fotbal.

CONFIRMAT (2026-10-20) via curl: API-ul public de citire folosit de site-ul
Pinnacle merge fără cheie:
- `{BASE}/sports/29/matchups`: meciurile de fotbal (~1100), cu `participants`
  (`alignment` "home"/"away", `name`), `league.name`, `startTime` (UTC) și
  `parentId` (setat la variantele speciale -- cornere, cartonașe -- pe care le
  ignorăm);
- `{BASE}/sports/29/markets/straight`: piețele (~35 000), cu `matchupId`,
  `type` ("moneyline" = 1X2, "total", "spread", "team_total"), `period`
  (0 = tot meciul, 1 = prima repriză), `status` ("open"), `prices[]` cu
  `designation` ("home"/"draw"/"away"/"over"/"under"), `points` (linia) și
  `price` în cote americane (+379 / -177), plus `limits[].amount` (miza maximă).
"""
from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE = "https://guest.api.arcadia.pinnacle.com/0.1"
SOCCER = 29

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
})
_retry = Retry(total=3, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry))


def american_to_decimal(price: float) -> float:
    return 1 + price / 100 if price > 0 else 1 + 100 / abs(price)


def fair_odds(odds: dict[str, float]) -> dict[str, float]:
    """Cotele corecte: probabilitățile implicite normalizate la 100% (marja
    casei împărțită proporțional)."""
    inv = {k: 1 / v for k, v in odds.items() if v > 1}
    total = sum(inv.values())
    return {k: total / p for k, p in inv.items()} if total else {}


# (piață, linie) -> {selecție: cotă corectă}; piață: "1x2", "1x2_h1", "total", "total_h1"
Markets = dict[tuple[str, float], dict[str, float]]


@dataclass
class PinMatch:
    id: int
    home: str
    away: str
    league: str
    start_utc: dt.datetime
    fair: Markets = field(default_factory=dict)
    limits: dict[tuple[str, float], float] = field(default_factory=dict)


def _utc(value: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def parse(matchups: list[dict], markets: list[dict]) -> list[PinMatch]:
    matches: dict[int, PinMatch] = {}
    for m in matchups:
        if m.get("parentId") or m.get("isLive"):
            continue
        teams = {p.get("alignment"): p.get("name", "") for p in m.get("participants") or []}
        start = _utc(m.get("startTime", ""))
        if not teams.get("home") or not teams.get("away") or start is None:
            continue
        matches[m["id"]] = PinMatch(m["id"], teams["home"], teams["away"],
                                    (m.get("league") or {}).get("name", ""), start)

    raw: dict[int, dict[tuple[str, float], dict[str, float]]] = defaultdict(dict)
    limits: dict[int, dict[tuple[str, float], float]] = defaultdict(dict)
    for mk in markets:
        match = matches.get(mk.get("matchupId"))
        period = mk.get("period")
        if match is None or mk.get("status") != "open" or period not in (0, 1):
            continue
        suffix = "" if period == 0 else "_h1"
        if mk.get("type") == "moneyline":
            key = ("1x2" + suffix, 0.0)
            odds = {p["designation"]: american_to_decimal(p["price"]) for p in mk.get("prices") or []}
            if set(odds) != {"home", "draw", "away"}:
                continue
        elif mk.get("type") == "total":
            prices = mk.get("prices") or []
            points = {p.get("points") for p in prices}
            if len(points) != 1 or None in points:
                continue
            line = float(points.pop())
            if line * 2 % 2 != 1:  # doar linii .5 (fără rambursări)
                continue
            key = ("total" + suffix, line)
            odds = {p["designation"]: american_to_decimal(p["price"]) for p in prices}
            if set(odds) != {"over", "under"}:
                continue
        else:
            continue
        raw[match.id][key] = odds
        limit = max((lim.get("amount", 0) for lim in mk.get("limits") or []), default=0)
        limits[match.id][key] = limit

    out = []
    for mid, match in matches.items():
        if mid not in raw:
            continue
        match.fair = {key: fair_odds(odds) for key, odds in raw[mid].items()}
        match.limits = limits[mid]
        out.append(match)
    return out


def fetch_matches(timeout: float = 60.0) -> list[PinMatch]:
    try:
        matchups = _session.get(f"{BASE}/sports/{SOCCER}/matchups", params={"withSpecials": "false"}, timeout=timeout)
        matchups.raise_for_status()
        markets = _session.get(f"{BASE}/sports/{SOCCER}/markets/straight",
                               params={"primaryOnly": "false", "withSpecials": "false"}, timeout=timeout)
        markets.raise_for_status()
        return parse(matchups.json(), markets.json())
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Pinnacle a eșuat: %s", exc)
        return []
