import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base, get_db
from src.repositories.cache_repository import CacheRepository

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
    session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture
async def seeded_session(test_session):
    repo = CacheRepository(test_session)
    await repo.upsert_space({"id": "s1", "name": "RNA"})
    await test_session.commit()
    await repo.upsert_folder({"id": "f1", "name": "Studios"}, "s1")
    await test_session.commit()
    await repo.upsert_list({"id": "l1", "name": "Studio CT3"}, "s1", "f1")
    await test_session.commit()
    for tid in ["t1", "t2", "t3"]:
        status_type = "closed" if tid == "t1" else "open"
        await repo.upsert_task({
            "id": tid, "name": f"Task {tid}",
            "status": {"status": "complete" if status_type == "closed" else "open", "type": status_type},
            "list": {"id": "l1"},
        }, "l1")
    await test_session.commit()
    yield test_session


@pytest.fixture
async def app_with_db(seeded_session):
    from src.main import app
    app.dependency_overrides[get_db] = lambda: seeded_session

    with patch("src.main.start_polling"), \
         patch("src.main.stop_polling"), \
         patch("src.main.start_cache_worker"), \
         patch("src.main.stop_cache_worker"):
        yield app

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_overview_endpoint(app_with_db):
    with patch("src.api.dashboard.settings") as mock_settings:
        mock_settings.clickup_default_space_id = "s1"
        async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
            resp = await client.get("/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["total_tasks"] == 3
    assert data["data"]["completed_tasks"] == 1


@pytest.mark.asyncio
async def test_folders_endpoint(app_with_db):
    with patch("src.api.dashboard.settings") as mock_settings:
        mock_settings.clickup_default_space_id = "s1"
        async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
            resp = await client.get("/dashboard/folders")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["name"] == "Studios"


@pytest.mark.asyncio
async def test_folder_endpoint(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/dashboard/folder/f1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 1
    assert data["data"][0]["list_id"] == "l1"


@pytest.mark.asyncio
async def test_list_endpoint(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/dashboard/list/l1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]) == 3


@pytest.mark.asyncio
async def test_task_endpoint(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/dashboard/task/t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["task_id"] == "t1"
    assert data["data"]["status_type"] == "closed"


@pytest.mark.asyncio
async def test_task_not_found(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/dashboard/task/nao-existe")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_home_returns_html(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_refresh_endpoint_triggers_background(app_with_db):
    with patch("src.api.dashboard.settings") as mock_settings, \
         patch("src.api.dashboard.CacheService") as mock_svc_cls:
        mock_settings.clickup_default_space_id = "s1"
        mock_instance = AsyncMock()
        mock_svc_cls.return_value = mock_instance

        async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
            resp = await client.post("/dashboard/refresh")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "background" in data["data"]["message"].lower()
