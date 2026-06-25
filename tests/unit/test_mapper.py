import pytest
from src.models.schemas import AirboxTask
from src.services.mapper import (
    clickup_task_to_airbox,
    airbox_task_to_clickup,
    clickup_to_airbox_fields,
    _unix_ms_to_iso,
    CLICKUP_STATUS_TO_AIRBOX_STAGE,
    AIRBOX_STAGE_TO_CLICKUP_STATUS,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def make_clickup_task(**kwargs) -> dict:
    defaults = {
        "id": "abc123",
        "name": "Instalar esquadrias",
        "description": "Montar janelas de alumínio",
        "status": {"status": "in progress", "color": "#blue"},
        "due_date": "1748649600000",
        "start_date": "1746000000000",
        "assignees": [{"id": 99, "email": "eng@obra.com", "username": "eng"}],
        "list": {"id": "list-1", "name": "Obra Alpha"},
    }
    defaults.update(kwargs)
    return defaults


def make_airbox_task(**kwargs) -> AirboxTask:
    defaults = dict(
        id=42,
        name="Instalar esquadrias",
        entity_type="Project",
        entity_id=10,
        task_stage_id=2,
        due_date="2025-05-30T00:00:00+00:00",
        started="2025-04-28T00:00:00+00:00",
        responsible_id=7,
        information="Montar janelas de alumínio",
    )
    defaults.update(kwargs)
    return AirboxTask(**defaults)


# ─── ClickUp → Airbox ────────────────────────────────────────────────────────

class TestClickUpTaskToAirbox:
    def test_maps_name(self):
        task = make_clickup_task(name="Concretar laje")
        result = clickup_task_to_airbox(task, agreement_id=5, entity_type="Project")
        assert result["name"] == "Concretar laje"

    def test_sets_entity_type_and_id(self):
        task = make_clickup_task()
        result = clickup_task_to_airbox(task, agreement_id=7, entity_type="Procedure")
        assert result["entity_type"] == "Procedure"
        assert result["entity_id"] == 7

    def test_maps_description_as_information(self):
        task = make_clickup_task(description="Detalhe importante")
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert result["information"] == "Detalhe importante"

    def test_maps_due_date(self):
        task = make_clickup_task(due_date="1748649600000")
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert result["due_date"] == _unix_ms_to_iso("1748649600000")

    def test_maps_start_date_as_started(self):
        task = make_clickup_task(start_date="1746000000000")
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert result["started"] == _unix_ms_to_iso("1746000000000")

    def test_no_due_date_when_none(self):
        task = make_clickup_task(due_date=None)
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert "due_date" not in result

    def test_maps_status_to_stage_id(self, monkeypatch):
        monkeypatch.setitem(CLICKUP_STATUS_TO_AIRBOX_STAGE, "in progress", 2)
        task = make_clickup_task(status={"status": "in progress"})
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert result["task_stage_id"] == 2

    def test_no_stage_when_status_not_mapped(self):
        task = make_clickup_task(status={"status": "custom_xyz"})
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert "task_stage_id" not in result

    def test_maps_responsible_id(self):
        task = make_clickup_task()
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project", airbox_responsible_id=55)
        assert result["responsible_id"] == 55

    def test_no_responsible_when_none(self):
        task = make_clickup_task()
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert "responsible_id" not in result

    def test_empty_description_not_included(self):
        task = make_clickup_task(description="", markdown_description="")
        result = clickup_task_to_airbox(task, agreement_id=1, entity_type="Project")
        assert "information" not in result


# ─── Airbox → ClickUp ────────────────────────────────────────────────────────

class TestAirboxTaskToClickUp:
    def test_maps_name(self):
        task = make_airbox_task(name="Concretar laje")
        result = airbox_task_to_clickup(task)
        assert result.name == "Concretar laje"

    def test_fallback_name_when_none(self):
        task = make_airbox_task(name=None, id=99)
        result = airbox_task_to_clickup(task)
        assert result.name == "Tarefa #99"

    def test_maps_due_date(self):
        task = make_airbox_task(due_date="2025-05-30T00:00:00+00:00")
        result = airbox_task_to_clickup(task)
        assert result.due_date == 1_748_563_200_000

    def test_maps_information_as_description(self):
        task = make_airbox_task(information="Detalhe da tarefa")
        result = airbox_task_to_clickup(task)
        assert result.description == "Detalhe da tarefa"

    def test_status_mapped_when_stage_configured(self, monkeypatch):
        monkeypatch.setitem(AIRBOX_STAGE_TO_CLICKUP_STATUS, 2, "in progress")
        task = make_airbox_task(task_stage_id=2)
        result = airbox_task_to_clickup(task)
        assert result.status == "in progress"

    def test_status_none_when_not_configured(self):
        task = make_airbox_task(task_stage_id=999)
        result = airbox_task_to_clickup(task)
        assert result.status is None


# ─── clickup_to_airbox_fields (webhook history) ───────────────────────────────

class TestClickUpToAirboxFields:
    def test_maps_name(self):
        items = [{"field": "name", "after": "Novo nome"}]
        assert clickup_to_airbox_fields(items)["name"] == "Novo nome"

    def test_maps_due_date(self):
        items = [{"field": "due_date", "after": "1748649600000"}]
        assert clickup_to_airbox_fields(items)["due_date"] == _unix_ms_to_iso("1748649600000")

    def test_maps_status_to_stage_id(self, monkeypatch):
        monkeypatch.setitem(CLICKUP_STATUS_TO_AIRBOX_STAGE, "complete", 3)
        items = [{"field": "status", "after": {"status": "complete"}}]
        assert clickup_to_airbox_fields(items)["task_stage_id"] == 3

    def test_unknown_status_not_mapped(self):
        items = [{"field": "status", "after": {"status": "custom_xyz"}}]
        assert "task_stage_id" not in clickup_to_airbox_fields(items)

    def test_empty_returns_empty(self):
        assert clickup_to_airbox_fields([]) == {}

    def test_unknown_field_ignored(self):
        items = [{"field": "priority", "after": "urgent"}]
        assert clickup_to_airbox_fields(items) == {}
