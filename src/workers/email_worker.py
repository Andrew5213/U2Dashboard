from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.services.email_service import EmailService


_email_scheduler: AsyncIOScheduler | None = None
_space_id: str = ""

_WEEKDAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


async def _run_email_report() -> None:
    if not _space_id:
        return
    logger.info("Email worker: iniciando envio do relatório semanal")
    try:
        async with AsyncSessionLocal() as db:
            await EmailService(db).send_weekly_report(_space_id)
    except Exception as exc:
        logger.error(f"Email worker: falha no envio — {exc}")


def start_email_worker(space_id: str) -> None:
    global _email_scheduler, _space_id
    _space_id = space_id

    weekday = settings.email_report_weekday
    hour = settings.email_report_hour

    _email_scheduler = AsyncIOScheduler()
    _email_scheduler.add_job(
        _run_email_report,
        trigger="cron",
        day_of_week=weekday,
        hour=hour,
        minute=0,
        id="weekly_email_job",
        replace_existing=True,
    )
    _email_scheduler.start()

    day_name = _WEEKDAY_NAMES[weekday] if 0 <= weekday <= 6 else str(weekday)
    logger.info(
        f"Email worker iniciado: toda {day_name} às {hour:02d}:00 UTC "
        f"→ {settings.email_recipients} (space={space_id})"
    )


def stop_email_worker() -> None:
    if _email_scheduler and _email_scheduler.running:
        _email_scheduler.shutdown()
        logger.info("Email worker encerrado")
