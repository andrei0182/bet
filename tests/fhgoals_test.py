"""Teste fără rețea pentru botul „gol în prima repriză”.
(Fișierul nu se numește test_*.py: .gitignore exclude acel tipar.)"""
import datetime as dt

from fhgoals.history import Fixture, parse_day_page, server_offset
from fhgoals.model import TeamForm, TeamIndex, fh_probability, predict
from fhgoals.picks import GOAL, NO_GOAL, PENDING, VOID, Pick, load_picks, save_picks
from fhgoals.report import check_results, format_alert, format_evening, select_picks
from fhgoals.superbet import SbMatch, find_match, parse_event

UTC = dt.timezone.utc

PAGE = """
<tr class="js-tournament"><th class="h-text-left" colspan="2"><a href="/football/england/premier-league/" class="table-main__tournament"><i><img src="x.svg" alt="England"></i>England: Premier League</a></th></tr>
<tr data-dt="17,10,2026,13,00" data-def="0" data-dt-now="20,10,2026,16,33">
<td class="table-main__tt"><span class="table-main__time">13:00</span><a href="/football/england/premier-league/arsenal-chelsea/AbC123/">Arsenal - <strong>Chelsea</strong></a></td>
<td class="table-main__result"><a href="/football/england/premier-league/arsenal-chelsea/AbC123/"> <strong>0:4</strong></a></td>
<td class="table-main__partial" colspan="3">(0:1, 0:3)</td>
</tr>
<tr data-dt="17,10,2026,15,00" data-def="0" data-dt-now="20,10,2026,16,33">
<td class="table-main__tt"><span class="table-main__time">15:00</span><a href="/football/england/premier-league/a-b/PoStP1/">Leeds - Fulham</a></td>
<td class="table-main__result"><a href="#">POSTP.</a></td>
<td class="table-main__partial" colspan="3"></td>
</tr>
<tr class="js-tournament"><th class="h-text-left" colspan="2"><a href="/football/europe/champions-league/" class="table-main__tournament"><i></i>Europe: Champions League</a></th></tr>
<tr data-live="LiVe01" data-dt="20,10,2026,15,00" data-def="1" data-dt-now="20,10,2026,16,28">
<td class="table-main__tt"><span class="table-main__time" data-live-cell="time">15:00</span><a href="/football/europe/champions-league/x-y/LiVe01/" data-live-cell="matchlink">PSG - Barcelona</a></td>
<td class="table-main__streams" data-live-cell="score"></td>
</tr>
<tr data-dt="21,10,2026,21,00" data-def="0" data-dt-now="20,10,2026,16,28">
<td class="table-main__tt"><span class="table-main__time">21:00</span><a href="/football/europe/champions-league/a-b/SchEd1/">Arsenal - Real &amp; Co</a></td>
<td class="table-main__odds " data-oid="">&nbsp;</td>
</tr>
"""


def test_parse_day_page():
    fx = parse_day_page(PAGE, dt.timedelta(hours=1))
    assert [f.match_id for f in fx] == ["AbC123", "LiVe01", "SchEd1"]  # amânatul lipsește
    done, live, sched = fx
    assert (done.status, done.country, done.league) == ("finished", "england", "England: Premier League")
    assert (done.home, done.away) == ("Arsenal", "Chelsea")
    assert (done.ht_home, done.ht_away, done.ft_home, done.ft_away) == (0, 1, 0, 4)
    assert done.kickoff_utc == dt.datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
    assert live.status == "live" and live.country == "europe"
    assert sched.status == "scheduled" and sched.away == "Real & Co"


def test_server_offset_from_date_header():
    page = 'data-dt-now="20,10,2026,16,28"'
    assert server_offset(page, "Tue, 20 Oct 2026 15:33:49 GMT") == dt.timedelta(hours=1)
    assert server_offset(page, None) == dt.timedelta(hours=1)
    assert server_offset(page, "Tue, 20 Oct 2026 14:30:00 GMT") == dt.timedelta(hours=2)


def _fx(mid, day, home, away, ht, country="england", league="England: League"):
    return Fixture(mid, dt.datetime(2026, 10, day, 15, tzinfo=UTC), country, league, home, away,
                   "finished", ht[0], ht[1], ht[0], ht[1])


def test_team_form_and_prediction():
    history = [
        _fx("1", 1, "A", "X", (1, 0)),
        _fx("2", 2, "Y", "A", (0, 0)),
        _fx("3", 3, "A", "Z", (2, 1)),
        _fx("4", 4, "B", "X", (0, 1)),
        _fx("5", 5, "Y", "B", (1, 1)),
        _fx("6", 6, "B", "Z", (0, 0)),
        _fx("7", 7, "A", "B", (0, 0), league="World: Club Friendly"),  # amical: ignorat
    ]
    index = TeamIndex(history)
    before = dt.datetime(2026, 10, 10, tzinfo=UTC)
    a = index.form("england", "A", before)
    assert a.n == 3 and a.fh_rate == 2 / 3 and a.scored == 1 and a.conceded == 1 / 3
    assert index.form("england", "A", dt.datetime(2026, 10, 2, tzinfo=UTC)).n == 1  # doar meciurile de dinainte

    # competiție europeană: echipa e legată de țara ei
    assert index.key("europe", "A") == ("england", "A")
    assert index.key("europe", "Necunoscut") == ("*", "Necunoscut")

    upcoming = Fixture("9", before, "europe", "Europe: Cup", "A", "B", "scheduled")
    assert predict(index, upcoming, min_matches=4) is None  # prea puține meciuri
    p = predict(index, upcoming, min_matches=3)
    assert p is not None and 0 < p.probability < 1


def test_fh_probability_bounds():
    zero = TeamForm(n=10, fh_rate=0.0, scored=0.0, conceded=0.0)
    high = TeamForm(n=10, fh_rate=1.0, scored=2.0, conceded=2.0)
    assert fh_probability(zero, zero, 0.0) == 0.0
    assert fh_probability(high, high, 1.0) > 0.95
    assert fh_probability(zero, zero, 0.8) == 0.4  # liga contează jumătate


def test_superbet_parse_and_match():
    event = {
        "event_id": 15308070,
        "fixture": {"event_name": "Wealdstone·Nottingham Forest U21", "utc_date": "2026-10-20T19:00:00Z"},
        "inplay_stats": {"home_team_score": "0", "away_team_score": "0", "minutes": "21"},
        "inplay_stats_metadata": {"status": "STARTED", "event_status_label": "1H"},
    }
    m = parse_event(event)
    assert (m.home, m.away, m.minute, m.label, m.goals) == ("Wealdstone", "Nottingham Forest U21", 21, "1H", 0)
    kickoff = dt.datetime(2026, 10, 20, 19, tzinfo=UTC)
    assert find_match("Wealdstone", "Nottingham U21", kickoff, [m]) is m
    assert find_match("Wealdstone", "Nottingham", kickoff, [m]) is None  # altă categorie (U21)
    assert find_match("Wealdstone", "Nottingham U21", kickoff + dt.timedelta(hours=2), [m]) is None


def _pick(**kw):
    base = dict(date="2026-10-20", kickoff_local="21:00", league="L", home="A", away="B", probability=84.0,
                home_n=10, away_n=10, match_id="m1", superbet_id="1")
    base.update(kw)
    return Pick(**base)


def test_picks_roundtrip(tmp_path):
    path = str(tmp_path / "p.csv")
    save_picks(path, [_pick(), _pick(match_id="m2", odds_fh05="1.25")])
    loaded = load_picks(path)
    assert [p.match_id for p in loaded] == ["m1", "m2"]
    assert loaded[0].probability == 84.0 and loaded[1].odds_fh05 == "1.25" and loaded[0].result == PENDING
    assert loaded[0].kickoff_utc() == dt.datetime(2026, 10, 20, 18, tzinfo=UTC)  # 21:00 ora României (EEST)


def test_check_results():
    picks = [_pick(match_id="g"), _pick(match_id="n"), _pick(match_id="old", date="2026-10-17"), _pick(match_id="wait")]
    history = {"g": _fx("g", 20, "A", "B", (1, 0)), "n": _fx("n", 20, "A", "B", (0, 0))}
    now = dt.datetime(2026, 10, 20, 22, tzinfo=UTC)
    changed = check_results(picks, history, now)
    assert [p.match_id for p in changed] == ["g", "n", "old"]
    assert [p.result for p in picks] == [GOAL, NO_GOAL, VOID, PENDING]
    assert picks[0].ht_score == "1-0"


def test_select_picks_needs_superbet_and_threshold():
    history = []
    for d in range(1, 11):
        history.append(_fx(f"a{d}", d, "Arsenal", f"O{d}", (1, 1)))
        history.append(_fx(f"b{d}", d, f"P{d}", "Burnley", (1, 0)))
        history.append(_fx(f"c{d}", d, "Chelsea", f"Q{d}", (0, 0)))
    index = TeamIndex(history)
    kickoff = dt.datetime(2026, 10, 20, 18, tzinfo=UTC)
    fixtures = [
        Fixture("ab", kickoff, "england", "England: League", "Arsenal", "Burnley", "scheduled"),
        Fixture("cb", kickoff, "england", "England: League", "Chelsea", "Burnley", "scheduled"),
        Fixture("ac", kickoff, "england", "England: League", "Arsenal", "Chelsea", "scheduled"),
    ]
    sb = [SbMatch(1, "Arsenal", "Burnley", kickoff), SbMatch(2, "Chelsea", "Burnley", kickoff)]  # A-C nu e la Superbet
    now = dt.datetime(2026, 10, 20, 8, tzinfo=UTC)
    chosen = select_picks(fixtures, index, sb, dt.date(2026, 10, 20), now, min_pct=60)
    assert [(p.fixture.match_id, s.event_id) for p, s in chosen] == [("ab", 1)]


def test_messages():
    p = _pick(result=GOAL, ht_score="1-0", odds_fh05="1.25")
    m = SbMatch(1, "A", "B", None, "STARTED", "1H", 20)
    alert = format_alert(p, m, 1.9)
    assert "minutul 20" in alert and "1.9" in alert and "84%" in alert and "superbet.ro/cote/fotbal/1" in alert
    text = format_evening(dt.date(2026, 10, 20), [p, _pick(match_id="x", result=NO_GOAL)], [p],
                          [{"key": p.key, "date": p.date}])
    assert "✅ A vs B 1-0 la pauză (84%)" in text and "Azi: 1/2 (50%)" in text and "Alerte" in text
