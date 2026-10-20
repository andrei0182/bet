"""Istoricul de rezultate (cu scorul la pauză) de pe BetExplorer.

CONFIRMAT (2026-10-20) via curl: pagina zilnică de rezultate
`/football/results/?year=&month=&day=` merge cu un GET simplu (fără Selenium)
și conține toate meciurile zilei, ~800-3500 pe zi:
- antet de ligă: `<a href="/football/<țară>/<ligă>/" class="table-main__tournament">`
  cu numele "Țară: Ligă" după `</i>`;
- rând de meci: `<tr data-dt="Z,L,AAAA,H,M" ... data-dt-now="...">`, link
  "Gazde - Oaspeți" spre `/football/.../<slug>/<match_id>/`;
- meci terminat: `td.table-main__result` ("0:4") și `td.table-main__partial`
  ("(0:1, 0:3)" -- prima pereche e scorul primei reprize);
- meci în desfășurare: atributul `data-live` pe `<tr>`; meci viitor: fără
  rezultat, doar cote.
`data-dt` e în ora serverului (UTC+1 la verificare). Diferența față de UTC se
calculează din `data-dt-now` comparat cu antetul `Date` al răspunsului.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import logging
import os
import re
from dataclasses import asdict, dataclass, fields
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://www.betexplorer.com"
DAY_URL = BASE_URL + "/football/results/?year={y}&month={m:02d}&day={d:02d}"

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
})
_retry = Retry(total=6, backoff_factor=2.0, status_forcelist=[429, 500, 502, 503, 504], respect_retry_after_header=True)
_session.mount("https://", HTTPAdapter(max_retries=_retry))

_LEAGUE_RE = re.compile(
    r'<a href="/football/([^/"]+)/[^"]*" class="table-main__tournament">.*?</i>([^<]+)</a>', re.S
)
_ROW_RE = re.compile(r'<tr([^>]*\bdata-dt="[^"]*"[^>]*)>(.*?)</tr>', re.S)
_DT_RE = re.compile(r'data-dt="(\d+),(\d+),(\d+),(\d+),(\d+)"')
_DT_NOW_RE = re.compile(r'data-dt-now="(\d+),(\d+),(\d+),(\d+),(\d+)"')
_LINK_RE = re.compile(r'<td class="table-main__tt">.*?<a href="(/football/[^"]+)"[^>]*>(.*?)</a>', re.S)
_RESULT_RE = re.compile(r'class="table-main__result">(.*?)</td>', re.S)
_PARTIAL_RE = re.compile(r'class="table-main__partial"[^>]*>([^<]*)<')
_SCORE_RE = re.compile(r"(\d+)\s*:\s*(\d+)")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Fixture:
    """Un meci de pe pagina zilnică BetExplorer."""

    match_id: str
    kickoff_utc: dt.datetime
    country: str  # primul segment din URL-ul ligii: "england", "europe", "world"...
    league: str  # "England: Premier League"
    home: str
    away: str
    status: str  # "finished" / "live" / "scheduled"
    ht_home: Optional[int] = None
    ht_away: Optional[int] = None
    ft_home: Optional[int] = None
    ft_away: Optional[int] = None

    @property
    def fh_goals(self) -> Optional[int]:
        if self.ht_home is None or self.ht_away is None:
            return None
        return self.ht_home + self.ht_away


def _text(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub("", fragment)).strip()


def _dt(match: re.Match) -> dt.datetime:
    d, m, y, h, mi = (int(x) for x in match.groups())
    return dt.datetime(y, m, d, h, mi)


def server_offset(page: str, date_header: Optional[str]) -> dt.timedelta:
    """Ora serverului minus UTC, rotunjită la oră (pagina poate fi din cache
    câteva minute). Implicit UTC+1, cât s-a văzut la verificare."""
    now_match = _DT_NOW_RE.search(page)
    if now_match and date_header:
        try:
            utc_now = parsedate_to_datetime(date_header).astimezone(dt.timezone.utc).replace(tzinfo=None)
            hours = round((_dt(now_match) - utc_now).total_seconds() / 3600)
            if -12 <= hours <= 14:
                return dt.timedelta(hours=hours)
        except (TypeError, ValueError):
            pass
    return dt.timedelta(hours=1)


def parse_day_page(page: str, offset: dt.timedelta) -> list[Fixture]:
    # Antetele de ligă și rândurile de meci, în ordinea din pagină.
    events = [(m.start(), "league", m) for m in _LEAGUE_RE.finditer(page)]
    events += [(m.start(), "row", m) for m in _ROW_RE.finditer(page)]
    events.sort(key=lambda e: e[0])

    fixtures: list[Fixture] = []
    country = league = ""
    for _, kind, m in events:
        if kind == "league":
            country, league = m.group(1), html.unescape(m.group(2)).strip()
            continue
        attrs, body = m.group(1), m.group(2)
        dt_match, link = _DT_RE.search(attrs), _LINK_RE.search(body)
        if not dt_match or not link or not league:
            continue
        home, sep, away = _text(link.group(2)).partition(" - ")
        if not sep:
            continue
        match_id = link.group(1).rstrip("/").rsplit("/", 1)[-1]
        fixture = Fixture(
            match_id=match_id,
            kickoff_utc=(_dt(dt_match) - offset).replace(tzinfo=dt.timezone.utc),
            country=country,
            league=league,
            home=home.strip(),
            away=away.strip(),
            status="scheduled",
        )
        result = _RESULT_RE.search(body)
        if "data-live=" in attrs:
            fixture.status = "live"
        elif result:
            ft = _SCORE_RE.fullmatch(_text(result.group(1)))
            partial = _PARTIAL_RE.search(body)
            ht = _SCORE_RE.search(partial.group(1)) if partial else None
            if not ft:  # POSTP., CANC., AWA. ...
                continue
            fixture.status = "finished"
            fixture.ft_home, fixture.ft_away = int(ft.group(1)), int(ft.group(2))
            if ht:
                fixture.ht_home, fixture.ht_away = int(ht.group(1)), int(ht.group(2))
        fixtures.append(fixture)
    return fixtures


def fetch_day(day: dt.date, timeout: float = 30.0) -> list[Fixture]:
    """Toate meciurile de pe pagina BetExplorer a zilei `day`. Ridică
    requests.RequestException dacă pagina nu se poate citi."""
    resp = _session.get(DAY_URL.format(y=day.year, m=day.month, d=day.day), timeout=timeout)
    resp.raise_for_status()
    return parse_day_page(resp.text, server_offset(resp.text, resp.headers.get("Date")))


# ============================================================
# Istoricul salvat pe disc: un CSV cu meciurile terminate care au scorul la
# pauză, plus lista zilelor deja citite (ca să nu le cerem din nou).
# ============================================================

_FIELDS = [f.name for f in fields(Fixture)]


def load_history(path: str) -> dict[str, Fixture]:
    if not os.path.exists(path):
        return {}
    out: dict[str, Fixture] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                out[row["match_id"]] = Fixture(
                    match_id=row["match_id"],
                    kickoff_utc=dt.datetime.fromisoformat(row["kickoff_utc"]),
                    country=row["country"],
                    league=row["league"],
                    home=row["home"],
                    away=row["away"],
                    status=row["status"],
                    ht_home=int(row["ht_home"]),
                    ht_away=int(row["ht_away"]),
                    ft_home=int(row["ft_home"]),
                    ft_away=int(row["ft_away"]),
                )
            except (KeyError, ValueError):
                continue
    return out


def save_history(path: str, history: dict[str, Fixture]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for fx in sorted(history.values(), key=lambda x: x.kickoff_utc):
            row = asdict(fx)
            row["kickoff_utc"] = fx.kickoff_utc.isoformat()
            writer.writerow(row)
    os.replace(tmp, path)


def _load_days(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def update_history(
    history_path: str,
    today: dt.date,
    days: int = 60,
    refresh: int = 2,
) -> dict[str, Fixture]:
    """Completează istoricul cu zilele lipsă din ultimele `days` zile (ultimele
    `refresh` zile se citesc mereu din nou, pentru rezultatele întârziate) și
    șterge ce e mai vechi. Întoarce istoricul (doar meciuri terminate cu scor
    la pauză)."""
    days_path = history_path + ".days"
    history = load_history(history_path)
    done = _load_days(days_path)
    start = today - dt.timedelta(days=days)
    cutoff = dt.datetime.combine(start, dt.time(), tzinfo=dt.timezone.utc)

    for i in range(days, -1, -1):
        day = today - dt.timedelta(days=i)
        if day.isoformat() in done and i > refresh:
            continue
        try:
            fixtures = fetch_day(day)
        except requests.RequestException as exc:
            logger.warning("Nu pot citi rezultatele din %s: %s", day, exc)
            continue
        for fx in fixtures:
            if fx.status == "finished" and fx.fh_goals is not None:
                history[fx.match_id] = fx
        if i > 0:  # ziua de azi nu e completă
            done.add(day.isoformat())
        logger.info("Istoric %s: %d meciuri citite", day, len(fixtures))

    history = {k: v for k, v in history.items() if v.kickoff_utc >= cutoff}
    done = {d for d in done if d >= start.isoformat()}
    save_history(history_path, history)
    with open(days_path, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(done)) + "\n")
    return history
