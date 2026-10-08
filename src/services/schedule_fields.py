"""Campos do ClickUp usados pelo cronograma e a leitura dos seus valores.

Os campos são criados por lista (a API não cria campos a nível de Space), então
cada lista tem ids próprios — por isso tudo aqui casa por NOME, nunca por id.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, timezone

from src.services.schedule_engine import CAL_CORRIDO, CAL_UTIL

FIELD_DURATION = "Duração (dias)"
FIELD_PERCENT = "% Concluído"
FIELD_CALENDAR = "Calendário"
FIELD_COMPLETION = "Data de Conclusão"   # já existe em todas as listas do space

OPTION_UTIL = "Útil"
OPTION_CORRIDO = "Corrido"

FIELD_DEFS: list[dict] = [
    {"name": FIELD_DURATION, "type": "number", "type_config": {}},
    {"name": FIELD_PERCENT, "type": "manual_progress", "type_config": {"start": 0, "end": 100}},
    {
        "name": FIELD_CALENDAR,
        "type": "drop_down",
        "type_config": {"options": [
            {"name": OPTION_UTIL, "color": "#2ecd6f"},
            {"name": OPTION_CORRIDO, "color": "#f9d900"},
        ]},
    },
]

_WEEKDAYS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}


def norm(text: str | None) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return nfkd.encode("ascii", "ignore").decode("ascii").strip().lower()


def find_field(fields: list[dict] | None, name: str, field_type: str | None = None) -> dict | None:
    """Campo com esse nome (sem acento/caixa). `field_type` desempata homónimos —
    o space tem dois campos "Observações", por exemplo."""
    wanted = norm(name)
    for f in fields or []:
        if norm(f.get("name")) == wanted and (field_type is None or f.get("type") == field_type):
            return f
    return None


def read_number(field: dict | None) -> float | None:
    value = (field or {}).get("value")
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_percent(field: dict | None) -> float | None:
    """Valor de um campo manual_progress: {"current": "55", "percent_completed": 0.55}."""
    value = (field or {}).get("value")
    if isinstance(value, dict):
        value = value.get("current")
    if value in (None, ""):
        return None
    try:
        return min(max(float(value), 0.0), 100.0)
    except (TypeError, ValueError):
        return None


def read_calendar(field: dict | None) -> str:
    """Dropdown devolve o orderindex da opção escolhida (ou o id, em alguns endpoints)."""
    value = (field or {}).get("value")
    if value in (None, ""):
        return CAL_UTIL
    for option in ((field or {}).get("type_config") or {}).get("options") or []:
        if value == option.get("orderindex") or value == option.get("id"):
            return CAL_CORRIDO if norm(option.get("name")) == norm(OPTION_CORRIDO) else CAL_UTIL
    return CAL_UTIL


def calendar_option_id(field: dict, calendar_type: str) -> str | None:
    wanted = norm(OPTION_CORRIDO if calendar_type == CAL_CORRIDO else OPTION_UTIL)
    for option in (field.get("type_config") or {}).get("options") or []:
        if norm(option.get("name")) == wanted:
            return option.get("id")
    return None


def ms_to_date(ms: str | int | None) -> date | None:
    if ms in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


def date_to_ms(day: date) -> int:
    """09:00 UTC: cai no mesmo dia tanto no fuso do workspace (UTC−3) quanto em
    Angola (UTC+1), e o ClickUp só guarda o dia (start_date_time/due_date_time false)."""
    return int(datetime(day.year, day.month, day.day, 9, tzinfo=timezone.utc).timestamp() * 1000)


def parse_weekend_mask(text: str | None, default: str) -> str:
    """Lê "folga=dom" ou "folga: sáb, dom" da descrição da lista → máscara Seg→Dom."""
    for line in (text or "").splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            key, sep, value = line.partition(":")
        if norm(key) != "folga" or not sep:
            continue
        days = {_WEEKDAYS[norm(part)[:3]] for part in value.replace(";", ",").split(",") if norm(part)[:3] in _WEEKDAYS}
        if days and len(days) < 7:
            return "".join("1" if index in days else "0" for index in range(7))
    return default
