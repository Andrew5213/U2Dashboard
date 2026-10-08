"""Dispara o recálculo do cronograma: logo após um webhook (com espera, para juntar
edições em sequência) e periodicamente — o ClickUp não avisa quando uma dependência
é removida nem quando a lista de feriados muda."""
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.core.logging import logger
from src.services.clickup_client import ClickUpClient
from src.services.schedule_service import ScheduleRunSummary, ScheduleService

_scheduler: AsyncIOScheduler | None = None
_locks: dict[str, asyncio.Lock] = {}
_pending: dict[str, asyncio.Task] = {}


def is_schedule_list(list_id: str | None) -> bool:
    return bool(settings.schedule_enabled and list_id and list_id in settings.schedule_lists)


async def run_recalculation(list_id: str, dry_run: bool = False) -> ScheduleRunSummary:
    """Uma execução por lista de cada vez — duas em paralelo gravariam por cima uma da outra."""
    lock = _locks.setdefault(list_id, asyncio.Lock())
    async with lock:
        async with AsyncSessionLocal() as db, ClickUpClient() as clickup:
            return await ScheduleService(db, clickup).recalculate(list_id, dry_run=dry_run)


async def _debounced(list_id: str) -> None:
    try:
        await asyncio.sleep(settings.schedule_debounce_seconds)
        _pending.pop(list_id, None)
        await run_recalculation(list_id)
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Cronograma: recálculo por webhook falhou na lista {list_id}: {exc}")


def notify_list_changed(list_id: str | None) -> None:
    """Chamado pelo webhook. Reinicia a espera se já houver um recálculo agendado."""
    if not is_schedule_list(list_id):
        return
    pending = _pending.pop(list_id, None)
    if pending and not pending.done():
        pending.cancel()
    _pending[list_id] = asyncio.create_task(_debounced(list_id))


async def _run_all() -> None:
    for list_id in settings.schedule_lists:
        try:
            await run_recalculation(list_id)
        except Exception as exc:  # noqa: BLE001 — uma lista com erro não impede as outras
            logger.warning(f"Cronograma: recálculo periódico falhou na lista {list_id}: {exc}")


def start_schedule_worker() -> None:
    global _scheduler
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _run_all,
        trigger="interval",
        seconds=settings.schedule_interval_seconds,
        id="schedule_recalculation_job",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info(
        f"Cronograma: worker iniciado, {len(settings.schedule_lists)} lista(s), "
        f"a cada {settings.schedule_interval_seconds}s"
    )


def stop_schedule_worker() -> None:
    for pending in _pending.values():
        pending.cancel()
    _pending.clear()
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Cronograma: worker encerrado")
