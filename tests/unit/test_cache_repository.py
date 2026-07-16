import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base
from src.models.cache_models import (
    ClickUpSpaceCache, ClickUpFolderCache, ClickUpListCache, ClickUpTaskCache,
)
from src.repositories.cache_repository import CacheRepository, _ms_to_dt

# ─── Setup in-memory SQLite ──────────────────────────────────────────────────

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
def repo(db: AsyncSession) -> CacheRepository:
    return CacheRepository(db)


# ─── _ms_to_dt ───────────────────────────────────────────────────────────────

def test_ms_to_dt_valid():
    dt = _ms_to_dt("1748649600000")
    assert dt is not None
    assert dt.year == 2025


def test_ms_to_dt_none():
    assert _ms_to_dt(None) is None


def test_ms_to_dt_empty():
    assert _ms_to_dt("") is None


def test_ms_to_dt_invalid():
    assert _ms_to_dt("not-a-number") is None


# ─── upsert_space ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_space_creates(repo, db):
    await repo.upsert_space({"id": "space1", "name": "RNA", "private": False})
    await db.commit()
    space = await db.get(ClickUpSpaceCache, "space1")
    assert space is not None
    assert space.name == "RNA"


@pytest.mark.asyncio
async def test_upsert_space_is_idempotent(repo, db):
    await repo.upsert_space({"id": "space1", "name": "RNA", "private": False})
    await db.commit()
    await repo.upsert_space({"id": "space1", "name": "RNA Updated", "private": False})
    await db.commit()
    space = await db.get(ClickUpSpaceCache, "space1")
    assert space.name == "RNA Updated"


# ─── upsert_folder ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "Studios", "hidden": False, "task_count": 5}, "s1")
    await db.commit()
    folder = await db.get(ClickUpFolderCache, "f1")
    assert folder.name == "Studios"
    assert folder.space_id == "s1"


# ─── upsert_list ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_list_with_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "F"}, "s1")
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "Lista A", "task_count": 10}, "s1", "f1")
    await db.commit()
    lst = await db.get(ClickUpListCache, "l1")
    assert lst.name == "Lista A"
    assert lst.folder_id == "f1"


@pytest.mark.asyncio
async def test_upsert_list_without_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l2", "name": "Sem Folder"}, "s1", None)
    await db.commit()
    lst = await db.get(ClickUpListCache, "l2")
    assert lst.folder_id is None


# ─── upsert_task ─────────────────────────────────────────────────────────────

@pytest.fixture
async def seed_list(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", None)
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_task_basic(repo, db, seed_list):
    task = {
        "id": "t1",
        "name": "Instalar antena",
        "status": {"status": "in progress", "type": "open", "color": "#4ade80"},
        "assignees": [{"id": "u1", "username": "João"}],
        "due_date": "1748649600000",
        "list": {"id": "l1"},
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.name == "Instalar antena"
    assert t.status == "in progress"
    assert t.status_type == "open"
    assert t.due_date is not None
    parsed = json.loads(t.assignees_json)
    assert any(a["username"] == "João" for a in parsed)


@pytest.mark.asyncio
async def test_upsert_task_idempotent(repo, db, seed_list):
    base = {"id": "t1", "name": "Original", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}}
    await repo.upsert_task(base, "l1")
    await db.commit()
    updated = {**base, "name": "Atualizado"}
    await repo.upsert_task(updated, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.name == "Atualizado"


# ─── mark_tasks_stale ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_tasks_stale_removes_orphans(repo, db, seed_list):
    for tid in ["t1", "t2", "t3"]:
        await repo.upsert_task({"id": tid, "name": tid, "list": {"id": "l1"}}, "l1")
    await db.commit()
    removed = await repo.mark_tasks_stale("l1", {"t1", "t2"})
    await db.commit()
    assert removed == 1
    assert await db.get(ClickUpTaskCache, "t3") is None
    assert await db.get(ClickUpTaskCache, "t1") is not None


@pytest.mark.asyncio
async def test_mark_tasks_stale_removes_deleted_subtasks(repo, db, seed_list):
    # Task pai + duas subtasks — uma delas foi apagada no ClickUp e não vem mais em `seen_ids`
    await repo.upsert_task({"id": "parent", "name": "Pai", "list": {"id": "l1"}}, "l1")
    await repo.upsert_task({"id": "sub1", "name": "Sub 1", "list": {"id": "l1"}, "parent": "parent"}, "l1")
    await repo.upsert_task({"id": "sub2", "name": "Sub 2", "list": {"id": "l1"}, "parent": "parent"}, "l1")
    await db.commit()

    removed = await repo.mark_tasks_stale("l1", {"parent", "sub1"})
    await db.commit()

    assert removed == 1
    assert await db.get(ClickUpTaskCache, "sub2") is None
    assert await db.get(ClickUpTaskCache, "sub1") is not None
    assert await db.get(ClickUpTaskCache, "parent") is not None


# ─── get_task_list_id / delete_task ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_task_list_id(repo, db, seed_list):
    await repo.upsert_task({"id": "t1", "name": "t1", "list": {"id": "l1"}}, "l1")
    await db.commit()
    assert await repo.get_task_list_id("t1") == "l1"


@pytest.mark.asyncio
async def test_get_task_list_id_missing(repo, db, seed_list):
    assert await repo.get_task_list_id("nao-existe") is None


@pytest.mark.asyncio
async def test_delete_task(repo, db, seed_list):
    await repo.upsert_task({"id": "t1", "name": "t1", "list": {"id": "l1"}}, "l1")
    await db.commit()
    await repo.delete_task("t1")
    await db.commit()
    assert await db.get(ClickUpTaskCache, "t1") is None


# ─── get_overview_kpis ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_overview_kpis(repo, db, seed_list):
    tasks = [
        {"id": "t1", "name": "A", "status": {"status": "complete", "type": "closed"}, "list": {"id": "l1"}},
        {"id": "t2", "name": "B", "status": {"status": "open", "type": "open"}, "due_date": "1000", "list": {"id": "l1"}},
        {"id": "t3", "name": "C", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
    ]
    for t in tasks:
        await repo.upsert_task(t, "l1")
    await db.commit()

    kpis = await repo.get_overview_kpis("s1")
    assert kpis["total_tasks"] == 3
    assert kpis["completed_tasks"] == 1
    assert kpis["overdue_tasks"] == 1  # t2 tem due_date no passado
    assert kpis["tasks_without_due_date"] == 2  # t1 e t3
    assert kpis["completion_rate"] == pytest.approx(1 / 3, abs=0.01)


# ─── get_subtask_count_by_parent ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subtask_count(repo, db, seed_list):
    await repo.upsert_task({"id": "parent1", "name": "Pai", "list": {"id": "l1"}}, "l1")
    await db.commit()
    for i in range(3):
        await repo.upsert_task(
            {"id": f"sub{i}", "name": f"Sub{i}", "parent": "parent1", "list": {"id": "l1"}}, "l1"
        )
    await db.commit()
    counts = await repo.get_subtask_count_by_parent("l1")
    assert counts.get("parent1") == 3
