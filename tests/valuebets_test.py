"""Teste fără rețea pentru scannerul de valoare.
(Fișierul nu se numește test_*.py: .gitignore exclude acel tipar.)"""
import datetime as dt

import pytest

from fhgoals.superbet import SbMatch
from valuebets.pinnacle import PinMatch, american_to_decimal, fair_odds, parse
from valuebets.scanner import (
    LOST,
    PENDING,
    VOID,
    WON,
    ValueBet,
    find_value,
    format_evening,
    format_new,
    load_bets,
    pair_matches,
    save_bets,
    settle,
    superbet_markets,
)

UTC = dt.timezone.utc
KICKOFF = dt.datetime(2026, 10, 20, 19, 0, tzinfo=UTC)


def test_odds_conversion_and_fair():
    assert american_to_decimal(150) == 2.5
    assert american_to_decimal(-200) == 1.5
    fair = fair_odds({"over": 1.9, "under": 1.9})
    assert fair == pytest.approx({"over": 2.0, "under": 2.0})
    three = fair_odds({"home": 2.0, "draw": 3.4, "away": 4.0})
    assert sum(1 / v for v in three.values()) == pytest.approx(1.0)


def test_parse_pinnacle():
    matchups = [
        {"id": 1, "parentId": None, "isLive": False, "startTime": "2026-10-20T19:00:00Z",
         "league": {"name": "England - Premier League"},
         "participants": [{"alignment": "home", "name": "Arsenal"}, {"alignment": "away", "name": "Chelsea"}]},
        {"id": 2, "parentId": 1, "startTime": "2026-10-20T19:00:00Z",  # cornere: ignorat
         "participants": [{"alignment": "home", "name": "Arsenal (Corners)"}, {"alignment": "away", "name": "Chelsea (Corners)"}]},
    ]
    markets = [
        {"matchupId": 1, "period": 0, "status": "open", "type": "moneyline", "limits": [{"amount": 3000}],
         "prices": [{"designation": "home", "price": 100}, {"designation": "draw", "price": 250}, {"designation": "away", "price": 300}]},
        {"matchupId": 1, "period": 1, "status": "open", "type": "total", "limits": [{"amount": 500}],
         "prices": [{"designation": "over", "points": 1.5, "price": 150}, {"designation": "under", "points": 1.5, "price": -170}]},
        {"matchupId": 1, "period": 0, "status": "open", "type": "total",  # linie asiatică: ignorată
         "prices": [{"designation": "over", "points": 2.25, "price": -105}, {"designation": "under", "points": 2.25, "price": -105}]},
        {"matchupId": 1, "period": 0, "status": "open", "type": "spread", "prices": []},
    ]
    [m] = parse(matchups, markets)
    assert (m.home, m.away, m.league, m.start_utc) == ("Arsenal", "Chelsea", "England - Premier League", KICKOFF)
    assert set(m.fair) == {("1x2", 0.0), ("total_h1", 1.5)}
    assert m.limits[("1x2", 0.0)] == 3000


def _sb_market(name, odds):
    return {"name": name, "odds": [
        {"price": p, "status": 1, "metadata": {"name": n, "specifiers": ({"total": t} if t else {})}}
        for n, p, t in odds
    ]}


def test_superbet_markets():
    markets = [
        _sb_market("Final", [("1", 2.1, None), ("X", 3.3, None), ("2", 3.6, None)]),
        _sb_market("Prima repriză - 1X2", [("Arsenal", 2.8, None), ("Egal", 2.1, None), ("Chelsea", 4.5, None)]),
        _sb_market("Total goluri", [("Sub 2.5", 1.9, "2.5"), ("Peste 2.5", 1.85, "2.5")]),
        _sb_market("Total goluri Arsenal", [("Sub 0.5", 5.0, "0.5")]),  # alt tip de piață: ignorat
    ]
    out = superbet_markets(markets, "Arsenal")
    assert out[("1x2", 0.0)] == {"home": 2.1, "draw": 3.3, "away": 3.6}
    assert out[("1x2_h1", 0.0)] == {"home": 2.8, "draw": 2.1, "away": 4.5}
    assert out[("total", 2.5)] == {"under": 1.9, "over": 1.85}
    assert len(out) == 3


def test_find_value_filters():
    pin = PinMatch(1, "Arsenal", "Chelsea", "EPL", KICKOFF,
                   fair={("1x2", 0.0): {"home": 2.0, "draw": 3.5, "away": 4.5}, ("total", 2.5): {"over": 1.9, "under": 2.1}},
                   limits={("1x2", 0.0): 3000, ("total", 2.5): 100})
    sb = SbMatch(9, "Arsenal", "Chelsea", KICKOFF)
    offered = {("1x2", 0.0): {"home": 2.1, "draw": 3.4, "away": 5.0}, ("total", 2.5): {"over": 2.2, "under": 1.8}}
    bets = find_value(pin, sb, offered, min_edge=3, min_fair=1.3, max_fair=4.0, min_limit=250)
    # home +5% trece; away e peste cota corectă maximă (4.5 > 4.0); totalul are limita Pinnacle prea mică
    assert [(b.market, b.selection, b.edge) for b in bets] == [("1x2", "home", 5.0)]
    assert bets[0].kickoff_local == "22:00" and bets[0].date == "2026-10-20"  # ora României


def test_pair_matches_names_and_reserves():
    pins = [PinMatch(1, "Worcester City", "Chorley", "", KICKOFF),
            PinMatch(2, "Defensa y Justicia", "Atletico de Rafaela", "", KICKOFF)]
    sbs = [SbMatch(10, "Worcester", "Chorley", KICKOFF),
           SbMatch(11, "Defensa y Justicia (R)", "Atletico Rafaela (R)", KICKOFF)]
    assert [(p.id, s.event_id) for p, s in pair_matches(pins, sbs)] == [(1, 10)]


def _bet(**kw):
    base = dict(date="2026-10-20", kickoff_local="22:00", kickoff_utc=KICKOFF.isoformat(), league="EPL",
                home="Arsenal", away="Chelsea", market="1x2", line=0.0, selection="home", sb_odds=2.1,
                fair_odds=2.0, edge=5.0, pin_limit=3000, superbet_id="9", pinnacle_id="1", close_fair=1.95)
    base.update(kw)
    return ValueBet(**base)


def test_settle():
    now = KICKOFF + dt.timedelta(hours=3)
    done = SbMatch(9, "Arsenal", "Chelsea", KICKOFF, "FINISHED", "END", None, 2, 1, 0, 1)
    home = _bet()
    assert settle(home, done, now) and home.result == WON and home.profit == pytest.approx(1.1) and home.score == "2-1"
    h1 = _bet(market="1x2_h1")
    assert settle(h1, done, now) and h1.result == LOST and h1.profit == -1 and h1.score == "0-1"
    over = _bet(market="total", line=2.5, selection="over")
    assert settle(over, done, now) and over.result == WON
    pending = _bet()
    assert not settle(pending, None, now) and pending.result == PENDING
    assert settle(pending, None, KICKOFF + dt.timedelta(hours=49)) and pending.result == VOID


def test_bets_roundtrip_and_messages(tmp_path):
    path = str(tmp_path / "v.csv")
    won = _bet(result=WON, profit=1.1, score="2-1")
    save_bets(path, [won, _bet(selection="away", sb_odds=4.0)])
    loaded = sorted(load_bets(path), key=lambda b: b.selection != "home")
    assert [b.selection for b in loaded] == ["home", "away"] and loaded[0].profit == 1.1
    assert loaded[0].clv == pytest.approx((2.1 / 1.95 - 1) * 100)

    text = format_new([loaded[0]])
    assert "Arsenal câștigă @2.1 (corect 2.00, +5.0%)" in text
    evening = format_evening(dt.date(2026, 10, 20), [loaded[0]], loaded)
    assert "✅ Arsenal vs Chelsea (2-1)" in evening and "ROI +110.0%" in evening and "CLV mediu +7.7%" in evening
