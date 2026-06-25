import httpx
from typing import Any
from src.core.logging import logger
from src.core.config import settings
from src.models.schemas import AirboxTask, AirboxAgreement, AirboxUser


class AirboxClient:
    """
    Cliente para a API do AltoQI Visus Workflow (Airbox).
    URL base: https://workflow-api.altoqivisus.com.br
    Auth: API Key no header 'apikey'.

    Atenção: a resposta de listagens vem em envelope {"value": [...], "Count": N}.
    Datas retornadas são ISO 8601 strings.
    """

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.airbox_base_url,
            headers={"apikey": settings.airbox_api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get_raw(self, path: str, params: dict | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _get_list(self, path: str, params: dict | None = None) -> list[Any]:
        """Faz GET e extrai a lista do envelope {"value": [...], "Count": N}."""
        data = await self._get_raw(path, params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "value" in data:
            return data["value"]
        return []

    async def _get_one(self, path: str, params: dict | None = None) -> dict[str, Any]:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, data: dict) -> dict:
        response = await self._client.post(path, json=data)
        response.raise_for_status()
        return response.json()

    async def _patch(self, path: str, data: dict) -> dict:
        response = await self._client.patch(path, json=data)
        response.raise_for_status()
        return response.json()

    # ─── Agreements ──────────────────────────────────────────────────────────

    async def list_agreements(self, type: str | None = None) -> list[AirboxAgreement]:
        params = {"type": type} if type else None
        items = await self._get_list("/agreements", params)
        logger.info(f"Airbox: {len(items)} agreements encontrados")
        return [self._parse_agreement(a) for a in items]

    async def get_agreement(self, agreement_id: int) -> AirboxAgreement:
        data = await self._get_one(f"/agreements/{agreement_id}")
        return self._parse_agreement(data)

    # ─── Tasks ───────────────────────────────────────────────────────────────

    async def list_tasks(
        self,
        entity_type: str | None = None,
        entity_id: int | None = None,
        include_archived: bool = False,
    ) -> list[AirboxTask]:
        params: dict = {}
        if entity_type:
            params["entity_type"] = entity_type
        if entity_id is not None:
            params["entity_id"] = entity_id
        if not include_archived:
            params["is_archived"] = "false"
        items = await self._get_list("/tasks", params or None)
        return [self._parse_task(t) for t in items]

    async def get_task(self, task_id: int) -> AirboxTask:
        data = await self._get_one(f"/tasks/{task_id}")
        return self._parse_task(data)

    async def create_task(self, payload: dict) -> AirboxTask:
        data = await self._post("/tasks", payload)
        logger.info(f"Airbox task criada: id={data.get('id')}, code={data.get('code')}")
        return self._parse_task(data)

    async def update_task(self, task_id: int, payload: dict) -> AirboxTask:
        """Atualiza task via PATCH (requer permissão adequada na API Key)."""
        data = await self._patch(f"/tasks/{task_id}", payload)
        logger.info(f"Airbox task atualizada: id={task_id}")
        return self._parse_task(data)

    # ─── Users ───────────────────────────────────────────────────────────────

    async def list_users(self) -> list[AirboxUser]:
        items = await self._get_list("/users")
        return [self._parse_user(u) for u in items]

    # ─── Parsers ─────────────────────────────────────────────────────────────

    def _parse_agreement(self, raw: dict) -> AirboxAgreement:
        return AirboxAgreement(
            id=raw["id"],
            name=raw.get("name"),
            additional_info=raw.get("additional_info"),
            type=raw.get("type"),
            contract_id=raw.get("contract_id"),
            state=raw.get("state"),
            default_responsible_id=raw.get("default_responsible_id"),
            starting=raw.get("starting"),
            revenue_value=raw.get("revenue_value"),
        )

    def _parse_task(self, raw: dict) -> AirboxTask:
        return AirboxTask(
            id=raw.get("id"),
            name=raw.get("name"),
            company_id=raw.get("company_id"),
            entity_type=raw.get("entity_type"),
            entity_id=raw.get("entity_id"),
            task_stage_id=raw.get("task_stage_id"),
            position=raw.get("position"),
            customer_id=raw.get("customer_id"),
            responsible_id=raw.get("responsible_id"),
            information=raw.get("information"),
            started=raw.get("started"),
            start_prediction=raw.get("start_prediction"),
            finish_prediction=raw.get("finish_prediction"),
            finished=raw.get("finished"),
            due_date=raw.get("due_date"),
            estimated_hours=raw.get("estimated_hours", 0),
            code=raw.get("code"),
            is_archived=raw.get("is_archived", False),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
        )

    def _parse_user(self, raw: dict) -> AirboxUser:
        return AirboxUser(
            id=raw["id"],
            name=raw.get("name"),
            email=raw.get("email"),
            avatar=raw.get("avatar"),
        )
