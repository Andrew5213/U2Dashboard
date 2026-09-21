import httpx
from src.core.logging import logger
from src.core.config import settings
from src.models.schemas import ClickUpTask


BASE_URL = "https://api.clickup.com/api/v2"


class ClickUpClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": settings.clickup_api_token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def _post(self, path: str, data: dict) -> dict:
        response = await self._client.post(path, json=data)
        response.raise_for_status()
        return response.json()

    async def _put(self, path: str, data: dict) -> dict:
        response = await self._client.put(path, json=data)
        response.raise_for_status()
        return response.json()

    async def _delete(self, path: str) -> None:
        response = await self._client.delete(path)
        response.raise_for_status()

    # ─── Leitura ─────────────────────────────────────────────────────────────

    async def get_spaces(self, team_id: str) -> list[dict]:
        data = await self._get(f"/team/{team_id}/space", {"archived": "false"})
        return data.get("spaces", [])

    async def get_lists_in_space(self, space_id: str) -> list[dict]:
        data = await self._get(f"/space/{space_id}/list")
        return data.get("lists", [])

    async def get_folderless_lists(self, space_id: str) -> list[dict]:
        data = await self._get(f"/space/{space_id}/list")
        return data.get("lists", [])

    async def get_folders(self, space_id: str) -> list[dict]:
        data = await self._get(f"/space/{space_id}/folder", {"archived": "false"})
        return data.get("folders", [])

    async def get_lists_in_folder(self, folder_id: str) -> list[dict]:
        data = await self._get(f"/folder/{folder_id}/list", {"archived": "false"})
        return data.get("lists", [])

    async def get_tasks(self, list_id: str, include_closed: bool = True) -> list[dict]:
        all_tasks: list[dict] = []
        page = 0
        while True:
            data = await self._get(f"/list/{list_id}/task", {
                "include_closed": str(include_closed).lower(),
                "subtasks": "true",
                "include_group_assignees": "true",
                "page": str(page),
            })
            tasks = data.get("tasks", [])
            if not tasks:
                break
            all_tasks.extend(tasks)
            page += 1
        return all_tasks

    async def get_task(self, task_id: str) -> dict:
        return await self._get(f"/task/{task_id}", {"include_group_assignees": "true"})

    async def get_team_members(self) -> list[dict]:
        data = await self._get(f"/team/{settings.clickup_team_id}/member")
        return data.get("members", [])

    async def find_member_by_email(self, email: str) -> dict | None:
        members = await self.get_team_members()
        for m in members:
            user = m.get("user", {})
            if user.get("email", "").lower() == email.lower():
                return user
        return None

    # ─── Escrita ─────────────────────────────────────────────────────────────

    async def create_list(self, space_id: str, name: str) -> dict:
        data = await self._post(f"/space/{space_id}/list", {"name": name})
        logger.info(f"ClickUp list created: {name} (id={data['id']})")
        return data

    async def create_list_in_folder(self, folder_id: str, name: str) -> dict:
        data = await self._post(f"/folder/{folder_id}/list", {"name": name})
        logger.info(f"ClickUp list created inside folder {folder_id}: {name} (id={data['id']})")
        return data

    async def create_custom_field(self, list_id: str, field_def: dict) -> dict:
        """field_def = {"name": str, "type": str, "type_config": dict}, no formato
        retornado por GET /list/{id}/field (sem os campos id/date_created/etc)."""
        payload = {
            "name": field_def["name"],
            "type": field_def["type"],
            "type_config": field_def.get("type_config", {}),
        }
        data = await self._post(f"/list/{list_id}/field", payload)
        logger.info(f"ClickUp custom field created on list {list_id}: {field_def['name']}")
        return data

    async def create_raw_task(self, list_id: str, payload: dict) -> dict:
        """Cria tarefa a partir de um payload bruto (ex.: com `parent` para subtarefas,
        campo nao suportado por ClickUpTask)."""
        data = await self._post(f"/list/{list_id}/task", payload)
        logger.info(f"ClickUp task created: {payload.get('name')} (id={data['id']})")
        return data

    async def create_task(self, list_id: str, task: ClickUpTask) -> dict:
        payload: dict = {"name": task.name}
        if task.description:
            payload["description"] = task.description
        if task.status:
            payload["status"] = task.status
        if task.due_date:
            payload["due_date"] = task.due_date
        if task.start_date:
            payload["start_date"] = task.start_date
        if task.time_estimate:
            payload["time_estimate"] = task.time_estimate
        if task.tags:
            payload["tags"] = task.tags
        if task.custom_fields:
            payload["custom_fields"] = task.custom_fields
        data = await self._post(f"/list/{list_id}/task", payload)
        logger.info(f"ClickUp task created: {task.name} (id={data['id']})")
        return data

    async def update_task(self, task_id: str, task: ClickUpTask) -> dict:
        payload: dict = {}
        if task.name:
            payload["name"] = task.name
        if task.description is not None:
            payload["description"] = task.description
        if task.status:
            payload["status"] = task.status
        if task.due_date is not None:
            payload["due_date"] = task.due_date
        if task.start_date is not None:
            payload["start_date"] = task.start_date
        if task.time_estimate is not None:
            payload["time_estimate"] = task.time_estimate
        data = await self._put(f"/task/{task_id}", payload)
        logger.info(f"ClickUp task updated: {task_id}")
        return data

    async def set_custom_field(
        self, task_id: str, field_id: str, value: object, value_options: dict | None = None
    ) -> dict:
        """`value_options={"time": True}` é obrigatório em campos de data que guardam
        hora — sem ele o ClickUp trunca o valor para a meia-noite do fuso do workspace."""
        payload: dict = {"value": value}
        if value_options:
            payload["value_options"] = value_options
        return await self._post(f"/task/{task_id}/field/{field_id}", payload)

    async def delete_task(self, task_id: str) -> None:
        await self._delete(f"/task/{task_id}")
        logger.info(f"ClickUp task deleted: {task_id}")

    async def create_webhook(self, space_id: str, endpoint_url: str, events: list[str]) -> dict:
        payload = {
            "endpoint": endpoint_url,
            "events": events,
            "space_id": space_id,
        }
        data = await self._post(f"/team/{settings.clickup_team_id}/webhook", payload)
        logger.info(f"ClickUp webhook created for space {space_id}")
        return data

    # ─── Autorizações de serviço ─────────────────────────────────────────────

    async def create_space(self, team_id: str, name: str) -> dict:
        """Cria um Space. A API não permite definir statuses customizados —
        eles precisam ser configurados manualmente na UI depois."""
        payload = {
            "name": name,
            "multiple_assignees": True,
            "features": {
                "due_dates": {"enabled": True},
                "tags": {"enabled": True},
                "custom_fields": {"enabled": True},
                "time_tracking": {"enabled": False},
                "time_estimates": {"enabled": False},
                "checklists": {"enabled": True},
            },
        }
        data = await self._post(f"/team/{team_id}/space", payload)
        logger.info(f"ClickUp space created: {name} (id={data['id']})")
        return data

    async def get_list_fields(self, list_id: str) -> list[dict]:
        data = await self._get(f"/list/{list_id}/field")
        return data.get("fields", [])

    async def get_list(self, list_id: str) -> dict:
        return await self._get(f"/list/{list_id}")

    async def set_task_status(self, task_id: str, status: str) -> dict:
        """Atualiza apenas o status da tarefa (PUT enxuto, sem tocar em outros campos)."""
        data = await self._put(f"/task/{task_id}", {"status": status})
        logger.info(f"ClickUp task {task_id} status → {status}")
        return data

    async def set_task_name(self, task_id: str, name: str) -> dict:
        """PUT enxuto só com o nome — não toca em status nem em datas."""
        return await self._put(f"/task/{task_id}", {"name": name})

    async def create_comment(self, task_id: str, comment_text: str, notify_all: bool = True) -> dict:
        payload = {"comment_text": comment_text, "notify_all": notify_all}
        return await self._post(f"/task/{task_id}/comment", payload)
