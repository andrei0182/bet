"""Alegerea pronosticurilor, verificarea rezultatelor și textele pentru Telegram."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from .history import Fixture
from .model import Prediction, TeamIndex, predict
from .picks import GOAL, NO_GOAL, PENDING, RO_TZ, VOID, Pick
from .superbet import SbMatch, find_match

# După atât timp de la ora de start, un pronostic fără scor la pauză în
# istoric (meci amânat / anulat) nu mai așteaptă rezultat.
VOID_AFTER = dt.timedelta(hours=36)


def local_day(kickoff_utc: dt.datetime) -> dt.date:
    return kickoff_utc.astimezone(RO_TZ).date()


def select_picks(
    fixtures: list[Fixture],
    index: TeamIndex,
    superbet: list[SbMatch],
    day: dt.date,
    now: dt.datetime,
    min_pct: float = 80.0,
    max_picks: int = 10,
    last_n: int = 10,
    min_matches: int = 5,
) -> list[tuple[Prediction, SbMatch]]:
    """Meciurile neîncepute din ziua `day` (ora României), cu probabilitatea
    >= `min_pct` și prezente în oferta Superbet, cele mai probabile primele."""
    preds: list[Prediction] = []
    seen = set()
    for fx in fixtures:
        if fx.status != "scheduled" or fx.match_id in seen or fx.kickoff_utc <= now or local_day(fx.kickoff_utc) != day:
            continue
        seen.add(fx.match_id)
        p = predict(index, fx, last_n, min_matches)
        if p is not None and p.probability * 100 >= min_pct:
            preds.append(p)
    preds.sort(key=lambda p: p.probability, reverse=True)

    out: list[tuple[Prediction, SbMatch]] = []
    used: set[int] = set()
    for p in preds:
        sb = find_match(p.fixture.home, p.fixture.away, p.fixture.kickoff_utc, superbet)
        if sb is None or sb.event_id in used:
            continue
        used.add(sb.event_id)
        out.append((p, sb))
        if len(out) >= max_picks:
            break
    return out


def to_pick(pred: Prediction, sb: SbMatch, odds_fh05: Optional[float]) -> Pick:
    fx = pred.fixture
    local = fx.kickoff_utc.astimezone(RO_TZ)
    return Pick(
        date=local.date().isoformat(),
        kickoff_local=local.strftime("%H:%M"),
        league=fx.league,
        home=fx.home,
        away=fx.away,
        probability=round(pred.probability * 100, 1),
        home_n=pred.home.n,
        away_n=pred.away.n,
        match_id=fx.match_id,
        superbet_id=str(sb.event_id),
        odds_fh05="" if odds_fh05 is None else str(odds_fh05),
    )


def check_results(picks: list[Pick], history: dict[str, Fixture], now: dt.datetime) -> list[Pick]:
    """Completează rezultatul pronosticurilor `pending` din istoric. Întoarce
    pronosticurile care s-au schimbat."""
    changed = []
    for p in picks:
        if p.result != PENDING:
            continue
        fx = history.get(p.match_id)
        if fx is not None and fx.fh_goals is not None:
            p.result = GOAL if fx.fh_goals > 0 else NO_GOAL
            p.ht_score = f"{fx.ht_home}-{fx.ht_away}"
        else:
            kickoff = p.kickoff_utc()
            if kickoff is None or now <= kickoff + VOID_AFTER:
                continue
            p.result = VOID
        p.checked_at = now.astimezone(RO_TZ).date().isoformat()
        changed.append(p)
    return changed


def _fmt_day(day: str) -> str:
    return dt.date.fromisoformat(day).strftime("%d.%m")


def _pct(hits: int, total: int) -> str:
    return f"{hits}/{total} ({hits * 100 / total:.0f}%)" if total else "0/0"


_ICON = {GOAL: "✅", NO_GOAL: "❌", VOID: "➖", PENDING: "⏳"}


def result_line(p: Pick) -> str:
    score = f" {p.ht_score} la pauză" if p.ht_score else ""
    return f"{_ICON[p.result]} {p.home} vs {p.away}{score} ({p.probability:.0f}%)"


def stats_line(picks: list[Pick], label: str) -> str:
    done = [p for p in picks if p.result in (GOAL, NO_GOAL)]
    return f"{label}: {_pct(sum(p.result == GOAL for p in done), len(done))}"


def format_morning(day: dt.date, new_picks: list[Pick], leftovers: list[Pick], all_picks: list[Pick],
                   min_pct: float, minute: int) -> str:
    lines = [f"⚽ Gol în prima repriză — {day.strftime('%d.%m')}"]
    if new_picks:
        lines.append(f"Șansa din istoricul echipelor (ultimele meciuri), peste {min_pct:.0f}%:")
        lines.append("")
        for i, p in enumerate(new_picks, 1):
            odds = f" · R1 Peste 0.5 @{p.odds_fh05}" if p.odds_fh05 else ""
            lines.append(f"{i}. {p.kickoff_local} {p.home} vs {p.away} — {p.probability:.0f}%")
            lines.append(f"   {p.league}{odds}")
        lines.append("")
        lines.append(f"⏰ Alertă dacă e tot 0-0 în minutul {minute}.")
    else:
        lines.append(f"Niciun meci din oferta Superbet nu trece de {min_pct:.0f}% azi.")
    if leftovers:
        lines.append("")
        lines.append("Rezultate rămase de ieri:")
        lines.extend(result_line(p) for p in leftovers)
    if any(p.result in (GOAL, NO_GOAL) for p in all_picks):
        lines.append("")
        lines.append(stats_line(all_picks, "📈 Total"))
    return "\n".join(lines)


def format_evening(day: dt.date, day_picks: list[Pick], all_picks: list[Pick], alerts: list[dict]) -> str:
    lines = [f"📊 Bilanț gol în prima repriză — {day.strftime('%d.%m')}"]
    if not day_picks:
        lines.append("Niciun pronostic azi.")
    else:
        lines.extend(result_line(p) for p in day_picks)
        lines.append("")
        lines.append(stats_line(day_picks, "Azi"))
    if alerts:
        by_key = {p.key: p for p in all_picks}
        hits = [a for a in alerts if (p := by_key.get(a.get("key"))) and p.result == GOAL]
        finished = [a for a in alerts if (p := by_key.get(a.get("key"))) and p.result in (GOAL, NO_GOAL)]
        lines.append(f"⏰ Alerte 0-0 la minut: {len(alerts)}, cu gol până la pauză: {_pct(len(hits), len(finished))}")
    lines.append(stats_line(all_picks, "📈 Total"))
    return "\n".join(lines)


def format_alert(p: Pick, sb: SbMatch, odds_live: Optional[float]) -> str:
    return "\n".join([
        f"⏰ 0-0 în minutul {sb.minute} — prima repriză",
        f"{sb.home} vs {sb.away}",
        p.league,
        f"Șansă de gol în R1 din istoric: {p.probability:.0f}%",
        f"Prima repriză Peste 0.5 live: {odds_live if odds_live is not None else 'indisponibilă'}"
        + (f" (pre-meci {p.odds_fh05})" if p.odds_fh05 else ""),
        f"🌐 {sb.url}",
    ])


def format_goal(p: Pick, sb: SbMatch, fh: tuple[int, int]) -> str:
    minute = f", minutul {sb.minute}" if sb.minute is not None and sb.label == "1H" else ""
    return "\n".join([
        "⚽⚽⚽ GOOOOOOOL! ⚽⚽⚽",
        f"{sb.home} {fh[0]}-{fh[1]} {sb.away}{minute}",
        p.league,
        "Prima repriză Peste 0.5 a intrat ✅",
    ])


def format_no_goal(p: Pick, sb: SbMatch) -> str:
    return "\n".join([
        "😞 Fără gol în prima repriză",
        f"{sb.home} 0-0 {sb.away} la pauză",
        p.league,
        "Prima repriză Peste 0.5 n-a intrat ❌",
    ])
