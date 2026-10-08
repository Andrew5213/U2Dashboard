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


class DependencyRef(BaseModel):
    """Tarefa do outro lado de uma dependência. `parent_name` desempata nomes
    repetidos (há duas "Cura do Concreto" na mesma lista)."""
    task_id: str
    name: str
    parent_name: str | None = None
    status: str | None = None
    status_type: str | None = None
    status_color: str | None = None
    start_date: datetime | None = None
    due_date: datetime | None = None
    progress_pct: float | None = None


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
    # Cronograma de obra — nulos fora das listas geridas pelo motor
    progress_pct: float | None = None
    duration_days: float | None = None
    calendar_type: str | None = None
    # De que tarefas esta depende. Num grupo, são as dependências das tarefas dele
    # que apontam para fora do grupo.
    depends_on: list[DependencyRef] = []


class TaskDetail(TaskSummary):
    description: str | None = None
    tags: list[str] = []
    date_created: datetime | None = None
    date_updated: datetime | None = None
    subtasks: list[TaskSummary] = []
    # Do topo até o pai direto: [{task_id, name}] — a tarefa pode estar no 3º nível
    ancestors: list[dict[str, str]] = []
    # Tarefas que esperam por esta (o inverso de depends_on)
    blocks: list[DependencyRef] = []


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
