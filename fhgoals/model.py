"""Probabilitatea de gol în prima repriză, din istoricul celor două echipe.

Pentru fiecare echipă se iau ultimele `last_n` meciuri (acasă și în
deplasare) dinaintea meciului:
- `fh_rate`: în ce parte din ele s-a marcat în prima repriză (oricine);
- `scored` / `conceded`: media golurilor marcate / primite în prima repriză.

Estimarea echipelor e media a două calcule:
- frecvența: media celor două `fh_rate`;
- Poisson: λ = (marcate gazde + primite oaspeți) / 2 + (marcate oaspeți +
  primite gazde) / 2, P = 1 - e^(-λ).
Probabilitatea finală e media dintre estimarea echipelor și rata de gol în
prima repriză a ligii (ultimele `LEAGUE_LAST_N` meciuri, trasă spre media
generală când liga are puține meciuri).

Backtest pe 21 de zile (2026-09-29 – 2026-10-20, 8213 meciuri, media generală
73%): meciurile cu P >= 80% au avut gol în R1 în 80% din cazuri, cele cu
P >= 85% în 81%. Doar echipele (fără ligă) supraestimau: 85%+ -> 80% real.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

from .history import Fixture

# Competiții continentale / mondiale: echipele din ele se leagă de țara lor
# din campionatul intern (când numele apare într-o singură țară).
LEAGUE_LAST_N = 60
LEAGUE_PRIOR_WEIGHT = 10  # câte meciuri „virtuale” cu media generală se adaugă la rata ligii
INTERNATIONAL = {"europe", "world", "africa", "asia", "south-america", "north-central-america", "oceania"}


def excluded_league(league: str) -> bool:
    """Amicalele nu spun mare lucru despre forma unei echipe."""
    return "friendly" in league.lower()


@dataclass
class TeamForm:
    n: int
    fh_rate: float
    scored: float
    conceded: float


def fh_probability(home: TeamForm, away: TeamForm, league_rate: float) -> float:
    lam = (home.scored + away.conceded) / 2 + (away.scored + home.conceded) / 2
    poisson = 1 - math.exp(-lam)
    freq = (home.fh_rate + away.fh_rate) / 2
    return ((poisson + freq) / 2 + league_rate) / 2


class TeamIndex:
    """Meciurile fiecărei echipe, ordonate după dată, cheia fiind (țară, nume)."""

    def __init__(self, history: Iterable[Fixture]):
        rows = [fx for fx in history if fx.fh_goals is not None and not excluded_league(fx.league)]
        self._countries: dict[str, set[str]] = defaultdict(set)
        for fx in rows:
            if fx.country not in INTERNATIONAL:
                self._countries[fx.home].add(fx.country)
                self._countries[fx.away].add(fx.country)

        # cheie -> [(kickoff, marcate R1, primite R1)]
        self._games: dict[tuple[str, str], list[tuple[dt.datetime, int, int]]] = defaultdict(list)
        for fx in rows:
            self._games[self.key(fx.country, fx.home)].append((fx.kickoff_utc, fx.ht_home, fx.ht_away))
            self._games[self.key(fx.country, fx.away)].append((fx.kickoff_utc, fx.ht_away, fx.ht_home))
        for games in self._games.values():
            games.sort(key=lambda g: g[0])

        # liga -> [(kickoff, s-a marcat în R1)]
        self._leagues: dict[str, list[tuple[dt.datetime, bool]]] = defaultdict(list)
        for fx in rows:
            self._leagues[fx.league].append((fx.kickoff_utc, fx.fh_goals > 0))
        for games in self._leagues.values():
            games.sort(key=lambda g: g[0])
        self.base_rate = sum(fx.fh_goals > 0 for fx in rows) / len(rows) if rows else 0.73

    def key(self, country: str, team: str) -> tuple[str, str]:
        if country not in INTERNATIONAL:
            return country, team
        countries = self._countries.get(team, set())
        return (next(iter(countries)), team) if len(countries) == 1 else ("*", team)

    def form(self, country: str, team: str, before: dt.datetime, last_n: int = 10) -> Optional[TeamForm]:
        games = self._games.get(self.key(country, team))
        if not games:
            return None
        end = bisect.bisect_left(games, before, key=lambda g: g[0])
        recent = games[max(0, end - last_n):end]
        if not recent:
            return None
        n = len(recent)
        return TeamForm(
            n=n,
            fh_rate=sum(1 for _, s, c in recent if s + c > 0) / n,
            scored=sum(s for _, s, _ in recent) / n,
            conceded=sum(c for _, _, c in recent) / n,
        )


    def league_rate(self, league: str, before: dt.datetime) -> float:
        games = self._leagues.get(league, [])
        end = bisect.bisect_left(games, before, key=lambda g: g[0])
        recent = games[max(0, end - LEAGUE_LAST_N):end]
        hits = sum(1 for _, goal in recent if goal)
        return (hits + self.base_rate * LEAGUE_PRIOR_WEIGHT) / (len(recent) + LEAGUE_PRIOR_WEIGHT)


@dataclass
class Prediction:
    fixture: Fixture
    probability: float  # 0..1
    home: TeamForm
    away: TeamForm


def predict(
    index: TeamIndex,
    fixture: Fixture,
    last_n: int = 10,
    min_matches: int = 5,
) -> Optional[Prediction]:
    """None dacă meciul e amical sau una dintre echipe are sub `min_matches`
    meciuri în istoric."""
    if excluded_league(fixture.league):
        return None
    home = index.form(fixture.country, fixture.home, fixture.kickoff_utc, last_n)
    away = index.form(fixture.country, fixture.away, fixture.kickoff_utc, last_n)
    if home is None or away is None or home.n < min_matches or away.n < min_matches:
        return None
    league = index.league_rate(fixture.league, fixture.kickoff_utc)
    return Prediction(fixture, fh_probability(home, away, league), home, away)


def backtest(history: Iterable[Fixture], since: dt.datetime, last_n: int = 10, min_matches: int = 5,
             buckets: tuple[int, ...] = (70, 75, 80, 85, 90)) -> list[tuple[int, int, int]]:
    """Pentru meciurile de după `since`, cu probabilitatea calculată doar din
    meciurile anterioare: [(prag %, meciuri cu P >= prag, din care cu gol în R1)]."""
    history = list(history)
    index = TeamIndex(history)
    preds = []
    for fx in history:
        if fx.kickoff_utc < since:
            continue
        p = predict(index, fx, last_n, min_matches)
        if p is not None:
            preds.append((p.probability, fx.fh_goals > 0))
    out = []
    for b in buckets:
        sel = [hit for prob, hit in preds if prob * 100 >= b]
        out.append((b, len(sel), sum(sel)))
    return out
