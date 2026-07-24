import json
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base
from src.models.dashboard_schemas import TaskSummary, TaskDetail
from src.repositories.cache_repository import CacheRepository, _FIELD_VENCIMENTO_ID
from src.services.dashboard_service import DashboardService, _task_to_summary
from src.models.cache_models import ClickUpTaskCache

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def seeded_db(db):
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "s1", "name": "Space"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "Pasta A"}, "s1")
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "Lista 1"}, "s1", "f1")
    await repo.upsert_list({"id": "l2", "name": "Lista 2"}, "s1", "f1")
    await db.commit()
    tasks = [
        {"id": "t1", "name": "Task concluída", "status": {"status": "complete", "type": "closed"}, "list": {"id": "l1"}},
        {"id": "t2", "name": "Task em atraso", "status": {"status": "open", "type": "open"},
         "list": {"id": "l1"}, "custom_fields": [{"id": _FIELD_VENCIMENTO_ID, "value": "1000"}]},
        {"id": "t3", "name": "Task normal", "status": {"status": "open", "type": "open"}, "list": {"id": "l2"}},
    ]
    for t in tasks:
        await repo.upsert_task(t, t["list"]["id"])
    await db.commit()
    yield db


# ─── _task_to_summary ────────────────────────────────────────────────────────

def _make_orm_task(**kwargs) -> ClickUpTaskCache:
    defaults = dict(
        task_id="t1", list_id="l1", name="Test Task",
        status="open", status_type="open", status_color="#4ade80",
        assignees_json='[{"id":"u1","username":"Ana"}]',
        tags_json='["tag1"]',
        due_date=None, start_date=None, date_created=None,
        date_updated=None, date_closed=None, parent_task_id=None, url=None,
        description=None, observacoes=None, last_refreshed_at=datetime.utcnow(),
    )
    defaults.update(kwargs)
    t = ClickUpTaskCache()
    for k, v in defaults.items():
        setattr(t, k, v)
    return t


def test_task_summary_not_overdue():
    task = _make_orm_task(due_date=datetime.utcnow() + timedelta(days=10), status_type="open")
    summary = _task_to_summary(task)
    assert summary.is_overdue is False
    assert summary.assignees == [{"id": "u1", "username": "Ana"}]


def test_task_summary_overdue():
    task = _make_orm_task(due_date=datetime.utcnow() - timedelta(days=1), status_type="open")
    summary = _task_to_summary(task)
    assert summary.is_overdue is True


def test_task_summary_closed_not_overdue():
    task = _make_orm_task(due_date=datetime.utcnow() - timedelta(days=10), status_type="closed")
    summary = _task_to_summary(task)
    assert summary.is_overdue is False


def test_task_summary_no_due_date_not_overdue():
    task = _make_orm_task(due_date=None, status_type="open")
    summary = _task_to_summary(task)
    assert summary.is_overdue is False


def test_task_summary_with_subtasks():
    task = _make_orm_task()
    summary = _task_to_summary(task, has_subtasks=True)
    assert summary.has_subtasks is True


def test_task_summary_invalid_assignees_json():
    task = _make_orm_task(assignees_json="invalid json {{")
    summary = _task_to_summary(task)
    assert summary.assignees == []


def test_task_summary_passes_through_observacoes():
    task = _make_orm_task(observacoes="Aguardando aprovação do cliente")
    summary = _task_to_summary(task)
    assert summary.observacoes == "Aguardando aprovação do cliente"


def test_task_summary_no_observacoes_is_none():
    task = _make_orm_task()
    summary = _task_to_summary(task)
    assert summary.observacoes is None


# ─── DashboardService ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_overview(seeded_db):
    svc = DashboardService(seeded_db)
    overview = await svc.get_overview("s1")
    assert overview.total_tasks == 3
    assert overview.completed_tasks == 1
    assert overview.overdue_tasks == 1
    assert overview.total_folders == 1
    assert overview.total_lists == 2
    assert abs(overview.completion_rate - 1 / 3) < 0.01


@pytest.mark.asyncio
async def test_get_folders(seeded_db):
    svc = DashboardService(seeded_db)
    folders = await svc.get_folders("s1")
    assert len(folders) == 1
    assert folders[0].name == "Pasta A"
    assert folders[0].total_tasks == 3


@pytest.mark.asyncio
async def test_get_folder_lists(seeded_db):
    svc = DashboardService(seeded_db)
    lists = await svc.get_folder_lists("f1")
    assert len(lists) == 2
    names = {l.name for l in lists}
    assert "Lista 1" in names and "Lista 2" in names


@pytest.mark.asyncio
async def test_get_list_tasks(seeded_db):
    svc = DashboardService(seeded_db)
    tasks = await svc.get_list_tasks("l1")
    assert len(tasks) == 2
    assert isinstance(tasks[0], TaskSummary)


@pytest.mark.asyncio
async def test_get_task_detail(seeded_db):
    svc = DashboardService(seeded_db)
    detail = await svc.get_task_detail("t1")
    assert detail is not None
    assert isinstance(detail, TaskDetail)
    assert detail.task_id == "t1"
    assert detail.status_type == "closed"


@pytest.mark.asyncio
async def test_get_task_detail_not_found(seeded_db):
    svc = DashboardService(seeded_db)
    detail = await svc.get_task_detail("nonexistent")
    assert detail is None


@pytest.mark.asyncio
async def test_completion_rate_no_tasks(db):
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "empty", "name": "Empty"})
    await db.commit()
    svc = DashboardService(db)
    overview = await svc.get_overview("empty")
    assert overview.completion_rate == 0.0
    assert overview.total_tasks == 0
