import asyncio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.logging import logger
from src.core.config import settings
from src.core.database import get_db, AsyncSessionLocal
from src.core.webhook_security import verify_clickup_signature
from src.services.sync_service import SyncService
from src.services.cache_service import CacheService
from src.services.event_broadcaster import broadcaster

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

HANDLED_EVENTS = {
    "taskCreated",
    "taskDeleted",
    "taskStatusUpdated",
    "taskUpdated",
    "taskAssigneeUpdated",
    "taskDueDateUpdated",
}


async def _update_cache_and_broadcast(event: str, task_id: str) -> None:
    """Atualiza o cache e publica no SSE broadcaster. Erros não propagam."""
    try:
        async with AsyncSessionLocal() as db:
            list_id = await CacheService(db).apply_webhook_event(event, task_id)
        if list_id:
            await broadcaster.publish({"type": event, "task_id": task_id, "list_id": list_id})
    except Exception as exc:
        logger.warning(f"Webhook cache update falhou para {event}/{task_id}: {exc}")


@router.post("/clickup")
async def receive_clickup_webhook(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    db: AsyncSession = Depends(get_db),
):
    body = await request.body()

    if not verify_clickup_signature(settings.clickup_webhook_secret, body, x_signature):
        logger.warning("ClickUp webhook: assinatura inválida")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    event = payload.get("event", "")
    task_id = payload.get("task_id")
    history_items = payload.get("history_items", [])

    logger.info(f"ClickUp webhook recebido: event={event}, task_id={task_id}")

    if event not in HANDLED_EVENTS:
        return {"status": "ignored", "event": event}

    if not task_id:
        return {"status": "ignored", "reason": "no task_id"}

    if settings.sync_enabled:
        # Sync para Airbox (fluxo original — não interrompido por erros de cache)
        result = await SyncService(db).handle_clickup_webhook(event, task_id, history_items)
        response = {"status": "ok" if result.success else "error", "detail": result.message}
    else:
        # SYNC_ENABLED=false: o Airbox não é usado, então só cache + SSE são atualizados.
        response = {"status": "ok", "detail": "sync desabilitado (SYNC_ENABLED=false)"}

    # Atualiza cache + SSE em background (fire-and-forget, não bloqueia resposta)
    asyncio.create_task(_update_cache_and_broadcast(event, task_id))

    return response
