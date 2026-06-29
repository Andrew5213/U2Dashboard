from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.database import AsyncSessionLocal, get_db
from src.core.logging import logger
from src.models.dashboard_schemas import DashboardEnvelope
from src.services.cache_service import CacheService
from src.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_NO_CACHE = {"Cache-Control": "no-store"}


def _svc(db: AsyncSession = Depends(get_db)) -> DashboardService:
    return DashboardService(db)


@router.get("/overview", response_model=DashboardEnvelope)
async def get_overview(svc: DashboardService = Depends(_svc)):
    data = await svc.get_overview(settings.clickup_default_space_id)
    return JSONResponse(DashboardEnvelope(data=data.model_dump()).model_dump(), headers=_NO_CACHE)


@router.get("/folders", response_model=DashboardEnvelope)
async def get_folders(svc: DashboardService = Depends(_svc)):
    data = await svc.get_folders(settings.clickup_default_space_id)
    return JSONResponse(DashboardEnvelope(data=[f.model_dump() for f in data]).model_dump(), headers=_NO_CACHE)


@router.get("/folder/{folder_id}", response_model=DashboardEnvelope)
async def get_folder(folder_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_folder_lists(folder_id)
    return JSONResponse(DashboardEnvelope(data=[lst.model_dump() for lst in data]).model_dump(), headers=_NO_CACHE)


@router.get("/list/{list_id}", response_model=DashboardEnvelope)
async def get_list(list_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_list_tasks(list_id)
    return JSONResponse(DashboardEnvelope(data=[t.model_dump() for t in data]).model_dump(), headers=_NO_CACHE)


@router.get("/task/{task_id}", response_model=DashboardEnvelope)
async def get_task(task_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_task_detail(task_id)
    if not data:
        raise HTTPException(status_code=404, detail="Task não encontrada no cache")
    return JSONResponse(DashboardEnvelope(data=data.model_dump()).model_dump(), headers=_NO_CACHE)


@router.get("/assignees", response_model=DashboardEnvelope)
async def get_assignees(svc: DashboardService = Depends(_svc)):
    data = await svc.get_assignee_stats(settings.clickup_default_space_id)
    return JSONResponse(DashboardEnvelope(data=[d.model_dump() for d in data]).model_dump(), headers=_NO_CACHE)


@router.get("/upcoming", response_model=DashboardEnvelope)
async def get_upcoming(days: int = 30, svc: DashboardService = Depends(_svc)):
    data = await svc.get_upcoming_tasks(settings.clickup_default_space_id, days)
    return JSONResponse(DashboardEnvelope(data=[d.model_dump() for d in data]).model_dump(), headers=_NO_CACHE)


@router.get("/gantt/overview", response_model=DashboardEnvelope)
async def get_gantt_overview(svc: DashboardService = Depends(_svc)):
    data = await svc.get_gantt_overview(settings.clickup_default_space_id)
    return DashboardEnvelope(data=data)


@router.get("/gantt/folder/{folder_id}", response_model=DashboardEnvelope)
async def get_gantt_folder(folder_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_gantt_tasks_by_folder(folder_id)
    return DashboardEnvelope(data=[t.model_dump() for t in data])


@router.get("/gantt/task/{task_id}", response_model=DashboardEnvelope)
async def get_gantt_task(task_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_gantt_task_with_subtasks(task_id)
    return DashboardEnvelope(data=[t.model_dump() for t in data])


@router.get("/gantt/{list_id}", response_model=DashboardEnvelope)
async def get_gantt(list_id: str, svc: DashboardService = Depends(_svc)):
    data = await svc.get_gantt_tasks(list_id)
    return DashboardEnvelope(data=[t.model_dump() for t in data])


@router.get("/evolution", response_model=DashboardEnvelope)
async def get_evolution(svc: DashboardService = Depends(_svc)):
    data = await svc.get_evolution_data(settings.clickup_default_space_id)
    return DashboardEnvelope(data=data)


@router.post("/refresh", response_model=DashboardEnvelope)
async def trigger_refresh(background_tasks: BackgroundTasks):
    if not settings.clickup_default_space_id:
        raise HTTPException(status_code=400, detail="CLICKUP_DEFAULT_SPACE_ID não configurado")

    async def _do() -> None:
        async with AsyncSessionLocal() as db:
            await CacheService(db).refresh_cache_full(
                settings.clickup_default_space_id, trigger="manual"
            )

    background_tasks.add_task(_do)
    logger.info("Dashboard: refresh manual disparado em background")
    return DashboardEnvelope(data={"message": "Refresh iniciado em background"})
