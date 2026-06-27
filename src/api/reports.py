from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.database import get_db
from src.core.config import settings
from src.core.logging import logger
from src.services.report_service import ReportService, ProvinceReportService, PeriodicReportService
from src.services.report_strings import get_strings
from src.repositories.cache_repository import CacheRepository

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/pdf", summary="Exportar relatório executivo em PDF")
async def export_pdf_report(
    space_id: str = Query(default="", description="ClickUp Space ID (usa CLICKUP_DEFAULT_SPACE_ID se omitido)"),
    inline: bool = Query(default=False, description="Exibir inline no browser (para preview)"),
    lang: str = Query(default="pt", description="Idioma do relatório: 'pt' (português) ou 'en' (inglês)"),
    db: AsyncSession = Depends(get_db),
):
    sid = space_id or settings.clickup_default_space_id
    if not sid:
        raise HTTPException(
            status_code=400,
            detail="space_id é obrigatório ou configure CLICKUP_DEFAULT_SPACE_ID no .env",
        )

    lang = lang if lang in ("pt", "en") else "pt"
    logger.info(f"Gerando relatório PDF para space {sid} (lang={lang})")
    try:
        pdf_bytes = await ReportService(db).generate_pdf(sid, lang=lang)
    except Exception as exc:
        logger.error(f"Erro ao gerar PDF para space {sid}: {exc}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {exc}")

    datestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    filename = get_strings(lang)["filename_executive"].format(ts=datestamp)
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.get("/pdf/provincia", summary="Exportar relatório detalhado de uma província/área")
async def export_provincia_pdf(
    folder_id: str = Query(..., description="ID da pasta (província) no ClickUp"),
    inline: bool = Query(default=False, description="Exibir inline no browser (para preview)"),
    lang: str = Query(default="pt", description="Idioma do relatório: 'pt' (português) ou 'en' (inglês)"),
    db: AsyncSession = Depends(get_db),
):
    lang = lang if lang in ("pt", "en") else "pt"
    logger.info(f"Gerando relatório PDF de província para folder {folder_id} (lang={lang})")
    try:
        pdf_bytes = await ProvinceReportService(db).generate_pdf(folder_id, lang=lang)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error(f"Erro ao gerar PDF de província {folder_id}: {exc}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {exc}")

    datestamp = datetime.utcnow().strftime("%Y%m%d_%H%M")
    filename = get_strings(lang)["filename_province"].format(folder_id=folder_id, ts=datestamp)
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )


@router.get("/pdf/daily", summary="Exportar relatório diário de atualizações")
async def export_daily_pdf(
    space_id: str = Query(default="", description="ClickUp Space ID (usa CLICKUP_DEFAULT_SPACE_ID se omitido)"),
    inline: bool = Query(default=False, description="Exibir inline no browser"),
    lang: str = Query(default="pt", description="Idioma do relatório: 'pt' (português) ou 'en' (inglês)"),
    db: AsyncSession = Depends(get_db),
):
    sid = space_id or settings.clickup_default_space_id
    if not sid:
        raise HTTPException(status_code=400, detail="space_id é obrigatório ou configure CLICKUP_DEFAULT_SPACE_ID no .env")

    lang = lang if lang in ("pt", "en") else "pt"
    logger.info(f"Gerando relatório diário para space {sid} (lang={lang})")
    try:
        pdf_bytes = await PeriodicReportService(db).generate_daily_pdf(sid, lang=lang)
    except Exception as exc:
        logger.error(f"Erro ao gerar relatório diário: {exc}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {exc}")

    datestamp = datetime.utcnow().strftime("%Y%m%d")
    filename = get_strings(lang)["filename_daily"].format(ts=datestamp)
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": disposition})


@router.get("/pdf/weekly", summary="Exportar relatório semanal de atualizações")
async def export_weekly_pdf(
    space_id: str = Query(default="", description="ClickUp Space ID (usa CLICKUP_DEFAULT_SPACE_ID se omitido)"),
    inline: bool = Query(default=False, description="Exibir inline no browser"),
    lang: str = Query(default="pt", description="Idioma do relatório: 'pt' (português) ou 'en' (inglês)"),
    db: AsyncSession = Depends(get_db),
):
    sid = space_id or settings.clickup_default_space_id
    if not sid:
        raise HTTPException(status_code=400, detail="space_id é obrigatório ou configure CLICKUP_DEFAULT_SPACE_ID no .env")

    lang = lang if lang in ("pt", "en") else "pt"
    logger.info(f"Gerando relatório semanal para space {sid} (lang={lang})")
    try:
        pdf_bytes = await PeriodicReportService(db).generate_weekly_pdf(sid, lang=lang)
    except Exception as exc:
        logger.error(f"Erro ao gerar relatório semanal: {exc}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar relatório: {exc}")

    datestamp = datetime.utcnow().strftime("%Y%m%d")
    filename = get_strings(lang)["filename_weekly"].format(ts=datestamp)
    disposition = "inline" if inline else f'attachment; filename="{filename}"'
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": disposition})


@router.get("/folders", summary="Listar pastas disponíveis para relatório")
async def list_report_folders(
    space_id: str = Query(default="", description="ClickUp Space ID (usa CLICKUP_DEFAULT_SPACE_ID se omitido)"),
    db: AsyncSession = Depends(get_db),
):
    sid = space_id or settings.clickup_default_space_id
    if not sid:
        raise HTTPException(status_code=400, detail="space_id é obrigatório")
    folders = await CacheRepository(db).get_all_folders(sid)
    return JSONResponse([{"folder_id": f.folder_id, "name": f.name} for f in folders])
