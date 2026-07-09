from datetime import date as _date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.logging import logger
from src.repositories.civil_repository import CivilRepository
from src.services.progress_service import ProgressService
import dataclasses

router = APIRouter(prefix="/civil/progress", tags=["civil-progress"])


def _repo(db: AsyncSession = Depends(get_db)) -> CivilRepository:
    return CivilRepository(db)


def _svc(db: AsyncSession = Depends(get_db)) -> ProgressService:
    return ProgressService(db)


def _parse_date(date_str: str | None) -> _date:
    if not date_str:
        return _date.today()
    try:
        return _date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")


# ─── Profiles ────────────────────────────────────────────────────────────────

@router.get("/profiles")
async def list_profiles(repo: CivilRepository = Depends(_repo)):
    profiles = await repo.list_profiles()
    result = []
    for p in profiles:
        cats = await repo.get_categories(p.id)
        cats_data = []
        for c in cats:
            acts = await repo.get_activity_defs(c.id)
            cats_data.append({
                "id": c.id, "name": c.name, "weight": c.weight, "sort_order": c.sort_order,
                "activities": [{"id": a.id, "name": a.name, "unit": a.unit, "sort_order": a.sort_order} for a in acts],
            })
        result.append({"id": p.id, "name": p.name, "categories": cats_data})
    return result


@router.post("/profiles", status_code=201)
async def create_profile(body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name é obrigatório")
    try:
        profile = await repo.create_profile(name)
        await db.commit()
        return {"id": profile.id, "name": profile.name}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Erro ao criar perfil: {exc}")


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: int, repo: CivilRepository = Depends(_repo)):
    profile = await repo.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Perfil não encontrado")
    cats = await repo.get_categories(profile_id)
    cats_data = []
    for c in cats:
        acts = await repo.get_activity_defs(c.id)
        cats_data.append({
            "id": c.id, "name": c.name, "weight": c.weight, "sort_order": c.sort_order,
            "activities": [{"id": a.id, "name": a.name, "unit": a.unit, "sort_order": a.sort_order} for a in acts],
        })
    return {"id": profile.id, "name": profile.name, "categories": cats_data}


# ─── Categories ───────────────────────────────────────────────────────────────

@router.post("/profiles/{profile_id}/categories", status_code=201)
async def add_category(profile_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    if not await repo.get_profile(profile_id):
        raise HTTPException(status_code=404, detail="Perfil não encontrado")
    name = body.get("name", "").strip()
    weight = body.get("weight")
    if not name or weight is None:
        raise HTTPException(status_code=400, detail="name e weight são obrigatórios")
    cat = await repo.create_category(profile_id, name, float(weight), body.get("sort_order", 0))
    await db.commit()
    return {"id": cat.id, "name": cat.name, "weight": cat.weight, "sort_order": cat.sort_order}


@router.put("/categories/{category_id}")
async def update_category(category_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    cat = await repo.update_category(category_id, body.get("name"), body.get("weight"))
    if not cat:
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    await db.commit()
    return {"id": cat.id, "name": cat.name, "weight": cat.weight}


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    if not await repo.delete_category(category_id):
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    await db.commit()


# ─── Activity Definitions ─────────────────────────────────────────────────────

@router.post("/categories/{category_id}/activities", status_code=201)
async def add_activity_def(category_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    if not await repo.get_category(category_id):
        raise HTTPException(status_code=404, detail="Categoria não encontrada")
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name é obrigatório")
    act = await repo.create_activity_def(category_id, name, body.get("unit"), body.get("sort_order", 0))
    await db.commit()
    return {"id": act.id, "name": act.name, "unit": act.unit, "sort_order": act.sort_order}


@router.delete("/activities/{activity_def_id}", status_code=204)
async def delete_activity_def(activity_def_id: int, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    if not await repo.delete_activity_def(activity_def_id):
        raise HTTPException(status_code=404, detail="Atividade não encontrada")
    await db.commit()


# ─── Site Quantities ──────────────────────────────────────────────────────────

@router.post("/sites/{site_id}/quantities")
async def set_site_quantities(site_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    """
    body: {"quantities": [{"activity_def_id": int, "total_qty": float}, ...]}
    """
    repo = CivilRepository(db)
    if not await repo.get_site(site_id):
        raise HTTPException(status_code=404, detail="Site não encontrado")
    quantities = body.get("quantities", [])
    for q in quantities:
        await repo.upsert_site_activity_qty(site_id, q["activity_def_id"], float(q["total_qty"]))
    await db.commit()
    return {"saved": len(quantities)}


@router.get("/sites/{site_id}/quantities")
async def get_site_quantities(site_id: int, repo: CivilRepository = Depends(_repo)):
    if not await repo.get_site(site_id):
        raise HTTPException(status_code=404, detail="Site não encontrado")
    qtys = await repo.get_site_activity_qtys(site_id)
    return [{"activity_def_id": k, "total_qty": v} for k, v in qtys.items()]


# ─── Measurements ─────────────────────────────────────────────────────────────

@router.post("/measurements")
async def save_measurements(body: dict, db: AsyncSession = Depends(get_db)):
    """
    body: {
      "site_id": int,
      "date": "YYYY-MM-DD",
      "measurements": [{"activity_def_id": int, "qty_yesterday": float, "qty_today": float, "marco": int|null, "notes": str|null}]
    }
    """
    repo = CivilRepository(db)
    site_id = body.get("site_id")
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id é obrigatório")
    if not await repo.get_site(int(site_id)):
        raise HTTPException(status_code=404, detail="Site não encontrado")

    mdate = _parse_date(body.get("date"))
    measurements = body.get("measurements", [])
    for m in measurements:
        await repo.upsert_measurement(
            site_id=int(site_id),
            activity_def_id=int(m["activity_def_id"]),
            mdate=mdate,
            qty_yesterday=float(m.get("qty_yesterday", 0)),
            qty_today=float(m.get("qty_today", 0)),
            marco=m.get("marco"),
            notes=m.get("notes"),
        )
    await db.commit()
    return {"saved": len(measurements), "date": mdate.isoformat()}


# ─── Activity table for measurement form ──────────────────────────────────────

@router.get("/sites/{site_id}/activity-table")
async def get_activity_table(
    site_id: int,
    date: str | None = Query(default=None),
    svc: ProgressService = Depends(_svc),
):
    mdate = _parse_date(date)
    try:
        return await svc.get_site_activity_table(site_id, mdate)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ─── Progress Summary ─────────────────────────────────────────────────────────

@router.get("/site/{site_id}")
async def get_site_progress(
    site_id: int,
    date: str | None = Query(default=None),
    svc: ProgressService = Depends(_svc),
):
    mdate = _parse_date(date)
    try:
        result = await svc.get_site_progress(site_id, mdate)
        return dataclasses.asdict(result)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/summary")
async def get_global_summary(
    date: str | None = Query(default=None),
    svc: ProgressService = Depends(_svc),
):
    mdate = _parse_date(date)
    try:
        result = await svc.get_global_progress(mdate)
        return dataclasses.asdict(result)
    except Exception as exc:
        logger.error(f"Erro ao calcular progresso global: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
