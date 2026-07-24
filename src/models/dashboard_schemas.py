from datetime import datetime
from typing import Any
from pydantic import BaseModel


class OverviewKPIs(BaseModel):
    total_tasks: int
    completed_tasks: int
    completion_rate: float
    overdue_tasks: int
    tasks_without_due_date: int
    total_folders: int
    total_lists: int
    last_refresh_at: datetime | None = None
    status_distribution: dict[str, int] = {}


class FolderMetrics(BaseModel):
    folder_id: str
    name: str
    total_lists: int
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    completion_rate: float


class ListMetrics(BaseModel):
    list_id: str
    name: str
    folder_id: str | None = None
    total_tasks: int
    completed_tasks: int
    overdue_tasks: int
    completion_rate: float


class TaskSummary(BaseModel):
    task_id: str
    name: str
    status: str | None = None
    status_type: str | None = None
    status_color: str | None = None
    assignees: list[dict[str, str]] = []
    due_date: datetime | None = None
    start_date: datetime | None = None
    is_overdue: bool = False
    parent_task_id: str | None = None
    has_subtasks: bool = False
    observacoes: str | None = None
    url: str | None = None


class TaskDetail(TaskSummary):
    description: str | None = None
    tags: list[str] = []
    date_created: datetime | None = None
    date_updated: datetime | None = None
    subtasks: list[TaskSummary] = []


class AssigneeStats(BaseModel):
    assignee: str
    open: int
    completed: int
    overdue: int


class UpcomingTask(BaseModel):
    task_id: str
    name: str
    status: str | None = None
    status_color: str | None = None
    due_date: str | None = None
    assignees: list[str] = []
    list_name: str | None = None
    folder_name: str | None = None
    url: str | None = None


class GanttTask(BaseModel):
    task_id: str
    name: str
    start_date: datetime | None = None
    due_date: datetime | None = None
    status: str | None = None
    status_color: str | None = None
    assignees: list[str] = []
    is_overdue: bool = False
    is_done: bool = False
    url: str | None = None
    list_name: str | None = None
    is_parent: bool = False


class DashboardEnvelope(BaseModel):
    success: bool = True
    data: Any = None
    error: str | None = None
