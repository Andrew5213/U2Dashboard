"""Jornada na descrição da lista e motivo da pausa em lista fechada (planilhas de tipos de site)."""
from datetime import time

from src.services.schedule_engine import WorkDay
from src.services.schedule_fields import (
    PAUSE_REASONS, SITE_TYPE_FIELD_DEFS, date_to_ms, parse_workday, read_task_pauses,
)
from datetime import date


def test_workday_comes_from_the_list_description():
    text = "folga=dom\njornada=08:00-17:00\nalmoço=12:00-13:00"
    assert parse_workday(text) == WorkDay(start=time(8), hours=8, lunch_start=time(12), lunch_hours=1)


def test_workday_without_lunch():
    assert parse_workday("jornada=07:00-16:00") == WorkDay(start=time(7), hours=9, lunch_start=None, lunch_hours=0)


def test_no_workday_line_means_dates_only():
    assert parse_workday("folga=dom") is None
    assert parse_workday(None) is None


def test_pause_reason_from_a_dropdown():
    options = [{"id": f"o{i}", "name": name, "orderindex": i} for i, name in enumerate(PAUSE_REASONS)]
    custom = [
        {"id": "f1", "name": "Pausa de", "type": "date", "value": str(date_to_ms(date(2026, 11, 3)))},
        {"id": "f2", "name": "Pausa até", "type": "date", "value": None},
        {"id": "f3", "name": "Motivo da pausa", "type": "drop_down", "type_config": {"options": options}, "value": 1},
        {"id": "f4", "name": "Histórico de pausas", "type": "text", "value": None},
    ]
    pause, _, _ = read_task_pauses(custom, 1)
    assert pause.reason == "Clima"


def test_site_type_fields_are_declared_once():
    names = [d["name"] for d in SITE_TYPE_FIELD_DEFS]
    assert len(names) == len(set(names))
    assert {"ID", "WBS", "Peso no projeto (%)", "% Planejado", "Situação", "Dias pausados", "Motivo da pausa"} <= set(names)
