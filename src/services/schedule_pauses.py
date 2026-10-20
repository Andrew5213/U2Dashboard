"""Pausas de tarefas do cronograma: leitura dos campos, histórico e arquivamento.

No ClickUp cada tarefa tem a pausa atual (ou a próxima) em três campos — "Pausa de",
"Pausa até" (em branco = parada até nova ordem) e "Motivo da pausa" — e as pausas que já
terminaram no campo de texto "Histórico de pausas", uma por linha:

    05/11/2026 – 08/11/2026 · chuva

Quando "Pausa até" passa, o motor arquiva a pausa nesse histórico e limpa os três campos
(`archive`). Pausas contíguas — a nova começa no dia útil seguinte ao fim de uma arquivada —
viram uma só. Módulo puro: não conhece ClickUp nem banco.
"""
from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from src.services.schedule_engine import WorkCalendar

FIELD_PAUSE_FROM = "Pausa de"
FIELD_PAUSE_UNTIL = "Pausa até"
FIELD_PAUSE_REASON = "Motivo da pausa"
FIELD_PAUSE_HISTORY = "Histórico de pausas"

PAUSE_FIELD_DEFS: list[dict] = [
    {"name": FIELD_PAUSE_FROM, "type": "date", "type_config": {}},
    {"name": FIELD_PAUSE_UNTIL, "type": "date", "type_config": {}},
    {"name": FIELD_PAUSE_REASON, "type": "short_text", "type_config": {}},
    {"name": FIELD_PAUSE_HISTORY, "type": "text", "type_config": {}},
]

_DATE = r"(\d{1,2})/(\d{1,2})/(\d{4})"
_LINE = re.compile(rf"^\s*{_DATE}\s*(?:–|—|-|a|até|ate)\s*{_DATE}\s*(?:[·•|:\-–—]\s*(.*?))?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Pause:
    start: date
    end: date | None          # None = parada até nova ordem (só na pausa atual)
    reason: str = ""
    archived: bool = False

    def until(self, today: date) -> date:
        """Último dia parado para o cálculo: sem fim, a pausa vai até hoje (e anda com ele)."""
        return self.end if self.end else max(today, self.start)

    def as_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat() if self.end else None,
                "reason": self.reason, "archived": self.archived}


def parse_history(text: str | None) -> tuple[list[Pause], list[str]]:
    """Pausas do texto do histórico e as linhas que não deu para ler (ficam como estão)."""
    pauses, bad = [], []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        match = _LINE.match(line)
        if not match:
            bad.append(line.strip())
            continue
        d1, m1, y1, d2, m2, y2, reason = match.groups()
        try:
            start, end = date(int(y1), int(m1), int(d1)), date(int(y2), int(m2), int(d2))
        except ValueError:
            bad.append(line.strip())
            continue
        if end < start:
            bad.append(line.strip())
            continue
        pauses.append(Pause(start, end, (reason or "").strip(), archived=True))
    return sorted(pauses, key=lambda p: p.start), bad


def format_history(pauses: list[Pause], bad_lines: Sequence[str] = ()) -> str:
    lines = [f"{p.start:%d/%m/%Y} – {p.end:%d/%m/%Y}" + (f" · {p.reason}" if p.reason else "")
             for p in sorted(pauses, key=lambda p: p.start) if p.end]
    return "\n".join([*lines, *bad_lines])


def _join_reasons(a: str, b: str) -> str:
    parts = [r for r in (a.strip(), b.strip()) if r]
    return "; ".join(dict.fromkeys(parts))


def archive(history: list[Pause], pause: Pause, calendar: WorkCalendar | None = None) -> list[Pause]:
    """Histórico com a pausa terminada acrescentada. Se ela encosta numa pausa já arquivada
    (sobrepõe ou começa no dia útil seguinte ao fim dela), as duas viram uma só."""
    assert pause.end, "só se arquiva pausa com fim"
    merged: list[Pause] = []
    current = Pause(pause.start, pause.end, pause.reason, archived=True)
    for old in sorted(history, key=lambda p: p.start):
        if old.end and _touches(old, current, calendar):
            current = Pause(min(old.start, current.start), max(old.end, current.end or old.end),
                            _join_reasons(old.reason, current.reason), archived=True)
        else:
            merged.append(old)
    merged.append(current)
    return sorted(merged, key=lambda p: p.start)


def _touches(a: Pause, b: Pause, calendar: WorkCalendar | None) -> bool:
    first, second = (a, b) if a.start <= b.start else (b, a)
    first_end = first.end or first.start
    if second.start <= first_end + timedelta(days=1):
        return True
    if calendar is None:
        return False
    # só dias de folga entre o fim de uma e o início da outra → contíguas
    day = first_end + timedelta(days=1)
    while day < second.start:
        if calendar.is_workday(day):
            return False
        day += timedelta(days=1)
    return True


def blocked_ranges(pauses: list[Pause], today: date) -> tuple[tuple[date, date], ...]:
    """Intervalos (dia inicial, dia final) em que a tarefa não anda, para o motor."""
    ranges = sorted((p.start, p.until(today)) for p in pauses if not p.archived)
    return tuple(ranges)


def pauses_to_json(current: Pause | None, history: list[Pause]) -> str | None:
    """O que o cache guarda: todas as pausas de uma tarefa, as do histórico e a atual."""
    items = [p.as_dict() for p in history] + ([current.as_dict()] if current else [])
    return json.dumps(items) if items else None


def display_pauses(pauses_json: str | None, today: date) -> list[dict]:
    """Pausas do cache prontas para um Gantt: {start, end, reason, archived}, com a pausa sem
    fim indo até hoje. Linhas inválidas são ignoradas."""
    try:
        items = json.loads(pauses_json or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        try:
            start = date.fromisoformat(item["start"])
            end = date.fromisoformat(item["end"]) if item.get("end") else max(today, start)
        except (KeyError, TypeError, ValueError):
            continue
        if end >= start:
            out.append({"start": start, "end": end, "reason": item.get("reason") or "",
                        "archived": bool(item.get("archived")), "open": not item.get("end")})
    return sorted(out, key=lambda p: p["start"])
