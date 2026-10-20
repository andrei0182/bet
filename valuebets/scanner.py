"""Pariuri cu valoare: cota Superbet peste cota corectă Pinnacle.

Cota corectă = cota Pinnacle fără marjă (vezi pinnacle.fair_odds). Avantajul
unui pariu = cota Superbet / cota corectă - 1; pe termen lung, profitul
așteptat la o miză de 1 e chiar acest procent.

Piețele comparate (Superbet, CONFIRMAT 2026-10-20 pe PSG–Barcelona):
- "Final" (1 / X / 2)                    <-> Pinnacle moneyline, perioada 0
- "Prima repriză - 1X2" (gazde/Egal/oaspeți) <-> moneyline, perioada 1
- "Total goluri" (Peste/Sub X.5)          <-> total, perioada 0
- "Prima repriză - Total goluri"          <-> total, perioada 1
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from dataclasses import asdict, dataclass, fields
from typing import Optional

from fhgoals.picks import RO_TZ
from fhgoals.superbet import ODD_STATUS_ACTIVE, SbMatch, team_score

from .pinnacle import Markets, PinMatch

PENDING, WON, LOST, VOID = "pending", "won", "lost", "void"
VOID_AFTER = dt.timedelta(hours=48)

_SB_MARKETS = {
    "Final": "1x2",
    "Prima repriză - 1X2": "1x2_h1",
    "Total goluri": "total",
    "Prima repriză - Total goluri": "total_h1",
}


def superbet_markets(markets: list[dict], home: str) -> Markets:
    """Cotele Superbet active, cu aceleași chei ca la Pinnacle."""
    out: Markets = {}
    for market in markets or []:
        kind = _SB_MARKETS.get(market.get("name"))
        if kind is None:
            continue
        for odd in market.get("odds") or []:
            if odd.get("status", ODD_STATUS_ACTIVE) != ODD_STATUS_ACTIVE or not odd.get("price"):
                continue
            meta = odd.get("metadata") or {}
            name = meta.get("name", "")
            if kind.startswith("1x2"):
                sel = {"1": "home", "X": "draw", "2": "away", "Egal": "draw", home: "home"}.get(name, "away")
                key = (kind, 0.0)
            else:
                total = (meta.get("specifiers") or {}).get("total")
                side = "over" if name.startswith("Peste") else "under" if name.startswith("Sub") else None
                if total is None or side is None:
                    continue
                key, sel = (kind, float(total)), side
            out.setdefault(key, {})[sel] = float(odd["price"])
    return out


@dataclass
class ValueBet:
    date: str  # ziua din România
    kickoff_local: str
    kickoff_utc: str  # ISO
    league: str
    home: str
    away: str
    market: str  # "1x2", "1x2_h1", "total", "total_h1"
    line: float
    selection: str  # "home"/"draw"/"away"/"over"/"under"
    sb_odds: float
    fair_odds: float
    edge: float  # procente
    pin_limit: float
    superbet_id: str
    pinnacle_id: str
    close_fair: float = 0.0  # ultima cotă corectă Pinnacle văzută înainte de start
    result: str = PENDING
    score: str = ""
    profit: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.superbet_id}|{self.market}|{self.line}|{self.selection}"

    def kickoff(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.kickoff_utc)

    @property
    def clv(self) -> Optional[float]:
        """Cota luată față de cota corectă de la start, în procente."""
        return (self.sb_odds / self.close_fair - 1) * 100 if self.close_fair else None

    def label(self) -> str:
        half = "Repriza 1: " if self.market.endswith("_h1") else ""
        if self.market.startswith("1x2"):
            what = {"home": f"{self.home} câștigă", "draw": "Egal", "away": f"{self.away} câștigă"}[self.selection]
        else:
            what = f"{'Peste' if self.selection == 'over' else 'Sub'} {self.line:g} goluri"
        return half + what


def find_value(pin: PinMatch, sb: SbMatch, sb_markets: Markets, min_edge: float, min_fair: float,
               max_fair: float, min_limit: float) -> list[ValueBet]:
    bets = []
    local = sb.kickoff_utc.astimezone(RO_TZ)
    for key, fair in pin.fair.items():
        if pin.limits.get(key, 0) < min_limit:
            continue
        offered = sb_markets.get(key, {})
        for sel, fair_price in fair.items():
            price = offered.get(sel)
            if price is None or not (min_fair <= fair_price <= max_fair):
                continue
            edge = price / fair_price - 1
            if edge * 100 < min_edge:
                continue
            bets.append(ValueBet(
                date=local.date().isoformat(), kickoff_local=local.strftime("%H:%M"),
                kickoff_utc=sb.kickoff_utc.isoformat(), league=pin.league, home=sb.home, away=sb.away,
                market=key[0], line=key[1], selection=sel, sb_odds=price, fair_odds=round(fair_price, 3),
                edge=round(edge * 100, 1), pin_limit=pin.limits.get(key, 0), superbet_id=str(sb.event_id),
                pinnacle_id=str(pin.id), close_fair=round(fair_price, 3),
            ))
    return bets


def _similar(a: str, b: str) -> float:
    # numele pot fi mai complete la oricare dintre case ("PSG" / "Paris Saint-Germain")
    return max(team_score(a, b), team_score(b, a))


def pair_matches(pins: list[PinMatch], sbs: list[SbMatch],
                 max_diff: dt.timedelta = dt.timedelta(minutes=20)) -> list[tuple[PinMatch, SbMatch]]:
    """Fiecare meci Pinnacle cu meciul Superbet corespunzător: aceeași oră de
    start și cel puțin jumătate din cuvintele specifice ale fiecărei echipe."""
    out, used = [], set()
    for pin in pins:
        best, best_score = None, 0.0
        for sb in sbs:
            if sb.event_id in used or sb.kickoff_utc is None or abs(sb.kickoff_utc - pin.start_utc) > max_diff:
                continue
            h, a = _similar(pin.home, sb.home), _similar(pin.away, sb.away)
            if h >= 0.5 and a >= 0.5 and h + a > best_score:
                best, best_score = sb, h + a
        if best is not None:
            used.add(best.event_id)
            out.append((pin, best))
    return out


def settle(bet: ValueBet, match: Optional[SbMatch], now: dt.datetime) -> bool:
    """Închide pariul din scorul final Superbet. True dacă s-a schimbat."""
    if bet.result != PENDING:
        return False
    if match is None or match.status != "FINISHED":
        if now > bet.kickoff() + VOID_AFTER:
            bet.result, bet.profit = VOID, 0.0
            return True
        return False
    if bet.market.endswith("_h1"):
        if match.fh_home is None or match.fh_away is None:
            return False
        h, a = match.fh_home, match.fh_away
    else:
        h, a = match.home_goals, match.away_goals
    if bet.market.startswith("1x2"):
        won = bet.selection == ("home" if h > a else "away" if a > h else "draw")
    else:
        won = (h + a > bet.line) == (bet.selection == "over")
    bet.result = WON if won else LOST
    bet.profit = round(bet.sb_odds - 1, 3) if won else -1.0
    bet.score = f"{h}-{a}"
    return True


_FIELDS = [f.name for f in fields(ValueBet)]
_FLOATS = {"line", "sb_odds", "fair_odds", "edge", "pin_limit", "close_fair", "profit"}


def load_bets(path: str) -> list[ValueBet]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            values = {k: row.get(k) or "" for k in _FIELDS}
            try:
                for k in _FLOATS:
                    values[k] = float(values[k] or 0)
                out.append(ValueBet(**values))
            except (TypeError, ValueError):
                continue
    return out


def save_bets(path: str, bets: list[ValueBet]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDS)
        writer.writeheader()
        for b in sorted(bets, key=lambda b: (b.kickoff_utc, b.home, b.market, b.selection)):
            writer.writerow(asdict(b))


# ============================================================
# Mesajele Telegram
# ============================================================

def format_new(bets: list[ValueBet]) -> str:
    lines = ["💎 Pariuri cu valoare: Superbet plătește peste cota corectă (Pinnacle fără marjă)", ""]
    for i, b in enumerate(bets, 1):
        lines.append(f"{i}. {b.kickoff_local} {b.home} vs {b.away}")
        lines.append(f"   {b.label()} @{b.sb_odds:g} (corect {b.fair_odds:.2f}, +{b.edge:.1f}%)")
        lines.append(f"   {b.league} · 🌐 superbet.ro/cote/fotbal/{b.superbet_id}")
    lines.append("")
    lines.append("Miză fixă mică (1–2% din bani). Valoarea se vede pe sute de pariuri, nu pe unul.")
    return "\n".join(lines)


def summary(bets: list[ValueBet], label: str) -> str:
    done = [b for b in bets if b.result in (WON, LOST)]
    if not done:
        return f"{label}: niciun pariu închis"
    profit = sum(b.profit for b in done)
    clvs = [b.clv for b in done if b.clv is not None]
    clv = f", CLV mediu {sum(clvs) / len(clvs):+.1f}%" if clvs else ""
    return (f"{label}: {sum(b.result == WON for b in done)}/{len(done)} câștigate, "
            f"profit {profit:+.2f} unități, ROI {profit / len(done) * 100:+.1f}%{clv}")


_ICON = {WON: "✅", LOST: "❌", VOID: "➖", PENDING: "⏳"}


def format_evening(day: dt.date, day_bets: list[ValueBet], all_bets: list[ValueBet]) -> str:
    lines = [f"💎 Bilanț pariuri cu valoare — {day.strftime('%d.%m')}"]
    if not day_bets:
        lines.append("Niciun pariu azi.")
    for b in day_bets:
        score = f" ({b.score})" if b.score else ""
        lines.append(f"{_ICON[b.result]} {b.home} vs {b.away}{score}: {b.label()} @{b.sb_odds:g}")
    lines.append("")
    lines.append(summary(day_bets, "Azi"))
    lines.append(summary(all_bets, "📈 Total"))
    return "\n".join(lines)
