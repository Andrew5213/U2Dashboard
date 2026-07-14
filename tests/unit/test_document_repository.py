import os
import shutil
import tempfile

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
from src.models.document_models import Document  # noqa: F401 — registers table on Base.metadata
from src.repositories.document_repository import DocumentRepository
from src.services.document_service import DocumentService

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
def repo(db: AsyncSession) -> DocumentRepository:
    return DocumentRepository(db)


@pytest.fixture
def svc(db: AsyncSession) -> DocumentService:
    return DocumentService(db)


@pytest.fixture
def docs_dir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ─── DocumentRepository ──────────────────────────────────────────────────────

async def test_create_and_get(repo: DocumentRepository):
    doc = await repo.create({
        "folder_id": "f1", "folder_name": "Luanda",
        "original_filename": "planta.pdf", "stored_filename": "abc.pdf",
        "file_size": 100,
    })
    fetched = await repo.get(doc.id)
    assert fetched is not None
    assert fetched.folder_name == "Luanda"
    assert fetched.original_filename == "planta.pdf"


async def test_get_missing_returns_none(repo: DocumentRepository):
    assert await repo.get(999) is None


async def test_list_filters_by_folder(repo: DocumentRepository):
    await repo.create({
        "folder_id": "f1", "folder_name": "Luanda",
        "original_filename": "a.pdf", "stored_filename": "a1.pdf", "file_size": 10,
    })
    await repo.create({
        "folder_id": "f2", "folder_name": "Benguela",
        "original_filename": "b.pdf", "stored_filename": "b1.pdf", "file_size": 20,
    })

    all_docs = await repo.list()
    assert len(all_docs) == 2

    f1_docs = await repo.list(folder_id="f1")
    assert len(f1_docs) == 1
    assert f1_docs[0].folder_id == "f1"


async def test_delete_removes_row(repo: DocumentRepository):
    doc = await repo.create({
        "folder_id": "f1", "folder_name": "Luanda",
        "original_filename": "a.pdf", "stored_filename": "a1.pdf", "file_size": 10,
    })
    assert await repo.delete(doc.id) is True
    assert await repo.get(doc.id) is None


async def test_delete_missing_returns_false(repo: DocumentRepository):
    assert await repo.delete(999) is False


# ─── DocumentService ─────────────────────────────────────────────────────────

async def test_upload_document_writes_file_and_row(svc: DocumentService, docs_dir: str):
    result = await svc.upload_document(
        folder_id="f1", folder_name="Luanda",
        file_bytes=b"%PDF-1.4 fake content",
        original_filename="Contrato.pdf",
        description="Contrato assinado",
        docs_dir=docs_dir,
    )
    assert result["folder_name"] == "Luanda"
    assert result["original_filename"] == "Contrato.pdf"
    assert result["file_size"] == len(b"%PDF-1.4 fake content")
    assert result["description"] == "Contrato assinado"
    assert len(os.listdir(docs_dir)) == 1


async def test_delete_document_removes_file(svc: DocumentService, docs_dir: str):
    result = await svc.upload_document(
        folder_id="f1", folder_name="Luanda",
        file_bytes=b"content", original_filename="a.pdf",
        description=None, docs_dir=docs_dir,
    )
    assert len(os.listdir(docs_dir)) == 1

    deleted = await svc.delete_document(result["id"], docs_dir)
    assert deleted is True
    assert len(os.listdir(docs_dir)) == 0


async def test_delete_document_missing_returns_false(svc: DocumentService, docs_dir: str):
    assert await svc.delete_document(999, docs_dir) is False
