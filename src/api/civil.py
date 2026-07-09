from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import get_db
from src.core.logging import logger
from src.repositories.civil_repository import CivilRepository
from src.services.civil_service import CivilService
from src.models.civil_models import CIVIL_DISCIPLINES

router = APIRouter(prefix="/civil", tags=["civil"])


def _repo(db: AsyncSession = Depends(get_db)) -> CivilRepository:
    return CivilRepository(db)


def _svc(db: AsyncSession = Depends(get_db)) -> CivilService:
    return CivilService(db)


async def _project_progress_for_pdf(db: AsyncSession, site_id: int, start_date: date, end_date: date | None = None):
    """Progresso de todos os sites do projeto do site informado, no período [start_date, end_date].
    Usado pelos exports de PDF (diário e semanal) para a seção de progresso EVM."""
    from src.services.progress_service import ProgressService

    repo = CivilRepository(db)
    site = await repo.get_site(site_id)
    if not site or not site.project_id:
        return []
    progress_svc = ProgressService(db)
    return await progress_svc.get_project_progress_range(
        site.project_id, start_date, end_date or start_date
    )


# ─── Projects ────────────────────────────────────────────────────────────────

@router.get("/projects")
async def list_projects(repo: CivilRepository = Depends(_repo)):
    projects = await repo.list_projects()
    return [{"id": p.id, "name": p.name, "description": p.description, "created_at": p.created_at.isoformat()} for p in projects]


@router.post("/projects", status_code=201)
async def create_project(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    repo = CivilRepository(db)
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name é obrigatório")
    proj = await repo.create_project(name, body.get("description"))
    await db.commit()
    return {"id": proj.id, "name": proj.name, "description": proj.description}


@router.get("/projects/{project_id}")
async def get_project(project_id: int, repo: CivilRepository = Depends(_repo)):
    proj = await repo.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    return {"id": proj.id, "name": proj.name, "description": proj.description}


@router.put("/projects/{project_id}")
async def update_project(project_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    proj = await repo.update_project(project_id, body.get("name", ""), body.get("description"))
    if not proj:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    await db.commit()
    return {"id": proj.id, "name": proj.name, "description": proj.description}


# ─── Sites ───────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/sites")
async def list_sites(project_id: int, repo: CivilRepository = Depends(_repo)):
    sites = await repo.list_sites(project_id)
    return [{"id": s.id, "name": s.name, "province": s.province, "profile_id": s.profile_id} for s in sites]


@router.post("/projects/{project_id}/sites", status_code=201)
async def create_site(project_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    proj = await repo.get_project(project_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name é obrigatório")
    site = await repo.create_site(project_id, name, body.get("province"), body.get("profile_id"))
    await db.commit()
    return {"id": site.id, "name": site.name, "province": site.province, "profile_id": site.profile_id}


@router.get("/sites")
async def list_all_sites(repo: CivilRepository = Depends(_repo)):
    sites = await repo.list_all_sites()
    return [{"id": s.id, "project_id": s.project_id, "name": s.name, "province": s.province, "profile_id": s.profile_id} for s in sites]


@router.put("/sites/{site_id}")
async def update_site(site_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    repo = CivilRepository(db)
    site = await repo.update_site(
        site_id,
        name=body.get("name"),
        province=body.get("province"),
        profile_id=body.get("profile_id"),
    )
    if not site:
        raise HTTPException(status_code=404, detail="Site não encontrado")
    await db.commit()
    return {"id": site.id, "name": site.name, "province": site.province, "profile_id": site.profile_id}


# ─── Reports ─────────────────────────────────────────────────────────────────

@router.get("/reports")
async def list_reports(
    site_id: int | None = Query(default=None),
    date: str | None = Query(default=None),
    project_id: int | None = Query(default=None),
    repo: CivilRepository = Depends(_repo),
):
    parsed_date = None
    if date:
        try:
            from datetime import date as _date
            parsed_date = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
    reports = await repo.list_reports(site_id=site_id, report_date=parsed_date, project_id=project_id)
    return [
        {
            "id": r.id, "site_id": r.site_id, "report_number": r.report_number,
            "date": r.date.isoformat(), "responsible": r.responsible,
            "general_situation": r.general_situation, "created_at": r.created_at.isoformat(),
        }
        for r in reports
    ]


@router.post("/reports", status_code=201)
async def create_report(body: dict, db: AsyncSession = Depends(get_db)):
    svc = CivilService(db)
    repo = CivilRepository(db)

    site_id = body.get("site_id")
    if not site_id:
        raise HTTPException(status_code=400, detail="site_id é obrigatório")
    site = await repo.get_site(int(site_id))
    if not site:
        raise HTTPException(status_code=404, detail="Site não encontrado")

    # Convert date string
    if "date" in body and isinstance(body["date"], str):
        from datetime import date as _date
        try:
            body["date"] = _date.fromisoformat(body["date"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")

    # Check for existing report on same site+date
    existing = await repo.get_report_by_site_date(int(site_id), body["date"])
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe o RDO nº {existing.report_number} para este site nesta data (id={existing.id})",
        )

    try:
        result = await svc.create_report(body)
        await db.commit()
        return result
    except Exception as exc:
        logger.error(f"Erro ao criar RDO: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/reports/{report_id}")
async def get_report(report_id: int, svc: CivilService = Depends(_svc)):
    result = await svc.get_full_report(report_id)
    if not result:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    return result


@router.patch("/reports/{report_id}")
async def update_report(report_id: int, body: dict, db: AsyncSession = Depends(get_db)):
    svc = CivilService(db)
    result = await svc.update_report(report_id, body)
    if not result:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    await db.commit()
    return result


@router.post("/reports/{report_id}/photos", status_code=201)
async def upload_photo(
    report_id: int,
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
    location: str | None = Form(default=None),
    taken_at: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    allowed = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    ext = ""
    if file.filename:
        import os
        ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo não permitido. Use: {', '.join(allowed)}")

    file_bytes = await file.read()
    if len(file_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Arquivo muito grande (máx 20 MB)")

    svc = CivilService(db)
    try:
        photo = await svc.save_photo(
            report_id=report_id,
            file_bytes=file_bytes,
            original_filename=file.filename or "foto.jpg",
            description=description,
            location=location,
            taken_at=taken_at,
            photos_dir=settings.civil_uploads_dir,
        )
        await db.commit()
        return photo
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Erro ao salvar foto: {exc}")
        raise HTTPException(status_code=500, detail="Erro ao salvar foto")


# ─── PDF export ──────────────────────────────────────────────────────────────

@router.get("/reports/{report_id}/pdf")
async def export_rdo_pdf(
    report_id: int,
    inline: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Exporta um RDO individual em PDF."""
    from src.services.rdo_pdf_service import generate_rdo_pdf

    svc = CivilService(db)
    full = await svc.get_full_report(report_id)
    if not full:
        raise HTTPException(status_code=404, detail="RDO não encontrado")

    report_date = date.fromisoformat(full["date"])
    project_progress = await _project_progress_for_pdf(
        db, full["site_id"], report_date - timedelta(days=1), report_date
    )

    pdf_bytes = generate_rdo_pdf(full, site_name=full.get("local_site") or "", project_progress=project_progress)
    num = full.get("report_number", report_id)
    date_str = str(full.get("date", "")).replace("-", "")
    filename = f"RDO_{num:03d}_{date_str}.pdf"
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": disposition})


@router.get("/reports/pdf/weekly")
async def export_weekly_rdo_pdf(
    site_id: int = Query(..., description="ID do site"),
    date: str | None = Query(default=None, description="Qualquer data da semana (YYYY-MM-DD). Padrão: semana atual"),
    inline: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
):
    """Exporta relatório semanal consolidado (segunda a domingo) em PDF."""
    from datetime import date as _date
    from src.services.rdo_pdf_service import generate_weekly_rdo_pdf

    if date:
        try:
            ref = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
    else:
        ref = _date.today()

    week_start = ref - timedelta(days=ref.weekday())   # segunda-feira
    week_end = week_start + timedelta(days=6)          # domingo

    repo = CivilRepository(db)
    site = await repo.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site não encontrado")

    raw = await repo.list_reports(site_id=site_id, start_date=week_start, end_date=week_end)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum RDO encontrado para {site.name} na semana {week_start} – {week_end}",
        )

    svc = CivilService(db)
    reports = [r for r in [await svc.get_full_report(rpt.id) for rpt in raw] if r]

    project_progress = await _project_progress_for_pdf(
        db, site_id, week_start - timedelta(days=1), week_end
    )

    week_label = f"{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}"
    pdf_bytes = generate_weekly_rdo_pdf(
        reports, site_name=site.name, week_label=week_label, project_progress=project_progress
    )

    safe_name = site.name.replace(" ", "_")
    filename = f"RDO_Semanal_{safe_name}_{week_start.strftime('%Y%m%d')}.pdf"
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": disposition})


# ─── XLSX export ─────────────────────────────────────────────────────────────

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/reports/{report_id}/xlsx")
async def export_rdo_xlsx(
    report_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Exporta um RDO individual em .xlsx."""
    from src.services.rdo_xlsx_service import generate_rdo_xlsx

    svc = CivilService(db)
    full = await svc.get_full_report(report_id)
    if not full:
        raise HTTPException(status_code=404, detail="RDO não encontrado")

    report_date = date.fromisoformat(full["date"])
    project_progress = await _project_progress_for_pdf(
        db, full["site_id"], report_date - timedelta(days=1), report_date
    )

    xlsx_bytes = generate_rdo_xlsx(full, site_name=full.get("local_site") or "", project_progress=project_progress)
    num = full.get("report_number", report_id)
    date_str = str(full.get("date", "")).replace("-", "")
    filename = f"RDO_{num:03d}_{date_str}.xlsx"
    return Response(content=xlsx_bytes, media_type=_XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/reports/xlsx/weekly")
async def export_weekly_rdo_xlsx(
    site_id: int = Query(..., description="ID do site"),
    date: str | None = Query(default=None, description="Qualquer data da semana (YYYY-MM-DD). Padrão: semana atual"),
    db: AsyncSession = Depends(get_db),
):
    """Exporta relatório semanal consolidado (segunda a domingo) em .xlsx."""
    from datetime import date as _date
    from src.services.rdo_xlsx_service import generate_weekly_rdo_xlsx

    if date:
        try:
            ref = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")
    else:
        ref = _date.today()

    week_start = ref - timedelta(days=ref.weekday())   # segunda-feira
    week_end = week_start + timedelta(days=6)          # domingo

    repo = CivilRepository(db)
    site = await repo.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site não encontrado")

    raw = await repo.list_reports(site_id=site_id, start_date=week_start, end_date=week_end)
    if not raw:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum RDO encontrado para {site.name} na semana {week_start} – {week_end}",
        )

    svc = CivilService(db)
    reports = [r for r in [await svc.get_full_report(rpt.id) for rpt in raw] if r]

    project_progress = await _project_progress_for_pdf(
        db, site_id, week_start - timedelta(days=1), week_end
    )

    week_label = f"{week_start.strftime('%d/%m/%Y')} – {week_end.strftime('%d/%m/%Y')}"
    xlsx_bytes = generate_weekly_rdo_xlsx(
        reports, site_name=site.name, week_label=week_label, project_progress=project_progress
    )

    safe_name = site.name.replace(" ", "_")
    filename = f"RDO_Semanal_{safe_name}_{week_start.strftime('%Y%m%d')}.xlsx"
    return Response(content=xlsx_bytes, media_type=_XLSX_MEDIA_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ─── Project-day view ────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/day")
async def project_day(
    project_id: int,
    date: str | None = Query(default=None),
    repo: CivilRepository = Depends(_repo),
):
    """Retorna todos os relatórios do projeto para uma data (visão de dia completo)."""
    from datetime import date as _date
    try:
        d = _date.fromisoformat(date) if date else _date.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de data inválido. Use YYYY-MM-DD")

    reports = await repo.list_reports_for_project_day(project_id, d)
    result = []
    for rpt in reports:
        site = await repo.get_site(rpt.site_id)
        result.append({
            "site_id": rpt.site_id,
            "site_name": site.name if site else f"Site {rpt.site_id}",
            "report_id": rpt.id,
            "report_number": rpt.report_number,
        })
    return result


# ─── Activity catalog for a site ─────────────────────────────────────────────

@router.get("/sites/{site_id}/activity-catalog")
async def site_activity_catalog(
    site_id: int,
    repo: CivilRepository = Depends(_repo),
):
    """Retorna o catálogo de atividades do perfil vinculado ao site."""
    site = await repo.get_site(site_id)
    if not site:
        raise HTTPException(status_code=404, detail="Site não encontrado")
    if not site.profile_id:
        return []
    return await repo.get_site_activity_catalog(site_id)


# ─── Config helpers ───────────────────────────────────────────────────────────

@router.get("/config/disciplines")
async def get_disciplines():
    return {"disciplines": CIVIL_DISCIPLINES}
