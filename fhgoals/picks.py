"""Jurnalul pronosticurilor „gol în prima repriză” (data/fh_picks.csv)."""
from __future__ import annotations

import csv
import datetime as dt
import os
from dataclasses import asdict, dataclass, fields
from typing import Optional
from zoneinfo import ZoneInfo

RO_TZ = ZoneInfo("Europe/Bucharest")
PENDING, GOAL, NO_GOAL, VOID = "pending", "goal", "no_goal", "void"


@dataclass
class Pick:
    date: str  # ziua din România, AAAA-LL-ZZ
    kickoff_local: str  # "HH:MM", ora României
    league: str
    home: str
    away: str
    probability: float  # procente, ex. 84.2
    home_n: int
    away_n: int
    match_id: str  # BetExplorer
    superbet_id: str
    odds_fh05: str = ""  # cota pre-meci Superbet „Prima repriză Peste 0.5”
    result: str = PENDING
    ht_score: str = ""
    checked_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.date}|{self.match_id}"

    def kickoff_utc(self) -> Optional[dt.datetime]:
        try:
            local = dt.datetime.strptime(f"{self.date} {self.kickoff_local}", "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        return local.replace(tzinfo=RO_TZ).astimezone(dt.timezone.utc)


_FIELDS = [f.name for f in fields(Pick)]


def load_picks(path: str) -> list[Pick]:
    if not os.path.exists(path):
        return []
    picks = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            values = {k: row.get(k) or "" for k in _FIELDS}
            try:
                values["probability"] = float(values["probability"])
                values["home_n"] = int(values["home_n"])
                values["away_n"] = int(values["away_n"])
                picks.append(Pick(**values))
            except (TypeError, ValueError):
                continue
    return picks


def save_picks(path: str, picks: list[Pick]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for p in sorted(picks, key=lambda p: (p.date, p.kickoff_local, p.home)):
            writer.writerow(asdict(p))
