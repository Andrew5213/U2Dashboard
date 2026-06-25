from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.services.sync_service import SyncService


_scheduler: AsyncIOScheduler | None = None
_space_id: str = ""


async def _run_sync() -> None:
    if not _space_id:
        logger.warning("Polling worker: space_id não configurado, sync ignorado")
        return

    logger.info("Polling worker: iniciando sync ClickUp → Airbox")
    async with AsyncSessionLocal() as db:
        service = SyncService(db)
        results = await service.sync_clickup_to_airbox(_space_id)

    total = len(results)
    created = sum(1 for r in results if r.action == "created")
    errors = sum(1 for r in results if not r.success)
    logger.info(f"Polling worker: concluído — {total} tasks, {created} criadas, {errors} erros")


def start_polling(space_id: str) -> None:
    global _scheduler, _space_id
    _space_id = space_id

    if not settings.sync_enabled:
        logger.info("Polling worker: desabilitado via SYNC_ENABLED=false")
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_sync,
        trigger="interval",
        seconds=settings.polling_interval_seconds,
        id="clickup_to_airbox_sync",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(f"Polling worker iniciado: a cada {settings.polling_interval_seconds}s (space={space_id})")


def stop_polling() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Polling worker encerrado")
