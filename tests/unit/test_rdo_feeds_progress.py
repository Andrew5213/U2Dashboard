"""
Testes de integração: fluxo RDO Diário → Controle de Progresso.

Cobre o caminho end-to-end onde uma atividade registrada no RDO
(seção 4, com activity_def_id) alimenta automaticamente a medição
de progresso civil, sem dupla digitação.
"""
import pytest
from datetime import date
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models.civil_models      # noqa: F401 — registra tabelas no Base
import src.models.progress_models   # noqa: F401

from src.repositories.civil_repository import CivilRepository
from src.services.civil_service import CivilService
from src.services.progress_service import ProgressService

TEST_DB = "sqlite+aiosqlite:///:memory:"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
async def db() -> AsyncSession:
    engine = create_async_engine(TEST_DB, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def repo(db: AsyncSession) -> CivilRepository:
    return CivilRepository(db)


@pytest.fixture
def svc(db: AsyncSession) -> CivilService:
    return CivilService(db)


@pytest.fixture
def progress_svc(db: AsyncSession) -> ProgressService:
    return ProgressService(db)


@pytest.fixture
async def base_setup(repo: CivilRepository, db: AsyncSession):
    """Cria projeto, site com perfil e uma atividade no catálogo."""
    proj = await repo.create_project("Projeto Alpha")
    profile = await repo.create_profile("Perfil Alpha")
    cat = await repo.create_category(profile.id, "Alvenaria", weight=1.0)
    act_def = await repo.create_activity_def(cat.id, "Assentamento de blocos", unit="m2")
    site = await repo.create_site(proj.id, "Site Luanda", profile_id=profile.id)
    await repo.upsert_site_activity_qty(site.id, act_def.id, total_qty=200.0)
    await db.commit()
    return {"proj": proj, "site": site, "cat": cat, "act_def": act_def}


# ─── Atividade livre (sem activity_def_id) não cria medição ──────────────────

@pytest.mark.asyncio
async def test_free_activity_does_not_create_measurement(base_setup, svc, repo, db):
    """Atividade sem vínculo ao catálogo não deve gerar medição de progresso."""
    setup = base_setup
    site = setup["site"]

    report_data = {
        "site_id": site.id,
        "date": date(2025, 7, 1),
        "responsible": "Eng. Teste",
        "activities": [
            {
                "activity_description": "Serviço avulso sem catálogo",
                "qty_day": 15.0,
                # activity_def_id intencionalmente omitido
            }
        ],
    }
    result = await svc.create_report(report_data)
    await db.commit()

    measurements = await repo.get_measurements_for_site_date(site.id, date(2025, 7, 1))
    assert measurements == [], "Atividade livre não deve criar medição de progresso"


# ─── Atividade do catálogo cria medição automática ───────────────────────────

@pytest.mark.asyncio
async def test_catalog_activity_creates_measurement(base_setup, svc, repo, db):
    """Atividade com activity_def_id cria medição: qty_today = 0 + qty_day."""
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]

    report_data = {
        "site_id": site.id,
        "date": date(2025, 7, 1),
        "responsible": "Eng. Teste",
        "activities": [
            {
                "activity_description": "Assentamento de blocos",
                "activity_def_id": act_def.id,
                "unit": "m2",
                "qty_day": 20.0,
                "status": "em_andamento",
            }
        ],
    }
    await svc.create_report(report_data)
    await db.commit()

    measurements = await repo.get_measurements_for_site_date(site.id, date(2025, 7, 1))
    assert len(measurements) == 1
    m = measurements[0]
    assert m.activity_def_id == act_def.id
    assert m.qty_yesterday == pytest.approx(0.0)
    assert m.qty_today == pytest.approx(20.0)


# ─── Segundo dia acumula corretamente ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_second_day_accumulates(base_setup, svc, repo, db):
    """Dia 2: qty_today = qty_today_dia1 + qty_day_dia2."""
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]

    # Dia 1: 20 m2
    await svc.create_report({
        "site_id": site.id,
        "date": date(2025, 7, 1),
        "activities": [
            {"activity_description": "Bloco", "activity_def_id": act_def.id, "qty_day": 20.0}
        ],
    })
    await db.commit()

    # Dia 2: mais 15 m2
    await svc.create_report({
        "site_id": site.id,
        "date": date(2025, 7, 2),
        "activities": [
            {"activity_description": "Bloco", "activity_def_id": act_def.id, "qty_day": 15.0}
        ],
    })
    await db.commit()

    m1 = await repo.get_measurement_for_date(site.id, act_def.id, date(2025, 7, 1))
    m2 = await repo.get_measurement_for_date(site.id, act_def.id, date(2025, 7, 2))

    assert m1 is not None
    assert m1.qty_today == pytest.approx(20.0)

    assert m2 is not None
    assert m2.qty_yesterday == pytest.approx(20.0)
    assert m2.qty_today == pytest.approx(35.0)


# ─── Regra "maior valor vence" ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_manual_override_preserved_when_higher(base_setup, repo, db):
    """Medição manual maior que o auto-preenchimento deve ser preservada."""
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]
    mdate = date(2025, 7, 1)

    # Insere medição manual com valor alto (30)
    await repo.upsert_measurement(site.id, act_def.id, mdate, qty_yesterday=0.0, qty_today=30.0)
    await db.commit()

    # RDO calcula apenas 20 → não deve sobrescrever
    svc = CivilService(db)
    await svc._auto_fill_measurements(
        site_id=site.id,
        report_date=mdate,
        activities=[
            type("Act", (), {"activity_def_id": act_def.id, "qty_day": 20.0})()
        ],
    )
    await db.commit()

    m = await repo.get_measurement_for_date(site.id, act_def.id, mdate)
    assert m is not None
    assert m.qty_today == pytest.approx(30.0), "Valor manual maior deve ser preservado"


@pytest.mark.asyncio
async def test_autofill_wins_when_higher(base_setup, repo, db):
    """Auto-preenchimento vence quando calcula valor maior que a medição existente."""
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]
    mdate = date(2025, 7, 1)

    # Medição existente pequena (5)
    await repo.upsert_measurement(site.id, act_def.id, mdate, qty_yesterday=0.0, qty_today=5.0)
    await db.commit()

    # RDO calcula 25 → deve sobrescrever
    svc = CivilService(db)
    await svc._auto_fill_measurements(
        site_id=site.id,
        report_date=mdate,
        activities=[
            type("Act", (), {"activity_def_id": act_def.id, "qty_day": 25.0})()
        ],
    )
    await db.commit()

    m = await repo.get_measurement_for_date(site.id, act_def.id, mdate)
    assert m is not None
    assert m.qty_today == pytest.approx(25.0), "Auto-preenchimento deve vencer quando maior"


# ─── project_id propagado automaticamente ────────────────────────────────────

@pytest.mark.asyncio
async def test_project_id_auto_propagated(base_setup, svc, repo, db):
    """create_report deve preencher project_id a partir do site quando não informado."""
    setup = base_setup
    site = setup["site"]
    proj = setup["proj"]

    result = await svc.create_report({
        "site_id": site.id,
        "date": date(2025, 7, 5),
        "responsible": "Eng. X",
    })
    await db.commit()

    report = await repo.get_report(result["id"])
    assert report is not None
    assert report.project_id == proj.id


# ─── project_id permite consulta de dia completo ─────────────────────────────

@pytest.mark.asyncio
async def test_list_reports_for_project_day(base_setup, svc, repo, db):
    """list_reports_for_project_day retorna todos os sites com RDO naquela data."""
    setup = base_setup
    proj = setup["proj"]
    site_a = setup["site"]

    # Segundo site no mesmo projeto
    site_b = await repo.create_site(proj.id, "Site Benguela")
    await db.commit()

    target_date = date(2025, 7, 10)
    other_date = date(2025, 7, 11)

    await svc.create_report({"site_id": site_a.id, "date": target_date})
    await db.commit()
    await svc.create_report({"site_id": site_b.id, "date": target_date})
    await db.commit()
    await svc.create_report({"site_id": site_a.id, "date": other_date})
    await db.commit()

    reports = await repo.list_reports_for_project_day(proj.id, target_date)
    assert len(reports) == 2
    site_ids = {r.site_id for r in reports}
    assert site_a.id in site_ids
    assert site_b.id in site_ids


# ─── E2E: RDO → medição → progresso global ───────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_rdo_feeds_global_progress(base_setup, svc, progress_svc, repo, db):
    """
    Fluxo completo: registrar qty_day no RDO → medição criada automaticamente
    → ProgressService.get_global_progress() reflete o progresso atualizado.
    """
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]
    mdate = date(2025, 7, 7)

    # Sem RDO ainda: progresso zero
    before = await progress_svc.get_global_progress(mdate)
    assert before.global_progress_today == pytest.approx(0.0)

    # Cria RDO com 100 m2 executados (total planejado = 200)
    await svc.create_report({
        "site_id": site.id,
        "date": mdate,
        "activities": [
            {
                "activity_description": "Assentamento de blocos",
                "activity_def_id": act_def.id,
                "unit": "m2",
                "qty_day": 100.0,
            }
        ],
    })
    await db.commit()

    # Progresso deve ser 100/200 = 50% (categoria com peso 1.0)
    after = await progress_svc.get_global_progress(mdate)
    assert after.active_fronts == 1
    assert after.global_progress_today == pytest.approx(0.50)


# ─── Múltiplas atividades no mesmo RDO ───────────────────────────────────────

@pytest.mark.asyncio
async def test_multiple_catalog_activities_in_one_report(base_setup, svc, repo, db):
    """RDO com duas atividades do catálogo cria duas medições independentes."""
    setup = base_setup
    site = setup["site"]
    cat = setup["cat"]
    act_def1 = setup["act_def"]

    act_def2 = await repo.create_activity_def(cat.id, "Reboco", unit="m2")
    await repo.upsert_site_activity_qty(site.id, act_def2.id, total_qty=100.0)
    await db.commit()

    mdate = date(2025, 7, 3)
    await svc.create_report({
        "site_id": site.id,
        "date": mdate,
        "activities": [
            {"activity_description": "Bloco", "activity_def_id": act_def1.id, "qty_day": 10.0},
            {"activity_description": "Reboco", "activity_def_id": act_def2.id, "qty_day": 5.0},
            {"activity_description": "Serviço avulso"},  # sem activity_def_id
        ],
    })
    await db.commit()

    measurements = await repo.get_measurements_for_site_date(site.id, mdate)
    assert len(measurements) == 2

    qty_map = {m.activity_def_id: m.qty_today for m in measurements}
    assert qty_map[act_def1.id] == pytest.approx(10.0)
    assert qty_map[act_def2.id] == pytest.approx(5.0)


# ─── Atualização do RDO re-calcula medição ───────────────────────────────────

@pytest.mark.asyncio
async def test_update_report_recalculates_measurement(base_setup, svc, repo, db):
    """Atualizar atividade via PATCH recalcula a medição se o novo valor for maior."""
    setup = base_setup
    site = setup["site"]
    act_def = setup["act_def"]
    mdate = date(2025, 7, 4)

    # Cria RDO inicial com 10 m2 — não carregamos a medição aqui para evitar
    # objeto stale na identity map (upsert usa SQL raw, não atualiza o ORM cache).
    result = await svc.create_report({
        "site_id": site.id,
        "date": mdate,
        "activities": [
            {"activity_description": "Bloco", "activity_def_id": act_def.id, "qty_day": 10.0}
        ],
    })
    await db.commit()
    report_id = result["id"]

    # Verifica estado inicial via get_full_report (não carrega CivilProgressMeasurement)
    full = await svc.get_full_report(report_id)
    assert full is not None
    assert full["activities"][0]["qty_day"] == pytest.approx(10.0)

    # Atualiza para 25 m2
    await svc.update_report(report_id, {
        "activities": [
            {"activity_description": "Bloco", "activity_def_id": act_def.id, "qty_day": 25.0}
        ],
    })
    await db.commit()

    # Lê a medição numa sessão limpa para evitar cache stale
    measurements = await repo.get_measurements_for_site_date(site.id, mdate)
    assert len(measurements) == 1
    assert measurements[0].qty_today == pytest.approx(25.0)
