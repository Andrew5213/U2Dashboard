from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.services.cache_service import CacheService


_cache_scheduler: AsyncIOScheduler | None = None
_space_id: str = ""


async def _run_cache_refresh() -> None:
    if not _space_id:
        return
    logger.info("Cache worker: iniciando refresh do cache ClickUp")
    async with AsyncSessionLocal() as db:
        summary = await CacheService(db).refresh_cache_full(_space_id, trigger="scheduler")
    logger.info(
        f"Cache worker: concluído — {summary.tasks_updated} tasks, "
        f"{len(summary.errors)} erro(s), {summary.duration_seconds:.1f}s"
    )


def start_cache_worker(space_id: str) -> None:
    global _cache_scheduler, _space_id
    _space_id = space_id

    _cache_scheduler = AsyncIOScheduler()
    _cache_scheduler.add_job(
        _run_cache_refresh,
        trigger="interval",
        seconds=settings.cache_refresh_interval_seconds,
        id="cache_refresh_job",
        replace_existing=True,
        next_run_time=datetime.now() if settings.cache_refresh_on_startup else None,
    )
    _cache_scheduler.start()
    logger.info(
        f"Cache worker iniciado: a cada {settings.cache_refresh_interval_seconds}s "
        f"(space={space_id}, startup_refresh={settings.cache_refresh_on_startup})"
    )


def stop_cache_worker() -> None:
    if _cache_scheduler and _cache_scheduler.running:
        _cache_scheduler.shutdown()
        logger.info("Cache worker encerrado")
