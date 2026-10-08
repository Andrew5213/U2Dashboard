"""Cache e dashboard sobre uma lista de cronograma (3 níveis, peso por duração)."""
from datetime import date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base
from src.models.cache_models import ClickUpTaskCache
from src.repositories.cache_repository import CacheRepository, _FIELD_VENCIMENTO_ID
from src.services.dashboard_service import DashboardService
from src.services.schedule_fields import date_to_ms
from src.services.weights_config import compute_list_progress, compute_task_progress

CALENDAR_OPTIONS = [{"id": "u", "name": "Útil", "orderindex": 0}, {"id": "c", "name": "Corrido", "orderindex": 1}]


def schedule_task(task_id, parent=None, percent=0, duration=None, corrido=False, status="planejando",
                  status_type="open", due=None):
    return {
        "id": task_id, "name": task_id, "parent": parent, "list": {"id": "L1"},
        "status": {"status": status, "type": status_type},
        "due_date": str(date_to_ms(due)) if due else None,
        "start_date": None,
        "custom_fields": [
            {"id": "p", "name": "% Concluído", "type": "manual_progress",
             "value": {"current": str(percent), "percent_completed": percent / 100}},
            {"id": "d", "name": "Duração (dias)", "type": "number",
             "value": None if duration is None else str(duration)},
            {"id": "k", "name": "Calendário", "type": "drop_down",
             "type_config": {"options": CALENDAR_OPTIONS}, "value": 1 if corrido else 0},
        ],
    }


def plain_task(task_id, parent=None, done=False, native_due=None, vencimento=None):
    return {
        "id": task_id, "name": task_id, "parent": parent, "list": {"id": "L2"},
        "status": {"status": "complete" if done else "planejando", "type": "done" if done else "open"},
        "due_date": str(date_to_ms(native_due)) if native_due else None,
        "custom_fields": [
            {"id": _FIELD_VENCIMENTO_ID, "name": "Vencimento", "type": "date",
             "value": str(date_to_ms(vencimento)) if vencimento else None},
        ],
    }


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def repo(db) -> CacheRepository:
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "S", "name": "Space"})
    await repo.upsert_folder({"id": "F", "name": "LUBANGO"}, "S")
    await repo.upsert_list({"id": "L1", "name": "Site FM"}, "S", "F")
    await repo.upsert_list({"id": "L2", "name": "Estudios"}, "S", "F")
    return repo


async def _civil(repo: CacheRepository) -> None:
    """Disciplina → 2 grupos → tarefas, como a Obra Civil de Lubango em miniatura."""
    for task in [
        schedule_task("civil"),
        schedule_task("base", parent="civil"),
        schedule_task("solo", parent="base", duration=2, percent=100, status="complete", status_type="done"),
        schedule_task("cura", parent="base", duration=14, corrido=True, percent=100, status="complete", status_type="done"),
        schedule_task("pintura", parent="civil"),
        schedule_task("parede", parent="pintura", duration=4, percent=50, status="fazendo", status_type="custom"),
        schedule_task("teto", parent="pintura", duration=3),
    ]:
        await repo.upsert_task(task, "L1")
    await repo._db.commit()


class TestUpsert:
    async def test_schedule_task_stores_percent_duration_and_native_due(self, repo, db):
        await repo.upsert_task(schedule_task("a", percent=40, duration=14, corrido=True, due=date(2026, 10, 30)), "L1")
        await db.commit()
        row = await db.get(ClickUpTaskCache, "a")

        assert row.progress_pct == 40
        assert row.duration_days == 14
        assert row.calendar_type == "corrido"
        assert row.due_date == datetime(2026, 10, 30, 23, 59, 59)   # vale até o fim do dia

    async def test_plain_task_is_untouched_and_ignores_the_native_due(self, repo, db):
        await repo.upsert_task(plain_task("x", native_due=date(2026, 1, 1)), "L2")
        await repo.upsert_task(plain_task("y", native_due=date(2026, 1, 1), vencimento=date(2026, 5, 5)), "L2")
        await db.commit()

        x, y = await db.get(ClickUpTaskCache, "x"), await db.get(ClickUpTaskCache, "y")
        assert x.progress_pct is None and x.duration_days is None
        assert x.due_date is None
        assert y.due_date == datetime(2026, 5, 5, 9)

    async def test_moving_a_task_updates_its_parent(self, repo, db):
        await repo.upsert_task(schedule_task("a", parent="g1", duration=1), "L1")
        await repo.upsert_task(schedule_task("a", parent="g2", duration=1), "L1")
        await db.commit()

        assert (await db.get(ClickUpTaskCache, "a")).parent_task_id == "g2"


class TestWeightedProgress:
    async def test_list_progress_is_weighted_by_useful_duration_across_levels(self, repo):
        await _civil(repo)
        rates = await repo._weighted_completion_by_list(["L1"])

        # úteis: solo 2 + cura 12 (14 corridos) + parede 4 + teto 3 = 21; feito: 2 + 12 + 2 = 16
        assert rates["L1"] == pytest.approx(16 / 21)

    async def test_leaf_kpis_count_only_third_level_tasks(self, repo):
        await _civil(repo)
        kpis = await repo.get_list_kpis("L1")

        assert kpis["total_tasks"] == 4
        assert kpis["completed_tasks"] == 2
        assert kpis["completion_rate"] == pytest.approx(16 / 21, abs=1e-4)

    async def test_cancelled_task_leaves_the_weights(self, repo):
        await _civil(repo)
        await repo.upsert_task(
            schedule_task("teto", parent="pintura", duration=3, status="cancelled", status_type="closed"), "L1"
        )
        await repo._db.commit()

        assert (await repo._weighted_completion_by_list(["L1"]))["L1"] == pytest.approx(16 / 18)

    async def test_top_level_task_without_children_uses_its_own_percent(self, repo):
        await repo.upsert_task(schedule_task("solta", duration=4, percent=25), "L1")
        await repo._db.commit()

        assert (await repo._weighted_completion_by_list(["L1"]))["L1"] == pytest.approx(0.25)

    async def test_folder_averages_the_schedule_list_with_a_plain_list(self, repo):
        await _civil(repo)
        await repo.upsert_task(plain_task("d1"), "L2")
        await repo.upsert_task(plain_task("d1a", parent="d1", done=True), "L2")
        await repo.upsert_task(plain_task("d1b", parent="d1"), "L2")
        await repo._db.commit()

        by_folder = await repo._weighted_completion_by_folder("S")
        assert by_folder["F"] == pytest.approx((16 / 21 + 0.5) / 2)


class TestWeightsConfigOverrides:
    def test_named_weights_still_apply_without_overrides(self):
        subtasks = [{"name": "a", "is_done": True}, {"name": "b", "is_done": False}]
        assert compute_task_progress("qualquer", False, subtasks) == 0.5

    def test_explicit_weight_and_partial_progress(self):
        subtasks = [
            {"name": "a", "is_done": False, "weight": 3, "progress": 0.5},
            {"name": "b", "is_done": False, "weight": 1, "progress": 0.0},
        ]
        assert compute_task_progress("qualquer", False, subtasks) == pytest.approx(0.375)

    def test_list_progress_uses_task_weight_override(self):
        tasks = [
            {"name": "x", "is_done": False, "weight": 9, "subtasks": [{"name": "a", "is_done": True, "weight": 9, "progress": 1.0}]},
            {"name": "y", "is_done": False, "weight": 1, "subtasks": [{"name": "b", "is_done": False, "weight": 1, "progress": 0.0}]},
        ]
        progress, details = compute_list_progress(tasks)
        assert progress == pytest.approx(0.9)
        assert details[0]["weight_norm"] == pytest.approx(0.9)


class TestDashboard:
    async def test_list_view_shows_only_the_discipline(self, repo, db):
        await _civil(repo)
        tasks = await DashboardService(db).get_list_tasks("L1")

        assert [t.task_id for t in tasks] == ["civil"]
        assert tasks[0].has_subtasks and tasks[0].progress_pct == 0

    async def test_group_inside_a_discipline_is_navigable(self, repo, db):
        await _civil(repo)
        detail = await DashboardService(db).get_task_detail("civil")

        assert {s.task_id: s.has_subtasks for s in detail.subtasks} == {"base": True, "pintura": True}
        assert detail.ancestors == []

    async def test_third_level_detail_carries_schedule_fields_and_ancestors(self, repo, db):
        await _civil(repo)
        detail = await DashboardService(db).get_task_detail("cura")

        assert detail.progress_pct == 100 and detail.duration_days == 14 and detail.calendar_type == "corrido"
        assert detail.ancestors == [{"task_id": "civil", "name": "civil"}, {"task_id": "base", "name": "base"}]
        assert not detail.has_subtasks


def _link(tasks: dict, task_id: str, on: str) -> None:
    """Regista "task_id espera por on" nas duas tarefas, como o ClickUp devolve."""
    record = {"task_id": task_id, "depends_on": on, "type": 1}
    tasks[task_id].setdefault("dependencies", []).append(record)
    tasks[on].setdefault("dependencies", []).append(record)


async def _civil_with_dependencies(repo: CacheRepository) -> None:
    tasks = {t["id"]: t for t in [
        schedule_task("civil"),
        schedule_task("base", parent="civil"),
        schedule_task("solo", parent="base", duration=2, percent=100, status="complete", status_type="done"),
        schedule_task("cura", parent="base", duration=14, corrido=True),
        schedule_task("pintura", parent="civil"),
        schedule_task("parede", parent="pintura", duration=4),
        schedule_task("teto", parent="pintura", duration=3),
    ]}
    _link(tasks, "cura", "solo")       # dentro do mesmo grupo
    _link(tasks, "parede", "cura")     # cruza de "pintura" para "base"
    _link(tasks, "teto", "parede")     # dentro do mesmo grupo
    for task in tasks.values():
        await repo.upsert_task(task, "L1")
    await repo._db.commit()


class TestDependencies:
    async def test_task_lists_what_it_waits_for_and_what_it_releases(self, repo, db):
        await _civil_with_dependencies(repo)
        cura = await DashboardService(db).get_task_detail("cura")

        assert [(d.task_id, d.parent_name, d.status_type) for d in cura.depends_on] == [("solo", "base", "done")]
        assert [(d.task_id, d.parent_name) for d in cura.blocks] == [("parede", "pintura")]

    async def test_only_the_waiting_side_stores_the_dependency(self, repo, db):
        await _civil_with_dependencies(repo)
        solo = await DashboardService(db).get_task_detail("solo")

        assert solo.depends_on == []
        assert [d.task_id for d in solo.blocks] == ["cura"]

    async def test_group_shows_only_dependencies_that_leave_the_group(self, repo, db):
        await _civil_with_dependencies(repo)
        civil = await DashboardService(db).get_task_detail("civil")
        by_id = {s.task_id: s for s in civil.subtasks}

        assert [d.task_id for d in by_id["pintura"].depends_on] == ["cura"]   # teto→parede é interna
        assert by_id["base"].depends_on == []
        assert civil.depends_on == [] and civil.blocks == []                  # tudo dentro da disciplina

        base = await DashboardService(db).get_task_detail("base")
        assert [d.task_id for d in base.blocks] == ["parede"]

    async def test_list_without_dependencies_costs_nothing(self, repo, db):
        await _civil(repo)
        detail = await DashboardService(db).get_task_detail("cura")

        assert detail.depends_on == [] and detail.blocks == []

    async def test_removed_dependency_disappears_on_the_next_upsert(self, repo, db):
        await _civil_with_dependencies(repo)
        await repo.upsert_task(schedule_task("cura", parent="base", duration=14, corrido=True), "L1")
        await db.commit()

        assert (await DashboardService(db).get_task_detail("cura")).depends_on == []
