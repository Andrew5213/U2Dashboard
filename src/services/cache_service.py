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
    folders_removed: int = 0
    lists_removed: int = 0
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
                # 1) Space — commitado imediatamente (leve e independente)
                spaces = await clickup.get_spaces(settings.clickup_team_id)
                space = next((s for s in spaces if str(s["id"]) == space_id), None)
                if space:
                    await self._repo.upsert_space(space)
                    summary.spaces_updated = 1
                    await self._db.commit()

                # 2) Membros — commitado separadamente para não bloquear o refresh principal
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

                # 3) Folders + listas + tasks. Primeiro LÊ tudo do ClickUp (leva minutos) e só
                # depois grava, numa transação curta e única: o dashboard continua a ver dados
                # completos ou o estado anterior, e o banco não fica travado durante a leitura.
                # Antes a transação abria no primeiro upsert e só fechava no fim — o motor do
                # cronograma, que grava no mesmo SQLite, falhava com "database is locked".
                folders = await self._fetch_folders(clickup, space_id, summary)

                for folder, lists in folders:
                    folder_id = str(folder["id"]) if folder else None
                    if folder:
                        await self._repo.upsert_folder(folder, space_id)
                        summary.folders_updated += 1
                    for lst, tasks in lists:
                        await self._repo.upsert_list(lst, space_id, folder_id)
                        summary.lists_updated += 1
                        if tasks is not None:
                            await self._store_tasks(str(lst["id"]), tasks, summary)

                # 4) Poda de listas e pastas apagadas no ClickUp (não retornadas mais pela API)
                seen_folder_ids = {str(folder["id"]) for folder, _ in folders if folder}
                seen_list_ids = {str(lst["id"]) for _, lists in folders for lst, _ in lists}
                summary.lists_removed = await self._repo.mark_lists_stale(space_id, seen_list_ids)
                summary.folders_removed = await self._repo.mark_folders_stale(space_id, seen_folder_ids)

                # Commit único e atômico — o dashboard só vê dados completos ou o estado anterior
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
            f"({summary.folders_removed} folders e {summary.lists_removed} listas removidas) "
            f"em {summary.duration_seconds:.1f}s — status={status}"
        )
        return summary

    async def _fetch_folders(
        self, clickup: ClickUpClient, space_id: str, summary: CacheRefreshSummary,
    ) -> list[tuple[dict | None, list[tuple[dict, list[dict] | None]]]]:
        """Pastas (None = listas sem pasta) com as suas listas e as tarefas de cada uma, lidas
        do ClickUp sem tocar no banco. Tarefas None = a leitura daquela lista falhou."""
        out: list[tuple[dict | None, list[tuple[dict, list[dict] | None]]]] = []
        for folder in await clickup.get_folders(space_id):
            lists = await clickup.get_lists_in_folder(str(folder["id"]))
            out.append((folder, [(lst, await self._fetch_tasks(clickup, str(lst["id"]), summary)) for lst in lists]))
        folderless = await clickup.get_folderless_lists(space_id)
        out.append((None, [(lst, await self._fetch_tasks(clickup, str(lst["id"]), summary)) for lst in folderless]))
        return out

    async def _fetch_tasks(
        self, clickup: ClickUpClient, list_id: str, summary: CacheRefreshSummary,
    ) -> list[dict] | None:
        try:
            return await clickup.get_tasks(list_id, include_closed=True)
        except Exception as exc:
            logger.error(f"Cache: erro ao carregar tasks da lista {list_id}: {exc}")
            summary.errors.append(f"list {list_id}: {exc}")
            # erros de lista são coletados e o refresh continua nas demais listas
            return None
        finally:
            await asyncio.sleep(0.6)

    async def _store_tasks(self, list_id: str, tasks: list[dict], summary: CacheRefreshSummary) -> None:
        seen: set[str] = set()
        for task in tasks:
            await self._repo.upsert_task(task, list_id)
            seen.add(str(task["id"]))
            summary.tasks_updated += 1
        await self._repo.mark_tasks_stale(list_id, seen)
        # Sem commit aqui — o refresh_cache_full commita tudo atomicamente ao final

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
            if event == "taskDeleted":
                # A task não existe mais no ClickUp — buscar de lá não é possível,
                # só resta remover a linha correspondente do cache local.
                list_id = await self._repo.get_task_list_id(task_id)
                await self._repo.delete_task(task_id)
                await self._db.commit()
                return list_id

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
