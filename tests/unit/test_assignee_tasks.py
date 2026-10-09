"""Tarefas por responsável — o detalhe por trás da barra do gráfico de produtividade.

A contagem desta lista tem de bater com a da barra (`get_assignee_task_stats`):
as duas medem tarefas-folha. Se uma mudar de unidade e a outra não, o utilizador
clica num "3" e recebe 5 linhas.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.database import Base
from src.repositories.cache_repository import CacheRepository

TEST_DB = "sqlite+aiosqlite:///:memory:"

ANA = {"id": 1, "username": "Ana Paula", "email": "ana@u2.ao"}
ANA_CURTA = {"id": 2, "username": "Ana", "email": "ana2@u2.ao"}
JOAO = {"id": 3, "username": "João Manuel", "email": "joao@u2.ao"}


@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed(db: AsyncSession) -> CacheRepository:
    repo = CacheRepository(db)
    await repo.upsert_space({"id": "s1", "name": "RNA"})
    await repo.upsert_folder({"id": "f1", "name": "NAMIBE"}, "s1")
    await repo.upsert_list({"id": "l1", "name": "Site FM"}, "s1", "f1")
    await db.commit()
    return repo


def _task(tid: str, name: str, assignees: list[dict], done: bool = False, parent: str | None = None):
    payload = {
        "id": tid,
        "name": name,
        "status": {"status": "complete" if done else "open", "type": "closed" if done else "open"},
        "list": {"id": "l1"},
        "assignees": assignees,
    }
    if parent:
        payload["parent"] = parent
    return payload


class TestTasksByAssignee:
    async def test_returns_only_that_persons_tasks(self, db):
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Fundação", [ANA]), "l1")
        await repo.upsert_task(_task("t2", "Torre", [JOAO]), "l1")
        await db.commit()

        rows = await repo.get_tasks_by_assignee("s1", "Ana Paula")
        assert [r["name"] for r in rows] == ["Fundação"]

    async def test_name_match_is_exact_not_substring(self, db):
        """O pré-filtro SQL é um LIKE — "Ana" casaria dentro de "Ana Paula"."""
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Fundação", [ANA]), "l1")
        await repo.upsert_task(_task("t2", "Cabos", [ANA_CURTA]), "l1")
        await db.commit()

        assert [r["name"] for r in await repo.get_tasks_by_assignee("s1", "Ana")] == ["Cabos"]
        assert [r["name"] for r in await repo.get_tasks_by_assignee("s1", "Ana Paula")] == ["Fundação"]

    async def test_task_with_two_assignees_shows_for_both(self, db):
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Içamento", [ANA, JOAO]), "l1")
        await db.commit()

        assert len(await repo.get_tasks_by_assignee("s1", "Ana Paula")) == 1
        assert len(await repo.get_tasks_by_assignee("s1", "João Manuel")) == 1

    async def test_counts_leaf_tasks_like_the_chart_does(self, db):
        """Pai com subtarefas não entra; as subtarefas entram no lugar dele —
        mesma regra de get_assignee_task_stats, senão o total não bate."""
        repo = await _seed(db)
        await repo.upsert_task(_task("pai", "Obra Civil", [ANA]), "l1")
        await repo.upsert_task(_task("sub1", "Escavação", [ANA], parent="pai"), "l1")
        await repo.upsert_task(_task("sub2", "Concretagem", [ANA], parent="pai"), "l1")
        await db.commit()

        rows = await repo.get_tasks_by_assignee("s1", "Ana Paula")
        stats = {s["assignee"]: s for s in await repo.get_assignee_task_stats("s1")}["Ana Paula"]

        assert sorted(r["name"] for r in rows) == ["Concretagem", "Escavação"]
        assert len(rows) == stats["open"] + stats["completed"]

    async def test_carries_province_and_module(self, db):
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Fundação", [ANA]), "l1")
        await db.commit()

        row = (await repo.get_tasks_by_assignee("s1", "Ana Paula"))[0]
        assert row["folder_name"] == "NAMIBE"
        assert row["list_name"] == "Site FM"

    async def test_open_tasks_come_before_completed(self, db):
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Concluída", [ANA], done=True), "l1")
        await repo.upsert_task(_task("t2", "Aberta", [ANA]), "l1")
        await db.commit()

        assert [r["name"] for r in await repo.get_tasks_by_assignee("s1", "Ana Paula")] == [
            "Aberta", "Concluída",
        ]

    async def test_unknown_or_empty_name_returns_nothing(self, db):
        repo = await _seed(db)
        await repo.upsert_task(_task("t1", "Fundação", [ANA]), "l1")
        await db.commit()

        assert await repo.get_tasks_by_assignee("s1", "Ninguém") == []
        assert await repo.get_tasks_by_assignee("s1", "") == []
        assert await repo.get_tasks_by_assignee("s1", "   ") == []

    async def test_other_space_is_not_mixed_in(self, db):
        repo = await _seed(db)
        await repo.upsert_space({"id": "s2", "name": "Outro"})
        await repo.upsert_list({"id": "l9", "name": "Avulsa"}, "s2", None)
        await db.commit()
        await repo.upsert_task(_task("t1", "Daqui", [ANA]), "l1")
        other = _task("t9", "De outro space", [ANA])
        other["list"] = {"id": "l9"}
        await repo.upsert_task(other, "l9")
        await db.commit()

        assert [r["name"] for r in await repo.get_tasks_by_assignee("s1", "Ana Paula")] == ["Daqui"]
