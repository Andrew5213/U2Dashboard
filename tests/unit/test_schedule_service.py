import copy
from datetime import date

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import src.models.schedule_models  # noqa: F401
from src.core.config import settings
from src.core.database import Base
from src.services import schedule_service
from src.services.schedule_fields import date_to_ms, ms_to_date
from src.services.schedule_service import ScheduleService, invalidate_holidays_cache, status_names

LIST_ID = "L1"
TODAY = date(2026, 10, 8)          # antes do início do projeto (13/10)

STATUSES = [
    {"status": "planejando", "type": "open", "orderindex": 0},
    {"status": "fazendo", "type": "custom", "orderindex": 1},
    {"status": "impedimento", "type": "custom", "orderindex": 2},
    {"status": "complete", "type": "done", "orderindex": 3},
    {"status": "cancelled", "type": "closed", "orderindex": 4},
]
F_DURATION, F_PERCENT, F_CALENDAR, F_COMPLETION = "f-dur", "f-pct", "f-cal", "f-done"
CALENDAR_OPTIONS = [
    {"id": "opt-util", "name": "Útil", "orderindex": 0},
    {"id": "opt-corrido", "name": "Corrido", "orderindex": 1},
]
FIELDS = [
    {"id": F_DURATION, "name": "Duração (dias)", "type": "number", "type_config": {}},
    {"id": F_PERCENT, "name": "% Concluído", "type": "manual_progress", "type_config": {"start": 0, "end": 100}},
    {"id": F_CALENDAR, "name": "Calendário", "type": "drop_down", "type_config": {"options": CALENDAR_OPTIONS}},
    {"id": F_COMPLETION, "name": "Data de Conclusão", "type": "date", "type_config": {}},
]


def make_task(task_id, parent=None, status="planejando", percent=0, duration=None, corrido=False, completed=None):
    status_type = next(s["type"] for s in STATUSES if s["status"] == status)
    values = {
        F_DURATION: None if duration is None else str(duration),
        F_PERCENT: {"current": str(percent), "percent_completed": percent / 100},
        F_CALENDAR: 1 if corrido else None,
        F_COMPLETION: None if completed is None else str(date_to_ms(completed)),
    }
    return {
        "id": task_id, "name": task_id.upper(), "parent": parent,
        "status": {"status": status, "type": status_type},
        "start_date": None, "due_date": None, "dependencies": [],
        "custom_fields": [{**f, "value": values[f["id"]]} for f in FIELDS],
    }


def depends(tasks, task_id, on):
    record = {"task_id": task_id, "depends_on": on, "type": 1}
    for t in tasks:
        if t["id"] in (task_id, on):   # o ClickUp devolve o registo nas duas tarefas
            t["dependencies"].append(record)


class FakeClickUp:
    """ClickUp em memória: guarda as tarefas e aplica as gravações do serviço."""

    def __init__(self, tasks, start=date(2026, 10, 13), content="", fields=FIELDS, holidays=()):
        self.tasks = {t["id"]: t for t in tasks}
        self.start, self.content, self.fields = start, content, fields
        self.holidays = list(holidays)
        self.writes: list[tuple] = []
        self.fail_on: set[str] = set()

    async def get_list(self, list_id):
        return {
            "id": list_id, "content": self.content, "statuses": STATUSES,
            "start_date": str(date_to_ms(self.start)) if self.start else None,
        }

    async def get_list_fields(self, list_id):
        return self.fields

    async def get_tasks(self, list_id, include_closed=True):
        if list_id == "HOLIDAYS":
            return [{"id": f"h{i}", "due_date": str(date_to_ms(d))} for i, d in enumerate(self.holidays)]
        return copy.deepcopy(list(self.tasks.values()))

    def _check(self, task_id):
        if task_id in self.fail_on:
            request = httpx.Request("PUT", "https://api.clickup.com")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(400, text="recusado", request=request))

    async def update_task_fields(self, task_id, payload):
        self._check(task_id)
        task = self.tasks[task_id]
        for key in ("start_date", "due_date"):
            if key in payload:
                task[key] = str(payload[key])
        if "status" in payload:
            status = next(s for s in STATUSES if s["status"] == payload["status"])
            task["status"] = {"status": status["status"], "type": status["type"]}
        self.writes.append(("task", task_id, payload))

    async def set_custom_field(self, task_id, field_id, value, value_options=None):
        self._check(task_id)
        field = next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)
        field["value"] = {"current": str(value["current"])} if isinstance(value, dict) else str(value)
        self.writes.append(("field", task_id, field_id, value))

    async def clear_custom_field(self, task_id, field_id):
        field = next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)
        field["value"] = None
        self.writes.append(("clear", task_id, field_id))

    # leitura cómoda para as asserções
    def dates(self, task_id):
        t = self.tasks[task_id]
        return ms_to_date(t["start_date"]), ms_to_date(t["due_date"])

    def value(self, task_id, field_id):
        return next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)["value"]

    def status(self, task_id):
        return self.tasks[task_id]["status"]["status"]


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _fast_and_isolated(monkeypatch):
    monkeypatch.setattr(schedule_service, "_WRITE_PAUSE_SECONDS", 0)
    monkeypatch.setattr(settings, "schedule_holidays_list_id", "")
    monkeypatch.setattr(settings, "schedule_weekend_mask", "0000001")
    invalidate_holidays_cache()


def _project():
    """Disciplina → grupo → duas tarefas encadeadas, mais uma tarefa solta."""
    tasks = [
        make_task("n1"),
        make_task("n2", parent="n1"),
        make_task("a", parent="n2", duration=2),
        make_task("b", parent="n2", duration=1),
        make_task("c", parent="n1", duration=14, corrido=True),
    ]
    depends(tasks, "b", "a")
    depends(tasks, "c", "b")
    return tasks


async def _run(db, clickup, today=TODAY, dry_run=False):
    return await ScheduleService(db, clickup).recalculate(LIST_ID, dry_run=dry_run, today=today)


class TestRecalculate:
    async def test_writes_dates_and_summaries(self, db):
        clickup = FakeClickUp(_project())
        summary = await _run(db, clickup)

        assert summary.ok and summary.warnings == []
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("b") == (date(2026, 10, 15), date(2026, 10, 15))
        assert clickup.dates("c") == (date(2026, 10, 16), date(2026, 10, 29))   # 14 corridos = 12 úteis
        assert clickup.dates("n2") == (date(2026, 10, 13), date(2026, 10, 15))
        assert clickup.dates("n1") == (date(2026, 10, 13), date(2026, 10, 29))
        assert float(clickup.value("n1", F_DURATION)) == 15
        assert summary.project_finish == date(2026, 10, 29)
        assert summary.percent == 0

    async def test_second_run_writes_nothing(self, db):
        clickup = FakeClickUp(_project())
        await _run(db, clickup)
        clickup.writes.clear()

        summary = await _run(db, clickup)

        assert summary.changed == 0 and summary.writes == 0
        assert clickup.writes == []

    async def test_dry_run_reports_but_does_not_write(self, db):
        clickup = FakeClickUp(_project())
        summary = await _run(db, clickup, dry_run=True)

        assert summary.changed == 5 and summary.writes == 0
        assert clickup.writes == []
        assert {c["name"] for c in summary.changes} == {"N1", "N2", "A", "B", "C"}

    async def test_percent_starts_the_task_and_rolls_up(self, db):
        tasks = _project()
        tasks[2] = make_task("a", parent="n2", duration=2, percent=50)
        clickup = FakeClickUp(tasks)
        depends(list(clickup.tasks.values()), "b", "a")

        summary = await _run(db, clickup)

        assert clickup.status("a") == "fazendo"
        assert clickup.status("n2") == "fazendo" and clickup.status("n1") == "fazendo"
        assert clickup.value("n2", F_PERCENT) == {"current": "33"}     # 1 de 3 dias
        assert summary.percent == pytest.approx(1 / 15 * 100, abs=0.01)

    async def test_completing_by_status_sets_100_and_the_completion_date(self, db):
        tasks = _project()
        tasks[2] = make_task("a", parent="n2", duration=2, status="complete")
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert clickup.value("a", F_PERCENT) == {"current": "100"}
        assert ms_to_date(clickup.value("a", F_COMPLETION)) == TODAY
        assert clickup.dates("a")[1] == TODAY

    async def test_known_completion_date_is_kept(self, db):
        tasks = [make_task("a", duration=1, status="complete", percent=100, completed=date(2026, 10, 2))]
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert ms_to_date(clickup.value("a", F_COMPLETION)) == date(2026, 10, 2)
        assert clickup.dates("a")[1] == date(2026, 10, 2)

    async def test_lowering_the_percent_reopens_and_clears_the_completion(self, db):
        clickup = FakeClickUp([make_task("a", duration=2, status="complete", percent=100)])
        await _run(db, clickup)                       # grava o estado: concluída a 100%

        clickup.tasks["a"]["custom_fields"][1]["value"] = {"current": "40"}
        await _run(db, clickup)

        assert clickup.status("a") == "fazendo"
        assert clickup.value("a", F_COMPLETION) is None

    async def test_reopening_by_status_takes_the_percent_off_100(self, db):
        clickup = FakeClickUp([make_task("a", duration=2, status="complete", percent=100)])
        await _run(db, clickup)

        clickup.tasks["a"]["status"] = {"status": "fazendo", "type": "custom"}
        await _run(db, clickup)

        assert clickup.value("a", F_PERCENT) == {"current": "99"}
        assert clickup.status("a") == "fazendo"

    async def test_all_tasks_done_completes_the_summaries_after_the_leaves(self, db):
        tasks = [
            make_task("n1"),
            make_task("a", parent="n1", duration=1, percent=100),
            make_task("b", parent="n1", duration=1, percent=100),
        ]
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert clickup.status("n1") == "complete"
        status_writes = [w[1] for w in clickup.writes if w[0] == "task" and "status" in w[2]]
        assert status_writes.index("n1") > max(status_writes.index("a"), status_writes.index("b"))

    async def test_summary_in_a_manual_status_is_respected(self, db):
        tasks = [make_task("n1", status="impedimento"), make_task("a", parent="n1", duration=1, percent=50)]
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert clickup.status("n1") == "impedimento"

    async def test_cancelled_task_is_not_touched(self, db):
        tasks = [make_task("a", duration=3, status="cancelled"), make_task("b", duration=1)]
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert clickup.dates("a") == (None, None)
        assert not [w for w in clickup.writes if w[1] == "a"]

    async def test_holidays_come_from_the_holidays_list(self, db, monkeypatch):
        monkeypatch.setattr(settings, "schedule_holidays_list_id", "HOLIDAYS")
        clickup = FakeClickUp([make_task("a", duration=2)], holidays=[date(2026, 10, 14)])

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 15))

    async def test_weekly_rest_can_be_set_in_the_list_description(self, db):
        clickup = FakeClickUp([make_task("a", duration=5)], content="folga=sáb, dom")

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 19))   # 13 é terça


class TestGuards:
    async def test_list_without_start_date_is_refused(self, db):
        clickup = FakeClickUp(_project(), start=None)
        summary = await _run(db, clickup)

        assert not summary.ok and "data de início" in summary.errors[0]
        assert clickup.writes == []

    async def test_list_without_schedule_fields_is_refused(self, db):
        clickup = FakeClickUp(_project(), fields=[f for f in FIELDS if f["id"] == F_COMPLETION])
        summary = await _run(db, clickup)

        assert not summary.ok and "não é um cronograma" in summary.errors[0]
        assert clickup.writes == []

    async def test_list_without_completion_date_field_is_refused(self, db):
        # sem esse campo uma tarefa concluída "terminaria hoje" a cada execução
        clickup = FakeClickUp(_project(), fields=[f for f in FIELDS if f["id"] != F_COMPLETION])
        summary = await _run(db, clickup)

        assert not summary.ok and "Data de Conclusão" in summary.errors[0]
        assert clickup.writes == []

    async def test_task_without_duration_is_reported(self, db):
        clickup = FakeClickUp([make_task("a", duration=1), make_task("b")])
        summary = await _run(db, clickup)

        assert summary.ok
        assert summary.warnings == ['"B": sem duração — não pesa no progresso nem ocupa o cronograma']

    async def test_one_failing_task_does_not_stop_the_others(self, db):
        clickup = FakeClickUp(_project())
        clickup.fail_on = {"b"}

        summary = await _run(db, clickup)

        assert len(summary.errors) == 1 and "B" in summary.errors[0] and "recusado" in summary.errors[0]
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("b") == (None, None)

    async def test_dependency_outside_the_list_is_reported(self, db):
        tasks = [make_task("a", duration=1)]
        tasks[0]["dependencies"].append({"task_id": "a", "depends_on": "outra-lista", "type": 1})
        summary = await _run(db, FakeClickUp(tasks))

        assert summary.ok
        assert summary.warnings == ['"A": antecessor outra-lista não está nesta lista — ignorado']


def test_rate_limit_wait_reads_the_clickup_reset_header():
    import time
    soon = httpx.Response(429, headers={"X-RateLimit-Reset": str(int(time.time()) + 7)})
    assert 5 <= schedule_service.rate_limit_wait(soon) <= 8
    assert schedule_service.rate_limit_wait(httpx.Response(429, headers={"Retry-After": "3"})) == 3
    assert schedule_service.rate_limit_wait(httpx.Response(429)) == 10
    far = httpx.Response(429, headers={"X-RateLimit-Reset": str(int(time.time()) + 900)})
    assert schedule_service.rate_limit_wait(far) == 60


def test_today_follows_the_site_timezone(monkeypatch):
    from datetime import datetime, timezone

    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 8, 23, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(schedule_service, "datetime", Late)
    monkeypatch.setattr(settings, "schedule_utc_offset_hours", 1)
    assert schedule_service.local_today() == date(2026, 10, 9)     # já é dia 9 em Angola
    monkeypatch.setattr(settings, "schedule_utc_offset_hours", -3)
    assert schedule_service.local_today() == date(2026, 10, 8)


def test_status_names_picks_the_three_automatic_statuses():
    names = status_names(STATUSES)
    assert (names.open, names.in_progress, names.done) == ("planejando", "fazendo", "complete")
