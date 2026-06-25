import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base, get_db
from src.repositories.cache_repository import CacheRepository
from src.models.cache_models import ClickUpTaskCache

TEST_DB = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="module")
async def test_engine():
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def test_session(test_engine) -> AsyncSession:
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def seeded_session(test_session):
    repo = CacheRepository(test_session)
    await repo.upsert_space({"id": "s1", "name": "RNA"})
    await test_session.commit()
    await repo.upsert_list({"id": "l1", "name": "Lista 1"}, "s1", None)
    await test_session.commit()
    yield test_session


@pytest.fixture
async def app_with_db(seeded_session):
    from src.main import app
    app.dependency_overrides[get_db] = lambda: seeded_session

    with patch("src.main.start_polling"), patch("src.main.stop_polling"), \
         patch("src.main.start_cache_worker"), patch("src.main.stop_cache_worker"):
        yield app

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_webhook_updates_cache(app_with_db, seeded_session):
    mock_task = {
        "id": "t_new",
        "name": "Task via Webhook",
        "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
    }

    with patch("src.api.webhooks.SyncService") as mock_sync, \
         patch("src.services.cache_service.ClickUpClient") as mock_cu_cls, \
         patch("src.api.webhooks.settings") as mock_settings, \
         patch("asyncio.create_task") as mock_create_task:

        mock_settings.clickup_webhook_secret = ""
        mock_sync_instance = AsyncMock()
        mock_sync_instance.handle_clickup_webhook = AsyncMock(return_value=AsyncMock(success=True, message="ok"))
        mock_sync.return_value = mock_sync_instance

        mock_cu = AsyncMock()
        mock_cu.__aenter__ = AsyncMock(return_value=mock_cu)
        mock_cu.__aexit__ = AsyncMock(return_value=False)
        mock_cu.get_task = AsyncMock(return_value=mock_task)
        mock_cu_cls.return_value = mock_cu

        async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
            resp = await client.post("/webhooks/clickup", json={
                "event": "taskCreated",
                "task_id": "t_new",
                "history_items": [],
            })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    # asyncio.create_task foi chamado (cache + SSE em background)
    mock_create_task.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_ignored_event(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.post("/webhooks/clickup", json={
            "event": "taskCommentPosted",
            "task_id": "t1",
            "history_items": [],
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_no_task_id(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.post("/webhooks/clickup", json={
            "event": "taskCreated",
            "history_items": [],
        })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
