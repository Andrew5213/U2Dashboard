import asyncio
import time
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from src.core.config import settings
from src.core.logging import logger
from src.repositories.cache_repository import CacheRepository
from src.services.clickup_client import ClickUpClient


@dataclass
class CacheRefreshSummary:
    spaces_updated: int = 0
    folders_updated: int = 0
    lists_updated: int = 0
    tasks_updated: int = 0
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)


class CacheService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = CacheRepository(db)

    async def refresh_cache_full(self, space_id: str, trigger: str = "scheduler") -> CacheRefreshSummary:
        summary = CacheRefreshSummary()
        start = time.monotonic()

        try:
            async with ClickUpClient() as clickup:
                # 1) Space
                spaces = await clickup.get_spaces(settings.clickup_team_id)
                space = next((s for s in spaces if str(s["id"]) == space_id), None)
                if space:
                    await self._repo.upsert_space(space)
                    summary.spaces_updated = 1
                    await self._db.commit()

                # 2) Membros
                try:
                    members = await clickup.get_team_members()
                    for m in members:
                        user = m.get("user", m)
                        if user.get("id"):
                            await self._repo.upsert_user(user)
                    await self._db.commit()
                except Exception as exc:
                    logger.warning(f"Cache: erro ao carregar membros: {exc}")
                    summary.errors.append(f"members: {exc}")
                    await self._db.rollback()

                # 3) Folders + listas + tasks
                folders = await clickup.get_folders(space_id)
                for folder in folders:
                    folder_id = str(folder["id"])
                    await self._repo.upsert_folder(folder, space_id)
                    summary.folders_updated += 1

                    lists = await clickup.get_lists_in_folder(folder_id)
                    for lst in lists:
                        list_id = str(lst["id"])
                        await self._repo.upsert_list(lst, space_id, folder_id)
                        summary.lists_updated += 1
                        await self._db.commit()

                        await self._load_tasks(clickup, list_id, summary)
                        await asyncio.sleep(0.6)

                await self._db.commit()

                # 4) Listas sem folder
                folderless = await clickup.get_folderless_lists(space_id)
                for lst in folderless:
                    list_id = str(lst["id"])
                    await self._repo.upsert_list(lst, space_id, None)
                    summary.lists_updated += 1
                    await self._db.commit()

                    await self._load_tasks(clickup, list_id, summary)
                    await asyncio.sleep(0.6)

                await self._db.commit()

        except Exception as exc:
            logger.error(f"Cache refresh falhou: {exc}")
            summary.errors.append(str(exc))
            try:
                await self._db.rollback()
            except Exception:
                pass

        summary.duration_seconds = time.monotonic() - start
        status = "success" if not summary.errors else ("partial" if summary.tasks_updated > 0 else "error")

        try:
            await self._repo.insert_refresh_log(
                space_id=space_id,
                trigger=trigger,
                status=status,
                folders_updated=summary.folders_updated,
                lists_updated=summary.lists_updated,
                tasks_updated=summary.tasks_updated,
                duration_ms=int(summary.duration_seconds * 1000),
                error_message="; ".join(summary.errors[:3]) if summary.errors else None,
            )
        except Exception as exc:
            logger.warning(f"Cache: falhou ao gravar log de refresh: {exc}")

        logger.info(
            f"Cache refresh [{trigger}]: {summary.folders_updated} folders, "
            f"{summary.lists_updated} listas, {summary.tasks_updated} tasks "
            f"em {summary.duration_seconds:.1f}s — status={status}"
        )
        return summary

    async def _load_tasks(self, clickup: ClickUpClient, list_id: str, summary: CacheRefreshSummary) -> None:
        try:
            tasks = await clickup.get_tasks(list_id, include_closed=True)
            seen: set[str] = set()
            for task in tasks:
                await self._repo.upsert_task(task, list_id)
                seen.add(str(task["id"]))
                summary.tasks_updated += 1
            await self._repo.mark_tasks_stale(list_id, seen)
            await self._db.commit()
        except Exception as exc:
            logger.error(f"Cache: erro ao carregar tasks da lista {list_id}: {exc}")
            summary.errors.append(f"list {list_id}: {exc}")
            await self._db.rollback()

    async def refresh_list(self, list_id: str) -> int:
        count = 0
        try:
            async with ClickUpClient() as clickup:
                tasks = await clickup.get_tasks(list_id, include_closed=True)
                seen: set[str] = set()
                for task in tasks:
                    await self._repo.upsert_task(task, list_id)
                    seen.add(str(task["id"]))
                    count += 1
                await self._repo.mark_tasks_stale(list_id, seen)
                await self._db.commit()
        except Exception as exc:
            logger.error(f"Cache: erro no refresh da lista {list_id}: {exc}")
            await self._db.rollback()
        return count

    async def apply_webhook_event(self, event: str, task_id: str) -> str | None:
        try:
            async with ClickUpClient() as clickup:
                task = await clickup.get_task(task_id)
            list_obj = task.get("list") or {}
            list_id = str(list_obj.get("id", ""))
            await self._repo.upsert_task(task, list_id)
            await self._db.commit()
            return list_id or None
        except Exception as exc:
            logger.warning(f"Cache: falhou ao aplicar webhook '{event}' para task {task_id}: {exc}")
            try:
                await self._db.rollback()
            except Exception:
                pass
            return None
