"""
Testes de integração: /disciplines exige a mesma senha de exclusão de
documentos (X-Delete-Password) para alterar (POST) ou remover (DELETE)
pesos de disciplinas já configurados.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base, get_db
from src.core.config import settings
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
    await repo.upsert_list({"id": "l2", "name": "Studio CT4"}, "s1", "f1")
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


_BODY = {"weights": [{"list_id": "l1", "weight": 0.5}, {"list_id": "l2", "weight": 0.5}]}


@pytest.mark.asyncio
async def test_set_weights_requires_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.post("/disciplines/folder/f1", json=_BODY)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_set_weights_rejects_wrong_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.post(
            "/disciplines/folder/f1", json=_BODY,
            headers={"X-Delete-Password": "senha-errada"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_set_weights_accepts_correct_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.post(
            "/disciplines/folder/f1", json=_BODY,
            headers={"X-Delete-Password": settings.documents_delete_password},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_delete_weights_requires_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.delete("/disciplines/folder/f1")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_weights_accepts_correct_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.delete(
            "/disciplines/folder/f1",
            headers={"X-Delete-Password": settings.documents_delete_password},
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_weights_does_not_require_password(app_with_db):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.get("/disciplines/folder/f1")
    assert resp.status_code == 200
