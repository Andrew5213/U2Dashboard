import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base
from src.services.cache_service import CacheService, CacheRefreshSummary

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


def _make_clickup_client(spaces=None, folders=None, lists=None, tasks=None, members=None):
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get_spaces = AsyncMock(return_value=spaces or [{"id": "s1", "name": "Space"}])
    client.get_folders = AsyncMock(return_value=folders or [{"id": "f1", "name": "Folder", "hidden": False, "task_count": 2}])
    client.get_lists_in_folder = AsyncMock(return_value=lists or [{"id": "l1", "name": "Lista 1", "task_count": 2}])
    client.get_folderless_lists = AsyncMock(return_value=[])
    client.get_tasks = AsyncMock(return_value=tasks or [
        {"id": "t1", "name": "Task 1", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
        {"id": "t2", "name": "Task 2", "status": {"status": "complete", "type": "closed"}, "list": {"id": "l1"}},
    ])
    client.get_team_members = AsyncMock(return_value=members or [
        {"user": {"id": "u1", "username": "Alice", "email": "alice@test.com"}}
    ])
    return client


@pytest.mark.asyncio
async def test_refresh_cache_full_success(db):
    mock_client = _make_clickup_client()
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        svc = CacheService(db)
        summary = await svc.refresh_cache_full("s1", trigger="test")

    assert summary.spaces_updated == 1
    assert summary.folders_updated == 1
    assert summary.lists_updated == 1
    assert summary.tasks_updated == 2
    assert summary.errors == []


@pytest.mark.asyncio
async def test_refresh_cache_full_unknown_space(db):
    mock_client = _make_clickup_client(spaces=[{"id": "other", "name": "Other"}])
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        svc = CacheService(db)
        summary = await svc.refresh_cache_full("s1", trigger="test")

    assert summary.spaces_updated == 0


@pytest.mark.asyncio
async def test_refresh_list_success(db):
    from src.repositories.cache_repository import CacheRepository
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", None)
    await db.commit()

    mock_client = _make_clickup_client()
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client):
        svc = CacheService(db)
        count = await svc.refresh_list("l1")

    assert count == 2


@pytest.mark.asyncio
async def test_apply_webhook_event_success(db):
    from src.repositories.cache_repository import CacheRepository
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", None)
    await db.commit()

    mock_client = _make_clickup_client()
    mock_client.get_task = AsyncMock(return_value={
        "id": "t99", "name": "Nova Task",
        "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
    })
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client):
        svc = CacheService(db)
        list_id = await svc.apply_webhook_event("taskCreated", "t99")

    assert list_id == "l1"


@pytest.mark.asyncio
async def test_apply_webhook_event_task_deleted_removes_from_cache(db):
    from src.repositories.cache_repository import CacheRepository
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", None)
    await db.commit()
    await repo.upsert_task({"id": "t1", "name": "Sera apagada", "list": {"id": "l1"}}, "l1")
    await db.commit()

    mock_client = _make_clickup_client()
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client):
        svc = CacheService(db)
        list_id = await svc.apply_webhook_event("taskDeleted", "t1")

    assert list_id == "l1"
    # Não deve nem tentar buscar a task no ClickUp — ela já não existe lá
    mock_client.get_task.assert_not_called()
    assert await repo.get_task_list_id("t1") is None


@pytest.mark.asyncio
async def test_apply_webhook_event_task_deleted_unknown_task(db):
    mock_client = _make_clickup_client()
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client):
        svc = CacheService(db)
        list_id = await svc.apply_webhook_event("taskDeleted", "nunca-existiu")
    assert list_id is None


@pytest.mark.asyncio
async def test_apply_webhook_event_api_error(db):
    mock_client = _make_clickup_client()
    mock_client.get_task = AsyncMock(side_effect=Exception("API error"))
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client):
        svc = CacheService(db)
        result = await svc.apply_webhook_event("taskUpdated", "t_bad")
    assert result is None


@pytest.mark.asyncio
async def test_refresh_full_task_error_continues(db):
    mock_client = _make_clickup_client()
    mock_client.get_tasks = AsyncMock(side_effect=Exception("Rate limit"))
    with patch("src.services.cache_service.ClickUpClient", return_value=mock_client), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        svc = CacheService(db)
        summary = await svc.refresh_cache_full("s1", trigger="test")

    assert len(summary.errors) > 0
    assert summary.tasks_updated == 0
