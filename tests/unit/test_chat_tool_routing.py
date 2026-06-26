"""
Testes para verificar que get_recent_changes e list_tasks_by_status
retornam dados corretos do banco.
"""
import json
import pytest
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base
from src.models.cache_models import (
    ClickUpSpaceCache, ClickUpFolderCache, ClickUpListCache, ClickUpTaskCache,
)
from src.repositories.cache_repository import CacheRepository

TEST_DB = "sqlite+aiosqlite:///:memory:"
SPACE_ID = "space-test"
FOLDER_ID = "folder-1"
LIST_ID = "list-1"


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
async def populated_db(db: AsyncSession) -> AsyncSession:
    """Insere estrutura mínima + tarefas com datas variadas."""
    now = datetime.utcnow()

    db.add(ClickUpSpaceCache(space_id=SPACE_ID, name="Test Space"))
    db.add(ClickUpFolderCache(folder_id=FOLDER_ID, space_id=SPACE_ID, name="Kuito"))
    db.add(ClickUpListCache(list_id=LIST_ID, space_id=SPACE_ID, folder_id=FOLDER_ID, name="Studio"))
    await db.flush()

    tasks = [
        # Concluída hoje
        ClickUpTaskCache(
            task_id="t1", list_id=LIST_ID, name="Obras Civis",
            status="complete", status_type="done",
            date_updated=now - timedelta(hours=2),
            date_created=now - timedelta(days=30),
            assignees_json=json.dumps([{"username": "João"}]),
        ),
        # Concluída há 10 dias
        ClickUpTaskCache(
            task_id="t2", list_id=LIST_ID, name="Instalação Elétrica",
            status="complete", status_type="done",
            date_updated=now - timedelta(days=10),
            date_created=now - timedelta(days=60),
            assignees_json="[]",
        ),
        # Em fazendo — atualizada há 2 dias
        ClickUpTaskCache(
            task_id="t3", list_id=LIST_ID, name="Montagem Acústica",
            status="fazendo", status_type="custom",
            date_updated=now - timedelta(days=2),
            date_created=now - timedelta(days=20),
            assignees_json=json.dumps([{"username": "Maria"}]),
        ),
        # Em revisão — atualizada há 5 dias
        ClickUpTaskCache(
            task_id="t4", list_id=LIST_ID, name="Testes de Áudio",
            status="em revisão", status_type="custom",
            date_updated=now - timedelta(days=5),
            date_created=now - timedelta(days=40),
            assignees_json="[]",
        ),
        # Planejando — velha, não deve aparecer em "semana"
        ClickUpTaskCache(
            task_id="t5", list_id=LIST_ID, name="Documentação",
            status="planejando", status_type="open",
            date_updated=now - timedelta(days=60),
            date_created=now - timedelta(days=90),
            assignees_json="[]",
        ),
        # Criada hoje, ainda em planejando
        ClickUpTaskCache(
            task_id="t6", list_id=LIST_ID, name="Reunião de Kick-off",
            status="planejando", status_type="open",
            date_updated=now - timedelta(hours=1),
            date_created=now - timedelta(hours=1),
            assignees_json="[]",
        ),
        # Subtarefa — NÃO deve aparecer (parent_task_id preenchido)
        ClickUpTaskCache(
            task_id="t7", list_id=LIST_ID, name="Subtarefa Ignorada",
            status="fazendo", status_type="custom",
            parent_task_id="t3",
            date_updated=now - timedelta(hours=1),
            date_created=now - timedelta(days=5),
            assignees_json="[]",
        ),
    ]
    for t in tasks:
        db.add(t)
    await db.commit()
    return db


# ─── get_recent_changes ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recent_changes_week_finds_completed(populated_db):
    repo = CacheRepository(populated_db)
    since = datetime.utcnow() - timedelta(days=7)
    result = await repo.get_recent_changes(SPACE_ID, since)

    names = [t["name"] for t in result["completed"]]
    assert "Obras Civis" in names, "Tarefa concluída hoje deve aparecer em 'completed'"
    assert "Instalação Elétrica" not in names, "Concluída há 10 dias não deve estar em 'week'"


@pytest.mark.asyncio
async def test_recent_changes_month_finds_older_completed(populated_db):
    repo = CacheRepository(populated_db)
    since = datetime.utcnow() - timedelta(days=30)
    result = await repo.get_recent_changes(SPACE_ID, since)

    names = [t["name"] for t in result["completed"]]
    assert "Obras Civis" in names
    assert "Instalação Elétrica" in names, "Concluída há 10 dias deve aparecer em 'month'"


@pytest.mark.asyncio
async def test_recent_changes_week_groups_active_by_status(populated_db):
    repo = CacheRepository(populated_db)
    since = datetime.utcnow() - timedelta(days=7)
    result = await repo.get_recent_changes(SPACE_ID, since)

    by_status = result["by_status"]
    assert "fazendo" in by_status, "Tarefa 'fazendo' atualizada há 2 dias deve aparecer"
    assert "em revisão" in by_status, "Tarefa 'em revisão' atualizada há 5 dias deve aparecer"

    fazendo_names = [t["name"] for t in by_status["fazendo"]]
    assert "Montagem Acústica" in fazendo_names


@pytest.mark.asyncio
async def test_recent_changes_excludes_subtasks(populated_db):
    repo = CacheRepository(populated_db)
    since = datetime.utcnow() - timedelta(days=7)
    result = await repo.get_recent_changes(SPACE_ID, since)

    all_names = (
        [t["name"] for t in result["completed"]]
        + [t["name"] for t in result["created"]]
        + [t["name"] for group in result["by_status"].values() for t in group]
    )
    assert "Subtarefa Ignorada" not in all_names, "Subtarefas não devem aparecer"


@pytest.mark.asyncio
async def test_recent_changes_today_finds_created(populated_db):
    repo = CacheRepository(populated_db)
    since = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await repo.get_recent_changes(SPACE_ID, since)

    created_names = [t["name"] for t in result["created"]]
    assert "Reunião de Kick-off" in created_names, "Tarefa criada hoje deve aparecer em 'created'"


# ─── list_tasks_by_status ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_by_status_specific(populated_db):
    repo = CacheRepository(populated_db)
    result = await repo.get_tasks_by_status(SPACE_ID, status_filter="fazendo")

    assert result["total"] >= 1
    assert "fazendo" in result["by_status"]
    names = [t["name"] for t in result["by_status"]["fazendo"]]
    assert "Montagem Acústica" in names


@pytest.mark.asyncio
async def test_list_tasks_by_status_all(populated_db):
    repo = CacheRepository(populated_db)
    result = await repo.get_tasks_by_status(SPACE_ID)

    assert len(result["by_status"]) >= 2, "Deve retornar múltiplos status"
    assert result["filter"] is None


@pytest.mark.asyncio
async def test_list_tasks_by_status_excludes_subtasks(populated_db):
    repo = CacheRepository(populated_db)
    result = await repo.get_tasks_by_status(SPACE_ID, status_filter="fazendo")

    all_names = [t["name"] for t in result["by_status"].get("fazendo", [])]
    assert "Subtarefa Ignorada" not in all_names


@pytest.mark.asyncio
async def test_list_tasks_by_status_folder_filter(populated_db):
    repo = CacheRepository(populated_db)
    result = await repo.get_tasks_by_status(SPACE_ID, folder_id=FOLDER_ID)

    assert result["total"] >= 1


@pytest.mark.asyncio
async def test_list_tasks_by_status_nonexistent_returns_empty(populated_db):
    repo = CacheRepository(populated_db)
    result = await repo.get_tasks_by_status(SPACE_ID, status_filter="status_inexistente")

    assert result["total"] == 0
    assert result["by_status"] == {}
