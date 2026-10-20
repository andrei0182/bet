"""Botul Telegram „gol în prima repriză”.

La fiecare rulare (workflow-ul o pornește la 20 de minute):
1. dimineața, după POST_MORNING (o dată pe zi): actualizează istoricul
   BetExplorer, alege meciurile zilei cu cea mai mare șansă de gol în prima
   repriză (doar cele din oferta Superbet) și le publică pe canal;
2. seara, după POST_EVENING (o dată pe zi): publică rezultatele zilei;
3. urmărește live meciurile alese și trimite alertă dacă sunt tot 0-0 în
   minutul FH_MINUTE (implicit 20) al primei reprize; după alertă urmărește
   meciul până la pauză și postează „GOOOOOOL!” + 🎉 la primul gol din prima
   repriză sau „Fără gol” + 😭 dacă pauza vine la 0-0 (cu GIF-urile din
   FH_GIF_GOAL / FH_GIF_NO_GOAL în loc de emoji, dacă sunt setate).

Pronosticurile se salvează în data/fh_picks.csv (îl comite workflow-ul),
istoricul și starea alertelor în state/ (cache-ul GitHub Actions).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import time

from fhgoals import telegram
from fhgoals.history import fetch_day, load_history, update_history
from fhgoals.model import TeamIndex, backtest
from fhgoals.picks import PENDING, RO_TZ, load_picks, save_picks
from fhgoals.report import (
    check_results,
    format_alert,
    format_evening,
    format_goal,
    format_morning,
    format_no_goal,
    select_picks,
    to_pick,
)
from fhgoals.superbet import (
    FIRST_HALF_LABEL,
    fetch_matches,
    first_half_over05,
)

logger = logging.getLogger("fh_bot")

PICKS_PATH = "data/fh_picks.csv"
STATE_DIR = "state"
HISTORY_PATH = os.path.join(STATE_DIR, "fh_history.csv")
STATE_PATH = os.path.join(STATE_DIR, "fh_state.json")
# Prima repriză durează ~50 de minute cu prelungirile.
FIRST_HALF_WINDOW = dt.timedelta(minutes=55)
# După alertă meciul se urmărește până la pauză, cu marjă pentru start întârziat.
ALERTED_WINDOW = dt.timedelta(minutes=80)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def env_time(name: str, default: str) -> dt.time:
    try:
        return dt.time.fromisoformat(os.environ.get(name) or default)
    except ValueError:
        return dt.time.fromisoformat(default)


MIN_PCT = env_float("FH_MIN_PCT", 80)
MAX_PICKS = int(env_float("FH_MAX_PICKS", 10))
FH_MINUTE = int(env_float("FH_MINUTE", 20))
LAST_N = int(env_float("FH_LAST_N", 10))
MIN_MATCHES = int(env_float("FH_MIN_MATCHES", 5))
HISTORY_DAYS = int(env_float("FH_HISTORY_DAYS", 60))
POST_MORNING = env_time("POST_MORNING", "08:00")
POST_EVENING = env_time("POST_EVENING", "23:30")
GIF_GOAL = os.environ.get("FH_GIF_GOAL", "")
GIF_NO_GOAL = os.environ.get("FH_GIF_NO_GOAL", "")


def celebrate(text: str, gif: str, emoji: str) -> bool:
    """Mesajul de după alertă: GIF-ul cu textul ca descriere dacă e setat,
    altfel textul urmat de un emoji singur (Telegram îl animă)."""
    if gif and telegram.send_animation(gif, text):
        return True
    if not telegram.send(text):
        return False
    telegram.send(emoji)
    return True


def follow_alerted(p, m) -> str | None:
    """Meci deja alertat (0-0 la minut): postează la primul gol din prima
    repriză sau la pauză fără gol. Întoarce motivul închiderii sau None."""
    fh = m.first_half_score()
    if fh is not None and sum(fh) > 0:
        if celebrate(format_goal(p, m, fh), GIF_GOAL, "🎉"):
            return f"gol în prima repriză ({fh[0]}-{fh[1]})"
        return None
    if m.status == "FINISHED" or (m.status == "STARTED" and m.label != FIRST_HALF_LABEL):
        if fh is None:
            return f"prima repriză s-a terminat, scor necunoscut ({m.label})"
        if celebrate(format_no_goal(p, m), GIF_NO_GOAL, "😭"):
            return "pauză 0-0"
        return None
    return None


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    # păstrăm doar ultimele 7 zile de alerte
    cutoff = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    state["alerts"] = [a for a in state.get("alerts", []) if a.get("date", "") >= cutoff]
    state["closed"] = [k for k in state.get("closed", []) if k[:10] >= cutoff]
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def morning(now: dt.datetime, state: dict) -> None:
    today = now.astimezone(RO_TZ).date()
    history = update_history(HISTORY_PATH, today, days=HISTORY_DAYS)
    picks = load_picks(PICKS_PATH)
    leftovers = [p for p in check_results(picks, history, now) if p.date < today.isoformat()]

    fixtures = []
    for day in (today, today + dt.timedelta(days=1)):
        try:
            fixtures += fetch_day(day)
        except Exception as exc:
            logger.warning("Nu pot citi meciurile din %s: %s", day, exc)
    superbet = fetch_matches("active-prematch", today - dt.timedelta(days=1), today + dt.timedelta(days=2))
    chosen = select_picks(fixtures, TeamIndex(history.values()), superbet, today, now,
                          MIN_PCT, MAX_PICKS, LAST_N, MIN_MATCHES)
    known = {p.key for p in picks}
    for pred, sb in chosen:
        pick = to_pick(pred, sb, first_half_over05(sb.event_id))
        if pick.key not in known:
            picks.append(pick)
    save_picks(PICKS_PATH, picks)
    logger.info("%d meciuri programate, %d alese", len(fixtures), len(chosen))

    today_picks = sorted((p for p in picks if p.date == today.isoformat()), key=lambda p: (-p.probability, p.kickoff_local))
    text = format_morning(today, today_picks, leftovers, picks, MIN_PCT, FH_MINUTE)
    if telegram.send(text):
        state["morning"] = today.isoformat()


def evening(now: dt.datetime, state: dict) -> None:
    today = now.astimezone(RO_TZ).date()
    history = update_history(HISTORY_PATH, today, days=HISTORY_DAYS, refresh=1)
    picks = load_picks(PICKS_PATH)
    check_results(picks, history, now)
    save_picks(PICKS_PATH, picks)
    day_picks = sorted((p for p in picks if p.date == today.isoformat()), key=lambda p: p.kickoff_local)
    alerts = [a for a in state.get("alerts", []) if a.get("date") == today.isoformat()]
    if telegram.send(format_evening(today, day_picks, picks, alerts)):
        state["evening"] = today.isoformat()


def monitor(state: dict, max_minutes: float, poll_seconds: int = 60) -> None:
    """Urmărește pronosticurile live până la `max_minutes`; iese imediat dacă
    niciun meci nu e în prima repriză și niciunul nu începe în fereastra asta."""
    start = dt.datetime.now(dt.timezone.utc)
    deadline = start + dt.timedelta(minutes=max_minutes)
    picks = [p for p in load_picks(PICKS_PATH) if p.result == PENDING and p.superbet_id]
    closed = set(state.setdefault("closed", []))

    while True:
        now = dt.datetime.now(dt.timezone.utc)
        alerted = {a.get("key") for a in state.get("alerts", [])}
        watch = []
        for p in picks:
            kickoff = p.kickoff_utc()
            if p.key in closed or kickoff is None:
                continue
            window = ALERTED_WINDOW if p.key in alerted else FIRST_HALF_WINDOW
            if kickoff <= deadline and now <= kickoff + window:
                watch.append(p)
        if not watch:
            logger.info("Niciun meci de urmărit acum.")
            return

        today = now.date()
        live = {str(m.event_id): m for m in fetch_matches("active-live", today - dt.timedelta(days=1), today + dt.timedelta(days=2))}
        for p in watch:
            m = live.get(p.superbet_id)
            if m is None:
                continue
            if p.key in alerted:
                reason = follow_alerted(p, m)
                if reason:
                    logger.info("%s vs %s: %s", p.home, p.away, reason)
                    closed.add(p.key)
                continue
            reason = None
            if m.status == "FINISHED" or m.goals > 0:
                reason = f"gol / terminat ({m.home_goals}-{m.away_goals})"
            elif m.label != FIRST_HALF_LABEL:
                if m.status == "STARTED":
                    reason = f"prima repriză s-a terminat ({m.label})"
            elif m.minute is not None and m.minute >= FH_MINUTE:
                odds = first_half_over05(m.event_id)
                if telegram.send(format_alert(p, m, odds)):
                    state.setdefault("alerts", []).append(
                        {"key": p.key, "date": p.date, "minute": m.minute, "odds": odds}
                    )
                    alerted.add(p.key)
                    logger.info("%s vs %s: alertă trimisă (minutul %d)", p.home, p.away, m.minute)
            if reason:
                logger.info("%s vs %s: %s", p.home, p.away, reason)
                closed.add(p.key)
        state["closed"] = sorted(closed)
        save_state(state)

        if dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=poll_seconds) > deadline:
            return
        time.sleep(poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bot Telegram: gol în prima repriză.")
    parser.add_argument("--test-telegram", action="store_true", help="Trimite doar un mesaj de test.")
    parser.add_argument("--max-minutes", type=float, default=env_float("MAX_MINUTES", 18),
                        help="Cât timp urmărește meciurile live (minute).")
    parser.add_argument("--morning", action="store_true", help="Forțează postarea de dimineață acum.")
    parser.add_argument("--evening", action="store_true", help="Forțează bilanțul de seară acum.")
    parser.add_argument("--backtest", type=int, metavar="ZILE",
                        help="Verifică modelul pe ultimele ZILE din istoricul salvat și iese.")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    if args.test_telegram:
        ok = telegram.send("✅ Test: botul „gol în prima repriză” din andrei0182/bet funcționează.")
        raise SystemExit(0 if ok else 1)

    if args.backtest:
        history = load_history(HISTORY_PATH)
        since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.backtest)
        for pct, n, hits in backtest(history.values(), since, LAST_N, MIN_MATCHES):
            print(f"P >= {pct}%: {n} meciuri, gol în R1 la {hits} ({hits * 100 / n:.1f}%)" if n else f"P >= {pct}%: 0 meciuri")
        return

    state = load_state()
    now = dt.datetime.now(dt.timezone.utc)
    local = now.astimezone(RO_TZ)
    today = local.date().isoformat()
    posts = os.environ.get("POSTS", "on").lower() != "off"

    if args.morning or (posts and local.time() >= POST_MORNING and state.get("morning") != today):
        try:
            morning(now, state)
        except Exception:
            logger.exception("Postarea de dimineață a eșuat")
        save_state(state)
    if args.evening or (posts and local.time() >= POST_EVENING and state.get("evening") != today):
        try:
            evening(now, state)
        except Exception:
            logger.exception("Bilanțul de seară a eșuat")
        save_state(state)

    monitor(state, args.max_minutes)
    save_state(state)


if __name__ == "__main__":
    main()
