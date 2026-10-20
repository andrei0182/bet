"""Oferta Superbet pentru fotbal (pre-meci și live).

CONFIRMAT (2026-10-20) via curl, același API ca în `andrei0182/live`:
- `v3/ro-RO/events?index=active-prematch|active-live&sports=5` întoarce toate
  meciurile de fotbal din interval (~130-140 pe zi pre-meci); `fixture.utc_date`
  = ora de start UTC, `fixture.event_name` = "Gazde·Oaspeți";
- live: `inplay_stats.home_team_score` / `away_team_score` = golurile,
  `inplay_stats.minutes` = minutul, `inplay_stats_metadata.event_status_label`
  = "1H" în prima repriză, "HT" la pauză, "2H" în a doua;
  `inplay_stats.periods[]` = scorul pe reprize (`num` 1 = prima repriză);
- piețele extinse vin prin endpoint-ul SSE `v3/subscription/ro-RO/events`;
  "Prima repriză - Total goluri" (id 200735) are "Sub/Peste 0.5" etc., atât
  pre-meci cât și live.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

EVENTS_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v3/ro-RO/events"
MARKETS_URL = "https://production-superbet-offer-ro.freetls.fastly.net/v3/subscription/ro-RO/events"
FOOTBALL_SPORT_ID = 5
ODD_STATUS_ACTIVE = 1
FIRST_HALF_LABEL = "1H"
FIRST_HALF_MARKET = "Prima repriză - Total goluri"

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
})
_retry = Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
_session.mount("https://", HTTPAdapter(max_retries=_retry))


@dataclass
class SbMatch:
    event_id: int
    home: str
    away: str
    kickoff_utc: Optional[dt.datetime]
    status: str = ""  # "STARTED" / "FINISHED" / "" pre-meci
    label: str = ""  # "1H", "HT", "2H", ...
    minute: Optional[int] = None
    home_goals: int = 0
    away_goals: int = 0
    # scorul primei reprize din `periods` (None dacă lipsește)
    fh_home: Optional[int] = None
    fh_away: Optional[int] = None

    @property
    def url(self) -> str:
        return f"https://superbet.ro/cote/fotbal/{self.event_id}"

    @property
    def goals(self) -> int:
        return self.home_goals + self.away_goals

    @property
    def first_half_over(self) -> bool:
        """Prima repriză s-a terminat. CONFIRMAT (2026-10-20, PSG–Barcelona): în
        primul minut după start meciul e deja "STARTED", dar fără
        `event_status_label` -- asta nu înseamnă că s-a trecut de prima repriză."""
        return self.status == "FINISHED" or (self.status == "STARTED" and self.label not in ("", FIRST_HALF_LABEL))

    def first_half_score(self) -> Optional[tuple[int, int]]:
        """Scorul primei reprize: din `periods` dacă există, altfel scorul
        curent cât timp meciul e încă în prima repriză."""
        if self.fh_home is not None and self.fh_away is not None:
            return self.fh_home, self.fh_away
        if self.label == FIRST_HALF_LABEL:
            return self.home_goals, self.away_goals
        return None


def _int(value) -> Optional[int]:
    m = re.match(r"\d+", str(value or ""))  # "45+2" -> 45
    return int(m.group()) if m else None


def _utc(value: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None


def parse_event(event: dict) -> SbMatch:
    fixture = event.get("fixture", {})
    home, _, away = fixture.get("event_name", "").partition("·")
    stats = event.get("inplay_stats") or {}
    meta = event.get("inplay_stats_metadata") or {}
    first = next((p for p in stats.get("periods") or [] if str(p.get("num")) == "1"), None) or {}
    return SbMatch(
        event_id=event.get("event_id"),
        home=home.strip(),
        away=away.strip(),
        kickoff_utc=_utc(fixture.get("utc_date", "")),
        status=meta.get("status", ""),
        label=meta.get("event_status_label", ""),
        minute=_int(stats.get("minutes")),
        home_goals=_int(stats.get("home_team_score")) or 0,
        away_goals=_int(stats.get("away_team_score")) or 0,
        fh_home=_int(first.get("home_team_score")),
        fh_away=_int(first.get("away_team_score")),
    )


def fetch_matches(index: str, start: dt.date, end: dt.date, timeout: float = 20.0) -> list[SbMatch]:
    """Meciurile de fotbal din `index` ("active-prematch" / "active-live"),
    de la `start` până la `end` exclusiv (zile UTC)."""
    params = {
        "startDate": f"{start.isoformat()}T00:00:00.000Z",
        "endDate": f"{end.isoformat()}T00:00:00.000Z",
        "index": index,
        "sports": FOOTBALL_SPORT_ID,
    }
    try:
        resp = _session.get(EVENTS_URL, params=params, timeout=timeout)
        resp.raise_for_status()
        return [parse_event(e) for e in resp.json().get("events", [])]
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Superbet %s a eșuat: %s", index, exc)
        return []


def fetch_event_markets(event_id: int, timeout: float = 20.0, max_bytes: int = 20_000_000) -> Optional[list[dict]]:
    """Toate piețele unui meci, din prima linie "data:[...]" a stream-ului SSE
    (stream-ul nu se închide singur). CONFIRMAT (2026-10-20): la meciurile
    mari (ex. Liga Campionilor) linia are peste 2 MB."""
    try:
        resp = _session.get(MARKETS_URL, params={"events": str(event_id)}, timeout=timeout, stream=True)
    except requests.RequestException as exc:
        logger.warning("Piețele meciului %s: %s", event_id, exc)
        return None
    buf = bytearray()
    try:
        for chunk in resp.iter_content(chunk_size=16384):
            buf += chunk
            if b"\n" in chunk or len(buf) > max_bytes:
                break
    except Exception as exc:  # stream întrerupt: parsăm ce avem
        logger.debug("Piețele meciului %s: stream oprit: %s", event_id, exc)
    finally:
        resp.close()
    line = bytes(buf).split(b"\n", 1)[0].decode("utf-8", errors="replace")
    if line.startswith("data:"):
        line = line[len("data:"):]
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        logger.warning("Piețele meciului %s: JSON incomplet", event_id)
        return None
    return data[0].get("markets", []) if data else None


def market_odds(markets: Optional[list[dict]], market_name: str, outcome: str) -> Optional[float]:
    """Cota activă a lui `outcome` (ex. "Peste 0.5") din piața cu numele exact
    `market_name`; None dacă lipsește sau e suspendată."""
    for market in markets or []:
        if market.get("name") != market_name:
            continue
        for odd in market.get("odds") or []:
            if (odd.get("metadata") or {}).get("name") == outcome and odd.get("status", ODD_STATUS_ACTIVE) == ODD_STATUS_ACTIVE:
                return odd.get("price")
    return None


def first_half_over05(event_id: int) -> Optional[float]:
    return market_odds(fetch_event_markets(event_id), FIRST_HALF_MARKET, "Peste 0.5")


# ============================================================
# Potrivirea numelor BetExplorer -> Superbet (aceeași logică ca în
# andrei0182/live, livemon/football.py): cel puțin jumătate din cuvintele
# specifice ale fiecărei echipe, aceeași categorie (juniori / fete), plus ora
# de start apropiată.
# ============================================================

_STOPWORDS = {
    "fc", "cf", "sc", "ac", "afc", "fk", "sk", "nk", "club", "city", "united", "utd", "town",
    "real", "sporting", "athletic", "atletico", "dinamo", "dynamo", "union", "u19", "u20",
    "u21", "u23", "women", "reserves",
}
_YOUTH = re.compile(r"^u(1[5-9]|2[0-3])$")
_WOMEN = {"f", "w", "women", "fem", "feminin"}
# echipe secunde: "Defensa y Justicia (R)", "Suduva B", "Jong Ajax II"
_RESERVES = {"r", "res", "reserve", "reserves", "b", "ii"}


def _words(name: str) -> list[str]:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", ascii_name) if t]


def _tokens(name: str) -> set[str]:
    return {t for t in _words(name) if len(t) >= 3 and t not in _STOPWORDS and not _YOUTH.match(t)}


def _category(name: str) -> tuple[frozenset, bool, bool]:
    """(vârstele de juniori, echipă de fete, echipă secundă) -- trebuie să coincidă."""
    words = _words(name)
    return (frozenset(w for w in words if _YOUTH.match(w)), any(w in _WOMEN for w in words),
            any(w in _RESERVES for w in words))


def team_score(name: str, sb_name: str) -> float:
    if _category(name) != _category(sb_name):
        return 0.0
    wanted = _tokens(name)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(sb_name)) / len(wanted)


def find_match(home: str, away: str, kickoff_utc: dt.datetime, matches: list[SbMatch],
               max_diff: dt.timedelta = dt.timedelta(minutes=30)) -> Optional[SbMatch]:
    best, best_score = None, 0.0
    for m in matches:
        if m.kickoff_utc is not None and abs(m.kickoff_utc - kickoff_utc) > max_diff:
            continue
        h, a = team_score(home, m.home), team_score(away, m.away)
        if h >= 0.5 and a >= 0.5 and h + a > best_score:
            best, best_score = m, h + a
    return best
