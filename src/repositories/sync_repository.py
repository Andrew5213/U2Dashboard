from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.sync_map import TaskSyncMap, AgreementSyncMap, SyncLog


class SyncRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ─── TaskSyncMap ──────────────────────────────────────────────────────────

    async def get_task_map_by_airbox(self, airbox_task_id: int) -> TaskSyncMap | None:
        result = await self._db.execute(
            select(TaskSyncMap).where(TaskSyncMap.airbox_task_id == airbox_task_id)
        )
        return result.scalar_one_or_none()

    async def get_task_map_by_clickup(self, clickup_task_id: str) -> TaskSyncMap | None:
        result = await self._db.execute(
            select(TaskSyncMap).where(TaskSyncMap.clickup_task_id == clickup_task_id)
        )
        return result.scalar_one_or_none()

    async def create_task_map(
        self,
        airbox_task_id: int,
        clickup_task_id: str,
        airbox_agreement_id: int,
        clickup_list_id: str,
    ) -> TaskSyncMap:
        entry = TaskSyncMap(
            airbox_task_id=airbox_task_id,
            clickup_task_id=clickup_task_id,
            airbox_agreement_id=airbox_agreement_id,
            clickup_list_id=clickup_list_id,
        )
        self._db.add(entry)
        await self._db.commit()
        await self._db.refresh(entry)
        return entry

    # ─── AgreementSyncMap ────────────────────────────────────────────────────

    async def get_agreement_map(self, airbox_agreement_id: int) -> AgreementSyncMap | None:
        result = await self._db.execute(
            select(AgreementSyncMap).where(AgreementSyncMap.airbox_agreement_id == airbox_agreement_id)
        )
        return result.scalar_one_or_none()

    async def get_agreement_map_by_list(self, clickup_list_id: str) -> AgreementSyncMap | None:
        result = await self._db.execute(
            select(AgreementSyncMap).where(AgreementSyncMap.clickup_list_id == clickup_list_id)
        )
        return result.scalar_one_or_none()

    async def list_agreement_maps(self) -> list[AgreementSyncMap]:
        result = await self._db.execute(select(AgreementSyncMap))
        return list(result.scalars().all())

    async def create_agreement_map(
        self,
        airbox_agreement_id: int,
        airbox_agreement_name: str,
        airbox_agreement_type: str,
        clickup_list_id: str,
        clickup_space_id: str,
    ) -> AgreementSyncMap:
        entry = AgreementSyncMap(
            airbox_agreement_id=airbox_agreement_id,
            airbox_agreement_name=airbox_agreement_name,
            airbox_agreement_type=airbox_agreement_type,
            clickup_list_id=clickup_list_id,
            clickup_space_id=clickup_space_id,
        )
        self._db.add(entry)
        await self._db.commit()
        await self._db.refresh(entry)
        return entry

    # ─── SyncLog ─────────────────────────────────────────────────────────────

    async def log(
        self,
        direction: str,
        entity_type: str,
        entity_id: str,
        action: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        entry = SyncLog(
            direction=direction,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            status=status,
            error_message=error_message,
        )
        self._db.add(entry)
        await self._db.commit()
