import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.cache_models import ClickUpTaskCache
from src.models.dashboard_schemas import (
    AssigneeStats, FolderMetrics, GanttTask, ListMetrics, OverviewKPIs,
    TaskDetail, TaskSummary, UpcomingTask,
)
from src.repositories.cache_repository import CacheRepository
from src.services.weights_config import build_province_evolution


def _task_to_summary(task: ClickUpTaskCache, has_subtasks: bool = False) -> TaskSummary:
    now = datetime.utcnow()
    is_overdue = (
        task.due_date is not None
        and task.due_date < now
        and task.status_type not in ("done", "closed")
    )
    try:
        assignees = json.loads(task.assignees_json or "[]")
    except (json.JSONDecodeError, TypeError):
        assignees = []

    return TaskSummary(
        task_id=task.task_id,
        name=task.name,
        status=task.status,
        status_type=task.status_type,
        status_color=task.status_color,
        assignees=assignees,
        due_date=task.due_date,
        start_date=task.start_date,
        is_overdue=is_overdue,
        parent_task_id=task.parent_task_id,
        has_subtasks=has_subtasks,
        observacoes=task.observacoes,
        url=task.url,
    )


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self._repo = CacheRepository(db)

    async def get_overview(self, space_id: str) -> OverviewKPIs:
        kpis = await self._repo.get_overview_kpis(space_id)
        last_log = await self._repo.get_last_refresh()
        return OverviewKPIs(
            **kpis,
            last_refresh_at=last_log.created_at if last_log else None,
        )

    async def get_folders(self, space_id: str) -> list[FolderMetrics]:
        rows = await self._repo.get_folders_with_metrics(space_id)
        return [FolderMetrics(**r) for r in rows]

    async def get_folder_lists(self, folder_id: str) -> list[ListMetrics]:
        rows = await self._repo.get_lists_with_metrics(folder_id)
        return [ListMetrics(**r) for r in rows]

    async def get_list_tasks(self, list_id: str) -> list[TaskSummary]:
        tasks = await self._repo.get_tasks_by_list(list_id, include_subtasks=False)
        subtask_counts = await self._repo.get_subtask_count_by_parent(list_id)
        return [_task_to_summary(t, has_subtasks=subtask_counts.get(t.task_id, 0) > 0) for t in tasks]

    async def get_assignee_stats(self, space_id: str) -> list[AssigneeStats]:
        rows = await self._repo.get_assignee_task_stats(space_id)
        return [AssigneeStats(**r) for r in rows]

    async def get_upcoming_tasks(self, space_id: str, days: int = 30) -> list[UpcomingTask]:
        rows = await self._repo.get_upcoming_tasks(space_id, days)
        return [UpcomingTask(**r) for r in rows]

    def _to_gantt(self, task, now, list_name: str | None = None, is_parent: bool = False) -> GanttTask:
        try:
            assignees = json.loads(task.assignees_json or "[]")
        except (json.JSONDecodeError, TypeError):
            assignees = []
        is_done = task.status_type in ("done", "closed")
        is_overdue = task.due_date is not None and task.due_date < now and not is_done
        return GanttTask(
            task_id=task.task_id,
            name=task.name,
            start_date=task.start_date,
            due_date=task.due_date,
            status=task.status,
            status_color=task.status_color,
            assignees=[a.get("username", "") for a in assignees if a.get("username")],
            is_overdue=is_overdue,
            is_done=is_done,
            url=task.url,
            list_name=list_name,
            is_parent=is_parent,
        )

    async def get_gantt_tasks(self, list_id: str) -> list[GanttTask]:
        now = datetime.utcnow()
        tasks = await self._repo.get_gantt_tasks(list_id)
        return [self._to_gantt(t, now) for t in tasks]

    async def get_gantt_tasks_by_folder(self, folder_id: str) -> list[GanttTask]:
        now = datetime.utcnow()
        rows = await self._repo.get_gantt_tasks_by_folder(folder_id)
        return [self._to_gantt(row[0], now, list_name=row[1]) for row in rows]

    async def get_gantt_task_with_subtasks(self, task_id: str) -> list[GanttTask]:
        now = datetime.utcnow()
        tasks = await self._repo.get_gantt_task_subtasks(task_id)
        return [self._to_gantt(t, now, is_parent=(t.task_id == task_id)) for t in tasks]

    async def get_evolution_data(self, space_id: str) -> list[dict]:
        """
        Retorna a curva de evolução de progresso ponderado por data para cada província.
        Ordenado por current_progress descendente (ranking atual).
        """
        now = datetime.utcnow()
        folders = await self._repo.get_all_folders(space_id)
        result = []
        for folder in folders:
            lists_data = await self._repo.get_folder_tasks_for_evolution(folder.folder_id)
            evolution = build_province_evolution(lists_data, now)
            result.append({
                "folder_id": folder.folder_id,
                "name": folder.name,
                "current_progress": evolution["current_progress"],
                "start_date": evolution["start_date"],
                "points": evolution["points"],
            })
        result.sort(key=lambda x: x["current_progress"], reverse=True)
        return result

    async def get_gantt_overview(self, space_id: str) -> list[dict]:
        return await self._repo.get_gantt_overview(space_id)

    async def get_task_detail(self, task_id: str) -> TaskDetail | None:
        task, subtasks = await self._repo.get_task_with_subtasks(task_id)
        if not task:
            return None

        try:
            tags = json.loads(task.tags_json or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        try:
            assignees = json.loads(task.assignees_json or "[]")
        except (json.JSONDecodeError, TypeError):
            assignees = []

        now = datetime.utcnow()
        is_overdue = (
            task.due_date is not None
            and task.due_date < now
            and task.status_type not in ("done", "closed")
        )
        return TaskDetail(
            task_id=task.task_id,
            name=task.name,
            status=task.status,
            status_type=task.status_type,
            status_color=task.status_color,
            assignees=assignees,
            due_date=task.due_date,
            start_date=task.start_date,
            is_overdue=is_overdue,
            parent_task_id=task.parent_task_id,
            has_subtasks=len(subtasks) > 0,
            observacoes=task.observacoes,
            url=task.url,
            description=task.description,
            tags=tags,
            date_created=task.date_created,
            date_updated=task.date_updated,
            subtasks=[_task_to_summary(s) for s in subtasks],
        )
