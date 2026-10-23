"""Campos do ClickUp usados pelo cronograma e a leitura dos seus valores.

Os campos são criados por lista (a API não cria campos a nível de Space), então
cada lista tem ids próprios — por isso tudo aqui casa por NOME, nunca por id.
"""
from __future__ import annotations

import unicodedata
from datetime import date, datetime, time, timedelta, timezone

from src.services.schedule_engine import CAL_CORRIDO, CAL_UTIL, WorkDay

FIELD_DURATION = "Duração (dias)"
FIELD_PERCENT = "% Concluído"
FIELD_CALENDAR = "Calendário"
FIELD_COMPLETION = "Data de Conclusão"   # já existe em todas as listas do space
# "não começar antes de" — preenchido pelo motor quando alguém muda à mão o início
# de uma tarefa não iniciada; apagar devolve a tarefa ao cálculo pelas dependências
FIELD_FIXED_START = "Início fixado"
# peso do item dentro do seu pai (coluna "Weight (%)" das planilhas de tipos de site); com
# peso em todos os filhos, o % do resumo é a média ponderada por ele, e não pela duração
FIELD_WEIGHT = "Peso (%)"

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
    {"name": FIELD_FIXED_START, "type": "date", "type_config": {}},
    {"name": FIELD_WEIGHT, "type": "number", "type_config": {}},
]
# os quatro campos de pausa ("Pausa de", "Pausa até", "Motivo da pausa", "Histórico de pausas")
from src.services.schedule_pauses import (  # noqa: E402
    FIELD_PAUSE_FROM, FIELD_PAUSE_HISTORY, FIELD_PAUSE_REASON, FIELD_PAUSE_UNTIL, PAUSE_FIELD_DEFS, Pause,
    parse_history,
)

FIELD_DEFS += PAUSE_FIELD_DEFS

# Informações das planilhas de tipos de site (2026-10-23). ID e WBS vêm da planilha (importador);
# os outros são calculados pelo motor a cada recálculo, como as colunas da planilha.
FIELD_TASK_ID = "ID"
FIELD_WBS = "WBS"
FIELD_PROJECT_WEIGHT = "Peso no projeto (%)"
FIELD_PLANNED = "% Planejado"
FIELD_SITUATION = "Situação"
FIELD_PAUSED_DAYS = "Dias pausados"
SITUATIONS = ("Não iniciada", "Em andamento", "Atrasada", "Pausada", "Concluída")
_SITUATION_COLORS = ("#87909e", "#1090e0", "#e8262a", "#f8ae00", "#2ecd6f")
PAUSE_REASONS = ("Logística", "Clima", "Externo", "Outro")       # aba Parameters: Pause reasons

SITE_TYPE_FIELD_DEFS: list[dict] = [
    {"name": FIELD_TASK_ID, "type": "number", "type_config": {}},
    {"name": FIELD_WBS, "type": "short_text", "type_config": {}},
    {"name": FIELD_PROJECT_WEIGHT, "type": "number", "type_config": {}},
    {"name": FIELD_PLANNED, "type": "number", "type_config": {}},
    {"name": FIELD_SITUATION, "type": "drop_down", "type_config": {"options": [
        {"name": name, "color": color} for name, color in zip(SITUATIONS, _SITUATION_COLORS)]}},
    {"name": FIELD_PAUSED_DAYS, "type": "number", "type_config": {}},
    # numa lista nova o motivo da pausa é lista fechada; numa que já o tem como texto, fica o texto
    {"name": FIELD_PAUSE_REASON, "type": "drop_down", "type_config": {"options": [
        {"name": name} for name in PAUSE_REASONS]}},
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
        if int(ms) <= 0:
            # a API do ClickUp não aceita null para limpar a data de início de uma
            # lista; o que ela aceita é 0, que significa "sem data" e não 01/01/1970
            return None
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


def ms_to_site_date(ms: str | int | None, utc_offset_hours: float) -> date | None:
    """Como `ms_to_date`, mas no fuso da obra. Uma data escolhida no ClickUp sem hora
    chega como a meia-noite do fuso de quem a digitou — em UTC, a meia-noite de
    Angola (UTC+1) já é o dia anterior. As datas que o motor grava (09:00 UTC) caem
    no mesmo dia nas duas leituras."""
    if ms in (None, ""):
        return None
    try:
        if int(ms) <= 0:
            return None
        moment = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) + timedelta(hours=utc_offset_hours)
        return moment.date()
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


def parse_workday(text: str | None) -> WorkDay | None:
    """Lê "jornada=08:00-17:00" (e "almoço=12:00-13:00") da descrição da lista. Sem a linha
    da jornada, None: as datas ficam só com o dia, como sempre."""
    spans: dict[str, tuple[time, time]] = {}
    for line in (text or "").splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            key, sep, value = line.partition(":")
        parts = [p.strip() for p in value.replace("–", "-").split("-")]
        if not sep or len(parts) != 2:
            continue
        try:
            first, last = (datetime.strptime(p, "%H:%M").time() for p in parts)
        except ValueError:
            continue
        spans[norm(key)] = (first, last)          # norm: "almoço" vira "almoco"
    if "jornada" not in spans:
        return None
    start, end = spans["jornada"]
    lunch = spans.get("almoco")
    lunch_hours = ((lunch[1].hour * 60 + lunch[1].minute) - (lunch[0].hour * 60 + lunch[0].minute)) / 60 if lunch else 0
    hours = ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) / 60 - lunch_hours
    return WorkDay(start=start, hours=hours, lunch_start=lunch[0] if lunch else None, lunch_hours=lunch_hours)


def read_option(field: dict | None) -> str | None:
    """Nome da opção escolhida num campo de lista fechada (o ClickUp devolve o orderindex)."""
    if not field or field.get("value") in (None, ""):
        return None
    options = (field.get("type_config") or {}).get("options") or []
    for option in options:
        if str(option.get("orderindex")) == str(field["value"]) or option.get("id") == field["value"]:
            return option.get("name")
    return None


def option_id(field: dict | None, name: str) -> str | None:
    for option in ((field or {}).get("type_config") or {}).get("options") or []:
        if norm(option.get("name")) == norm(name):
            return option.get("id")
    return None


def read_task_pauses(custom: list[dict] | None, utc_offset_hours: float) -> tuple[Pause | None, list[Pause], list[str]]:
    """(pausa atual ou próxima, pausas do histórico, linhas do histórico que não deu para ler)."""
    start = ms_to_site_date((find_field(custom, FIELD_PAUSE_FROM, "date") or {}).get("value"), utc_offset_hours)
    end = ms_to_site_date((find_field(custom, FIELD_PAUSE_UNTIL, "date") or {}).get("value"), utc_offset_hours)
    reason_field = find_field(custom, FIELD_PAUSE_REASON)
    if reason_field and reason_field.get("type") == "drop_down":
        reason = read_option(reason_field) or ""
    else:
        reason = str((reason_field or {}).get("value") or "").strip()
    history, bad = parse_history((find_field(custom, FIELD_PAUSE_HISTORY) or {}).get("value"))
    return (Pause(start, end, reason) if start else None), history, bad
