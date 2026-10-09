import json
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from src.models.cache_models import ClickUpTaskCache
from src.models.dashboard_schemas import (
    AssigneeStats, DependencyRef, FolderMetrics, GanttTask, ListMetrics, OverviewKPIs,
    TaskDetail, TaskSummary, UpcomingTask,
)
from src.repositories.cache_repository import CacheRepository
from src.services.weights_config import build_province_evolution


def _own_dependencies(task: ClickUpTaskCache) -> list[str]:
    try:
        return list(json.loads(task.depends_on_json or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []


class _DependencyIndex:
    """Dependências de uma lista, prontas para exibir: de quem cada tarefa depende
    e quem espera por ela. Num grupo (tarefa com filhos) contam as dependências
    das tarefas de dentro que cruzam a fronteira do grupo."""

    def __init__(self, tasks: list[ClickUpTaskCache], outside: list[ClickUpTaskCache]) -> None:
        self._by_id = {t.task_id: t for t in list(tasks) + list(outside)}
        children: dict[str, list[str]] = {}
        for t in tasks:
            if t.parent_task_id:
                children.setdefault(t.parent_task_id, []).append(t.task_id)

        def members(task_id: str) -> set[str]:
            found = {task_id}
            for child in children.get(task_id, []):
                found |= members(child)
            return found

        own = {t.task_id: _own_dependencies(t) for t in tasks}
        self._depends: dict[str, list[str]] = {}
        self._blocks: dict[str, list[str]] = {}
        for t in tasks:
            inside = members(t.task_id)
            waiting = [d for m in inside for d in own.get(m, []) if d not in inside]
            released = [o for o, deps in own.items() if o not in inside and any(d in inside for d in deps)]
            self._depends[t.task_id] = list(dict.fromkeys(waiting))
            self._blocks[t.task_id] = list(dict.fromkeys(released))

    def _refs(self, ids: list[str]) -> list[DependencyRef]:
        refs = []
        for task_id in ids:
            t = self._by_id.get(task_id)
            if t is None:
                continue
            parent = self._by_id.get(t.parent_task_id) if t.parent_task_id else None
            refs.append(DependencyRef(
                task_id=t.task_id, name=t.name, parent_name=parent.name if parent else None,
                status=t.status, status_type=t.status_type, status_color=t.status_color,
                start_date=t.start_date, due_date=t.due_date, progress_pct=t.progress_pct,
            ))
        return refs

    def depends_on(self, task_id: str) -> list[DependencyRef]:
        return self._refs(self._depends.get(task_id, []))

    def blocks(self, task_id: str) -> list[DependencyRef]:
        return self._refs(self._blocks.get(task_id, []))


def _baseline_fields(task: ClickUpTaskCache, baseline: dict | None) -> dict:
    """Término na linha de base e desvio (dias) de uma tarefa de cronograma."""
    row = (baseline or {}).get(task.task_id)
    if row is None:
        return {}
    delay = (task.due_date.date() - row.finish).days if task.due_date else None
    return {"baseline_due": row.finish, "delay_days": delay}


def _task_to_summary(
    task: ClickUpTaskCache, has_subtasks: bool = False, deps: "_DependencyIndex | None" = None,
    baseline: dict | None = None,
) -> TaskSummary:
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
        progress_pct=task.progress_pct,
        duration_days=task.duration_days,
        calendar_type=task.calendar_type,
        depends_on=deps.depends_on(task.task_id) if deps else [],
        **_baseline_fields(task, baseline),
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

    async def get_list_kpis(self, list_id: str) -> ListMetrics | None:
        row = await self._repo.get_list_kpis(list_id)
        return ListMetrics(**row) if row else None

    async def get_list_tasks(self, list_id: str) -> list[TaskSummary]:
        tasks = await self._repo.get_tasks_by_list(list_id, include_subtasks=False)
        subtask_counts = await self._repo.get_subtask_count_by_parent(list_id)
        deps = await self._dependency_index(list_id)
        baseline = await self._repo.get_baseline_by_task(list_id)
        return [
            _task_to_summary(t, has_subtasks=subtask_counts.get(t.task_id, 0) > 0, deps=deps, baseline=baseline)
            for t in tasks
        ]

    async def search_tasks(self, space_id: str, query: str) -> list[dict]:
        return await self._repo.search_tasks(space_id, query)

    async def _dependency_index(self, list_id: str) -> _DependencyIndex | None:
        """None quando a lista não tem nenhuma dependência — o caso de quase todas."""
        tasks = await self._repo.get_tasks_by_list(list_id, include_subtasks=True)
        wanted = {d for t in tasks for d in _own_dependencies(t)}
        if not wanted:
            return None
        known = {t.task_id for t in tasks}
        outside = await self._repo.get_tasks_by_ids(wanted - known)
        return _DependencyIndex(tasks, outside)

    async def get_assignee_stats(self, space_id: str) -> list[AssigneeStats]:
        rows = await self._repo.get_assignee_task_stats(space_id)
        return [AssigneeStats(**r) for r in rows]

    async def get_assignee_tasks(self, space_id: str, assignee: str) -> list[dict]:
        """Tarefas de uma pessoa — o detalhe por trás da barra do gráfico de produtividade."""
        return await self._repo.get_tasks_by_assignee(space_id, assignee)

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
        subtask_counts = await self._repo.get_subtask_count_by_parent(task.list_id)
        ancestors = await self._repo.get_task_ancestors(task)
        deps = await self._dependency_index(task.list_id)
        baseline = await self._repo.get_baseline_by_task(task.list_id)
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
            progress_pct=task.progress_pct,
            duration_days=task.duration_days,
            calendar_type=task.calendar_type,
            **_baseline_fields(task, baseline),
            ancestors=[{"task_id": a.task_id, "name": a.name} for a in ancestors],
            depends_on=deps.depends_on(task.task_id) if deps else [],
            blocks=deps.blocks(task.task_id) if deps else [],
            description=task.description,
            tags=tags,
            date_created=task.date_created,
            date_updated=task.date_updated,
            subtasks=[
                _task_to_summary(s, has_subtasks=subtask_counts.get(s.task_id, 0) > 0, deps=deps, baseline=baseline)
                for s in subtasks
            ],
        )
