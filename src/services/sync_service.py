from sqlalchemy.exc import IntegrityError
from src.core.logging import logger
from src.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.clickup_client import ClickUpClient
from src.services.airbox_client import AirboxClient
from src.services.mapper import clickup_task_to_airbox
from src.repositories.sync_repository import SyncRepository
from src.models.schemas import AirboxAgreement, SyncResult


class SyncService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._repo = SyncRepository(db)

    # ─── ClickUp → Airbox (direção principal) ────────────────────────────────

    async def sync_clickup_to_airbox(self, space_id: str) -> list[SyncResult]:
        """Lê todas as listas e tasks do ClickUp e cria no Airbox."""
        results: list[SyncResult] = []

        async with ClickUpClient() as clickup, AirboxClient() as airbox:
            # Carregar agreements do Airbox para matching por nome
            agreements = await airbox.list_agreements()
            agreement_by_name = {
                (a.name or "").strip().lower(): a
                for a in agreements
            }

            # Buscar todas as listas do space (diretas + dentro de folders)
            all_lists = await self._get_all_lists(space_id, clickup)
            logger.info(f"ClickUp: {len(all_lists)} listas encontradas no space {space_id}")

            for cu_list in all_lists:
                list_id = cu_list["id"]
                list_name = cu_list.get("name", "")

                # Encontrar agreement correspondente no Airbox
                agreement = await self._resolve_agreement(
                    list_id, list_name, agreement_by_name
                )
                if not agreement:
                    logger.warning(
                        f"Lista '{list_name}' (id={list_id}) sem agreement correspondente no Airbox — ignorando"
                    )
                    results.append(SyncResult(
                        success=False,
                        entity_type="list",
                        entity_id=list_id,
                        action="skipped",
                        message=f"Nenhum agreement com nome '{list_name}' no Airbox",
                    ))
                    continue

                # Sincronizar tasks desta lista
                tasks = await clickup.get_tasks(list_id)
                logger.info(f"Lista '{list_name}': {len(tasks)} tasks")

                for task in tasks:
                    result = await self._sync_task_to_airbox(task, agreement, airbox)
                    results.append(result)

        return results

    async def _get_all_lists(self, space_id: str, clickup: ClickUpClient) -> list[dict]:
        """Retorna todas as listas do space: diretas + dentro de folders."""
        all_lists: list[dict] = []

        # Listas diretas (sem folder)
        direct = await clickup.get_folderless_lists(space_id)
        all_lists.extend(direct)

        # Listas dentro de folders
        folders = await clickup.get_folders(space_id)
        for folder in folders:
            folder_lists = await clickup.get_lists_in_folder(folder["id"])
            all_lists.extend(folder_lists)

        return all_lists

    async def _resolve_agreement(
        self,
        list_id: str,
        list_name: str,
        agreement_by_name: dict[str, AirboxAgreement],
    ) -> AirboxAgreement | None:
        """Retorna o agreement do Airbox mapeado a esta lista do ClickUp.
        Primeiro consulta o banco; depois tenta match por nome."""
        # Checar mapeamento já salvo
        existing = await self._repo.get_agreement_map_by_list(list_id)
        if existing:
            return AirboxAgreement(
                id=existing.airbox_agreement_id,
                name=existing.airbox_agreement_name,
                type=existing.airbox_agreement_type,
            )

        # Tentar match por nome
        agreement = agreement_by_name.get(list_name.strip().lower())
        if agreement:
            await self._repo.create_agreement_map(
                airbox_agreement_id=agreement.id,
                airbox_agreement_name=agreement.name or list_name,
                airbox_agreement_type=agreement.type or settings.airbox_default_entity_type,
                clickup_list_id=list_id,
                clickup_space_id="",
            )
            logger.info(f"Lista '{list_name}' mapeada ao agreement '{agreement.name}' (id={agreement.id})")

        return agreement

    async def _sync_task_to_airbox(
        self,
        cu_task: dict,
        agreement: AirboxAgreement,
        airbox: AirboxClient,
    ) -> SyncResult:
        task_id = cu_task["id"]
        task_name = cu_task.get("name", "")
        try:
            # Checar se já foi sincronizada
            existing = await self._repo.get_task_map_by_clickup(task_id)
            if existing:
                return SyncResult(
                    success=True,
                    entity_type="task",
                    entity_id=task_id,
                    action="skipped",
                    message="Já sincronizada",
                )

            payload = clickup_task_to_airbox(cu_task, agreement.id)
            airbox_task = await airbox.create_task(payload)

            try:
                await self._repo.create_task_map(
                    airbox_task_id=airbox_task.id,
                    clickup_task_id=task_id,
                    airbox_agreement_id=agreement.id,
                    clickup_list_id=cu_task.get("list", {}).get("id", ""),
                )
            except IntegrityError:
                # Task já mapeada por outra lista (tasks in multiple lists no ClickUp)
                await self._db.rollback()
                return SyncResult(success=True, entity_type="task", entity_id=task_id, action="skipped", message="Já sincronizada (outra lista)")

            await self._repo.log("to_airbox", "task", task_id, "created", "success")
            logger.info(f"Task '{task_name}' criada no Airbox (id={airbox_task.id})")
            return SyncResult(success=True, entity_type="task", entity_id=task_id, action="created", message="OK")

        except Exception as exc:
            msg = str(exc)
            logger.error(f"Erro ao sincronizar task '{task_name}' (id={task_id}) para Airbox: {msg}")
            try:
                await self._db.rollback()
                await self._repo.log("to_airbox", "task", task_id, "created", "error", msg[:500])
            except Exception:
                pass
            return SyncResult(success=False, entity_type="task", entity_id=task_id, action="created", message="Erro", error=msg)

    # ─── Webhook do ClickUp → Airbox ─────────────────────────────────────────

    async def handle_clickup_webhook(
        self, event: str, task_id: str, history_items: list[dict]
    ) -> SyncResult:
        """Processa evento do ClickUp e propaga ao Airbox."""
        try:
            async with ClickUpClient() as clickup, AirboxClient() as airbox:
                if event == "taskCreated":
                    return await self._handle_task_created(task_id, clickup, airbox)
                else:
                    return await self._handle_task_updated(event, task_id, history_items)
        except Exception as exc:
            msg = str(exc)
            logger.error(f"Erro no webhook '{event}' (task {task_id}): {msg}")
            await self._repo.log("to_airbox", "task", task_id, event, "error", msg[:500])
            return SyncResult(success=False, entity_type="task", entity_id=task_id, action=event, message="Erro", error=msg)

    async def _handle_task_created(
        self, task_id: str, clickup: ClickUpClient, airbox: AirboxClient
    ) -> SyncResult:
        # Checar se já existe mapeamento
        if await self._repo.get_task_map_by_clickup(task_id):
            return SyncResult(success=True, entity_type="task", entity_id=task_id, action="skipped", message="Já sincronizada")

        # Buscar task completa no ClickUp
        cu_task = await clickup.get_task(task_id)
        list_id = cu_task.get("list", {}).get("id", "")
        list_name = cu_task.get("list", {}).get("name", "")

        # Resolver agreement
        agreements = await airbox.list_agreements()
        agreement_by_name = {(a.name or "").strip().lower(): a for a in agreements}
        agreement = await self._resolve_agreement(list_id, list_name, agreement_by_name)

        if not agreement:
            msg = f"Lista '{list_name}' sem agreement correspondente no Airbox"
            await self._repo.log("to_airbox", "task", task_id, "taskCreated", "error", msg)
            return SyncResult(success=False, entity_type="task", entity_id=task_id, action="taskCreated", message=msg)

        payload = clickup_task_to_airbox(cu_task, agreement.id)
        airbox_task = await airbox.create_task(payload)

        await self._repo.create_task_map(
            airbox_task_id=airbox_task.id,
            clickup_task_id=task_id,
            airbox_agreement_id=agreement.id,
            clickup_list_id=list_id,
        )
        await self._repo.log("to_airbox", "task", task_id, "taskCreated", "success")
        logger.info(f"Webhook taskCreated: task {task_id} criada no Airbox (id={airbox_task.id})")
        return SyncResult(success=True, entity_type="task", entity_id=task_id, action="taskCreated", message="Criada no Airbox")

    async def _handle_task_updated(
        self, event: str, task_id: str, history_items: list[dict]
    ) -> SyncResult:
        """Atualizações de task no ClickUp — registradas no log até Airbox liberar PATCH /tasks."""
        mapping = await self._repo.get_task_map_by_clickup(task_id)
        if not mapping:
            return SyncResult(success=False, entity_type="task", entity_id=task_id, action=event,
                              message="Task não mapeada — sem correspondente no Airbox")

        await self._repo.log("to_airbox", "task", task_id, event, "skipped",
                             "Airbox public API não suporta PATCH /tasks")
        return SyncResult(success=True, entity_type="task", entity_id=task_id, action=event,
                          message="Evento registrado. Atualização no Airbox pendente de suporte da API.")

    # ─── Mapeamento manual de Lista → Agreement ───────────────────────────────

    async def map_list_to_agreement(
        self,
        clickup_list_id: str,
        clickup_list_name: str,
        airbox_agreement_id: int,
        clickup_space_id: str = "",
    ) -> bool:
        """Cria manualmente um mapeamento entre lista do ClickUp e agreement do Airbox."""
        async with AirboxClient() as airbox:
            agreement = await airbox.get_agreement(airbox_agreement_id)

        await self._repo.create_agreement_map(
            airbox_agreement_id=agreement.id,
            airbox_agreement_name=agreement.name or clickup_list_name,
            airbox_agreement_type=agreement.type or settings.airbox_default_entity_type,
            clickup_list_id=clickup_list_id,
            clickup_space_id=clickup_space_id,
        )
        logger.info(f"Mapeamento manual: lista {clickup_list_id} → agreement {airbox_agreement_id}")
        return True
