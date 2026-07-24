import json
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from src.core.database import Base
from src.models.cache_models import (
    ClickUpSpaceCache, ClickUpFolderCache, ClickUpListCache, ClickUpTaskCache, DisciplineWeight,
)
from src.repositories.cache_repository import (
    CacheRepository, _ms_to_dt, _FIELD_VENCIMENTO_ID, _FIELD_DATA_CONCLUSAO_ID, _FIELD_OBSERVACOES_ID,
)

# ─── Setup in-memory SQLite ──────────────────────────────────────────────────

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
def repo(db: AsyncSession) -> CacheRepository:
    return CacheRepository(db)


# ─── _ms_to_dt ───────────────────────────────────────────────────────────────

def test_ms_to_dt_valid():
    dt = _ms_to_dt("1748649600000")
    assert dt is not None
    assert dt.year == 2025


def test_ms_to_dt_none():
    assert _ms_to_dt(None) is None


def test_ms_to_dt_empty():
    assert _ms_to_dt("") is None


def test_ms_to_dt_invalid():
    assert _ms_to_dt("not-a-number") is None


# ─── upsert_space ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_space_creates(repo, db):
    await repo.upsert_space({"id": "space1", "name": "RNA", "private": False})
    await db.commit()
    space = await db.get(ClickUpSpaceCache, "space1")
    assert space is not None
    assert space.name == "RNA"


@pytest.mark.asyncio
async def test_upsert_space_is_idempotent(repo, db):
    await repo.upsert_space({"id": "space1", "name": "RNA", "private": False})
    await db.commit()
    await repo.upsert_space({"id": "space1", "name": "RNA Updated", "private": False})
    await db.commit()
    space = await db.get(ClickUpSpaceCache, "space1")
    assert space.name == "RNA Updated"


# ─── upsert_folder ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "Studios", "hidden": False, "task_count": 5}, "s1")
    await db.commit()
    folder = await db.get(ClickUpFolderCache, "f1")
    assert folder.name == "Studios"
    assert folder.space_id == "s1"


# ─── upsert_list ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upsert_list_with_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "F"}, "s1")
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "Lista A", "task_count": 10}, "s1", "f1")
    await db.commit()
    lst = await db.get(ClickUpListCache, "l1")
    assert lst.name == "Lista A"
    assert lst.folder_id == "f1"


@pytest.mark.asyncio
async def test_upsert_list_without_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l2", "name": "Sem Folder"}, "s1", None)
    await db.commit()
    lst = await db.get(ClickUpListCache, "l2")
    assert lst.folder_id is None


# ─── upsert_task ─────────────────────────────────────────────────────────────

@pytest.fixture
async def seed_list(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", None)
    await db.commit()


@pytest.mark.asyncio
async def test_upsert_task_basic(repo, db, seed_list):
    task = {
        "id": "t1",
        "name": "Instalar antena",
        "status": {"status": "in progress", "type": "open", "color": "#4ade80"},
        "assignees": [{"id": "u1", "username": "João"}],
        "due_date": "1748649600000",
        "custom_fields": [{"id": _FIELD_VENCIMENTO_ID, "value": "1748649600000"}],
        "list": {"id": "l1"},
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.name == "Instalar antena"
    assert t.status == "in progress"
    assert t.status_type == "open"
    assert t.due_date is not None
    parsed = json.loads(t.assignees_json)
    assert any(a["username"] == "João" for a in parsed)


@pytest.mark.asyncio
async def test_upsert_task_idempotent(repo, db, seed_list):
    base = {"id": "t1", "name": "Original", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}}
    await repo.upsert_task(base, "l1")
    await db.commit()
    updated = {**base, "name": "Atualizado"}
    await repo.upsert_task(updated, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.name == "Atualizado"


# ─── upsert_task — custom fields "Vencimento"/"Data de Conclusão" ────────────

@pytest.mark.asyncio
async def test_upsert_task_prefers_vencimento_field_over_native_due_date(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
        "due_date": "1700000000000",  # nativo — deve ser ignorado
        "custom_fields": [{"id": _FIELD_VENCIMENTO_ID, "value": "1800000000000"}],
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.due_date == _ms_to_dt("1800000000000")


@pytest.mark.asyncio
async def test_upsert_task_ignores_native_due_date_when_field_unset(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
        "due_date": "1700000000000",  # nativo — nao deve mais ser usado, nem como fallback
        "custom_fields": [{"id": _FIELD_VENCIMENTO_ID, "value": None}],
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.due_date is None


@pytest.mark.asyncio
async def test_upsert_task_prefers_data_conclusao_field_over_native_date_closed(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "complete", "type": "done"},
        "list": {"id": "l1"},
        "date_closed": "1700000000000",  # nativo — deve ser ignorado
        "custom_fields": [{"id": _FIELD_DATA_CONCLUSAO_ID, "value": "1800000000000"}],
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.date_closed == _ms_to_dt("1800000000000")


@pytest.mark.asyncio
async def test_upsert_task_without_custom_fields_key_has_no_due_date(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"}, "due_date": "1700000000000",  # nativo — ignorado
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.due_date is None


@pytest.mark.asyncio
async def test_upsert_task_stores_observacoes_field(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
        "custom_fields": [{"id": _FIELD_OBSERVACOES_ID, "value": "Aguardando material do fornecedor"}],
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.observacoes == "Aguardando material do fornecedor"


@pytest.mark.asyncio
async def test_upsert_task_without_observacoes_is_none(repo, db, seed_list):
    task = {
        "id": "t1", "name": "Task", "status": {"status": "open", "type": "open"},
        "list": {"id": "l1"},
    }
    await repo.upsert_task(task, "l1")
    await db.commit()
    t = await db.get(ClickUpTaskCache, "t1")
    assert t.observacoes is None


# ─── mark_tasks_stale ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_tasks_stale_removes_orphans(repo, db, seed_list):
    for tid in ["t1", "t2", "t3"]:
        await repo.upsert_task({"id": tid, "name": tid, "list": {"id": "l1"}}, "l1")
    await db.commit()
    removed = await repo.mark_tasks_stale("l1", {"t1", "t2"})
    await db.commit()
    assert removed == 1
    assert await db.get(ClickUpTaskCache, "t3") is None
    assert await db.get(ClickUpTaskCache, "t1") is not None


@pytest.mark.asyncio
async def test_mark_tasks_stale_removes_deleted_subtasks(repo, db, seed_list):
    # Task pai + duas subtasks — uma delas foi apagada no ClickUp e não vem mais em `seen_ids`
    await repo.upsert_task({"id": "parent", "name": "Pai", "list": {"id": "l1"}}, "l1")
    await repo.upsert_task({"id": "sub1", "name": "Sub 1", "list": {"id": "l1"}, "parent": "parent"}, "l1")
    await repo.upsert_task({"id": "sub2", "name": "Sub 2", "list": {"id": "l1"}, "parent": "parent"}, "l1")
    await db.commit()

    removed = await repo.mark_tasks_stale("l1", {"parent", "sub1"})
    await db.commit()

    assert removed == 1
    assert await db.get(ClickUpTaskCache, "sub2") is None
    assert await db.get(ClickUpTaskCache, "sub1") is not None
    assert await db.get(ClickUpTaskCache, "parent") is not None


# ─── mark_lists_stale / mark_folders_stale ────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_lists_stale_removes_deleted_list_and_its_data(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "Fica"}, "s1", None)
    await repo.upsert_list({"id": "l2", "name": "Apagada no ClickUp"}, "s1", None)
    await db.commit()
    await repo.upsert_task({"id": "t1", "name": "t1", "list": {"id": "l2"}}, "l2")
    await db.commit()
    await repo.set_discipline_weights({"l2": 0.5})
    await db.commit()

    removed = await repo.mark_lists_stale("s1", {"l1"})
    await db.commit()

    assert removed == 1
    assert await db.get(ClickUpListCache, "l1") is not None
    assert await db.get(ClickUpListCache, "l2") is None
    assert await db.get(ClickUpTaskCache, "t1") is None
    assert (await db.get(DisciplineWeight, "l2")) is None


@pytest.mark.asyncio
async def test_mark_lists_stale_ignores_other_spaces(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S1"})
    await repo.upsert_space({"id": "s2", "name": "S2"})
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "Outro space"}, "s2", None)
    await db.commit()

    removed = await repo.mark_lists_stale("s1", set())
    await db.commit()

    assert removed == 0
    assert await db.get(ClickUpListCache, "l1") is not None


@pytest.mark.asyncio
async def test_mark_folders_stale_removes_deleted_folder(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await db.commit()
    await repo.upsert_folder({"id": "f1", "name": "Fica"}, "s1")
    await repo.upsert_folder({"id": "f2", "name": "Apagada no ClickUp"}, "s1")
    await db.commit()

    removed = await repo.mark_folders_stale("s1", {"f1"})
    await db.commit()

    assert removed == 1
    assert await db.get(ClickUpFolderCache, "f1") is not None
    assert await db.get(ClickUpFolderCache, "f2") is None


# ─── get_task_list_id / delete_task ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_task_list_id(repo, db, seed_list):
    await repo.upsert_task({"id": "t1", "name": "t1", "list": {"id": "l1"}}, "l1")
    await db.commit()
    assert await repo.get_task_list_id("t1") == "l1"


@pytest.mark.asyncio
async def test_get_task_list_id_missing(repo, db, seed_list):
    assert await repo.get_task_list_id("nao-existe") is None


@pytest.mark.asyncio
async def test_delete_task(repo, db, seed_list):
    await repo.upsert_task({"id": "t1", "name": "t1", "list": {"id": "l1"}}, "l1")
    await db.commit()
    await repo.delete_task("t1")
    await db.commit()
    assert await db.get(ClickUpTaskCache, "t1") is None


# ─── get_overview_kpis ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_overview_kpis(repo, db, seed_list):
    tasks = [
        {"id": "t1", "name": "A", "status": {"status": "complete", "type": "closed"}, "list": {"id": "l1"}},
        {"id": "t2", "name": "B", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"},
         "custom_fields": [{"id": _FIELD_VENCIMENTO_ID, "value": "1000"}]},
        {"id": "t3", "name": "C", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
    ]
    for t in tasks:
        await repo.upsert_task(t, "l1")
    await db.commit()

    kpis = await repo.get_overview_kpis("s1")
    assert kpis["total_tasks"] == 3
    assert kpis["completed_tasks"] == 1
    assert kpis["overdue_tasks"] == 1  # t2 tem due_date no passado
    assert kpis["tasks_without_due_date"] == 2  # t1 e t3
    assert kpis["completion_rate"] == pytest.approx(1 / 3, abs=0.01)


@pytest.mark.asyncio
async def test_get_overview_kpis_counts_subtasks_not_parent(repo, db, seed_list):
    # Task pai com subtasks: o progresso deve vir das subtasks, não da task pai.
    await repo.upsert_task(
        {"id": "parent1", "name": "Pai", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "sub1", "name": "Sub1", "status": {"status": "complete", "type": "closed"},
         "parent": "parent1", "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "sub2", "name": "Sub2", "status": {"status": "open", "type": "open"},
         "parent": "parent1", "list": {"id": "l1"}},
        "l1",
    )
    # Task de topo sem subtasks: conta por ela mesma.
    await repo.upsert_task(
        {"id": "leaf1", "name": "Leaf", "status": {"status": "complete", "type": "closed"}, "list": {"id": "l1"}},
        "l1",
    )
    await db.commit()

    kpis = await repo.get_overview_kpis("s1")
    # Contagem bruta: sub1, sub2, leaf1 (parent1 é excluído por ter subtasks)
    assert kpis["total_tasks"] == 3
    assert kpis["completed_tasks"] == 2
    # completion_rate agora vem do progresso ponderado (weights_config.py), não da
    # contagem simples: parent1 e leaf1 são as 2 disciplinas da lista, cada uma com
    # peso igual (nomes não mapeados caem no fallback). parent1 = 0.5 (1 de 2
    # subtasks concluída, pesos iguais); leaf1 = 1.0 (concluída). Média = 0.75.
    assert kpis["completion_rate"] == pytest.approx(0.75, abs=0.01)


@pytest.mark.asyncio
async def test_get_lists_with_metrics_applies_real_engineering_weights(repo, db, seed_list):
    # "Obras Civis" (peso 30) e "Fim das Obras" (peso 2) são disciplinas reais
    # mapeadas em weights_config.py — o teste prova que o peso real é usado, não
    # o fallback de peso igual nem a contagem simples de tarefas-folha.
    await repo.upsert_task(
        {"id": "civis", "name": "Obras Civis", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "paredes", "name": "Paredes", "status": {"status": "complete", "type": "closed"},
         "parent": "civis", "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "pisos", "name": "Pisos", "status": {"status": "open", "type": "open"},
         "parent": "civis", "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "tetos", "name": "Tetos", "status": {"status": "open", "type": "open"},
         "parent": "civis", "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "fim", "name": "Fim das Obras", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
        "l1",
    )
    await db.commit()

    lists = await repo.get_lists_with_metrics(None, space_id="s1")
    l1 = next(l for l in lists if l["list_id"] == "l1")

    # Ponderado: Obras Civis (peso 30/32) x progresso interno (Paredes 30 de 73
    # concluída) + Fim das Obras (peso 2/32) x 0 = (30/32)*(30/73)
    expected = (30 / 32) * (30 / 73)
    assert l1["completion_rate"] == pytest.approx(expected, abs=0.001)

    # Contagem simples de tarefas-folha daria 1/4 (Paredes de 4 folhas) — o
    # resultado real diverge, confirmando que o peso de engenharia foi aplicado.
    assert l1["completion_rate"] != pytest.approx(0.25, abs=0.01)


@pytest.mark.asyncio
async def test_get_folder_kpis_counts_subtasks_not_parent(repo, db):
    await repo.upsert_space({"id": "s1", "name": "S"})
    await repo.upsert_folder({"id": "f1", "name": "F"}, "s1")
    await db.commit()
    await repo.upsert_list({"id": "l1", "name": "L"}, "s1", "f1")
    await db.commit()

    await repo.upsert_task(
        {"id": "parent1", "name": "Pai", "status": {"status": "open", "type": "open"}, "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "sub1", "name": "Sub1", "status": {"status": "complete", "type": "closed"},
         "parent": "parent1", "list": {"id": "l1"}},
        "l1",
    )
    await repo.upsert_task(
        {"id": "sub2", "name": "Sub2", "status": {"status": "open", "type": "open"},
         "parent": "parent1", "list": {"id": "l1"}},
        "l1",
    )
    await db.commit()

    kpis = await repo.get_folder_kpis("f1")
    # Unidades: sub1, sub2 (parent1 é excluído por ter subtasks)
    assert kpis["total_tasks"] == 2
    assert kpis["completed_tasks"] == 1
    assert kpis["completion_rate"] == pytest.approx(0.5, abs=0.01)


# ─── get_subtask_count_by_parent ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subtask_count(repo, db, seed_list):
    await repo.upsert_task({"id": "parent1", "name": "Pai", "list": {"id": "l1"}}, "l1")
    await db.commit()
    for i in range(3):
        await repo.upsert_task(
            {"id": f"sub{i}", "name": f"Sub{i}", "parent": "parent1", "list": {"id": "l1"}}, "l1"
        )
    await db.commit()
    counts = await repo.get_subtask_count_by_parent("l1")
    assert counts.get("parent1") == 3
