import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base, get_db
from src.models.document_models import Document  # noqa: F401 — registers table on Base.metadata
from src.repositories.document_repository import DocumentRepository

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
async def doc_id(test_session):
    repo = DocumentRepository(test_session)
    doc = await repo.create({
        "folder_id": "f1", "folder_name": "Luanda",
        "original_filename": "contrato.pdf", "stored_filename": "abc123.pdf",
        "file_size": 100,
    })
    await test_session.commit()
    return doc.id


@pytest.fixture
async def app_with_db(test_session):
    from src.main import app
    app.dependency_overrides[get_db] = lambda: test_session

    with patch("src.main.start_polling"), \
         patch("src.main.stop_polling"), \
         patch("src.main.start_cache_worker"), \
         patch("src.main.stop_cache_worker"):
        yield app

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_delete_without_password_is_forbidden(app_with_db, doc_id):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_with_wrong_password_is_forbidden(app_with_db, doc_id):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.delete(f"/documents/{doc_id}", headers={"X-Delete-Password": "senha-errada"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_with_correct_password_succeeds(app_with_db, doc_id):
    async with AsyncClient(transport=ASGITransport(app=app_with_db), base_url="http://test") as client:
        resp = await client.delete(f"/documents/{doc_id}", headers={"X-Delete-Password": "u2dashboard2026"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
