"""
Testes para CacheRepository.get_period_updates — cobre o agrupamento de
tasks/subtasks por período e o aninhamento correto de subtarefas sob a
tarefa-pai real, mesmo quando a tarefa-pai em si não teve atualização
reportável (não deve virar uma linha solta "Pai > Sub").
"""
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
async def base(db: AsyncSession) -> AsyncSession:
    db.add(ClickUpSpaceCache(space_id=SPACE_ID, name="Test Space"))
    db.add(ClickUpFolderCache(folder_id=FOLDER_ID, space_id=SPACE_ID, name="Kuito"))
    db.add(ClickUpListCache(list_id=LIST_ID, space_id=SPACE_ID, folder_id=FOLDER_ID, name="Studio"))
    await db.flush()
    return db


def _find(folders: list[dict], task_id: str) -> dict | None:
    for f in folders:
        for tk in f["tasks"]:
            if tk["task_id"] == task_id:
                return tk
    return None


@pytest.mark.asyncio
async def test_subtask_nests_under_shell_when_parent_still_planning(base):
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    until = now

    # Disciplina ainda em planejando (não teve atualização reportável ela mesma)
    base.add(ClickUpTaskCache(
        task_id="parent1", list_id=LIST_ID, name="Obra Civil",
        status="planejando", status_type="open",
        date_updated=now - timedelta(days=60), date_created=now - timedelta(days=90),
    ))
    # Atividade dessa disciplina, movida para "fazendo" nesta semana
    base.add(ClickUpTaskCache(
        task_id="sub1", list_id=LIST_ID, name="Instalação de Rede de Ar-Condicionado",
        status="fazendo", status_type="custom", parent_task_id="parent1",
        date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
        assignees_json="[]",
    ))
    await base.commit()

    repo = CacheRepository(base)
    folders = await repo.get_period_updates(SPACE_ID, since, until)

    shell = _find(folders, "parent1")
    assert shell is not None, "Deve existir um container com o task_id da disciplina real"
    assert shell["name"] == "Obra Civil", "Nome deve ser o da disciplina, sem concatenação"
    assert ">" not in shell["name"]
    assert len(shell["subtasks"]) == 1
    assert shell["subtasks"][0]["name"] == "Instalação de Rede de Ar-Condicionado"

    # A atividade não deve aparecer como uma linha de topo separada
    assert _find(folders, "sub1") is None


@pytest.mark.asyncio
async def test_multiple_subtasks_same_category_share_one_shell(base):
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    until = now

    base.add(ClickUpTaskCache(
        task_id="parent1", list_id=LIST_ID, name="Obra Civil",
        status="planejando", status_type="open",
        date_updated=now - timedelta(days=60), date_created=now - timedelta(days=90),
    ))
    for i in range(2):
        base.add(ClickUpTaskCache(
            task_id=f"sub{i}", list_id=LIST_ID, name=f"Atividade {i}",
            status="fazendo", status_type="custom", parent_task_id="parent1",
            date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
            assignees_json="[]",
        ))
    await base.commit()

    repo = CacheRepository(base)
    folders = await repo.get_period_updates(SPACE_ID, since, until)

    matches = [tk for f in folders for tk in f["tasks"] if tk["task_id"] == "parent1"]
    assert len(matches) == 1, "Só deve existir UM container para a mesma disciplina+categoria"
    assert len(matches[0]["subtasks"]) == 2


@pytest.mark.asyncio
async def test_subtasks_split_by_category_get_separate_shells(base):
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    until = now

    base.add(ClickUpTaskCache(
        task_id="parent1", list_id=LIST_ID, name="Obra Civil",
        status="planejando", status_type="open",
        date_updated=now - timedelta(days=60), date_created=now - timedelta(days=90),
    ))
    # Uma concluída (date_closed no período)
    base.add(ClickUpTaskCache(
        task_id="sub_done", list_id=LIST_ID, name="Atividade Concluida",
        status="complete", status_type="done", parent_task_id="parent1",
        date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
        date_closed=now - timedelta(days=1),
        assignees_json="[]",
    ))
    # Outra só em progresso
    base.add(ClickUpTaskCache(
        task_id="sub_active", list_id=LIST_ID, name="Atividade Em Andamento",
        status="fazendo", status_type="custom", parent_task_id="parent1",
        date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
        assignees_json="[]",
    ))
    await base.commit()

    repo = CacheRepository(base)
    folders = await repo.get_period_updates(SPACE_ID, since, until)

    matches = [tk for f in folders for tk in f["tasks"] if tk["task_id"] == "parent1"]
    assert len(matches) == 2, "Categorias diferentes geram containers separados"
    categories = {m["category"] for m in matches}
    assert categories == {"concluded", "updated"}


@pytest.mark.asyncio
async def test_subtask_still_planning_is_dropped_entirely(base):
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    until = now

    base.add(ClickUpTaskCache(
        task_id="parent1", list_id=LIST_ID, name="Obra Civil",
        status="planejando", status_type="open",
        date_updated=now - timedelta(days=60), date_created=now - timedelta(days=90),
    ))
    base.add(ClickUpTaskCache(
        task_id="sub1", list_id=LIST_ID, name="Atividade Recem Criada",
        status="planejando", status_type="open", parent_task_id="parent1",
        date_updated=now - timedelta(hours=1), date_created=now - timedelta(hours=1),
        assignees_json="[]",
    ))
    await base.commit()

    repo = CacheRepository(base)
    folders = await repo.get_period_updates(SPACE_ID, since, until)

    assert folders == [], "Nada deve aparecer: pai e subtask ainda em planejando"


@pytest.mark.asyncio
async def test_parent_and_subtask_both_qualify_nest_normally(base):
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    until = now

    base.add(ClickUpTaskCache(
        task_id="parent1", list_id=LIST_ID, name="Obra Civil",
        status="fazendo", status_type="custom",
        date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
        assignees_json="[]",
    ))
    base.add(ClickUpTaskCache(
        task_id="sub1", list_id=LIST_ID, name="Instalação de Rede de Ar-Condicionado",
        status="fazendo", status_type="custom", parent_task_id="parent1",
        date_updated=now - timedelta(days=1), date_created=now - timedelta(days=90),
        assignees_json="[]",
    ))
    await base.commit()

    repo = CacheRepository(base)
    folders = await repo.get_period_updates(SPACE_ID, since, until)

    parent_entry = _find(folders, "parent1")
    assert parent_entry is not None
    assert parent_entry["name"] == "Obra Civil"
    assert len(parent_entry["subtasks"]) == 1
    assert parent_entry["subtasks"][0]["name"] == "Instalação de Rede de Ar-Condicionado"
