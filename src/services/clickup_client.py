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

    async def set_custom_field(self, task_id: str, field_id: str, value: str) -> dict:
        return await self._post(f"/task/{task_id}/field/{field_id}", {"value": value})

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
