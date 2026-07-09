"""
Testes para as fórmulas de cálculo de progresso EVM civil.
Cobrem as funções puras em progress_service.py e a lógica do ProgressService
contra um SQLite em memória.
"""
import pytest
from datetime import date
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from src.core.database import Base
import src.models.civil_models  # noqa: F401 — registra tabelas no Base
import src.models.progress_models  # noqa: F401

from src.services.progress_service import (
    pct, activity_contribution, site_progress_from_contributions, global_progress,
    ProgressService,
)
from src.repositories.civil_repository import CivilRepository

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
def svc(db: AsyncSession) -> ProgressService:
    return ProgressService(db)


# ─── pct ─────────────────────────────────────────────────────────────────────

def test_pct_normal():
    assert pct(5, 10) == pytest.approx(0.5)


def test_pct_complete():
    assert pct(10, 10) == pytest.approx(1.0)


def test_pct_over_total_clamped():
    assert pct(12, 10) == pytest.approx(1.0)


def test_pct_zero_total():
    assert pct(5, 0) == pytest.approx(0.0)


def test_pct_zero_qty():
    assert pct(0, 100) == pytest.approx(0.0)


def test_pct_negative_total():
    assert pct(5, -1) == pytest.approx(0.0)


# ─── activity_contribution ────────────────────────────────────────────────────

def test_contribution_basic():
    assert activity_contribution(0.20, 0.5) == pytest.approx(0.10)


def test_contribution_zero_pct():
    assert activity_contribution(0.30, 0.0) == pytest.approx(0.0)


def test_contribution_full_pct():
    assert activity_contribution(0.25, 1.0) == pytest.approx(0.25)


# ─── site_progress_from_contributions ─────────────────────────────────────────

def test_site_progress_empty():
    assert site_progress_from_contributions([]) == pytest.approx(0.0)


def test_site_progress_single():
    assert site_progress_from_contributions([0.25]) == pytest.approx(0.25)


def test_site_progress_multiple():
    result = site_progress_from_contributions([0.10, 0.20, 0.05])
    assert result == pytest.approx(0.35)


def test_site_progress_sums_to_one():
    # Perfil Luanda: pesos somam 1.0, todas atividades 100% → progresso = 1.0
    weights = [0.20, 0.05, 0.05, 0.03, 0.05, 0.08, 0.08, 0.06, 0.30, 0.05, 0.05]
    contribs = [w * 1.0 for w in weights]
    assert site_progress_from_contributions(contribs) == pytest.approx(1.0, rel=1e-6)


# ─── global_progress ──────────────────────────────────────────────────────────

def test_global_progress_empty():
    assert global_progress([]) == pytest.approx(0.0)


def test_global_progress_single_site():
    assert global_progress([0.60]) == pytest.approx(0.60)


def test_global_progress_average():
    result = global_progress([0.40, 0.60, 0.80])
    assert result == pytest.approx(0.60)


def test_global_progress_all_zero():
    assert global_progress([0.0, 0.0]) == pytest.approx(0.0)


# ─── Day advance ─────────────────────────────────────────────────────────────

def test_day_advance_positive():
    p_y = pct(40, 100)
    p_t = pct(50, 100)
    assert p_t - p_y == pytest.approx(0.10)


def test_day_advance_no_change():
    p = pct(50, 100)
    assert p - p == pytest.approx(0.0)


# ─── ProgressService integration ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_site_progress_no_profile(repo, svc, db):
    """Site sem perfil → progresso 0, sem atividades."""
    proj = await repo.create_project("P1")
    site = await repo.create_site(proj.id, "Site A")
    await db.commit()

    result = await svc.get_site_progress(site.id, date(2025, 7, 1))
    assert result.progress_today == pytest.approx(0.0)
    assert result.activities == []
    assert result.has_measurements is False


@pytest.mark.asyncio
async def test_site_progress_with_measurements(repo, svc, db):
    """Site com perfil + medições → calcula progresso corretamente."""
    proj = await repo.create_project("P2")
    profile = await repo.create_profile("TestProfile")

    # Duas categorias com pesos 0.60 e 0.40
    cat1 = await repo.create_category(profile.id, "Cat A", weight=0.60)
    cat2 = await repo.create_category(profile.id, "Cat B", weight=0.40)

    act1 = await repo.create_activity_def(cat1.id, "Atividade 1", unit="m2")
    act2 = await repo.create_activity_def(cat2.id, "Atividade 2", unit="un")

    site = await repo.create_site(proj.id, "Site B", profile_id=profile.id)

    await repo.upsert_site_activity_qty(site.id, act1.id, 100.0)
    await repo.upsert_site_activity_qty(site.id, act2.id, 50.0)
    await db.commit()

    mdate = date(2025, 7, 7)
    # act1: 50/100 = 50%; act2: 25/50 = 50%
    await repo.upsert_measurement(site.id, act1.id, mdate, qty_yesterday=40.0, qty_today=50.0)
    await repo.upsert_measurement(site.id, act2.id, mdate, qty_yesterday=20.0, qty_today=25.0)
    await db.commit()

    result = await svc.get_site_progress(site.id, mdate)

    assert result.has_measurements is True
    # progresso_hoje = 0.60 * 0.50 + 0.40 * 0.50 = 0.30 + 0.20 = 0.50
    assert result.progress_today == pytest.approx(0.50)
    # progresso_ontem = 0.60 * 0.40 + 0.40 * 0.40 = 0.24 + 0.16 = 0.40
    assert result.progress_yesterday == pytest.approx(0.40)
    assert result.day_advance == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_global_progress_active_fronts(repo, svc, db):
    """Apenas sites com medições contam para o progresso global."""
    proj = await repo.create_project("P3")
    profile = await repo.create_profile("SimpleProfile")
    cat = await repo.create_category(profile.id, "Cat", weight=1.0)
    act = await repo.create_activity_def(cat.id, "Tarefa", unit="un")

    site_a = await repo.create_site(proj.id, "Site A", profile_id=profile.id)
    site_b = await repo.create_site(proj.id, "Site B", profile_id=profile.id)  # sem medição

    await repo.upsert_site_activity_qty(site_a.id, act.id, 100.0)
    await repo.upsert_site_activity_qty(site_b.id, act.id, 100.0)
    await db.commit()

    mdate = date(2025, 7, 7)
    await repo.upsert_measurement(site_a.id, act.id, mdate, qty_yesterday=0.0, qty_today=80.0)
    await db.commit()

    result = await svc.get_global_progress(mdate)

    assert result.active_fronts == 1
    # global = média de apenas site_a → 0.80
    assert result.global_progress_today == pytest.approx(0.80)


@pytest.mark.asyncio
async def test_measurement_upsert_idempotent(repo, db):
    """Salvar medição duas vezes para o mesmo (site, atividade, data) atualiza sem duplicar."""
    proj = await repo.create_project("P4")
    profile = await repo.create_profile("P4Profile")
    cat = await repo.create_category(profile.id, "Cat", weight=1.0)
    act = await repo.create_activity_def(cat.id, "Act", unit="m")
    site = await repo.create_site(proj.id, "S1", profile_id=profile.id)
    await repo.upsert_site_activity_qty(site.id, act.id, 10.0)
    await db.commit()

    mdate = date(2025, 7, 1)
    await repo.upsert_measurement(site.id, act.id, mdate, 0.0, 3.0)
    await db.commit()
    await repo.upsert_measurement(site.id, act.id, mdate, 3.0, 5.0)
    await db.commit()

    meas = await repo.get_measurements_for_site_date(site.id, mdate)
    assert len(meas) == 1
    assert meas[0].qty_today == pytest.approx(5.0)
    assert meas[0].qty_yesterday == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_site_not_found_raises(svc, db):
    with pytest.raises(ValueError, match="não encontrado"):
        await svc.get_site_progress(99999, date(2025, 1, 1))
