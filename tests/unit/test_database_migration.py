"""
Testes para a sincronização automática de colunas em init_db() — este projeto não
usa Alembic, então uma coluna nova em um modelo ORM precisa ser adicionada sozinha
em bancos já existentes (create_all só cria tabelas ausentes, nunca altera as
existentes). Usa um arquivo SQLite temporário — :memory: não serve aqui porque
cada conexão nova abre um banco em memória isolado.
"""
import os
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import src.models.cache_models  # noqa: F401 - registra as tabelas no Base.metadata
from src.core.database import Base, _sync_missing_columns

TEST_DB_PATH = "./_test_migration_sync.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_PATH}"


@pytest.fixture
async def old_schema_engine():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE clickup_task_cache (
                task_id VARCHAR(100) PRIMARY KEY,
                list_id VARCHAR(100) NOT NULL,
                name VARCHAR(500) NOT NULL
            )
        """))
    yield engine
    await engine.dispose()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


def _columns(sync_conn, table_name: str) -> set[str]:
    return {c["name"] for c in inspect(sync_conn).get_columns(table_name)}


@pytest.mark.asyncio
async def test_sync_missing_columns_adds_new_column(old_schema_engine):
    async with old_schema_engine.connect() as conn:
        before = await conn.run_sync(_columns, "clickup_task_cache")
    assert "observacoes" not in before

    async with old_schema_engine.begin() as conn:
        await conn.run_sync(_sync_missing_columns)

    async with old_schema_engine.connect() as conn:
        after = await conn.run_sync(_columns, "clickup_task_cache")
    assert "observacoes" in after
    assert "due_date" in after
    assert "status" in after


@pytest.mark.asyncio
async def test_sync_missing_columns_is_idempotent(old_schema_engine):
    async with old_schema_engine.begin() as conn:
        await conn.run_sync(_sync_missing_columns)
    # Rodar de novo não deve levantar erro de "coluna duplicada"
    async with old_schema_engine.begin() as conn:
        await conn.run_sync(_sync_missing_columns)


@pytest.mark.asyncio
async def test_sync_missing_columns_preserves_existing_data(old_schema_engine):
    async with old_schema_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO clickup_task_cache (task_id, list_id, name) VALUES ('t1', 'l1', 'Minha Task')"
        ))

    async with old_schema_engine.begin() as conn:
        await conn.run_sync(_sync_missing_columns)

    async with old_schema_engine.connect() as conn:
        row = (await conn.execute(text(
            "SELECT task_id, name, observacoes FROM clickup_task_cache WHERE task_id = 't1'"
        ))).one()
    assert row.task_id == "t1"
    assert row.name == "Minha Task"
    assert row.observacoes is None


@pytest.mark.asyncio
async def test_sync_missing_columns_skips_non_sqlite(monkeypatch, old_schema_engine):
    from src.core import database as database_module
    monkeypatch.setattr(database_module.settings, "database_url", "postgresql://fake")

    async with old_schema_engine.begin() as conn:
        await conn.run_sync(_sync_missing_columns)

    async with old_schema_engine.connect() as conn:
        after = await conn.run_sync(_columns, "clickup_task_cache")
    assert "observacoes" not in after
