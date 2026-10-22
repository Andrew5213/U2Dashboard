import copy
from datetime import date, datetime, timedelta, timezone

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
F_DURATION, F_PERCENT, F_CALENDAR, F_COMPLETION, F_FIXED = "f-dur", "f-pct", "f-cal", "f-done", "f-fixed"
F_PFROM, F_PUNTIL, F_PREASON, F_PHIST = "f-pfrom", "f-puntil", "f-preason", "f-phist"
CALENDAR_OPTIONS = [
    {"id": "opt-util", "name": "Útil", "orderindex": 0},
    {"id": "opt-corrido", "name": "Corrido", "orderindex": 1},
]
FIELDS = [
    {"id": F_DURATION, "name": "Duração (dias)", "type": "number", "type_config": {}},
    {"id": F_PERCENT, "name": "% Concluído", "type": "manual_progress", "type_config": {"start": 0, "end": 100}},
    {"id": F_CALENDAR, "name": "Calendário", "type": "drop_down", "type_config": {"options": CALENDAR_OPTIONS}},
    {"id": F_COMPLETION, "name": "Data de Conclusão", "type": "date", "type_config": {}},
    {"id": F_FIXED, "name": "Início fixado", "type": "date", "type_config": {}},
    {"id": F_PFROM, "name": "Pausa de", "type": "date", "type_config": {}},
    {"id": F_PUNTIL, "name": "Pausa até", "type": "date", "type_config": {}},
    {"id": F_PREASON, "name": "Motivo da pausa", "type": "short_text", "type_config": {}},
    {"id": F_PHIST, "name": "Histórico de pausas", "type": "text", "type_config": {}},
]


def make_task(task_id, parent=None, status="planejando", percent=0, duration=None, corrido=False, completed=None):
    status_type = next(s["type"] for s in STATUSES if s["status"] == status)
    values = {
        F_DURATION: None if duration is None else str(duration),
        F_PERCENT: {"current": str(percent), "percent_completed": percent / 100},
        F_CALENDAR: 1 if corrido else None,
        F_COMPLETION: None if completed is None else str(date_to_ms(completed)),
        F_FIXED: None,
        F_PFROM: None, F_PUNTIL: None, F_PREASON: None, F_PHIST: None,
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
        for i, t in enumerate(tasks):                  # ordem de criação, como no ClickUp
            t.setdefault("date_created", str(1_000 + i))
        self.tasks = {t["id"]: t for t in tasks}
        self.store_instead: dict[str, dict] = {}      # gravação que o ClickUp guarda diferente
        self.after_write: dict[str, object] = {}      # o que uma pessoa faz logo depois da gravação
        self.halfway_once: set[str] = set()           # a releitura mostra o início antigo (só 1 vez)
        self.drop_start_once: set[str] = set()        # o PUT descarta o início (e a resposta mostra)
        self.before_check = None                      # o que uma pessoa faz antes de o motor gravar
        self.freshness_checks = 0
        self.start, self.content, self.fields = start, content, list(fields)
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

    async def update_list(self, list_id, payload):
        if "start_date" in payload:
            self.start = ms_to_date(payload["start_date"])
        self.writes.append(("list", list_id, payload))

    async def get_tasks(self, list_id, include_closed=True, date_updated_gt=None):
        if list_id == "HOLIDAYS":
            return [{"id": f"h{i}", "due_date": str(date_to_ms(d))} for i, d in enumerate(self.holidays)]
        if date_updated_gt is not None:
            self.freshness_checks += 1
            hook, self.before_check = self.before_check, None
            if hook:
                hook()                                 # a pessoa mexe entre a leitura e a gravação
        return copy.deepcopy(list(self.tasks.values()))

    async def get_task(self, task_id):
        return copy.deepcopy(self.tasks[task_id])

    def _check(self, task_id):
        if task_id in self.fail_on:
            request = httpx.Request("PUT", "https://api.clickup.com")
            raise httpx.HTTPStatusError("boom", request=request, response=httpx.Response(400, text="recusado", request=request))

    async def update_task_fields(self, task_id, payload):
        self._check(task_id)
        task = self.tasks[task_id]
        old_start = task.get("start_date")
        for key in ("start_date", "due_date"):
            if key in payload:
                task[key] = str(self.store_instead.get(task_id, {}).get(key, payload[key]))
        if task_id in self.drop_start_once and "start_date" in payload:
            self.drop_start_once.discard(task_id)
            task["start_date"] = old_start
        if "status" in payload:
            status = next(s for s in STATUSES if s["status"] == payload["status"])
            task["status"] = {"status": status["status"], "type": status["type"]}
        self.writes.append(("task", task_id, payload))
        response = copy.deepcopy(task)                 # como a API: a tarefa depois da gravação
        if task_id in self.halfway_once and "start_date" in payload:
            self.halfway_once.discard(task_id)
            task["start_date"] = old_start
        hook = self.after_write.pop(task_id, None)
        if hook:
            hook()
        return response

    async def set_custom_field(self, task_id, field_id, value, value_options=None):
        self._check(task_id)
        field = next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)
        field["value"] = {"current": str(value["current"])} if isinstance(value, dict) else str(value)
        self.writes.append(("field", task_id, field_id, value))

    async def clear_custom_field(self, task_id, field_id):
        field = next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)
        field["value"] = None
        self.writes.append(("clear", task_id, field_id))

    async def create_custom_field(self, list_id, definition):
        field = {"id": "f-new-" + definition["name"], **definition}
        self.fields.append(field)
        for task in self.tasks.values():
            task["custom_fields"] = [cf for cf in task["custom_fields"] if cf["name"] != field["name"]]
            task["custom_fields"].append({**field, "value": None})
        self.writes.append(("create_field", definition["name"]))
        return field

    async def create_comment(self, task_id, text, notify_all=True):
        self.writes.append(("comment", task_id, text))
        return {"id": "c1"}

    # o que uma pessoa faz no ClickUp
    def type_dates(self, task_id, start=None, due=None):
        """Data escolhida no ClickUp sem hora = meia-noite em Angola (23:00 UTC do dia anterior)."""
        for key, day in (("start_date", start), ("due_date", due)):
            if day:
                midnight = datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(hours=1)))
                self.tasks[task_id][key] = str(int(midnight.timestamp() * 1000))

    # leitura cómoda para as asserções
    def dates(self, task_id):
        t = self.tasks[task_id]
        return ms_to_date(t["start_date"]), ms_to_date(t["due_date"])

    def value(self, task_id, field_id):
        return next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)["value"]

    def pause(self, task_id, start=None, until=None, reason=None, history=None):
        """O que uma pessoa preenche nos campos de pausa (data sem hora, meia-noite em Angola)."""
        def typed(day):
            midnight = datetime(day.year, day.month, day.day, tzinfo=timezone(timedelta(hours=1)))
            return str(int(midnight.timestamp() * 1000))
        for field_id, value in ((F_PFROM, start), (F_PUNTIL, until)):
            if value is not None:
                self._set(task_id, field_id, typed(value) if value else None)
        if reason is not None:
            self._set(task_id, F_PREASON, reason or None)
        if history is not None:
            self._set(task_id, F_PHIST, history or None)

    def _set(self, task_id, field_id, value):
        next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["id"] == field_id)["value"] = value

    def value_by_name(self, task_id, name):
        return next(cf for cf in self.tasks[task_id]["custom_fields"] if cf["name"] == name)["value"]

    def touched(self, task_id):
        return [w for w in self.writes if len(w) > 1 and w[1] == task_id]

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
        assert float(clickup.value("n1", F_DURATION)) == 17          # 2 + 1 + 14: soma das tarefas
        assert float(clickup.value("n2", F_DURATION)) == 3
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


async def test_clickup_server_errors_are_retried(monkeypatch):
    """O ClickUp devolve 500/502/503 de vez em quando (7 vezes em 3 dias em produção) e a
    execução inteira era perdida na primeira; agora tenta de novo, como já fazia no 429."""
    monkeypatch.setattr(schedule_service, "_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(schedule_service, "_WRITE_PAUSE_SECONDS", 0)
    calls = []

    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise httpx.HTTPStatusError("erro", request=httpx.Request("GET", "https://x"),
                                        response=httpx.Response(502 if len(calls) == 1 else 500))
        return "ok"

    assert await ScheduleService(None, None)._call(flaky) == "ok"
    assert len(calls) == 3


async def test_clickup_client_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr(schedule_service, "_RETRY_DELAY_SECONDS", 0)
    calls = []

    async def bad_request():
        calls.append(1)
        raise httpx.HTTPStatusError("erro", request=httpx.Request("PUT", "https://x"), response=httpx.Response(400))

    with pytest.raises(httpx.HTTPStatusError):
        await ScheduleService(None, None)._call(bad_request)
    assert len(calls) == 1


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


def test_zero_timestamp_means_no_date():
    # limpar a data de início de uma lista pela API deixa 0, não null
    assert ms_to_date(0) is None and ms_to_date("0") is None and ms_to_date(None) is None
    assert ms_to_date(date_to_ms(date(2026, 10, 13))) == date(2026, 10, 13)


def test_status_names_picks_the_three_automatic_statuses():
    names = status_names(STATUSES)
    assert (names.open, names.in_progress, names.done) == ("planejando", "fazendo", "complete")


class TestBaseline:
    """Linha de base: o plano fixado contra o qual o atraso é medido."""

    async def _rows(self, db):
        from sqlalchemy import select
        from src.models.schedule_models import ScheduleBaseline
        return {r.task_id: r for r in (await db.execute(select(ScheduleBaseline))).scalars().all()}

    async def test_first_run_stores_the_plan(self, db):
        summary = await _run(db, FakeClickUp(_project()))
        assert summary.baseline_captured
        assert summary.baseline_finish == date(2026, 10, 29) and summary.delay_days == 0
        rows = await self._rows(db)
        assert set(rows) == {"n1", "n2", "a", "b", "c"}
        assert (rows["a"].start, rows["a"].finish) == (date(2026, 10, 13), date(2026, 10, 14))
        assert all(r.list_id == LIST_ID for r in rows.values())

    async def test_slipping_shows_as_delay_and_the_baseline_stays_put(self, db):
        clickup = FakeClickUp(_project())
        await _run(db, clickup)
        late = await _run(db, clickup, today=date(2026, 10, 20))   # nada começou: tudo desliza
        assert not late.baseline_captured
        assert late.baseline_finish == date(2026, 10, 29)
        assert late.project_finish > date(2026, 10, 29)
        assert late.delay_days == (late.project_finish - date(2026, 10, 29)).days > 0

    async def test_first_baseline_is_the_plan_not_the_progress(self, db):
        tasks = _project()
        tasks[2] = make_task("a", parent="n2", duration=2, status="complete", percent=100,
                             completed=date(2026, 10, 13))            # terminou um dia antes do plano
        depends(tasks, "b", "a")
        summary = await _run(db, FakeClickUp(tasks), today=date(2026, 10, 13))
        assert summary.baseline_finish == date(2026, 10, 29)          # o plano puro, sem o adiantamento
        assert summary.delay_days is not None and summary.delay_days < 0

    async def test_dry_run_does_not_store_a_baseline(self, db):
        summary = await _run(db, FakeClickUp(_project()), dry_run=True)
        assert summary.baseline_finish is None and summary.delay_days is None
        assert await self._rows(db) == {}

    async def test_rebaseline_adopts_the_current_schedule_without_writing_to_clickup(self, db):
        clickup = FakeClickUp(_project())
        await _run(db, clickup)
        late = await _run(db, clickup, today=date(2026, 10, 20))
        writes = len(clickup.writes)
        reset = await ScheduleService(db, clickup).recalculate(
            LIST_ID, dry_run=True, today=date(2026, 10, 20), rebaseline=True)
        assert reset.baseline_captured and reset.delay_days == 0
        assert reset.baseline_finish == late.project_finish
        assert len(clickup.writes) == writes

    async def test_list_without_start_date_gets_no_baseline(self, db):
        summary = await _run(db, FakeClickUp(_project(), start=None))
        assert not summary.ok and await self._rows(db) == {}


# ─── Datas digitadas à mão ───────────────────────────────────────────────────

def _chains():
    """Disciplina n1 → grupo n2 com a → b; c depende de b; x → y é outra cadeia, sem
    ligação com a primeira. Semana com folga só ao domingo; o projeto começa terça 13/10:
    a 13–14, b 15, c 16–19 (sex, sáb, seg), x 13–14, y 15."""
    tasks = [
        make_task("n1"),
        make_task("n2", parent="n1"),
        make_task("a", parent="n2", duration=2),
        make_task("b", parent="n2", duration=1),
        make_task("c", parent="n1", duration=3),
        make_task("x", parent="n1", duration=2),
        make_task("y", parent="n1", duration=1),
    ]
    depends(tasks, "b", "a")
    depends(tasks, "c", "b")
    depends(tasks, "y", "x")
    return tasks


async def _planned(db, tasks=None, **kwargs):
    """Lista já calculada uma vez pelo motor (o estado guarda as datas que ele deixou)."""
    clickup = FakeClickUp(tasks or _chains(), **kwargs)
    await _run(db, clickup)
    assert clickup.dates("c") == (date(2026, 10, 16), date(2026, 10, 19))
    clickup.writes.clear()
    return clickup


class TestManualDates:
    async def test_delaying_the_due_date_moves_only_the_tasks_that_depend_on_it(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 16))

        summary = await _run(db, clickup)

        assert summary.ok, summary.errors
        assert float(clickup.value("a", F_DURATION)) == 4                  # ter → sex
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 16))
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))
        assert clickup.dates("n2") == (date(2026, 10, 13), date(2026, 10, 17))
        assert clickup.dates("n1") == (date(2026, 10, 13), date(2026, 10, 21))
        assert clickup.touched("x") == [] and clickup.touched("y") == []
        assert clickup.value("a", F_FIXED) is None                         # só o vencimento mudou

    async def test_bringing_the_due_date_forward_pulls_the_successors(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 13))

        await _run(db, clickup)

        assert float(clickup.value("a", F_DURATION)) == 1
        assert clickup.dates("b") == (date(2026, 10, 14), date(2026, 10, 14))
        assert clickup.dates("c") == (date(2026, 10, 15), date(2026, 10, 17))

    async def test_moving_both_dates_keeps_the_duration_and_fixes_the_start(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 15), due=date(2026, 10, 16))

        await _run(db, clickup)

        assert float(clickup.value("a", F_DURATION)) == 2
        assert ms_to_date(clickup.value("a", F_FIXED)) == date(2026, 10, 15)
        assert clickup.dates("a") == (date(2026, 10, 15), date(2026, 10, 16))
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))
        assert clickup.touched("x") == []

    async def test_changing_start_and_due_by_different_amounts_sets_both(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 14), due=date(2026, 10, 17))

        await _run(db, clickup)

        assert ms_to_date(clickup.value("a", F_FIXED)) == date(2026, 10, 14)
        assert float(clickup.value("a", F_DURATION)) == 4                  # qua, qui, sex, sáb
        assert clickup.dates("a") == (date(2026, 10, 14), date(2026, 10, 17))
        assert clickup.dates("b") == (date(2026, 10, 19), date(2026, 10, 19))

    async def test_changing_only_the_start_keeps_the_duration(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 15))                  # o vencimento fica 14

        await _run(db, clickup)

        assert float(clickup.value("a", F_DURATION)) == 2
        assert clickup.dates("a") == (date(2026, 10, 15), date(2026, 10, 16))

    async def test_a_second_run_after_an_edit_writes_nothing(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 15), due=date(2026, 10, 16))
        await _run(db, clickup)
        clickup.writes.clear()

        summary = await _run(db, clickup)

        assert summary.changed == 0 and clickup.writes == []
        assert clickup.dates("a") == (date(2026, 10, 15), date(2026, 10, 16))

    async def test_due_date_typed_on_a_calendar_day_task_is_honoured(self, db):
        """Cura do betão ("Corrido"): o vencimento digitado vira a duração em dias corridos que
        termina nesse dia — fracionada se for preciso, como nas tarefas de dias úteis. Antes saía
        em dias corridos inteiros e a conversão para dias úteis (× 6/7) terminava um dia depois
        (achado no fuzz de 2026-10-22, Saurimo)."""
        clickup = FakeClickUp(_project())
        await _run(db, clickup)                                   # c: 14 corridos, 16–29/10
        clickup.type_dates("c", due=date(2026, 11, 2))

        await _run(db, clickup)

        assert clickup.dates("c") == (date(2026, 10, 16), date(2026, 11, 2))
        assert float(clickup.value("c", F_DURATION)) == 17.5     # 15 dias úteis × 7/6

    async def test_due_date_typed_on_a_calendar_day_task_in_progress_is_honoured(self, db):
        clickup = FakeClickUp(_project())
        await _run(db, clickup)
        clickup.tasks["c"]["status"] = {"status": "fazendo", "type": "custom"}
        clickup._set("c", F_PERCENT, {"current": "50"})
        clickup.type_dates("c", start=date(2026, 10, 16), due=date(2026, 11, 2))

        await _run(db, clickup, today=date(2026, 10, 16))

        assert clickup.dates("c")[1] == date(2026, 11, 2)

    async def test_typed_dates_are_rewritten_in_the_engine_format(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 16))

        await _run(db, clickup)

        assert clickup.tasks["a"]["due_date"] == str(date_to_ms(date(2026, 10, 16)))

    async def test_start_before_the_predecessor_finishes_wins_with_an_alert(self, db):
        """Decisão de 22/10/2026: a data digitada vence a dependência ("Must start on")."""
        clickup = await _planned(db)
        clickup.type_dates("b", start=date(2026, 10, 13), due=date(2026, 10, 13))

        summary = await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 13), date(2026, 10, 13))     # a termina 14
        assert clickup.dates("c") == (date(2026, 10, 14), date(2026, 10, 16))     # c segue b
        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and comments[0][1] == "b"
        assert '"A"' in comments[0][2] and "14/10/2026" in comments[0][2] and "13/10/2026" in comments[0][2]
        assert any("antes do fim" in w for w in summary.warnings)

    async def test_a_fixed_start_stays_when_the_predecessor_slips_later(self, db):
        clickup = await _planned(db)
        clickup.type_dates("b", start=date(2026, 10, 17), due=date(2026, 10, 17))
        await _run(db, clickup)
        clickup.type_dates("a", due=date(2026, 10, 20))                          # a passa a terminar 20

        await _run(db, clickup)

        assert clickup.dates("b")[0] == date(2026, 10, 17)

    async def test_start_on_a_rest_day_just_moves_to_the_next_workday_without_a_comment(self, db):
        clickup = await _planned(db)
        clickup.type_dates("x", start=date(2026, 10, 18), due=date(2026, 10, 19))   # domingo → segunda

        summary = await _run(db, clickup)

        assert clickup.dates("x") == (date(2026, 10, 19), date(2026, 10, 20))
        assert not [w for w in clickup.writes if w[0] == "comment"]
        assert not any("não foi possível" in w for w in summary.warnings)

    async def test_rest_day_start_blocked_by_the_predecessor_names_the_predecessor(self, db):
        clickup = await _planned(db)
        clickup.type_dates("c", start=date(2026, 10, 11), due=date(2026, 10, 14))   # domingo, antes de b

        await _run(db, clickup)

        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and '"B"' in comments[0][2]

    async def test_start_in_the_past_is_explained(self, db):
        clickup = await _planned(db)
        clickup.type_dates("x", start=date(2026, 10, 13), due=date(2026, 10, 14))   # sem mudança
        clickup.type_dates("y", start=date(2026, 10, 14), due=date(2026, 10, 14))

        summary = await _run(db, clickup, today=date(2026, 10, 15))

        assert clickup.dates("y")[0] == date(2026, 10, 15)
        assert any("já passou" in w for w in summary.warnings)

    async def test_tasks_outside_the_chain_keep_their_dates_even_if_something_else_changed(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 16))
        clickup.tasks["x"]["custom_fields"][0]["value"] = "5"              # outra mudança, noutra cadeia

        await _run(db, clickup)
        assert clickup.dates("x") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("y") == (date(2026, 10, 15), date(2026, 10, 15))

        await _run(db, clickup)                                            # o recálculo seguinte é completo
        assert clickup.dates("x") == (date(2026, 10, 13), date(2026, 10, 17))
        assert clickup.dates("y") == (date(2026, 10, 19), date(2026, 10, 19))

    async def test_clearing_the_fixed_start_returns_the_task_to_its_dependencies(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 15), due=date(2026, 10, 16))
        await _run(db, clickup)

        clickup._set("a", F_FIXED, None)                                     # apaga o "Início fixado"
        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("c") == (date(2026, 10, 16), date(2026, 10, 19))

    async def test_due_date_of_a_completed_task_becomes_its_completion_date(self, db):
        tasks = _chains()
        tasks[2] = make_task("a", parent="n2", duration=2, status="complete", percent=100,
                             completed=date(2026, 10, 14))
        depends(tasks, "b", "a")
        clickup = await _planned(db, tasks)
        clickup.type_dates("a", due=date(2026, 10, 16))

        await _run(db, clickup, today=date(2026, 10, 16))

        assert ms_to_date(clickup.value("a", F_COMPLETION)) == date(2026, 10, 16)
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))

    async def test_due_before_start_is_refused_and_reported(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 12))

        summary = await _run(db, clickup)

        assert float(clickup.value("a", F_DURATION)) == 2
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert any("vencimento antes do início" in w for w in summary.warnings)

    async def test_editing_a_group_is_undone(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n2", due=date(2026, 10, 20))

        await _run(db, clickup)

        assert clickup.dates("n2") == (date(2026, 10, 13), date(2026, 10, 15))

    async def test_without_known_dates_nothing_counts_as_an_edit(self, db):
        from sqlalchemy import update
        from src.models.schedule_models import ScheduleTaskState
        clickup = await _planned(db)
        await db.execute(update(ScheduleTaskState).values(start=None, due=None))   # estado antigo
        await db.commit()
        clickup.type_dates("a", due=date(2026, 10, 16))

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert float(clickup.value("a", F_DURATION)) == 2

    async def test_dry_run_shows_the_edit_without_writing(self, db):
        clickup = await _planned(db)
        clickup.type_dates("a", due=date(2026, 10, 16))

        summary = await _run(db, clickup, dry_run=True)

        assert clickup.writes == []
        changed = {c["name"]: c["changes"] for c in summary.changes}
        assert changed["A"]["duracao"] == [2.0, 4.0]
        assert changed["C"]["fim"] == ["2026-10-19", "2026-10-21"]
        assert "X" not in changed

    async def test_missing_fixed_start_field_is_created(self, db):
        clickup = await _planned(db, fields=[f for f in FIELDS if f["id"] != F_FIXED])
        clickup.type_dates("a", start=date(2026, 10, 15), due=date(2026, 10, 16))

        summary = await _run(db, clickup)

        assert summary.ok, summary.errors
        assert ("create_field", "Início fixado") in clickup.writes
        assert ms_to_date(clickup.value_by_name("a", "Início fixado")) == date(2026, 10, 15)


class TestEditsFoundInTheRealClickUp:
    """Casos que apareceram no teste de comportamento numa lista real (2026-10-19)."""

    def _half_day(self):
        """a termina a meio do dia (0,5): b começa a meio do dia 13 e c depende de b."""
        tasks = [make_task("n1"), make_task("a", parent="n1", duration=0.5),
                 make_task("b", parent="n1", duration=2), make_task("c", parent="n1", duration=1),
                 make_task("x", parent="n1", duration=1)]
        depends(tasks, "b", "a")
        depends(tasks, "c", "b")
        return tasks

    async def test_typed_due_is_kept_when_the_task_starts_in_the_middle_of_a_day(self, db):
        clickup = FakeClickUp(self._half_day())
        await _run(db, clickup)
        assert clickup.dates("b") == (date(2026, 10, 13), date(2026, 10, 15))      # 13,5 → 15,5
        clickup.type_dates("b", due=date(2026, 10, 17))

        await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 13), date(2026, 10, 17))      # o dia digitado
        assert float(clickup.value("b", F_DURATION)) == 4.5                        # de 13,5 ao fim de 17
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 19))      # 18 é domingo

    async def test_pinned_predecessor_keeps_its_half_day(self, db):
        clickup = FakeClickUp(self._half_day())
        await _run(db, clickup)
        clickup.type_dates("c", due=date(2026, 10, 17))                            # mexe só no fim da cadeia

        await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 13), date(2026, 10, 15))      # b não salta para o dia 14
        assert clickup.dates("c") == (date(2026, 10, 15), date(2026, 10, 17))

    async def test_typed_due_of_a_task_in_progress_is_kept(self, db):
        tasks = _chains()
        tasks[2] = make_task("a", parent="n2", duration=4, status="fazendo", percent=50)
        tasks[2]["start_date"] = str(date_to_ms(date(2026, 10, 13)))
        depends(tasks, "b", "a")
        clickup = FakeClickUp(tasks)
        await _run(db, clickup, today=date(2026, 10, 15))
        clickup.type_dates("a", due=date(2026, 10, 20))

        await _run(db, clickup, today=date(2026, 10, 15))

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 20))
        assert float(clickup.value("a", F_DURATION)) == 10      # 50% feito: faltam 5 dias (15, 16, 17, 19, 20)
        assert clickup.dates("b")[0] == date(2026, 10, 21)

    async def test_due_before_today_on_a_task_in_progress_is_refused(self, db):
        tasks = [make_task("a", duration=4, status="fazendo", percent=50)]
        tasks[0]["start_date"] = str(date_to_ms(date(2026, 10, 13)))
        clickup = FakeClickUp(tasks)
        await _run(db, clickup, today=date(2026, 10, 15))
        clickup.type_dates("a", due=date(2026, 10, 14))

        summary = await _run(db, clickup, today=date(2026, 10, 15))

        assert float(clickup.value("a", F_DURATION)) == 4
        assert any("antes de hoje" in w for w in summary.warnings)

    async def test_first_row_is_the_first_created_whatever_the_orderindex(self, db):
        clickup = await _planned(db, self._with_second_discipline())
        clickup.tasks["n1"]["orderindex"] = "9999"                 # o ClickUp reordena ao editar
        clickup.tasks["t1"]["orderindex"] = "1"
        clickup.type_dates("n1", start=date(2026, 10, 20))

        await _run(db, clickup)

        assert clickup.start == date(2026, 10, 20)
        assert clickup.dates("a")[0] == date(2026, 10, 20)

    def _with_second_discipline(self):
        return _chains() + [make_task("t1"), make_task("z", parent="t1", duration=1)]

    async def test_a_date_the_clickup_stores_differently_is_not_taken_as_typed(self, db):
        clickup = await _planned(db)
        clickup.store_instead["c"] = {"start_date": date_to_ms(date(2026, 10, 18))}   # guarda outro início
        clickup.type_dates("a", due=date(2026, 10, 16))

        first = await _run(db, clickup)
        assert any("o ClickUp ficou com" in w for w in first.warnings)

        clickup.store_instead.clear()
        clickup.writes.clear()
        second = await _run(db, clickup)

        assert clickup.value("c", F_FIXED) is None                                 # nada de "Início fixado"
        assert not [w for w in clickup.writes if w[0] == "comment"]
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))      # o motor só corrige a data
        assert second.ok


class TestWritesRacingWithPeople:
    """O motor relê a lista depois de gravar. O que mudou entre a gravação e a releitura
    é de uma pessoa (ou um tropeço do ClickUp) — nunca pode ser desfeito em silêncio."""

    async def test_an_edit_made_right_after_the_engine_wrote_the_task_is_kept(self, db):
        clickup = await _planned(db)
        clickup.after_write["c"] = lambda: clickup.type_dates("c", start=date(2026, 10, 22))
        clickup.type_dates("a", due=date(2026, 10, 16))       # a cresce → b e c são regravadas

        await _run(db, clickup)                                # a pessoa mexe em c logo depois do motor
        second = await _run(db, clickup)
        assert second.ok
        assert clickup.dates("c") == (date(2026, 10, 22), date(2026, 10, 24))   # respeitada, 3 dias
        assert clickup.value("c", F_FIXED) is not None

    async def test_an_edit_made_between_the_read_and_the_write_is_not_overwritten(self, db):
        clickup = await _planned(db)
        clickup.before_check = lambda: clickup.type_dates("c", start=date(2026, 10, 22))
        clickup.type_dates("a", due=date(2026, 10, 16))       # a cresce → b e c seriam regravadas

        first = await _run(db, clickup)
        assert first.ok
        assert not [w for w in clickup.touched("c") if w[0] == "task"]   # o motor não passa por cima

        await _run(db, clickup)                                # a execução que o webhook dispara
        assert clickup.dates("c") == (date(2026, 10, 22), date(2026, 10, 24))
        assert ms_to_date(clickup.value("c", F_FIXED)) == date(2026, 10, 22)

    async def test_writes_are_checked_for_fresh_changes_in_small_batches(self, db, monkeypatch):
        monkeypatch.setattr(schedule_service, "_CHECK_EVERY", 2)
        clickup = FakeClickUp(_chains())
        await _run(db, clickup)                                # 7 tarefas gravadas
        assert clickup.freshness_checks >= 4

    async def test_a_start_the_clickup_drops_on_the_put_is_written_again(self, db):
        """Visto no ClickUp real: a resposta do PUT já vem com o início antigo."""
        clickup = await _planned(db)
        clickup.drop_start_once.add("c")
        clickup.type_dates("a", due=date(2026, 10, 16))

        summary = await _run(db, clickup)

        assert summary.ok
        assert not any("ficou com" in w for w in summary.warnings)
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))

    async def test_a_date_the_clickup_applies_only_halfway_is_written_again(self, db):
        clickup = await _planned(db)
        clickup.halfway_once.add("c")                          # visto no ClickUp real: o início não fica
        clickup.type_dates("a", due=date(2026, 10, 16))

        summary = await _run(db, clickup)
        assert summary.ok
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))

        clickup.writes.clear()
        await _run(db, clickup)
        assert clickup.value("c", F_FIXED) is None                                 # nada de edição fantasma
        assert not [w for w in clickup.writes if w[0] == "comment"]


class TestSummaryEdits:
    """Datas digitadas num grupo ou disciplina (resumo). Decisão de 22/10/2026: mudar o
    início move o bloco — vira "não começar antes de" para todas as tarefas dele, com as
    dependências valendo; um vencimento digitado num resumo é desfeito, com comentário."""

    async def test_moving_a_group_start_holds_the_whole_block(self, db):
        clickup = await _planned(db)                      # n2 = grupo com a → b, 13–15
        clickup.type_dates("n2", start=date(2026, 10, 19))

        summary = await _run(db, clickup)

        assert summary.ok, summary.errors
        assert ms_to_date(clickup.value("n2", F_FIXED)) == date(2026, 10, 19)
        assert clickup.dates("a") == (date(2026, 10, 19), date(2026, 10, 20))
        assert clickup.dates("b") == (date(2026, 10, 21), date(2026, 10, 21))
        assert clickup.dates("n2") == (date(2026, 10, 19), date(2026, 10, 21))
        assert clickup.dates("c") == (date(2026, 10, 22), date(2026, 10, 24))  # c depende de b
        assert clickup.touched("x") == []                                      # outra cadeia
        assert not [w for w in clickup.writes if w[0] == "comment"]

        clickup.writes.clear()
        second = await _run(db, clickup)
        assert second.changed == 0 and clickup.writes == []

    async def test_a_group_start_still_waits_for_the_dependencies(self, db):
        clickup = await _planned(db, TestAcrossDisciplines()._two_disciplines())
        clickup.type_dates("t2", start=date(2026, 10, 13))                    # z espera a (13–14)

        await _run(db, clickup)

        assert ms_to_date(clickup.value("t2", F_FIXED)) == date(2026, 10, 13)
        assert clickup.dates("z") == (date(2026, 10, 15), date(2026, 10, 16))
        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and comments[0][1] == "t2" and '"A"' in comments[0][2]

    async def test_dragging_a_group_moves_the_block(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n2", start=date(2026, 10, 15), due=date(2026, 10, 17))   # +2 dias

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 15), date(2026, 10, 16))
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))
        assert not [w for w in clickup.writes if w[0] == "comment"]

    async def test_changing_only_the_due_date_of_a_group_is_undone_and_explained(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n2", due=date(2026, 10, 20))

        await _run(db, clickup)

        assert clickup.dates("n2") == (date(2026, 10, 13), date(2026, 10, 15))
        assert clickup.value("n2", F_FIXED) is None
        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and comments[0][1] == "n2"

    async def test_moving_a_group_carries_the_fixed_starts_inside_it(self, db):
        """Mover o bloco desloca o "começa em" das tarefas dele pela mesma distância."""
        clickup = await _planned(db)
        clickup.type_dates("b", start=date(2026, 10, 16), due=date(2026, 10, 16))   # b "começa em" 16
        await _run(db, clickup)
        clickup.type_dates("n2", start=date(2026, 10, 20))                         # 13 → 20: +7 dias

        await _run(db, clickup)

        assert ms_to_date(clickup.value("b", F_FIXED)) == date(2026, 10, 23)
        assert clickup.dates("a") == (date(2026, 10, 20), date(2026, 10, 21))
        assert clickup.dates("b") == (date(2026, 10, 23), date(2026, 10, 23))

    async def test_a_fixed_start_ahead_of_its_predecessor_keeps_its_lead_when_the_group_moves(self, db):
        """Como a AC Distribution Panel de Lubango: posta antes do fim da antecessora e depois
        a disciplina inteira adiada — continua à frente, pela mesma distância."""
        clickup = await _planned(db, TestAcrossDisciplines()._two_disciplines())   # z espera a (13–14)
        clickup.type_dates("z", start=date(2026, 10, 13), due=date(2026, 10, 14))   # z na frente de a
        await _run(db, clickup)
        clickup.type_dates("t1", start=date(2026, 10, 20))                         # disciplina +7

        await _run(db, clickup)

        assert clickup.dates("z")[0] == date(2026, 10, 20)
        assert clickup.dates("t1")[0] == date(2026, 10, 20)

    async def test_moving_a_group_earlier_carries_its_fixed_starts_too(self, db):
        clickup = await _planned(db)
        clickup.type_dates("b", start=date(2026, 10, 24), due=date(2026, 10, 24))
        await _run(db, clickup)
        clickup.type_dates("n2", start=date(2026, 10, 9))                          # 13 → 9: −4 dias

        await _run(db, clickup)

        assert ms_to_date(clickup.value("b", F_FIXED)) == date(2026, 10, 20)
        assert clickup.dates("b") == (date(2026, 10, 20), date(2026, 10, 20))
        # "não começar antes de" é um piso: a não vai para antes do início do projeto (13)
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and comments[0][1] == "n2" and "o projeto começa em 13/10/2026" in comments[0][2]

    async def test_clearing_the_group_floor_lets_the_block_come_back(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n2", start=date(2026, 10, 19))
        await _run(db, clickup)
        clickup._set("n2", F_FIXED, None)

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("n2") == (date(2026, 10, 13), date(2026, 10, 15))


class TestStaleState:
    """Estado guardado desatualizado (banco restaurado de um backup, gravação do estado que
    falhou): todas as diferenças pareceriam datas digitadas — e com "a data digitada vence a
    dependência" isso criaria dezenas de "começa em" falsos. Nenhuma pessoa mexe em tantas
    tarefas entre duas execuções: aí o motor não trata nada como edição e avisa."""

    async def test_too_many_typed_dates_at_once_are_not_taken_as_edits(self, db, monkeypatch):
        monkeypatch.setattr(schedule_service, "_MAX_EDITS_PER_RUN", 2)
        clickup = await _planned(db)
        for task_id in ("a", "c", "x"):                    # 3 tarefas andaram 1 dia "sozinhas"
            start, due = clickup.dates(task_id)
            clickup.type_dates(task_id, start=start + timedelta(days=2), due=due + timedelta(days=2))

        summary = await _run(db, clickup)

        assert any("estado guardado" in w for w in summary.warnings)
        assert all(clickup.value(t, F_FIXED) is None for t in ("a", "c", "x"))
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))      # de volta ao cálculo
        assert not [w for w in clickup.writes if w[0] == "comment"]

    async def test_a_few_edits_are_still_edits(self, db, monkeypatch):
        monkeypatch.setattr(schedule_service, "_MAX_EDITS_PER_RUN", 2)
        clickup = await _planned(db)
        clickup.type_dates("a", start=date(2026, 10, 15), due=date(2026, 10, 16))
        clickup.type_dates("x", start=date(2026, 10, 15), due=date(2026, 10, 16))

        await _run(db, clickup)

        assert ms_to_date(clickup.value("a", F_FIXED)) == date(2026, 10, 15)


class TestAcrossDisciplines:
    """Subtarefa de uma disciplina que espera por subtarefa de outra disciplina."""

    def _two_disciplines(self):
        tasks = _chains() + [
            make_task("t1"),                                  # 2ª disciplina (ex.: Área Técnica)
            make_task("t2", parent="t1"),
            make_task("z", parent="t2", duration=2),
            make_task("w", parent="t2", duration=1),
        ]
        depends(tasks, "z", "a")                              # z (Área Técnica) espera a (Obra Civil)
        depends(tasks, "w", "z")
        return tasks

    async def test_successor_in_another_discipline_follows_its_predecessor(self, db):
        clickup = FakeClickUp(self._two_disciplines())
        await _run(db, clickup)
        assert clickup.dates("z") == (date(2026, 10, 15), date(2026, 10, 16))     # depois de a (13–14)
        assert clickup.dates("w") == (date(2026, 10, 17), date(2026, 10, 17))
        assert float(clickup.value("t1", F_DURATION)) == 3                        # 2 + 1

        clickup.writes.clear()
        clickup.type_dates("a", due=date(2026, 10, 16))                           # a atrasa 2 dias
        await _run(db, clickup)

        assert clickup.dates("z") == (date(2026, 10, 17), date(2026, 10, 19))     # sáb, (dom), seg
        assert clickup.dates("w") == (date(2026, 10, 20), date(2026, 10, 20))
        assert clickup.dates("t1") == (date(2026, 10, 17), date(2026, 10, 20))    # a disciplina acompanha
        assert clickup.touched("x") == [] and clickup.touched("y") == []

    async def test_dependency_on_a_whole_task_waits_for_all_its_subtasks(self, db):
        tasks = self._two_disciplines()
        for t in tasks:                                       # troca: z espera o grupo n2 inteiro (a e b)
            t["dependencies"] = [d for d in t["dependencies"] if not (d["task_id"] == "z" and d["depends_on"] == "a")]
        depends(tasks, "z", "n2")
        clickup = FakeClickUp(tasks)

        await _run(db, clickup)

        assert clickup.dates("z")[0] == date(2026, 10, 16)                        # depois de b (15)


class TestProjectStart:
    """A data de início posta na primeira linha (a disciplina do topo) dá a partida no projeto."""

    async def test_first_row_start_dates_a_list_that_had_no_start(self, db):
        clickup = FakeClickUp(_chains(), start=None)
        clickup.type_dates("n1", start=date(2026, 10, 13))

        summary = await _run(db, clickup)

        assert summary.ok, summary.errors
        assert clickup.start == date(2026, 10, 13)                          # gravado na lista
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))
        assert clickup.dates("c") == (date(2026, 10, 16), date(2026, 10, 19))
        assert clickup.dates("y") == (date(2026, 10, 15), date(2026, 10, 15))
        assert clickup.dates("n1") == (date(2026, 10, 13), date(2026, 10, 19))
        assert clickup.tasks["n1"]["start_date"] == str(date_to_ms(date(2026, 10, 13)))   # normalizada

    async def test_changing_the_first_row_moves_the_whole_project(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n1", start=date(2026, 10, 20))

        await _run(db, clickup)

        assert clickup.start == date(2026, 10, 20)
        assert clickup.dates("a") == (date(2026, 10, 20), date(2026, 10, 21))
        assert clickup.dates("b") == (date(2026, 10, 22), date(2026, 10, 22))
        assert clickup.dates("c") == (date(2026, 10, 23), date(2026, 10, 26))   # sex, sáb, seg
        assert clickup.dates("x") == (date(2026, 10, 20), date(2026, 10, 21))   # todas as cadeias andam
        assert clickup.dates("y") == (date(2026, 10, 22), date(2026, 10, 22))

        assert not [w for w in clickup.writes if w[0] == "comment"]
        clickup.writes.clear()
        summary = await _run(db, clickup)
        assert summary.changed == 0 and clickup.writes == []

    async def test_first_row_can_also_bring_the_project_forward(self, db):
        clickup = await _planned(db)
        clickup.type_dates("n1", start=date(2026, 10, 9))

        await _run(db, clickup)

        assert clickup.start == date(2026, 10, 9)
        assert clickup.dates("a") == (date(2026, 10, 9), date(2026, 10, 10))

    async def test_list_start_still_works_and_the_first_row_follows_it(self, db):
        clickup = await _planned(db)
        clickup.start = date(2026, 10, 20)                                  # mudado nas configurações da lista

        await _run(db, clickup)

        assert clickup.dates("n1")[0] == date(2026, 10, 20)
        assert clickup.dates("a") == (date(2026, 10, 20), date(2026, 10, 21))

    async def test_without_any_start_nothing_is_written(self, db):
        clickup = FakeClickUp(_chains(), start=None)

        summary = await _run(db, clickup)

        assert not summary.ok and "primeira linha" in summary.errors[0]
        assert clickup.writes == []

    async def test_start_in_the_past_is_reported(self, db):
        clickup = FakeClickUp(_chains(), start=None)
        clickup.type_dates("n1", start=date(2026, 10, 1))

        summary = await _run(db, clickup)

        assert any("já passou" in w for w in summary.warnings)
        assert clickup.dates("a")[0] == TODAY                               # não iniciada: começa hoje

    async def test_a_project_start_the_first_row_cannot_show_is_explained(self, db):
        """A primeira linha é um resumo: com uma tarefa concluída antes, ela continua a mostrar
        o início dessa tarefa — o motor explica, num comentário, que o início mudou."""
        tasks = [make_task("x", parent="n1", duration=2, status="complete", percent=100,
                           completed=date(2026, 10, 9)) if t["id"] == "x" else t for t in _chains()]
        clickup = await _planned(db, tasks)
        clickup.type_dates("n1", start=date(2026, 10, 20))

        await _run(db, clickup)

        assert clickup.start == date(2026, 10, 20)
        assert clickup.dates("n1")[0] < date(2026, 10, 20)
        comments = [w for w in clickup.writes if w[0] == "comment"]
        assert len(comments) == 1 and comments[0][1] == "n1" and "20/10/2026" in comments[0][2]

    async def test_dry_run_does_not_touch_the_list(self, db):
        clickup = FakeClickUp(_chains(), start=None)
        clickup.type_dates("n1", start=date(2026, 10, 13))

        summary = await _run(db, clickup, dry_run=True)

        assert clickup.start is None and clickup.writes == []
        assert any(c["name"] == "(início do projeto)" for c in summary.changes)


def test_debounce_default_is_five_seconds():
    from src.core.config import Settings
    assert Settings.model_fields["schedule_debounce_seconds"].default == 5.0


class TestPauses:
    """Pausa: os dias parados não contam como trabalho; a tarefa e as que dependem dela andam."""

    async def test_pause_in_the_middle_moves_the_task_and_its_successors_only(self, db):
        clickup = await _planned(db)                       # a 13–14, b 15, c 16–19, x 13–14, y 15
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16), reason="chuva")

        summary = await _run(db, clickup)

        assert summary.ok, summary.errors
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))     # começa depois da pausa
        assert clickup.dates("c") == (date(2026, 10, 19), date(2026, 10, 21))
        assert clickup.dates("a") == (date(2026, 10, 13), date(2026, 10, 14))     # antes: não muda
        assert clickup.touched("x") == [] and clickup.touched("y") == []          # outra cadeia: não muda
        assert float(clickup.value("b", F_DURATION)) == 1                         # a duração fica

    async def test_extending_only_the_end_of_the_pause_pushes_further(self, db):
        clickup = await _planned(db)
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16))
        await _run(db, clickup)

        clickup.pause("b", until=date(2026, 10, 20))
        await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 21), date(2026, 10, 21))
        assert clickup.dates("c") == (date(2026, 10, 22), date(2026, 10, 24))

    async def test_cancelling_a_future_pause_brings_the_dates_back(self, db):
        clickup = await _planned(db)
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16))
        await _run(db, clickup)

        clickup.pause("b", start=False, until=False)                              # apaga as datas
        await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 15), date(2026, 10, 15))
        assert clickup.value("b", F_PHIST) is None                                # não vai para o histórico

    async def test_pause_on_a_group_applies_to_all_its_tasks(self, db):
        clickup = await _planned(db)
        clickup.pause("n2", start=date(2026, 10, 13), until=date(2026, 10, 14), reason="licença")

        await _run(db, clickup)

        assert clickup.dates("a") == (date(2026, 10, 15), date(2026, 10, 16))
        assert clickup.dates("b") == (date(2026, 10, 17), date(2026, 10, 17))
        assert clickup.dates("n2") == (date(2026, 10, 15), date(2026, 10, 17))

    async def test_open_ended_pause_slides_day_by_day(self, db):
        clickup = await _planned(db)
        clickup.pause("x", start=date(2026, 10, 13), reason="aguarda material")   # sem "Pausa até"

        await _run(db, clickup, today=date(2026, 10, 13))
        assert clickup.dates("x") == (date(2026, 10, 14), date(2026, 10, 15))
        await _run(db, clickup, today=date(2026, 10, 14))
        assert clickup.dates("x") == (date(2026, 10, 15), date(2026, 10, 16))
        assert clickup.dates("y") == (date(2026, 10, 17), date(2026, 10, 17))

    async def test_finished_pause_is_archived_and_the_fields_cleared(self, db):
        clickup = await _planned(db)
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16), reason="chuva")
        await _run(db, clickup)

        summary = await _run(db, clickup, today=date(2026, 10, 19))

        assert summary.ok
        assert clickup.value("b", F_PHIST) == "15/10/2026 – 16/10/2026 · chuva"
        assert clickup.value("b", F_PFROM) is None and clickup.value("b", F_PUNTIL) is None
        assert clickup.value("b", F_PREASON) is None

    async def test_new_pause_right_after_an_archived_one_is_merged(self, db):
        clickup = await _planned(db)
        clickup.pause("b", history="15/10/2026 – 16/10/2026 · chuva")
        clickup.pause("b", start=date(2026, 10, 17), until=date(2026, 10, 19), reason="chuva")

        await _run(db, clickup, today=date(2026, 10, 20))

        assert clickup.value("b", F_PHIST) == "15/10/2026 – 19/10/2026 · chuva"

    async def test_unreadable_history_line_is_kept_and_reported(self, db):
        clickup = await _planned(db)
        clickup.pause("b", history="parou uns dias em setembro")

        summary = await _run(db, clickup)

        assert any("histórico de pausas" in w for w in summary.warnings)
        assert clickup.value("b", F_PHIST) == "parou uns dias em setembro"

    async def test_list_without_pause_fields_ignores_pauses(self, db):
        clickup = await _planned(db, fields=[f for f in FIELDS if f["id"] not in (F_PFROM, F_PUNTIL, F_PREASON, F_PHIST)])
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16))

        await _run(db, clickup)

        assert clickup.dates("b") == (date(2026, 10, 15), date(2026, 10, 15))

    async def test_second_run_with_a_pause_writes_nothing(self, db):
        clickup = await _planned(db)
        clickup.pause("b", start=date(2026, 10, 15), until=date(2026, 10, 16))
        await _run(db, clickup)
        clickup.writes.clear()

        summary = await _run(db, clickup)

        assert summary.changed == 0 and clickup.writes == []
