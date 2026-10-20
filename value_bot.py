"""Scannerul de valoare: pariuri unde Superbet plătește peste cota corectă.

Rulează continuu, în rulări de câte o oră care o pornesc singure pe
următoarea (workflow-ul value-telegram.yml); la fiecare VAL_INTERVAL_MIN
minute (implicit 30):
1. închide pariurile terminate, din scorul final Superbet (indexul `live`
   păstrează meciurile terminate, cu scorul la pauză în `periods`);
2. citește cotele Pinnacle, scoate marja și le compară cu Superbet pentru
   meciurile care încep în următoarele VAL_WINDOW_H ore; pariurile noi cu
   avantaj >= VAL_MIN_EDGE se postează pe Telegram;
3. pentru pariurile încă neîncepute actualizează cota corectă Pinnacle
   (ultima valoare dinainte de start = cota de închidere, pentru CLV);
4. seara, după POST_EVENING (o dată pe zi, verificat pe minut): bilanțul
   zilei și totalul.

Pariurile se salvează în data/value_bets.csv (îl comite workflow-ul).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

from fhgoals import telegram
from fhgoals.picks import RO_TZ
from fhgoals.superbet import fetch_event_markets, fetch_matches
from valuebets import pinnacle
from valuebets.scanner import (
    PENDING,
    find_value,
    format_evening,
    format_new,
    load_bets,
    pair_matches,
    save_bets,
    settle,
    superbet_markets,
)

logger = logging.getLogger("value_bot")

BETS_PATH = "data/value_bets.csv"
STATE_PATH = os.path.join("vstate", "value_state.json")


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


MIN_EDGE = env_float("VAL_MIN_EDGE", 3)  # procente
MIN_FAIR = env_float("VAL_MIN_FAIR", 1.3)
MAX_FAIR = env_float("VAL_MAX_FAIR", 4.0)
MIN_LIMIT = env_float("VAL_MIN_LIMIT", 250)  # miza maximă Pinnacle: piețele mici sunt mai puțin sigure
WINDOW_H = env_float("VAL_WINDOW_H", 12)
MAX_POST = int(env_float("VAL_MAX_POST", 10))
INTERVAL_MIN = env_float("VAL_INTERVAL_MIN", 30)
try:
    POST_EVENING = dt.time.fromisoformat(os.environ.get("POST_EVENING") or "23:30")
except ValueError:
    POST_EVENING = dt.time(23, 30)


def load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f)


def settle_pending(bets, now: dt.datetime) -> int:
    pending = [b for b in bets if b.result == PENDING and now > b.kickoff() + dt.timedelta(hours=2)]
    if not pending:
        return 0
    start = min(b.kickoff() for b in pending).date() - dt.timedelta(days=1)
    finished = {str(m.event_id): m for m in fetch_matches("live", start, now.date() + dt.timedelta(days=1))}
    return sum(settle(b, finished.get(b.superbet_id), now) for b in pending)


def scan(bets, now: dt.datetime, dry_run: bool) -> list:
    pins = [p for p in pinnacle.fetch_matches()
            if now + dt.timedelta(minutes=5) < p.start_utc < now + dt.timedelta(hours=WINDOW_H)]
    today = now.date()
    sbs = [m for m in fetch_matches("active-prematch", today - dt.timedelta(days=1), today + dt.timedelta(days=2))
           if m.kickoff_utc]
    pairs = pair_matches(pins, sbs)
    logger.info("Pinnacle %d meciuri în fereastră, Superbet %d, potrivite %d", len(pins), len(sbs), len(pairs))

    # cota corectă de închidere pentru pariurile încă neîncepute
    by_pin = {str(p.id): p for p in pins}
    for b in bets:
        pin = by_pin.get(b.pinnacle_id)
        if b.result == PENDING and pin and b.kickoff() > now:
            fair = pin.fair.get((b.market, b.line), {}).get(b.selection)
            if fair:
                b.close_fair = round(fair, 3)

    with ThreadPoolExecutor(max_workers=6) as pool:
        markets = list(pool.map(lambda pair: fetch_event_markets(pair[1].event_id), pairs))
    known = {b.key for b in bets}
    new = []
    for (pin, sb), mk in zip(pairs, markets):
        if mk is None:
            continue
        for bet in find_value(pin, sb, superbet_markets(mk, sb.home), MIN_EDGE, MIN_FAIR, MAX_FAIR, MIN_LIMIT):
            if bet.key not in known:
                known.add(bet.key)
                new.append(bet)
    new.sort(key=lambda b: b.edge, reverse=True)
    new = new[:MAX_POST]
    logger.info("%d pariuri noi cu valoare", len(new))
    if new:
        text = format_new(sorted(new, key=lambda b: (b.kickoff_utc, -b.edge)))
        if dry_run:
            print(text)
        elif not telegram.send(text):
            return []  # se reîncearcă la rularea următoare
    return new


def evening_post(state: dict, bets, force: bool, dry_run: bool) -> None:
    local = dt.datetime.now(dt.timezone.utc).astimezone(RO_TZ)
    today = local.date()
    posts = os.environ.get("POSTS", "on").lower() != "off"
    if not (force or (posts and local.time() >= POST_EVENING and state.get("evening") != today.isoformat())):
        return
    text = format_evening(today, [b for b in bets if b.date == today.isoformat()], bets)
    if dry_run:
        print(text)
    elif telegram.send(text):
        state["evening"] = today.isoformat()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Scanner de valoare Superbet vs Pinnacle.")
    parser.add_argument("--dry-run", action="store_true", help="O singură scanare; afișează mesajele, nu trimite și nu salvează.")
    parser.add_argument("--evening", action="store_true", help="Forțează bilanțul de seară acum.")
    parser.add_argument("--max-minutes", type=float, default=env_float("MAX_MINUTES", 0),
                        help="Cât durează rularea: scanare la VAL_INTERVAL_MIN minute (0 = o singură scanare).")
    args = parser.parse_args()

    state = load_state()
    bets = load_bets(BETS_PATH)
    deadline = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=args.max_minutes)
    next_scan = dt.datetime.now(dt.timezone.utc)
    force_evening = args.evening
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        if now >= next_scan:
            try:
                logger.info("%d pariuri închise", settle_pending(bets, now))
                bets += scan(bets, now, args.dry_run)
            except Exception:
                logger.exception("Scanarea a eșuat")
            next_scan = now + dt.timedelta(minutes=INTERVAL_MIN)
            if not args.dry_run:
                save_bets(BETS_PATH, bets)
        evening_post(state, bets, force_evening, args.dry_run)
        force_evening = False
        if not args.dry_run:
            save_state(state)
        if args.dry_run or dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60) > deadline:
            break
        time.sleep(60)

if __name__ == "__main__":
    main()
