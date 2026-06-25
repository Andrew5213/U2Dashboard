from fastapi import APIRouter, Depends, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from src.core.database import get_db
from src.models.sync_map import TaskSyncMap, AgreementSyncMap, SyncLog
from src.services.sync_service import SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


@router.post("/trigger")
async def trigger_sync(
    space_id: str = Query(..., description="ClickUp Space ID de onde ler as tasks"),
    db: AsyncSession = Depends(get_db),
):
    """Dispara manualmente um sync completo ClickUp → Airbox.

    Para cada lista do space: tenta encontrar um agreement de mesmo nome no Airbox
    e cria as tasks ainda não sincronizadas.
    """
    service = SyncService(db)
    results = await service.sync_clickup_to_airbox(space_id)
    total = len(results)
    errors = sum(1 for r in results if not r.success)
    created = sum(1 for r in results if r.action == "created")
    skipped = sum(1 for r in results if r.action == "skipped")
    return {
        "total": total,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "results": [r.model_dump() for r in results],
    }


@router.get("/status")
async def sync_status(db: AsyncSession = Depends(get_db)):
    """Retorna estatísticas atuais do sync."""
    agreements_count = await db.scalar(select(func.count()).select_from(AgreementSyncMap))
    tasks_count = await db.scalar(select(func.count()).select_from(TaskSyncMap))
    errors_count = await db.scalar(
        select(func.count()).select_from(SyncLog).where(SyncLog.status == "error")
    )
    last_log = await db.scalar(
        select(SyncLog.created_at).order_by(SyncLog.created_at.desc()).limit(1)
    )
    return {
        "total_agreements_mapped": agreements_count,
        "total_tasks_synced": tasks_count,
        "total_errors": errors_count,
        "last_sync_event": last_log,
    }


@router.get("/logs")
async def sync_logs(
    limit: int = Query(50, le=200),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Retorna logs recentes de sync."""
    query = select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit)
    if status:
        query = query.where(SyncLog.status == status)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "direction": log.direction,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "action": log.action,
            "status": log.status,
            "error": log.error_message,
            "created_at": log.created_at,
        }
        for log in logs
    ]


@router.get("/mappings/agreements")
async def list_agreement_mappings(db: AsyncSession = Depends(get_db)):
    """Lista os mapeamentos ativos entre listas do ClickUp e agreements do Airbox."""
    result = await db.execute(select(AgreementSyncMap).order_by(AgreementSyncMap.created_at.desc()))
    maps = result.scalars().all()
    return [
        {
            "clickup_list_id": m.clickup_list_id,
            "airbox_agreement_id": m.airbox_agreement_id,
            "airbox_agreement_name": m.airbox_agreement_name,
            "airbox_agreement_type": m.airbox_agreement_type,
            "last_synced_at": m.last_synced_at,
        }
        for m in maps
    ]


@router.post("/mappings/agreements")
async def create_agreement_mapping(
    clickup_list_id: str = Body(..., description="ID da lista no ClickUp"),
    clickup_list_name: str = Body(..., description="Nome da lista (para referência)"),
    airbox_agreement_id: int = Body(..., description="ID do agreement no Airbox"),
    clickup_space_id: str = Body("", description="Space ID (opcional, para referência)"),
    db: AsyncSession = Depends(get_db),
):
    """Cria manualmente um mapeamento entre lista do ClickUp e agreement do Airbox.

    Use quando os nomes não batem automaticamente.
    """
    service = SyncService(db)
    await service.map_list_to_agreement(
        clickup_list_id=clickup_list_id,
        clickup_list_name=clickup_list_name,
        airbox_agreement_id=airbox_agreement_id,
        clickup_space_id=clickup_space_id,
    )
    return {"status": "ok", "message": f"Lista {clickup_list_id} mapeada ao agreement {airbox_agreement_id}"}
